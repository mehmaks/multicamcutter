"""Timecode/Frame-Konvertierung — dedupliziert aus build_base_edl, add_reactions, run_from_bin."""

from __future__ import annotations

import json
import subprocess
from typing import Optional, Tuple


def timecode_to_frames(tc: str, fps: float = 25.0) -> int:
    """HH:MM:SS:FF -> Frame-Nummer."""
    parts = tc.split(':')
    total = (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * fps + int(parts[3])
    return int(total)


def frames_to_timecode(frames: int, fps: float = 25.0) -> str:
    """Frame-Nummer -> HH:MM:SS:FF."""
    if frames < 0:
        frames = 0
    total_seconds = frames / fps
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    f = int(frames % fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def get_video_timecode_with_ffprobe(video_path: str) -> Optional[str]:
    """Liest den eingebetteten Timecode aus einer Videodatei via ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', str(video_path)],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        if 'format' in data and 'tags' in data['format']:
            tc = data['format']['tags'].get('timecode')
            if tc:
                return tc
        for stream in data.get('streams', []):
            tc = stream.get('tags', {}).get('timecode')
            if tc:
                return tc
        return None
    except Exception as e:
        print(f"    ffprobe Fehler: {e}")
        return None


def get_reference_frame(video_path: str, fps: float) -> Tuple[int, Optional[str]]:
    """Referenz-Frame aus eingebettetem Timecode ermitteln.

    Returns:
        (reference_frame, timecode_string) oder (0, None) wenn kein TC vorhanden.
    """
    tc = get_video_timecode_with_ffprobe(video_path)
    if tc:
        return timecode_to_frames(tc, fps), tc
    return 0, None
