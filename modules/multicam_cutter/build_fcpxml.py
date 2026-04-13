#!/usr/bin/env python3
"""
Generiert eine FCPXML 1.9 Timeline aus final.edl + synchronisierten Mediendateien.

Ausgabe:
  V1   — Videoschnitte aus der EDL
  A1   — mic_paths[0] kontinuierlich, mit Sync-Offset
  A2   — mic_paths[1] kontinuierlich, mit Sync-Offset (wenn vorhanden)

Kamera-Audio wird ausgeschlossen (hasAudio="0" auf Camera-Assets).
FCPXML kann direkt in DaVinci Resolve, Premiere Pro und Final Cut Pro importiert werden.
"""

import json
import re
import subprocess
import uuid
from pathlib import Path


# ── Timing helpers ────────────────────────────────────────────────────────────

# FCPXML rational frame durations für bekannte Framerates
_FPS_RATIONALS = {
    23.976: (1001, 24000),
    24.0:   (1, 24),
    25.0:   (1, 25),
    29.97:  (1001, 30000),
    30.0:   (1, 30),
    50.0:   (1, 50),
    59.94:  (1001, 60000),
    60.0:   (1, 60),
}


def _fps_rational(fps: float) -> tuple:
    for known, (p, q) in _FPS_RATIONALS.items():
        if abs(fps - known) < 0.01:
            return p, q
    return 1, int(round(fps))


def _frame_duration_str(fps: float) -> str:
    p, q = _fps_rational(fps)
    return f"{p}/{q}s"


def _frames_to_time(frames: int, fps: float) -> str:
    """Wandelt Frame-Anzahl in FCPXML Rational-Zeit-String um."""
    p, q = _fps_rational(fps)
    return f"{frames * p}/{q}s"


def _tc_to_frames(tc: str, fps: float) -> int:
    h, m, s, f = (int(x) for x in tc.split(':'))
    return int((h * 3600 + m * 60 + s) * fps + f)


# ── ffprobe helpers ───────────────────────────────────────────────────────────

def _probe_duration_frames(path: str, fps: float) -> int:
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        capture_output=True, text=True,
    )
    try:
        return int(float(r.stdout.strip()) * fps)
    except (ValueError, ZeroDivisionError):
        return 0


def _probe_video_size(path: str) -> tuple:
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height',
         '-of', 'default=noprint_wrappers=1', path],
        capture_output=True, text=True,
    )
    w, h = 1920, 1080
    for line in r.stdout.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            if k == 'width':  w = int(v)
            if k == 'height': h = int(v)
    return w, h


def _probe_audio_channels(path: str) -> int:
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
         '-show_entries', 'stream=channels',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        capture_output=True, text=True,
    )
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 1


def _probe_embedded_tc_frames(path: str, fps: float) -> int:
    """Liefert den embedded Timecode eines Videos als Frame-Zahl (oder 0)."""
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_format', '-show_streams', path],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return 0
    tc = data.get('format', {}).get('tags', {}).get('timecode')
    if not tc:
        for stream in data.get('streams', []):
            tc = stream.get('tags', {}).get('timecode')
            if tc:
                break
    if tc:
        try:
            return _tc_to_frames(tc, fps)
        except Exception:
            pass
    return 0


# ── EDL parser (ohne Resolve-Objekte) ────────────────────────────────────────

def _parse_edl(edl_path: Path, cam_paths: list, fps: float) -> list:
    """
    Parst final.edl und liefert Cut-Events:
      [{'cam_index': 0|1, 'source_in': int, 'source_out': int, 'reason': str}, ...]

    source_in/out sind clip-relative Frames (embedded TC bereits subtrahiert).
    cam_index 0 = cam_paths[0], 1 = cam_paths[1].

    Timecode-Kodierung in der EDL: source_TC = embedded_TC + clip_video_frame
    → clip_video_frame = tc_to_frames(source_TC) - embedded_TC_frames
    """
    text = edl_path.read_text()

    cam_tc    = [_probe_embedded_tc_frames(p, fps) for p in cam_paths]
    cam_stems = [Path(p).stem.lower() for p in cam_paths]
    cam_names = [Path(p).name.lower() for p in cam_paths]

    event_re = re.compile(
        r'^\d+\s+\S+\s+\S+\s+C\s+'
        r'(\d{2}:\d{2}:\d{2}:\d{2})\s+'   # source in
        r'(\d{2}:\d{2}:\d{2}:\d{2})\s+'   # source out
        r'(\d{2}:\d{2}:\d{2}:\d{2})\s+'   # record in
        r'(\d{2}:\d{2}:\d{2}:\d{2})',      # record out
        re.MULTILINE,
    )
    clip_re = re.compile(r'^\*\s*FROM CLIP NAME:\s*(.+)', re.MULTILINE)

    events_raw = list(event_re.finditer(text))
    clip_names = list(clip_re.finditer(text))

    colors = []
    colors_path = edl_path.with_suffix('.colors.json')
    if colors_path.exists():
        try:
            colors = json.loads(colors_path.read_text())
        except Exception:
            pass

    result = []
    for i, (ev, cn) in enumerate(zip(events_raw, clip_names)):
        clip_name = cn.group(1).strip()
        clip_stem = Path(clip_name).stem.lower()
        clip_lo   = clip_name.lower()

        cam_idx = None
        for j, (stem, name) in enumerate(zip(cam_stems, cam_names)):
            if clip_lo == name or clip_stem == stem:
                cam_idx = j
                break

        if cam_idx is None:
            print(f"  Warnung FCPXML: Clip '{clip_name}' nicht erkannt — überspringe")
            continue

        ref      = cam_tc[cam_idx]
        src_in   = _tc_to_frames(ev.group(1), fps) - ref
        src_out  = _tc_to_frames(ev.group(2), fps) - ref

        if src_in < 0 or src_out <= src_in:
            continue

        reason = colors[i].get('reason', 'speaker') if i < len(colors) else 'speaker'
        result.append({
            'cam_index':  cam_idx,
            'source_in':  src_in,
            'source_out': src_out,
            'reason':     reason,
        })

    return result


