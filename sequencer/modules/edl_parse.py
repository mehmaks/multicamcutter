"""EDL-Parse-Modul — Konvertiert die finale Event-Liste in frame-basierte cut_events."""

from __future__ import annotations

from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import EDLEvent


class EDLParseModule(Module):
    name = "edl_parse"
    description = "Events in frame-basierte cut_events umwandeln"
    category = "io"

    inputs = ["frame_mapping", "sources.cameras"]
    outputs = ["cut_events"]
    optional_inputs = ["events.filtered", "events.split", "events.cleaned",
                       "events.with_cutaways", "events.base"]

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        frame_mapping = ctx.get("frame_mapping")
        cameras = ctx.get("sources.cameras")
        fps = frame_mapping.fps

        # Die letzte verfuegbare Event-Liste nehmen
        events = None
        for key in ["events.filtered", "events.split", "events.cleaned",
                     "events.with_pause_cutaways", "events.with_cutaways", "events.base"]:
            if ctx.has(key):
                events = ctx.get(key)
                print(f"  Quelle: {key} ({len(events)} Events)")
                break

        if events is None:
            raise ValueError("Keine Events im Context gefunden")

        # Clip-Item Lookup
        cam_by_name = {c.name: c for c in cameras}

        # In cut_events konvertieren (frame-basiert, mit Resolve clip_item)
        cut_events = []
        for ev in events:
            ref = frame_mapping.reference_frames.get(ev.clip_name, 0)
            source_in = ev.source_in_frame - ref  # Video-Frame relativ zum Clip-Start
            source_out = ev.source_out_frame - ref

            cam = cam_by_name.get(ev.clip_name)
            cut_events.append({
                'clip': cam.clip_item if cam else None,
                'clip_name': ev.clip_name,
                'source_in': source_in,
                'source_out': source_out,
                'record_in': ev.record_in_frame,
                'record_out': ev.record_out_frame,
                'reason': ev.reason,
            })

        print(f"  {len(cut_events)} cut_events erstellt")
        ctx.set("cut_events", cut_events)
