"""Cutaway-Insertion-Modul — Fuegt Reaktions-Cutaways in die Event-Liste ein."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.module import Module

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from add_reactions_to_edl import build_events_with_cutaways, EDLEvent as LegacyEDLEvent
from sequencer.frame_utils import frames_to_timecode
from sequencer.types import EDLEvent


def _to_legacy_events(events: List[EDLEvent]) -> List[LegacyEDLEvent]:
    """Konvertiert Sequencer-EDLEvents in Legacy-Format fuer bestehende Funktionen."""
    legacy = []
    for ev in events:
        legacy.append(LegacyEDLEvent(
            event_num=0, clip_name=ev.clip_name,
            source_in=frames_to_timecode(ev.source_in_frame, ev.fps),
            source_out=frames_to_timecode(ev.source_out_frame, ev.fps),
            record_in=frames_to_timecode(ev.record_in_frame, ev.fps),
            record_out=frames_to_timecode(ev.record_out_frame, ev.fps),
            fps=ev.fps, reason=ev.reason,
        ))
    return legacy


def _from_legacy_events(events: List[LegacyEDLEvent]) -> List[EDLEvent]:
    """Konvertiert Legacy-EDLEvents zurueck in Sequencer-Format."""
    result = []
    for ev in events:
        result.append(EDLEvent(
            clip_name=ev.clip_name,
            source_in_frame=ev.source_in_frame,
            source_out_frame=ev.source_out_frame,
            record_in_frame=ev.record_in_frame,
            record_out_frame=ev.record_out_frame,
            fps=ev.fps,
            reason=ev.reason,
        ))
    return result


class CutawayInsertionModule(Module):
    name = "cutaway_insertion"
    description = "Reaktions-Cutaways in Schnittliste einfuegen (PASS 2)"
    category = "editing"

    inputs = ["events.base", "cameras_config", "frame_mapping"]
    outputs = ["events.with_cutaways"]

    schema = {
        "expanders": [{
            "key": "cutaways",
            "label": "Cutaway-Einstellungen",
            "rows": [
                {
                    "columns": 3,
                    "params": [
                        {"name": "min_shot_duration", "widget": "number_input", "default": 2.0,
                         "label": "Min. Shot (s)", "column": 0},
                        {"name": "reaction_min_duration", "widget": "number_input", "default": 3.0,
                         "label": "Cutaway-Dauer (s)", "column": 1},
                        {"name": "max_shot_duration", "widget": "number_input", "default": 30.0,
                         "label": "Max. Shot (s)", "column": 2},
                    ],
                },
                {
                    "columns": 2,
                    "params": [
                        {"name": "min_confidence", "widget": "number_input", "default": 0.86,
                         "label": "Min. Confidence", "expert": True, "column": 0},
                        {"name": "cutaway_randomness", "widget": "number_input", "default": 0.0,
                         "label": "Zufallsfaktor", "expert": True, "column": 1},
                    ],
                },
            ],
        }],
    }

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        events = ctx.get("events.base")
        cameras_config = ctx.get("cameras_config")
        frame_mapping = ctx.get("frame_mapping")
        fps = frame_mapping.fps

        ref_frames = frame_mapping.reference_frames
        tzvf = frame_mapping.timeline_zero_video_frames

        settings = {
            'min_shot_duration': params.get("min_shot_duration", 2.0),
            'reaction_min_duration': params.get("reaction_min_duration", 3.0),
            'max_shot_duration': params.get("max_shot_duration", 30.0),
            'min_confidence': params.get("min_confidence", 0.86),
            'cutaway_randomness': params.get("cutaway_randomness", 0.0),
            'cutaway_enabled': params.get("cutaway_enabled", {
                'nodding': True, 'speaking_reaction': True,
            }),
            'cluster_max_gap_frames': params.get("cluster_max_gap_frames", 75),
            'pre_roll_frames': params.get("pre_roll_frames", 0),
            'speaking_min_confidence': params.get("speaking_min_confidence", 0.5),
        }

        # Sections pro Kamera sammeln
        cam_sections: Dict[str, List[Dict]] = {}
        for ev in events:
            name = ev.clip_name
            if name not in cam_sections:
                cam_sections[name] = []
            if name in ref_frames:
                video_start = ev.source_in_frame - ref_frames[name]
                cam_sections[name].append({
                    'timeline_start': ev.record_in_frame,
                    'timeline_end': ev.record_out_frame,
                    'video_start': video_start,
                })

        # cam_dicts aufbauen
        cam_dicts = {}
        for cam_cfg in cameras_config:
            name = cam_cfg['name']
            if name in ref_frames:
                cam_dicts[name] = {
                    'name': name,
                    'type': cam_cfg.get('type', 'close'),
                    'reference_frame': ref_frames[name],
                    'timeline_zero_video': tzvf[name],
                    'reactions': cam_cfg.get('reactions', []),
                }

        # PASS 2: Cutaways einfuegen
        all_events = []
        for on_name, sections in cam_sections.items():
            if on_name not in ref_frames:
                continue
            cutaway_cams = [cam_dicts[n] for n in cam_dicts if n != on_name]
            if not cutaway_cams:
                for sec in sections:
                    vi = sec['video_start']
                    vo = vi + (sec['timeline_end'] - sec['timeline_start'])
                    all_events.append(LegacyEDLEvent(
                        event_num=0, clip_name=on_name,
                        source_in=frames_to_timecode(ref_frames[on_name] + vi, fps),
                        source_out=frames_to_timecode(ref_frames[on_name] + vo, fps),
                        record_in=frames_to_timecode(sec['timeline_start'], fps),
                        record_out=frames_to_timecode(sec['timeline_end'], fps),
                        fps=fps, reason="speaker",
                    ))
                continue

            for sec in sections:
                evs = build_events_with_cutaways(
                    sec['timeline_start'], sec['timeline_end'], sec['video_start'],
                    on_name, ref_frames[on_name],
                    cutaway_cams, settings, fps,
                )
                all_events.extend(evs)

        all_events.sort(key=lambda e: e.record_in_frame)
        result = _from_legacy_events(all_events)

        cutaway_count = sum(1 for e in result if e.reason != "speaker")
        print(f"  {len(result)} Events ({cutaway_count} Cutaways)")
        ctx.set("events.with_cutaways", result)
