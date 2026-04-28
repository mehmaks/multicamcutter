"""
Audio Enhance Backend — DeNoise, DeReverb, Voice-Leveler Pipeline.

Extrahiert aus ui/pages/enhance.py.
"""

from __future__ import annotations

import logging
import os
import queue
import tempfile
from pathlib import Path

_log = logging.getLogger("rtk")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}


# ── Library availability flags ──────────────────────────────────────────────

try:
    from df.enhance import enhance as df_enhance, init_df, load_audio
    DF_AVAILABLE = True
except ImportError:
    DF_AVAILABLE = False

try:
    from audio_separator.separator import Separator as _ASSeparator
    AS_AVAILABLE = True
except ImportError:
    AS_AVAILABLE = False

try:
    from nara_wpe.wpe import wpe_v8 as _nara_wpe
    NARA_WPE_AVAILABLE = True
except ImportError:
    NARA_WPE_AVAILABLE = False

try:
    from resemble_enhance.enhancer.inference import enhance as re_enhance
    RE_AVAILABLE = True
except ImportError:
    RE_AVAILABLE = False

DR_AVAILABLE = AS_AVAILABLE or NARA_WPE_AVAILABLE or RE_AVAILABLE
AS_MODEL_DIR = str(Path.home() / ".cache" / "audio-separator-models")


# ── Voice Leveler Filter Chain ──────────────────────────────────────────────

def build_mv_filterchain(gate_db, llt_db, ll_gain_db, leveler_lufs, ceiling_dbfs,
                         hlt_db, hl_gain_db, soft_mode):
    """
    Voice Leveler-style dynamics chain via ffmpeg compand + loudnorm + alimiter.

    Compand transfer curve (input -> output, all in dBFS):
      -90  -> -90             floor (below Gate: 1:1)
      gate -> gate            Gate: static lower boundary; below = no processing
      llt  -> llt + ll_gain   Low Level Threshold: full upward compression from here
      hlt  -> hlt             High Level Threshold: gain back to 0 (unity); 1:1 above this
      0    -> hl_gain          Peak Compressor (hl_gain is negative = attenuation at 0 dBFS)

    Monotonicity constraints (validated in UI):
      gate < llt
      hlt  >= llt + ll_gain   (otherwise LL taper zone inverts -> pumping)
      hl_gain >= hlt           (otherwise HL compression zone inverts -> pumping)
    """
    limit_linear = round(min(max(10 ** (ceiling_dbfs / 20), 0.001), 1.0), 6)
    soft_knee    = 4 if soft_mode else 0
    compand_pts  = (
        f"-90/-90"
        f"|{round(gate_db, 1)}/{round(gate_db, 1)}"
        f"|{round(llt_db, 1)}/{round(llt_db + ll_gain_db, 1)}"
        f"|{round(hlt_db, 1)}/{round(hlt_db, 1)}"
        f"|0/{round(hl_gain_db, 1)}"
    )
    return ", ".join([
        f"compand=attacks=0.02:decays=0.4:points={compand_pts}:soft-knee={soft_knee}",
        f"loudnorm=I={leveler_lufs}:TP={ceiling_dbfs}:LRA=9:linear=true",
        f"alimiter=level_in=1:level_out=1:limit={limit_linear}:attack=5:release=50:level=disabled",
    ])


# ── Enhancement Pipeline ────────────────────────────────────────────────────

