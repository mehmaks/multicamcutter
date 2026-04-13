#!/usr/bin/env python3
"""
Fully automated multicam EDL workflow starting from a raw media bin.

Steps:
  1. Scan bin for CAM + MIC files
  2. Waveform sync → frame offsets
  3. Build sync timeline (V1/V2 + A1/A2 camera ref + A3/A4+ mics, all mono)
  4. Run RMS diarization + nodding analysis
  5. Build cut timeline: V1 with assembled segments, A1/A2 continuous MICs

Usage:
    python run_from_bin.py --bin "30 - Ebra" --output "JU 30 Final"
"""

import sys
import os
import re
import json
import subprocess
import argparse
import time
from pathlib import Path

os.environ.setdefault('PYTHONUNBUFFERED', '1')

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from resolve_bridge.connection import get_resolve
from shared.waveform_sync import sync_sources, SyncError

SCRIPT_DIR = Path(__file__).parent


# ── Media Pool helpers ────────────────────────────────────────────────────────

def find_bin(folder, name):
    if folder.GetName() == name:
        return folder
    for sf in (folder.GetSubFolderList() or []):
        result = find_bin(sf, name)
        if result:
            return result
    return None


def scan_bin(folder) -> dict:
    """
    Returns {'cam': [...], 'mic': [...]} MediaPoolItems sorted by name.
    CAM = Video+Audio clips (.MP4/.MOV/.MXF)
    MIC = Audio-only clips (.WAV/.AIF)
    """
    VIDEO_EXT = {'.mp4', '.mov', '.mxf', '.r3d', '.ari'}
    AUDIO_EXT = {'.wav', '.aif', '.aiff'}

    clips = folder.GetClipList() or []
    cams, mics = [], []
    for clip in clips:
        ctype = clip.GetClipProperty('Type') or ''
        if 'Video' in ctype:
            cams.append(clip)
        elif 'Audio' in ctype:
            mics.append(clip)

    return {
        'cam': sorted(cams, key=lambda c: c.GetName()),
        'mic': sorted(mics, key=lambda c: c.GetName()),
    }


# ── Timeline builders ─────────────────────────────────────────────────────────

def build_sync_timeline(mp, name: str, cams: list, mics: list,
                        offsets: dict, fps: float):
    """
    Builds the sync reference timeline:
      V1: CAM1        V2: CAM2
      A1: CAM1 audio  A2: CAM2 audio   (camera reference, mono)
      A3: MIC1        A4: MIC2 ...     (zoom recorder, mono)
    """
    print(f"\nErstelle Sync-Timeline: '{name}'")

    tl = mp.CreateEmptyTimeline(name)
    if tl is None:
        # Name already taken — append a counter until we find a free name
        i = 2
        while tl is None:
            tl = mp.CreateEmptyTimeline(f"{name} {i}")
            i += 1
        print(f"  Name vergeben, erstellt als '{tl.GetName()}'")
    # starts with V1 (stereo) + A1 (stereo)

    # Add V2
    tl.AddTrack('video')
    # Reconfigure A1 to mono — can't change existing, so add A2 mono and note
    # A1 stays as created (stereo default). We add the rest as mono.
    tl.AddTrack('audio', 'mono')   # A2 — CAM2 ref
    tl.AddTrack('audio', 'mono')   # A3 — MIC1
    if len(mics) > 1:
        tl.AddTrack('audio', 'mono')  # A4 — MIC2

    def clip_frames(clip):
        """Frame count via Resolve API, with ffprobe fallback for audio-only files."""
        try:
            n = int(clip.GetClipProperty('Frames'))
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
        path = clip.GetClipProperty('File Path') or ''
        if path:
            try:
                probe = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'default=noprint_wrappers=1:nokey=1', path],
                    capture_output=True, text=True,
                )
                return round(float(probe.stdout.strip()) * fps)
            except Exception:
                pass
        return 0

    # ── Shift all record frames so nothing lands below 0 ─────────────────────
    all_offsets = [0, offsets.get('CAM2', 0)] + [offsets.get(f'MIC{i+1}', offsets.get('MIC1', 0)) for i in range(len(mics))]
    shift = max(0, -min(all_offsets))  # >= 0; pushes everything right if any offset is negative

    append_list = []

    # V1: CAM1
    cam1_frames = clip_frames(cams[0])
    append_list.append({
        'mediaPoolItem': cams[0],
        'startFrame': 0, 'endFrame': cam1_frames,
        'mediaType': 1, 'trackIndex': 1, 'recordFrame': shift,
    })
    # V2: CAM2
    cam2_offset = offsets.get('CAM2', 0)
    cam2_frames = clip_frames(cams[1])
    append_list.append({
        'mediaPoolItem': cams[1],
        'startFrame': 0, 'endFrame': cam2_frames,
        'mediaType': 1, 'trackIndex': 2, 'recordFrame': cam2_offset + shift,
    })
    # A1: CAM1 embedded audio
    append_list.append({
        'mediaPoolItem': cams[0],
        'startFrame': 0, 'endFrame': cam1_frames,
        'mediaType': 2, 'trackIndex': 1, 'recordFrame': shift,
    })
    # A2: CAM2 embedded audio
    append_list.append({
        'mediaPoolItem': cams[1],
        'startFrame': 0, 'endFrame': cam2_frames,
        'mediaType': 2, 'trackIndex': 2, 'recordFrame': cam2_offset + shift,
    })
    # A3+: MIC files
    for i, mic in enumerate(mics):
        mic_label  = f'MIC{i+1}'
        mic_offset = offsets.get(mic_label, offsets.get('MIC1', 0))
        mic_frames = clip_frames(mic)
        append_list.append({
            'mediaPoolItem': mic,
            'startFrame': 0, 'endFrame': mic_frames,
            'mediaType': 2, 'trackIndex': 3 + i, 'recordFrame': mic_offset + shift,
        })

    mp.AppendToTimeline(append_list)
    print(f"  V-Tracks: {tl.GetTrackCount('video')}, "
          f"A-Tracks: {tl.GetTrackCount('audio')}")
    return tl


