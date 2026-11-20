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
import sys
import time
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
            # Die Kommentarzeilen NACH dem Event einsammeln statt nur die
            # unmittelbar folgende: seit die Basis-EDL auch '* CUT REASON'
            # schreibt, stehen dort zwei. Ein fester Blick auf i+1 haette die
            # Begruendung uebersehen oder — je nach Reihenfolge — den Clipnamen.
            clip_name, reason = None, "speaker"
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith('*'):
                cm = lines[j].strip()
                cn = re.match(r'\* FROM CLIP NAME:\s*(.+)', cm)
                rs = re.match(r'\* CUT REASON:\s*(\S+)', cm)
                if cn:
                    clip_name = cn.group(1).strip()
                elif rs:
                    reason = rs.group(1).strip()
                j += 1
            if clip_name:
                events.append(EDLEvent(
                    event_num=event_num,
                    clip_name=clip_name,
                    source_in=m.group(2), source_out=m.group(3),
                    record_in=m.group(4), record_out=m.group(5),
                    fps=fps, reason=reason,
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
            # Kein embedded TC: build_base_edl_from_audio hat die EDL mit ref=0
            # geschrieben. Damit gilt: source_in = 0 + video_frame und
            # video_frame = tzvf + record_in_frame → tzvf = source_in - record_in.
            # Vorher wurde dieser Wert fälschlich als ref gespeichert und tzvf=0
            # gesetzt — was alle Cutaways auf dieser Cam um den Sync-Offset
            # (typisch ~250 Frames bei +10s-Cam-Start) verschoben hat.
            ref = 0
            tzvf = event.source_in_frame - event.record_in_frame
            reference_frames[clip_name] = ref
            timeline_zero_video_frames[clip_name] = tzvf
            print(f"    {clip_name}: kein embedded TC ⚠️ (Fallback: ref=0, tl0={tzvf})")

    return reference_frames, timeline_zero_video_frames


def _pick_widest(cams: List[Dict]) -> Optional[Dict]:
    """Kamera mit den meisten gezeigten Personen (breiteste Einstellung) — der
    N-Ersatz fuer „die Totale", wenn keine Kamera ausdruecklich als 'wide' gilt.
    Bei Gleichstand die erste (max ist stabil); ohne 'mics' hat jede Stufe 1,
    dann faellt es auf die erste zurueck — genau wie das alte close_cams[0]."""
    from shot_sizes import shot_level
    return max(cams, key=shot_level) if cams else None


def _pick_totale(wide_cams: List[Dict], mode: str, state: Dict) -> Optional[Dict]:
    """Waehlt EINE Totale aus wide_cams je nach `mode`. `state` ist ein
    veraenderliches Dict (haelt Round-Robin-Zaehler bzw. RNG), damit die Wahl
    ueber Cutaways UND Sections hinweg weiterrotiert.

    Bei 0/1 Totale oder mode='first' immer wide_cams[0] → **byte-identisch** zum
    alten Verhalten (nur Multi-Totale-Setups aendern sich). 'round_robin' (Default)
    reihum, 'random' pseudo-zufaellig mit festem Seed (gleicher Lauf → gleiches Ergebnis)."""
    if not wide_cams:
        return None
    if len(wide_cams) == 1 or mode == 'first':
        return wide_cams[0]
    if mode == 'random':
        rng = state.get('rng')
        if rng is None:
            import random as _random
            rng = _random.Random(0xC0FFEE)   # fester Seed → reproduzierbar
            state['rng'] = rng
        return wide_cams[rng.randrange(len(wide_cams))]
    # round_robin (Default): reihum, Zaehler persistiert im state
    i = state.get('rr', 0)
    state['rr'] = i + 1
    return wide_cams[i % len(wide_cams)]


def _pick_multi_person_offcam(reacting_cams: List[Dict], cutaway_cams: List[Dict],
                              wide_cams: List[Dict],
                              pick_totale=None) -> Optional[Dict]:
    """Bei Multi-Person-Reaktion: kleinste Kamera, die ALLE reagierenden Personen
    zeigt (Totale-Ersatz via smallest_containing). Fallback auf eine Totale — per
    `pick_totale()` (Round-Robin/zufall bei mehreren Totalen) oder, ohne Callback,
    die feste `wide_cams[0]` (byte-identisch). Gibt None, wenn keine gemeinsame
    Kamera existiert (dann bleibt es beim Einzel-Cutaway auf die reagierende Kamera)."""
    from shot_sizes import smallest_containing
    persons = sorted({p for c in reacting_cams for p in (c.get('mics') or [])})
    common = smallest_containing(cutaway_cams, persons) if persons else None
    if common is None and wide_cams:
        common = pick_totale() if pick_totale else wide_cams[0]
    return common


def build_events_with_cutaways(
    section_start: int,
    section_end: int,
    section_video_start: int,
    on_clip: str,
    on_reference_frame: int,
    cutaway_cams: List[Dict],  # [{'name', 'type', 'reference_frame', 'timeline_zero_video', 'reactions'}]
    config: Dict,
    fps: float,
    decision_log: Optional[List] = None,
    base_reason: str = "speaker",
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
    cluster_max_gap          = int(config.get('cluster_max_gap_frames', 75))
    pre_roll_frames          = int(config.get('pre_roll_frames', 0))
    cutaway_enabled          = config['cutaway_enabled']

    # Close-up vs. Wide-Kameras trennen
    close_cams = [c for c in cutaway_cams if c.get('type', 'close') != 'wide']
    wide_cams  = [c for c in cutaway_cams if c.get('type', 'close') == 'wide']

    # Totale-Auswahl (Punkt 4): bei MEHREREN Totalen reihum/zufaellig statt stur
    # der ersten. Der State liegt im config-Dict (einmal gebaut, ueber alle Sections
    # geteilt) → der Round-Robin zaehlt global weiter. Bei 0/1 Totale byte-identisch.
    totale_mode = str(config.get('totale_mode', 'round_robin')).lower()
    totale_state = config.setdefault('_totale_state', {})
    def _next_totale():
        return _pick_totale(wide_cams, totale_mode, totale_state)

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
            # Konfidenz je Nick-Muster (Slider „Treffsicherheit", Sichtung 19.11.):
            # {muster: schwelle}; > 1 = Muster aus. Fehlt das Muster → nur min_confidence.
            if rtype == 'nodding':
                _pc = (config.get('nodding_pattern_min_conf') or {}).get(reaction.get('pattern'))
                if _pc is not None and confidence < float(_pc):
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

    # Vorrang Einwürfe vor Nicken (User, 19.11.; Schalter `speaking_priority`):
    # PASS 2 setzt chronologisch „wer zuerst kommt". Ein Nick-Cutaway kurz vor einem
    # Einwurf blockiert diesen sonst über den Mindestabstand. Mit Vorrang fällt jedes
    # Nicken weg, dessen Cutaway (geschätzte Länge wie unten) weniger als min_shot vor
    # dem Cutaway eines späteren Einwurfs endet. Ohne Schalter byte-identisch.
    if config.get('speaking_priority') and cutaway_enabled.get('speaking_reaction'):
        sp_cut = sorted(r['timeline_frame'] - pre_roll_frames
                        for r in valid_reactions if r['type'] == 'speaking_reaction')
        if sp_cut:
            import bisect
            keep = []
            for r in valid_reactions:
                if r['type'] == 'nodding':
                    n_cut = r['timeline_frame'] - pre_roll_frames
                    n_end = n_cut + max(reaction_duration_frames,
                                        max(0, r['peak_tl_frame'] - n_cut + r['tail_frames']))
                    i = bisect.bisect_left(sp_cut, n_cut)
                    if i < len(sp_cut) and sp_cut[i] < n_end + min_shot_frames:
                        if decision_log is not None:
                            decision_log.append({
                                "pass": "2", "action": "skip", "reason": "speaking_priority",
                                "timecode": frames_to_timecode(max(n_cut, section_start), fps),
                                "on_clip": on_clip, "off_clip": r['cam']['name'],
                                "reaction_type": "nodding",
                                "detail": f"Einwurf bei {frames_to_timecode(sp_cut[i], fps)} hat Vorrang",
                            })
                        continue
                keep.append(r)
            valid_reactions = keep

    # Sortieren: erst nach Position, dann nach Confidence absteigend
    valid_reactions.sort(key=lambda x: (x['timeline_frame'], -x['confidence']))

    # Multi-Person-Erkennung: Frames mit ≥2 verschiedenen Close-Kameras innerhalb cluster_max_gap
    close_cam_frames: Dict[str, List[int]] = {}
    for r in valid_reactions:
        close_cam_frames.setdefault(r['cam']['name'], []).append(r['timeline_frame'])

    def _reacting_cams_near(frame: int) -> List[Dict]:
        """Close-Kameras mit einer Reaktion innerhalb cluster_max_gap von frame."""
        return [c for c in close_cams
                if any(abs(f - frame) <= cluster_max_gap
                       for f in close_cam_frames.get(c['name'], []))]

    def _is_multi_person(frame: int) -> bool:
        """True wenn ≥2 Close-Kameras nahe frame reagieren."""
        return len(_reacting_cams_near(frame)) >= 2

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
            if decision_log is not None:
                decision_log.append({
                    "pass": "2", "action": "skip", "reason": "min_shot_spacing",
                    "timecode": frames_to_timecode(cutaway_frame, fps),
                    "on_clip": on_clip, "off_clip": reaction['cam']['name'],
                    "reaction_type": rtype,
                    "gap_frames": cutaway_frame - last_cut_frame,
                    "min_shot_frames": min_shot_frames,
                    "detail": f"Abstand zum letzten Cut nur {cutaway_frame - last_cut_frame} Frames (min {min_shot_frames})",
                })
            continue

        # Schnittabstand je Cutaway-Typ (Slider „Wie oft"): frühestens type_cd nach dem
        # letzten Cutaway desselben Typs auf dieselbe Person. Gespeichert werden die
        # Enden ALLER gesetzten Cutaways (PASS 2 läuft je Sprecher-Kamera, nicht
        # chronologisch) — geprüft wird nur, ob eines kurz VOR diesem liegt.
        _type_cd = int(float((config.get('type_cooldown_s') or {}).get(rtype, 0) or 0) * fps)
        _tkey = (rtype, reaction['cam']['name'])
        if _type_cd > 0:
            _ends = config.setdefault('_type_cutaway_ends', {}).get(_tkey, [])
            _block = next((e for e in _ends if cutaway_frame - _type_cd < e <= cutaway_frame), None)
            if _block is not None:
                if decision_log is not None:
                    decision_log.append({
                        "pass": "2", "action": "skip", "reason": "type_cooldown",
                        "timecode": frames_to_timecode(cutaway_frame, fps),
                        "on_clip": on_clip, "off_clip": reaction['cam']['name'],
                        "reaction_type": rtype,
                        "detail": f"letzter {rtype}-Cutaway endete {cutaway_frame - _block} Frames vorher (min {_type_cd})",
                    })
                continue

        # OFF-Cutaway: Multi-Person → kleinste Kamera, die ALLE Reagierenden zeigt
        # (Totale-Ersatz via smallest_containing); Single-Person → beste Close.
        # Binaer: smallest_containing liefert die Totale; hat sie keine Mics
        # zugeordnet, faengt der wide_cams[0]-Fallback denselben Fall ab. Ohne
        # gemeinsame Kamera bleibt es bei reaction['cam'] — wie bisher.
        _common = (_pick_multi_person_offcam(_reacting_cams_near(cutaway_frame),
                                             cutaway_cams, wide_cams,
                                             pick_totale=_next_totale)
                   if _is_multi_person(cutaway_frame) else None)
        if _common is not None:
            off_cam    = _common
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
            if decision_log is not None:
                decision_log.append({
                    "pass": "2", "action": "skip", "reason": "off_cam_not_ready",
                    "timecode": frames_to_timecode(cutaway_frame, fps),
                    "on_clip": on_clip, "off_clip": off_clip,
                    "reaction_type": rtype,
                    "detail": f"Off-Cam startet {-off_vi_check} Frames spaeter",
                })
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
                fps=fps, reason=base_reason,
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
        config.setdefault('_type_cutaway_ends', {}).setdefault(_tkey, []).append(cutaway_end)

    # Rest der Section
    if current_pos < section_end:
        # Wide als bevorzugter Reset-Schnitt; ohne Totale die breiteste Kamera
        # (meiste Personen) statt stur der ersten Close. Bei mehreren Totalen wird
        # die konkrete Totale pro Cutaway unten via _next_totale() gewaehlt
        # (Round-Robin/zufall); ohne Totale gilt reset_fallback (byte-identisch).
        reset_fallback = None if wide_cams else _pick_widest(close_cams)
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
                        fps=fps, reason=base_reason,
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
                    fps=fps, reason=base_reason,
                ))

                # Totale pro Cutaway waehlen (rotiert bei mehreren Totalen).
                reset_cam = _next_totale() if wide_cams else reset_fallback
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
                        if decision_log is not None:
                            decision_log.append({
                                "pass": "2", "action": "skip", "reason": "off_cam_not_ready",
                                "timecode": frames_to_timecode(cut_start, fps),
                                "on_clip": on_clip, "off_clip": reset_cam['name'],
                                "detail": f"Max-Time Reset: Off-Cam startet {-off_vi} Frames spaeter",
                            })
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
                fps=fps, reason=base_reason,
            ))

    return events


