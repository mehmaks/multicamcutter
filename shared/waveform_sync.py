"""
Waveform-based audio synchronization.

Calculates frame offsets between audio sources using cross-correlation.
No Resolve required — works purely on audio files and embedded camera audio.

Typical use:
    offsets = sync_sources([cam1_video, cam2_video], [mic1_wav, mic2_wav])
    # Returns frame offsets relative to CAM1 for all sources.
"""

import subprocess
import tempfile
import os
import numpy as np
from pathlib import Path
from dataclasses import dataclass


SAMPLE_RATE   = 8000    # Hz — low enough for fast correlation, high enough for speech
CHUNK_SECONDS = 180     # Initial analysis window: 3 minutes
CHUNK_STEP    = 180     # Expand by 3 minutes if confidence too low
MIN_CONFIDENCE = 5.0    # Peak must be MIN_CONFIDENCE × median of correlation


# ── Audio extraction ──────────────────────────────────────────────────────────

def extract_audio(source_path: str, duration_s: float = None) -> np.ndarray:
    """
    Extracts mono audio from a video or audio file via ffmpeg.
    Returns a float32 numpy array at SAMPLE_RATE.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-vn",
    ]
    if duration_s:
        cmd += ["-t", str(duration_s)]

    cmd += ["-f", "f32le", "-"]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg fehlgeschlagen für {source_path}:\n"
            + result.stderr.decode(errors="replace")[-500:]
        )

    audio = np.frombuffer(result.stdout, dtype=np.float32)
    return audio


# ── Cross-correlation ─────────────────────────────────────────────────────────

def _correlate_offset(ref: np.ndarray, target: np.ndarray) -> tuple[int, float]:
    """
    Computes the sample offset of `target` relative to `ref` via FFT cross-correlation.
    Returns (offset_samples, confidence).
    Positive offset = target starts later than ref.
    """
    from scipy.signal import correlate

    # Normalize both signals to avoid amplitude bias
    ref    = ref    / (np.std(ref)    + 1e-9)
    target = target / (np.std(target) + 1e-9)

    corr = correlate(ref, target, method="fft")
    peak_idx    = int(np.argmax(corr))
    peak_val    = corr[peak_idx]
    confidence  = float(peak_val / (np.median(np.abs(corr)) + 1e-9))

    # Convert peak index to signed sample offset
    # correlate() output: index len(target)-1 = zero-lag
    offset_samples = peak_idx - (len(target) - 1)

    return offset_samples, confidence


def _samples_to_frames(samples: int, fps: float) -> int:
    return round(samples / SAMPLE_RATE * fps)


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    ref_label: str           # e.g. "CAM1"
    target_label: str        # e.g. "CAM2"
    offset_frames: int       # positive = target starts this many frames AFTER ref
    offset_seconds: float
    confidence: float
    analyzed_seconds: float  # how much audio was used


class SyncError(Exception):
    pass


def _sync_pair(
    ref_path: str,
    target_path: str,
    ref_label: str,
    target_label: str,
    fps: float,
    cache: dict = None,
) -> SyncResult:
    """
    Syncs one pair of audio/video sources against a reference.
    Expands analysis window in CHUNK_STEP increments until confidence is met.
    """
    duration = CHUNK_SECONDS
    max_duration = None  # will probe on first failure

    while True:
        print(f"  {ref_label} ↔ {target_label}: analysiere {duration}s ...", end=" ", flush=True)

        # Die Referenz wird gegen JEDE andere Quelle korreliert und sonst bei
        # jedem Paar neu dekodiert. Bei 4K-Material sind das je Aufruf zweistellige
        # Sekunden fuer exakt dasselbe Ergebnis. Nur die Referenz wird gehalten —
        # alle Quellen zu cachen waere bei erweitertem Fenster schnell dreistellig
        # in MB.
        if cache is not None and (ref_path, duration) in cache:
            ref_audio = cache[(ref_path, duration)]
        else:
            ref_audio = extract_audio(ref_path, duration_s=duration)
            if cache is not None:
                cache[(ref_path, duration)] = ref_audio
        target_audio = extract_audio(target_path, duration_s=duration)

        # Use the shorter of the two
        min_len = min(len(ref_audio), len(target_audio))
        ref_audio    = ref_audio[:min_len]
        target_audio = target_audio[:min_len]

        offset_samples, confidence = _correlate_offset(ref_audio, target_audio)
        offset_frames  = _samples_to_frames(offset_samples, fps)
        offset_seconds = offset_samples / SAMPLE_RATE

        print(f"Confidence: {confidence:.1f}x", end="")

        if confidence >= MIN_CONFIDENCE:
            print(f" ✓ → Offset: {offset_frames:+d} frames ({offset_seconds:+.3f}s)")
            return SyncResult(
                ref_label=ref_label,
                target_label=target_label,
                offset_frames=offset_frames,
                offset_seconds=offset_seconds,
                confidence=confidence,
                analyzed_seconds=duration,
            )

        print(f" (unter Schwellwert {MIN_CONFIDENCE}x) — erweitere Fenster")

        # Probe total duration to know when to give up
        if max_duration is None:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", ref_path],
                capture_output=True, text=True
            )
            try:
                max_duration = float(probe.stdout.strip())
            except ValueError:
                max_duration = duration * 5  # fallback

        duration += CHUNK_STEP
        if duration > max_duration:
            raise SyncError(
                f"Kein verlässlicher Sync gefunden für {ref_label} ↔ {target_label} "
                f"(max. Confidence erreicht: {confidence:.1f}x bei {max_duration:.0f}s Material).\n"
                f"Bitte manuell synchronisieren."
            )


def _probe_duration(path: str) -> float:
    """Laenge in Sekunden, 0.0 wenn nicht ermittelbar."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    try:
        return float(probe.stdout.strip())
    except ValueError:
        return 0.0


