"""RMS-Diarization-Modul — Sprechererkennung aus RMS-Pegelvergleich."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import DiarizationResult

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from build_base_edl_from_audio import rms_diarize


class RMSDiarizeModule(Module):
    name = "rms_diarize"
    description = "Sprechererkennung (RMS-Pegelvergleich)"
    category = "analysis"

    inputs = ["audio.data"]
    outputs = ["diarization.segments"]
    optional_inputs = ["audio.gated"]

    schema = {
        "expanders": [{
            "key": "rms_diarize",
            "label": "Sprecher-Erkennung",
            "rows": [
                {
                    "columns": 2,
                    "params": [
                        {"name": "threshold_db", "widget": "number_input", "default": 6.0,
                         "label": "Schwelle (dB)", "column": 0,
                         "help": "Mindest-Pegeldifferenz fuer Sprecherwechsel"},
                        {"name": "min_edit_duration", "widget": "number_input", "default": 1.0,
                         "label": "Min. Segment (s)", "column": 1,
                         "help": "Kuerzestes erlaubtes Sprechersegment"},
                    ],
                },
                {
                    "columns": 2,
                    "params": [
                        {"name": "change_delay", "widget": "number_input", "default": 0.3,
                         "label": "Wechsel-Verzoegerung (s)", "expert": True, "column": 0},
                        {"name": "analysis_window", "widget": "number_input", "default": 0.05,
                         "label": "Analyse-Fenster (s)", "expert": True, "column": 1},
                    ],
                },
                {
                    "columns": 1,
                    "params": [
                        {"name": "silence_gate_db", "widget": "number_input", "default": -55.0,
                         "label": "Stille-Gate (dB)", "expert": True, "column": 0,
                         "help": "Unter diesem Pegel: kein Sprecher zugewiesen"},
                    ],
                },
            ],
        }],
    }

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        # Bevorzugt gated Audio, sonst Original
        if ctx.has("audio.gated"):
            audio_data = ctx.get("audio.gated")
        else:
            audio_data = ctx.get("audio.data")

        cam_names = list(audio_data.audio.keys())
        if len(cam_names) < 2:
            raise ValueError("RMS-Diarization braucht mindestens 2 Audio-Quellen")
        if len(cam_names) > 2:
            raise NotImplementedError(
                f"RMS-Diarization unterstuetzt aktuell nur 2 Quellen, "
                f"erhalten: {cam_names}. N-Way-Diarization ist geplant."
            )

        audio1 = audio_data.audio[cam_names[0]]
        audio2 = audio_data.audio[cam_names[1]]
        sr = audio_data.sr

        window_s = params.get("analysis_window", 0.05)
        threshold_db = params.get("threshold_db", 6.0)
        change_delay = params.get("change_delay", 0.3)
        min_edit = params.get("min_edit_duration", 1.0)
        silence_gate = params.get("silence_gate_db", -55.0)

        print(f"  Schwelle={threshold_db:.1f} dB, Min-Edit={min_edit:.1f}s, "
              f"Stille-Gate={silence_gate:.0f} dB")

        segments = rms_diarize(
            audio1, audio2, sr,
            window_s, threshold_db,
            change_delay, min_edit,
            silence_gate_db=silence_gate,
        )

        print(f"  {len(segments)} Segmente erkannt")

        ctx.set("diarization.segments", DiarizationResult(segments=segments))