def _nearest_speaker(seq):
    """Erster Nicht-Übergang in `seq` (Reihenfolge wie übergeben), sonst None.

    Der Sandwich-Schutz muss durch eingefügte Brücken HINDURCHSEHEN: eine
    Übergangs-Einstellung zwischen B und dem zurückkehrenden A ist ein
    gewollter Schnitt, kein echter Nachbar. Wer nur auf das unmittelbar
    angrenzende Event schaut, haelt B faelschlich fuer ungeschuetzt, sobald eine
    Bruecke daneben steht — genau so verschwand ein echter Sprecherwechsel.
    """
    for e in seq:
        if getattr(e, 'reason', 'speaker') != "transition":
            return e
    return None


def _is_diarization_switch(event, prev, next_event) -> bool:
    """Prüft ob ein kurzes Event ein reiner Diarization-Sprecherwechsel ist.

    Ein Sprecherwechsel-Sandwich liegt vor, wenn:
    - Das kurze Event reason='speaker' hat
    - Vorgänger und Nachfolger ebenfalls reason='speaker' haben
    - Das Event einen anderen Clip hat als Vorgänger UND Nachfolger
    - Vorgänger und Nachfolger denselben Clip haben (CAM1→CAM2→CAM1)

    `prev`/`next_event` sind die nächsten SPRECHER-Nachbarn (Brücken werden von
    `_nearest_speaker` übersprungen), damit der Schutz auch bei A→B→T→A greift.
    """
    if event.reason != "speaker":
        return False
    if prev is None or prev.reason != "speaker":
        return False
    if next_event is None or next_event.reason != "speaker":
        return False
    if event.clip_name == prev.clip_name:
        return False
    if next_event.clip_name == event.clip_name:
        return False
    return True