def build_cut_timeline(mp, name: str, cut_events: list, mics: list,
                       offsets: dict, cam_items: dict, fps: float):
    """
    Builds the final cut timeline:
      V1: assembled video segments (from cut_events)
      A1: MIC1 continuous   A2: MIC2 continuous  (mono)

    cut_events: list of dicts with keys:
      clip (MediaPoolItem), source_in (int), source_out (int)

    offsets: {'CAM1': 0, 'CAM2': int, 'MIC1': int, ...} relative to CAM1
    cam_items: {'CAM1': (item, path), 'CAM2': (item, path)}
    """
    print(f"\nErstelle Cut-Timeline: '{name}'")

    tl = mp.CreateEmptyTimeline(name)
    time.sleep(0.5)  # Resolve braucht einen Moment nach CreateEmptyTimeline

    # Alle default Audio-Tracks entfernen (Resolve erstellt einen stereo A1)
    n_audio = tl.GetTrackCount('audio') or 0
    for _ in range(n_audio):
        tl.DeleteTrack('audio', 1)
        time.sleep(0.1)
    time.sleep(0.2)

    # Gewünschte Mono-Tracks anlegen
    for _ in range(len(mics)):
        tl.AddTrack('audio', 'mono')
    time.sleep(0.3)  # Track-Operationen abwarten

    # V1: video segments sequentially
    video_list = []
    record_cursor = 0
    for event in cut_events:
        duration = event['source_out'] - event['source_in']
        video_list.append({
            'mediaPoolItem': event['clip'],
            'startFrame':   event['source_in'],
            'endFrame':     event['source_out'],
            'mediaType':    1,
            'trackIndex':   1,
            'recordFrame':  record_cursor,
        })
        record_cursor += duration

    mp.AppendToTimeline(video_list)
    time.sleep(0.3)  # Video-Append abwarten bevor Audio folgt

    # A1/A2+: MIC files continuous, aligned with start of cut timeline.
    first_event = cut_events[0] if cut_events else None
    mic1_offset = offsets.get('MIC1', 0)
    if first_event:
        # Determine which camera the first event belongs to
        cam1_item = cam_items['CAM1'][0]
        if first_event['clip'] is cam1_item:
            cam_offset = offsets.get('CAM1', 0)
        else:
            cam_offset = offsets.get('CAM2', 0)
        # Absolute frame (CAM1-relative) of first cut event
        abs_start = first_event['source_in'] + cam_offset
        if abs_start >= mic1_offset:
            # MIC started before or at the first cut — trim source start
            mic_source_start = abs_start - mic1_offset
            mic_record_start = 0
        else:
            # MIC starts after the first cut — delay MIC in the cut timeline
            mic_source_start = 0
            mic_record_start = mic1_offset - abs_start
    else:
        mic_source_start = 0
        mic_record_start = 0

    audio_list = []
    for i, mic in enumerate(mics):
        try:
            mic_frames = int(mic.GetClipProperty('Frames') or 0)
            if mic_frames == 0:
                raise ValueError
        except (TypeError, ValueError):
            path = mic.GetClipProperty('File Path') or ''
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', path],
                capture_output=True, text=True,
            )
            mic_frames = round(float(probe.stdout.strip()) * fps)
        mic_available = record_cursor - mic_record_start
        mic_source_end = min(mic_frames, mic_source_start + mic_available)
        audio_list.append({
            'mediaPoolItem': mic,
            'startFrame':   mic_source_start,
            'endFrame':     mic_source_end,
            'mediaType':    2,
            'trackIndex':   1 + i,
            'recordFrame':  mic_record_start,
        })

    mp.AppendToTimeline(audio_list)
    print(f"  {len(cut_events)} Video-Segmente, {len(mics)} MIC-Spur(en)")

    # Apply clip colors based on cut reason
    _COLOR_MAP = {
        ('speaker', True):                      'Blue',    # CAM1 Hauptsprecher
        ('speaker', False):                     'Teal',    # CAM2 Hauptsprecher
        ('reaction_nodding', True):             'Purple',  # Nodding-Cutaway (auf CAM1)
        ('reaction_nodding', False):            'Purple',  # Nodding-Cutaway (auf CAM2)
        ('reaction_speaking_reaction', True):   'Green',   # Speaking-Cutaway (auf CAM1)
        ('reaction_speaking_reaction', False):  'Green',   # Speaking-Cutaway (auf CAM2)
        ('max_time', True):                     'Orange',  # Forced Max-Time Split (CAM1)
        ('max_time', False):                    'Orange',  # Forced Max-Time Split (CAM2)
    }
    cam1_ref = cam_items['CAM1'][0]
    video_items = sorted(
        tl.GetItemListInTrack('video', 1) or [],
        key=lambda x: x.GetStart(),
    )
    colored = 0
    for i, item in enumerate(video_items):
        if i >= len(cut_events):
            break
        ev = cut_events[i]
        reason  = ev.get('reason', 'speaker')
        is_cam1 = ev['clip'] is cam1_ref
        color   = _COLOR_MAP.get((reason, is_cam1), 'Blue')
        if item.SetClipColor(color):
            colored += 1
    print(f"  {colored}/{len(video_items)} Clips eingefärbt")

    return tl


