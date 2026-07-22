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
    start_duration: float = None,
) -> SyncResult:
    """
    Synchronisiert eine Quelle gegen eine Referenz.

    ASYMMETRISCHE FENSTER: Das ZIEL liefert den Inhalt zum Wiedererkennen —
    3 Minuten reichen dafuer. Die REFERENZ bestimmt den durchsuchbaren
    Versatzbereich, denn correlate(mode="full") findet nur Lags bis zu ihrer
    Laenge. Beide gleich kurz zu halten war der Fehler: ein Kamera-Fragment,
    das 30 min in die Aufnahme hinein beginnt, ist mit einer 3-Minuten-Referenz
    nicht auffindbar — die Fenster haben nicht einmal gemeinsamen Inhalt.

    Erweitert wird bis TRUST_CONFIDENCE, nicht bis MIN_CONFIDENCE: 14x ist
    Rauschen, das die 5.0 muehelos passiert. Ist das Referenzmaterial
    erschoepft, wird das BESTE gefundene Ergebnis zurueckgegeben (sofern
    ueberhaupt ueber MIN_CONFIDENCE) — die Gegenpruefung in sync_sources
    entscheidet dann, ob es tragfaehig ist.
    """
    target_duration = start_duration or CHUNK_SECONDS
    ref_duration    = target_duration
    max_ref         = _probe_duration(ref_path) or target_duration * 8
    best            = None

    while True:
        print(f"  {ref_label} ↔ {target_label}: {target_duration:.0f}s gegen "
              f"{ref_duration:.0f}s Referenz ...", end=" ", flush=True)

        if cache is not None and (ref_path, ref_duration) in cache:
            ref_audio = cache[(ref_path, ref_duration)]
        else:
            ref_audio = extract_audio(ref_path, duration_s=ref_duration)
            if cache is not None:
                cache[(ref_path, ref_duration)] = ref_audio
        target_audio = extract_audio(target_path, duration_s=target_duration)

        offset_samples, confidence = _correlate_offset(ref_audio, target_audio)
        result = SyncResult(
            ref_label=ref_label,
            target_label=target_label,
            offset_frames=_samples_to_frames(offset_samples, fps),
            offset_seconds=offset_samples / SAMPLE_RATE,
            confidence=confidence,
            analyzed_seconds=ref_duration,
        )
        if best is None or confidence > best.confidence:
            best = result

        if confidence >= TRUST_CONFIDENCE:
            print(f"Confidence: {confidence:.1f}x ✓ → Offset: "
                  f"{result.offset_frames:+d} frames ({result.offset_seconds:+.3f}s)")
            return result

        if ref_duration >= max_ref:
            if best.confidence >= MIN_CONFIDENCE:
                print(f"Confidence: {confidence:.1f}x (bestes: {best.confidence:.1f}x) "
                      f"→ Offset: {best.offset_frames:+d} frames — wird gegengeprueft")
                return best
            raise SyncError(
                f"Kein verlaesslicher Sync fuer {ref_label} ↔ {target_label} "
                f"(beste Confidence {best.confidence:.1f}x bei {max_ref:.0f}s "
                f"Referenzmaterial). Bitte manuell synchronisieren."
            )

        print(f"Confidence: {confidence:.1f}x — erweitere Referenzfenster")
        # Verdoppeln statt linear erhoehen: der gesuchte Versatz kann Stunden
        # betragen, in 3-Minuten-Schritten dauerte das ewig.
        ref_duration = min(ref_duration * 2, max_ref)


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

# Faktor fuers Nachmessen der schwaechsten Quelle bei uneiniger Kreuzprobe.
# 4x180s = 12 min deckt auch lange Vorlaeufe ab, ohne den Normalfall zu bremsen
# (es greift nur nach einem Widerspruch).
RETRY_WINDOW_FACTOR = 4

# Untergrenze fuer eine sinnvolle Korrelation. Bewusst niedrig: eine kurze
# Quelle laesst sich seit dem Wegfall der min_len-Kuerzung sauber einordnen,
# solange die REFERENZ lang genug ist. Kuerzer als das ist es Rauschen.
MIN_SOURCE_SECONDS = 10.0