# Nur diese Cutaways schneiden auf eine andere CLOSE-Kamera und kommen fuer einen
# Rueckweg ueber eine groessere Einstellung in Frage. Max-Zeit und die
# *_wide-Varianten SIND schon die Totale (Reset bzw. Mehrpersonen-Reaktion) und
# brauchen keinen Uebergang zurueck. Exakter Match schliesst '_wide' automatisch
# aus. Occasion-Schluessel (wie in der Bildsprache-Matrix) → EDL-reason:
CUTAWAY_RETURN_REASONS = {
    'nodding':           'reaction_nodding',
    'speaking_reaction': 'reaction_speaking_reaction',
    'pause':             'pause_cutaway',
}


def _camera_on_cooldown(out: List[EDLEvent], cam: str, cut_cooldown: int,
                        time_cooldown_frames: int, current_frame: int) -> bool:
    """Ist `cam` noch gesperrt — nach SCHNITTEN oder ZEIT, was zuerst faellt?

    Baustein des in brain/Bildsprache.md vorgesehenen `cooldown_ok`-Helfers (R10):
    eine Zusatzkamera soll nicht staendig wiederkehren. Zaehlt ALLE bisherigen
    Vorkommen dieser Kamera im Ausgabestrom (Bruecken, Cutaways,
    Sprecherwechsel-Bruecken), pro Kamera.

    ZWEI Schwellen (User, 22.07.): der reine Schnitt-Zaehler wird von den haeufigen
    Sprecherwechsel-Bruecken staendig zurueckgesetzt, sodass zwischendurch kaum ein
    Rueckweg durchkommt. Deshalb laeuft parallel eine Zeit-Schwelle. Freigegeben
    wird, sobald EINE greift: genug Schnitte ODER genug Zeit seit der letzten
    Verwendung. Gesperrt bleibt nur, wenn beide (aktiven) Schwellen noch unter dem
    Limit liegen.
    """
    cut_active  = cut_cooldown > 0
    time_active = time_cooldown_frames > 0
    if not (cut_active or time_active):
        return False

    for back, e in enumerate(reversed(out), start=1):
        if e.clip_name == cam:
            cut_blocks  = cut_active  and back <= cut_cooldown
            time_blocks = time_active and (current_frame - e.record_out_frame) < time_cooldown_frames
            # Nur eine aktive Schwelle blockiert → diese entscheidet. Beide aktiv →
            # Sperre nur, solange BEIDE noch blockieren (die zuerst fallende gibt frei).
            return (cut_blocks or not cut_active) and (time_blocks or not time_active) \
                   and (cut_blocks or time_blocks)
    return False


def insert_cutaway_return_transitions(
    events: List[EDLEvent], cameras: List[Dict],
    reference_frames: Dict[str, int], timeline_zero_video_frames: Dict[str, int],
    enabled_reasons: set, bridge_len_frames, min_shot_frames: int, fps: float,
    cooldown: int = 0, cooldown_frames: int = 0,
) -> List[EDLEvent]:
    """Weiche Landung zurueck zum Sprecher nach einem Close-Cutaway.

    Aus `Sprecher A → Cutaway X → Sprecher A` wird `A → X → Bruecke → A`: nach dem
    Cutaway fuehrt eine groessere Einstellung (die kleinste Kamera, die die Person
    im Cutaway UND den zurueckkehrenden Sprecher zeigt) zurueck aufs enge Bild.

    Nur der RUECKWEG, kein Hinweg: die Reaktion soll sofort sichtbar sein, der
    Schnitt HIN zum Cutaway bleibt hart (siehe Matrix in brain/Bildsprache.md).

    Die Bruecke frisst den Anfang des zurueckkehrenden Sprechers (nicht den
    Cutaway) — analog zum Sprecherwechsel. Bedingung wie dort: der Sprecher muss
    nach der Bruecke noch min_shot uebrig haben. Sonst kein Uebergang; der Cleanup
    faengt Reste zwar ab, aber schon vorab zu pruefen erzeugt weniger Fragmente
    (User, 22.07.).
    """
    from shot_sizes import smallest_containing, person_ids
    if not enabled_reasons:
        return events

    by_name = {c['name']: c for c in cameras}

    def people(clip):
        c = by_name.get(clip)
        return set(person_ids(c)) if c else set()

    out: List[EDLEvent] = []
    inserted = skipped_cooldown = 0
    for i, ev in enumerate(events):
        prev = events[i - 1] if i > 0 else None
        if (prev is not None and ev.reason == "speaker"
                and prev.reason in enabled_reasons):
            ppl = people(prev.clip_name) | people(ev.clip_name)
            bridge = smallest_containing(cameras, list(ppl)) if ppl else None
            if (bridge and bridge['name'] not in (prev.clip_name, ev.clip_name)
                    and (not out or out[-1].clip_name != bridge['name'])):
                bc   = bridge['name']
                # Cooldown: kam diese Kamera gerade erst? Dann keine Bruecke, der
                # Rueckweg bleibt ein harter Schnitt. Verhindert, dass dieselbe
                # Totale bei jedem Rueckweg wiederkehrt (R10).
                if _camera_on_cooldown(out, bc, cooldown, cooldown_frames,
                                       ev.record_in_frame):
                    skipped_cooldown += 1
                    out.append(ev)
                    continue
                want = bridge_len_frames()
                ev_len = ev.record_out_frame - ev.record_in_frame
                tzv    = timeline_zero_video_frames.get(bc, 0)
                ref    = reference_frames.get(bc, 0)
                vid_start = tzv + ev.record_in_frame
                # Sprecher braucht Platz; Bruecken-Kamera muss laufen.
                if ev_len >= want + min_shot_frames and vid_start >= 0:
                    bridge_end = ev.record_in_frame + want
                    out.append(EDLEvent(
                        0, bc,
                        frames_to_timecode(ref + vid_start, fps),
                        frames_to_timecode(ref + tzv + bridge_end, fps),
                        frames_to_timecode(ev.record_in_frame, fps),
                        frames_to_timecode(bridge_end, fps),
                        fps=fps, reason="transition",
                    ))
                    src_off = ev.source_in_frame - ev.record_in_frame
                    ev = EDLEvent(
                        0, ev.clip_name,
                        frames_to_timecode(src_off + bridge_end, fps),
                        ev.source_out,
                        frames_to_timecode(bridge_end, fps),
                        ev.record_out,
                        fps=fps, reason=ev.reason,
                    )
                    inserted += 1
        out.append(ev)

    if inserted or skipped_cooldown:
        msg = f"  {inserted} Cutaway-Rueckwege eingefügt (weiche Landung)"
        if skipped_cooldown:
            msg += f"; {skipped_cooldown} per Cooldown ausgelassen"
        print(msg)
    return out