# ── EDL parser ───────────────────────────────────────────────────────────────

def _tc_to_frames(tc: str, fps: float) -> int:
    h, m, s, f = (int(x) for x in tc.split(':'))
    return int((h * 3600 + m * 60 + s) * fps + f)


def _get_embedded_tc_frames(video_path: str, fps: float) -> int:
    """Returns the embedded start timecode of a video file as frame number."""
    probe = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_format', '-show_streams', video_path],
        capture_output=True, text=True
    )
    data = json.loads(probe.stdout)
    tc = data.get('format', {}).get('tags', {}).get('timecode')
    if not tc:
        for stream in data.get('streams', []):
            tc = stream.get('tags', {}).get('timecode')
            if tc:
                break
    if tc:
        return _tc_to_frames(tc, fps)
    return 0


def parse_edl(edl_path: Path, cam_items: dict, fps: float) -> list:
    """
    Parses a CMX3600 EDL and returns cut_events for build_cut_timeline().

    Each event: {'clip': MediaPoolItem, 'source_in': int, 'source_out': int}

    Source frames are recovered by subtracting the camera's embedded TC offset
    from the timecode values stored in the EDL (which were encoded as
    cam_ref + video_frame during EDL generation).

    cam_items: {'CAM1': (MediaPoolItem, file_path), 'CAM2': (...)}
    """
    text = edl_path.read_text()

    # Pre-compute embedded TC frames per camera
    ref_frames = {}
    for label, (item, path) in cam_items.items():
        ref_frames[label] = _get_embedded_tc_frames(path, fps)
        print(f"  {label} embedded TC: {ref_frames[label]} frames")

    # Build clip-name → cam label lookup (filename without extension)
    name_to_label = {}
    for label, (item, path) in cam_items.items():
        name_to_label[Path(path).name.lower()] = label

    # Parse EDL events
    # Pattern: event line followed by * FROM CLIP NAME: ...
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

    if len(events_raw) != len(clip_names):
        raise ValueError(
            f"EDL-Parsefehler: {len(events_raw)} Events aber "
            f"{len(clip_names)} Clip-Namen"
        )

    cut_events = []
    for ev_match, cn_match in zip(events_raw, clip_names):
        src_in_tc  = ev_match.group(1)
        src_out_tc = ev_match.group(2)
        clip_name  = cn_match.group(1).strip()

        label = name_to_label.get(clip_name.lower())
        if label is None:
            # Try stem match (name without extension)
            stem = Path(clip_name).stem.lower()
            for k, v in name_to_label.items():
                if Path(k).stem.lower() == stem:
                    label = v
                    break

        if label is None:
            print(f"  Warnung: Clip '{clip_name}' nicht in cam_items — überspringe Event")
            continue

        item, _ = cam_items[label]
        ref      = ref_frames[label]

        source_in  = _tc_to_frames(src_in_tc,  fps) - ref
        source_out = _tc_to_frames(src_out_tc, fps) - ref

        if source_in < 0 or source_out <= source_in:
            print(f"  Warnung: ungültige Source-Frames ({source_in}–{source_out}) für '{clip_name}' — überspringe")
            continue

        cut_events.append({
            'clip':       item,
            'source_in':  source_in,
            'source_out': source_out,
            'reason':     'speaker',
        })

    # Load companion colors JSON if available
    colors_path = edl_path.with_suffix('.colors.json')
    if colors_path.exists():
        try:
            colors_data = json.loads(colors_path.read_text())
            if len(colors_data) == len(cut_events):
                for ev, c in zip(cut_events, colors_data):
                    ev['reason'] = c.get('reason', 'speaker')
                print(f"  Colors-Metadaten geladen ({len(colors_data)} Einträge)")
            else:
                print(f"  ⚠ Colors JSON hat {len(colors_data)} Einträge, EDL hat {len(cut_events)} — ignoriert")
        except Exception as e:
            print(f"  ⚠ Colors JSON konnte nicht gelesen werden: {e}")

    print(f"  {len(cut_events)} Cut-Events aus EDL gelesen")
    if cut_events:
        first = cut_events[0]
        first_s = first['source_in'] / fps
        print(f"  Erster Event: source_in={first['source_in']} ({first_s:.1f}s ins Video)")
    return cut_events


