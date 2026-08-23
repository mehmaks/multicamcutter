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

    Gezählt wird über die *nominale* Ganzzahl-Bildrate ``round(fps)`` (Non-Drop).
    Das hält den Round-Trip frames→TC→frames EXAKT — auch bei krummen Raten wie
    29,97, wo die frühere fraktionale Rechnung (`* 29.97`) um bis zu 1 Frame
    driftete und jeden AAF-Schnitt um einen Frame verschob. Für ganzzahlige fps
    ist ``round(fps) == fps`` → Ergebnis identisch zum bisherigen Verhalten.
    """
    parts = tc.replace(';', ':').split(':')
    h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    rate = int(round(fps))
    return (h * 3600 + m * 60 + s) * rate + f


def frames_to_timecode(frames: int, fps: float = 25.0) -> str:
    """Frame-Nummer → HH:MM:SS:FF (Non-Drop, nominale Ganzzahl-Rate).

    Negative Frame-Werte werden auf 0 geklemmt. Zur nominalen Zählung (exakter
    Round-Trip bei krummen Raten) siehe :func:`timecode_to_frames`.
    """
    if frames < 0:
        frames = 0
    rate = int(round(fps))
    f = frames % rate
    total_seconds = frames // rate
    s = total_seconds % 60
    m = (total_seconds // 60) % 60
    h = total_seconds // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def get_embedded_timecode(video_path: str) -> Optional[str]:
    """Liest den eingebetteten Start-Timecode aus einer Videodatei via ffprobe.

    Sucht zuerst in format.tags.timecode, dann in den Stream-Tags.
    Returns None wenn kein TC gefunden oder ffprobe fehlschlägt — schreibt in
    diesem Fall einen Hinweis auf stderr, damit Probleme nicht stillschweigend
    durchrutschen (siehe TC-Auflösung in run_from_bin.parse_edl).
    """
    import sys
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-print_format', 'json',
             '-show_format', '-show_streams', str(video_path)],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
        )
    except FileNotFoundError:
        print(f"⚠️  ffprobe nicht im PATH (TC-Read für {video_path} übersprungen)",
              file=sys.stderr)
        return None
    except Exception as e:
        print(f"⚠️  ffprobe-Aufruf fehlgeschlagen für {video_path}: {e!r}",
              file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"⚠️  ffprobe returncode={result.returncode} für {video_path}: "
              f"{result.stderr.strip()[:300]}", file=sys.stderr)
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"⚠️  ffprobe-Output für {video_path} nicht parsebar: {e!r}",
              file=sys.stderr)
        return None

    tc = data.get('format', {}).get('tags', {}).get('timecode')
    if tc:
        return tc
    for stream in data.get('streams', []):
        tc = stream.get('tags', {}).get('timecode')
        if tc:
            return tc
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
