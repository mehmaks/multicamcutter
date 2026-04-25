"""Typisierte Dataclasses für Pipeline-Daten."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class MediaSource:
    """Eine Kamera- oder Mikrofon-Quelle."""
    name: str                          # z.B. "C5835.MP4", "MIC1.WAV"
    path: str                          # Dateipfad
    source_type: str                   # "camera" oder "mic"
    clip_item: Any = None              # Resolve MediaPoolItem (None ohne Resolve)


@dataclass
class SyncOffsets:
    """Frame-Offsets relativ zur Referenz-Kamera."""
    offsets: Dict[str, int]            # {"CAM1": 0, "CAM2": -12, "MIC1": 45, ...}
    fps: float


@dataclass
class AudioData:
    """Geladene und normalisierte Audio-Daten pro Quelle."""
    audio: Dict[str, np.ndarray]       # {"CAM1": array, "CAM2": array}
    sr: int


@dataclass
class DiarizationResult:
    """Ergebnis der Sprechererkennung."""
    segments: List[Dict]               # [{speaker: "CAM1", start_s: float, end_s: float}, ...]


@dataclass
class FrameMapping:
    """Timecode-Konvertierungsdaten pro Kamera."""
    reference_frames: Dict[str, int]               # clip_name -> eingebetteter TC in Frames
    timeline_zero_video_frames: Dict[str, int]     # clip_name -> Video-Frame bei Timeline 0
    fps: float


@dataclass
class EDLEvent:
    """Ein einzelnes Schnitt-Event."""
    clip_name: str
    source_in_frame: int
    source_out_frame: int
    record_in_frame: int
    record_out_frame: int
    fps: float
    reason: str = "speaker"

    @property
    def duration_frames(self) -> int:
        return self.record_out_frame - self.record_in_frame

    @property
    def duration_s(self) -> float:
        return self.duration_frames / self.fps


@dataclass
class ReactionData:
    """Erkannte Reaktionen für eine Kamera."""
    cam_name: str
    reactions: List[Dict]              # [{frame, type, confidence, dur_s, ...}, ...]
    fps: float


@dataclass
class PauseData:
    """Erkannte Sprechpausen."""
    pauses: List[Dict]                 # [{pause_start_frame, pause_end_frame, boundary_frame, pause_dur_s}, ...]
