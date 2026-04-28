"""Speaking-Reactions-Modul — Erkennt Sprech-Reaktionen auf dem Off-Mic."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import ReactionData

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from build_base_edl_from_audio import (
    detect_on_speaker_pauses,
    detect_speaking_reactions,
)


class SpeakingReactionsModule(Module):
    name = "speaking_reactions"
    description = "Sprech-Reaktionen erkennen (Off-Mic Burst-Detection)"
    category = "analysis"

    inputs = ["audio.data", "diarization.segments", "frame_mapping"]
    outputs = ["reactions.speaking"]
    optional_inputs = ["audio.gated"]

    schema = {
        "expanders": [{
            "key": "speaking_reactions",
            "label": "Sprech-Reaktionen",
            "rows": [
                {
                    "columns": 1,
                    "params": [
                        {"name": "enabled", "widget": "toggle", "default": True,
                         "label": "Aktiviert", "column": 0},
                    ],
                },
                {
                    "columns": 3,
                    "params": [
                        {"name": "rise_db", "widget": "number_input", "default": 6.0,
                         "label": "Anstieg (dB)", "expert": True, "column": 0},
                        {"name": "min_duration", "widget": "number_input", "default": 0.20,
                         "label": "Min. Dauer (s)", "expert": True, "column": 1},
                        {"name": "max_duration", "widget": "number_input", "default": 2.5,
                         "label": "Max. Dauer (s)", "expert": True, "column": 2},
                    ],
                },
                {
                    "columns": 3,
                    "params": [
                        {"name": "attack_window", "widget": "number_input", "default": 0.2,
                         "label": "Attack (s)", "expert": True, "column": 0},
                        {"name": "release_window", "widget": "number_input", "default": 20.0,
                         "label": "Release (s)", "expert": True, "column": 1},
                        {"name": "warmup", "widget": "number_input", "default": 3.0,
                         "label": "Warmup (s)", "expert": True, "column": 2},
                    ],
                },
            ],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        return not params.get("enabled", True)

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        # Original-Audio fuer Baseline-Freeze-Pausen
        audio_data = ctx.get("audio.data")
        diarization = ctx.get("diarization.segments")
        frame_mapping = ctx.get("frame_mapping")

        cam_names = list(audio_data.audio.keys())
        if len(cam_names) > 2:
            raise NotImplementedError(
                f"Speaking-Reactions unterstuetzt aktuell nur 2 Quellen, "
                f"erhalten: {cam_names}. N-Kanal-Analyse ist geplant."
            )
        audio1 = audio_data.audio[cam_names[0]]
        audio2 = audio_data.audio[cam_names[1]]
        sr = audio_data.sr
        fps = frame_mapping.fps

        segments = diarization.segments

        # Analyse-Audio (gated wenn vorhanden, sonst Original)
        if ctx.has("audio.gated"):
            analysis = ctx.get("audio.gated")
            a1_analysis = analysis.audio[cam_names[0]]
            a2_analysis = analysis.audio[cam_names[1]]
        else:
            a1_analysis = audio1
            a2_analysis = audio2

        # Pausen erkennen (fuer Baseline-Freeze)
        on_pauses = detect_on_speaker_pauses(
            audio1, audio2, sr, segments,
        )

        # Timeline-Koordinaten
        tzvf = frame_mapping.timeline_zero_video_frames
        cam1_tzvf = tzvf.get(cam_names[0], 0)
        cam2_tzvf = tzvf.get(cam_names[1], 0)

        # wav_edl_frame: Offset des Audio-Starts im EDL-Koordinatensystem
        # Im aktuellen Code aus dem CLI-Argument, hier aus dem Sync-Offset ableitbar
        wav_edl_frame = params.get("wav_edl_frame", 0)

        cam1_reactions, cam2_reactions = detect_speaking_reactions(
            a1_analysis, a2_analysis, sr, segments,
            fps=fps,
            wav_edl_frame=wav_edl_frame,
            cam1_timeline_zero_video=cam1_tzvf,
            cam2_timeline_zero_video=cam2_tzvf,
            window_s=params.get("analysis_window", 0.05),
            rise_db=params.get("rise_db", 6.0),
            min_duration_s=params.get("min_duration", 0.20),
            max_duration_s=params.get("max_duration", 2.5),
            attack_window_s=params.get("attack_window", 0.2),
            release_window_s=params.get("release_window", 20.0),
            warmup_s=params.get("warmup", 3.0),
            on_pauses=on_pauses,
        )

        print(f"  {cam_names[0]}: {len(cam1_reactions)} Reaktionen")
        print(f"  {cam_names[1]}: {len(cam2_reactions)} Reaktionen")

        ctx.set("reactions.speaking", {
            cam_names[0]: ReactionData(
                cam_name=cam_names[0], reactions=cam1_reactions, fps=fps,
            ),
            cam_names[1]: ReactionData(
                cam_name=cam_names[1], reactions=cam2_reactions, fps=fps,
            ),
        })