# ── XML helpers ───────────────────────────────────────────────────────────────

def _x(s: str) -> str:
    """Minimales XML-Attribut-Escaping."""
    return (s.replace('&', '&amp;')
             .replace('"', '&quot;')
             .replace('<', '&lt;')
             .replace('>', '&gt;'))


# ── Haupt-Generator ───────────────────────────────────────────────────────────

def build_fcpxml(
    cam_paths: list,
    mic_paths: list,
    offsets: dict,
    edl_path: Path,
    fps: float,
    output: Path,
) -> Path:
    """
    Erzeugt eine FCPXML 1.9 Timeline aus final.edl + synchronisierten Medien.

    V1:  Videoschnitte aus edl_path (Kamera-Audio ausgeschlossen)
    A1:  mic_paths[0], synchronisiert über offsets['MIC1']
    A2:  mic_paths[1], synchronisiert über offsets['MIC2']  (wenn vorhanden)

    offsets: {'CAM1': 0, 'CAM2': N, 'MIC1': N, 'MIC2': N}
             Werte = Frame-Offset relativ zu CAM1-Start.
             Positiv = Quelle startet N Frames nach CAM1.
    """
    print("\nErstelle FCPXML...")

    # ── EDL parsen ────────────────────────────────────────────────────────────
    events = _parse_edl(edl_path, cam_paths, fps)
    if not events:
        raise RuntimeError("Keine Cut-Events in EDL — FCPXML-Generierung abgebrochen")
    print(f"  {len(events)} Cut-Events")

    def ft(frames):
        return _frames_to_time(int(frames), fps)

    # ── Medien-Metadaten ──────────────────────────────────────────────────────
    cam1_path, cam2_path = cam_paths[0], cam_paths[1]
    w, h     = _probe_video_size(cam1_path)
    cam1_dur = _probe_duration_frames(cam1_path, fps)
    cam2_dur = _probe_duration_frames(cam2_path, fps)

    fps_int  = int(round(fps))
    fps_name = f"FFVideoFormat{h}p{fps_int}"

    # Embedded Timecodes der Kameras (Resolve braucht diese als asset.start)
    cam_tc = [
        _probe_embedded_tc_frames(cam1_path, fps),
        _probe_embedded_tc_frames(cam2_path, fps),
    ]
    cam_durs = [cam1_dur, cam2_dur]

    # MIC-Dateien (max. 2)
    mics = mic_paths[:2]
    mic_durs    = [_probe_duration_frames(str(p), fps) for p in mics]
    mic_chs     = [_probe_audio_channels(str(p))       for p in mics]
    mic_offsets = [offsets.get(f'MIC{i + 1}', 0)      for i in range(len(mics))]

    # Kamera-Offsets (CAM1 = 0, CAM2 = N)
    cam_offs = [offsets.get('CAM1', 0), offsets.get('CAM2', 0)]

    # Gesamtlänge der Record-Timeline
    total_frames = sum(e['source_out'] - e['source_in'] for e in events)

    # UUIDs (deterministisch aus absolutem Pfad)
    def uid(p):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, str(Path(p).resolve())))

    def furi(p):
        return _x(Path(p).resolve().as_uri())

    # ── FCPXML-Text aufbauen ─────────────────────────────────────────────────
    # Struktur orientiert sich am Resolve-Export-Format:
    # - asset.start = embedded TC der Quelldatei
    # - <media-rep> statt src= auf dem Asset
    # - clip.start = embedded_TC + src_in
    # - <video> child-Element in jedem Clip
    # - MIC-Audio als <asset-clip> mit positivem lane (2, 3)
    L = []
    A = L.append

    A('<?xml version="1.0" encoding="UTF-8"?>')
    A('<!DOCTYPE fcpxml>')
    A('<fcpxml version="1.9">')
    A('  <resources>')
    A(f'    <format id="r1" name="{fps_name}"'
      f' frameDuration="{_frame_duration_str(fps)}" width="{w}" height="{h}"/>')

    # Camera-Assets (start = embedded TC, <media-rep> child)
    for idx, (cp, dur, tc) in enumerate(zip(cam_paths, cam_durs, cam_tc)):
        rid = f"r{2 + idx}"
        A(f'    <asset id="{rid}" name="{_x(Path(cp).name)}" format="r1"')
        A(f'           start="{ft(tc)}" duration="{ft(dur)}"')
        A(f'           hasVideo="1" hasAudio="1" audioSources="1" audioChannels="2">')
        A(f'        <media-rep kind="original-media" src="{furi(cp)}"/>')
        A( '    </asset>')

    # MIC-Assets (WAV ohne embedded TC → start="0s")
    for idx, (mp, dur, ch) in enumerate(zip(mics, mic_durs, mic_chs)):
        rid = f"r{4 + idx}"
        A(f'    <asset id="{rid}" name="{_x(Path(mp).name)}"')
        A(f'           start="0s" duration="{ft(dur)}"')
        A(f'           hasVideo="0" hasAudio="1" audioSources="1" audioChannels="{ch}">')
        A(f'        <media-rep kind="original-media" src="{furi(mp)}"/>')
        A( '    </asset>')

    A('  </resources>')
    A('  <library>')
    A(f'    <event name="{_x(output.stem)}">')
    A(f'      <project name="{_x(output.stem)}">')
    A(f'        <sequence format="r1" duration="{ft(total_frames)}"'
      f' tcStart="0s" tcFormat="NDF">')
    A('          <spine>')

    # MIC-Startframe für kontinuierlichen Audio-Clip
    ev0        = events[0]
    abs_start0 = ev0['source_in'] + cam_offs[ev0['cam_index']]
    # clip.start des ersten Clips = embedded_TC[cam_idx] + src_in
    first_clip_start = cam_tc[ev0['cam_index']] + ev0['source_in']

    record_cursor = 0
    for ev_idx, ev in enumerate(events):
        cam_idx   = ev['cam_index']
        src_in    = ev['source_in']
        dur       = ev['source_out'] - ev['source_in']
        cam_ref   = f"r{2 + cam_idx}"
        cam_name  = _x(Path(cam_paths[cam_idx]).stem)
        tc        = cam_tc[cam_idx]
        cam_dur   = cam_durs[cam_idx]
        clip_start = tc + src_in  # embedded TC + source in-point

        if ev_idx == 0:
            A(f'            <clip start="{ft(clip_start)}" enabled="1"'
              f' offset="{ft(record_cursor)}" name="{cam_name}"'
              f' format="r1" tcFormat="NDF" duration="{ft(dur)}">')
            A(f'                <video start="{ft(tc)}" ref="{cam_ref}"'
              f' offset="{ft(tc)}" duration="{ft(cam_dur)}"/>')
            # MIC als <asset-clip> mit positivem lane (wie Resolve es exportiert)
            for i, (mic_off, mic_dur, ch) in enumerate(zip(mic_offsets, mic_durs, mic_chs)):
                lane      = i + 2        # lane 2 = MIC1, lane 3 = MIC2
                rid       = f"r{4 + i}"
                mic_name  = _x(Path(mics[i]).name)
                mic_start = max(0, abs_start0 - mic_off)
                actual_dur = min(total_frames, max(0, mic_dur - mic_start))
                if actual_dur <= 0:
                    continue
                A(f'                <asset-clip start="{ft(mic_start)}" ref="{rid}" enabled="1"'
                  f' lane="{lane}" offset="{ft(first_clip_start)}"'
                  f' name="{mic_name}" duration="{ft(actual_dur)}"/>')
            A('            </clip>')
        else:
            A(f'            <clip start="{ft(clip_start)}" enabled="1"'
              f' offset="{ft(record_cursor)}" name="{cam_name}"'
              f' format="r1" tcFormat="NDF" duration="{ft(dur)}">')
            A(f'                <video start="{ft(tc)}" ref="{cam_ref}"'
              f' offset="{ft(tc)}" duration="{ft(cam_dur)}"/>')
            A('            </clip>')

        record_cursor += dur

    A('          </spine>')
    A('        </sequence>')
    A('      </project>')
    A('    </event>')
    A('  </library>')
    A('</fcpxml>')

    output.write_text('\n'.join(L), encoding='utf-8')
    print(f"  → {output.name}  ({len(events)} Events, {len(mics)} MIC-Spur(en))")
    return output
