"""Pause-Detect-Modul — Erkennt Sprechpausen an Diarization-Grenzen."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import PauseData

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from pause_trim_edl import detect_pauses


class PauseDetectModule(Module):
    name = "pause_detect"
    description = "Sprechpausen an Segmentgrenzen erkennen"
    category = "analysis"

    inputs = ["events.base", "audio.data"]
    outputs = ["pauses.detected"]

    schema = {
        "expanders": [{
            "key": "pause_detect",
            "label": "Pausen-Erkennung",
            "rows": [
                {
                    "columns": 1,
                    "params": [
                        {"name": "enabled", "widget": "toggle", "default": True,
                         "label": "Pausen-Trimming", "column": 0},
                    ],
                },
                {
                    "columns": 3,
                    "params": [
                        {"name": "silence_db", "widget": "number_input", "default": -40.0,
                         "label": "Stille-Schwelle (dB)", "column": 0},
                        {"name": "search_radius_s", "widget": "number_input", "default": 3.0,
                         "label": "Suchradius (s)", "expert": True, "column": 1},
                        {"name": "min_pause_s", "widget": "number_input", "default": 0.3,
                         "label": "Min. Pause (s)", "expert": True, "column": 2},
                    ],
                },
            ],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        return not params.get("enabled", True)

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        events = ctx.get("events.base")
        audio_data = ctx.get("audio.data")

        cam_names = list(audio_data.audio.keys())
        if len(cam_names) > 2:
            raise NotImplementedError(
                f"Pause-Detect unterstuetzt aktuell nur 2 Quellen, "
                f"erhalten: {cam_names}. N-Kanal-Analyse ist geplant."
            )
        audio1 = audio_data.audio[cam_names[0]]
        audio2 = audio_data.audio[cam_names[1]]
        sr = audio_data.sr
        fps = ctx.fps

        # detect_pauses erwartet Event-Dicts mit record_out als TC
        # Konvertierung von EDLEvent-Objekten falls noetig
        event_dicts = []
        for ev in events:
            if isinstance(ev, dict):
                event_dicts.append(ev)
            else:
                from sequencer.frame_utils import frames_to_timecode
                event_dicts.append({
                    "clip_name": ev.clip_name,
                    "record_out": frames_to_timecode(ev.record_out_frame, fps),
                })

        wav_edl_frame = params.get("wav_edl_frame", 0)

        pauses = detect_pauses(
            event_dicts, audio1, audio2, sr,
            wav_edl_frame=wav_edl_frame,
            fps=fps,
            silence_db=params.get("silence_db", -40.0),
            search_radius_s=params.get("search_radius_s", 3.0),
            min_pause_s=params.get("min_pause_s", 0.3),
        )

        print(f"  {len(pauses)} Pausen erkannt")

        ctx.set("pauses.detected", PauseData(pauses=pauses))
