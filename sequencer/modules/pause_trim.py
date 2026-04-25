"""Pause-Trim-Modul — Kuerzt ueberlange Pausen in den finalen cut_events."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from pause_trim_edl import apply_pauses_to_cut_events


class PauseTrimModule(Module):
    name = "pause_trim"
    description = "Ueberlange Pausen kuerzen und Audio-Keeps berechnen"
    category = "editing"

    inputs = ["cut_events", "pauses.detected"]
    outputs = ["audio_keeps"]

    schema = {
        "expanders": [{
            "key": "pause_trim",
            "label": "Pausen-Trimming",
            "rows": [{
                "columns": 2,
                "params": [
                    {"name": "max_pause_s", "widget": "number_input", "default": 1.0,
                     "label": "Max. Pausendauer (s)", "column": 0},
                    {"name": "cut_mode", "widget": "selectbox",
                     "options": ["middle", "l-cut", "j-cut"],
                     "default": "middle", "label": "Schnittmodus", "column": 1},
                ],
            }],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        if not ctx.has("pauses.detected"):
            return True
        pause_data = ctx.get("pauses.detected")
        return len(pause_data.pauses) == 0

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        cut_events = ctx.get("cut_events")
        pause_data = ctx.get("pauses.detected")
        fps = ctx.fps

        modified_events, audio_keeps = apply_pauses_to_cut_events(
            cut_events, pause_data.pauses, fps,
            max_pause_s=params.get("max_pause_s", 1.0),
            cut_mode=params.get("cut_mode", "middle"),
        )

        # cut_events in-place aktualisieren
        ctx.set("cut_events", modified_events)
        ctx.set("audio_keeps", audio_keeps)

        print(f"  {len(audio_keeps)} Audio-Keep-Regionen")
