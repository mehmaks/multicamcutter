"""
Social Cutter — Zoom-Zuweisung + Reframing.

Bestimmt pro Segment:
1. Zoom-Tier basierend auf Audio-Prosodie (RMS, Sprechtempo, Keywords)
2. Pan/Tilt basierend auf MediaPipe Face Detection + Safe Area
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .types import (
    FacePosition,
    FinalSegment,
    TranscriptResult,
    ZoomParams,
    ZoomTier,
)

_log = logging.getLogger("rtk.social_cutter")

# Anrede-Keywords die auf direkte Ansprache hindeuten → engerer Zoom
_ADDRESS_KEYWORDS = {"ihr", "du", "sie", "euch", "dich", "dir", "ihnen", "dein", "euer"}


# ── Audio-Prosodie ──────────────────────────────────────────────────────────

def analyze_audio_prosody(
    audio_path: str,
    segments: list[FinalSegment],
    transcript: TranscriptResult,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> list[dict]:
    """Analysiert pro Segment: RMS-Peak, Sprechtempo, Anrede-Keywords.

    Returns:
        Liste von Dicts mit Keys:
        - rms_peak_db: Maximaler RMS-Wert in dB
        - speaking_rate_wps: Wörter pro Sekunde
        - has_address_keyword: Enthält Anrede-Pronomen
        - energy_rank: Normalisierter Energiewert 0–1
    """
    from shared.ffmpeg_utils import load_audio_numpy
    from shared.audio_analysis import rms_frames

    if progress_cb:
        progress_cb(0.1, "Audio laden …")

    data, sr = load_audio_numpy(audio_path)
    rms = rms_frames(data, sr, frame_ms=20)
    rms_times = np.arange(len(rms)) * 0.02

    results = []
    for i, seg in enumerate(segments):
        # RMS im Segment
        mask = (rms_times >= seg.source_start_s) & (rms_times <= seg.source_end_s)
        seg_rms = rms[mask]
        peak_db = float(np.max(seg_rms)) if len(seg_rms) > 0 else -60.0

        # Sprechtempo
        words_in_seg = [
            w for w in transcript.words
            if seg.source_start_s <= (w.start_s + w.end_s) / 2 <= seg.source_end_s
        ]
        wps = len(words_in_seg) / seg.duration_s if seg.duration_s > 0 else 0.0

        # Anrede-Keywords
        text_lower = seg.transcript_text.lower()
        has_address = any(kw in text_lower.split() for kw in _ADDRESS_KEYWORDS)

        results.append({
            "rms_peak_db": round(peak_db, 1),
            "speaking_rate_wps": round(wps, 1),
            "has_address_keyword": has_address,
        })

        if progress_cb:
            progress_cb(0.1 + 0.4 * (i + 1) / len(segments), f"Segment {i + 1}/{len(segments)} …")

    # Energie-Ranking normalisieren (0–1)
    if results:
        peaks = [r["rms_peak_db"] for r in results]
        rates = [r["speaking_rate_wps"] for r in results]
        p_min, p_max = min(peaks), max(peaks)
        r_min, r_max = min(rates), max(rates)
        p_range = p_max - p_min if p_max > p_min else 1.0
        r_range = r_max - r_min if r_max > r_min else 1.0

        for r in results:
            energy = (
                0.5 * (r["rms_peak_db"] - p_min) / p_range
                + 0.3 * (r["speaking_rate_wps"] - r_min) / r_range
                + 0.2 * (1.0 if r["has_address_keyword"] else 0.0)
            )
            r["energy_rank"] = round(energy, 3)

    if progress_cb:
        progress_cb(0.5, "Prosodie-Analyse fertig.")

    return results


# ── Face Detection ──────────────────────────────────────────────────────────

def _extract_frame(video_path: str, time_s: float) -> Optional[np.ndarray]:
    """Extrahiert ein einzelnes Frame aus einem Video via ffmpeg."""
    cmd = [
        "ffmpeg", "-ss", str(time_s), "-i", str(video_path),
        "-vframes", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-v", "error", "-"
    ]
    # Brauchen wir die Auflösung vorab
    probe_cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", str(video_path),
    ]
    try:
        probe = subprocess.run(probe_cmd, capture_output=True, text=True)
        w, h = [int(x) for x in probe.stdout.strip().split(",")]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            return None
        frame = np.frombuffer(result.stdout, dtype=np.uint8).reshape(h, w, 3)
        return frame
    except Exception:
        return None


def detect_face_positions(
    video_path: str,
    segments: list[FinalSegment],
    fps: float,
    source_offset_s: float = 0.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> list[FacePosition]:
    """Erkennt die Kopfposition pro Segment (am Segment-Mittelpunkt).

    Nutzt MediaPipe FaceLandmarker (gleiches Pattern wie video_reaction_analyzer_v2.4.py).

    Returns:
        Liste von FacePosition (eine pro Segment). Bei nicht-erkanntem
        Gesicht wird center_x=0.5, center_y=0.35 als Fallback verwendet.
    """
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision

    # Modell laden (gleicher Pfad wie video_reaction_analyzer)
    model_path = Path(__file__).parent.parent / "multicam_cutter" / "face_landmarker.task"
    if not model_path.exists():
        _log.warning("face_landmarker.task nicht gefunden, lade herunter …")
        import urllib.request
        url = (
            "https://storage.googleapis.com/mediapipe-models/"
            "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
        )
        urllib.request.urlretrieve(url, model_path)

    base_options = mp_tasks.BaseOptions(model_asset_path=str(model_path))
    options = mp_vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.5,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(options)

    positions: list[FacePosition] = []
    fallback = FacePosition(center_x=0.5, center_y=0.35, face_height=0.3)

    for i, seg in enumerate(segments):
        if progress_cb:
            progress_cb(0.5 + 0.5 * i / len(segments),
                        f"Face Detection {i + 1}/{len(segments)} …")

        mid_s = (seg.source_start_s + seg.source_end_s) / 2 + source_offset_s
        frame = _extract_frame(video_path, mid_s)

        if frame is None:
            positions.append(fallback)
            continue

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
        result = landmarker.detect(mp_image)

        if not result.face_landmarks:
            positions.append(fallback)
            continue

        landmarks = result.face_landmarks[0]
        # Landmark 1 = Nasenspitze (nose tip)
        nose = landmarks[1]
        # Face-Höhe: Stirn (10) bis Kinn (152)
        top_y = landmarks[10].y
        bottom_y = landmarks[152].y
        face_h = abs(bottom_y - top_y)

        positions.append(FacePosition(
            center_x=round(nose.x, 4),
            center_y=round(nose.y, 4),
            face_height=round(face_h, 4),
        ))

    landmarker.close()

    if progress_cb:
        progress_cb(1.0, "Face Detection fertig.")

    return positions


# ── Zoom-Tier-Zuweisung ─────────────────────────────────────────────────────

def assign_zoom_tiers(
    segments: list[FinalSegment],
    prosody: list[dict],
    face_positions: list[FacePosition],
    safe_area: Optional[dict] = None,
    tier_config: Optional[dict] = None,
    frame_width: int = 1080,
    frame_height: int = 1920,
) -> list[FinalSegment]:
    """Weist jedem Segment einen Zoom-Tier + Pan/Tilt zu.

    Algorithmus:
    1. Segmente nach Energie ranken
    2. Top-Quartil → TIGHT, nächstes → CLOSE, nächstes → MEDIUM, Rest → WIDE
    3. Keine zwei aufeinanderfolgenden Segmente mit gleichem Tier
    4. Pan/Tilt aus Face-Position + Zoom + Safe Area berechnen

    Args:
        safe_area: {"x": 0.05, "y": 0.12, "w": 0.90, "h": 0.76}
        tier_config: {"wide": 1.0, "medium": 1.18, "close": 1.30, "tight": 1.45}
    """
    if not segments:
        return segments

    tc = tier_config or {"wide": 1.0, "medium": 1.18, "close": 1.30, "tight": 1.45}
    sa = safe_area or {"x": 0.05, "y": 0.12, "w": 0.90, "h": 0.76}

    # Tier-Reihenfolge nach Energie
    tiers_by_energy = [ZoomTier.WIDE, ZoomTier.MEDIUM, ZoomTier.CLOSE, ZoomTier.TIGHT]

    # Quartile berechnen
    energies = [p.get("energy_rank", 0) for p in prosody]
    if energies:
        sorted_e = sorted(energies)
        q25 = sorted_e[len(sorted_e) // 4]
        q50 = sorted_e[len(sorted_e) // 2]
        q75 = sorted_e[3 * len(sorted_e) // 4]
    else:
        q25 = q50 = q75 = 0.5

    # Tier pro Segment basierend auf Energie-Quartil
    raw_tiers: list[ZoomTier] = []
    for e in energies:
        if e >= q75:
            raw_tiers.append(ZoomTier.TIGHT)
        elif e >= q50:
            raw_tiers.append(ZoomTier.CLOSE)
        elif e >= q25:
            raw_tiers.append(ZoomTier.MEDIUM)
        else:
            raw_tiers.append(ZoomTier.WIDE)

    # Keine zwei aufeinanderfolgenden gleichen Tiers
    final_tiers = list(raw_tiers)
    for i in range(1, len(final_tiers)):
        if final_tiers[i] == final_tiers[i - 1]:
            # Zum nächstbesten Tier wechseln
            current_idx = tiers_by_energy.index(final_tiers[i])
            if current_idx > 0:
                final_tiers[i] = tiers_by_energy[current_idx - 1]
            else:
                final_tiers[i] = tiers_by_energy[1]

    # Pan/Tilt berechnen und Segmente aktualisieren
    for i, seg in enumerate(segments):
        tier = final_tiers[i] if i < len(final_tiers) else ZoomTier.WIDE
        scale = tc.get(tier.value, 1.0)
        face = face_positions[i] if i < len(face_positions) else FacePosition(0.5, 0.35, 0.3)

        pan, tilt = calculate_pan_tilt(face, scale, frame_width, frame_height, sa)

        seg.zoom = ZoomParams(
            tier=tier,
            scale=scale,
            pan=round(pan, 1),
            tilt=round(tilt, 1),
            face_pos=face,
        )

    return segments


def calculate_pan_tilt(
    face: FacePosition,
    scale: float,
    frame_width: int,
    frame_height: int,
    safe_area: Optional[dict] = None,
) -> tuple[float, float]:
    """Berechnet Pan/Tilt um das Gesicht im gezoomten Frame zu zentrieren.

    Bei Zoom 1.0 ist kein Pan/Tilt nötig (Frame = Source).
    Bei Zoom >1.0 wird der sichtbare Ausschnitt kleiner — Pan/Tilt
    verschiebt den Ausschnitt so, dass der Kopf in der Safe Area
    horizontal zentriert ist.

    Die Pan/Tilt-Werte sind in Pixel-Offset vom Framezentrum.

    Returns:
        (pan, tilt) in Pixeln. Positiv = nach rechts/unten verschoben.
    """
    if scale <= 1.0:
        return 0.0, 0.0

    sa = safe_area or {"x": 0.05, "y": 0.12, "w": 0.90, "h": 0.76}

    # Safe-Area-Zentrum (normalisiert)
    safe_cx = sa["x"] + sa["w"] / 2
    safe_cy = sa["y"] + sa["h"] / 2

    # Gewünschte Position: Gesicht auf Safe-Area-Zentrum (horizontal)
    # Vertikal: Gesicht leicht über der Mitte (Regel der Drittel)
    target_x = safe_cx
    target_y = safe_cy * 0.85  # Leicht nach oben

    # Offset zwischen Gesichtsposition und Zielposition
    offset_x = (face.center_x - target_x) * frame_width
    offset_y = (face.center_y - target_y) * frame_height

    # Maximaler Pan/Tilt: Quellframe darf nicht über die Grenzen gehen
    visible_w = frame_width / scale
    visible_h = frame_height / scale
    max_pan = (frame_width - visible_w) / 2
    max_tilt = (frame_height - visible_h) / 2

    pan = max(-max_pan, min(max_pan, offset_x))
    tilt = max(-max_tilt, min(max_tilt, offset_y))

    return pan, tilt