# Toleranz der Kreuzprobe. 2 Frames decken Rundung auf Frame-Raster ab
# (jede Messung rundet einmal), alles darueber ist ein echter Widerspruch.
CROSSCHECK_TOLERANCE_FRAMES = 2


def sync_sources(
    cam_paths: list[str],
    mic_paths: list[str],
    fps: float = 25.0,
    reference: str = None,
) -> dict[str, int]:
    """
    Ermittelt Sync-Offsets fuer BELIEBIG VIELE Kameras und Mikrofone.

    Rueckgabe: {label: offset_frames}, label = CAM1..CAMn / MIC1..MICm.
      CAM1 ist immer 0 (Normalisierung), positiv = startet spaeter als CAM1.

    Jede Quelle wird EINZELN gegen eine Referenz gemessen. Vorher galt:
    CAM1<->CAM2 und CAM1<->MIC1 gemessen, alle weiteren Mikrofone bekamen
    ungeprueft MIC1s Offset und Kameras ab Nr. 3 gar keinen (blieben still
    auf 0). Beides erzeugte lautlos asynchrones Material.

    Referenz ist standardmaessig das LAENGSTE MIKROFON, nicht CAM1: Mikrofone
    laufen meist durch, waehrend Kameras zwischendurch stoppen oder splitten —
    eine Quelle, die alle anderen zeitlich ueberlappt, ist die verlaesslichere
    Bezugsgroesse. Am Ende wird auf CAM1 = 0 normalisiert, damit EDL, AAF und
    `_cam_shift` unveraendert weiterrechnen.
    """
    sources: dict[str, str] = {}
    for i, path in enumerate(cam_paths, start=1):
        sources[f"CAM{i}"] = path
    for i, path in enumerate(mic_paths, start=1):
        sources[f"MIC{i}"] = path

    if "CAM1" not in sources:
        raise SyncError("Mindestens eine Kamera wird benoetigt (CAM1 fehlt).")

    # ── Referenz waehlen ──
    if reference is not None:
        if reference not in sources:
            raise SyncError(f"Referenz '{reference}' ist keine der Quellen: "
                            f"{', '.join(sources)}")
        ref_label = reference
    else:
        mic_labels = [l for l in sources if l.startswith("MIC")]
        if mic_labels:
            ref_label = max(mic_labels, key=lambda l: _probe_duration(sources[l]))
        else:
            ref_label = "CAM1"
    ref_path = sources[ref_label]

    print("Waveform-Sync gestartet")
    print(f"  Referenz: {ref_label} ({Path(ref_path).name})")
    print(f"  Quellen:  {len(sources)} ({', '.join(sources)})")
    print(f"  FPS: {fps}")
    print()

    # ── Jede Quelle einzeln gegen die Referenz ──
    rel: dict[str, int] = {ref_label: 0}
    confidences: dict[str, float] = {}
    ref_cache: dict = {}
    for label, path in sources.items():
        if label == ref_label:
            continue
        result = _sync_pair(ref_path, path, ref_label, label, fps, cache=ref_cache)
        rel[label] = result.offset_frames
        confidences[label] = result.confidence

    # ── Auf CAM1 = 0 normalisieren ──
    cam1_rel = rel["CAM1"]
    offsets = {label: value - cam1_rel for label, value in rel.items()}

    # ── Kreuzprobe: CAM1<->CAM2 unabhaengig nachmessen ──
    # Beide Kameras wurden gegen die Referenz gemessen; ihre Differenz muss zu
    # einer DIREKTEN Messung passen. Weicht sie ab, hat mindestens eine der
    # Korrelationen auf ein falsches Maximum gezeigt — das faellt sonst erst
    # im schon geschnittenen Material auf.
    if "CAM2" in sources and ref_label not in ("CAM1", "CAM2"):
        direct = _sync_pair(sources["CAM1"], sources["CAM2"], "CAM1", "CAM2", fps)
        ref_cache.clear()   # ab hier nicht mehr gebraucht
        drift = abs(direct.offset_frames - offsets["CAM2"])
        if drift > CROSSCHECK_TOLERANCE_FRAMES:
            raise SyncError(
                f"Kreuzprobe fehlgeschlagen: ueber {ref_label} ergibt CAM2 "
                f"{offsets['CAM2']:+d} Frames, direkt gemessen "
                f"{direct.offset_frames:+d} Frames "
                f"(Abweichung {drift} Frames, erlaubt {CROSSCHECK_TOLERANCE_FRAMES}).\n"
                f"Mindestens eine Korrelation hat ein falsches Maximum getroffen. "
                f"Bitte Material pruefen oder manuell synchronisieren."
            )
        print(f"  Kreuzprobe CAM1 ↔ CAM2: ✓ (Abweichung {drift} Frames)")

    print()
    print("Sync abgeschlossen:")
    for label, offset in offsets.items():
        seconds = offset / fps
        conf = confidences.get(label)
        conf_txt = f"  [Confidence {conf:.1f}x]" if conf is not None else "  [Referenz]"
        print(f"  {label}: {offset:+d} frames ({seconds:+.3f}s){conf_txt}")

    return offsets


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Waveform-basierter Audio-Sync")
    parser.add_argument("--cams", nargs="+", required=True, help="Video-Dateien, CAM1 zuerst")
    parser.add_argument("--mics", nargs="+", required=True, help="Audio-Dateien, MIC1 zuerst")
    parser.add_argument("--reference", help="Label der Referenzquelle, z.B. MIC1 (Default: laengstes Mic)")
    parser.add_argument("--fps",   type=float, default=25.0)
    parser.add_argument("--json",  action="store_true", help="Ausgabe als JSON")
    args = parser.parse_args()

    try:
        offsets = sync_sources(args.cams, args.mics, args.fps, args.reference)
        if args.json:
            print(json.dumps(offsets))
    except SyncError as e:
        print(f"\nFEHLER: {e}")
        raise SystemExit(1)
