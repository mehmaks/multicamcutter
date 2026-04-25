"""Crossbleed-Gate-Modul — Unterdrueckt Uebersprechen zwischen Mikrofonen."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import AudioData

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from build_base_edl_from_audio import rms_gate, compute_rms_db


class CrossbleedGateModule(Module):
    name = "crossbleed_gate"
    description = "Crossbleed-Filter zwischen Mikrofonen"
    category = "analysis"

    inputs = ["audio.data"]
    outputs = ["audio.gated"]

    schema = {
        "expanders": [{
            "key": "crossbleed_gate",
            "label": "Crossbleed-Filter",
            "rows": [
                {
                    "columns": 3,
                    "params": [
                        {"name": "enabled", "widget": "toggle", "default": False,
                         "label": "Aktiviert", "column": 0},
                        {"name": "gate_floor", "widget": "number_input", "default": -25,
                         "label": "Daempfung (dB)", "expert": True, "column": 1},
                        {"name": "gate_hysteresis", "widget": "number_input", "default": 2.0,
                         "label": "Hysterese (dB)", "expert": True, "column": 2},
                    ],
                },
                {
                    "columns": 3,
                    "params": [
                        {"name": "gate_window", "widget": "number_input", "default": 80,
                         "label": "Fenster (ms)", "expert": True, "column": 0},
                        {"name": "gate_attack", "widget": "number_input", "default": 15,
                         "label": "Attack (ms)", "expert": True, "column": 1},
                        {"name": "gate_release", "widget": "number_input", "default": 80,
                         "label": "Release (ms)", "expert": True, "column": 2},
                    ],
                },
                {
                    "columns": 2,
                    "params": [
                        {"name": "gate_both_threshold", "widget": "number_input", "default": 3.0,
                         "label": "Both-Threshold (dB)", "expert": True, "column": 0},
                        {"name": "gate_use_filtered", "widget": "toggle", "default": False,
                         "label": "Gefilterte WAVs exportieren", "expert": True, "column": 1},
                    ],
                },
            ],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        return not params.get("enabled", False)

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        audio_data = ctx.get("audio.data")
        cam_names = list(audio_data.audio.keys())

        if len(cam_names) < 2:
            print("  Crossbleed-Gate uebersprungen (weniger als 2 Kameras)")
            ctx.set("audio.gated", audio_data)
            return

        if len(cam_names) > 2:
            raise NotImplementedError(
                f"Crossbleed-Gate unterstuetzt aktuell nur 2 Quellen, "
                f"erhalten: {cam_names}. N-Kanal-Gate ist geplant."
            )

        audio1 = audio_data.audio[cam_names[0]]
        audio2 = audio_data.audio[cam_names[1]]
        sr = audio_data.sr

        print(f"  Gate: Fenster={params.get('gate_window', 80)}ms, "
              f"Floor={params.get('gate_floor', -25)}dB, "
              f"Both<{params.get('gate_both_threshold', 3.0)}dB")

        gated1, gated2 = rms_gate(
            audio1, audio2, sr,
            window_ms=params.get("gate_window", 80),
            attack_ms=params.get("gate_attack", 15),
            release_ms=params.get("gate_release", 80),
            floor_db=params.get("gate_floor", -25),
            hysteresis_db=params.get("gate_hysteresis", 2.0),
            both_threshold_db=params.get("gate_both_threshold", 3.0),
        )

        # Post-Gate Normalisierung: nur aktive Fenster fuer Median
        analysis_window = params.get("analysis_window", 0.05)
        rms1 = compute_rms_db(gated1, sr, analysis_window)
        rms2 = compute_rms_db(gated2, sr, analysis_window)

        floor_thresh = params.get("gate_floor", -25) + 5
        active1 = rms1[rms1 > floor_thresh]
        active2 = rms2[rms2 > floor_thresh]
        median1 = float(np.median(active1)) if len(active1) > 0 else float(np.median(rms1))
        median2 = float(np.median(active2)) if len(active2) > 0 else float(np.median(rms2))

        offset_db = (median1 - median2) / 2.0
        if abs(offset_db) > 0.1:
            gain1 = 10 ** (-offset_db / 20.0)
            gain2 = 10 ** (+offset_db / 20.0)
            gated1 = (gated1 * gain1).astype(gated1.dtype)
            gated2 = (gated2 * gain2).astype(gated2.dtype)
            print(f"  Post-Gate Normalisierung: {cam_names[0]} {-offset_db:+.1f} dB, "
                  f"{cam_names[1]} {+offset_db:+.1f} dB")

        ctx.set("audio.gated", AudioData(
            audio={cam_names[0]: gated1, cam_names[1]: gated2},
            sr=sr,
        ))
