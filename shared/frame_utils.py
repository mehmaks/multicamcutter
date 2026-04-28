"""
Kanonische Timecode/Frame-Konvertierung und ffprobe-TC-Extraktion.

Einzige Quelle für TC↔Frame-Umrechnung im gesamten Projekt.
Alle anderen Dateien importieren von hier.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def timecode_to_frames(tc: str, fps: float = 25.0) -> int:
    """HH:MM:SS:FF → Frame-Nummer.

    Akzeptiert auch Semikolon-Trenner (Drop-Frame-Notation).
    """
    parts = tc.replace(';', ':').split(':')
    h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return int((h * 3600 + m * 60 + s) * fps + f)


def frames_to_timecode(frames: int, fps: float = 25.0) -> str:
    """Frame-Nummer → HH:MM:SS:FF.

    Negative Frame-Werte werden auf 0 geklemmt.
    """
    if frames < 0:
        frames = 0
    total_seconds = frames / fps
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    f = int(frames % fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def get_embedded_timecode(video_path: str) -> Optional[str]:
    """Liest den eingebetteten Start-Timecode aus einer Videodatei via ffprobe.

    Sucht zuerst in format.tags.timecode, dann in den Stream-Tags.
    Returns None wenn kein TC gefunden oder ffprobe fehlschlägt.
    """
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', str(video_path)],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        tc = data.get('format', {}).get('tags', {}).get('timecode')
        if tc:
            return tc
        for stream in data.get('streams', []):
            tc = stream.get('tags', {}).get('timecode')
            if tc:
                return tc
        return None
    except Exception:
        return None


def get_reference_frame(video_path: str, fps: float) -> Tuple[int, Optional[str]]:
    """Referenz-Frame aus eingebettetem Timecode ermitteln.

    Returns:
        (reference_frame, timecode_string) — oder (0, None) wenn kein TC vorhanden.
    """
    tc = get_embedded_timecode(video_path)
    if tc:
        return timecode_to_frames(tc, fps), tc
    return 0, None
