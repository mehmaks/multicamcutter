"""
Gemeinsame ffprobe/ffmpeg-Hilfsfunktionen.

Konsolidiert Duplikate aus silence.py, takes.py, voice_leveler.py und
modules/multicam_cutter/build_aaf.py.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional


# ── Low-level probe ──────────────────────────────────────────────────────────

def _probe(path: str, *args) -> str:
    """Führt ffprobe mit den gegebenen Argumenten aus und gibt stdout zurück."""
    r = subprocess.run(
        ['ffprobe', '-v', 'error'] + list(args) + [str(path)],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


# ── Duration / FPS ───────────────────────────────────────────────────────────

def probe_duration(path: str) -> float:
    """Gibt die Dauer einer Mediendatei in Sekunden zurück (0.0 bei Fehler)."""
    raw = _probe(path, '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1')
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def probe_fps(path: str) -> float:
    """Gibt die Video-Framerate zurück (25.0 als Fallback)."""
    raw = _probe(path, '-select_streams', 'v:0',
                 '-show_entries', 'stream=r_frame_rate',
                 '-of', 'default=noprint_wrappers=1:nokey=1')
    if '/' in raw:
        n, d = raw.split('/')
        try:
            return float(n) / float(d)
        except (ValueError, ZeroDivisionError):
            return 25.0
    try:
        return float(raw)
    except ValueError:
        return 25.0


def get_audio_frames(path: str, fps: float) -> int:
    """Gibt die Audio-Dauer in Frames zurück (0 bei Fehler)."""
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_streams', str(path)],
            capture_output=True, encoding='utf-8', errors='replace',
        )
        data = json.loads(r.stdout)
        duration = float(data['streams'][0]['duration'])
        return max(1, int(duration * fps) - 1)
    except Exception:
        return 0


# ── Video-Info ───────────────────────────────────────────────────────────────

def probe_video_info(path: str) -> dict:
    """Gibt {width, height, display_aspect_ratio} als dict zurück."""
    raw = _probe(path, '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height,display_aspect_ratio',
                 '-of', 'default=noprint_wrappers=1')
    info = {}
    for line in raw.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            info[k.strip()] = v.strip()
    return info


# ── Audio-Info ───────────────────────────────────────────────────────────────

def probe_audio_channels(path: str) -> int:
    """Gibt die Anzahl der Audio-Kanäle zurück (2 als Fallback)."""
    raw = _probe(path, '-select_streams', 'a:0',
                 '-show_entries', 'stream=channels',
                 '-of', 'default=noprint_wrappers=1:nokey=1')
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 2


def probe_audio_info(path: str) -> tuple[int, int, int]:
    """Gibt (channels, sample_rate, bit_depth) zurück.

    Vollständigere Variante für AAF-Erstellung (Multicam).
    """
    raw = _probe(path, '-select_streams', 'a:0',
                 '-show_entries', 'stream=channels,sample_rate,bits_per_sample',
                 '-of', 'default=noprint_wrappers=1')
    info = {}
    for line in raw.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            info[k] = v
    channels = int(info.get('channels', '1') or '1')
    sample_rate = int(info.get('sample_rate', '48000') or '48000')
    bit_depth = int(info.get('bits_per_sample', '24') or '24') or 24
    return channels, sample_rate, bit_depth


# ── Timecode ─────────────────────────────────────────────────────────────────

def probe_embedded_tc_frames(path: str, fps: float) -> int:
    """Liest embedded TC aus Video- oder Audiodateien.

    Sucht in dieser Reihenfolge:
    1. format.tags.timecode (Video und manche Audio-Formate)
    2. stream.tags.timecode
    3. BWF BEXT time_reference (Samples ab Mitternacht → Frames)

    Dies ist die vollständigste Version (aus Multicam build_aaf.py).
    """
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_format', '-show_streams', str(path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return 0

    fmt_tags = data.get('format', {}).get('tags', {})
    stream_tags = {}
    sample_rate = None
    for stream in data.get('streams', []):
        if stream.get('codec_type') == 'audio' and sample_rate is None:
            try:
                sample_rate = int(stream.get('sample_rate', 0))
            except ValueError:
                pass
        t = stream.get('tags', {})
        if t:
            stream_tags = t

    # 1) Standard timecode-Tag
    tc = fmt_tags.get('timecode') or stream_tags.get('timecode')
    if tc:
        try:
            h, m, s, f = (int(x) for x in tc.split(':'))
            return int((h * 3600 + m * 60 + s) * fps + f)
        except Exception:
            pass

    # 2) BWF BEXT time_reference: Sample-Offset ab Mitternacht
    time_ref = fmt_tags.get('time_reference')
    if time_ref and sample_rate:
        try:
            return round(int(time_ref) / sample_rate * fps)
        except (ValueError, ZeroDivisionError):
            pass

    return 0


# ── Audio laden ──────────────────────────────────────────────────────────────

def load_audio_numpy(path: str, max_sec: int = 0):
    """Lädt Audio via ffmpeg als numpy float32 mono 16 kHz.

    Returns: (data: np.ndarray, sample_rate: int)
    """
    import numpy as np

    args = ['ffmpeg', '-y', '-i', str(path), '-ac', '1', '-ar', '16000']
    if max_sec:
        args += ['-t', str(max_sec)]
    args += ['-f', 'f32le', '-']
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr[-200:].decode(errors='replace')}")
    data = np.frombuffer(r.stdout, dtype=np.float32).copy()
    return data, 16000
