#!/usr/bin/env python3
"""
Add Reactions to EDL v3.0
Kombiniert Resolve's Scene-Cut EDL mit MediaPipe Reaktions-Daten

Multi-Pass Architektur:
- Pass 1: Original-EDL parsen, Cam1/Cam2 Sections sammeln
- Pass 2: Für Cam1-Sections → Cam2-Reaktionen einbauen
- Pass 3: Für Cam2-Sections → Cam1-Reaktionen einbauen
- Pass 4: Cleanup - zu kurze Events entfernen

Author: Max's Podcast Automation
Version: 3.0 - Multi-Pass Architektur
"""

import json
import argparse
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import configparser
import os
import subprocess


def load_config(config_path='config.ini'):
    """Lade Config-Datei"""
    config = configparser.ConfigParser()
    
    search_paths = [
        config_path,
        Path(__file__).parent / 'config.ini',
        Path.cwd() / 'config.ini'
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            config.read(path)
            print(f"✓ Config geladen: {path}")
            return config
    
    print(f"⚠️  config.ini nicht gefunden, nutze Default-Werte")
    return None


def timecode_to_frames(tc: str, fps: float = 25.0) -> int:
    """Konvertiert Timecode zu Frames (HH:MM:SS:FF)"""
    parts = tc.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    frames = int(parts[3])
    
    total_frames = (hours * 3600 + minutes * 60 + seconds) * fps + frames
    return int(total_frames)


def get_embedded_timecode(video_path: str, fps: float = 25.0) -> Optional[str]:
    """
    Lese embedded timecode bei Frame 0 aus Video File mit ffprobe
    
    Returns:
        Timecode string (HH:MM:SS:FF) oder None wenn nicht vorhanden
    """
    try:
        # ffprobe um embedded TC zu lesen
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-select_streams', 'v:0',
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return None
            
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if not streams:
            return None
            
        # Suche nach timecode tag
        tags = streams[0].get('tags', {})
        timecode = tags.get('timecode')
        
        return timecode if timecode else None
        
    except Exception as e:
        print(f"    ⚠️  ffprobe Fehler bei {Path(video_path).name}: {e}")
        return None


def frames_to_timecode(frames: int, fps: float = 25.0) -> str:
    """Konvertiert Frames zu Timecode (HH:MM:SS:FF)"""
    if frames < 0:
        frames = 0
    
    total_seconds = frames / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    frame_part = int(frames % fps)
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame_part:02d}"


class EDLEvent:
    """Ein Event in der EDL"""
    def __init__(self, event_num: int, clip_name: str, 
                 source_in: str, source_out: str,
                 record_in: str, record_out: str, fps: float = 25.0):
        self.event_num = event_num
        self.clip_name = clip_name
        self.source_in = source_in
        self.source_out = source_out
        self.record_in = record_in
        self.record_out = record_out
        self.fps = fps
        
        # Konvertiere zu Frames
        self.source_in_frame = timecode_to_frames(source_in, fps)
        self.source_out_frame = timecode_to_frames(source_out, fps)
        self.record_in_frame = timecode_to_frames(record_in, fps)
        self.record_out_frame = timecode_to_frames(record_out, fps)
    
    def duration_frames(self) -> int:
        """Event-Dauer in Frames"""
        return self.record_out_frame - self.record_in_frame
    
    def __repr__(self):
        return f"Event {self.event_num}: {self.clip_name} R[{self.record_in}-{self.record_out}]"


def parse_resolve_edl(edl_path: str, fps: float = 25.0) -> List[EDLEvent]:
    """
    Pass 1: Parse Resolve EDL (nur Video-Events)
    """
    print(f"\n📋 PASS 1: Parse Resolve EDL")
    print(f"  File: {edl_path}")
    
    events = []
    
    with open(edl_path, 'r') as f:
        lines = f.readlines()
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Event-Zeile - NUR Video (V)
        event_match = re.match(r'^(\d+)\s+\w+\s+V\s+C\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)', line)
        
        if event_match:
            event_num = int(event_match.group(1))
            source_in = event_match.group(2)
            source_out = event_match.group(3)
            record_in = event_match.group(4)
            record_out = event_match.group(5)
            
            # Nächste Zeile: Clip-Name
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                clip_match = re.match(r'\* FROM CLIP NAME:\s*(.+)', next_line)
                
                if clip_match:
                    clip_name = clip_match.group(1).strip()
                    
                    event = EDLEvent(
                        event_num=event_num,
                        clip_name=clip_name,
                        source_in=source_in,
                        source_out=source_out,
                        record_in=record_in,
                        record_out=record_out,
                        fps=fps
                    )
                    events.append(event)
        
        i += 1
    
    print(f"  ✓ {len(events)} Video-Events gefunden")
    
    return events


