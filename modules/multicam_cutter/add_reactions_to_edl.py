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
import os
import subprocess


_ROOT = Path(__file__).resolve().parent.parent.parent

def load_params(params_path: str = None) -> dict:
    """Lädt Parameter aus params.json."""
    if params_path and os.path.exists(params_path):
        params = json.loads(Path(params_path).read_text())
        print(f"✓ Params geladen: {params_path}")
        return params
    print("⚠️  params.json nicht gefunden, nutze Default-Werte")
    return {}


from frame_utils import (
    timecode_to_frames, frames_to_timecode,
    get_embedded_timecode as get_video_timecode_with_ffprobe,
)


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
    cutaway_cams: List[Dict],  # [{'name', 'type', 'reference_frame', 'timeline_zero_video', 'reactions'}]
    config: Dict,
    fps: float,
) -> List[EDLEvent]:
    """
    Baut Events für eine Section mit Cutaways von einer oder mehreren OFF-Kameras.

    Kamera-Rollen (Feld 'type' im cam-Dict):
    - 'close' (default): Normale Reaktions-Cutaways (Single-Person).
    - 'wide': Totale — wird verwendet wenn ≥2 Close-Kameras gleichzeitig reagieren
              oder als Reset-Schnitt nach max_shot_duration.
    """
    min_shot_frames          = int(config['min_shot_duration'] * fps)
    reaction_duration_frames = int(config['reaction_min_duration'] * fps)
    max_shot_frames          = int(config['max_shot_duration'] * fps)
    min_confidence           = config['min_confidence']
    speaking_min_confidence  = config.get('speaking_min_confidence', min_confidence)
    cluster_max_gap          = int(config.get('cluster_max_gap_frames', 75))
    pre_roll_frames          = int(config.get('pre_roll_frames', 0))
    cutaway_enabled          = config['cutaway_enabled']

    # Close-up vs. Wide-Kameras trennen
    close_cams = [c for c in cutaway_cams if c.get('type', 'close') != 'wide']
    wide_cams  = [c for c in cutaway_cams if c.get('type', 'close') == 'wide']

    # Reaktionen nur von Close-Kameras sammeln (Wide wird durch Multi-Person-Logik entschieden)
    valid_reactions = []
    for cam in close_cams:
        tzvf = cam['timeline_zero_video']
        for reaction in cam['reactions']:
            rtype      = reaction['type']
            confidence = reaction['confidence']
            timeline_frame = reaction['frame'] - tzvf

            if not cutaway_enabled.get(rtype, False):
                continue
            if rtype != 'speaking_reaction' and confidence < min_confidence:
                continue
            if timeline_frame < 0:
                continue
            if section_start <= timeline_frame < section_end:
                peak = reaction.get('peak_frame')
                peak_tl = (peak - tzvf) if peak is not None else timeline_frame
                tail = reaction.get('tail_frames', 0)
                valid_reactions.append({
                    'timeline_frame': timeline_frame,
                    'peak_tl_frame':  peak_tl,
                    'tail_frames':    tail,
                    'type':           rtype,
                    'confidence':     confidence,
                    'cam':            cam,
                })

    # Sortieren: erst nach Position, dann nach Confidence absteigend
    valid_reactions.sort(key=lambda x: (x['timeline_frame'], -x['confidence']))

    # Multi-Person-Erkennung: Frames mit ≥2 verschiedenen Close-Kameras innerhalb cluster_max_gap
    close_cam_frames: Dict[str, List[int]] = {}
    for r in valid_reactions:
        close_cam_frames.setdefault(r['cam']['name'], []).append(r['timeline_frame'])

    def _is_multi_person(frame: int) -> bool:
        """True wenn ≥2 Close-Kameras eine Reaktion innerhalb cluster_max_gap von frame haben."""
        if not wide_cams:
            return False
        active = sum(
            1 for frames in close_cam_frames.values()
            if any(abs(f - frame) <= cluster_max_gap for f in frames)
        )
        return active >= 2

    events: List[EDLEvent] = []
    current_pos    = section_start
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

        # OFF-Cutaway: Multi-Person → Wide-Kamera; Single-Person → beste Close-Kamera
        if _is_multi_person(cutaway_frame) and wide_cams:
            off_cam    = wide_cams[0]
            cut_reason = f"reaction_{rtype}_wide"
        else:
            off_cam    = reaction['cam']
            cut_reason = f"reaction_{rtype}"

        off_clip            = off_cam['name']
        off_reference_frame = off_cam['reference_frame']
        off_tzvf            = off_cam['timeline_zero_video']

        # Prüfe ob Kamera zum Cutaway-Zeitpunkt bereits aufnimmt
        off_vi_check = off_tzvf + cutaway_frame
        if off_vi_check < 0:
            print(f"  ⚠️  Cutaway auf {off_clip} übersprungen @ EDL {cutaway_frame}: "
                  f"Kamera startet erst {-off_vi_check} Frames später")
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

        # Cutaway-Dauer: natürliche Pattern-Länge (Start→Peak+Tail) oder Minimum
        peak_tl = reaction.get('peak_tl_frame', reaction['timeline_frame'])
        tail = reaction.get('tail_frames', 0)
        pattern_dur = max(0, peak_tl - cutaway_frame + tail)
        base_frames = max(reaction_duration_frames, pattern_dur)
        randomness = config.get('cutaway_randomness', 0.0)
        this_cutaway_frames = int(
            base_frames * (1.0 + random.uniform(0.0, randomness))
        ) if randomness > 0 else base_frames
        cutaway_end = min(cutaway_frame + this_cutaway_frames, section_end)

        off_vi = off_tzvf + cutaway_frame
        off_vo = off_tzvf + cutaway_end
        events.append(EDLEvent(
            event_num=0, clip_name=off_clip,
            source_in=frames_to_timecode(off_reference_frame + off_vi, fps),
            source_out=frames_to_timecode(off_reference_frame + off_vo, fps),
            record_in=frames_to_timecode(cutaway_frame, fps),
            record_out=frames_to_timecode(cutaway_end, fps),
            fps=fps, reason=cut_reason,
        ))

        last_cut_frame = cutaway_end
        current_pos    = cutaway_end

    # Rest der Section
    if current_pos < section_end:
        # Wide als bevorzugter Reset-Schnitt; Fallback: erste Close-Kamera
        reset_cam = wide_cams[0] if wide_cams else (close_cams[0] if close_cams else None)
        if section_end - current_pos > max_shot_frames:
            while current_pos < section_end:
                remaining = section_end - current_pos
                if remaining <= max_shot_frames:
                    # Letztes Segment passt ohne Split
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
                    current_pos = section_end
                    break

                # Cutaway in der MITTE des Segments platzieren
                segment_end = min(current_pos + max_shot_frames, section_end)
                segment_dur = segment_end - current_pos
                middle = current_pos + (segment_dur // 2)
                cut_half = reaction_duration_frames // 2
                cut_start = middle - cut_half
                cut_end = min(cut_start + reaction_duration_frames, section_end)

                # Erster On-Speaker-Teil: current_pos → cut_start
                vi = section_video_start + (current_pos - section_start)
                vo = section_video_start + (cut_start - section_start)
                events.append(EDLEvent(
                    event_num=0, clip_name=on_clip,
                    source_in=frames_to_timecode(on_reference_frame + vi, fps),
                    source_out=frames_to_timecode(on_reference_frame + vo, fps),
                    record_in=frames_to_timecode(current_pos, fps),
                    record_out=frames_to_timecode(cut_start, fps),
                    fps=fps, reason="speaker",
                ))

                # Cutaway in der Mitte
                if reset_cam:
                    off_vi = reset_cam['timeline_zero_video'] + cut_start
                    off_vo = reset_cam['timeline_zero_video'] + cut_end
                    if off_vi >= 0:
                        events.append(EDLEvent(
                            event_num=0, clip_name=reset_cam['name'],
                            source_in=frames_to_timecode(reset_cam['reference_frame'] + off_vi, fps),
                            source_out=frames_to_timecode(reset_cam['reference_frame'] + off_vo, fps),
                            record_in=frames_to_timecode(cut_start, fps),
                            record_out=frames_to_timecode(cut_end, fps),
                            fps=fps, reason="max_time",
                        ))
                        current_pos = cut_end
                    else:
                        print(f"  ⚠️  Max-Time Reset auf {reset_cam['name']} übersprungen @ EDL {cut_start}: "
                              f"Kamera startet erst {-off_vi} Frames später")
                        current_pos = segment_end
                else:
                    current_pos = segment_end
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


def _is_diarization_switch(event, prev, next_event) -> bool:
    """Prüft ob ein kurzes Event ein reiner Diarization-Sprecherwechsel ist.

    Ein Sprecherwechsel-Sandwich liegt vor, wenn:
    - Das kurze Event reason='speaker' hat
    - Vorgänger und Nachfolger ebenfalls reason='speaker' haben
    - Das Event einen anderen Clip hat als Vorgänger UND Nachfolger
    - Vorgänger und Nachfolger denselben Clip haben (CAM1→CAM2→CAM1)
    """
    if event.reason != "speaker":
        return False
    if prev.reason != "speaker":
        return False
    if next_event is None or next_event.reason != "speaker":
        return False
    if event.clip_name == prev.clip_name:
        return False
    if next_event.clip_name == event.clip_name:
        return False
    return True


def cleanup_short_events(events: List[EDLEvent], min_duration: float, fps: float) -> List[EDLEvent]:
    print(f"\n🧹 PASS 3: Cleanup kurzer Events")
    print(f"  Min Duration: {min_duration}s ({int(min_duration * fps)} Frames)")
    min_frames = int(min_duration * fps)
    cleaned = []
    removed = 0
    skipped_diarization = 0
    for i, event in enumerate(events):
        if event.duration_frames() < min_frames and cleaned:
            next_event = events[i + 1] if i + 1 < len(events) else None
            prev = cleaned[-1]
            if _is_diarization_switch(event, prev, next_event):
                cleaned.append(event)
                skipped_diarization += 1
                print(f"  ⏭ Sprecherwechsel beibehalten: {event.clip_name} @ {event.record_in} ({event.duration_frames()} Frames)")
                continue
            source_offset = prev.source_in_frame - prev.record_in_frame
            prev.record_out       = event.record_out
            prev.record_out_frame = event.record_out_frame
            prev.source_out_frame = source_offset + event.record_out_frame
            prev.source_out       = frames_to_timecode(prev.source_out_frame, fps)
            removed += 1
            print(f"  ✗ Entfernt: Event @ {event.record_in} ({event.duration_frames()} Frames)")
        else:
            cleaned.append(event)
    print(f"  ✓ {removed} entfernt, {skipped_diarization} Sprecherwechsel beibehalten, {len(cleaned)} verbleiben")
    return cleaned


def insert_pause_cutaways(
    events: List[EDLEvent],
    pause_data: Dict,
    cameras: List[Dict],
    reference_frames: Dict[str, int],
    timeline_zero_video_frames: Dict[str, int],
    min_shot_frames: int,
    fps: float,
) -> List[EDLEvent]:
    """Pass 2b: Fügt Cutaways in On-Speaker-Pausen ein.

    Für jede Pause wird geprüft, ob sie komplett innerhalb eines
    speaker-Events liegt (nicht an einem Schnitt beginnt/endet).
    Wenn ja, wird das Event aufgespalten und ein Cutaway eingefügt.
    """
    print(f"\n🔇 PASS 2b: Pause-Cutaways")
    pauses = pause_data.get('pauses', [])
    if not pauses:
        print("  Keine Pausen-Kandidaten vorhanden")
        return events

    # CAM1/CAM2 → Clip-Name Mapping (erste zwei Kameras)
    speaker_to_clip = {}
    if len(cameras) >= 1:
        speaker_to_clip['CAM1'] = cameras[0]['name']
    if len(cameras) >= 2:
        speaker_to_clip['CAM2'] = cameras[1]['name']

    inserted = 0
    result = list(events)

    for pause in pauses:
        ps = pause['start_frame']
        pe = pause['end_frame']
        spk = pause['speaker']
        on_clip = speaker_to_clip.get(spk)
        if not on_clip:
            continue

        # Finde das Event, das die Pause komplett enthält
        host_idx = None
        for i, ev in enumerate(result):
            if (ev.clip_name == on_clip
                    and ev.reason == "speaker"
                    and ev.record_in_frame <= ps
                    and ev.record_out_frame >= pe):
                # Mindestabstand zum Event-Rand prüfen
                if (ps - ev.record_in_frame >= min_shot_frames
                        and ev.record_out_frame - pe >= min_shot_frames):
                    host_idx = i
                    break

        if host_idx is None:
            continue

        ev = result[host_idx]
        on_ref = reference_frames[on_clip]
        on_tzvf = timeline_zero_video_frames[on_clip]

        # Off-Kamera wählen: erste andere Close-Kamera
        off_cam = None
        for cam in cameras:
            if cam['name'] != on_clip:
                off_cam = cam
                break
        if not off_cam or off_cam['name'] not in reference_frames:
            continue

        off_clip = off_cam['name']
        off_ref = reference_frames[off_clip]
        off_tzvf = timeline_zero_video_frames[off_clip]

        # Prüfe ob Off-Kamera zum Pause-Zeitpunkt bereits aufnimmt
        off_vi_check = off_tzvf + ps
        if off_vi_check < 0:
            continue

        # Source-Offset des Host-Events beibehalten
        source_offset = ev.source_in_frame - ev.record_in_frame

        # 3 neue Events: ON-vor-Pause, OFF-Cutaway, ON-nach-Pause
        new_events = []

        # ON vor Pause
        vi_pre = on_tzvf + ev.record_in_frame
        vo_pre = on_tzvf + ps
        new_events.append(EDLEvent(
            event_num=0, clip_name=on_clip,
            source_in=frames_to_timecode(on_ref + vi_pre, fps),
            source_out=frames_to_timecode(on_ref + vo_pre, fps),
            record_in=frames_to_timecode(ev.record_in_frame, fps),
            record_out=frames_to_timecode(ps, fps),
            fps=fps, reason="speaker",
        ))

        # OFF Cutaway (Pause)
        off_vi = off_tzvf + ps
        off_vo = off_tzvf + pe
        new_events.append(EDLEvent(
            event_num=0, clip_name=off_clip,
            source_in=frames_to_timecode(off_ref + off_vi, fps),
            source_out=frames_to_timecode(off_ref + off_vo, fps),
            record_in=frames_to_timecode(ps, fps),
            record_out=frames_to_timecode(pe, fps),
            fps=fps, reason="pause_cutaway",
        ))

        # ON nach Pause
        vi_post = on_tzvf + pe
        vo_post = on_tzvf + ev.record_out_frame
        new_events.append(EDLEvent(
            event_num=0, clip_name=on_clip,
            source_in=frames_to_timecode(on_ref + vi_post, fps),
            source_out=frames_to_timecode(on_ref + vo_post, fps),
            record_in=frames_to_timecode(pe, fps),
            record_out=frames_to_timecode(ev.record_out_frame, fps),
            fps=fps, reason="speaker",
        ))

        # Host-Event ersetzen
        result[host_idx:host_idx + 1] = new_events
        inserted += 1
        print(f"  🔇 Pause-Cutaway: {on_clip}→{off_clip} @ {frames_to_timecode(ps, fps)} "
              f"({(pe - ps) / fps:.1f}s)")

    print(f"  ✓ {inserted} Pause-Cutaways eingefügt, {len(result)} Events total")
    return result


def split_long_shots(
    events: List[EDLEvent],
    max_shot_duration: float,
    cutaway_duration: float,
    reference_frames: Dict[str, int],
    timeline_zero_video_frames: Dict[str, int],
    all_cam_names: List[str],
    fps: float,
    cam_types_dict: Dict[str, str] = None,  # {clip_name: 'close'|'wide'}
) -> List[EDLEvent]:
    print(f"\n✂️  PASS 4: Split zu lange Shots")
    threshold_frames = int((max_shot_duration + 3.0) * fps)
    cutaway_frames   = int(cutaway_duration * fps)
    new_events = []
    split_count = 0
    types = cam_types_dict or {}

    for idx, event in enumerate(events):
        duration = event.duration_frames()
        if duration <= threshold_frames:
            new_events.append(event)
            continue

        # Wenn das nächste Event bereits ein Sprecherwechsel ist und der
        # Split in der zweiten Hälfte landen würde, ist er überflüssig.
        next_ev = events[idx + 1] if idx + 1 < len(events) else None
        if next_ev and next_ev.clip_name != event.clip_name:
            # Abstand vom geplanten Split-Ende zum Event-Ende
            middle = event.record_in_frame + (duration // 2)
            cut_end = middle + (cutaway_frames // 2)
            remaining_after_split = event.record_out_frame - cut_end
            if remaining_after_split < threshold_frames:
                new_events.append(event)
                continue

        # Wide-Kamera bevorzugt als Split-Ziel (Reset-Schnitt); Fallback: erste andere Close-Kamera
        wide_others  = [c for c in all_cam_names if c != event.clip_name and types.get(c, 'close') == 'wide']
        close_others = [c for c in all_cam_names if c != event.clip_name and types.get(c, 'close') != 'wide']
        other_clip = wide_others[0] if wide_others else (close_others[0] if close_others else None)
        if not other_clip or other_clip not in reference_frames:
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
                if off_vi >= 0:
                    new_events.append(EDLEvent(
                        event_num=0, clip_name=other_clip,
                        source_in=frames_to_timecode(reference_frames[other_clip] + off_vi, fps),
                        source_out=frames_to_timecode(reference_frames[other_clip] + off_vo, fps),
                        record_in=frames_to_timecode(cut_start, fps),
                        record_out=frames_to_timecode(cut_end, fps),
                        fps=fps, reason="max_time",
                    ))
                else:
                    # Kamera noch nicht gestartet — kein Split, Event ungeteilt lassen
                    new_events.pop()  # Ersten ON-Teil wieder entfernen
                    new_events.append(event)  # Original-Event beibehalten
                    print(f"  ⚠️  Split-Cutaway auf {other_clip} übersprungen @ EDL {cut_start}: "
                          f"Kamera startet erst {-off_vi} Frames später")
                    break  # Zweiten ON-Teil nicht hinzufügen

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


def _tc_to_seconds(tc: str, fps: float) -> float:
    """HH:MM:SS:FF → Sekunden."""
    parts = tc.split(':')
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / fps


def _extract_frame(video_path: str, time_s: float, output_path: str) -> bool:
    """Extrahiert ein Einzelbild per ffmpeg."""
    result = subprocess.run(
        ['ffmpeg', '-y', '-ss', f'{time_s:.3f}', '-i', video_path,
         '-frames:v', '1', '-q:v', '2', output_path],
        capture_output=True, timeout=10,
    )
    return result.returncode == 0 and Path(output_path).exists()


def _clip_score_for_event(
    event: 'EDLEvent',
    clip_to_video: Dict[str, str],
    clip_start_s: Dict[str, float],
    model, processor, all_prompts: List[str],
    n_ignore: int, fps: float, tmpdir: str, tag: str,
    device: str,
) -> float:
    """Berechnet den Ignore-Score für ein Cutaway-Event (max über 2 Frames)."""
    import torch
    from PIL import Image

    video_path = clip_to_video.get(event.clip_name)
    if not video_path or not Path(video_path).exists():
        return 0.0

    start_offset = clip_start_s.get(event.clip_name, 0.0)
    src_in_s = _tc_to_seconds(event.source_in, fps) - start_offset
    src_out_s = _tc_to_seconds(event.source_out, fps) - start_offset
    mid_s = (src_in_s + src_out_s) / 2

    scores = []
    for label, t in [('s', src_in_s + 0.2), ('m', mid_s)]:
        frame_path = f"{tmpdir}/clip_{tag}_{label}.jpg"
        if not _extract_frame(video_path, t, frame_path):
            continue
        image = Image.open(frame_path).convert('RGB')
        inputs = processor(text=all_prompts, images=image,
                           return_tensors="pt", padding=True).to(device)
        with torch.no_grad():
            outputs = model(**inputs)
            probs = outputs.logits_per_image[0].softmax(dim=0).cpu().numpy()
        scores.append(float(sum(probs[:n_ignore])))

    return max(scores) if scores else 0.0


def clip_filter_cutaways(
    events: List['EDLEvent'],
    cameras: List[Dict],
    reference_frames: Dict[str, int],
    timeline_zero_video_frames: Dict[str, int],
    clip_config: Dict,
    fps: float,
) -> List['EDLEvent']:
    """Pass 5: CLIP-basierter Ignore-Filter.

    Prüft alle Cutaway-Events gegen eine Ignore-Liste (z.B. 'Person trinkt').
    Geflagte Cutaways werden verschoben (alternierend ±step) und erneut geprüft.
    """
    import tempfile

    prompts_path = clip_config.get('prompts_path', '')
    threshold = clip_config.get('ignore_threshold', 0.5)
    shift_step_s = clip_config.get('shift_step_s', 2.0)
    max_attempts = clip_config.get('max_attempts', 5)

    if not prompts_path or not Path(prompts_path).exists():
        print("\n⚠️  CLIP-Filter: Prompts-JSON nicht gefunden, überspringe")
        return events

    prompts_data = json.loads(Path(prompts_path).read_text())
    ignore_prompts = prompts_data.get('ignore', [])
    neutral_prompts = prompts_data.get('neutral', [])
    if not ignore_prompts:
        return events

    print(f"\n🔍 PASS 5: CLIP Ignore-Filter")
    print(f"  Ignore-Prompts: {ignore_prompts}")
    print(f"  Threshold: {threshold:.0%}, Shift: {shift_step_s}s, Max Versuche: {max_attempts}")

    # CLIP laden
    try:
        import torch
        from transformers import CLIPProcessor, CLIPModel
    except ImportError:
        print("  ⚠️  transformers/torch nicht installiert, überspringe CLIP-Filter")
        return events

    device = 'cpu'
    if torch.backends.mps.is_available():
        device = 'mps'
    elif torch.cuda.is_available():
        device = 'cuda'

    print(f"  Lade CLIP-Modell auf {device}...")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    all_prompts = ignore_prompts + neutral_prompts
    n_ignore = len(ignore_prompts)

    # Video-Pfade und Start-TCs
    clip_to_video = {cam['name']: cam['video'] for cam in cameras}
    clip_start_s = {}
    for cam in cameras:
        tc = get_video_timecode_with_ffprobe(cam['video'])
        clip_start_s[cam['name']] = _tc_to_seconds(tc, fps) if tc else 0.0

    shift_frames = int(shift_step_s * fps)
    checked = 0
    flagged = 0
    shifted = 0
    unresolved = 0

    result = list(events)
    total_cutaways = sum(1 for e in result if e.reason != "speaker")

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, event in enumerate(result):
            if event.reason == "speaker":
                continue

            checked += 1
            if checked % 50 == 0 or checked == total_cutaways:
                print(f"  … {checked}/{total_cutaways} geprüft", flush=True)

            score = _clip_score_for_event(
                event, clip_to_video, clip_start_s,
                model, processor, all_prompts, n_ignore,
                fps, tmpdir, f"e{i}", device,
            )

            if score < threshold:
                continue

            flagged += 1
            print(f"  🚫 Geflagged: {event.reason} @ {event.record_in} "
                  f"({event.clip_name}) ignore={score:.0%}")

            # Verschiebungsversuche
            best_delta = 0
            best_score = score
            cutaway_dur = event.duration_frames()

            # Grenzen: Vorgänger und Nachfolger müssen Speaker sein
            prev_ev = result[i - 1] if i > 0 else None
            next_ev = result[i + 1] if i + 1 < len(result) else None

            found = False
            for attempt in range(1, max_attempts + 1):
                # Alternierend: +1*step, -1*step, +2*step, -2*step, ...
                sign = 1 if attempt % 2 == 1 else -1
                magnitude = (attempt + 1) // 2
                delta = sign * magnitude * shift_frames

                new_rec_in = event.record_in_frame + delta
                new_rec_out = new_rec_in + cutaway_dur

                # Grenzen prüfen
                if prev_ev and prev_ev.reason == "speaker":
                    if new_rec_in < prev_ev.record_in_frame + 1:
                        continue
                else:
                    if new_rec_in < event.record_in_frame:
                        continue

                if next_ev and next_ev.reason == "speaker":
                    if new_rec_out > next_ev.record_out_frame - 1:
                        continue
                else:
                    if new_rec_out > event.record_out_frame:
                        continue

                # Testweise Source-TCs berechnen
                tzvf = timeline_zero_video_frames.get(event.clip_name, 0)
                ref = reference_frames.get(event.clip_name, 0)
                test_event = EDLEvent(
                    event_num=0, clip_name=event.clip_name,
                    source_in=frames_to_timecode(ref + tzvf + new_rec_in, fps),
                    source_out=frames_to_timecode(ref + tzvf + new_rec_out, fps),
                    record_in=frames_to_timecode(new_rec_in, fps),
                    record_out=frames_to_timecode(new_rec_out, fps),
                    fps=fps, reason=event.reason,
                )

                test_score = _clip_score_for_event(
                    test_event, clip_to_video, clip_start_s,
                    model, processor, all_prompts, n_ignore,
                    fps, tmpdir, f"e{i}_a{attempt}", device,
                )

                if test_score < best_score:
                    best_score = test_score
                    best_delta = delta

                if test_score < threshold:
                    found = True
                    print(f"    ✓ Verschoben um {delta/fps:+.1f}s → ignore={test_score:.0%}")
                    break
                else:
                    print(f"    ✗ Versuch {delta/fps:+.1f}s → ignore={test_score:.0%}")

            if not found and best_delta == 0:
                print(f"    ⚠️  Keine bessere Position gefunden, belasse Original")
                unresolved += 1
                continue

            if not found:
                print(f"    ⚠️  Keine saubere Position, nutze beste ({best_score:.0%}, "
                      f"{best_delta/fps:+.1f}s)")
                unresolved += 1

            # Event verschieben
            delta = best_delta
            new_rec_in = event.record_in_frame + delta
            new_rec_out = new_rec_in + cutaway_dur
            tzvf = timeline_zero_video_frames.get(event.clip_name, 0)
            ref = reference_frames.get(event.clip_name, 0)

            event.record_in_frame = new_rec_in
            event.record_out_frame = new_rec_out
            event.record_in = frames_to_timecode(new_rec_in, fps)
            event.record_out = frames_to_timecode(new_rec_out, fps)
            event.source_in_frame = ref + tzvf + new_rec_in
            event.source_out_frame = ref + tzvf + new_rec_out
            event.source_in = frames_to_timecode(event.source_in_frame, fps)
            event.source_out = frames_to_timecode(event.source_out_frame, fps)

            # Nachbar-Events anpassen
            if prev_ev and prev_ev.reason == "speaker":
                prev_ev.record_out_frame = new_rec_in
                prev_ev.record_out = frames_to_timecode(new_rec_in, fps)
                prev_offset = prev_ev.source_in_frame - prev_ev.record_in_frame
                prev_ev.source_out_frame = prev_offset + new_rec_in
                prev_ev.source_out = frames_to_timecode(prev_ev.source_out_frame, fps)

            if next_ev and next_ev.reason == "speaker":
                next_offset = next_ev.source_in_frame - next_ev.record_in_frame
                next_ev.record_in_frame = new_rec_out
                next_ev.record_in = frames_to_timecode(new_rec_out, fps)
                next_ev.source_in_frame = next_offset + new_rec_out
                next_ev.source_in = frames_to_timecode(next_ev.source_in_frame, fps)

            shifted += 1

    print(f"  ✓ {checked} geprüft, {flagged} geflagged, "
          f"{shifted} verschoben, {unresolved} nicht lösbar")
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Fügt Reaktions-Cutaways zu EDL hinzu (v4.0 - N Kameras)'
    )
    parser.add_argument('--cameras-json', required=True,
                        help='JSON-Datei mit Kamera-Konfiguration')
    parser.add_argument('--resolve-edl', required=True,
                        help='Base-EDL (Sprecher-Segmente)')
    parser.add_argument('--output', '-o', required=True)
    parser.add_argument('--params', default=None,
                        help='Pfad zur params.json mit Modul-Parametern')
    parser.add_argument('--pause-cutaways', default=None,
                        help='JSON mit On-Speaker-Pausen für Stille-Cutaways')
    parser.add_argument('--clip-filter-config', default=None,
                        help='JSON mit CLIP Ignore-/Neutral-Prompts')
    parser.add_argument('--fps', type=float, default=25.0)
    args = parser.parse_args()

    print("=" * 70)
    print("🎬 ADD REACTIONS TO EDL v4.0 — N-Kamera-Architektur")
    print("=" * 70)

    cameras: List[Dict] = json.loads(Path(args.cameras_json).read_text())
    params = load_params(args.params)

    # Settings aus params
    min_shot_duration       = float(params.get('min_shot', 2.0))
    reaction_min_duration   = float(params.get('reaction_dur', 3.0))
    max_shot_duration       = float(params.get('max_shot', 30.0))
    min_confidence          = float(params.get('min_conf', 0.86))
    speaking_min_confidence = float(params.get('speaking_min_confidence', min_confidence))
    cleanup_min_duration    = float(params.get('cleanup_dur', 1.5))
    cutaway_randomness      = float(params.get('randomness', 0.0))
    cluster_max_gap_frames  = int(params.get('cluster_max_gap_frames', 75))
    pre_roll_frames         = int(params.get('pre_roll', 0))

    cutaway_enabled = {
        'nodding': bool(params.get('nodding_enabled', True)),
        'laughing': bool(params.get('laughing_cutaway', False)),
        'head_shake': bool(params.get('headshake_cutaway', False)),
        'eyebrow_raise': bool(params.get('eyebrow_cutaway', False)),
        'speaking_reaction': bool(params.get('speaking_enabled', False)),
    }

    # CLIP-Filter Config
    clip_filter_enabled = bool(params.get('clip_filter_enabled', False))
    clip_config = {
        'ignore_threshold': float(params.get('clip_ignore_threshold', 0.5)),
        'shift_step_s':     float(params.get('clip_shift_step_s', 2.0)),
        'max_attempts':     int(params.get('clip_max_attempts', 5)),
        'prompts_path':     args.clip_filter_config or '',
    }

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
                'name':                name,
                'type':                cam.get('type', 'close'),
                'reference_frame':     reference_frames[name],
                'timeline_zero_video': timeline_zero_video_frames[name],
                'reactions':           reactions_by_cam.get(name, []),
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
    speaking_cutaways = sum(1 for e in all_events if 'speaking' in getattr(e, 'reason', ''))
    nodding_cutaways = sum(1 for e in all_events if 'nodding' in getattr(e, 'reason', ''))
    print(f"\n  Gesamt vor Cleanup: {len(all_events)} Events")
    print(f"    davon Nodding-Cutaways: {nodding_cutaways}, Speaking-Cutaways: {speaking_cutaways}")

    # Pass 2b: Pause-Cutaways
    if args.pause_cutaways and Path(args.pause_cutaways).exists():
        pause_data = json.loads(Path(args.pause_cutaways).read_text())
        min_shot_frames = int(min_shot_duration * args.fps)
        all_events = insert_pause_cutaways(
            all_events, pause_data, cameras,
            reference_frames, timeline_zero_video_frames,
            min_shot_frames, args.fps,
        )

    # Pass 3: Cleanup
    final_events = cleanup_short_events(all_events, cleanup_min_duration, args.fps)

    # Pass 4: Split zu lange Shots
    all_cam_names  = [cam['name'] for cam in cameras]
    cam_types_dict = {cam['name']: cam.get('type', 'close') for cam in cameras}
    final_events = split_long_shots(
        final_events, max_shot_duration, cleanup_min_duration,
        reference_frames, timeline_zero_video_frames, all_cam_names, args.fps,
        cam_types_dict=cam_types_dict,
    )

    # Pass 5: CLIP Ignore-Filter
    if clip_filter_enabled and clip_config.get('prompts_path'):
        final_events = clip_filter_cutaways(
            final_events, cameras,
            reference_frames, timeline_zero_video_frames,
            clip_config, args.fps,
        )

    write_edl(final_events, args.output)

    colors_path = Path(args.output).with_suffix('.colors.json')
    colors_path.write_text(json.dumps([{'reason': e.reason} for e in final_events], indent=2))
    print(f"✓ Colors-Metadaten: {colors_path.name}")

    print(f"\n{'=' * 70}\n✓ FERTIG! {len(final_events)} Events → {args.output}\n{'=' * 70}")
    return 0


if __name__ == '__main__':
    exit(main())
