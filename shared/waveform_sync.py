"""
Waveform-based audio synchronization.

Calculates frame offsets between audio sources using cross-correlation.
No Resolve required — works purely on audio files and embedded camera audio.

Typical use:
    offsets = sync_sources(cam1_video, cam2_video, mic1_wav)
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
) -> SyncResult:
    """
    Syncs one pair of audio/video sources against a reference.
    Expands analysis window in CHUNK_STEP increments until confidence is met.
    """
    duration = CHUNK_SECONDS
    max_duration = None  # will probe on first failure

    while True:
        print(f"  {ref_label} ↔ {target_label}: analysiere {duration}s ...", end=" ", flush=True)

        ref_audio    = extract_audio(ref_path,    duration_s=duration)
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


def sync_sources(
    cam1_path: str,
    cam2_path: str,
    mic1_path: str,
    fps: float = 25.0,
    additional_mics: list[str] = None,
) -> dict[str, int]:
    """
    Calculates sync offsets for all sources relative to CAM1.

    Sync pairs:
      CAM1 ↔ CAM2   (both use their embedded camera audio)
      CAM1 ↔ MIC1   (camera audio vs. Zoom recorder)
      All additional MICs are assumed synchronous with MIC1.

    Returns dict: {label: offset_frames_relative_to_cam1}
      CAM1 is always 0 (reference).
      Positive = starts later than CAM1.
      Negative = starts earlier than CAM1.
    """
    print("Waveform-Sync gestartet")
    print(f"  Referenz: CAM1 ({Path(cam1_path).name})")
    print(f"  FPS: {fps}")
    print()

    offsets = {"CAM1": 0}

    # CAM1 ↔ CAM2
    result_cam2 = _sync_pair(cam1_path, cam2_path, "CAM1", "CAM2", fps)
    offsets["CAM2"] = result_cam2.offset_frames

    # CAM1 ↔ MIC1
    result_mic1 = _sync_pair(cam1_path, mic1_path, "CAM1", "MIC1", fps)
    offsets["MIC1"] = result_mic1.offset_frames

    # Additional MICs: same offset as MIC1
    if additional_mics:
        for i, mic_path in enumerate(additional_mics, start=2):
            label = f"MIC{i}"
            offsets[label] = result_mic1.offset_frames
            print(f"  {label}: synchron mit MIC1 → Offset {result_mic1.offset_frames:+d} frames")

    print()
    print("Sync abgeschlossen:")
    for label, offset in offsets.items():
        seconds = offset / fps
        print(f"  {label}: {offset:+d} frames ({seconds:+.3f}s)")

    return offsets


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Waveform-basierter Audio-Sync")
    parser.add_argument("--cam1",  required=True)
    parser.add_argument("--cam2",  required=True)
    parser.add_argument("--mic1",  required=True)
    parser.add_argument("--mic2",  help="Weitere MIC-Datei (synchron mit MIC1)")
    parser.add_argument("--fps",   type=float, default=25.0)
    parser.add_argument("--json",  action="store_true", help="Ausgabe als JSON")
    args = parser.parse_args()

    additional = [args.mic2] if args.mic2 else []

    try:
        offsets = sync_sources(args.cam1, args.cam2, args.mic1, args.fps, additional)
        if args.json:
            print(json.dumps(offsets))
    except SyncError as e:
        print(f"\nFEHLER: {e}")
        raise SystemExit(1)
