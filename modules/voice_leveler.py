"""
Voice Leveler Backend — Filter-Chain, Loudness-Messung, ffmpeg-Processing.

Extrahiert aus ui/pages/voice_leveler.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from shared.ffmpeg_utils import probe_audio_channels


def build_filterchain(
    gate_db, gate_on,
    llt_db, ll_gain, ll_on,
    hlt_db, hl_gain_db, hl_on,
    leveler_lufs, leveler_on,
    ceiling_dbfs,
    loud,
):
    """
    Baut die Dynamics-Kette (ohne Loudnorm) und gibt ein Tupel zurück:
      (dynamics_chain, leveler_lufs_or_None, ceiling_dbfs)

    Loudnorm wird als Zwei-Pass in run_ffmpeg_processing behandelt —
    dynamics_chain enthält nur compand + alimiter.
    """
    limit_linear = round(min(max(10 ** (ceiling_dbfs / 20), 0.001), 1.0), 6)

    # Build compand points (input_dB/output_dB)
    pts = []

    if ll_on:
        ll_out_at_90 = -90.0 + ll_gain  # LL comp output at -90 dBFS (max boost point)
        if gate_on and ll_out_at_90 < gate_db and gate_db < llt_db:
            t = (gate_db - (-90.0)) / (llt_db - (-90.0))
            gate_ll_out = round(ll_out_at_90 + t * (llt_db - ll_out_at_90), 1)
            floor_out = round(gate_ll_out + 2.0 * (-90.0 - gate_db), 1)
            pts.append(f"-90/{floor_out}")
            pts.append(f"{gate_db}/{gate_ll_out}")
        elif gate_on and gate_db >= llt_db:
            floor_out = round(llt_db + 2.0 * (-90.0 - llt_db), 1)
            pts.append(f"-90/{floor_out}")
        else:
            pts.append(f"-90/{round(ll_out_at_90, 1)}")
        pts.append(f"{llt_db}/{llt_db}")
    elif gate_on:
        gate_floor = round(gate_db - 2.0 * (gate_db + 90.0), 1)
        pts.append(f"-90/{gate_floor}")
        pts.append(f"{gate_db}/{gate_db}")
    else:
        pts.append("-90/-90")

    if hl_on:
        if hlt_db > llt_db:
            pts.append(f"{hlt_db}/{hlt_db}")
        pts.append(f"0/{hl_gain_db}")
    else:
        pts.append("0/0")

    compand_pts = "|".join(pts)

    attacks = 0.02
    decays = 0.15 if loud else 0.8

    dynamics = ", ".join([
        f"compand=attacks={attacks}:decays={decays}:points={compand_pts}:soft-knee=4",
        f"alimiter=level_in=1:level_out=1:limit={limit_linear}:attack=5:release=50:level=disabled",
    ])

    return dynamics, (leveler_lufs if leveler_on else None), ceiling_dbfs


def measure_loudness(src_path: str, leveler_lufs: float,
                     ceiling_dbfs: float) -> str:
    """
    Erster Pass: Integrierte Lautheit der Quelldatei messen (EBU R128).
    Gibt einen fertigen loudnorm-Filterstring mit gemessenen Werten zurück
    (Zwei-Pass-Modus), oder einen Single-Pass-Fallback bei Fehler.
    """
    _fallback = f"loudnorm=I={leveler_lufs}:TP={ceiling_dbfs}:LRA=9:linear=true"
    try:
        _r = subprocess.run(
            ["ffmpeg", "-i", src_path,
             "-af", f"loudnorm=I={leveler_lufs}:TP={ceiling_dbfs}:LRA=9:print_format=json",
             "-f", "null", "-"],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        _m = None
        for _line in reversed(_r.stderr.splitlines()):
            if _line.strip() == "}":
                _stderr = _r.stderr
                _end = _stderr.rfind("}")
                _start = _stderr.rfind("{", 0, _end)
                if _start >= 0:
                    _m = json.loads(_stderr[_start:_end + 1])
                break
        if not _m:
            return _fallback
        return (
            f"loudnorm=I={leveler_lufs}:TP={ceiling_dbfs}:LRA=9"
            f":measured_I={_m['input_i']}"
            f":measured_TP={_m['input_tp']}"
            f":measured_LRA={_m['input_lra']}"
            f":measured_thresh={_m['input_thresh']}"
            f":linear=true"
        )
    except Exception:
        return _fallback


def run_ffmpeg_processing(src_path: str, out_path: str,
                          dynamics_chain: str, leveler_lufs: float | None,
                          ceiling_dbfs: float, q) -> bool:
    """
    Führt die Voice-Leveler-ffmpeg-Pipeline aus.

    Warmup-Stille → Filter-Chain → Warmup abschneiden.
    Schreibt Fortschrittsmeldungen in die Queue q.
    """
    _warmup = 3
    _proc_tmp = tempfile.mktemp(suffix=".wav")
    try:
        _channels = probe_audio_channels(src_path)
        _cl = "mono" if _channels == 1 else "stereo"

        if leveler_lufs is not None:
            q.put("  Lautheit messen (Pass 1) …")
            _loudnorm = measure_loudness(src_path, leveler_lufs, ceiling_dbfs)
            _filterchain = f"{_loudnorm}, {dynamics_chain}"
        else:
            _filterchain = dynamics_chain

        _fc = (
            "[0:a]aformat=sample_fmts=fltp[sil];"
            f"[1:a]aformat=sample_fmts=fltp:sample_rates=48000"
            f":channel_layouts={_cl}[aud];"
            "[sil][aud]concat=n=2:v=0:a=1[cat];"
            f"[cat]{_filterchain}[out]"
        )
        _r1 = subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-t", str(_warmup),
            "-i", f"anullsrc=r=48000:cl={_cl}",
            "-i", src_path,
            "-filter_complex", _fc,
            "-map", "[out]",
            "-ar", "48000", "-acodec", "pcm_s24le", _proc_tmp,
        ], capture_output=True, encoding="utf-8", errors="replace")
        if _r1.returncode != 0:
            raise RuntimeError(_r1.stderr[-300:])

        _r2 = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(_warmup), "-i", _proc_tmp,
             "-acodec", "copy", out_path],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        if _r2.returncode != 0:
            raise RuntimeError(_r2.stderr[-200:])

        return True

    except RuntimeError as _e:
        q.put(f"  Fehler (ffmpeg): {_e}")
        return False
    finally:
        Path(_proc_tmp).unlink(missing_ok=True)