def cleanup_short_events(events: List[EDLEvent], min_duration: float, fps: float,
                         decision_log: Optional[List] = None,
                         pass_label: str = "PASS 3", pass_id: str = "3",
                         cutaway_min_duration: Optional[float] = None) -> List[EDLEvent]:
    """Entfernt Reste kürzer als min_duration (prev wird verlängert).

    Reaktions-Cutaways (beta.4, User 19.11.):
    - Für sie gilt höchstens die eingestellte Cutaway-Länge (`cutaway_min_duration`)
      als Mindestlänge — der Cleanup soll Reste wegräumen, nicht Cutaways löschen,
      die der Nutzer selbst so kurz eingestellt hat (Cutaway-Länge 1,6 s bei
      Aufräumlänge 1,8 s löschte sonst ~40 % aller Cutaways).
    - Ist ein Cutaway trotzdem zu kurz (vom nächsten Sprecherwechsel gekappt) und
      gehört die FOLGENDE Einstellung derselben Kamera (die Person, die eingeworfen
      hat, spricht danach selbst), wird er nicht verworfen: die folgende Einstellung
      beginnt schon am Cutaway-Anfang — der Schnitt zu ihr kommt einfach früher.
    """
    print(f"\n🧹 {pass_label}: Cleanup kurzer Events")
    print(f"  Min Duration: {min_duration}s ({int(min_duration * fps)} Frames)")
    min_frames = int(min_duration * fps)
    cut_frames = (min(min_frames, int(cutaway_min_duration * fps))
                  if cutaway_min_duration is not None else min_frames)
    cleaned = []
    removed = 0
    merged_forward = 0
    skipped_diarization = 0
    for i, event in enumerate(events):
        is_cutaway = str(getattr(event, 'reason', '')).startswith('reaction_')
        limit = cut_frames if is_cutaway else min_frames
        if (is_cutaway and event.duration_frames() < limit and i + 1 < len(events)
                and events[i + 1].clip_name == event.clip_name
                and events[i + 1].reason == 'speaker'):
            nxt = events[i + 1]
            shift = nxt.record_in_frame - event.record_in_frame
            nxt.record_in_frame = event.record_in_frame
            nxt.record_in = event.record_in
            nxt.source_in_frame -= shift
            nxt.source_in = frames_to_timecode(nxt.source_in_frame, fps)
            merged_forward += 1
            print(f"  ↦ Früher geschnitten: {event.clip_name} @ {event.record_in} "
                  f"(Cutaway {event.duration_frames()} Frames → Sprecher-Einstellung beginnt hier)")
            if decision_log is not None:
                decision_log.append({
                    "pass": pass_id, "action": "merge_forward", "reason": "cutaway_before_own_turn",
                    "timecode": event.record_in, "event_clip": event.clip_name,
                    "duration_frames": event.duration_frames(),
                    "detail": f"{event.clip_name}: gekappter Cutaway geht in die eigene Sprecher-Einstellung über",
                })
            continue
        if event.duration_frames() < limit and cleaned:
            prev = cleaned[-1]
            # Bruecken sind BEWUSST gesetzte Einstellungen, keine Fragmente.
            # PASS 3 raeumt Reste weg — eine Uebergangs-Einstellung ist keiner,
            # auch wenn sie kurz ist.
            if event.reason == "transition":
                cleaned.append(event)
                continue
            # Sandwich-Nachbarn durch etwaige Bruecken hindurch bestimmen: ein
            # echter Sprecherwechsel A->B->A bleibt geschuetzt, auch wenn eine
            # Bruecke daneben eingefuegt wurde (A->B->T->A).
            prev_speaker = _nearest_speaker(reversed(cleaned))
            next_speaker = _nearest_speaker(events[i + 1:])
            if _is_diarization_switch(event, prev_speaker, next_speaker):
                cleaned.append(event)
                skipped_diarization += 1
                print(f"  ⏭ Sprecherwechsel beibehalten: {event.clip_name} @ {event.record_in} ({event.duration_frames()} Frames)")
                continue
            prev_old_out = prev.record_out
            source_offset = prev.source_in_frame - prev.record_in_frame
            prev.record_out       = event.record_out
            prev.record_out_frame = event.record_out_frame
            prev.source_out_frame = source_offset + event.record_out_frame
            prev.source_out       = frames_to_timecode(prev.source_out_frame, fps)
            removed += 1
            print(f"  ✗ Entfernt: Event @ {event.record_in} ({event.duration_frames()} Frames)")
            if decision_log is not None:
                decision_log.append({
                    "pass": pass_id, "action": "remove", "reason": "too_short",
                    "timecode": event.record_in,
                    "event_clip": event.clip_name,
                    "event_reason": getattr(event, 'reason', ''),
                    "duration_frames": event.duration_frames(),
                    "extended_prev_clip": prev.clip_name,
                    "extended_prev_from": prev_old_out,
                    "extended_prev_to": prev.record_out,
                    "prev_new_duration_frames": prev.duration_frames(),
                    "detail": f"{event.clip_name} ({event.duration_frames()} Frames) entfernt, {prev.clip_name} auf {prev.duration_frames()} Frames verlaengert",
                })
        else:
            cleaned.append(event)
    print(f"  ✓ {removed} entfernt, {merged_forward} früher geschnitten, {skipped_diarization} "
          f"Sprecherwechsel beibehalten, {len(cleaned)} verbleiben")
    return cleaned