# ── Analysis pipeline ─────────────────────────────────────────────────────────

def run_analysis(cam_paths: list, mic_paths: list, offsets: dict,
                 fps: float, work_dir: Path, config: Path,
                 skip_analysis: bool = False, skip_base_edl: bool = False,
                 mic_index_cam1: int = 1, mic_index_cam2: int = 0,
                 speaking_mode_override: str = None):
    """
    Runs nodding + RMS analysis, returns path to final EDL.

    mic_index_cam1 / mic_index_cam2: 0-based index into mic_paths for each camera.
    Default: MIC2 (index 1) → CAM1, MIC1 (index 0) → CAM2.
    """

    cam1_path = cam_paths[0]
    cam2_path = cam_paths[1]
    mic_cam1  = mic_paths[mic_index_cam1]
    mic_cam2  = mic_paths[mic_index_cam2]

    cam1_json = work_dir / (Path(cam1_path).stem + '_reactions.json')
    cam2_json = work_dir / (Path(cam2_path).stem + '_reactions.json')
    base_edl  = work_dir / 'base.edl'
    cam1_off_sections = work_dir / (Path(cam1_path).stem + '_off_sections.json')
    cam2_off_sections = work_dir / (Path(cam2_path).stem + '_off_sections.json')

    def run(cmd, desc):
        print(f"\n  {desc}...")
        result = subprocess.run([sys.executable] + cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Fehlgeschlagen: {desc}")

    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(str(config), encoding='utf-8')
    rms   = cfg['RMSDiarization'] if 'RMSDiarization' in cfg else {}
    sr_cfg = cfg['SpeakingReaction'] if 'SpeakingReaction' in cfg else {}
    cam1_speaking_json = work_dir / (Path(cam1_path).stem + '_speaking.json')
    cam2_speaking_json = work_dir / (Path(cam2_path).stem + '_speaking.json')
    speaking_enabled = sr_cfg.get('enabled', 'false').strip().lower() == 'true'

    # ── Schritt 1: Base-EDL aus Audio (immer zuerst, liefert Off-Sektionen) ──
    if not skip_base_edl:
        builder = str(SCRIPT_DIR / 'build_base_edl_from_audio.py')
        builder_args = [
            builder,
            '--mic-cam1',          mic_cam1,
            '--mic-cam2',          mic_cam2,
            '--cam1-video',        cam1_path,
            '--cam2-video',        cam2_path,
            '--cam1-clip',         Path(cam1_path).name,
            '--cam2-clip',         Path(cam2_path).name,
            '--wav-edl-frame',     str(offsets['MIC1']),
            '--cam1-edl-frame',    str(offsets['CAM1']),
            '--cam2-edl-frame',    str(offsets['CAM2']),
            '--fps',               str(fps),
            '--output',            str(base_edl),
            '--min-edit-duration', rms.get('min_edit_duration', '1.0'),
            '--change-delay',      rms.get('change_delay', '0.3'),
            '--threshold-db',      rms.get('threshold_db', '6.0'),
            '--cam1-off-sections-out', str(cam1_off_sections),
            '--cam2-off-sections-out', str(cam2_off_sections),
        ]
        if speaking_enabled:
            mode = speaking_mode_override or sr_cfg.get('mode', 'rms')
            builder_args += [
                '--speaking-reactions-cam1-out', str(cam1_speaking_json),
                '--speaking-reactions-cam2-out', str(cam2_speaking_json),
                '--speaking-rise-db',        sr_cfg.get('rise_db',        '10.0'),
                '--speaking-min-duration',   sr_cfg.get('min_duration',   '0.20'),
                '--speaking-max-duration',   sr_cfg.get('max_duration',   '1.5'),
                '--speaking-attack-window',  sr_cfg.get('attack_window',  '1.0'),
                '--speaking-release-window', sr_cfg.get('release_window', '20.0'),
                '--speaking-warmup',         sr_cfg.get('warmup',         '3.0'),
                '--speaking-hold',           sr_cfg.get('hold',           '0.0'),
                '--speaking-mode',           mode,
            ]
        run(builder_args, "Base-EDL aus Audio")

    # ── Schritt 2: Nodding-Analyse (nur Off-Sektionen) ────────────────────────
    if not skip_analysis:
        analyzer = str(SCRIPT_DIR / 'video_reaction_analyzer_v2.4.py')
        cam1_analyzer_args = [analyzer, cam1_path, '--output', str(cam1_json), '--config', str(config)]
        if cam1_off_sections.exists():
            cam1_analyzer_args += ['--off-sections', str(cam1_off_sections)]
        run(cam1_analyzer_args, "Nodding-Analyse CAM1")

        cam2_analyzer_args = [analyzer, cam2_path, '--output', str(cam2_json), '--config', str(config)]
        if cam2_off_sections.exists():
            cam2_analyzer_args += ['--off-sections', str(cam2_off_sections)]
        run(cam2_analyzer_args, "Nodding-Analyse CAM2")

    adder = str(SCRIPT_DIR / 'add_reactions_to_edl.py')
    final_edl = work_dir / 'final.edl'
    adder_args = [
        adder,
        '--resolve-edl',    str(base_edl),
        '--cam1-clip',      Path(cam1_path).name,
        '--cam1-reactions', str(cam1_json),
        '--cam2-clip',      Path(cam2_path).name,
        '--cam2-reactions', str(cam2_json),
        '--cam1-video',     cam1_path,
        '--cam2-video',     cam2_path,
        '--output',         str(final_edl),
        '--config',         str(config),
    ]
    if speaking_enabled and cam1_speaking_json.exists():
        adder_args += ['--cam1-speaking-reactions', str(cam1_speaking_json)]
    if speaking_enabled and cam2_speaking_json.exists():
        adder_args += ['--cam2-speaking-reactions', str(cam2_speaking_json)]
    run(adder_args, "Nodding-Cutaways einfügen")

    return final_edl


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Multicam Workflow: Bin → Sync → Analyse → Cut-Timeline'
    )
    parser.add_argument('--bin',    required=True, help='Media Pool Bin-Name')
    parser.add_argument('--output', required=True, help='Name der fertigen Cut-Timeline')
    parser.add_argument('--fps',    type=float, default=25.0)
    parser.add_argument('--config', default=str(SCRIPT_DIR / 'config.ini'))
    parser.add_argument('--skip-analysis', action='store_true')
    parser.add_argument('--skip-base-edl', action='store_true')
    parser.add_argument('--sync-timeline', default=None,
                        help='Name der Sync-Timeline (default: <output> Sync)')
    parser.add_argument('--mic-cam1', type=int, default=1,
                        help='0-basierter MIC-Index für CAM1 (default: 1 = MIC2)')
    parser.add_argument('--mic-cam2', type=int, default=0,
                        help='0-basierter MIC-Index für CAM2 (default: 0 = MIC1)')
    parser.add_argument('--speaking-mode', choices=['rms', 'peak'], default=None,
                        help='Überschreibt speaking_mode aus config.ini')
    args = parser.parse_args()

    resolve = get_resolve()
    pm      = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    mp      = project.GetMediaPool()

    # 1. Bin scannen
    print(f"\nScanne Bin: '{args.bin}'")
    bin_folder = find_bin(mp.GetRootFolder(), args.bin)
    if not bin_folder:
        print(f"FEHLER: Bin '{args.bin}' nicht gefunden.")
        return 1

    media = scan_bin(bin_folder)
    cams, mics = media['cam'], media['mic']

    if len(cams) < 2:
        print(f"FEHLER: Mindestens 2 Kamera-Clips erwartet, {len(cams)} gefunden.")
        return 1
    if len(mics) < 1:
        print(f"FEHLER: Mindestens 1 MIC-Clip erwartet, {len(mics)} gefunden.")
        return 1

    print(f"  Kameras: {[c.GetName() for c in cams]}")
    print(f"  Mics:    {[m.GetName() for m in mics]}")

    # 2. Waveform-Sync
    cam1_path = cams[0].GetClipProperty('File Path')
    cam2_path = cams[1].GetClipProperty('File Path')
    mic_paths = [m.GetClipProperty('File Path') for m in mics]

    print()
    try:
        offsets = sync_sources(
            cam1_path, cam2_path, mic_paths[0],
            fps=args.fps,
            additional_mics=mic_paths[1:],
        )
    except SyncError as e:
        print(f"\nFEHLER: {e}")
        return 1

    # 3. Sync-Timeline aufbauen
    sync_name = args.sync_timeline or f"{args.output} Sync"
    sync_tl = build_sync_timeline(mp, sync_name, cams, mics, offsets, args.fps)
    project.SetCurrentTimeline(sync_tl)

    # 4. Analyse-Pipeline
    work_dir = Path(cam1_path).parent / 'analyse'
    work_dir.mkdir(exist_ok=True)
    try:
        final_edl = run_analysis(
            [cam1_path, cam2_path], mic_paths, offsets,
            args.fps, work_dir, Path(args.config),
            args.skip_analysis, args.skip_base_edl,
            mic_index_cam1=args.mic_cam1,
            mic_index_cam2=args.mic_cam2,
            speaking_mode_override=args.speaking_mode,
        )
    except RuntimeError as e:
        print(f"\nFEHLER in Analyse: {e}")
        return 1

    # 5. Cut-Timeline via AppendToTimeline aufbauen
    cam_items = {
        'CAM1': (cams[0], cam1_path),
        'CAM2': (cams[1], cam2_path),
    }
    print(f"\nParse finale EDL: {final_edl.name}")
    try:
        cut_events = parse_edl(final_edl, cam_items, args.fps)
    except (ValueError, Exception) as e:
        print(f"FEHLER beim EDL-Parsen: {e}")
        return 1

    if not cut_events:
        print("FEHLER: Keine Cut-Events aus EDL gelesen.")
        return 1

    cut_tl = build_cut_timeline(
        mp, args.output, cut_events, mics,
        offsets=offsets, cam_items=cam_items, fps=args.fps,
    )
    project.SetCurrentTimeline(cut_tl)
    time.sleep(0.3)
    pm.SaveProject()
    print(f"  '{args.output}' angelegt, aktiviert und gespeichert.")

    print(f"\nWorkflow abgeschlossen.")
    print(f"  Sync-Timeline: {sync_name}")
    print(f"  Cut-Timeline:  {args.output}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
