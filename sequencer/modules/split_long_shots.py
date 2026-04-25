"""Split-Long-Shots-Modul — Splittet zu lange Events in der Mitte (PASS 4)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import EDLEvent
from sequencer.frame_utils import frames_to_timecode

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from add_reactions_to_edl import split_long_shots as _legacy_split
from add_reactions_to_edl import EDLEvent as LegacyEDLEvent


class SplitLongShotsModule(Module):
    name = "split_long_shots"
    description = "Zu lange Shots in der Mitte splitten (PASS 4)"
    category = "editing"

    inputs = ["events.cleaned", "frame_mapping", "cameras_config"]
    outputs = ["events.split"]

    schema = {
        "expanders": [{
            "key": "split",
            "label": "Lange Shots",
            "rows": [{
                "columns": 2,
                "params": [
                    {"name": "max_shot_duration", "widget": "number_input",
                     "default": 30.0, "label": "Max. Shot-Dauer (s)", "column": 0},
                    {"name": "cutaway_duration", "widget": "number_input",
                     "default": 1.5, "label": "Split-Cutaway-Dauer (s)", "expert": True,
                     "column": 1},
                ],
            }],
        }],
    }

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        events = ctx.get("events.cleaned")
        frame_mapping = ctx.get("frame_mapping")
        cameras_config = ctx.get("cameras_config")
        fps = frame_mapping.fps

        max_dur = params.get("max_shot_duration", 30.0)
        cutaway_dur = params.get("cutaway_duration", 1.5)

        all_cam_names = [c['name'] for c in cameras_config]
        cam_types_dict = {c['name']: c.get('type', 'close') for c in cameras_config}

        # Zu Legacy konvertieren
        legacy = []
        for ev in events:
            legacy.append(LegacyEDLEvent(
                event_num=0, clip_name=ev.clip_name,
                source_in=frames_to_timecode(ev.source_in_frame, fps),
                source_out=frames_to_timecode(ev.source_out_frame, fps),
                record_in=frames_to_timecode(ev.record_in_frame, fps),
                record_out=frames_to_timecode(ev.record_out_frame, fps),
                fps=fps, reason=ev.reason,
            ))

        split = _legacy_split(
            legacy, max_dur, cutaway_dur,
            frame_mapping.reference_frames,
            frame_mapping.timeline_zero_video_frames,
            all_cam_names, fps,
            cam_types_dict=cam_types_dict,
        )

        result = []
        for ev in split:
            result.append(EDLEvent(
                clip_name=ev.clip_name,
                source_in_frame=ev.source_in_frame,
                source_out_frame=ev.source_out_frame,
                record_in_frame=ev.record_in_frame,
                record_out_frame=ev.record_out_frame,
                fps=ev.fps, reason=ev.reason,
            ))

        added = len(result) - len(events)
        print(f"  {added} Splits eingefuegt, {len(result)} Events total")
        ctx.set("events.split", result)