def insert_pause_cutaways(
    events: List[EDLEvent],
    pause_data: Dict,
    cameras: List[Dict],
    reference_frames: Dict[str, int],
    timeline_zero_video_frames: Dict[str, int],
    min_shot_frames: int,
    fps: float,
    decision_log: Optional[List] = None,
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
        skip_reason = "no_host_event"
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
                else:
                    skip_reason = "min_shot_margin"

        if host_idx is None:
            if decision_log is not None:
                pause_dur = (pe - ps) / fps
                detail = ("Pause liegt nicht komplett in einem Speaker-Event"
                          if skip_reason == "no_host_event"
                          else f"Mindestabstand zum Event-Rand nicht eingehalten (min {min_shot_frames} Frames)")
                decision_log.append({
                    "pass": "2b", "action": "skip", "reason": skip_reason,
                    "timecode": frames_to_timecode(ps, fps),
                    "pause_duration_s": round(pause_dur, 1),
                    "speaker": spk, "on_clip": on_clip,
                    "detail": detail,
                })
            continue

        ev = result[host_idx]
        on_ref = reference_frames[on_clip]
        on_tzvf = timeline_zero_video_frames[on_clip]

        # Off-Kamera wählen: erste andere Close-Kamera.
        # Der Typ-Filter fehlte, obwohl der Kommentar ihn seit jeher behauptet —
        # je nach Kamera-Reihenfolge landete hier die Totale. Fallback auf eine
        # beliebige andere Cam bleibt, sonst entfiele der Cutaway ganz, wenn es
        # ausser der Totale keine zweite Kamera gibt.
        off_cam = None
        for cam in cameras:
            if cam['name'] != on_clip and cam.get('type', 'close') != 'wide':
                off_cam = cam
                break
        if off_cam is None:
            for cam in cameras:
                if cam['name'] != on_clip:
                    off_cam = cam
                    break
        if not off_cam or off_cam['name'] not in reference_frames:
            if decision_log is not None:
                decision_log.append({
                    "pass": "2b", "action": "skip", "reason": "no_off_cam",
                    "timecode": frames_to_timecode(ps, fps),
                    "pause_duration_s": round((pe - ps) / fps, 1),
                    "speaker": spk, "on_clip": on_clip,
                    "detail": "Keine Off-Kamera verfuegbar",
                })
            continue

        off_clip = off_cam['name']
        off_ref = reference_frames[off_clip]
        off_tzvf = timeline_zero_video_frames[off_clip]

        # Prüfe ob Off-Kamera zum Pause-Zeitpunkt bereits aufnimmt
        off_vi_check = off_tzvf + ps
        if off_vi_check < 0:
            if decision_log is not None:
                decision_log.append({
                    "pass": "2b", "action": "skip", "reason": "off_cam_not_ready",
                    "timecode": frames_to_timecode(ps, fps),
                    "pause_duration_s": round((pe - ps) / fps, 1),
                    "speaker": spk, "on_clip": on_clip, "off_clip": off_clip,
                    "detail": f"Off-Cam startet {-off_vi_check} Frames spaeter",
                })
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
        if decision_log is not None:
            decision_log.append({
                "pass": "2b", "action": "insert", "reason": "pause_cutaway",
                "timecode": frames_to_timecode(ps, fps),
                "pause_duration_s": round((pe - ps) / fps, 1),
                "speaker": spk, "on_clip": on_clip, "off_clip": off_clip,
            })

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
    cam_shot_levels: Dict[str, int] = None,  # {clip_name: Anzahl gezeigter Personen}
    decision_log: Optional[List] = None,
) -> List[EDLEvent]:
    print(f"\n✂️  PASS 4: Split zu lange Shots")
    import math
    threshold_frames = int((max_shot_duration + 3.0) * fps)
    cutaway_frames   = int(cutaway_duration * fps)
    new_events = []
    split_count = 0
    cutaway_count = 0
    types = cam_types_dict or {}
    levels = cam_shot_levels or {}

    def _emit_speaker(parent, rec_in, rec_out):
        """Speaker-Teilstück aus einem Parent-Event mit korrigierten Source-Frames."""
        vi = timeline_zero_video_frames[parent.clip_name] + rec_in
        vo = timeline_zero_video_frames[parent.clip_name] + rec_out
        return EDLEvent(
            event_num=0, clip_name=parent.clip_name,
            source_in=frames_to_timecode(reference_frames[parent.clip_name] + vi, fps),
            source_out=frames_to_timecode(reference_frames[parent.clip_name] + vo, fps),
            record_in=frames_to_timecode(rec_in, fps),
            record_out=frames_to_timecode(rec_out, fps),
            fps=fps, reason=getattr(parent, 'reason', 'speaker'),
        )

    def _emit_cutaway(off_clip_name, cut_start, cut_end):
        """max_time-Cutaway auf der Off-Cam, oder None wenn die Cam noch nicht gestartet ist."""
        off_vi = timeline_zero_video_frames[off_clip_name] + cut_start
        off_vo = timeline_zero_video_frames[off_clip_name] + cut_end
        if off_vi < 0:
            return None
        return EDLEvent(
            event_num=0, clip_name=off_clip_name,
            source_in=frames_to_timecode(reference_frames[off_clip_name] + off_vi, fps),
            source_out=frames_to_timecode(reference_frames[off_clip_name] + off_vo, fps),
            record_in=frames_to_timecode(cut_start, fps),
            record_out=frames_to_timecode(cut_end, fps),
            fps=fps, reason="max_time",
        )

    for idx, event in enumerate(events):
        duration = event.duration_frames()
        if duration <= threshold_frames:
            new_events.append(event)
            continue

        # Wide-Kamera bevorzugt als Split-Ziel (Reset-Schnitt); Fallback: erste andere Close-Kamera
        # Totale bevorzugt als Split-Ziel (Reset-Schnitt); ohne Totale die
        # breiteste andere Kamera (meiste Personen) statt stur der ersten Close.
        # Binaer mit Totale unveraendert; ohne Totale bei gleichen Stufen die
        # erste (max ist stabil) — also byte-identisch, fuer N besser.
        wide_others = [c for c in all_cam_names if c != event.clip_name and types.get(c, 'close') == 'wide']
        if wide_others:
            other_clip = wide_others[0]
        else:
            _others = [c for c in all_cam_names if c != event.clip_name]
            other_clip = max(_others, key=lambda c: levels.get(c, 1)) if _others else None
        if not other_clip or other_clip not in reference_frames:
            new_events.append(event)
            continue

        # Anzahl Cutaways berechnen, sodass jedes Speaker-Stück ≤ threshold bleibt.
        # Bei N Cutaways entstehen N+1 Speaker-Stücke. Damit jedes ≤ threshold:
        #   (duration - N · cutaway_frames) / (N+1) ≤ threshold
        # → N ≥ (duration - threshold) / (threshold + cutaway_frames)
        n_cutaways = max(1, math.ceil(
            (duration - threshold_frames) / (threshold_frames + cutaway_frames)
        ))

        # Sprecherwechsel-Skip: wenn nächstes Event eine andere Cam ist und
        # nur EIN Split nötig wäre UND das Event nur knapp über dem Threshold
        # liegt (max 20% drüber), lieber ungeteilt lassen.
        next_ev = events[idx + 1] if idx + 1 < len(events) else None
        if (n_cutaways == 1 and next_ev and next_ev.clip_name != event.clip_name
                and duration <= threshold_frames * 1.2):
            if decision_log is not None:
                decision_log.append({
                    "pass": "4", "action": "skip", "reason": "speaker_switch_heuristic",
                    "timecode": event.record_in,
                    "event_clip": event.clip_name,
                    "duration_s": round(duration / fps, 1),
                    "next_clip": next_ev.clip_name,
                    "detail": f"Nur 1 Split noetig, naechstes Event ist Sprecherwechsel zu {next_ev.clip_name} — ungeteilt belassen",
                })
            new_events.append(event)
            continue

        # Speaker-Chunk-Länge: gleichmäßig verteilen
        total_speaker_frames = duration - n_cutaways * cutaway_frames
        chunk_frames = total_speaker_frames // (n_cutaways + 1)

        # Sequenz aus (speaker)(cutaway)(speaker)…(cutaway)(speaker) bauen.
        # Bei Off-Cam-Fail (cut_start zu früh): Cutaway weglassen → die
        # umliegenden Speaker-Stücke werden zum nächsten Chunk gemerged.
        segments = []  # list of EDLEvent (in record-Reihenfolge)
        pending_speaker_start = event.record_in_frame
        skipped_cutaways = 0
        for i in range(n_cutaways):
            chunk_end = event.record_in_frame + (i + 1) * (chunk_frames + cutaway_frames) - cutaway_frames
            cut_start = chunk_end
            cut_end   = cut_start + cutaway_frames
            cutaway_ev = _emit_cutaway(other_clip, cut_start, cut_end)
            if cutaway_ev is None:
                # Off-Cam noch nicht gestartet → diesen Slot überspringen, Speaker läuft weiter
                skipped_cutaways += 1
                if decision_log is not None:
                    decision_log.append({
                        "pass": "4", "action": "skip_slot", "reason": "off_cam_not_ready",
                        "timecode": frames_to_timecode(cut_start, fps),
                        "event_clip": event.clip_name, "off_clip": other_clip,
                        "slot": i + 1, "total_slots": n_cutaways,
                        "detail": f"Split-Slot {i+1}/{n_cutaways}: Off-Cam noch nicht aktiv",
                    })
                continue
            segments.append(_emit_speaker(event, pending_speaker_start, cut_start))
            segments.append(cutaway_ev)
            pending_speaker_start = cut_end
        # Finaler Speaker-Rest bis Event-Ende
        if pending_speaker_start < event.record_out_frame:
            segments.append(_emit_speaker(event, pending_speaker_start, event.record_out_frame))

        # Wenn ALLE Cutaways geskippt wurden → original Event unverändert behalten
        if skipped_cutaways == n_cutaways:
            new_events.append(event)
            print(f"  ⚠️  Alle {n_cutaways} Split-Cutaways auf {other_clip} übersprungen "
                  f"(Kamera noch nicht aktiv), Event ungeteilt: @ {event.record_in} ({duration/fps:.1f}s)")
            continue

        new_events.extend(segments)
        applied_cutaways = n_cutaways - skipped_cutaways
        split_count   += 1
        cutaway_count += applied_cutaways
        skip_note = f" ({skipped_cutaways} übersprungen weil {other_clip} noch nicht aktiv)" if skipped_cutaways else ""
        print(f"  ✂️  Split: @ {event.record_in} ({duration/fps:.1f}s) → "
              f"{applied_cutaways} Cutaway(s), {applied_cutaways + 1} Speaker-Stücke{skip_note}")
        if decision_log is not None:
            decision_log.append({
                "pass": "4", "action": "split", "reason": "max_time",
                "timecode": event.record_in,
                "event_clip": event.clip_name,
                "duration_s": round(duration / fps, 1),
                "cutaways_applied": applied_cutaways,
                "cutaways_skipped": skipped_cutaways,
                "off_clip": other_clip,
            })

    print(f"  ✓ {split_count} Events gesplittet, {cutaway_count} max_time-Cutaways eingefügt, "
          f"{len(new_events)} Events total")
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
    score_mode: str = 'sum',
) -> float:
    """Berechnet den Ignore-Score für ein Cutaway-Event (max über 2 Frames).

    score_mode='sum'  → Summe der Ignore-Prompt-Wahrscheinlichkeiten (Default,
                        für max_time/Pausen-Cutaways). Historisch validiert.
    score_mode='max'  → nur der stärkste einzelne Ignore-Prompt. Robuster gegen
                        das Aufstapeln fast identischer Prompts (mehrere „drinking"-
                        Varianten summieren sonst ihre Softmax-Masse und flaggen
                        harmlose Frames). Für den Nodding-DROP-Pfad, wo ein
                        Fehlflag einen echten Nick-Cutaway kostet (gemessen an
                        ep04: max trennt echtes Glas 0,65 sauber von Gestik 0,58).
    """
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
        ignore_probs = probs[:n_ignore]
        scores.append(float(max(ignore_probs)) if score_mode == 'max'
                      else float(sum(ignore_probs)))

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
    threshold = clip_config.get('ignore_threshold', 0.65)
    shift_step_s = clip_config.get('shift_step_s', 2.0)
    max_attempts = clip_config.get('max_attempts', 5)
    # Nodding-Cutaways: manche Nicken sind in Wahrheit Trinkbewegungen (Kopf
    # hoch/runter ≈ Nicken). 'drop' prueft sie mit CLIP und VERWIRFT die
    # geflagten (statt zu verschieben — Verschieben war die Ursache des
    # 0.6.10-Spaetschnitt-Bugs). 'off' laesst sie unangetastet.
    # max-Scoring + Schwelle 0,6: an ep04 trennt das echtes Glas (0,65) sauber
    # von Gestik/Zuhoeren (≤0,58). Sprachreaktionen bleiben IMMER unangetastet.
    # Default 'off' (User, 27.10.): Schwelle erst an echten Trink-Nick-TCs
    # kalibrieren, dann einschalten — 1.0 soll nicht an ihr haengen.
    nodding_mode = clip_config.get('nodding_mode', 'off')
    nodding_threshold = clip_config.get('nodding_threshold', 0.6)

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
    print(f"  Nodding-Modus: {nodding_mode} (Schwelle {nodding_threshold:.0%}, max-Scoring)")

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
    # Erst aus lokalem HF-Cache laden (umgeht httpx-Race bei HF-Hub-Metadaten-Calls).
    # Nur bei Cache-Miss zum Netzwerk-Download fallen.
    _model_id = "openai/clip-vit-base-patch32"
    try:
        model     = CLIPModel.from_pretrained(_model_id, local_files_only=True).to(device)
        processor = CLIPProcessor.from_pretrained(_model_id, local_files_only=True)
    except (OSError, ValueError):
        print(f"  Cache-Miss — lade {_model_id} von HuggingFace Hub...")
        model     = CLIPModel.from_pretrained(_model_id).to(device)
        processor = CLIPProcessor.from_pretrained(_model_id)

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
    nod_checked = 0
    nod_dropped = 0
    drop_nodding = nodding_mode == 'drop'

    result = list(events)
    # max_time/Pausen-Cutaways werden verschoben; Nodding-Cutaways im DROP-Modus
    # zusaetzlich geprueft (verworfen statt verschoben). Sprachreaktionen NIE.
    total_cutaways = sum(
        1 for e in result
        if e.reason != "speaker"
        and (not e.reason.startswith("reaction_")
             or (drop_nodding and e.reason.startswith("reaction_nodding"))))
    # Startzeit fuer die ETA. Dieser Pass ist der mit Abstand teuerste (ein
    # CLIP-Durchlauf je Cutaway), deshalb rechnet er seine Restzeit selbst --
    # genauso wie die Nodding-Analyse (video_reaction_analyzer_v2.4.py:903).
    clip_start_time = time.time()

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, event in enumerate(result):
            if event.reason == "speaker":
                continue

            # Nodding-Cutaways im DROP-Modus: manche Nicken sind Trinkbewegungen
            # (Kopf hoch/runter ≈ Nicken). CLIP prueft sie und VERWIRFT die als
            # Trinken erkannten — statt sie zu verschieben. Verschieben war die
            # Ursache des 0.6.10-Bugs (Cut landete 2 s spaeter auf Zuhoeren). Ein
            # verworfener Cutaway faellt sauber zurueck auf die Sprecher-Kamera und
            # kann das Spaetschnitt-Symptom nie erzeugen. max-Scoring (nicht Summe):
            # die frueheren „drinking"-Prompts stapelten ihre Softmax-Masse und
            # flaggten harmlose Nick-Frames (gemessen 50–67 %).
            if drop_nodding and event.reason.startswith("reaction_nodding"):
                nod_checked += 1
                if total_cutaways:
                    _elapsed = time.time() - clip_start_time
                    _done = checked + nod_checked
                    _eta = (f"{int((total_cutaways-_done)/(_done/_elapsed)//60)}:"
                            f"{int((total_cutaways-_done)/(_done/_elapsed)%60):02d}"
                            if _elapsed > 1 and _done > 0 else "--:--")
                    print(f"__PROGRESS__ {_done/total_cutaways*100:.1f} "
                          f"{_eta} {_done}/{total_cutaways}", flush=True)
                nod_score = _clip_score_for_event(
                    event, clip_to_video, clip_start_s,
                    model, processor, all_prompts, n_ignore,
                    fps, tmpdir, f"nod{i}", device, score_mode='max',
                )
                if nod_score < nodding_threshold:
                    continue
                # DROP: Cutaway zur Fortsetzung der Sprecher-Kamera umschreiben.
                # prev_ev ist der (kontinuierliche) Sprecher-Take, den der Cutaway
                # unterbrochen hat → Source laeuft 1:1 mit Record, also lueckenlos.
                prev_ev = result[i - 1] if i > 0 else None
                if (prev_ev and prev_ev.reason == "speaker"
                        and prev_ev.clip_name in reference_frames):
                    offset = prev_ev.source_in_frame - prev_ev.record_in_frame
                    event.clip_name = prev_ev.clip_name
                    event.reason = "speaker"
                    event.source_in_frame = offset + event.record_in_frame
                    event.source_out_frame = offset + event.record_out_frame
                    event.source_in = frames_to_timecode(event.source_in_frame, fps)
                    event.source_out = frames_to_timecode(event.source_out_frame, fps)
                    nod_dropped += 1
                    print(f"  🥤 Nick verworfen (Trinken {nod_score:.0%}) @ "
                          f"{event.record_in} → {event.clip_name}")
                else:
                    print(f"  🥤 Nick als Trinken erkannt ({nod_score:.0%}) @ "
                          f"{event.record_in}, aber kein Sprecher-Vorgänger — belasse")
                continue

            # A (26.07.): Reaktions-Cutaways NIE zeitverschieben — ihr ganzer Sinn
            # ist, GENAU auf der Reaktion zu sitzen. Der CLIP-Zeit-Shift schob sie
            # vom Nicken weg (0.6.10-Bug). Sprachreaktionen (und Nodding bei
            # nodding_mode!='drop') bleiben komplett unangetastet; CLIP-Shift nur
            # fuer max_time/Pausen-Cutaways (dort ist das Timing flexibel).
            if event.reason.startswith("reaction_"):
                continue

            checked += 1
            # Fortschritt fuer die UI: __PROGRESS__ wird vom JsonLineWriter geparst
            # (gleicher Mechanismus wie die MediaPipe-Analyse). Jeder Check, sonst
            # oszilliert die Progressbar minutenlang ohne echten Wert.
            if total_cutaways:
                _elapsed = time.time() - clip_start_time
                if _elapsed > 1 and checked > 0:
                    _eta_s = (total_cutaways - checked) / (checked / _elapsed)
                    _eta = f"{int(_eta_s // 60)}:{int(_eta_s % 60):02d}"
                else:
                    _eta = "--:--"
                # Reihenfolge: Prozent, ETA, Zaehler. Die ETA steht an derselben
                # Stelle wie bei der Nodding-Analyse, damit beide Schritte
                # dasselbe Format sprechen; der Zaehler kommt zusaetzlich dazu.
                print(f"__PROGRESS__ {checked / total_cutaways * 100:.1f} "
                      f"{_eta} {checked}/{total_cutaways}", flush=True)
            # Lesbare Log-Zeile bleibt grob — sonst flutet sie das Log.
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
    if drop_nodding:
        print(f"  ✓ Nodding: {nod_checked} geprüft, {nod_dropped} als Trinken verworfen")
    return result


