"""Simultaneous-Speech-Modul — Erkennt gleichzeitiges Sprechen."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from build_base_edl_from_audio import detect_simultaneous_speech


class SimultaneousSpeechModule(Module):
    name = "simultaneous_speech"
    description = "Gleichzeitiges Sprechen erkennen (fuer Totale-Kamera)"
    category = "analysis"

    inputs = ["audio.data"]
    outputs = ["simultaneous_speech"]
    optional_inputs = ["audio.gated"]

    schema = {
        "expanders": [{
            "key": "simultaneous_speech",
            "label": "Simultansprechen",
            "rows": [{
                "columns": 2,
                "params": [
                    {"name": "simul_min_duration", "widget": "number_input", "default": 3.0,
                     "label": "Min. Dauer (s)", "column": 0},
                    {"name": "threshold_db", "widget": "number_input", "default": 6.0,
                     "label": "Schwelle (dB)", "expert": True, "column": 1},
                ],
            }],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        return not params.get("enabled", False)

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        if ctx.has("audio.gated"):
            audio_data = ctx.get("audio.gated")
        else:
            audio_data = ctx.get("audio.data")

        cam_names = list(audio_data.audio.keys())
        audio1 = audio_data.audio[cam_names[0]]
        audio2 = audio_data.audio[cam_names[1]]
        sr = audio_data.sr

        segments = detect_simultaneous_speech(
            audio1, audio2, sr,
            window_s=params.get("analysis_window", 0.05),
            threshold_db=params.get("threshold_db", 6.0),
            min_duration_s=params.get("simul_min_duration", 3.0),
        )

        print(f"  {len(segments)} Simultansprechen-Segmente erkannt")
        ctx.set("simultaneous_speech", segments)
