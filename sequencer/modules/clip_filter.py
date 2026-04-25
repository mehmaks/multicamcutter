"""CLIP-Filter-Modul — Validiert Cutaways per CLIP Vision Model (PASS 5)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import EDLEvent
from sequencer.frame_utils import frames_to_timecode

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from add_reactions_to_edl import clip_filter_cutaways as _legacy_filter
from add_reactions_to_edl import EDLEvent as LegacyEDLEvent


class CLIPFilterModule(Module):
    name = "clip_filter"
    description = "CLIP-basierte Cutaway-Validierung (PASS 5)"
    category = "analysis"

    inputs = ["events.split", "cameras_config", "frame_mapping"]
    outputs = ["events.filtered"]

    schema = {
        "expanders": [{
            "key": "clip_filter",
            "label": "CLIP-Filter",
            "rows": [{
                "columns": 2,
                "params": [
                    {"name": "enabled", "widget": "toggle", "default": False,
                     "label": "Aktiviert", "column": 0},
                    {"name": "ignore_threshold", "widget": "number_input", "default": 0.5,
                     "label": "Ignore-Schwelle", "expert": True, "column": 1},
                ],
            }],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        return not params.get("enabled", False)

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        events = ctx.get("events.split")
        cameras_config = ctx.get("cameras_config")
        frame_mapping = ctx.get("frame_mapping")
        fps = frame_mapping.fps

        clip_config = {
            'ignore_threshold': params.get("ignore_threshold", 0.5),
            'shift_step_s': params.get("shift_step_s", 2.0),
            'max_attempts': params.get("max_attempts", 5),
            'prompts_path': params.get("prompts_path", ""),
        }

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

        filtered = _legacy_filter(
            legacy, cameras_config,
            frame_mapping.reference_frames,
            frame_mapping.timeline_zero_video_frames,
            clip_config, fps,
        )

        result = []
        for ev in filtered:
            result.append(EDLEvent(
                clip_name=ev.clip_name,
                source_in_frame=ev.source_in_frame,
                source_out_frame=ev.source_out_frame,
                record_in_frame=ev.record_in_frame,
                record_out_frame=ev.record_out_frame,
                fps=ev.fps, reason=ev.reason,
            ))

        ctx.set("events.filtered", result)
