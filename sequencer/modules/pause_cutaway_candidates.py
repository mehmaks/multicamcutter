"""Pause-Cutaway-Candidates-Modul — Findet Stille-Regionen fuer Cutaways."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

from sequencer.context import PipelineContext
from sequencer.module import Module

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from build_base_edl_from_audio import compute_rms_db


class PauseCutawayCandidatesModule(Module):
    name = "pause_cutaway_candidates"
    description = "Stille-Pausen als Cutaway-Kandidaten erkennen"
    category = "analysis"

    inputs = ["audio.data", "diarization.segments"]
    outputs = ["pauses.cutaway_candidates"]
    optional_inputs = ["audio.gated"]

    schema = {
        "expanders": [{
            "key": "pause_cutaway",
            "label": "Stille-Cutaways",
            "rows": [{
                "columns": 2,
                "params": [
                    {"name": "enabled", "widget": "toggle", "default": True,
                     "label": "Aktiviert", "column": 0},
                    {"name": "min_pause", "widget": "number_input", "default": 2.0,
                     "label": "Min. Pausendauer (s)", "column": 1},
                ],
            }],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        return not params.get("enabled", True)

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        # Gated Audio bevorzugen (bessere Stille-Erkennung)
        if ctx.has("audio.gated"):
            audio_data = ctx.get("audio.gated")
        else:
            audio_data = ctx.get("audio.data")

        diarization = ctx.get("diarization.segments")
        segments = diarization.segments

        cam_names = list(audio_data.audio.keys())
        audio1 = audio_data.audio[cam_names[0]]
        audio2 = audio_data.audio[cam_names[1]]
        sr = audio_data.sr
        fps = ctx.fps
        wav_edl_frame = params.get("wav_edl_frame", 0)

        # Gegenseitige Stille: beide Mics unter -50 dB
        window_s = 0.02
        cutaway_silence_db = -50.0
        min_pause_s = params.get("min_pause", 2.0)

        db1 = compute_rms_db(audio1, sr, window_s)
        db2 = compute_rms_db(audio2, sr, window_s)
        n = min(len(db1), len(db2))
        db1, db2 = db1[:n], db2[:n]
        both_silent = (db1 < cutaway_silence_db) & (db2 < cutaway_silence_db)

        # Zusammenhaengende Stille-Regionen
        min_wins = max(1, int(min_pause_s / window_s))
        mutual_pauses = []
        in_pause = False
        ps = 0
        for i in range(n):
            if both_silent[i] and not in_pause:
                ps = i
                in_pause = True
            elif not both_silent[i] and in_pause:
                if i - ps >= min_wins:
                    mutual_pauses.append((ps * window_s, i * window_s))
                in_pause = False
        if in_pause and n - ps >= min_wins:
            mutual_pauses.append((ps * window_s, n * window_s))

        # Sprecher vor Pause bestimmen
        pause_list = []
        for ps_s, pe_s in mutual_pauses:
            spk = None
            for seg in segments:
                if seg['end_s'] >= ps_s - 0.5 and seg['start_s'] < ps_s:
                    spk = seg['speaker']
            if spk not in cam_names:
                continue
            sf = round(ps_s * fps) + wav_edl_frame
            ef = round(pe_s * fps) + wav_edl_frame
            if ef > sf:
                pause_list.append({
                    'start_frame': sf,
                    'end_frame': ef,
                    'speaker': spk,
                })

        pause_list.sort(key=lambda p: p['start_frame'])
        print(f"  {len(pause_list)} Pause-Cutaway-Kandidaten")
        ctx.set("pauses.cutaway_candidates", pause_list)
