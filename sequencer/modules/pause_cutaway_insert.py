"""Pause-Cutaway-Insert-Modul — Fuegt Stille-Cutaways in die Event-Liste ein."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import EDLEvent

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from add_reactions_to_edl import insert_pause_cutaways as _legacy_insert
from add_reactions_to_edl import EDLEvent as LegacyEDLEvent
from sequencer.frame_utils import frames_to_timecode


class PauseCutawayInsertModule(Module):
    name = "pause_cutaway_insert"
    description = "Stille-Cutaways in Schnittliste einfuegen (PASS 2b)"
    category = "editing"

    inputs = ["events.with_cutaways", "pauses.cutaway_candidates",
              "cameras_config", "frame_mapping"]
    outputs = ["events.with_pause_cutaways"]

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        if not ctx.has("pauses.cutaway_candidates"):
            return True
        candidates = ctx.get("pauses.cutaway_candidates")
        return len(candidates) == 0

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        events = ctx.get("events.with_cutaways")
        candidates = ctx.get("pauses.cutaway_candidates")
        cameras_config = ctx.get("cameras_config")
        frame_mapping = ctx.get("frame_mapping")
        fps = frame_mapping.fps

        # Zu Legacy konvertieren
        legacy_events = []
        for ev in events:
            legacy_events.append(LegacyEDLEvent(
                event_num=0, clip_name=ev.clip_name,
                source_in=frames_to_timecode(ev.source_in_frame, fps),
                source_out=frames_to_timecode(ev.source_out_frame, fps),
                record_in=frames_to_timecode(ev.record_in_frame, fps),
                record_out=frames_to_timecode(ev.record_out_frame, fps),
                fps=fps, reason=ev.reason,
            ))

        pause_data = {'fps': fps, 'pauses': candidates}
        min_shot_frames = int(params.get("min_shot_duration", 2.0) * fps)

        result_legacy = _legacy_insert(
            legacy_events, pause_data, cameras_config,
            frame_mapping.reference_frames,
            frame_mapping.timeline_zero_video_frames,
            min_shot_frames, fps,
        )

        # Zurueck konvertieren
        result = []
        for ev in result_legacy:
            result.append(EDLEvent(
                clip_name=ev.clip_name,
                source_in_frame=ev.source_in_frame,
                source_out_frame=ev.source_out_frame,
                record_in_frame=ev.record_in_frame,
                record_out_frame=ev.record_out_frame,
                fps=ev.fps, reason=ev.reason,
            ))

        pause_count = sum(1 for e in result if e.reason == "pause_cutaway") - \
                      sum(1 for e in events if e.reason == "pause_cutaway")
        print(f"  {pause_count} Pause-Cutaways eingefuegt")
        ctx.set("events.with_pause_cutaways", result)