# Ab dieser Confidence gilt eine EINZELMESSUNG als belastbar. Darunter wird die
# Quelle ueber einen zweiten Weg gegengeprueft.
#
# MIN_CONFIDENCE (5.0) ist die Schwelle zum Weitersuchen, nicht zum Vertrauen:
# gemessen wurde eine Totale, die bei JEDEM Fenster ~12x lieferte und dabei
# Offsets zwischen -478 und +111 Frames -- reines Rauschen, das die 5.0 muehelos
# passiert. Eine gleichbleibend niedrige Confidence bei wachsendem Fenster ist
# das Erkennungsmerkmal: es gibt keinen echten Korrelationsgipfel.
TRUST_CONFIDENCE = 50.0


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

    # ── Quellen auf plausible Laenge pruefen ──
    # Die Korrelation braucht ein Fenster von CHUNK_SECONDS. Ist eine Quelle
    # kuerzer, wird intern auf ihre Laenge gekappt (min_len in _sync_pair) und
    # das Ergebnis ist bestenfalls Glueckssache — mehr Material anzufordern hilft
    # dann nicht, weil es keines gibt.
    #
    # Aufgefallen an einer abgebrochenen FPS-Konvertierung, die als 94-Sekunden-
    # Fragment liegen blieb (Original: 99 min) und beim Scan als vollwertige
    # Kamera uebernommen wurde. Der Konverter prueft seine Ausgabe inzwischen
    # selbst, aber eine unvollstaendige Datei kann auch anders entstehen —
    # abgebrochener Kopiervorgang, halb geladene Cloud-Datei, Altbestand.
    durations = {label: _probe_duration(path) for label, path in sources.items()}
    longest = max(durations.values()) if durations else 0.0
    # Hart abbrechen nur, wenn eine Korrelation sinnlos waere. Alles darueber
    # kann die Korrelation seit dem Wegfall der min_len-Kuerzung selbst
    # bewaeltigen — und eine Kamera, die nur zeitweise lief, ist legitim.
    unusable = {l: d for l, d in durations.items() if 0 < d < MIN_SOURCE_SECONDS}
    if unusable:
        lines = "\n".join(
            f"    {l}: {d:.1f} s  ({Path(sources[l]).name})"
            for l, d in sorted(unusable.items())
        )
        raise SyncError(
            f"Quelle(n) zu kurz fuer eine Korrelation (unter {MIN_SOURCE_SECONDS:.0f} s):\n{lines}\n"
            f"    laengste Quelle: {longest / 60:.1f} min"
        )
    # Deutlich kuerzer als der Rest ist verdaechtig, kann aber stimmen (Kamera
    # lief nur zeitweise). Deshalb nur ein Hinweis, kein Abbruch.
    for label, d in sorted(durations.items()):
        if longest and d < longest * 0.5:
            print(f"  ⚠ {label} ist mit {d / 60:.1f} min deutlich kuerzer als die "
                  f"laengste Quelle ({longest / 60:.1f} min). Der Sync kommt damit "
                  f"zurecht — falls die Datei aber unvollstaendig ist (abgebrochene "
                  f"Konvertierung o. ae.), fehlt sie spaeter im Schnitt.")

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

    def _name(label: str) -> str:
        return Path(sources[label]).name

    print("Waveform-Sync gestartet")
    print(f"  Referenz: {ref_label} ({_name(ref_label)})")
    print(f"  Quellen ({len(sources)}) — welche Datei welches Label ist:")
    for _label in sources:
        print(f"    {_label} = {_name(_label)}")
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
            # Nicht sofort aufgeben. Die Confidence zeigt, WELCHE Messung
            # verdaechtig ist — die schwaechste. Ursache ist fast immer zu wenig
            # ueberlappendes Material (Rekorder liefen vor den Kameras), und
            # dagegen hilft schlicht ein groesseres Fenster.
            suspect = min(confidences, key=confidences.get)
            print(f"  ⚠ Kreuzprobe uneinig ({drift} Frames Abweichung).")
            print(f"    Schwaechste Messung: {ref_label} ↔ {suspect} "
                  f"({confidences[suspect]:.1f}x) — messe mit mehr Material nach...")
            retry = _sync_pair(ref_path, sources[suspect], ref_label, suspect, fps,
                               cache=ref_cache,
                               start_duration=CHUNK_SECONDS * RETRY_WINDOW_FACTOR)
            if retry.confidence > confidences[suspect]:
                rel[suspect] = retry.offset_frames
                confidences[suspect] = retry.confidence
                cam1_rel = rel["CAM1"]
                offsets = {l: v - cam1_rel for l, v in rel.items()}
                drift = abs(direct.offset_frames - offsets["CAM2"])
                if drift <= CROSSCHECK_TOLERANCE_FRAMES:
                    print(f"    ✓ behoben — {suspect} jetzt {retry.offset_frames:+d} "
                          f"Frames bei {retry.confidence:.1f}x")

        if drift > CROSSCHECK_TOLERANCE_FRAMES:
            raise SyncError(
                f"Kreuzprobe fehlgeschlagen: ueber {ref_label} ({_name(ref_label)}) "
                f"ergibt CAM2 ({_name('CAM2')}) {offsets['CAM2']:+d} Frames, direkt "
                f"gemessen {direct.offset_frames:+d} Frames "
                f"(Abweichung {drift} Frames, erlaubt {CROSSCHECK_TOLERANCE_FRAMES}).\n"
                f"Mindestens eine Korrelation hat ein falsches Maximum getroffen; "
                f"Nachmessen mit mehr Material hat es nicht aufgeloest.\n"
                f"Haeufigste Ursache: eine Quelle hat einen langen Vorlauf, sodass "
                f"die Analysefenster kaum gemeinsames Material enthalten."
            )
        print(f"  Kreuzprobe CAM1 ↔ CAM2: ✓ (Abweichung {drift} Frames)")

    # ── Schwache Messungen ueber einen zweiten Weg gegenpruefen ──
    # Die Kreuzprobe oben deckt nur CAM2 ab. Jede andere Quelle koennte mit
    # duerftiger Confidence einen Zufallswert liefern, ohne dass es auffaellt —
    # und Offsets sind genau die Sorte Zahl, die man dem fertigen Schnitt nicht
    # mehr ansieht.
    unreliable = []
    for label, conf in sorted(confidences.items(), key=lambda kv: kv[1]):
        if conf >= TRUST_CONFIDENCE:
            continue
        # Als Pruefer die sicherste ANDERE Quelle nehmen.
        others = [l for l in confidences if l != label]
        if not others:
            continue
        verifier = max(others, key=lambda l: confidences[l])
        check = _sync_pair(sources[verifier], sources[label], verifier, label, fps)
        via_verifier = rel[verifier] + check.offset_frames
        spread = abs(via_verifier - rel[label])
        if spread > CROSSCHECK_TOLERANCE_FRAMES:
            unreliable.append((label, conf, rel[label] - rel["CAM1"],
                               via_verifier - rel["CAM1"], verifier, spread))
        else:
            print(f"  {label} gegengeprueft ueber {verifier}: ✓ "
                  f"(Abweichung {spread} Frames)")

    if unreliable:
        lines = "\n".join(
            f"    {l} ({_name(l)}): ueber {ref_label} {a:+d} Frames, "
            f"ueber {v} {b:+d} Frames (Abweichung {sp}, Confidence nur {c:.1f}x)"
            for l, c, a, b, v, sp in unreliable
        )
        # Die betroffenen DATEIEN klar benennen: der Nutzer kennt nur seine
        # Dateinamen, nicht die internen Labels (MIC3). Ohne das weiss er nicht,
        # welches seiner Files gemeint ist.
        files = ", ".join(f'„{_name(l)}"' for l, *_ in unreliable)
        raise SyncError(
            f"Diese Quelle(n) lassen sich nicht verlaesslich einordnen:\n{lines}\n"
            f"Zwei unabhaengige Wege kommen zu verschiedenen Ergebnissen, und die "
            f"Confidence liegt unter {TRUST_CONFIDENCE:.0f}x — die Korrelation findet "
            f"keinen echten Gipfel, sondern Rauschen.\n"
            f"Wenn die Confidence bei WACHSENDEM Referenzfenster flach bleibt, lag der "
            f"wahre Versatz bisher ausserhalb des durchsuchten Bereichs — das faengt die "
            f"Fenster-Erweiterung inzwischen ab. Bleibt es auch danach uneinig, stammt "
            f"der Ton der Quelle vermutlich aus einer ganz anderen Position (weit "
            f"entfernte Totale, Wind).\n"
            f"Betroffene Datei(en): {files}. Diese Datei manuell synchronisieren "
            f"oder im Schritt Personen/Kameras abwaehlen."
        )

    print()
    print("Sync abgeschlossen:")
    for label, offset in offsets.items():
        seconds = offset / fps
        conf = confidences.get(label)
        conf_txt = f"  [Confidence {conf:.1f}x]" if conf is not None else "  [Referenz]"
        print(f"  {label} ({_name(label)}): {offset:+d} frames ({seconds:+.3f}s){conf_txt}")

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
