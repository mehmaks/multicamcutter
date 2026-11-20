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
from build_base_edl_from_audio import compute_rms_db


# Aus build_base_edl_from_audio.py hierher verschoben (20.11.): der MultiCamCutter
# nutzt das Gate nicht mehr (ersetzt durch die Analysespur), nur noch der Sequencer.
def rms_gate(audio1: np.ndarray, audio2: np.ndarray, sr: int,
             window_ms: float = 80, attack_ms: float = 15, release_ms: float = 80,
             floor_db: float = -25, hysteresis_db: float = 2.0,
             both_threshold_db: float = 3.0):
    """
    RMS-gesteuerter Crossbleed-Gate: Pro Fenster wird das lautere Mic
    als aktiv betrachtet, das leisere wird stark gedaempft.
    Bei gleichzeitigem Sprechen (|diff| < both_threshold) werden beide
    Mics durchgelassen.

    Gibt (audio1_gated, audio2_gated) zurueck — nur fuer Analyse,
    nicht fuer die finale Timeline.
    """
    win_samples = int(sr * window_ms / 1000)
    hop = win_samples // 2  # 50% Overlap
    n_frames = (len(audio1) - win_samples) // hop + 1

    # RMS pro Fenster
    rms1 = np.zeros(n_frames)
    rms2 = np.zeros(n_frames)
    for i in range(n_frames):
        s = i * hop
        e = s + win_samples
        rms1[i] = np.sqrt(np.mean(audio1[s:e] ** 2) + 1e-12)
        rms2[i] = np.sqrt(np.mean(audio2[s:e] ** 2) + 1e-12)

    rms1_db = 20 * np.log10(rms1)
    rms2_db = 20 * np.log10(rms2)
    diff_db = rms1_db - rms2_db  # positiv = MIC1 lauter

    # Gate-Entscheidung mit Hysterese und BOTH-Zustand
    # Zustaende: 0=MIC1_ACTIVE, 1=MIC2_ACTIVE, 2=BOTH
    STATE_MIC1, STATE_MIC2, STATE_BOTH = 0, 1, 2
    states = np.zeros(n_frames, dtype=int)
    current = STATE_MIC1 if diff_db[0] > 0 else STATE_MIC2

    for i in range(n_frames):
        d = diff_db[i]
        if current == STATE_MIC1:
            if d < -hysteresis_db:
                current = STATE_MIC2
            elif abs(d) < both_threshold_db:
                current = STATE_BOTH
        elif current == STATE_MIC2:
            if d > hysteresis_db:
                current = STATE_MIC1
            elif abs(d) < both_threshold_db:
                current = STATE_BOTH
        else:  # STATE_BOTH
            if d > both_threshold_db:
                current = STATE_MIC1
            elif d < -both_threshold_db:
                current = STATE_MIC2
        states[i] = current

    # Gain-Kurven
    floor_linear = 10 ** (floor_db / 20)
    gain1_frames = np.where(states == STATE_MIC2, floor_linear, 1.0)
    gain2_frames = np.where(states == STATE_MIC1, floor_linear, 1.0)

    # Attack/Release Smoothing
    attack_f = max(1, int((attack_ms / 1000) * sr / hop))
    release_f = max(1, int((release_ms / 1000) * sr / hop))
    alpha_attack = 1.0 - np.exp(-2.2 / attack_f) if attack_f > 0 else 1.0
    alpha_release = 1.0 - np.exp(-2.2 / release_f) if release_f > 0 else 1.0

    def smooth_gain(gain_raw):
        smoothed = np.zeros_like(gain_raw)
        smoothed[0] = gain_raw[0]
        for i in range(1, len(gain_raw)):
            if gain_raw[i] > smoothed[i - 1]:
                smoothed[i] = smoothed[i - 1] + alpha_attack * (gain_raw[i] - smoothed[i - 1])
            else:
                smoothed[i] = smoothed[i - 1] + alpha_release * (gain_raw[i] - smoothed[i - 1])
        return smoothed

    gain1_smooth = smooth_gain(gain1_frames)
    gain2_smooth = smooth_gain(gain2_frames)

    # Frame-Gains auf Sample-Ebene interpolieren
    frame_times = np.arange(n_frames) * hop + win_samples // 2
    sample_times = np.arange(len(audio1))
    gain1_samples = np.interp(sample_times, frame_times, gain1_smooth)
    gain2_samples = np.interp(sample_times, frame_times, gain2_smooth)

    # Statistiken
    mic1_pct = np.sum(states == STATE_MIC1) / n_frames * 100
    mic2_pct = np.sum(states == STATE_MIC2) / n_frames * 100
    both_pct = np.sum(states == STATE_BOTH) / n_frames * 100
    switches = np.sum(np.diff(states) != 0)
    print(f"  MIC1 aktiv: {mic1_pct:.1f}%, MIC2 aktiv: {mic2_pct:.1f}%, "
          f"Beide: {both_pct:.1f}%")
    print(f"  Wechsel: {switches}")

    return audio1 * gain1_samples, audio2 * gain2_samples



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
