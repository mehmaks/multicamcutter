"""Audio-Load-Modul — Lädt und normalisiert Audio pro Kamera."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import AudioData

# Importpfad für bestehende Funktionen
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from build_base_edl_from_audio import load_audio, combine_audios, compute_rms_db


class AudioLoadModule(Module):
    name = "audio_load"
    description = "Audio laden und Pegel normalisieren"
    category = "analysis"

    inputs = ["sources.cameras", "sources.mics"]
    outputs = ["audio.data"]
    optional_inputs = ["sources.cam_mic_map"]

    schema = {
        "expanders": [{
            "key": "audio_load",
            "label": "Audio-Einstellungen",
            "rows": [{
                "columns": 1,
                "params": [{
                    "name": "analysis_window",
                    "widget": "number_input",
                    "default": 0.05,
                    "label": "Analyse-Fenster (s)",
                    "help": "RMS-Fenstergroesse fuer Pegelanalyse",
                    "expert": True,
                    "column": 0,
                }],
            }],
        }],
    }

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        cameras = ctx.get("sources.cameras")
        mics = ctx.get("sources.mics")
        window_s = params.get("analysis_window", 0.05)

        # Mic-Zuordnung: cam_mic_map[cam_idx] = [mic_idx, ...]
        if ctx.has("sources.cam_mic_map"):
            cam_mic_map = ctx.get("sources.cam_mic_map")
        else:
            # Default: CAM1→MIC2, CAM2→MIC1 (Kreuzzuordnung wie im aktuellen Code)
            cam_mic_map = [[1], [0]] if len(mics) >= 2 else [[0], [0]]

        # Audio pro Kamera laden
        audio_dict = {}
        sr = None

        for cam_idx, cam in enumerate(cameras):
            mic_indices = cam_mic_map[cam_idx] if cam_idx < len(cam_mic_map) else [0]
            mic_paths = [mics[i].path for i in mic_indices if i < len(mics)]

            if not mic_paths:
                raise ValueError(f"Keine Mics fuer {cam.name} zugeordnet")

            audio, sample_rate = combine_audios(mic_paths)
            audio_dict[cam.name] = audio

            if sr is None:
                sr = sample_rate
            elif sr != sample_rate:
                raise ValueError(f"Sample-Rates unterschiedlich: {sr} vs {sample_rate}")

            mic_names = [Path(p).name for p in mic_paths]
            print(f"  {cam.name} ({len(mic_paths)} MIC(s)): {mic_names}")

        # Laengen angleichen
        min_len = min(len(a) for a in audio_dict.values())
        for key in audio_dict:
            audio_dict[key] = audio_dict[key][:min_len]

        print(f"  Laenge: {min_len / sr / 60:.1f} min")

        # Pegel-Normalisierung: Median-dB ausgleichen
        cam_names = list(audio_dict.keys())
        if len(cam_names) > 2:
            raise NotImplementedError(
                f"Pegel-Normalisierung unterstuetzt aktuell nur 2 Quellen, "
                f"erhalten: {cam_names}. Globale Normalisierung ist geplant."
            )
        if len(cam_names) >= 2:
            rms1 = compute_rms_db(audio_dict[cam_names[0]], sr, window_s)
            rms2 = compute_rms_db(audio_dict[cam_names[1]], sr, window_s)
            median1 = float(np.median(rms1))
            median2 = float(np.median(rms2))
            offset_db = (median1 - median2) / 2.0

            if abs(offset_db) > 0.1:
                gain1 = 10 ** (-offset_db / 20.0)
                gain2 = 10 ** (+offset_db / 20.0)
                audio_dict[cam_names[0]] = (audio_dict[cam_names[0]] * gain1).astype(np.float32)
                audio_dict[cam_names[1]] = (audio_dict[cam_names[1]] * gain2).astype(np.float32)
                print(f"  Pegel-Normalisierung: {cam_names[0]} {-offset_db:+.1f} dB, "
                      f"{cam_names[1]} {+offset_db:+.1f} dB")
            else:
                print(f"  Pegel-Check: {median1:.1f} dB / {median2:.1f} dB (kein Ausgleich noetig)")

        ctx.set("audio.data", AudioData(audio=audio_dict, sr=sr))
