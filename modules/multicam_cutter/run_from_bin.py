#!/usr/bin/env python3
"""
Fully automated multicam EDL workflow starting from a raw media bin.

Steps:
  1. Scan bin for CAM + MIC files
  2. Waveform sync → frame offsets
  3. Run RMS diarization + nodding analysis
  4. Build cut timeline: V1 with assembled segments, A1/A2 continuous MICs

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
from shared.paths import effective_clip_prompts_path
from shot_sizes import camera_roles

SCRIPT_DIR = Path(__file__).parent

# „Mund + Mikro" (Beta 1.1.0): vorerst abgeschaltet, Code bleibt (User, 19.11.).
# Nachfolger: Einwurf-Erkennung auf der Analysespur (analyse/aktivitaet/einwurf_b.py).
MOUTH_REACTIONS_AVAILABLE = False


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

def _create_timeline(mp, name: str, bin_folder=None):
    """
    Creates an empty timeline, handling Resolve's global name uniqueness.
    If bin_folder is given, sets it as current folder first.
    Returns (timeline, actual_name).
    """
    if bin_folder:
        mp.SetCurrentFolder(bin_folder)
    tl = mp.CreateEmptyTimeline(name)
    if tl is None:
        time.sleep(1.0)
        tl = mp.CreateEmptyTimeline(name)
    if tl is not None:
        return tl, name

    # Name global vergeben (anderer Bin) — Bin-Name als Prefix
    if bin_folder:
        bin_name = bin_folder.GetName()
        prefixed = f"{bin_name} – {name}"
        tl = mp.CreateEmptyTimeline(prefixed)
        if tl is not None:
            print(f"  '{name}' existiert in anderem Bin → '{prefixed}'")
            return tl, prefixed

    # Letzter Fallback: Suffix
    for suffix in range(2, 20):
        alt = f"{name} ({suffix})"
        tl = mp.CreateEmptyTimeline(alt)
        if tl is not None:
            print(f"  '{name}' existiert bereits → '{alt}'")
            return tl, alt

    raise RuntimeError(f"Timeline '{name}' konnte nicht erstellt werden.")



def build_cut_timeline(mp, name: str, cut_events: list, mics: list,
                       offsets: dict, cam_items: dict, fps: float,
                       skipped_gap_frames: int = 0, bin_folder=None,
                       audio_trims_path: Path = None):
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

    tl, actual_name = _create_timeline(mp, name, bin_folder)
    time.sleep(0.5)  # Resolve braucht einen Moment nach CreateEmptyTimeline

    # Mono-Tracks anlegen, dann den Default-Stereo-Track löschen.
    # Resolve kann den letzten Audio-Track nicht löschen, daher erst hinzufügen.
    for _ in range(len(mics)):
        tl.AddTrack('audio', 'mono')
        time.sleep(0.1)
    time.sleep(0.3)

    # Default-Stereo-A1 entfernen (jetzt möglich, da Mono-Tracks existieren)
    if tl.DeleteTrack('audio', 1):
        time.sleep(0.2)
    else:
        print("  ⚠️  Default-Stereo-Track konnte nicht gelöscht werden")

    # Audio-Track-Index bestimmen: erste Mono-Spur
    n_audio = tl.GetTrackCount('audio') or 0
    audio_start_idx = n_audio - len(mics) + 1  # Falls Stereo-Track noch da ist
    print(f"  Audio-Tracks: {n_audio} (MICs ab A{audio_start_idx})")

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
    # When parse_edl skipped events (negative source frames), the record
    # timeline is shorter than the EDL span. The MIC must skip the same
    # duration to stay in sync with the remaining video events.
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

        # Verify sync using last event (detects gaps from skipped events).
        # Nur prüfen wenn KEIN Pause-Trimming aktiv — bei audio_keeps wird
        # MIC segmentiert platziert, nicht als durchgehender Clip.
        _has_audio_keeps = (audio_trims_path and audio_trims_path.exists())
        if len(cut_events) > 1 and not _has_audio_keeps:
            last_event = cut_events[-1]
            if last_event['clip'] is cam1_item:
                last_cam_offset = offsets.get('CAM1', 0)
            else:
                last_cam_offset = offsets.get('CAM2', 0)
            last_abs_end = last_event['source_out'] + last_cam_offset
            expected_mic_end = last_abs_end - mic1_offset
            actual_mic_end = mic_source_start + record_cursor
            drift = expected_mic_end - actual_mic_end
            if abs(drift) > 1:
                print(f"  ⚠️  MIC-Sync-Drift erkannt: {drift} Frames ({drift / fps:.2f}s)")
                print(f"      Übersprungene Events: {skipped_gap_frames} Frames")
                print(f"      ⚠️  Audio/Video werden NICHT synchron sein!")
    else:
        mic_source_start = 0
        mic_record_start = 0

    # Audio-Keeps laden (Pause-Trimming)
    audio_keeps = None
    if audio_trims_path and audio_trims_path.exists():
        try:
            audio_keeps = json.loads(audio_trims_path.read_text())
            print(f"  Audio-Keeps geladen: {len(audio_keeps)} Segmente (Pause-Trim aktiv)")
        except Exception:
            audio_keeps = None

    if audio_keeps:
        # MIC segmentiert platzieren: Keep-Regionen überspringen die Trim-Lücken
        # audio_keeps: [(orig_start_frame, orig_end_frame, new_record_frame), ...]
        # Batch-Aufruf wie Video (einzelne AppendToTimeline-Aufrufe können
        # bei Resolve zu kumulativem Drift führen).
        for i, mic in enumerate(mics):
            mic_segments = []
            for orig_s, orig_e, rec_frame in audio_keeps:
                src_s = mic_source_start + (orig_s - audio_keeps[0][0])
                src_e = mic_source_start + (orig_e - audio_keeps[0][0])
                if src_s < 0:
                    rec_frame += -src_s
                    src_s = 0
                if src_e <= src_s:
                    continue
                mic_segments.append({
                    'mediaPoolItem': mic,
                    'startFrame':   src_s,
                    'endFrame':     src_e,
                    'mediaType':    2,
                    'trackIndex':   audio_start_idx + i,
                    'recordFrame':  rec_frame,
                })
            mp.AppendToTimeline(mic_segments)
            time.sleep(0.3)
        # Diagnostik: Audio-Segment-Positionen loggen
        _ak_total = sum(e - s for s, e, _ in audio_keeps)
        print(f"  Audio-Keeps: {len(audio_keeps)} Segmente, "
              f"Gesamt={_ak_total} Frames ({_ak_total / fps:.1f}s)")
        print(f"  Video-Gesamt: {record_cursor} Frames ({record_cursor / fps:.1f}s)")
        _ak_diff = record_cursor - _ak_total
        if abs(_ak_diff) > 2:
            print(f"  ⚠️  Video/Audio-Keeps Diff: {_ak_diff} Frames")
        else:
            print(f"  ✓ Video/Audio-Keeps synchron (Diff={_ak_diff})")
        print(f"  {len(cut_events)} Video-Segmente, {len(mics)} MIC-Spur(en) "
              f"({len(audio_keeps)} Audio-Segmente je MIC)")
    else:
        # Standard: MIC als ein durchgehender Clip
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
                'trackIndex':   audio_start_idx + i,
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
        ('pause_cutaway', True):                'Violet',  # Stille-Cutaway (auf CAM1)
        ('pause_cutaway', False):               'Violet',  # Stille-Cutaway (auf CAM2)
    }
    cam1_ref = cam_items['CAM1'][0]
    video_items = sorted(
        tl.GetItemListInTrack('video', 1) or [],
        key=lambda x: x.GetStart(),
    )
    if len(video_items) != len(cut_events):
        print(f"  ⚠️  FARB-MISMATCH: {len(video_items)} Timeline-Items vs "
              f"{len(cut_events)} Cut-Events — Farben können verschoben sein!")

    colored = 0
    color_stats = {}
    for i, item in enumerate(video_items):
        if i >= len(cut_events):
            break
        ev = cut_events[i]
        reason  = ev.get('reason', 'speaker')
        is_cam1 = ev['clip'] is cam1_ref
        color   = _COLOR_MAP.get((reason, is_cam1), 'Blue')
        if item.SetClipColor(color):
            colored += 1
        color_stats[reason] = color_stats.get(reason, 0) + 1
    print(f"  {colored}/{len(video_items)} Clips eingefärbt")
    for reason, count in sorted(color_stats.items()):
        color = _COLOR_MAP.get((reason, True), 'Blue')
        print(f"    {color:8s} ← {reason} ({count}x)")

    # Farblegende als Marker an Frame 1 der Timeline
    tl.AddMarker(
        1, 'Blue', 'Farblegende',
        'Blue = Speaker CAM1 | Teal = Speaker CAM2 | '
        'Purple = Nodding | Green = Speaking-Reaction | '
        'Orange = Max-Time',
        1,
    )

    # Post-Trim Manifest: Zeigt für jedes Timeline-Event Reason + Color + Record-TC
    manifest = []
    for i, ev in enumerate(cut_events):
        reason = ev.get('reason', 'speaker')
        is_cam1 = ev['clip'] is cam1_ref
        color = _COLOR_MAP.get((reason, is_cam1), 'Blue')
        rec_in = ev.get('record_in', 0)
        rec_out = ev.get('record_out', 0)
        # Clip-Name ermitteln
        clip_name = 'CAM1' if is_cam1 else 'CAM2'
        for label, (item, _) in cam_items.items():
            if item is ev['clip']:
                clip_name = label
                break
        s_in = ev.get('source_in', 0)
        manifest.append({
            'idx': i + 1,
            'record_tc': f"{int(rec_in / fps) // 3600:02d}:{(int(rec_in / fps) % 3600) // 60:02d}:"
                         f"{int(rec_in / fps) % 60:02d}:{int(rec_in % fps):02d}",
            'clip': clip_name,
            'source_frame': s_in,
            'reason': reason,
            'color': color,
        })
    if audio_trims_path:
        manifest_path = audio_trims_path.parent / 'timeline_manifest.json'
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                     encoding='utf-8')
            print(f"  ✓ Manifest: {manifest_path.name} ({len(manifest)} Events)")
        except Exception:
            pass

    return tl


# ── EDL parser ───────────────────────────────────────────────────────────────

from frame_utils import timecode_to_frames as _tc_to_frames, get_reference_frame as _get_ref_frame


def _get_embedded_tc_frames(video_path: str, fps: float, item=None) -> int:
    """Returns the embedded start timecode of a video file as frame number.

    Versucht zuerst ffprobe (kanonischer Weg). Wenn das in dieser Umgebung
    fehlschlägt (z.B. UnicodeDecodeError im stdout-Decode), fragt es als
    Fallback Resolves MediaPoolItem direkt über 'Start TC'. Beide Pfade
    schlagen nur dann komplett fehl, wenn die Quelldatei wirklich keinen
    TC hat — dann return 0.
    """
    ref_frame, _ = _get_ref_frame(video_path, fps)
    if ref_frame:
        return ref_frame
    if item is not None:
        tc = item.GetClipProperty('Start TC') or ''
        if tc:
            try:
                return _tc_to_frames(tc, fps)
            except (ValueError, IndexError):
                pass
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
        ref_frames[label] = _get_embedded_tc_frames(path, fps, item=item)
        print(f"  {label} embedded TC: {ref_frames[label]} frames")
        if ref_frames[label] == 0:
            print(f"  ⚠️  {label}: Embedded TC = 0 für '{path}'. "
                  f"Source-Frames in der finalen Timeline werden falsch aufgelöst "
                  f"(Standbild + leere Audiospuren). Pfad-Existenz: "
                  f"{Path(path).exists() if path else 'leer/None'}")

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
    skipped_gaps = 0
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

        rec_in_tc  = ev_match.group(3)
        rec_out_tc = ev_match.group(4)
        source_in  = _tc_to_frames(src_in_tc,  fps) - ref
        source_out = _tc_to_frames(src_out_tc, fps) - ref

        if source_in < 0 or source_out <= source_in:
            gap_frames = _tc_to_frames(rec_out_tc, fps) - _tc_to_frames(rec_in_tc, fps)
            print(f"  ⚠️  ÜBERSPRUNGEN: '{clip_name}' Source-Frames {source_in}–{source_out} "
                  f"(Record {rec_in_tc}–{rec_out_tc}, {gap_frames} Frames Lücke)")
            skipped_gaps += gap_frames
            continue

        cut_events.append({
            'clip':       item,
            'source_in':  source_in,
            'source_out': source_out,
            'record_in':  _tc_to_frames(rec_in_tc, fps),
            'record_out': _tc_to_frames(rec_out_tc, fps),
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
    if skipped_gaps > 0:
        print(f"  ⚠️  {skipped_gaps} Frames ({skipped_gaps / fps:.1f}s) übersprungen — "
              f"MIC-Platzierung wird kompensiert")
    if cut_events:
        first = cut_events[0]
        first_s = first['source_in'] / fps
        print(f"  Erster Event: source_in={first['source_in']} ({first_s:.1f}s ins Video)")
    return cut_events, skipped_gaps


# ── Analysis pipeline ─────────────────────────────────────────────────────────

def run_analysis(cam_paths: list, mic_paths: list, offsets: dict,
                 fps: float, work_dir: Path, params: dict,
                 skip_analysis: bool = False, skip_base_edl: bool = False,
                 cam_mic_map: list = None,
                 cam_types: list = None,
                 cam_nodding: list = None,
                 speaking_mode_override: str = None,
                 auto_accuracy: bool = False,
                 lut_path: str = None):
    """
    Runs nodding + RMS analysis for N cameras, returns path to final EDL.

    Sprecher-Erkennung (Base-EDL) läuft binär über cam_paths[0] und cam_paths[1].
    Nodding-Analyse läuft über alle cam_paths.

    cam_mic_map: Liste von Listen mit 0-basierten MIC-Indizes pro Kamera.
      Beispiel: [[1], [0]]      → CAM1 nutzt MIC2, CAM2 nutzt MIC1 (Default)
               [[0, 1], [2]]   → CAM1 nutzt MIC1+MIC2 (aggregiert), CAM2 nutzt MIC3
    """
    if cam_mic_map is None:
        cam_mic_map = [[min(1, len(mic_paths) - 1)], [0]]
    if cam_types is None:
        cam_types = ['close'] * len(cam_paths)
    if cam_nodding is None:
        cam_nodding = [True] * len(cam_paths)
    # Globaler Schalter schlaegt die Per-Cam-Liste. Die Mac-App kennt nur diesen
    # einen Schalter und sendet ihn als params-Key, NICHT als --cam-nodding.
    # Ohne das hier lief MediaPipe trotz ausgeschaltetem Kopfnicken durch (~30 min
    # pro Lauf) und die Ergebnisse wurden anschliessend verworfen — der Schalter
    # steuerte nur, ob Nicken zu Cutaways wird (add_reactions_to_edl.py:1122).
    if not params.get('nodding_enabled', True):
        cam_nodding = [False] * len(cam_paths)

    # Die Diarisierung laeuft binaer ueber Position 1 und 2. Steht dort eine Totale,
    # ist ihre Seite per combine_audios das Maximum ueber ALLE Mics dieser Cam und
    # damit fast immer die lautere -- die Sprechererkennung kippt, ohne dass etwas
    # abbricht. Die Mac-App sortiert deshalb Closes nach vorn (orderedAnalysisCams),
    # aber diese Invariante lebte bisher NUR dort: wer run_from_bin direkt aufruft,
    # hatte keinerlei Schutz. Die Engine setzt sie jetzt selbst durch.
    # ── N-Entscheidung: mehr als zwei Close-Kameras → Personen-basierter Pfad ──
    # Den Personen-Graphen (Kamera → gezeigte Personen) aus den Mic-Zuordnungen
    # ableiten und die Rollen bestimmen. Genau die Konstellation, die der alte
    # Waechter (unsupportedCloseCams / _wide_at_front) sperrte, faehrt jetzt den
    # N-Weg (build_base_edl_n) statt binaer CAM1/CAM2.
    _cams_for_roles = [
        {'name': Path(cp).name,
         'mics': [mic_paths[j]
                  for j in (cam_mic_map[i] if i < len(cam_mic_map) else [])
                  if j < len(mic_paths)]}
        for i, cp in enumerate(cam_paths)
    ]
    _n_close = sum(1 for r in camera_roles(_cams_for_roles).values() if r == 'close')
    use_n_path = _n_close > 2
    if use_n_path:
        print(f"\n  ℹ️  {_n_close} Close-Kameras → N-Personen-Pfad (build_base_edl_n).")

    # Der binaere Pfad vergleicht genau Position 1 und 2 — dort darf keine Totale
    # stehen. Fuer den N-Pfad gibt es diese ausgezeichneten Positionen nicht.
    _wide_at_front = [] if use_n_path else [
        i for i in (0, 1) if i < len(cam_types) and cam_types[i] == 'wide']
    if _wide_at_front:
        _names = ', '.join(f"CAM{i + 1} ({Path(cam_paths[i]).name})"
                           for i in _wide_at_front)
        raise ValueError(
            f"Auf Position 1/2 steht eine Totale: {_names}.\n"
            "Die Sprechererkennung vergleicht genau diese beiden Positionen. Eine "
            "Totale fasst dort alle ihre Mikrofone zusammen und gewinnt den Vergleich "
            "fast immer — der Schnitt waere still falsch.\n"
            "Abhilfe: Close-Kameras nach vorne sortieren (--cams/--cam-types), "
            "Totalen ans Ende."
        )

    cam1_path = cam_paths[0]
    cam2_path = cam_paths[1]

    def _resolve_mic_paths(indices):
        return [mic_paths[i] for i in indices if i < len(mic_paths)]

    mic_cam1_paths = _resolve_mic_paths(cam_mic_map[0] if len(cam_mic_map) > 0 else [1])
    mic_cam2_paths = _resolve_mic_paths(cam_mic_map[1] if len(cam_mic_map) > 1 else [0])
    if not mic_cam1_paths:
        mic_cam1_paths = [mic_paths[min(1, len(mic_paths) - 1)]]
    if not mic_cam2_paths:
        mic_cam2_paths = [mic_paths[0]]

    base_edl = work_dir / 'base.edl'
    cam1_off_sections = work_dir / (Path(cam1_path).stem + '_off_sections.json')
    cam2_off_sections = work_dir / (Path(cam2_path).stem + '_off_sections.json')

    def run(cmd, desc):
        print(f"\n  {desc}...")
        if getattr(sys, 'frozen', False):
            # PyInstaller Bundle: Scripts in-process ausfuehren via runpy.
            # Subprocesses funktionieren nicht weil sys.executable auf das
            # frozen Binary zeigt, nicht auf einen Python-Interpreter.
            import runpy
            script_path = cmd[0]
            old_argv = sys.argv
            sys.argv = [script_path] + cmd[1:]
            try:
                runpy.run_path(script_path, run_name='__main__')
            except SystemExit as e:
                if e.code not in (None, 0):
                    raise RuntimeError(f"Fehlgeschlagen: {desc}")
            finally:
                sys.argv = old_argv
        elif hasattr(sys.stdout, '_log'):
            # Dev/App-Modus: Subprocess-Output pipen und durch TeeWriter leiten
            proc = subprocess.Popen(
                [sys.executable, '-u'] + cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, text=True, encoding='utf-8', errors='replace',
            )
            for line in proc.stdout:
                sys.stdout.write(line)
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"Fehlgeschlagen: {desc}")
        else:
            result = subprocess.run([sys.executable] + cmd)
            if result.returncode != 0:
                raise RuntimeError(f"Fehlgeschlagen: {desc}")

    speaking_enabled = bool(params.get('speaking_enabled', False))
    pause_cutaway_enabled = bool(params.get('pause_cutaway_enabled', False))
    clip_filter_enabled = bool(params.get('clip_filter_enabled', False))

    # Sprech-/Pausen-Reaktionen (beide opt-in) sind fuer >2 Personen noch nicht
    # verfuegbar — die Rolling-Baseline-Detektoren sind bisher rein binaer. Bewusst
    # deaktivieren mit klarer Meldung, statt sie still fehlen zu lassen. Nicken,
    # Simultan→Totale und Uebergaenge laufen im N-Pfad normal.
    if use_n_path and (speaking_enabled or pause_cutaway_enabled):
        print("  ⚠️  Sprech-/Pausen-Reaktionen sind fuer mehr als zwei Personen noch "
              "nicht verfuegbar und werden in diesem Lauf uebersprungen.")
        print("      (Nicken-Cutaways, Simultan→Totale und Uebergaenge laufen normal.)")
        speaking_enabled = False
        pause_cutaway_enabled = False

    # „Mund + Mikro" (Beta): zusaetzliche Quelle fuer Sprachreaktionen aus der
    # Gesichtsanalyse. Haengt an den Sprachreaktionen (gleicher Cutaway-Typ) und
    # ist wie diese vorerst nur im binaeren Pfad verfuegbar. Braucht die
    # Gesichtsanalyse → bei skip_analysis aus.
    # Seit 19.11. abgeschaltet (nicht verworfen): die Einwurf-Erkennung auf der
    # Analysespur verfolgt dasselbe Ziel ohne Gesichtsanalyse. Wieder an: True.
    mouth_enabled = (MOUTH_REACTIONS_AVAILABLE
                     and bool(params.get('mouth_reactions_enabled', False)) and speaking_enabled)
    # Einwürfe aus der Analysespur (Beta): braucht keine Gesichtsanalyse, aber wie
    # die Sprachreaktionen nur den binären Pfad.
    # Seit 20.11. die EINZIGE Einwurf-Erkennung (die alte auf der wandernden
    # Grundlinie ist entfernt) — läuft immer, wenn Sprachreaktionen an sind.
    # Auch ohne Sprachreaktionen nötig, wenn Pausen gekürzt / Pausen-Cutaways gesetzt
    # werden: Pausen und Sprecherwechsel-Feinlage kommen ebenfalls aus der Analysespur.
    analysespur_enabled = ((speaking_enabled or bool(params.get('pause_trim_enabled', False))
                            or pause_cutaway_enabled) and not use_n_path)
    if mouth_enabled and (use_n_path or skip_analysis):
        mouth_enabled = False

    # ── Schritt 1 (N-Pfad): Base-EDL ueber Personen → engste Kamera ──────────
    # Diarisiert ueber die Personen-Mics und schneidet jede auf ihre engste
    # Kamera. Nicken/Simultan/Uebergaenge laufen; Sprech-/Pausen-Reaktionen (s.o.)
    # sind fuer N noch deaktiviert.
    if not skip_base_edl and use_n_path:
        cams_json_path = work_dir / 'cams.json'
        cams_spec = {
            'cameras': [
                {'clip': Path(cp).name, 'video': cp,
                 'mics': [mic_paths[j]
                          for j in (cam_mic_map[i] if i < len(cam_mic_map) else [])
                          if j < len(mic_paths)],
                 'edl_frame': offsets.get(f'CAM{i + 1}', 0)}
                for i, cp in enumerate(cam_paths)
            ],
            'mic_offsets': {mic_paths[k]: offsets.get(f'MIC{k + 1}', 0)
                            for k in range(len(mic_paths))},
        }
        cams_json_path.write_text(json.dumps(cams_spec, ensure_ascii=False),
                                  encoding='utf-8')
        builder_args = [
            str(SCRIPT_DIR / 'build_base_edl_from_audio.py'),
            '--cams-json',         str(cams_json_path),
            '--fps',               str(fps),
            '--output',            str(base_edl),
            '--min-edit-duration', str(params.get('min_edit', 1.0)),
            '--change-delay',      str(params.get('change_delay', 0.3)),
            '--threshold-db',      str(params.get('threshold_db', 6.0)),
            '--totale-simul-min-duration', str(params.get('totale_simul_dur', 3.0)),
        ]
        if params.get('pause_silence_db') is not None:
            builder_args += ['--pause-silence-db', str(params['pause_silence_db'])]
        # Bildsprache-Uebergaenge bei Sprecherwechseln (Default an) — im N-Pfad
        # ueber die kleinste gemeinsame Kamera je Personenpaar (smallest_containing).
        if params.get('transition_speaker_change', True):
            builder_args += [
                '--transition-on-speaker-change',
                '--transition-min-shot',      str(params.get('min_shot', 2.3)),
                '--transition-randomness',    str(params.get('randomness', 0.0)),
                '--transition-return-factor',
                str(params.get('transition_return_factor', 2.5)),
            ]
        run(builder_args, "Base-EDL aus Audio (N Personen)")

    # ── Schritt 1: Base-EDL aus Audio (binäre Diarisierung CAM1/CAM2) ────────
    elif not skip_base_edl:
        cam1_speaking_json = work_dir / (Path(cam1_path).stem + '_speaking.json')
        cam2_speaking_json = work_dir / (Path(cam2_path).stem + '_speaking.json')
        builder_args = [
            str(SCRIPT_DIR / 'build_base_edl_from_audio.py'),
            '--mic-cam1'] + mic_cam1_paths + [
            '--mic-cam2'] + mic_cam2_paths + [
            '--cam1-video',        cam1_path,
            '--cam2-video',        cam2_path,
            '--cam1-clip',         Path(cam1_path).name,
            '--cam2-clip',         Path(cam2_path).name,
            '--wav-edl-frame',     str(offsets['MIC1']),
            '--cam1-edl-frame',    str(offsets['CAM1']),
            '--cam2-edl-frame',    str(offsets['CAM2']),
            '--fps',               str(fps),
            '--output',            str(base_edl),
            '--min-edit-duration', str(params.get('min_edit', 1.0)),
            '--change-delay',      str(params.get('change_delay', 0.3)),
            '--threshold-db',      str(params.get('threshold_db', 6.0)),
            '--cam1-off-sections-out', str(cam1_off_sections),
            '--cam2-off-sections-out', str(cam2_off_sections),
        ]
        # Totale-Cam: erste Kamera mit type='wide' (falls vorhanden)
        totale_idx = next(
            (i for i, t in enumerate(cam_types) if t == 'wide'), None
        )
        if totale_idx is not None:
            totale_path = cam_paths[totale_idx]
            builder_args += [
                '--totale-video',               totale_path,
                '--totale-clip',                Path(totale_path).name,
                '--totale-edl-frame',           str(offsets.get(f'CAM{totale_idx + 1}', 0)),
                '--totale-simul-min-duration',  str(params.get('totale_simul_dur', 3.0)),
            ]
            # Uebergangsregel: bei Sprecherwechseln ueber die kleinste gemeinsame
            # Einstellung schneiden. Standardmaessig AN — greift aber nur, wenn es
            # ueberhaupt eine Totale gibt (dieser Block laeuft sonst nicht). In
            # Setups, in denen jede Kamera genau eine Person zeigt, aendert sich
            # also nichts. Siehe brain/Bildsprache.md.
            if params.get('transition_speaker_change', True):
                builder_args += [
                    '--transition-on-speaker-change',
                    '--transition-min-shot',    str(params.get('min_shot', 2.3)),
                    '--transition-randomness',  str(params.get('randomness', 0.0)),
                    '--transition-return-factor',
                    str(params.get('transition_return_factor', 2.5)),
                ]
        # Pause-Trimming
        pause_trim_enabled = bool(params.get('pause_trim_enabled', False))
        if pause_trim_enabled:
            _cut_mode = params.get('pause_cut_mode', 'middle')
            builder_args += [
                '--pause-trim',
                '--max-pause',           str(params.get('max_pause', 1.0)),
                '--pause-search-radius', str(params.get('pause_search_radius', 3.0)),
                '--pause-min-duration',  str(params.get('pause_min_duration', 0.3)),
                '--pause-cut-mode',      'middle' if _cut_mode == 'random' else _cut_mode,
                '--audio-trims-out',     str(work_dir / 'audio_trims.json'),
            ]

        # Pause-Cutaway (Stille-Cutaway)
        if pause_cutaway_enabled:
            builder_args += [
                '--pause-cutaway-json-out',  str(work_dir / 'pause_cutaways.json'),
                '--pause-cutaway-min-pause', str(params.get('pause_cutaway_min_pause', 2.0)),
            ]

        run(builder_args, "Base-EDL aus Audio")

    # ── Schritt 2: Nodding-Analyse für ALLE Kameras ───────────────────────────
    # Off-Sections beschränken die (teure) Nicken-Analyse auf die Frames, in denen
    # eine Kamera einen Zuhörer zeigt. Im N-Pfad schreibt build_base_edl_n sie je
    # Kamera (<video_stem>_off_sections.json) — sonst liefe die Analyse bei 3+
    # Kameras aufs volle Material. Im binären Pfad nur CAM1/CAM2 (Rest voll).
    if use_n_path:
        off_sections_map = {
            cp: work_dir / (Path(cp).stem + '_off_sections.json')
            for cp in cam_paths
        }
    else:
        off_sections_map = {
            cam1_path: cam1_off_sections,
            cam2_path: cam2_off_sections,
        }
    # params.json für Subprozesse schreiben (Analyzer, etc.)
    params_json_path = work_dir / 'params.json'
    params_json_path.write_text(json.dumps(params, indent=2), encoding='utf-8')

    mouth_npz = {cp: work_dir / (Path(cp).stem + '_mouth.npz') for cp in (cam1_path, cam2_path)}
    if not skip_analysis:
        analyzer = str(SCRIPT_DIR / 'video_reaction_analyzer_v2.4.py')
        for i, cp in enumerate(cam_paths):
            nodding_enabled = cam_nodding[i] if i < len(cam_nodding) else True
            wants_mouth = mouth_enabled and cp in mouth_npz
            if not nodding_enabled and not wants_mouth:
                print(f"\n  Reaktionsanalyse CAM{i + 1} übersprungen (Nicken und Mund aus)")
                continue
            # Totalen liefern nie eigene Reaktions-Cutaways: PASS 2 sammelt
            # ausschliesslich aus close_cams (add_reactions_to_edl.py:183-189).
            # Die Analyse lief dort trotzdem — rund 30 min pro Totale und Lauf,
            # deren Ergebnis anschliessend verworfen wurde.
            #
            # Bedingung bewusst aus dem VERBRAUCHER abgeleitet und nicht neu
            # gebildet: waeren es zwei Urteile darueber, was eine Totale ist,
            # koennten sie auseinanderlaufen. Eine Cam, die fuer mindestens eine
            # Person die engste Einstellung ist, gilt bereits als 'close'
            # ("Close gewinnt", EngineController.camRoles) — ein Zwei-Personen-Bild
            # wird also nur uebersprungen, wenn es fuer NIEMANDEN die engste ist.
            if i < len(cam_types) and cam_types[i] == 'wide':
                print(f"\n  Reaktionsanalyse CAM{i + 1} übersprungen (Totale — "
                      f"PASS 2 verwendet nur Close-Kameras)")
                continue
            json_out = work_dir / (Path(cp).stem + '_reactions.json')
            cam_params = params_json_path
            if not nodding_enabled:
                # Nur fuer die Mund-Daten analysiert → keine Nicken-Erkennung, sonst
                # entstuenden Nicken-Cutaways auf einer Kamera, wo sie aus sind.
                cam_params = work_dir / 'params_mouth_only.json'
                cam_params.write_text(json.dumps({**params, 'nodding_enabled': False}, indent=2),
                                      encoding='utf-8')
            args_list = [analyzer, cp, '--output', str(json_out), '--params', str(cam_params)]
            if wants_mouth:
                args_list += ['--mouth-out', str(mouth_npz[cp])]
            off_sec = off_sections_map.get(cp)
            if off_sec and off_sec.exists():
                args_list += ['--off-sections', str(off_sec)]
            args_list += ['--preview-path', f'/tmp/multicam_preview_cam{i + 1}.jpg']
            # max_faces aus MIC-Zuordnung ableiten: Cam mit 2 zugewiesenen Mics →
            # 2 Personen erwartet → MediaPipe darf 2 Gesichter parallel tracken.
            mic_idxs_for_cam = cam_mic_map[i] if i < len(cam_mic_map) else []
            cam_max_faces = max(1, len(mic_idxs_for_cam))
            args_list += ['--max-faces', str(cam_max_faces)]
            if auto_accuracy:
                args_list += ['--auto-accuracy']
            if lut_path:
                args_list += ['--lut', lut_path]
            run(args_list, f"Reaktionsanalyse CAM{i + 1} ({Path(cp).name})")

    # ── Schritt 3: Cameras-JSON bauen und Cutaways einfügen ──────────────────
    cam1_speaking_json = work_dir / (Path(cam1_path).stem + '_speaking.json')
    cam2_speaking_json = work_dir / (Path(cam2_path).stem + '_speaking.json')
    speaking_jsons = {cam1_path: cam1_speaking_json, cam2_path: cam2_speaking_json}

    # ── Schritt 2a: Einwürfe aus der Analysespur ─────────────────────────────
    # Erkennung auf der Analysespur (Mikro ohne Übersprechen/Rauschen). Nur binärer
    # Pfad, genau ein Mikro je Kamera. Geht das nicht → Lauf ohne Sprachreaktionen.
    # Einwurf-Listen eines früheren Laufs im (wiederverwendeten) Arbeitsordner nie
    # übernehmen: scheitert die Erkennung, läuft dieser Lauf ohne Sprachreaktionen.
    for _sp in speaking_jsons.values():
        _sp.unlink(missing_ok=True)
    if analysespur_enabled:
        if (len(mic_cam1_paths) != 1 or len(mic_cam2_paths) != 1
                or mic_cam1_paths[0] == mic_cam2_paths[0]):
            if speaking_enabled:
                print("\n  ⚠️  Sprachreaktionen brauchen je Kamera ein eigenes Mikro — "
                      "dieser Lauf ist ohne Sprachreaktionen.")
        else:
            try:
                from einwurf_analysespur import add_analysespur_reactions
                _ac = [{'video': cp, 'cam_key': f'CAM{cam_paths.index(cp) + 1}',
                        'mic': m[0], 'mic_key': f'MIC{mic_paths.index(m[0]) + 1}',
                        'speaking_json': str(speaking_jsons[cp])}
                       for cp, m in ((cam1_path, mic_cam1_paths), (cam2_path, mic_cam2_paths))]
                print("\n  Analysespur: Einwürfe, Pausen, Sprecherwechsel...")
                add_analysespur_reactions(base_edl, _ac, offsets, fps, params, work_dir)
            except Exception as e:
                # Darf den Lauf nie kaputt machen → dann eben ohne Sprachreaktionen
                print(f"  ⚠️  Analysespur übersprungen: {e}"
                      + (" — dieser Lauf ist ohne Sprachreaktionen." if speaking_enabled else ""))

    # ── Schritt 2b: „Mund + Mikro" — Einwuerfe in die Sprachreaktionen eintragen ─
    if mouth_enabled:
        try:
            from mouth_reactions import add_mouth_reactions
            _mc = []
            for cp, mics_for in ((cam1_path, mic_cam1_paths), (cam2_path, mic_cam2_paths)):
                m = mics_for[0]
                _mc.append({'video': cp, 'cam_key': f'CAM{cam_paths.index(cp) + 1}',
                            'mic': m, 'mic_key': f'MIC{mic_paths.index(m) + 1}',
                            'mouth_npz': str(mouth_npz[cp]),
                            'speaking_json': str(speaking_jsons[cp])})
            print("\n  Mund + Mikro: Einwürfe der Zuhörer suchen...")
            add_mouth_reactions(base_edl, _mc, offsets, fps, params)
        except Exception as e:
            # Beta-Funktion darf den Lauf nie kaputt machen → ohne sie weiter
            print(f"  ⚠️  Mund + Mikro übersprungen: {e}")

    cameras_config = []
    for i, cp in enumerate(cam_paths):
        mic_idxs = cam_mic_map[i] if i < len(cam_mic_map) else []
        mics_for_cam = [mic_paths[j] for j in mic_idxs if j < len(mic_paths)]
        entry = {
            'name':              Path(cp).name,
            'video':             cp,
            'type':              cam_types[i]   if i < len(cam_types)   else 'close',
            'nodding_detection': cam_nodding[i] if i < len(cam_nodding) else True,
            'mics':              mics_for_cam,
            # Stufenleiter statt zweier Klassen: Anzahl gezeigter Personen,
            # kleiner = enger. Erlaubt Regeln wie „eine Stufe weiter", ohne dass
            # sie feste Groessennamen oder Kameras kennen muessen.
            # Siehe shot_sizes.py und brain/Bildsprache.md.
            'shot_level':        max(1, len(mics_for_cam)),
            'reactions':         str(work_dir / (Path(cp).stem + '_reactions.json')),
        }
        sp = speaking_jsons.get(cp)
        if speaking_enabled and sp and sp.exists():
            entry['speaking_reactions'] = str(sp)
        cameras_config.append(entry)

    # Rollen SELBST bestimmen statt --cam-types zu vertrauen. Die App berechnet
    # dieselbe Regel (camRoles), aber eine Invariante, die nur im Aufrufer lebt,
    # ist keine Invariante — genau daran krankte die Diarisierungs-Reihenfolge.
    # Vorerst nur ein Abgleich: weicht etwas ab, will man es SEHEN, bevor man das
    # Verhalten umstellt.
    _own_roles = camera_roles(cameras_config)
    for _c in cameras_config:
        _sent, _own = _c['type'], _own_roles.get(_c['name'])
        if _own != 'unused' and _sent != _own:
            print(f"  ⚠ Rollen-Abweichung {_c['name']}: App sagt '{_sent}', "
                  f"aus den Zuordnungen folgt '{_own}' "
                  f"({_c['shot_level']} Person(en) im Bild)")

    cameras_json_path = work_dir / 'cameras.json'
    cameras_json_path.write_text(
        __import__('json').dumps(cameras_config, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )

    final_edl = work_dir / 'final.edl'
    add_reactions_args = [
        str(SCRIPT_DIR / 'add_reactions_to_edl.py'),
        '--cameras-json', str(cameras_json_path),
        '--resolve-edl',  str(base_edl),
        '--output',       str(final_edl),
        '--params',       str(params_json_path),
        '--fps',          str(fps),
    ]
    pause_cutaways_json = work_dir / 'pause_cutaways.json'
    if pause_cutaway_enabled and pause_cutaways_json.exists():
        add_reactions_args += ['--pause-cutaways', str(pause_cutaways_json)]
    if clip_filter_enabled:
        # User-editierte Prompts bevorzugen (Application Support), sonst die
        # gebündelten Defaults — Settings-Tab „CLIP" schreibt die User-Datei.
        add_reactions_args += ['--clip-filter-config', str(effective_clip_prompts_path())]
    run(add_reactions_args, "Cutaways einfügen")

    return final_edl


# ── Entry point ───────────────────────────────────────────────────────────────

def _parse_cam_list(arg, n_cams: int, default: str) -> list:
    """Parst z.B. --cam-types 'close close wide' → ['close', 'close', 'wide']."""
    if arg is None:
        return [default] * n_cams
    result = list(arg[:n_cams])
    while len(result) < n_cams:
        result.append(default)
    return result


def _parse_cam_nodding(arg, n_cams: int) -> list:
    """Parst --cam-nodding 'true true false' → [True, True, False]."""
    if arg is None:
        return [True] * n_cams
    result = [s.lower() not in ('false', '0', 'no') for s in arg[:n_cams]]
    while len(result) < n_cams:
        result.append(True)
    return result


def _parse_cam_mics(cam_mics_arg, n_cams: int, n_mics: int) -> list:
    """
    Parst --cam-mics in List[List[int]].

    Beispiele:
      None         → [[1], [0]]          (bisheriger Default)
      ["1", "0"]   → [[1], [0]]
      ["0,1", "2"] → [[0, 1], [2]]
    """
    if cam_mics_arg is None:
        return [[min(1, n_mics - 1)], [0]]
    result = []
    for spec in cam_mics_arg[:n_cams]:
        indices = [int(x.strip()) for x in spec.split(',') if x.strip()]
        result.append(indices)
    while len(result) < n_cams:
        result.append([])
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Multicam Workflow: Bin → Sync → Analyse → Cut-Timeline'
    )
    parser.add_argument('--bin',    required=True, help='Media Pool Bin-Name')
    parser.add_argument('--output', required=True, help='Name der fertigen Cut-Timeline')
    parser.add_argument('--fps',    type=float, default=25.0)
    parser.add_argument('--params', default=None,
                        help='Pfad zur params.json mit Modul-Parametern')
    parser.add_argument('--skip-analysis', action='store_true')
    parser.add_argument('--skip-base-edl', action='store_true')
    parser.add_argument('--skip-clip-filter', action='store_true',
                        help='CLIP-Bilderkennungs-Filter für ungünstige Cutaways überspringen '
                             '(spart ~30 min CPU/GPU bei Test-Läufen, überschreibt params.clip_filter_enabled).')
    parser.add_argument('--sync-from-timeline', action='store_true',
                        help='Sync-Offsets aus der aktuell aktiven Resolve-Timeline lesen, '
                             'statt sie per Waveform-Cross-Correlation zu bestimmen.')
    parser.add_argument('--cam-mics', nargs='+', default=None,
                        help='MIC-Zuordnung pro Kamera als "INDEX[,INDEX]" je CAM. '
                             'Reihenfolge = CAM1, CAM2, ... '
                             'Beispiele: "1 0" (Default) oder "0,1 2" (CAM1→MIC1+MIC2, CAM2→MIC3)')
    parser.add_argument('--cam-types', nargs='+', default=None,
                        help='Kamera-Typ je CAM: "close" (default) oder "wide". '
                             'Beispiel: "close close wide" für 2 Close-Ups + 1 Totale')
    parser.add_argument('--cam-nodding', nargs='+', default=None,
                        help='Nodding-Analyse je CAM: "true" (default) oder "false". '
                             'Beispiel: "true true false" (deaktiviert für CAM3)')
    parser.add_argument('--speaking-mode', choices=['rms', 'peak'], default=None,
                        help='Überschreibt speaking_mode aus params.json')
    parser.add_argument('--mic-cam1', type=int, default=None,
                        help='MIC-Index für CAM1 (Legacy, nutze --cam-mics)')
    parser.add_argument('--mic-cam2', type=int, default=None,
                        help='MIC-Index für CAM2 (Legacy, nutze --cam-mics)')
    parser.add_argument('--auto-accuracy', action='store_true',
                        help='OBSOLET — Face-Size-Adaption ist immer aktiv. Flag wird ignoriert.')
    parser.add_argument('--lut', default=None,
                        help='Pfad zu einer .cube LUT-Datei für die Mediapipe-Analyse')
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

    # 1b. FPS-Konsistenz prüfen — alle Cams müssen die Timeline-FPS haben.
    # Bei Mismatch entstehen sonst durch Resolves Auto-Speed-Adaption
    # Source/Record-Drifts (siehe modules/multicam_cutter/CLAUDE.md "Gotchas").
    fps_mismatches = []
    for cam in cams:
        cam_fps_str = cam.GetClipProperty('FPS') or ''
        try:
            cam_fps = float(cam_fps_str)
        except ValueError:
            cam_fps = None
        if cam_fps is None or abs(cam_fps - args.fps) > 0.01:
            fps_mismatches.append((cam.GetName(),
                                   cam.GetClipProperty('File Path') or '',
                                   cam_fps_str))
    if fps_mismatches:
        print(f"\n✗ FPS-MISMATCH — Abbruch.")
        print(f"  Timeline-FPS: {args.fps}")
        print(f"  Folgende Kamera(s) haben abweichende Source-FPS:")
        for name, path, fps in fps_mismatches:
            print(f"    • {name} ({path}): FPS={fps}")
        print(f"\n  Resolve macht bei FPS-Mismatch eine automatische Speed-Adaption,")
        print(f"  die Source-/Record-Frames inkonsistent macht und zu Drift sowie")
        print(f"  Standbild am Timeline-Ende führt.")
        print(f"\n  Lösung: betroffene Datei(en) auf {args.fps} fps konvertieren, z.B.:")
        for _, path, _ in fps_mismatches:
            from pathlib import Path as _P
            out = str(_P(path).with_stem(_P(path).stem + f'_{int(args.fps)}fps'))
            print(f"    ffmpeg -i \"{path}\" -vf \"fps={args.fps}\" -c:v libx264 "
                  f"-crf 18 -c:a aac \"{out}\"")
        return 42  # Spezial-Exit-Code: FPS-Mismatch (UI kann das abfangen)

    # 2. Sync — entweder aus aktiver Resolve-Timeline oder per Waveform-Korrelation
    cam1_path = cams[0].GetClipProperty('File Path')
    cam2_path = cams[1].GetClipProperty('File Path')
    mic_paths = [m.GetClipProperty('File Path') for m in mics]
    cam_paths_all = [c.GetClipProperty('File Path') for c in cams]

    print()
    if args.sync_from_timeline:
        from resolve_bridge.timeline_reader import read_offsets_from_timeline
        try:
            offsets = read_offsets_from_timeline(cam_paths_all, mic_paths)
        except RuntimeError as e:
            print(f"\nFEHLER beim Lesen der Sync-Timeline: {e}")
            return 1
        print("Sync aus aktiver Resolve-Timeline:")
        for label, frames in offsets.items():
            print(f"  {label}: {frames:+d} frames ({frames / args.fps:+.3f}s)")
    else:
        try:
            offsets = sync_sources(cam_paths_all, mic_paths, fps=args.fps)
        except SyncError as e:
            print(f"\nFEHLER: {e}")
            return 1

    # 3. Analyse-Pipeline
    n_cams      = len(cams)
    # --mic-cam1/--mic-cam2 als Fallback wenn --cam-mics nicht gesetzt
    _cam_mics_arg = args.cam_mics
    if _cam_mics_arg is None and (args.mic_cam1 is not None or args.mic_cam2 is not None):
        _cam_mics_arg = [
            str(args.mic_cam1 if args.mic_cam1 is not None else min(1, len(mic_paths) - 1)),
            str(args.mic_cam2 if args.mic_cam2 is not None else 0),
        ]
    cam_mic_map = _parse_cam_mics(_cam_mics_arg,   n_cams, len(mic_paths))
    cam_types   = _parse_cam_list(args.cam_types,   n_cams, 'close')
    cam_nodding = _parse_cam_nodding(args.cam_nodding, n_cams)
    # Parameter laden (JSON aus UI oder leeres Dict als Fallback)
    _params = {}
    if args.params:
        _params = json.loads(Path(args.params).read_text())

    # Debug-Settings aus config.ini mergen (einzige Sektion die dort verbleibt)
    _debug_ini = ROOT / 'config' / 'config.ini'
    if _debug_ini.exists():
        import configparser as _cp
        _dbg_cfg = _cp.ConfigParser()
        _dbg_cfg.read(str(_debug_ini), encoding='utf-8')
        if _dbg_cfg.has_section('Debug'):
            _params.setdefault('debug_limit_frames',
                               _dbg_cfg.getboolean('Debug', 'limit_frames', fallback=False))
            _params.setdefault('debug_max_analysis_frames',
                               _dbg_cfg.getint('Debug', 'max_analysis_frames', fallback=10000))

    # CLI-Override: CLIP-Filter für diesen Lauf überspringen
    if args.skip_clip_filter:
        if _params.get('clip_filter_enabled'):
            print("  ℹ️  --skip-clip-filter aktiv: CLIP-Filter wird übersprungen.")
        _params['clip_filter_enabled'] = False

    import hashlib
    _src_hash = hashlib.md5(cam1_path.encode()).hexdigest()[:12]
    work_dir = Path(f'/tmp/resolve-toolkit/{_src_hash}')
    work_dir.mkdir(parents=True, exist_ok=True)

    # ── Dev-Modus: Console-Capture starten ──────────────────────────────────
    _dev_console_log = None
    try:
        from shared.dev_mode import is_dev_mode
        if is_dev_mode():
            _console_log_path = work_dir / 'console.log'
            _dev_console_log = open(_console_log_path, 'w', encoding='utf-8')

            class _TeeWriter:
                """Schreibt gleichzeitig auf Original-Stream und Log-Datei."""
                def __init__(self, original, log_file):
                    self._original = original
                    self._log = log_file
                def write(self, text):
                    self._original.write(text)
                    self._log.write(text)
                def flush(self):
                    self._original.flush()
                    self._log.flush()

            sys.stdout = _TeeWriter(sys.stdout, _dev_console_log)
            sys.stderr = _TeeWriter(sys.stderr, _dev_console_log)
    except ImportError:
        pass

    def _close_dev_console():
        """Stellt stdout/stderr wieder her und schliesst das Console-Log."""
        if _dev_console_log is not None and not _dev_console_log.closed:
            if hasattr(sys.stdout, '_original'):
                sys.stdout = sys.stdout._original
            if hasattr(sys.stderr, '_original'):
                sys.stderr = sys.stderr._original
            _dev_console_log.close()

    try:
        final_edl = run_analysis(
            [cam1_path, cam2_path], mic_paths, offsets,
            args.fps, work_dir, _params,
            args.skip_analysis, args.skip_base_edl,
            cam_mic_map=cam_mic_map,
            cam_types=cam_types,
            cam_nodding=cam_nodding,
            speaking_mode_override=args.speaking_mode,
            auto_accuracy=args.auto_accuracy,
            lut_path=args.lut,
        )
    except RuntimeError as e:
        print(f"\nFEHLER in Analyse: {e}")
        _close_dev_console()
        return 1

    # 5. Cut-Timeline via AppendToTimeline aufbauen
    cam_items = {
        'CAM1': (cams[0], cam1_path),
        'CAM2': (cams[1], cam2_path),
    }
    print(f"\nParse finale EDL: {final_edl.name}")
    try:
        cut_events, skipped_gap_frames = parse_edl(final_edl, cam_items, args.fps)
    except (ValueError, Exception) as e:
        print(f"FEHLER beim EDL-Parsen: {e}")
        _close_dev_console()
        return 1

    if not cut_events:
        print("FEHLER: Keine Cut-Events aus EDL gelesen.")
        _close_dev_console()
        return 1

    # ── Pause-Trimming anwenden (auf finale cut_events, nach Cutaway-Einfügung) ──
    audio_trims_path = work_dir / 'audio_trims.json'
    audio_keeps_path = work_dir / 'audio_keeps.json'
    audio_keeps = None
    if audio_trims_path.exists():
        try:
            from pause_trim_edl import load_pauses, apply_pauses_to_cut_events
            raw = json.loads(audio_trims_path.read_text())
            # Nur Pause-Dicts verarbeiten (nicht versehentlich audio_keeps)
            if isinstance(raw, list) and raw and isinstance(raw[0], dict):
                pauses = raw
            else:
                pauses = None
            if pauses:
                cut_events, audio_keeps = apply_pauses_to_cut_events(
                    cut_events, pauses, args.fps,
                    max_pause_s=float(_params.get('max_pause', 1.0)),
                    cut_mode=_params.get('pause_cut_mode', 'middle'),
                    min_event_s=float(_params.get('cleanup_dur', 1.5)),
                    cut_offset_s=float(_params.get('pause_cut_offset_s', 1.0)),
                )
                if audio_keeps:
                    # Audio-Keeps in separate Datei speichern (nicht audio_trims ueberschreiben!)
                    audio_keeps_path.write_text(json.dumps(audio_keeps), encoding='utf-8')
                    print(f"  Audio-Keeps: {len(audio_keeps)} Segmente")
        except Exception as e:
            print(f"  ⚠️  Pause-Trim Fehler: {e}")
            audio_keeps_path.unlink(missing_ok=True)

    cut_tl = build_cut_timeline(
        mp, args.output, cut_events, mics,
        offsets=offsets, cam_items=cam_items, fps=args.fps,
        skipped_gap_frames=skipped_gap_frames,
        bin_folder=bin_folder,
        audio_trims_path=audio_keeps_path,
    )
    project.SetCurrentTimeline(cut_tl)
    time.sleep(0.3)
    pm.SaveProject()
    print(f"  '{args.output}' angelegt, aktiviert und gespeichert.")

    print(f"\nWorkflow abgeschlossen.")
    print(f"  Cut-Timeline: {args.output}")

    # ── Dev-Modus: Console-Capture beenden + Episode-Archiv erstellen ────────
    _close_dev_console()
    if _dev_console_log is not None:
        import shutil
        from datetime import date
        _safe_name = re.sub(r'[^\w\-]', '_', args.output or 'unnamed')
        _archive_dir = Path(os.path.expanduser(
            f'~/.resolve-toolkit/runs/{date.today().isoformat()}_{_safe_name}'
        ))
        _archive_dir.mkdir(parents=True, exist_ok=True)
        _archived = 0
        for f in work_dir.iterdir():
            if f.suffix in ('.edl', '.json', '.log'):
                shutil.copy2(f, _archive_dir / f.name)
                _archived += 1
        print(f"\n  Dev: Episode-Archiv -> {_archive_dir}")
        print(f"       {_archived} Dateien archiviert")

    return 0


if __name__ == '__main__':
    sys.exit(main())