def load_reactions(json_path: str) -> Tuple[List[Dict], float]:
    """Lade Reaktions-JSON"""
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    reactions = data.get('reactions', [])
    fps = data.get('fps', 25.0)
    
    return reactions, fps


def get_video_timecode_with_ffprobe(video_path: str) -> Optional[str]:
    """
    Liest embedded Timecode aus Video mit ffprobe
    
    Returns:
        Timecode string (HH:MM:SS:FF) oder None
    """
    import subprocess
    import json as json_module
    
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json_module.loads(result.stdout)
        
        # Suche timecode in format tags
        if 'format' in data and 'tags' in data['format']:
            if 'timecode' in data['format']['tags']:
                return data['format']['tags']['timecode']
        
        # Suche timecode in stream tags
        if 'streams' in data:
            for stream in data['streams']:
                if 'tags' in stream and 'timecode' in stream['tags']:
                    return stream['tags']['timecode']
        
        return None
        
    except Exception as e:
        print(f"    ⚠️  ffprobe Fehler: {e}")
        return None


def calculate_reference_frames(events: List[EDLEvent], cam1_clip: str, cam2_clip: str,
                              cam1_video_path: Optional[str] = None,
                              cam2_video_path: Optional[str] = None,
                              cam1_embedded_tc: Optional[str] = None,
                              cam2_embedded_tc: Optional[str] = None,
                              fps: float = 25.0) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Berechne Referenz-Frames für Timeline → Video Frame Mapping
    
    WICHTIG: Reference Frame = ffprobe TAG:timecode des Videos
    Die EDL Source-TCs beziehen sich auf diesen TC.
    Video Frame = EDL Source Frame - TAG:timecode Frame
    
    Returns:
        Tuple: (reference_frames, timeline_zero_video_frames)
        - reference_frames: Für Source TC Berechnung
        - timeline_zero_video_frames: Welcher Video Frame ist bei Timeline 0
    
    Args:
        cam1_video_path: Pfad zur Cam1 Video-Datei (für ffprobe)
        cam2_video_path: Pfad zur Cam2 Video-Datei (für ffprobe)
        cam1_embedded_tc: Manuell angegebener TC (überschreibt ffprobe)
        cam2_embedded_tc: Manuell angegebener TC (überschreibt ffprobe)
    """
    reference_frames = {}
    timeline_zero_video_frames = {}
    
    # Finde ersten Event für jeden Clip  
    first_events = {}
    for event in events:
        if event.clip_name not in first_events:
            first_events[event.clip_name] = event
    
    # Berechne Reference Frames
    for clip_name, event in first_events.items():
        embedded_tc = None
        source = "fallback"
        
        # Bestimme embedded TC
        if clip_name == cam1_clip:
            if cam1_embedded_tc:
                # Manuell angegeben (höchste Priorität)
                embedded_tc = cam1_embedded_tc
                source = "manual"
            elif cam1_video_path:
                # Aus Video lesen
                embedded_tc = get_video_timecode_with_ffprobe(cam1_video_path)
                source = "ffprobe"
            
        elif clip_name == cam2_clip:
            if cam2_embedded_tc:
                embedded_tc = cam2_embedded_tc
                source = "manual"
            elif cam2_video_path:
                embedded_tc = get_video_timecode_with_ffprobe(cam2_video_path)
                source = "ffprobe"
        
        if embedded_tc:
            # Reference Frame = Video TAG:timecode
            reference_frame = timecode_to_frames(embedded_tc, fps)
            reference_frames[clip_name] = reference_frame
            
            # KRITISCH: Berechne wo Timeline 0 im Video liegt!
            # Erster Event: Timeline X, Video Frame Y
            # Timeline 0 = Video Frame (Y - X)
            first_event_video_frame = event.source_in_frame - reference_frame
            first_event_timeline_frame = event.record_in_frame
            timeline_zero_video_frame = first_event_video_frame - first_event_timeline_frame
            timeline_zero_video_frames[clip_name] = timeline_zero_video_frame
            
            print(f"    {clip_name}:")
            print(f"      Video TAG:timecode: {embedded_tc} = {reference_frame} frames [{source}]")
            print(f"      Timeline 0 = Video Frame {timeline_zero_video_frame}")
            print(f"      Verification: Timeline {first_event_timeline_frame} = Video Frame {first_event_video_frame}")
            
        else:
            # Fallback: alte (falsche) Methode
            old_reference = event.source_in_frame - event.record_in_frame
            reference_frames[clip_name] = old_reference
            timeline_zero_video_frames[clip_name] = 0
            print(f"    {clip_name}: {old_reference}")
            print(f"      ⚠️  WARNUNG: Kein embedded TC - Mapping möglicherweise inkorrekt!")
    
    return reference_frames, timeline_zero_video_frames
    
    # Finde ersten Event für jeden Clip
    first_events = {}
    for event in events:
        if event.clip_name not in first_events:
            first_events[event.clip_name] = event
    
    # Berechne Reference Frames
    for clip_name, event in first_events.items():
        # Standard-Methode (FALSCH - gibt Timeline Frames statt Video Frames!)
        # Wird nur als Fallback benutzt wenn keine embedded TCs gefunden werden
        old_reference = event.source_in_frame - event.record_in_frame
        
        embedded_tc = None
        video_path = None
        
        # Bestimme welche Kamera
        if clip_name == cam1_clip:
            video_path = cam1_video_path
            embedded_tc = cam1_embedded_tc
        elif clip_name == cam2_clip:
            video_path = cam2_video_path
            embedded_tc = cam2_embedded_tc
        
        # 1. Versuche ffprobe
        if video_path and Path(video_path).exists():
            print(f"    {clip_name}: Lese embedded TC mit ffprobe...")
            auto_tc = get_embedded_timecode(video_path, fps)
            if auto_tc:
                embedded_tc = auto_tc
                print(f"      ✓ Gefunden: {embedded_tc}")
        
        # 2. Berechne mit embedded TC (automatisch oder manuell)
        if embedded_tc:
            embedded_frame = timecode_to_frames(embedded_tc, fps)
            
            # Timeline Frame 0 liegt bei diesem embedded TC Frame:
            timeline_zero_tc = event.source_in_frame - event.record_in_frame
            
            # Multicam Offset = Wo im Video liegt Timeline Frame 0
            multicam_offset = timeline_zero_tc - embedded_frame
            
            # Reference = Embedded TC - Offset
            reference_frames[clip_name] = embedded_frame - multicam_offset
            
            print(f"      Embedded TC bei Frame 0: {embedded_tc} ({embedded_frame} frames)")
            print(f"      Timeline 0 liegt bei TC: {timeline_zero_tc} frames")
            print(f"      Multicam Offset: {multicam_offset} frames")
            print(f"      → Reference: {reference_frames[clip_name]}")
            
        else:
            # 3. Fallback: alte (falsche) Methode
            reference_frames[clip_name] = old_reference
            print(f"    {clip_name}: {old_reference}")
            print(f"      ⚠️  WARNUNG: Kein embedded TC! Ergebnis möglicherweise inkorrekt!")
            print(f"      → Gib Video-Pfad mit --cam1-video/--cam2-video an")
    
    return reference_frames


def build_events_with_cutaways(section_start: int,
                               section_end: int,
                               section_video_start: int,
                               on_clip: str,
                               on_reference_frame: int,
                               off_clip: str,
                               off_reference_frame: int,
                               off_timeline_zero_video: int,
                               reactions: List[Dict],
                               config: Dict,
                               fps: float) -> List[EDLEvent]:
    """
    Baut Events für eine Section mit Cutaways
    
    Args:
        section_start/end: Timeline Frames der Section
        section_video_start: Video Frame wo diese Section im ON-clip startet
        on_clip: Clip der zu sehen ist (ON-camera)
        on_reference_frame: Referenz-Frame für ON-clip
        off_clip: Clip für Cutaways (OFF-camera)
        off_reference_frame: Referenz-Frame für OFF-clip
        off_timeline_zero_video: Welcher Video Frame im OFF-clip ist bei Timeline 0
        reactions: Reaktionen vom OFF-clip
        config: Settings (min_shot_duration, reaction_min_duration, min_confidence, max_shot_duration)
        fps: Frames per second
    """
    min_shot_frames = int(config['min_shot_duration'] * fps)
    reaction_duration_frames = int(config['reaction_min_duration'] * fps)
    max_shot_frames = int(config['max_shot_duration'] * fps)
    min_confidence = config['min_confidence']
    cluster_max_gap = int(config.get('cluster_max_gap_frames', 75))
    pre_roll_frames = int(config.get('pre_roll_frames', 0))
    cutaway_enabled = config['cutaway_enabled']
    
    # Filtere Reaktionen für diese Section
    valid_reactions = []
    for reaction in reactions:
        reaction_type = reaction['type']
        confidence = reaction['confidence']
        json_video_frame = reaction['frame']
        
        # Filter
        if not cutaway_enabled.get(reaction_type, False):
            continue
        if confidence < min_confidence:
            continue
        
        # KRITISCH: JSON Video Frame → Timeline Frame Konvertierung!
        # JSON gibt Video Frames (ab 0 im File)
        # Timeline Frame = JSON Video Frame - Timeline-0-Video-Frame
        timeline_frame = json_video_frame - off_timeline_zero_video
        
        # Ignoriere Reaktionen vor Timeline 0
        # (JSON analysiert komplettes Video, auch Teile vor Multicam-Start)
        if timeline_frame < 0:
            continue
        
        # Liegt in dieser Section?
        if section_start <= timeline_frame < section_end:
            valid_reactions.append({
                'timeline_frame': timeline_frame,
                'type': reaction_type,
                'confidence': confidence
            })
    
    # Sortiere Reaktionen
    valid_reactions.sort(key=lambda x: x['timeline_frame'])
    
    # Baue Events
    events = []
    current_pos = section_start
    last_cut_frame = section_start
    
    for i, reaction in enumerate(valid_reactions):
        # Finde Cluster-Start: geh rückwärts solange Abstand ≤ cluster_max_gap
        # → schneidet beim ersten Event des Clusters, nicht beim auslösenden
        cluster_start = reaction['timeline_frame']
        for j in range(i - 1, -1, -1):
            if valid_reactions[j]['type'] != reaction['type']:
                break
            gap = valid_reactions[j + 1]['timeline_frame'] - valid_reactions[j]['timeline_frame']
            if gap <= cluster_max_gap:
                cluster_start = valid_reactions[j]['timeline_frame']
            else:
                break
        # Pre-Roll anwenden (nach Cluster-Suche, begrenzt auf section_start)
        cutaway_frame = max(cluster_start - pre_roll_frames, section_start)

        # Min Shot Duration check
        if cutaway_frame - last_cut_frame < min_shot_frames:
            continue
        
        # 1. ON-Event bis Cutaway
        if cutaway_frame > current_pos:
            # Timeline Frame → Video Frame Konvertierung
            video_in = section_video_start + (current_pos - section_start)
            video_out = section_video_start + (cutaway_frame - section_start)
            
            on_source_in = on_reference_frame + video_in
            on_source_out = on_reference_frame + video_out
            
            event1 = EDLEvent(
                event_num=0,  # Wird später renummeriert
                clip_name=on_clip,
                source_in=frames_to_timecode(on_source_in, fps),
                source_out=frames_to_timecode(on_source_out, fps),
                record_in=frames_to_timecode(current_pos, fps),
                record_out=frames_to_timecode(cutaway_frame, fps),
                fps=fps
            )
            events.append(event1)
        
        # 2. OFF-Camera Cutaway
        cutaway_end = min(cutaway_frame + reaction_duration_frames, section_end)
        
        # OFF-Clip: Timeline Frame → Video Frame
        # Video Frame = timeline_zero_video + timeline_frame
        off_video_in = off_timeline_zero_video + cutaway_frame
        off_video_out = off_timeline_zero_video + cutaway_end
        
        off_source_in = off_reference_frame + off_video_in
        off_source_out = off_reference_frame + off_video_out
        
        event2 = EDLEvent(
            event_num=0,
            clip_name=off_clip,
            source_in=frames_to_timecode(off_source_in, fps),
            source_out=frames_to_timecode(off_source_out, fps),
            record_in=frames_to_timecode(cutaway_frame, fps),
            record_out=frames_to_timecode(cutaway_end, fps),
            fps=fps
        )
        events.append(event2)
        
        last_cut_frame = cutaway_end
        current_pos = cutaway_end
    
    # 3. Rest der Section (falls übrig)
    # Wenn Rest > max_shot_duration: Füge forced Cutaways ein
    if current_pos < section_end:
        remaining_duration = section_end - current_pos
        
        if remaining_duration > max_shot_frames:
            # Rest ist zu lang - füge forced Cutaways ein
            while current_pos < section_end:
                # Nächster forced Cutaway bei current_pos + max_shot_frames
                next_cut = min(current_pos + max_shot_frames, section_end)
                
                # Ist das der letzte Abschnitt?
                if next_cut >= section_end:
                    # Letzter Abschnitt - Timeline → Video Frame
                    video_in = section_video_start + (current_pos - section_start)
                    video_out = section_video_start + (section_end - section_start)
                    
                    on_source_in = on_reference_frame + video_in
                    on_source_out = on_reference_frame + video_out
                    
                    event = EDLEvent(
                        event_num=0,
                        clip_name=on_clip,
                        source_in=frames_to_timecode(on_source_in, fps),
                        source_out=frames_to_timecode(on_source_out, fps),
                        record_in=frames_to_timecode(current_pos, fps),
                        record_out=frames_to_timecode(section_end, fps),
                        fps=fps
                    )
                    events.append(event)
                    break
                else:
                    # ON-Clip bis forced Cutaway - Timeline → Video Frame
                    video_in = section_video_start + (current_pos - section_start)
                    video_out = section_video_start + (next_cut - section_start)
                    
                    on_source_in = on_reference_frame + video_in
                    on_source_out = on_reference_frame + video_out
                    
                    event1 = EDLEvent(
                        event_num=0,
                        clip_name=on_clip,
                        source_in=frames_to_timecode(on_source_in, fps),
                        source_out=frames_to_timecode(on_source_out, fps),
                        record_in=frames_to_timecode(current_pos, fps),
                        record_out=frames_to_timecode(next_cut, fps),
                        fps=fps
                    )
                    events.append(event1)
                    
                    # Forced Cutaway zur OFF-Kamera
                    cutaway_end = min(next_cut + reaction_duration_frames, section_end)
                    
                    # OFF-Clip: Timeline Frame → Video Frame
                    off_video_in = off_timeline_zero_video + next_cut
                    off_video_out = off_timeline_zero_video + cutaway_end
                    
                    off_source_in = off_reference_frame + off_video_in
                    off_source_out = off_reference_frame + off_video_out
                    
                    event2 = EDLEvent(
                        event_num=0,
                        clip_name=off_clip,
                        source_in=frames_to_timecode(off_source_in, fps),
                        source_out=frames_to_timecode(off_source_out, fps),
                        record_in=frames_to_timecode(next_cut, fps),
                        record_out=frames_to_timecode(cutaway_end, fps),
                        fps=fps
                    )
                    events.append(event2)
                    
                    current_pos = cutaway_end
        else:
            # Rest ist kurz genug - normal einfügen
            # Timeline → Video Frame
            video_in = section_video_start + (current_pos - section_start)
            video_out = section_video_start + (section_end - section_start)
            
            on_source_in = on_reference_frame + video_in
            on_source_out = on_reference_frame + video_out
            
            event3 = EDLEvent(
                event_num=0,
                clip_name=on_clip,
                source_in=frames_to_timecode(on_source_in, fps),
                source_out=frames_to_timecode(on_source_out, fps),
                record_in=frames_to_timecode(current_pos, fps),
                record_out=frames_to_timecode(section_end, fps),
                fps=fps
            )
            events.append(event3)
    
    return events


def cleanup_short_events(events: List[EDLEvent], min_duration: float, fps: float) -> List[EDLEvent]:
    """
    Pass 4: Cleanup - entferne zu kurze Events
    
    Wenn Event < min_duration:
    - Entferne diesen Event
    - Verlängere vorherigen Event bis zum nächsten
    """
    print(f"\n🧹 PASS 4: Cleanup kurzer Events")
    print(f"  Min Duration: {min_duration}s ({int(min_duration * fps)} Frames)")
    
    min_frames = int(min_duration * fps)
    
    cleaned = []
    removed_count = 0
    
    i = 0
    while i < len(events):
        event = events[i]
        duration = event.duration_frames()
        
        if duration < min_frames and cleaned:
            # Event zu kurz! Entferne ihn und verlängere vorherigen
            prev_event = cleaned[-1]
            
            # Verlängere vorherigen bis zum Ende dieses Events
            prev_event.record_out = event.record_out
            prev_event.record_out_frame = event.record_out_frame
            
            # Source-Out anpassen (nur wenn gleicher Clip!)
            if prev_event.clip_name == event.clip_name:
                prev_event.source_out = event.source_out
                prev_event.source_out_frame = event.source_out_frame
            
            removed_count += 1
            print(f"  ✗ Entfernt: Event @ {event.record_in} ({duration} Frames = {duration/fps:.2f}s)")
        else:
            cleaned.append(event)
        
        i += 1
    
    print(f"  ✓ {removed_count} Events entfernt")
    print(f"  ✓ {len(cleaned)} Events verbleiben")
    
    return cleaned


def split_long_shots(events: List[EDLEvent],
                     max_shot_duration: float,
                     cutaway_duration: float,
                     reference_frames: Dict[str, int],
                     timeline_zero_video_frames: Dict[str, int],
                     fps: float) -> List[EDLEvent]:
    """
    Pass 5: Split zu lange Shots
    
    Wenn Event > max_shot_duration + 3s:
    - Schneide in der Mitte auf andere Kamera für cutaway_duration
    """
    print(f"\n✂️  PASS 5: Split zu lange Shots")
    
    threshold_frames = int((max_shot_duration + 3.0) * fps)
    cutaway_frames = int(cutaway_duration * fps)
    
    print(f"  Threshold: {max_shot_duration + 3.0}s ({threshold_frames} Frames)")
    print(f"  Cutaway Duration: {cutaway_duration}s ({cutaway_frames} Frames)")
    
    # Finde die beiden Clips
    clips = list(set(e.clip_name for e in events))
    if len(clips) != 2:
        print(f"  ⚠️  Warnung: Erwarte 2 Clips, fand {len(clips)} - überspringe Pass 5")
        return events
    
    new_events = []
    split_count = 0
    
    for event in events:
        duration = event.duration_frames()
        
        if duration > threshold_frames:
            # Zu lang! Split in der Mitte
            split_count += 1
            
            # Andere Kamera
            other_clip = clips[1] if event.clip_name == clips[0] else clips[0]
            
            # Mitte des Events
            middle_timeline = event.record_in_frame + (duration // 2)
            
            # Cutaway Start/End (zentriert um Mitte)
            cutaway_start = middle_timeline - (cutaway_frames // 2)
            cutaway_end = cutaway_start + cutaway_frames
            
            # Event 1: ON bis Cutaway
            on_video_in_1 = timeline_zero_video_frames[event.clip_name] + event.record_in_frame
            on_video_out_1 = timeline_zero_video_frames[event.clip_name] + cutaway_start
            
            event1 = EDLEvent(
                event_num=0,
                clip_name=event.clip_name,
                source_in=frames_to_timecode(reference_frames[event.clip_name] + on_video_in_1, fps),
                source_out=frames_to_timecode(reference_frames[event.clip_name] + on_video_out_1, fps),
                record_in=event.record_in,
                record_out=frames_to_timecode(cutaway_start, fps),
                fps=fps
            )
            new_events.append(event1)
            
            # Event 2: OFF Cutaway
            off_video_in = timeline_zero_video_frames[other_clip] + cutaway_start
            off_video_out = timeline_zero_video_frames[other_clip] + cutaway_end
            
            event2 = EDLEvent(
                event_num=0,
                clip_name=other_clip,
                source_in=frames_to_timecode(reference_frames[other_clip] + off_video_in, fps),
                source_out=frames_to_timecode(reference_frames[other_clip] + off_video_out, fps),
                record_in=frames_to_timecode(cutaway_start, fps),
                record_out=frames_to_timecode(cutaway_end, fps),
                fps=fps
            )
            new_events.append(event2)
            
            # Event 3: ON nach Cutaway
            on_video_in_3 = timeline_zero_video_frames[event.clip_name] + cutaway_end
            on_video_out_3 = timeline_zero_video_frames[event.clip_name] + event.record_out_frame
            
            event3 = EDLEvent(
                event_num=0,
                clip_name=event.clip_name,
                source_in=frames_to_timecode(reference_frames[event.clip_name] + on_video_in_3, fps),
                source_out=frames_to_timecode(reference_frames[event.clip_name] + on_video_out_3, fps),
                record_in=frames_to_timecode(cutaway_end, fps),
                record_out=event.record_out,
                fps=fps
            )
            new_events.append(event3)
            
            print(f"  ✂️  Split: Event @ {event.record_in} ({duration/fps:.1f}s) → 3 Events")
        else:
            new_events.append(event)
    
    print(f"  ✓ {split_count} Events gesplittet")
    print(f"  ✓ {len(new_events)} Events total")
    
    return new_events


def write_edl(events: List[EDLEvent], output_path: str, title: str = "Multicam with Reactions"):
    """Schreibt Events als EDL"""
    print(f"\n💾 Schreibe EDL: {output_path}")
    
    lines = [
        f"TITLE: {title}",
        "FCM: NON-DROP FRAME\n"
    ]
    
    for i, event in enumerate(events, 1):
        lines.append(f"{i:03d}  AX       V     C        {event.source_in} {event.source_out} {event.record_in} {event.record_out}")
        lines.append(f"* FROM CLIP NAME: {event.clip_name}\n")
    
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"✓ {len(events)} Events geschrieben")


def main():
    parser = argparse.ArgumentParser(
        description='Fügt Reaktions-Cutaways zu Resolve EDL hinzu (v3.0 - Multi-Pass)'
    )
    parser.add_argument('--resolve-edl', required=True,
                        help='Resolve EDL (flattened Multicam)')
    parser.add_argument('--cam1-clip', required=True,
                        help='Clip-Name für Kamera 1')
    parser.add_argument('--cam1-reactions', required=True,
                        help='Reaktions-JSON für Kamera 1')
    parser.add_argument('--cam1-video', required=False,
                        help='Pfad zur Cam1 Video-Datei (für automatische embedded TC Erkennung)')
    parser.add_argument('--cam2-clip', required=True,
                        help='Clip-Name für Kamera 2')
    parser.add_argument('--cam2-reactions', required=True,
                        help='Reaktions-JSON für Kamera 2')
    parser.add_argument('--cam2-video', required=False,
                        help='Pfad zur Cam2 Video-Datei (für automatische embedded TC Erkennung)')
    parser.add_argument('--cam1-embedded-tc', required=False,
                        help='Embedded TC von Cam1 bei Frame 0 (z.B. 00:32:36:11) - nur wenn --cam1-video nicht verfügbar')
    parser.add_argument('--cam2-embedded-tc', required=False,
                        help='Embedded TC von Cam2 bei Frame 0 (z.B. 10:26:39:13) - nur wenn --cam2-video nicht verfügbar')
    parser.add_argument('--output', '-o', required=True,
                        help='Output EDL')
    parser.add_argument('--config', default='config.ini',
                        help='Config-Datei')
    parser.add_argument('--fps', type=float, default=25.0,
                        help='FPS (default: 25)')
    
    args = parser.parse_args()
    
    print("="*70)
    print("🎬 ADD REACTIONS TO EDL v3.0 - Multi-Pass Architektur")
    print("="*70)
    
    # Lade Config
    config = load_config(args.config)
    
    # Settings
    min_shot_duration = 2.0
    reaction_min_duration = 3.0
    max_shot_duration = 30.0
    min_confidence = 0.86
    cleanup_min_duration = 1.5
    
    if config:
        if config.has_option('General', 'min_shot_duration'):
            min_shot_duration = config.getfloat('General', 'min_shot_duration')
        if config.has_option('General', 'reaction_min_duration'):
            reaction_min_duration = config.getfloat('General', 'reaction_min_duration')
        if config.has_option('General', 'max_shot_duration'):
            max_shot_duration = config.getfloat('General', 'max_shot_duration')
        if config.has_option('General', 'cleanup_min_duration'):
            cleanup_min_duration = config.getfloat('General', 'cleanup_min_duration')
        if config.has_option('Detection', 'min_confidence'):
            min_confidence = config.getfloat('Detection', 'min_confidence')
    
    cutaway_enabled = {
        'nodding': True,
        'laughing': False,
        'head_shake': False,
        'eyebrow_raise': False,
    }
    
    if config and config.has_section('ReactionCutaways'):
        cutaway_enabled['nodding'] = config.getboolean('ReactionCutaways', 'nodding_cutaway', fallback=True)
        cutaway_enabled['laughing'] = config.getboolean('ReactionCutaways', 'laughing_cutaway', fallback=False)
        cutaway_enabled['head_shake'] = config.getboolean('ReactionCutaways', 'headshake_cutaway', fallback=False)
        cutaway_enabled['eyebrow_raise'] = config.getboolean('ReactionCutaways', 'eyebrow_cutaway', fallback=False)
    
    cluster_max_gap_frames = 75
    pre_roll_frames = 0
    if config and config.has_section('CutawayTiming'):
        cluster_max_gap_frames = config.getint('CutawayTiming', 'cluster_max_gap_frames', fallback=75)
        pre_roll_frames = config.getint('CutawayTiming', 'pre_roll_frames', fallback=0)

    settings = {
        'min_shot_duration': min_shot_duration,
        'reaction_min_duration': reaction_min_duration,
        'max_shot_duration': max_shot_duration,
        'min_confidence': min_confidence,
        'cutaway_enabled': cutaway_enabled,
        'cluster_max_gap_frames': cluster_max_gap_frames,
        'pre_roll_frames': pre_roll_frames,
    }
    
    print(f"\n⚙️  Settings:")
    print(f"  Min Shot Duration: {min_shot_duration}s")
    print(f"  Reaction Duration: {reaction_min_duration}s")
    print(f"  Max Shot Duration: {max_shot_duration}s")
    print(f"  Min Confidence: {min_confidence}")
    print(f"  Cleanup Min Duration: {cleanup_min_duration}s")
    enabled_types = [k for k, v in cutaway_enabled.items() if v]
    print(f"  Cutaway Types: {', '.join(enabled_types)}")
    
    # Pass 1: Parse Original-EDL
    original_events = parse_resolve_edl(args.resolve_edl, args.fps)
    
    if not original_events:
        print("✗ Keine Events in EDL gefunden!")
        return 1
    
    # Berechne Referenz-Frames und Timeline-0 Offsets
    print(f"\n  Referenz-Frames:")
    reference_frames, timeline_zero_video_frames = calculate_reference_frames(
        original_events, 
        args.cam1_clip, 
        args.cam2_clip,
        cam1_video_path=args.cam1_video if hasattr(args, 'cam1_video') else None,
        cam2_video_path=args.cam2_video if hasattr(args, 'cam2_video') else None,
        cam1_embedded_tc=args.cam1_embedded_tc,
        cam2_embedded_tc=args.cam2_embedded_tc,
        fps=args.fps
    )
    
    # Sammle Sections mit Video Frame Offsets
    cam1_sections = []
    cam2_sections = []
    
    for event in original_events:
        if event.clip_name == args.cam1_clip:
            # Berechne Video Frame für diesen Event
            video_start = event.source_in_frame - reference_frames[args.cam1_clip]
            cam1_sections.append({
                'timeline_start': event.record_in_frame,
                'timeline_end': event.record_out_frame,
                'video_start': video_start
            })
        elif event.clip_name == args.cam2_clip:
            video_start = event.source_in_frame - reference_frames[args.cam2_clip]
            cam2_sections.append({
                'timeline_start': event.record_in_frame,
                'timeline_end': event.record_out_frame,
                'video_start': video_start
            })
    
    print(f"\n  Sections:")
    print(f"    Cam1 (ON): {len(cam1_sections)} Sections")
    print(f"    Cam2 (ON): {len(cam2_sections)} Sections")
    
    # Lade Reaktionen
    print(f"\n📊 Lade Reaktions-Daten:")
    cam1_reactions, _ = load_reactions(args.cam1_reactions)
    cam2_reactions, _ = load_reactions(args.cam2_reactions)
    print(f"  Cam1: {len(cam1_reactions)} Reaktionen")
    print(f"  Cam2: {len(cam2_reactions)} Reaktionen")
    
    # Pass 2: Cam1 ON → Cam2 Cutaways
    print(f"\n🎬 PASS 2: Cam1 ON → Cam2 Cutaways")
    
    all_events = []
    cam2_cutaways = 0
    
    for section in cam1_sections:
        events = build_events_with_cutaways(
            section['timeline_start'], section['timeline_end'], section['video_start'],
            args.cam1_clip, reference_frames[args.cam1_clip],
            args.cam2_clip, reference_frames[args.cam2_clip],
            timeline_zero_video_frames[args.cam2_clip],
            cam2_reactions,
            settings,
            args.fps
        )
        all_events.extend(events)
        cam2_cutaways += sum(1 for e in events if e.clip_name == args.cam2_clip)
    
    print(f"  ✓ {cam2_cutaways} Cam2-Cutaways eingefügt")
    
    # Pass 3: Cam2 ON → Cam1 Cutaways
    print(f"\n🎬 PASS 3: Cam2 ON → Cam1 Cutaways")
    
    cam1_cutaways = 0
    
    for section in cam2_sections:
        events = build_events_with_cutaways(
            section['timeline_start'], section['timeline_end'], section['video_start'],
            args.cam2_clip, reference_frames[args.cam2_clip],
            args.cam1_clip, reference_frames[args.cam1_clip],
            timeline_zero_video_frames[args.cam1_clip],
            cam1_reactions,
            settings,
            args.fps
        )
        all_events.extend(events)
        cam1_cutaways += sum(1 for e in events if e.clip_name == args.cam1_clip)
    
    print(f"  ✓ {cam1_cutaways} Cam1-Cutaways eingefügt")
    
    # Sortiere Events nach Timeline-Position
    all_events.sort(key=lambda e: e.record_in_frame)
    
    print(f"\n  Gesamt vor Cleanup: {len(all_events)} Events")
    
    # Pass 4: Cleanup
    final_events = cleanup_short_events(all_events, cleanup_min_duration, args.fps)
    
    # Pass 5: Split zu lange Shots
    final_events = split_long_shots(
        final_events,
        max_shot_duration,
        cleanup_min_duration,
        reference_frames,
        timeline_zero_video_frames,
        args.fps
    )
    
    # Schreibe finale EDL
    write_edl(final_events, args.output)
    
    print(f"\n{'='*70}")
    print(f"✓ FERTIG!")
    print(f"{'='*70}")
    print(f"Importiere in Resolve:")
    print(f"  File → Import → Timeline → EDL")
    print(f"  → {args.output}")
    print()
    
    return 0


if __name__ == '__main__':
    exit(main())
