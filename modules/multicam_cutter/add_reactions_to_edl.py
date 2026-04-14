#!/usr/bin/env python3
"""
Add Reactions to EDL v4.0 — N-Kamera-Architektur

Multi-Pass:
- Pass 1: Original-EDL parsen, Sections je Kamera sammeln
- Pass 2: Für jede ON-Kamera → Cutaways von allen anderen Kameras
- Pass 3: Cleanup zu kurze Events
- Pass 4: Split zu lange Shots

Eingabe (--cameras-json):
[
  {"name": "C5576.MP4", "video": "/path/C5576.MP4",
   "reactions": "/path/C5576_reactions.json",
   "speaking_reactions": "/path/C5576_speaking.json"},  # optional
  ...
]
"""

import json
import argparse
import re
import random
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import configparser
import os
import subprocess


def load_config(config_path='config.ini'):
    config = configparser.ConfigParser()
    for path in [config_path, Path(__file__).parent / 'config.ini', Path.cwd() / 'config.ini']:
        if os.path.exists(path):
            config.read(path)
            print(f"✓ Config geladen: {path}")
            return config
    print("⚠️  config.ini nicht gefunden, nutze Default-Werte")
    return None


def timecode_to_frames(tc: str, fps: float = 25.0) -> int:
    parts = tc.split(':')
    total = (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * fps + int(parts[3])
    return int(total)


def frames_to_timecode(frames: int, fps: float = 25.0) -> str:
    if frames < 0:
        frames = 0
    total_seconds = frames / fps
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    f = int(frames % fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def get_video_timecode_with_ffprobe(video_path: str) -> Optional[str]:
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
        print(f"    ⚠️  ffprobe Fehler: {e}")
        return None


class EDLEvent:
    def __init__(self, event_num: int, clip_name: str,
                 source_in: str, source_out: str,
                 record_in: str, record_out: str, fps: float = 25.0,
                 reason: str = "speaker"):
        self.event_num = event_num
        self.clip_name = clip_name
        self.source_in = source_in
        self.source_out = source_out
        self.record_in = record_in
        self.record_out = record_out
        self.fps = fps
        self.reason = reason
        self.source_in_frame  = timecode_to_frames(source_in, fps)
        self.source_out_frame = timecode_to_frames(source_out, fps)
        self.record_in_frame  = timecode_to_frames(record_in, fps)
        self.record_out_frame = timecode_to_frames(record_out, fps)

    def duration_frames(self) -> int:
        return self.record_out_frame - self.record_in_frame

    def __repr__(self):
        return f"Event {self.event_num}: {self.clip_name} R[{self.record_in}-{self.record_out}]"


def parse_resolve_edl(edl_path: str, fps: float = 25.0) -> List[EDLEvent]:
    print(f"\n📋 PASS 1: Parse Resolve EDL")
    print(f"  File: {edl_path}")
    events = []
    with open(edl_path, 'r') as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r'^(\d+)\s+\w+\s+V\s+C\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)', line)
        if m:
            event_num = int(m.group(1))
            if i + 1 < len(lines):
                cn = re.match(r'\* FROM CLIP NAME:\s*(.+)', lines[i + 1].strip())
                if cn:
                    events.append(EDLEvent(
                        event_num=event_num,
                        clip_name=cn.group(1).strip(),
                        source_in=m.group(2), source_out=m.group(3),
                        record_in=m.group(4), record_out=m.group(5),
                        fps=fps,
                    ))
        i += 1
    print(f"  ✓ {len(events)} Video-Events gefunden")
    return events


def load_reactions(json_path: str) -> Tuple[List[Dict], float]:
    with open(json_path, 'r') as f:
        data = json.load(f)
    return data.get('reactions', []), data.get('fps', 25.0)


def calculate_reference_frames(
    events: List[EDLEvent],
    cameras: List[Dict],   # [{'name': str, 'video': str}, ...]
    fps: float = 25.0,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Berechnet reference_frames und timeline_zero_video_frames für alle Kameras.

    reference_frames[clip_name]           = embedded TC in Frames
    timeline_zero_video_frames[clip_name] = welcher Video-Frame bei Timeline 0 liegt
    """
    video_paths = {cam['name']: cam['video'] for cam in cameras}

    reference_frames: Dict[str, int] = {}
    timeline_zero_video_frames: Dict[str, int] = {}

    first_events: Dict[str, EDLEvent] = {}
    for event in events:
        if event.clip_name not in first_events and event.record_in_frame < event.record_out_frame:
            first_events[event.clip_name] = event

    for clip_name, event in first_events.items():
        video_path = video_paths.get(clip_name)
        embedded_tc = get_video_timecode_with_ffprobe(video_path) if video_path else None

        if embedded_tc:
            ref = timecode_to_frames(embedded_tc, fps)
            reference_frames[clip_name] = ref
            tzvf = (event.source_in_frame - ref) - event.record_in_frame
            timeline_zero_video_frames[clip_name] = tzvf
            print(f"    {clip_name}: TC={embedded_tc} ({ref} f), tl0={tzvf}")
        else:
            ref = event.source_in_frame - event.record_in_frame
            reference_frames[clip_name] = ref
            timeline_zero_video_frames[clip_name] = 0
            print(f"    {clip_name}: {ref} (kein embedded TC ⚠️)")

    return reference_frames, timeline_zero_video_frames


def build_events_with_cutaways(
    section_start: int,
    section_end: int,
    section_video_start: int,
    on_clip: str,
    on_reference_frame: int,
    cutaway_cams: List[Dict],  # [{'name', 'reference_frame', 'timeline_zero_video', 'reactions'}]
    config: Dict,
    fps: float,
) -> List[EDLEvent]:
    """
    Baut Events für eine Section mit Cutaways von einer oder mehreren OFF-Kameras.

    cutaway_cams enthält alle Kameras die als Cutaway-Quelle infrage kommen.
    Bei mehreren Reaktionen gleichzeitig wird die mit höchster Confidence gewählt.
    """
    min_shot_frames          = int(config['min_shot_duration'] * fps)
    reaction_duration_frames = int(config['reaction_min_duration'] * fps)
    max_shot_frames          = int(config['max_shot_duration'] * fps)
    min_confidence           = config['min_confidence']
    speaking_min_confidence  = config.get('speaking_min_confidence', min_confidence)
    cluster_max_gap          = int(config.get('cluster_max_gap_frames', 75))
    pre_roll_frames          = int(config.get('pre_roll_frames', 0))
    cutaway_enabled          = config['cutaway_enabled']

    # Reaktionen aller OFF-Kameras sammeln
    valid_reactions = []
    for cam in cutaway_cams:
        tzvf = cam['timeline_zero_video']
        for reaction in cam['reactions']:
            rtype      = reaction['type']
            confidence = reaction['confidence']
            timeline_frame = reaction['frame'] - tzvf

            if not cutaway_enabled.get(rtype, False):
                continue
            threshold = speaking_min_confidence if rtype == 'speaking_reaction' else min_confidence
            if confidence < threshold:
                continue
            if timeline_frame < 0:
                continue
            if section_start <= timeline_frame < section_end:
                valid_reactions.append({
                    'timeline_frame': timeline_frame,
                    'type':           rtype,
                    'confidence':     confidence,
                    'cam':            cam,
                })

    # Sortieren: erst nach Position, dann nach Confidence absteigend
    valid_reactions.sort(key=lambda x: (x['timeline_frame'], -x['confidence']))

    events: List[EDLEvent] = []
    current_pos   = section_start
    last_cut_frame = section_start

    for i, reaction in enumerate(valid_reactions):
        rtype = reaction['type']

        # Cluster-Start suchen (rückwärts, gleicher Typ)
        cluster_start = reaction['timeline_frame']
        for j in range(i - 1, -1, -1):
            if valid_reactions[j]['type'] != rtype:
                break
            if valid_reactions[j + 1]['timeline_frame'] - valid_reactions[j]['timeline_frame'] <= cluster_max_gap:
                cluster_start = valid_reactions[j]['timeline_frame']
            else:
                break

        cutaway_frame = max(cluster_start - pre_roll_frames, section_start)

        if cutaway_frame - last_cut_frame < min_shot_frames:
            continue

        # ON-Clip bis Cutaway
        if cutaway_frame > current_pos:
            vi = section_video_start + (current_pos - section_start)
            vo = section_video_start + (cutaway_frame - section_start)
            events.append(EDLEvent(
                event_num=0, clip_name=on_clip,
                source_in=frames_to_timecode(on_reference_frame + vi, fps),
                source_out=frames_to_timecode(on_reference_frame + vo, fps),
                record_in=frames_to_timecode(current_pos, fps),
                record_out=frames_to_timecode(cutaway_frame, fps),
                fps=fps, reason="speaker",
            ))

        # OFF-Cutaway — Kamera mit höchster Confidence dieser Position
        off_cam               = reaction['cam']
        off_clip              = off_cam['name']
        off_reference_frame   = off_cam['reference_frame']
        off_tzvf              = off_cam['timeline_zero_video']

        randomness = config.get('cutaway_randomness', 0.0)
        this_cutaway_frames = int(
            reaction_duration_frames * (1.0 + random.uniform(0.0, randomness))
        ) if randomness > 0 else reaction_duration_frames
        cutaway_end = min(cutaway_frame + this_cutaway_frames, section_end)

        off_vi = off_tzvf + cutaway_frame
        off_vo = off_tzvf + cutaway_end
        events.append(EDLEvent(
            event_num=0, clip_name=off_clip,
            source_in=frames_to_timecode(off_reference_frame + off_vi, fps),
            source_out=frames_to_timecode(off_reference_frame + off_vo, fps),
            record_in=frames_to_timecode(cutaway_frame, fps),
            record_out=frames_to_timecode(cutaway_end, fps),
            fps=fps, reason=f"reaction_{rtype}",
        ))

        last_cut_frame = cutaway_end
        current_pos    = cutaway_end

    # Rest der Section
    if current_pos < section_end:
        if section_end - current_pos > max_shot_frames:
            # Forced Cutaways: immer erste OFF-Kamera als Ziel
            off_cam = cutaway_cams[0] if cutaway_cams else None
            while current_pos < section_end:
                next_cut = min(current_pos + max_shot_frames, section_end)
                vi = section_video_start + (current_pos - section_start)
                vo = section_video_start + (next_cut - section_start)
                events.append(EDLEvent(
                    event_num=0, clip_name=on_clip,
                    source_in=frames_to_timecode(on_reference_frame + vi, fps),
                    source_out=frames_to_timecode(on_reference_frame + vo, fps),
                    record_in=frames_to_timecode(current_pos, fps),
                    record_out=frames_to_timecode(next_cut, fps),
                    fps=fps, reason="speaker",
                ))
                if next_cut >= section_end:
                    break
                cutaway_end = min(next_cut + reaction_duration_frames, section_end)
                if off_cam:
                    off_vi = off_cam['timeline_zero_video'] + next_cut
                    off_vo = off_cam['timeline_zero_video'] + cutaway_end
                    events.append(EDLEvent(
                        event_num=0, clip_name=off_cam['name'],
                        source_in=frames_to_timecode(off_cam['reference_frame'] + off_vi, fps),
                        source_out=frames_to_timecode(off_cam['reference_frame'] + off_vo, fps),
                        record_in=frames_to_timecode(next_cut, fps),
                        record_out=frames_to_timecode(cutaway_end, fps),
                        fps=fps, reason="max_time",
                    ))
                current_pos = cutaway_end
        else:
            vi = section_video_start + (current_pos - section_start)
            vo = section_video_start + (section_end - section_start)
            events.append(EDLEvent(
                event_num=0, clip_name=on_clip,
                source_in=frames_to_timecode(on_reference_frame + vi, fps),
                source_out=frames_to_timecode(on_reference_frame + vo, fps),
                record_in=frames_to_timecode(current_pos, fps),
                record_out=frames_to_timecode(section_end, fps),
                fps=fps, reason="speaker",
            ))

    return events


def cleanup_short_events(events: List[EDLEvent], min_duration: float, fps: float) -> List[EDLEvent]:
    print(f"\n🧹 PASS 3: Cleanup kurzer Events")
    print(f"  Min Duration: {min_duration}s ({int(min_duration * fps)} Frames)")
    min_frames = int(min_duration * fps)
    cleaned = []
    removed = 0
    for event in events:
        if event.duration_frames() < min_frames and cleaned:
            prev = cleaned[-1]
            source_offset = prev.source_in_frame - prev.record_in_frame
            prev.record_out       = event.record_out
            prev.record_out_frame = event.record_out_frame
            prev.source_out_frame = source_offset + event.record_out_frame
            prev.source_out       = frames_to_timecode(prev.source_out_frame, fps)
            removed += 1
            print(f"  ✗ Entfernt: Event @ {event.record_in} ({event.duration_frames()} Frames)")
        else:
            cleaned.append(event)
    print(f"  ✓ {removed} entfernt, {len(cleaned)} verbleiben")
    return cleaned


def split_long_shots(
    events: List[EDLEvent],
    max_shot_duration: float,
    cutaway_duration: float,
    reference_frames: Dict[str, int],
    timeline_zero_video_frames: Dict[str, int],
    all_cam_names: List[str],
    fps: float,
) -> List[EDLEvent]:
    print(f"\n✂️  PASS 4: Split zu lange Shots")
    threshold_frames = int((max_shot_duration + 3.0) * fps)
    cutaway_frames   = int(cutaway_duration * fps)
    new_events = []
    split_count = 0

    for event in events:
        duration = event.duration_frames()
        if duration <= threshold_frames:
            new_events.append(event)
            continue

        # Nächste verfügbare Kamera als Cutaway-Ziel
        others = [c for c in all_cam_names if c != event.clip_name]
        if not others:
            new_events.append(event)
            continue
        other_clip = others[0]

        if other_clip not in reference_frames:
            new_events.append(event)
            continue

        split_count += 1
        middle    = event.record_in_frame + (duration // 2)
        cut_start = middle - (cutaway_frames // 2)
        cut_end   = cut_start + cutaway_frames

        for (on_in, on_out, rec_in, rec_out, reason) in [
            (event.record_in_frame, cut_start, event.record_in_frame, cut_start, getattr(event, 'reason', 'speaker')),
            (cut_end, event.record_out_frame, cut_end, event.record_out_frame, getattr(event, 'reason', 'speaker')),
        ]:
            vi = timeline_zero_video_frames[event.clip_name] + on_in
            vo = timeline_zero_video_frames[event.clip_name] + on_out
            new_events.append(EDLEvent(
                event_num=0, clip_name=event.clip_name,
                source_in=frames_to_timecode(reference_frames[event.clip_name] + vi, fps),
                source_out=frames_to_timecode(reference_frames[event.clip_name] + vo, fps),
                record_in=frames_to_timecode(rec_in, fps),
                record_out=frames_to_timecode(rec_out, fps),
                fps=fps, reason=reason,
            ))
            if on_in == event.record_in_frame:
                # Insert cutaway between first and second ON-segment
                off_vi = timeline_zero_video_frames[other_clip] + cut_start
                off_vo = timeline_zero_video_frames[other_clip] + cut_end
                new_events.append(EDLEvent(
                    event_num=0, clip_name=other_clip,
                    source_in=frames_to_timecode(reference_frames[other_clip] + off_vi, fps),
                    source_out=frames_to_timecode(reference_frames[other_clip] + off_vo, fps),
                    record_in=frames_to_timecode(cut_start, fps),
                    record_out=frames_to_timecode(cut_end, fps),
                    fps=fps, reason="max_time",
                ))

        print(f"  ✂️  Split: @ {event.record_in} ({duration/fps:.1f}s)")

    print(f"  ✓ {split_count} gesplittet, {len(new_events)} Events total")
    return new_events


def write_edl(events: List[EDLEvent], output_path: str, title: str = "Multicam with Reactions"):
    print(f"\n💾 Schreibe EDL: {output_path}")
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME\n"]
    for i, event in enumerate(events, 1):
        lines.append(
            f"{i:03d}  AX       V     C        "
            f"{event.source_in} {event.source_out} {event.record_in} {event.record_out}"
        )
        lines.append(f"* FROM CLIP NAME: {event.clip_name}\n")
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"✓ {len(events)} Events geschrieben")


def main():
    parser = argparse.ArgumentParser(
        description='Fügt Reaktions-Cutaways zu EDL hinzu (v4.0 - N Kameras)'
    )
    parser.add_argument('--cameras-json', required=True,
                        help='JSON-Datei mit Kamera-Konfiguration')
    parser.add_argument('--resolve-edl', required=True,
                        help='Base-EDL (Sprecher-Segmente)')
    parser.add_argument('--output', '-o', required=True)
    parser.add_argument('--config', default='config.ini')
    parser.add_argument('--fps', type=float, default=25.0)
    args = parser.parse_args()

    print("=" * 70)
    print("🎬 ADD REACTIONS TO EDL v4.0 — N-Kamera-Architektur")
    print("=" * 70)

    cameras: List[Dict] = json.loads(Path(args.cameras_json).read_text())
    config = load_config(args.config)

    # Settings aus config
    min_shot_duration       = 2.0
    reaction_min_duration   = 3.0
    max_shot_duration       = 30.0
    min_confidence          = 0.86
    speaking_min_confidence = 0.90
    cleanup_min_duration    = 1.5
    cutaway_randomness      = 0.0
    cluster_max_gap_frames  = 75
    pre_roll_frames         = 0

    if config:
        g = config['General'] if config.has_section('General') else {}
        min_shot_duration       = float(g.get('min_shot_duration',     min_shot_duration))
        reaction_min_duration   = float(g.get('reaction_min_duration', reaction_min_duration))
        max_shot_duration       = float(g.get('max_shot_duration',     max_shot_duration))
        cleanup_min_duration    = float(g.get('cleanup_min_duration',  cleanup_min_duration))
        cutaway_randomness      = float(g.get('cutaway_randomness',    cutaway_randomness))
        if config.has_option('Detection', 'min_confidence'):
            min_confidence = config.getfloat('Detection', 'min_confidence')
        if config.has_option('SpeakingReaction', 'min_confidence'):
            speaking_min_confidence = config.getfloat('SpeakingReaction', 'min_confidence')
        if config.has_section('CutawayTiming'):
            cluster_max_gap_frames = config.getint('CutawayTiming', 'cluster_max_gap_frames', fallback=75)
            pre_roll_frames        = config.getint('CutawayTiming', 'pre_roll_frames', fallback=0)

    cutaway_enabled = {
        'nodding': True, 'laughing': False,
        'head_shake': False, 'eyebrow_raise': False, 'speaking_reaction': False,
    }
    if config and config.has_section('ReactionCutaways'):
        rc = config['ReactionCutaways']
        cutaway_enabled['nodding']          = rc.getboolean('nodding_cutaway',  True)
        cutaway_enabled['laughing']         = rc.getboolean('laughing_cutaway', False)
        cutaway_enabled['head_shake']       = rc.getboolean('headshake_cutaway', False)
        cutaway_enabled['eyebrow_raise']    = rc.getboolean('eyebrow_cutaway',  False)
    if config and config.has_option('SpeakingReaction', 'enabled'):
        cutaway_enabled['speaking_reaction'] = config.getboolean('SpeakingReaction', 'enabled', fallback=False)

    settings = {
        'min_shot_duration':      min_shot_duration,
        'reaction_min_duration':  reaction_min_duration,
        'max_shot_duration':      max_shot_duration,
        'min_confidence':         min_confidence,
        'speaking_min_confidence': speaking_min_confidence,
        'cutaway_enabled':        cutaway_enabled,
        'cluster_max_gap_frames': cluster_max_gap_frames,
        'pre_roll_frames':        pre_roll_frames,
        'cutaway_randomness':     cutaway_randomness,
    }

    print(f"\n⚙️  Kameras: {[c['name'] for c in cameras]}")
    print(f"⚙️  Min Shot: {min_shot_duration}s  Reaction: {reaction_min_duration}s  Max: {max_shot_duration}s")

    # Pass 1: EDL parsen
    original_events = parse_resolve_edl(args.resolve_edl, args.fps)
    if not original_events:
        print("✗ Keine Events in EDL!")
        return 1

    # Referenz-Frames für alle Kameras berechnen
    print(f"\n  Referenz-Frames:")
    reference_frames, timeline_zero_video_frames = calculate_reference_frames(
        original_events, cameras, args.fps)

    # Sections je Kamera sammeln
    cam_sections: Dict[str, List[Dict]] = {}
    for event in original_events:
        name = event.clip_name
        if name not in cam_sections:
            cam_sections[name] = []
        if name in reference_frames:
            video_start = event.source_in_frame - reference_frames[name]
            cam_sections[name].append({
                'timeline_start': event.record_in_frame,
                'timeline_end':   event.record_out_frame,
                'video_start':    video_start,
            })

    print(f"\n  Sections: " + ", ".join(f"{k}: {len(v)}" for k, v in cam_sections.items()))

    # Reaktionen laden
    print(f"\n📊 Lade Reaktions-Daten:")
    reactions_by_cam: Dict[str, List[Dict]] = {}
    for cam in cameras:
        rlist = []
        rpath = cam.get('reactions', '')
        if rpath and Path(rpath).exists():
            r, _ = load_reactions(rpath)
            rlist.extend(r)
            print(f"  {cam['name']}: {len(r)} Reaktionen")
        spath = cam.get('speaking_reactions', '')
        if spath and Path(spath).exists():
            sr, _ = load_reactions(spath)
            rlist.extend(sr)
            print(f"  + {len(sr)} Speaking Reactions für {cam['name']}")
        reactions_by_cam[cam['name']] = rlist

    # cutaway_cams-Dicts aufbauen (brauchen reference_frame + timeline_zero_video)
    cam_dicts: Dict[str, Dict] = {}
    for cam in cameras:
        name = cam['name']
        if name in reference_frames:
            cam_dicts[name] = {
                'name':               name,
                'reference_frame':    reference_frames[name],
                'timeline_zero_video': timeline_zero_video_frames[name],
                'reactions':          reactions_by_cam.get(name, []),
            }

    # Pass 2: Für jede ON-Kamera Cutaways aus allen OFF-Kameras einfügen
    print(f"\n🎬 PASS 2: Cutaways einfügen")
    all_events: List[EDLEvent] = []

    for on_name, sections in cam_sections.items():
        if on_name not in reference_frames:
            continue
        cutaway_cams = [cam_dicts[n] for n in cam_dicts if n != on_name]
        if not cutaway_cams:
            # Keine OFF-Kamera → Sections direkt als Speaker-Events übernehmen
            for sec in sections:
                vi = sec['video_start']
                vo = vi + (sec['timeline_end'] - sec['timeline_start'])
                all_events.append(EDLEvent(
                    event_num=0, clip_name=on_name,
                    source_in=frames_to_timecode(reference_frames[on_name] + vi, args.fps),
                    source_out=frames_to_timecode(reference_frames[on_name] + vo, args.fps),
                    record_in=frames_to_timecode(sec['timeline_start'], args.fps),
                    record_out=frames_to_timecode(sec['timeline_end'], args.fps),
                    fps=args.fps, reason="speaker",
                ))
            continue

        cam_cutaways = 0
        for sec in sections:
            evs = build_events_with_cutaways(
                sec['timeline_start'], sec['timeline_end'], sec['video_start'],
                on_name, reference_frames[on_name],
                cutaway_cams, settings, args.fps,
            )
            all_events.extend(evs)
            cam_cutaways += sum(1 for e in evs if e.clip_name != on_name)
        print(f"  {on_name}: {cam_cutaways} Cutaways eingefügt")

    all_events.sort(key=lambda e: e.record_in_frame)
    print(f"\n  Gesamt vor Cleanup: {len(all_events)} Events")

    # Pass 3: Cleanup
    final_events = cleanup_short_events(all_events, cleanup_min_duration, args.fps)

    # Pass 4: Split zu lange Shots
    all_cam_names = [cam['name'] for cam in cameras]
    final_events = split_long_shots(
        final_events, max_shot_duration, cleanup_min_duration,
        reference_frames, timeline_zero_video_frames, all_cam_names, args.fps,
    )

    write_edl(final_events, args.output)

    colors_path = Path(args.output).with_suffix('.colors.json')
    colors_path.write_text(json.dumps([{'reason': e.reason} for e in final_events], indent=2))
    print(f"✓ Colors-Metadaten: {colors_path.name}")

    print(f"\n{'=' * 70}\n✓ FERTIG! {len(final_events)} Events → {args.output}\n{'=' * 70}")
    return 0


if __name__ == '__main__':
    exit(main())