def run_pipeline(in_path: str, out_path: str,
                 use_dn: bool, dn_params: dict,
                 use_dr: bool, dr_params: dict,
                 use_mv: bool, mv_params: dict,
                 q: queue.Queue,
                 pre_normalize: bool = False,
                 dr_first: bool = False):
    """Run full enhancement pipeline on a single file. Writes result to out_path."""
    import torch
    import soundfile as sf
    import numpy as np
    import subprocess
    import json
    import re

    # ── Video extraction ──────────────────────────────────────────────────────
    current = in_path
    _video_tmp = None
    if Path(in_path).suffix.lower() in VIDEO_EXTENSIONS:
        q.put("  Audio-Extraktion via ffmpeg …")
        _video_tmp = tempfile.mktemp(suffix=".wav")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", in_path, "-map", "0:a:0", "-acodec", "pcm_s24le", _video_tmp],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg Audio-Extraktion fehlgeschlagen:\n{r.stderr[-500:]}")
        current = _video_tmp

    # ── Sample rate detection ─────────────────────────────────────────────────
    orig_sr = (sf.info(current).samplerate
               if Path(current).suffix.lower() in {".wav", ".aif", ".aiff", ".flac"}
               else None)
    if orig_sr is None:
        import librosa
        orig_sr = librosa.get_samplerate(current)

    # ── Format conversion (MP3/AIF -> WAV for DeepFilterNet) ─────────────────
    _converted_tmp = None
    if Path(current).suffix.lower() in {".mp3", ".aif", ".aiff", ".flac", ".m4a"}:
        import librosa
        _audio_data, _sr = librosa.load(in_path, sr=None, mono=False)
        if _audio_data.ndim == 1:
            _audio_data = _audio_data[np.newaxis, :]
        _converted_tmp = tempfile.mktemp(suffix=".wav")
        sf.write(_converted_tmp, _audio_data.T, _sr, subtype="PCM_24")
        current = _converted_tmp

    # ── EBU R128 Pre-Normalisierung ───────────────────────────────────────────
    _norm_tmp = None
    if pre_normalize:
        q.put("  EBU R128 Normalisierung …")
        r1 = subprocess.run(
            ["ffmpeg", "-i", current,
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "/dev/null"],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        _m = re.search(r'\{[^{}]+\}', r1.stderr, re.DOTALL)
        if not _m:
            raise RuntimeError(f"EBU R128 Analyse fehlgeschlagen:\n{r1.stderr[-300:]}")
        _stats = json.loads(_m.group())
        _norm_tmp = tempfile.mktemp(suffix=".wav")
        _af = (
            f"loudnorm=I=-16:TP=-1.5:LRA=11"
            f":measured_I={_stats['input_i']}:measured_TP={_stats['input_tp']}"
            f":measured_LRA={_stats['input_lra']}:measured_thresh={_stats['input_thresh']}"
            f":offset={_stats['target_offset']}:linear=true"
        )
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-i", current, "-af", _af, _norm_tmp],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        if r2.returncode != 0:
            raise RuntimeError(f"EBU R128 fehlgeschlagen:\n{r2.stderr[-300:]}")
        current = _norm_tmp

    # ── De-Noise helper ───────────────────────────────────────────────────────
    def _do_denoise(src):
        q.put("  De-Noise …")
        model, df_state, _ = init_df()
        audio, _ = load_audio(src, sr=df_state.sr())
        enhanced = df_enhance(model, df_state, audio, atten_lim_db=dn_params["atten_lim"])
        _np = enhanced.cpu().numpy()
        if _np.ndim == 2:
            _np = _np.T
        tmp = tempfile.mktemp(suffix=".wav")
        sf.write(tmp, _np, df_state.sr(), subtype="FLOAT")
        return tmp

    # ── De-Reverb helper ─────────────────────────────────────────────────────
    def _do_dereverb(src):
        q.put(f"  De-Reverb ({dr_params.get('as_model', '').split('_')[0]}) …")
        if AS_AVAILABLE:
            import shutil
            _as_tmpdir = tempfile.mkdtemp()
            try:
                _is_vr = dr_params["as_model"].endswith(".pth")
                sep = _ASSeparator(
                    log_level=logging.WARNING,
                    model_file_dir=AS_MODEL_DIR,
                    output_dir=_as_tmpdir,
                    output_format="WAV",
                    output_single_stem=None,
                    vr_params={
                        "batch_size": 1, "window_size": 512,
                        "aggression": dr_params["as_aggression"],
                        "enable_tta": dr_params["as_tta"],
                        "enable_post_process": False,
                        "post_process_threshold": 0.2,
                        "high_end_process": False,
                    } if _is_vr else {},
                )
                sep.load_model(dr_params["as_model"])
                output_files = sep.separate(src)
                output_files = [
                    f if os.path.isabs(f) and os.path.exists(f)
                    else str(Path(_as_tmpdir) / os.path.basename(f))
                    for f in output_files
                ]
                _POS = ["no reverb", "no_reverb", "dry", "clean"]
                _NEG = ["(reverb)", "(echo)", "(reverb+echo)", "_reverb)", "_echo)"]
                _clean = next((f for f in output_files
                               if any(k in os.path.basename(f).lower() for k in _POS)), None)
                if _clean is None:
                    _clean = next((f for f in output_files
                                   if not any(k in os.path.basename(f).lower() for k in _NEG)), None)
                if _clean is None and output_files:
                    _clean = output_files[0]
                if _clean is None:
                    raise RuntimeError("audio-separator hat keine Output-Datei erzeugt.")
                q.put(f"  Clean-Stem: {os.path.basename(_clean)}")
                _data, _sr = sf.read(_clean, dtype="float32", always_2d=True)
                tmp = tempfile.mktemp(suffix=".wav")
                sf.write(tmp, _data, _sr, subtype="FLOAT")
                return tmp
            finally:
                shutil.rmtree(_as_tmpdir, ignore_errors=True)
        elif torch.cuda.is_available() and RE_AVAILABLE:
            _data, _sr = sf.read(src, dtype="float32", always_2d=True)
            wav = torch.from_numpy(_data.mean(axis=1))
            enh, new_sr = re_enhance(wav, _sr, "cuda",
                nfe=dr_params["nfe"], solver="midpoint",
                lambd=dr_params["lambd"], tau=0.5)
            tmp = tempfile.mktemp(suffix=".wav")
            sf.write(tmp, enh.unsqueeze(0).cpu().numpy().T, new_sr, subtype="FLOAT")
            return tmp
        elif NARA_WPE_AVAILABLE:
            from scipy.signal import stft as _stft, istft as _istft
            _data, _sr = sf.read(src, dtype="float64", always_2d=True)
            nperseg, noverlap = 512, 384
            Y = np.stack([_stft(_data[:, ch], fs=_sr, nperseg=nperseg, noverlap=noverlap)[2]
                          for ch in range(_data.shape[1])], axis=1)
            Y_clean = _nara_wpe(Y, taps=dr_params["taps"], delay=3,
                                iterations=dr_params["iterations"])
            out_ch = []
            for ch in range(Y_clean.shape[1]):
                _, ch_out = _istft(Y_clean[:, ch, :], fs=_sr, nperseg=nperseg, noverlap=noverlap)
                out_ch.append(ch_out.astype(np.float32))
            _out = np.stack(out_ch, axis=1)
            orig_len = _data.shape[0]
            _out = (_out[:orig_len] if _out.shape[0] >= orig_len
                    else np.pad(_out, ((0, orig_len - _out.shape[0]), (0, 0))))
            tmp = tempfile.mktemp(suffix=".wav")
            sf.write(tmp, _out, _sr, subtype="FLOAT")
            return tmp
        else:
            q.put("  ⚠ De-Reverb übersprungen — kein kompatibles Modul verfügbar")
            return src

    # ── Voice Leveler helper ─────────────────────────────────────────────────
    def _do_maxxvolume(src):
        q.put("  Voice Leveler …")
        filterchain = build_mv_filterchain(
            mv_params["gate"],    mv_params["llt"],     mv_params["ll_gain"],
            mv_params["leveler"], mv_params["ceiling"],
            mv_params["hlt"],     mv_params["hl_gain"], mv_params["soft"],
        )
        tmp = tempfile.mktemp(suffix=".wav")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-af", filterchain,
             "-ar", "48000", "-acodec", "pcm_s24le", tmp],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            raise RuntimeError(f"Voice Leveler (ffmpeg) fehlgeschlagen:\n{r.stderr[-300:]}")
        return tmp

    # ── Pipeline-Reihenfolge ─────────────────────────────────────────────────
    _intermediates = []

    if dr_first:
        if use_dr:
            _n = _do_dereverb(current); _intermediates.append(_n); current = _n
        if use_dn:
            _n = _do_denoise(current);  _intermediates.append(_n); current = _n
    else:
        if use_dn:
            _n = _do_denoise(current);  _intermediates.append(_n); current = _n
        if use_dr:
            _n = _do_dereverb(current); _intermediates.append(_n); current = _n

    # Voice Leveler is always last; it also sets 48kHz sample rate
    if use_mv:
        _n = _do_maxxvolume(current)
        _intermediates.append(_n)
        current = _n
        # Voice Leveler output is already PCM_24 @ 48kHz — copy directly
        import shutil
        shutil.copy2(current, out_path)
    else:
        # Resample to original SR and write PCM_24
        _out_np, _final_sr = sf.read(current, dtype="float32", always_2d=True)
        if _final_sr != orig_sr:
            import librosa
            q.put(f"  Resample {_final_sr} Hz → {orig_sr} Hz …")
            _out_np = np.stack([
                librosa.resample(ch, orig_sr=_final_sr, target_sr=orig_sr)
                for ch in _out_np.T
            ], axis=1)
        sf.write(out_path, _out_np, orig_sr, subtype="PCM_24")

    # ── Cleanup ──────────────────────────────────────────────────────────────
    for _tmp in [_video_tmp, _converted_tmp, _norm_tmp] + _intermediates:
        if _tmp and _tmp != in_path and Path(_tmp).exists():
            try:
                Path(_tmp).unlink()
            except Exception:
                pass
