"""Cleanup-Short-Events-Modul — Entfernt zu kurze Events (PASS 3)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import EDLEvent
from sequencer.frame_utils import frames_to_timecode

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from add_reactions_to_edl import cleanup_short_events as _legacy_cleanup
from add_reactions_to_edl import EDLEvent as LegacyEDLEvent


class CleanupShortEventsModule(Module):
    name = "cleanup_short_events"
    description = "Zu kurze Events entfernen (PASS 3)"
    category = "editing"

    inputs = ["events.with_cutaways"]
    outputs = ["events.cleaned"]
    optional_inputs = ["events.with_pause_cutaways"]

    schema = {
        "expanders": [{
            "key": "cleanup",
            "label": "Cleanup",
            "rows": [{
                "columns": 1,
                "params": [{
                    "name": "cleanup_min_duration", "widget": "number_input",
                    "default": 1.5, "label": "Min. Event-Dauer (s)", "column": 0,
                }],
            }],
        }],
    }

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        # Bevorzugt events.with_pause_cutaways, sonst events.with_cutaways
        if ctx.has("events.with_pause_cutaways"):
            events = ctx.get("events.with_pause_cutaways")
        else:
            events = ctx.get("events.with_cutaways")

        fps = ctx.fps
        min_dur = params.get("cleanup_min_duration", 1.5)

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

        cleaned = _legacy_cleanup(legacy, min_dur, fps)

        result = []
        for ev in cleaned:
            result.append(EDLEvent(
                clip_name=ev.clip_name,
                source_in_frame=ev.source_in_frame,
                source_out_frame=ev.source_out_frame,
                record_in_frame=ev.record_in_frame,
                record_out_frame=ev.record_out_frame,
                fps=ev.fps, reason=ev.reason,
            ))

        removed = len(events) - len(result)
        print(f"  {removed} Events entfernt, {len(result)} verbleibend")
        ctx.set("events.cleaned", result)