def main():
    # Nur für Testläufe (analyse/stufen_test.py): fester Startwert für den
    # Zufallsfaktor, damit Varianten vergleichbar sind. Die App setzt ihn nicht.
    if os.environ.get('MCC_RANDOM_SEED'):
        random.seed(int(os.environ['MCC_RANDOM_SEED']))
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
    cleanup_min_duration    = float(params.get('cleanup_dur', 1.5))
    cutaway_randomness      = float(params.get('randomness', 0.0))
    cluster_max_gap_frames  = int(params.get('cluster_max_gap_frames', 75))
    pre_roll_frames         = int(params.get('pre_roll', 0))
    # Cutaway-Rueckwege: Liste von Occasion-Schluesseln ('nodding',
    # 'speaking_reaction', 'pause'). Leer = aus (Matrix-Default). Siehe
    # brain/Bildsprache.md und CUTAWAY_RETURN_REASONS.
    transition_cutaway_back = params.get('transition_cutaway_back', []) or []
    # Cooldown je Zusatzkamera in SCHNITTEN (R10): 0 = aus. Bremst, dass dieselbe
    # Totale bei jedem Rueckweg wiederkehrt.
    transition_cutaway_cooldown = int(params.get('transition_cutaway_cooldown', 0))
    # Zeit-Schwelle parallel zum Schnitt-Zaehler: freigegeben, was zuerst faellt.
    transition_cutaway_cooldown_s = float(params.get('transition_cutaway_cooldown_s', 0.0))

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
        # Default 0.5→0.65 (26.07.): 0.5 flaggte reine Nick-/Zuhoer-Frames faelschlich
        # als "a person drinking" (gemessen 50–67 %). 0.65 filtert das Gros dieser
        # False-Positives, laesst klares Trinken (hoehere Scores) aber durch.
        # Ueber params['clip_ignore_threshold'] weiterhin ueberschreibbar.
        'ignore_threshold': float(params.get('clip_ignore_threshold', 0.65)),
        'shift_step_s':     float(params.get('clip_shift_step_s', 2.0)),
        'max_attempts':     int(params.get('clip_max_attempts', 5)),
        'prompts_path':     args.clip_filter_config or '',
        # Nodding-Cutaways gegen Trinkbewegungen filtern (verwerfen statt
        # verschieben). max-Scoring, Schwelle 0,6 (an ep04 validiert).
        # Default AUS bis zur Kalibrierung (siehe clip_filter_cutaways).
        'nodding_mode':      params.get('clip_nodding_mode', 'off'),
        'nodding_threshold': float(params.get('clip_nodding_threshold', 0.6)),
    }

    settings = {
        'min_shot_duration':      min_shot_duration,
        'reaction_min_duration':  reaction_min_duration,
        'max_shot_duration':      max_shot_duration,
        'min_confidence':         min_confidence,
        'cutaway_enabled':        cutaway_enabled,
        'cluster_max_gap_frames': cluster_max_gap_frames,
        'pre_roll_frames':        pre_roll_frames,
        'cutaway_randomness':     cutaway_randomness,
        'totale_mode':            str(params.get('totale_mode', 'round_robin')).lower(),
        'speaking_priority':      bool(params.get('speaking_priority', False)),
        # Slider-Bausteine (19.11.): Schnittabstand je Typ (s) + Konfidenz je Nick-Muster
        'type_cooldown_s': {
            'nodding':           float(params.get('nodding_cooldown_s', 0) or 0),
            'speaking_reaction': float(params.get('speaking_cooldown_s', 0) or 0),
        },
        'nodding_pattern_min_conf': params.get('nodding_pattern_min_conf') or {},
    }

    # Decision Log: nur im Dev-Modus aktiv
    decision_log = None
    try:
        from shared.dev_mode import is_dev_mode
        if is_dev_mode():
            decision_log = []
    except ImportError:
        pass

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
                # Begruendung aus der Basis-EDL mitfuehren. PASS 2 baut die
                # ON-Clip-Events neu; ohne das hier bekaemen sie pauschal
                # 'speaker' und eine Uebergangs-Einstellung waere danach nicht
                # mehr von einem gewoehnlichen Sprecherbild zu unterscheiden.
                'reason':         getattr(event, 'reason', 'speaker'),
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
                'mics':                cam.get('mics', []),
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
            # Keine OFF-Kamera → Sections direkt als Events übernehmen.
            # Genau hier landen die Uebergangs-Einstellungen: die Bruecke ist die
            # Totale, und fuer sie gibt es keine Cutaway-Quellen. Ohne die
            # Begruendung aus der Section haetten ausgerechnet SIE wieder
            # 'speaker' getragen.
            for sec in sections:
                vi = sec['video_start']
                vo = vi + (sec['timeline_end'] - sec['timeline_start'])
                all_events.append(EDLEvent(
                    event_num=0, clip_name=on_name,
                    source_in=frames_to_timecode(reference_frames[on_name] + vi, args.fps),
                    source_out=frames_to_timecode(reference_frames[on_name] + vo, args.fps),
                    record_in=frames_to_timecode(sec['timeline_start'], args.fps),
                    record_out=frames_to_timecode(sec['timeline_end'], args.fps),
                    fps=args.fps, reason=sec.get('reason', 'speaker'),
                ))
            continue

        cam_cutaways = 0
        for sec in sections:
            evs = build_events_with_cutaways(
                sec['timeline_start'], sec['timeline_end'], sec['video_start'],
                on_name, reference_frames[on_name],
                cutaway_cams, settings, args.fps,
                decision_log=decision_log,
                base_reason=sec.get('reason', 'speaker'),
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
            decision_log=decision_log,
        )

    # Pass 2c: Cutaway-Rueckwege (weiche Landung zurueck zum Sprecher).
    # NACH allen Cutaways (2 + 2b), damit die Positionen feststehen, aber VOR
    # dem Cleanup: der transition-bewusste PASS 3 schuetzt die eingefuegten
    # Bruecken und raeumt eventuelle Reste auf.
    if transition_cutaway_back:
        enabled = {CUTAWAY_RETURN_REASONS[k] for k in transition_cutaway_back
                   if k in CUTAWAY_RETURN_REASONS}
        min_shot_frames = int(min_shot_duration * args.fps)

        def _cutaway_bridge_len():
            import random as _r
            factor = 1.0 + _r.uniform(0.0, cutaway_randomness) if cutaway_randomness > 0 else 1.0
            return max(1, int(round(min_shot_duration * factor * args.fps)))

        print(f"\n🎬 PASS 2c: Cutaway-Rueckwege ({', '.join(transition_cutaway_back)})")
        all_events = insert_cutaway_return_transitions(
            all_events, cameras, reference_frames, timeline_zero_video_frames,
            enabled, _cutaway_bridge_len, min_shot_frames, args.fps,
            cooldown=transition_cutaway_cooldown,
            cooldown_frames=int(transition_cutaway_cooldown_s * args.fps),
        )

    # Pass 3: Cleanup
    final_events = cleanup_short_events(all_events, cleanup_min_duration, args.fps,
                                        decision_log=decision_log,
                                        cutaway_min_duration=reaction_min_duration)

    # Pass 4: Split zu lange Shots
    all_cam_names  = [cam['name'] for cam in cameras]
    cam_types_dict = {cam['name']: cam.get('type', 'close') for cam in cameras}
    final_events = split_long_shots(
        final_events, max_shot_duration, cleanup_min_duration,
        reference_frames, timeline_zero_video_frames, all_cam_names, args.fps,
        cam_types_dict=cam_types_dict,
        cam_shot_levels={c['name']: max(1, len(c.get('mics') or [])) for c in cameras},
        decision_log=decision_log,
    )

    # Pass 5: CLIP Ignore-Filter
    if clip_filter_enabled and clip_config.get('prompts_path'):
        final_events = clip_filter_cutaways(
            final_events, cameras,
            reference_frames, timeline_zero_video_frames,
            clip_config, args.fps,
        )

    # Pass 6 (D, 26.07.): Finaler Cleanup. PASS 3 lief VOR dem max_time-Split
    # (PASS 4) und vor CLIP (PASS 5). Winzige Basis-Kamera-Splitter zwischen zwei
    # benachbarten Cutaways (Realfall: 4-Frame-„Robin" zwischen zwei Max-Zeit-
    # Clips), die diese Paesse erzeugen bzw. eine CLIP-Verschiebung hinterlaesst,
    # blieben sonst stehen. Ein zweiter Cleanup raeumt sie weg; Uebergaenge und
    # echte Sprecherwechsel bleiben geschuetzt (dieselbe Logik wie PASS 3).
    final_events = cleanup_short_events(
        final_events, cleanup_min_duration, args.fps,
        decision_log=decision_log, pass_label="PASS 6", pass_id="6",
        cutaway_min_duration=reaction_min_duration)

    write_edl(final_events, args.output)

    colors_path = Path(args.output).with_suffix('.colors.json')
    colors_path.write_text(json.dumps([{'reason': e.reason} for e in final_events], indent=2),
                           encoding='utf-8')
    print(f"✓ Colors-Metadaten: {colors_path.name}")

    # Decision Log schreiben (nur Dev-Modus)
    if decision_log is not None:
        dl_path = Path(args.output).with_name('decision_log.json')
        dl_path.write_text(json.dumps(decision_log, indent=2, ensure_ascii=False),
                           encoding='utf-8')
        print(f"✓ Decision Log: {dl_path.name} ({len(decision_log)} Eintraege)")

    print(f"\n{'=' * 70}\n✓ FERTIG! {len(final_events)} Events → {args.output}\n{'=' * 70}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
