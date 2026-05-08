"""
Shared Audio-Analyse — Adaptive Schwellwertfindung via K-Means Clustering.

Genutzt von: Silence Cutter, Multicam Cutter (Pause-Trimming, Diarization,
Speaking Reactions, Cutaway-Detection).
"""

from __future__ import annotations

import numpy as np


def rms_frames(data: np.ndarray, sr: int, frame_ms: int = 20) -> np.ndarray:
    """Berechnet RMS in dB pro Frame. Filtert digitale Stille (< -75 dB)."""
    fs = int(sr * frame_ms / 1000)
    n = len(data) // fs
    if n == 0:
        return np.array([])
    frames = data[:n * fs].reshape(n, fs)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    with np.errstate(divide='ignore'):
        db = 20 * np.log10(np.where(rms > 1e-7, rms, 1e-7))
    return db[db > -75]


def suggest_threshold_kmeans(data: np.ndarray, sr: int,
                             frame_ms: int = 20) -> dict:
    """
    Adaptiver Schwellwert via K-Means 2-Cluster auf RMS-Frames.

    Findet die materialspezifische Grenze zwischen Noise-Floor und Sprache.
    Funktioniert bei jeder Sample-Rate (K-Means arbeitet auf dB-Werten).

    Args:
        data: Mono-Audio als float-Array
        sr: Sample-Rate
        frame_ms: Fensterbreite für RMS-Berechnung

    Returns:
        dict mit threshold (int, dB), noise_floor, quiet_speech,
        confidence ('hoch'/'mittel'/'niedrig'), confidence_note
    """
    db = rms_frames(data, sr, frame_ms)
    if len(db) < 30:
        raise RuntimeError("Zu wenig auswertbare Frames")

    # K-Means 2-Cluster
    c0, c1 = float(np.percentile(db, 25)), float(np.percentile(db, 75))
    for _ in range(40):
        mid = (c0 + c1) / 2
        lo = db[db < mid]
        hi = db[db >= mid]
        new_c0 = float(lo.mean()) if len(lo) > 0 else c0
        new_c1 = float(hi.mean()) if len(hi) > 0 else c1
        if abs(new_c0 - c0) < 0.05 and abs(new_c1 - c1) < 0.05:
            break
        c0, c1 = new_c0, new_c1

    boundary = (c0 + c1) / 2
    noise_frames = db[db < boundary]
    speech_frames = db[db >= boundary]

    noise_floor = float(np.median(noise_frames)) if len(noise_frames) > 0 else c0
    quiet_speech = float(np.percentile(speech_frames, 10)) if len(speech_frames) > 0 else c1
    threshold = int(round((noise_floor + quiet_speech) / 2))
    threshold = max(-60, min(-10, threshold))

    separation = c1 - c0
    std0 = float(noise_frames.std()) if len(noise_frames) > 1 else 1.0
    std1 = float(speech_frames.std()) if len(speech_frames) > 1 else 1.0
    fisher_score = separation / max((std0 + std1) / 2, 0.1)

    if fisher_score >= 2.5:
        confidence = "hoch"
        confidence_note = f"Cluster-Abstand: {separation:.0f} dB, Fisher-Score: {fisher_score:.1f}"
    elif fisher_score >= 1.5:
        confidence = "mittel"
        confidence_note = (
            f"Cluster-Abstand: {separation:.0f} dB, Fisher-Score: {fisher_score:.1f} — "
            "Ergebnis prüfen, Whisper für mehr Genauigkeit"
        )
    else:
        confidence = "niedrig"
        confidence_note = (
            f"Cluster-Abstand: {separation:.0f} dB, Fisher-Score: {fisher_score:.1f} — "
            "Verteilung unimodal oder stark überlappend, Whisper empfohlen"
        )

    return {
        "threshold": threshold,
        "noise_floor": round(noise_floor, 1),
        "quiet_speech": round(quiet_speech, 1),
        "confidence": confidence,
        "confidence_note": confidence_note,
    }
