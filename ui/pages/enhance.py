"""
Audio Enhance — DeepFilterNet (De-Noise) + audio-separator (De-Reverb) + Voice Leveler (Dynamics)
Optionale Whisper-Analyse ermittelt Gate-Threshold, Leveler-Target und Low-Level-Gain automatisch.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import threading
import queue
import tempfile
import logging
import time
from pathlib import Path

_log = logging.getLogger("rtk")

st.title(":material/mic: Audio Enhance")
st.caption("Entfernt Raumhall und Hintergrundgeräusche aus Sprachaufnahmen. Optional wird die Lautstärke danach automatisch angeglichen.")

# ── Library availability ───────────────────────────────────────────────────────

try:
    from df.enhance import enhance as df_enhance, init_df, load_audio, save_audio as df_save
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

try:
    import whisper as _whisper_lib
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

DR_AVAILABLE = AS_AVAILABLE or NARA_WPE_AVAILABLE or RE_AVAILABLE
AS_MODEL_DIR  = str(Path.home() / ".cache" / "audio-separator-models")

if not DF_AVAILABLE and not DR_AVAILABLE:
    st.error("Keine Enhancement-Bibliothek installiert.")
    st.code("pip install deepfilternet audio-separator onnxruntime", language="bash")
    st.stop()

# ── Session state ─────────────────────────────────────────────────────────────

for _k, _v in {
    "enhance_running":          False,
    "enhance_log":              [],
    "enhance_download_results": {},
    "enhance_analysis_running": False,
    "enhance_analysis_queue":   None,
    "enhance_analysis_result":  None,
    "mv_gate":    -40.0,
    "mv_llt":     -32.0,
    "mv_ll_gain":  12.0,
    "mv_leveler": -20.0,
    "mv_hlt":      -6.0,
    "mv_hl_gain":  -4.5,
    "mv_soft":     True,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Analysis queue polling — must run before any widgets are rendered ──────────
if st.session_state.enhance_analysis_running and st.session_state.enhance_analysis_queue:
    _aq = st.session_state.enhance_analysis_queue
    if not _aq.empty():
        _result = _aq.get_nowait()
        st.session_state.enhance_analysis_running = False
        if isinstance(_result, dict) and "error" not in _result:
            st.session_state.enhance_analysis_result = _result
            st.session_state.mv_gate    = _result["gate_threshold"]
            st.session_state.mv_llt     = _result["quiet_speech"]
            st.session_state.mv_ll_gain = _result["ll_gain_suggestion"]
            # Re-open Voice Leveler expanders to show updated values
            st.session_state.pop("mv_expander_open", None)
            st.session_state.pop("mv_adv_expander_open", None)
            st.rerun()

# ── Pipeline ──────────────────────────────────────────────────────────────────

st.subheader("Pipeline")
col_p1, col_p2, col_p3 = st.columns(3)

with col_p1:
    use_denoise = st.checkbox(
        "De-Noise (DeepFilterNet)",
        value=True,
        disabled=not DF_AVAILABLE,
        help="Nicht installiert — `pip install deepfilternet`" if not DF_AVAILABLE else
             "KI-basierte Rauschunterdrückung.",
    )

with col_p2:
    if AS_AVAILABLE:
        _dr_label = "De-Reverb (audio-separator)"
        _dr_help  = "KI-basierte Hall-Entfernung. Läuft auf CPU/Apple Silicon."
    elif NARA_WPE_AVAILABLE:
        _dr_label = "De-Reverb (nara_wpe)"
        _dr_help  = "Klassischer WPE-Algorithmus."
    else:
        _dr_label = "De-Reverb ⚠ nicht verfügbar"
        _dr_help  = "`pip install audio-separator onnxruntime`"
    use_dereverb = st.checkbox(_dr_label, value=False, disabled=not DR_AVAILABLE, help=_dr_help)

with col_p3:
    use_maxxvolume = st.checkbox(
        "Voice Leveler (Dynamics)",
        value=False,
        help="Gate → Upward Compressor → Leveler (AGC) → Limiter via ffmpeg. Nur für Sprachspuren.",
    )

if not use_denoise and not use_dereverb and not use_maxxvolume:
    st.warning("Mindestens eine Pipeline-Stufe auswählen.")

col_opt1, col_opt2 = st.columns(2)
with col_opt1:
    pre_normalize = st.checkbox(
        "EBU R128 Normalisierung (Pre-Processing)",
        value=False,
        help="Normalisiert auf -16 LUFS / -1.5 dBTP vor der Verarbeitung.",
    )
with col_opt2:
    dr_first = st.checkbox(
        "De-Reverb vor De-Noise",
        value=False,
        disabled=not (use_denoise and use_dereverb),
        help="Empfohlen bei halligen Aufnahmen: De-Reverb zuerst, De-Noise glättet Artefakte.",
    )

# ── Settings ──────────────────────────────────────────────────────────────────

atten_lim    = 0
nfe          = 32
lambd        = 0.5
wpe_taps     = 10
wpe_iter     = 3
as_model     = "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt"
as_aggression = 5
as_tta       = False

_AS_MODELS = {
    "Standard — MelBand Roformer De-Reverb (anvuew)":             "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt",
    "Sanft — MelBand Roformer De-Reverb Less Aggressive (anvuew)":"dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt",
    "BS-Roformer De-Reverb":                                       "deverb_bs_roformer_8_384dim_10depth.ckpt",
    "Normal — UVR De-Echo Normal (FoxJoy)":                       "UVR-De-Echo-Normal.pth",
    "Aggressiv — UVR De-Echo Aggressive (FoxJoy)":                "UVR-De-Echo-Aggressive.pth",
    "Echo+Reverb — MelBand Roformer De-Reverb-Echo V2 (Sucial)":  "dereverb-echo_mel_band_roformer_sdr_13.4843_v2.ckpt",
    "Klassisch — UVR DeEcho-DeReverb (FoxJoy)":                   "UVR-DeEcho-DeReverb.pth",
}
_VR_MODELS = {f for f in _AS_MODELS.values() if f.endswith(".pth")}

if use_denoise and DF_AVAILABLE:
    with st.expander("De-Noise Einstellungen", expanded=True):
        atten_lim = st.slider(
            "Dämpfungs-Limit (dB)", min_value=0, max_value=40, value=0,
            help="0 = maximale Rauschreduktion · höhere Werte = sanfterer Eingriff",
        )

if use_dereverb and DR_AVAILABLE:
    with st.expander("De-Reverb Einstellungen", expanded=True):
        import torch as _torch_check
        _use_cuda = _torch_check.cuda.is_available() and RE_AVAILABLE and not AS_AVAILABLE
        if AS_AVAILABLE:
            _model_display = st.selectbox(
                "Modell", options=list(_AS_MODELS.keys()), index=0,
                help="Roformer (`.ckpt`): KI-basiert. UVR (`.pth`): mit Aggressivitäts-Regler.",
            )
            as_model = _AS_MODELS[_model_display]
            _is_vr = as_model in _VR_MODELS
            if _is_vr:
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    as_aggression = st.slider("Aggressivität", min_value=1, max_value=20, value=5,
                        help="1 = minimal, 20 = maximal. Default 5 ist ein guter Ausgangspunkt.")
                with col_r2:
                    as_tta = st.checkbox("Test-Time Augmentation (TTA)", value=False,
                        help="Bessere Qualität durch gespiegeltes Signal. ~2× langsamer.")
                    st.caption("**UVR VR-Arch** — Aggressivität 10–15 für starken Hall.")
            else:
                st.caption("**MelBand Roformer** — kein Intensitäts-Regler. Für mehr/weniger Eingriff: anderes Modell wählen.")
        elif _use_cuda:
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                nfe   = st.slider("Qualitätsstufen (NFE)", min_value=8, max_value=64, value=32, step=8)
                lambd = st.slider("De-Reverb-Stärke (λ)", min_value=0.0, max_value=1.0, value=0.5, step=0.05)
            with col_r2:
                st.caption("**Resemble Enhance (CUDA)**")
        else:
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                wpe_taps = st.slider("Filter-Länge (taps)", min_value=5, max_value=30, value=10)
                wpe_iter = st.slider("Iterationen", min_value=1, max_value=10, value=3)
            with col_r2:
                st.caption("**nara_wpe** — für bessere Ergebnisse: `pip install audio-separator`")

if use_maxxvolume:
    _mv_expand = "mv_expander_open" not in st.session_state
    st.session_state.mv_expander_open = True
    with st.expander("Voice Leveler Einstellungen", expanded=_mv_expand):
        _ana = st.session_state.enhance_analysis_result

        col_mv1, col_mv2, col_mv3 = st.columns(3)
        with col_mv1:
            mv_gate = st.slider(
                "Gate (dBFS)",
                min_value=-70.0, max_value=-10.0,
                value=float(st.session_state.mv_gate),
                step=0.5, format="%.1f dBFS",
                help="Unterster Arbeitspunkt. Unter diesem Pegel: keine Veränderung. "
                     "Zwischen Gate und LLT: Übergangszone in den Upward Compressor.",
            )
            st.session_state.mv_gate = mv_gate
        with col_mv2:
            mv_llt = st.slider(
                "Low Level Threshold (dBFS)",
                min_value=-60.0, max_value=-10.0,
                value=float(st.session_state.mv_llt),
                step=0.5, format="%.1f dBFS",
                help="Ab diesem Pegel greift der Upward Compressor vollständig. "
                     "Signale zwischen Gate und LLT werden schrittweise angehoben.",
            )
            st.session_state.mv_llt = mv_llt
        with col_mv3:
            mv_ll_gain = st.slider(
                "Low Level Gain (dB)",
                min_value=0.0, max_value=24.0,
                value=float(st.session_state.mv_ll_gain),
                step=0.5, format="+%.1f dB",
                help="Maximale Anhebung für Signale am und unterhalb des LLT.",
            )
            st.session_state.mv_ll_gain = mv_ll_gain

        col_mv4, col_mv5, col_mv6 = st.columns(3)
        with col_mv4:
            mv_leveler = st.slider(
                "Leveler Target (LUFS)",
                min_value=-30.0, max_value=-10.0,
                value=float(st.session_state.mv_leveler),
                step=0.5, format="%.1f LUFS",
                help="Ziel-Loudness des AGC-Levelers (EBU R128 normalisierung).",
            )
            st.session_state.mv_leveler = mv_leveler
        with col_mv5:
            mv_ceiling = st.slider(
                "Output Ceiling (dBFS)",
                min_value=-6.0, max_value=-0.5, value=-1.5, step=0.5,
                format="%.1f dBFS",
                help="True Peak Ceiling für Loudnorm und Brickwall-Limiter.",
            )
        with col_mv6:
            st.write("")

        _mv_adv_expand = "mv_adv_expander_open" not in st.session_state
        st.session_state.mv_adv_expander_open = True
        with st.expander("Erweiterte Parameter", expanded=_mv_adv_expand):
            col_ma1, col_ma2, col_ma3 = st.columns(3)
            with col_ma1:
                mv_hlt = st.slider(
                    "High Level Threshold (dBFS)",
                    min_value=-30.0, max_value=-1.0,
                    value=float(st.session_state.mv_hlt),
                    step=0.5, format="%.1f dBFS",
                    help="Ab diesem Pegel greift der Peak Compressor. "
                         "Muss ≥ LLT + LL Gain sein.",
                )
                st.session_state.mv_hlt = mv_hlt
            with col_ma2:
                mv_hl_gain = st.slider(
                    "High Level Gain (dB)",
                    min_value=-12.0, max_value=0.0,
                    value=float(st.session_state.mv_hl_gain),
                    step=0.5, format="%.1f dB",
                    help="Maximale Absenkung bei 0 dBFS. Muss ≥ HLT (dBFS-Wert) sein.",
                )
                st.session_state.mv_hl_gain = mv_hl_gain
            with col_ma3:
                mv_soft = st.checkbox(
                    "Soft Mode",
                    value=bool(st.session_state.mv_soft),
                    help="Soft-Knee an allen Übergangspunkten der Dynamikkurve.",
                )
                st.session_state.mv_soft = mv_soft

            # Constraint warnings
            _warns = []
            if mv_gate >= mv_llt:
                _warns.append(f"Gate ({mv_gate:.1f}) muss unter LLT ({mv_llt:.1f}) liegen.")
            if mv_hlt < mv_llt + mv_ll_gain:
                _warns.append(
                    f"HLT ({mv_hlt:.1f}) muss ≥ LLT + LL Gain "
                    f"({mv_llt:.1f} + {mv_ll_gain:.1f} = {mv_llt + mv_ll_gain:.1f}) sein "
                    f"— sonst Pumpen im Upward-Compressor."
                )
            if mv_hl_gain < mv_hlt:
                _warns.append(
                    f"HL Gain ({mv_hl_gain:.1f} dBFS) muss ≥ HLT ({mv_hlt:.1f} dBFS) sein "
                    f"— sonst Pumpen im Peak-Compressor."
                )
            for _w in _warns:
                st.warning(_w)

        if _ana:
            st.caption(
                f"Letzte Analyse: Rauschboden **{_ana['noise_floor']:.1f} dBFS** · "
                f"Leise Sprache **{_ana['quiet_speech']:.1f} dBFS** · "
                f"Mittlere Sprache **{_ana['median_speech']:.1f} dBFS** · "
                f"Sprachanteil **{_ana['speech_ratio']:.0%}** "
                f"— Gate / LLT / LL Gain automatisch gesetzt"
            )
else:
    mv_gate    = st.session_state.mv_gate
    mv_llt     = st.session_state.mv_llt
    mv_ll_gain = st.session_state.mv_ll_gain
    mv_leveler = st.session_state.mv_leveler
    mv_ceiling = -1.5
    mv_hlt     = st.session_state.mv_hlt
    mv_hl_gain = st.session_state.mv_hl_gain
    mv_soft    = st.session_state.mv_soft

st.divider()

# ── File selection ─────────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}

st.subheader("Dateien auswählen")
source_mode = st.radio("Quelle", ["Resolve Media Pool", "Ordner / Dateien"], horizontal=True)

selected_path_files: list = []
uploaded_files = []
resolve_import_target = None

if source_mode == "Resolve Media Pool":

    def _collect_bins(folder, depth=0):
        bins = []
        if depth > 0:
            bins.append("  " * (depth - 1) + folder.GetName())
        for sf in (folder.GetSubFolderList() or []):
            bins.extend(_collect_bins(sf, depth + 1))
        return bins

    def _find_folder(folder, name):
        if folder.GetName() == name:
            return folder
        for sf in (folder.GetSubFolderList() or []):
            found = _find_folder(sf, name)
            if found:
                return found
        return None

    try:
        from resolve_bridge.connection import get_resolve
        resolve = get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        mp = project.GetMediaPool()
        root = mp.GetRootFolder()

        all_bins = _collect_bins(root)
        if not all_bins:
            st.warning("Keine Bins im Media Pool gefunden.")
        else:
            selected_display = st.selectbox("Media Pool Bin", options=all_bins, key="enhance_mp_bin")
            bin_name = selected_display.strip() if selected_display else None
            if bin_name:
                folder = _find_folder(root, bin_name)
                if folder:
                    clips = folder.GetClipList() or []
                    _all_ext = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
                    audio_clips = [
                        (c.GetName(), c.GetClipProperty("File Path"))
                        for c in clips
                        if c.GetClipProperty("File Path")
                        and Path(c.GetClipProperty("File Path")).suffix.lower() in _all_ext
                    ]
                    if audio_clips:
                        _sel_key = f"enhance_mp_clips_{bin_name}"
                        if _sel_key not in st.session_state:
                            st.session_state[_sel_key] = [n for n, _ in audio_clips]
                        chosen = st.multiselect(
                            f"Clips in '{bin_name}'",
                            options=[n for n, _ in audio_clips],
                            key=_sel_key,
                        )
                        selected_path_files = [(n, p) for n, p in audio_clips if n in chosen]
                        resolve_import_target = (mp, folder)
                        _n_video = sum(1 for _, p in selected_path_files
                                       if Path(p).suffix.lower() in VIDEO_EXTENSIONS)
                        if _n_video:
                            st.caption(f"ℹ {_n_video} Videodatei(en) — Audio via ffmpeg extrahiert.")
                    else:
                        st.info("Keine Audio- oder Videodateien in diesem Bin.")
    except Exception as e:
        _log.exception("Audio Enhance: Resolve-Verbindungsfehler beim Laden der Bins")
        st.error("Resolve nicht verbunden")
        st.caption(str(e))

else:
    # ── Ordner scannen ────────────────────────────────────────────────────────
    col_path, col_browse, col_scan = st.columns([4, 1, 1])
    with col_path:
        folder_path_str = st.text_input("Ordner-Pfad",
            placeholder="/Volumes/Media/Recording", key="enhance_folder_path")
    with col_browse:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("", icon=":material/folder_open:", use_container_width=True, key="enhance_folder_browse"):
            import subprocess as _sp_dlg
            try:
                _r = _sp_dlg.run(
                    ["osascript", "-e",
                     'POSIX path of (choose folder with prompt "Ordner auswählen")'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    st.session_state["enhance_folder_path"] = _r.stdout.strip()
                    st.rerun()
            except Exception:
                pass
    with col_scan:
        st.markdown("<br>", unsafe_allow_html=True)
        scan_clicked = st.button("Scannen", use_container_width=True, key="enhance_scan")

    if "enhance_scanned_files" not in st.session_state:
        st.session_state.enhance_scanned_files = []

    if scan_clicked and folder_path_str:
        p = Path(folder_path_str)
        if p.is_dir():
            found = sorted(
                (f for f in p.iterdir()
                 if f.suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS),
                key=lambda f: f.name,
            )
            st.session_state.enhance_scanned_files = [(f.name, str(f)) for f in found]
            if not found:
                st.warning("Keine Audio- oder Videodateien gefunden.")
        else:
            st.error("Ordner nicht gefunden.")
            st.session_state.enhance_scanned_files = []

    # ── Einzelne Dateien auswählen ─────────────────────────────────────────────
    st.caption("Oder einzelne Dateien auswählen:")
    col_fp1, col_fp2 = st.columns([4, 1])
    with col_fp2:
        if st.button("", icon=":material/audio_file:", use_container_width=True, key="enhance_file_browse"):
            import subprocess as _sp_dlg
            try:
                _r = _sp_dlg.run(
                    ["osascript", "-e",
                     'set fs to choose file with prompt "Audio- oder Videodateien auswählen" '
                     'of type {"wav","mp3","aif","aiff","mp4","mov","mxf","avi","mkv"} '
                     'with multiple selections allowed\n'
                     'set out to ""\n'
                     'repeat with f in fs\n'
                     'set out to out & POSIX path of f & "\n"\n'
                     'end repeat\n'
                     'return out'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    _paths = [p.strip() for p in _r.stdout.strip().splitlines() if p.strip()]
                    _valid = [(Path(p).name, p) for p in _paths
                              if Path(p).suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS]
                    if _valid:
                        st.session_state.enhance_scanned_files = _valid
                        st.rerun()
            except Exception:
                pass
    with col_fp1:
        _picked_names = ", ".join(n for n, _ in st.session_state.get("enhance_scanned_files", []))
        st.text_input("Ausgewählte Dateien", value=_picked_names, disabled=True,
                      placeholder="Noch keine Dateien ausgewählt",
                      label_visibility="collapsed")

    if st.session_state.enhance_scanned_files:
        _fsel_key = "enhance_folder_select"
        if _fsel_key not in st.session_state:
            st.session_state[_fsel_key] = [n for n, _ in st.session_state.enhance_scanned_files]
        chosen = st.multiselect(
            "Dateien auswählen",
            options=[n for n, _ in st.session_state.enhance_scanned_files],
            key=_fsel_key,
        )
        selected_path_files = [
            (n, p) for n, p in st.session_state.enhance_scanned_files if n in chosen
        ]

    uploaded_files = []

# ── Whisper-Analyse ───────────────────────────────────────────────────────────

_analysis_src = selected_path_files[0][1] if selected_path_files else None

if use_maxxvolume:
    st.divider()
    st.subheader("Whisper-Analyse")

    if not WHISPER_AVAILABLE:
        st.warning("Whisper nicht installiert — `pip install openai-whisper`")
    elif not _analysis_src:
        st.caption("Datei auswählen um die Analyse zu starten.")
    else:
        whisper_model = "base"
        _src_label = Path(_analysis_src).name if _analysis_src else "—"
        col_wa1, col_wa2 = st.columns([4, 1])
        with col_wa1:
            st.caption(f"Quelle: `{_src_label}` · Whisper base")
        with col_wa2:
            analyse_clicked = st.button(
                "Analysieren",
                disabled=st.session_state.enhance_analysis_running,
                use_container_width=True,
                help="Erkennt Stille und Sprache · leitet Voice Leveler-Parameter ab",
            )

        # Show running indicator (polling happens at page top, before widgets)
        if st.session_state.enhance_analysis_running:
            st.info("Analyse läuft …")
            time.sleep(1)
            st.rerun()

        if analyse_clicked and _analysis_src and not st.session_state.enhance_analysis_running:
            _aq = queue.Queue()
            st.session_state.enhance_analysis_queue   = _aq
            st.session_state.enhance_analysis_running = True

            def _run_analysis(wav_path, model_size, q):
                try:
                    import whisper
                    import soundfile as _sf
                    import numpy as _np
                    import subprocess as _sp
                    import tempfile as _tmp

                    # Extract audio from video containers to WAV first
                    _VIDEO_EXT = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}
                    _analysis_tmp = None
                    if Path(wav_path).suffix.lower() in _VIDEO_EXT:
                        _analysis_tmp = _tmp.mktemp(suffix=".wav")
                        r = _sp.run(
                            ["ffmpeg", "-y", "-i", wav_path, "-map", "0:a:0",
                             "-acodec", "pcm_s16le", "-ar", "16000", _analysis_tmp],
                            capture_output=True, encoding="utf-8", errors="replace",
                        )
                        if r.returncode != 0:
                            q.put({"error": f"ffmpeg Audio-Extraktion fehlgeschlagen: {r.stderr[-200:]}"})
                            return
                        wav_path = _analysis_tmp

                    # Load audio as mono float32
                    audio_data, sr = _sf.read(wav_path, dtype="float32", always_2d=True)
                    audio_mono = audio_data.mean(axis=1)

                    # Transcribe with Whisper to get speech segment timestamps
                    model = whisper.load_model(model_size)
                    result = model.transcribe(
                        wav_path, word_timestamps=False, verbose=False,
                        condition_on_previous_text=False,
                    )

                    total_dur = len(audio_mono) / sr

                    # Collect speech intervals from segments
                    speech_intervals = [
                        (max(0.0, seg["start"]), min(total_dur, seg["end"]))
                        for seg in result.get("segments", [])
                        if seg["end"] > seg["start"]
                    ]

                    # Derive silence intervals as gaps between speech
                    silence_intervals = []
                    prev_end = 0.0
                    for s_start, s_end in sorted(speech_intervals):
                        if s_start - prev_end > 0.2:   # gaps > 200ms count as silence
                            silence_intervals.append((prev_end, s_start))
                        prev_end = max(prev_end, s_end)
                    if total_dur - prev_end > 0.2:
                        silence_intervals.append((prev_end, total_dur))

                    def rms_db(samples):
                        rms = _np.sqrt(_np.mean(samples ** 2))
                        return float(20 * _np.log10(max(rms, 1e-10)))

                    # Measure RMS in silence regions (noise floor)
                    silence_levels = []
                    for s, e in silence_intervals:
                        chunk = audio_mono[int(s * sr): int(e * sr)]
                        if len(chunk) > int(sr * 0.1):
                            silence_levels.append(rms_db(chunk))

                    # Measure RMS in 100ms windows within speech regions
                    speech_levels = []
                    win = int(sr * 0.1)
                    for s, e in speech_intervals:
                        start_i, end_i = int(s * sr), int(e * sr)
                        for i in range(start_i, end_i - win, win):
                            speech_levels.append(rms_db(audio_mono[i: i + win]))

                    if not silence_levels or not speech_levels:
                        q.put({"error": "Zu wenig Stille oder Sprache erkannt — "
                                        "Datei ggf. zu kurz oder keine klaren Pausen."})
                        return

                    noise_floor   = float(_np.percentile(silence_levels, 75))
                    quiet_speech  = float(_np.percentile(speech_levels, 10))
                    median_speech = float(_np.percentile(speech_levels, 50))

                    # Derive Voice Leveler parameters from analysis
                    # Gate: 5 dB above noise floor (static curve point, not time-domain gate)
                    gate_threshold    = round(min(noise_floor + 5.0, -15.0), 1)
                    # LLT: where full upward compression begins = quiet speech (10th pct)
                    # LL Gain suggestion: dynamic range of speech = how much to lift quiet to median
                    ll_gain_suggestion = round(max(0.0, min(24.0, median_speech - quiet_speech)), 1)
                    speech_ratio   = (
                        sum(e - s for s, e in speech_intervals) / total_dur
                        if total_dur > 0 else 0.0
                    )

                    # Waveform visualization: peak + RMS envelope (100ms windows)
                    _win = int(sr * 0.1)
                    _n   = len(audio_mono) // _win
                    _wf_times   = [round(i * 0.1 + 0.05, 2) for i in range(_n)]
                    _wf_peak_db = [
                        float(20 * _np.log10(max(
                            _np.max(_np.abs(audio_mono[i*_win:(i+1)*_win])), 1e-10
                        )))
                        for i in range(_n)
                    ]
                    _wf_rms_db  = [
                        float(20 * _np.log10(max(
                            _np.sqrt(_np.mean(audio_mono[i*_win:(i+1)*_win] ** 2)), 1e-10
                        )))
                        for i in range(_n)
                    ]

                    q.put({
                        "gate_threshold":    gate_threshold,
                        "ll_gain_suggestion": ll_gain_suggestion,
                        "noise_floor":       round(noise_floor, 1),
                        "quiet_speech":    round(quiet_speech, 1),
                        "median_speech":   round(median_speech, 1),
                        "speech_ratio":    speech_ratio,
                        "waveform_times":   _wf_times,
                        "waveform_peak_db": _wf_peak_db,
                        "waveform_rms_db":  _wf_rms_db,
                        "speech_intervals": [[s, e] for s, e in speech_intervals],
                    })

                except Exception as exc:
                    _log.exception("Audio Enhance: Analyse-Fehler")
                    q.put({"error": str(exc)})
                finally:
                    if _analysis_tmp and Path(_analysis_tmp).exists():
                        Path(_analysis_tmp).unlink()

            threading.Thread(
                target=_run_analysis,
                args=(_analysis_src, whisper_model, _aq),
                daemon=True,
            ).start()
            st.rerun()

        # ── Waveform Chart ────────────────────────────────────────────────────
        _ana = st.session_state.enhance_analysis_result
        if _ana and "waveform_times" in _ana:
            try:
                import plotly.graph_objects as go

                fig = go.Figure()

                # Speech regions as subtle background bands
                for _s, _e in _ana.get("speech_intervals", []):
                    fig.add_vrect(
                        x0=_s, x1=_e,
                        fillcolor="rgba(100,200,100,0.07)",
                        line_width=0,
                        layer="below",
                    )

                # RMS fill (background reference, thinner)
                fig.add_trace(go.Scatter(
                    x=_ana["waveform_times"],
                    y=_ana["waveform_rms_db"],
                    name="Waveform RMS",
                    mode="lines",
                    line=dict(color="rgba(120,160,255,0.0)", width=0),
                    fill="tozeroy",
                    fillcolor="rgba(120,160,255,0.15)",
                ))

                # Peak waveform (matches DAW meters)
                fig.add_trace(go.Scatter(
                    x=_ana["waveform_times"],
                    y=_ana["waveform_peak_db"],
                    name="Waveform Peak",
                    mode="lines",
                    line=dict(color="rgba(140,180,255,0.9)", width=1),
                ))

                # Helper: horizontal level line as Scatter (toggleable via legend)
                def _lvl(label, value, color, dash="dash"):
                    t0, t1 = _ana["waveform_times"][0], _ana["waveform_times"][-1]
                    return go.Scatter(
                        x=[t0, t1], y=[value, value],
                        name=f"{label}  {value:+.1f} dBFS",
                        mode="lines",
                        line=dict(color=color, dash=dash, width=1.5),
                    )

                # Analysis measurements — RMS-based (dashed)
                fig.add_trace(_lvl("Rauschboden (RMS)",      _ana["noise_floor"],   "#4CAF50"))
                fig.add_trace(_lvl("Leise Sprache (RMS)",    _ana["quiet_speech"],  "#CDDC39"))
                fig.add_trace(_lvl("Mittlere Sprache (RMS)", _ana["median_speech"], "#FF9800"))

                # Voice Leveler parameters (solid)
                fig.add_trace(_lvl("Gate",            mv_gate,    "#F44336", "solid"))
                fig.add_trace(_lvl("Low Level Thresh", mv_llt,    "#FFC107", "solid"))
                fig.add_trace(_lvl("High Level Thresh", mv_hlt,   "#9C27B0", "solid"))
                fig.add_trace(_lvl("Leveler Target",  mv_leveler, "#CE93D8", "dash"))
                fig.add_trace(_lvl("Output Ceiling",  mv_ceiling, "#00BCD4", "dot"))

                fig.update_layout(
                    height=320,
                    margin=dict(l=0, r=0, t=8, b=0),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    legend=dict(
                        orientation="h",
                        yanchor="bottom", y=1.01,
                        xanchor="left", x=0,
                        font=dict(size=11),
                        itemclick="toggle",
                        itemdoubleclick="toggleothers",
                    ),
                    xaxis=dict(
                        title="Zeit (s)",
                        gridcolor="rgba(128,128,128,0.15)",
                        ticksuffix=" s",
                    ),
                    yaxis=dict(
                        title="dBFS",
                        gridcolor="rgba(128,128,128,0.15)",
                        range=[-90, 0],
                    ),
                )

                st.plotly_chart(fig, use_container_width=True)

            except ImportError:
                st.caption("Plotly nicht installiert — `pip install plotly`")

# ── Processing functions ──────────────────────────────────────────────────────

def _build_mv_filterchain(gate_db, llt_db, ll_gain_db, leveler_lufs, ceiling_dbfs,
                           hlt_db, hl_gain_db, soft_mode):
    """
    Voice Leveler-style dynamics chain via ffmpeg compand + loudnorm + alimiter.

    Compand transfer curve (input → output, all in dBFS):
      -90  → -90             floor (below Gate: 1:1)
      gate → gate            Gate: static lower boundary; below = no processing
      llt  → llt + ll_gain   Low Level Threshold: full upward compression from here
      hlt  → hlt             High Level Threshold: gain back to 0 (unity); 1:1 above this
      0    → hl_gain          Peak Compressor (hl_gain is negative = attenuation at 0 dBFS)

    Monotonicity constraints (validated in UI):
      gate < llt
      hlt  >= llt + ll_gain   (otherwise LL taper zone inverts → pumping)
      hl_gain >= hlt           (otherwise HL compression zone inverts → pumping)
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


def _run_pipeline(in_path: str, out_path: str,
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

    # ── Video extraction ───────────────────────────────────────────────────────
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

    # ── Sample rate detection ──────────────────────────────────────────────────
    orig_sr = (sf.info(current).samplerate
               if Path(current).suffix.lower() in {".wav", ".aif", ".aiff", ".flac"}
               else None)
    if orig_sr is None:
        import librosa
        orig_sr = librosa.get_samplerate(current)

    # ── Format conversion (MP3/AIF → WAV for DeepFilterNet) ───────────────────
    _converted_tmp = None
    if Path(current).suffix.lower() in {".mp3", ".aif", ".aiff", ".flac", ".m4a"}:
        import librosa
        _audio_data, _sr = librosa.load(in_path, sr=None, mono=False)
        if _audio_data.ndim == 1:
            _audio_data = _audio_data[np.newaxis, :]
        _converted_tmp = tempfile.mktemp(suffix=".wav")
        sf.write(_converted_tmp, _audio_data.T, _sr, subtype="PCM_24")
        current = _converted_tmp

    # ── EBU R128 Pre-Normalisierung ────────────────────────────────────────────
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

    # ── De-Noise helper ────────────────────────────────────────────────────────
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

    # ── De-Reverb helper ──────────────────────────────────────────────────────
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

    # ── Voice Leveler helper ──────────────────────────────────────────────────────
    def _do_maxxvolume(src):
        q.put("  Voice Leveler …")
        filterchain = _build_mv_filterchain(
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

    # ── Pipeline-Reihenfolge ──────────────────────────────────────────────────
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

    # ── Cleanup ───────────────────────────────────────────────────────────────
    for _tmp in [_video_tmp, _converted_tmp, _norm_tmp] + _intermediates:
        if _tmp and _tmp != in_path and Path(_tmp).exists():
            try:
                Path(_tmp).unlink()
            except Exception:
                pass


def _process_files(files: list,
                   use_dn: bool, dn_params: dict,
                   use_dr: bool, dr_params: dict,
                   use_mv: bool, mv_params: dict,
                   q: queue.Queue, result_store: dict = None,
                   resolve_import: tuple = None,
                   pre_normalize: bool = False,
                   dr_first: bool = False):
    # Build output filename suffix
    _parts = []
    if pre_normalize:
        _parts.append("norm")
    if dr_first and use_dn and use_dr:
        _parts.append("dr-first")
    if use_dn:
        _parts.append(f"denoise-{dn_params['atten_lim']}db")
    if use_dr:
        import torch as _t
        if AS_AVAILABLE:
            _tag = dr_params["as_model"].split(".")[0][:20].rstrip("_")
            if dr_params["as_model"].endswith(".pth"):
                _tag += f"-a{dr_params['as_aggression']}"
                if dr_params["as_tta"]:
                    _tag += "-tta"
            _parts.append(f"dereverb-{_tag}")
        elif _t.cuda.is_available() and RE_AVAILABLE:
            _lam = f"{dr_params['lambd']:.2f}".rstrip("0").rstrip(".")
            _parts.append(f"dereverb-q{dr_params['nfe']}-l{_lam}")
        else:
            _parts.append(f"dereverb-taps{dr_params['taps']}")
    if use_mv:
        _parts.append(
            f"maxxvol-g{mv_params['gate']:.0f}-llt{mv_params['llt']:.0f}"
            f"-llg{mv_params['ll_gain']:.0f}-l{mv_params['leveler']:.0f}"
        )
    _suffix = "_" + "_".join(_parts) if _parts else "_enhanced"

    try:
        q.put("Starte Verarbeitung …\n")
        for name, source, is_path in files:
            q.put(f"► {name}")
            suffix = Path(name).suffix or ".wav"
            if is_path:
                src = Path(source)
                out = src.parent / (src.stem + _suffix + ".wav")
                _run_pipeline(str(src), str(out),
                              use_dn, dn_params, use_dr, dr_params, use_mv, mv_params,
                              q, pre_normalize=pre_normalize, dr_first=dr_first)
                q.put(f"  ✓ gespeichert: {out.name}")
                if resolve_import:
                    try:
                        _mp, _folder = resolve_import
                        _mp.SetCurrentFolder(_folder)
                        _mp.ImportMedia([str(out)])
                        q.put("  ✓ in Resolve importiert\n")
                    except Exception as _e:
                        q.put(f"  ⚠ Resolve-Import fehlgeschlagen: {_e}\n")
                else:
                    q.put("")
            else:
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
                    tmp_in.write(source)
                    tmp_in_path = tmp_in.name
                tmp_out_path = tempfile.mktemp(suffix=".wav")
                try:
                    _run_pipeline(tmp_in_path, tmp_out_path,
                                  use_dn, dn_params, use_dr, dr_params, use_mv, mv_params,
                                  q, pre_normalize=pre_normalize, dr_first=dr_first)
                    with open(tmp_out_path, "rb") as f:
                        result_store[Path(name).stem + _suffix + ".wav"] = f.read()
                    q.put("  ✓ bereit zum Download\n")
                finally:
                    for p in [tmp_in_path, tmp_out_path]:
                        if Path(p).exists():
                            Path(p).unlink()

        q.put("__DONE__0")
    except Exception as e:
        _log.exception("Audio Enhance: Verarbeitungsfehler")
        q.put(f"Fehler: {e}")
        q.put("__DONE__1")


# ── Run ────────────────────────────────────────────────────────────────────────

st.divider()

has_path_files = len(selected_path_files) > 0
pipeline_ok    = use_denoise or use_dereverb or use_maxxvolume
can_start      = has_path_files and pipeline_ok and not st.session_state.enhance_running

start = st.button(
    "Enhance starten", icon=":material/play_arrow:", type="primary",
    disabled=not can_start, use_container_width=True,
)

if start:
    dn_params = {"atten_lim": atten_lim}
    dr_params = {
        "nfe": nfe, "lambd": lambd,
        "taps": wpe_taps, "iterations": wpe_iter,
        "as_model": as_model, "as_aggression": as_aggression, "as_tta": as_tta,
    }
    mv_params = {
        "gate":    mv_gate,
        "llt":     mv_llt,
        "ll_gain": mv_ll_gain,
        "leveler": mv_leveler,
        "ceiling": mv_ceiling,
        "hlt":     mv_hlt,
        "hl_gain": mv_hl_gain,
        "soft":    mv_soft,
    }

    file_list = [(n, p, True) for n, p in selected_path_files]

    st.session_state.enhance_running          = True
    st.session_state.enhance_log              = []
    st.session_state.enhance_download_results = {}
    q = queue.Queue()
    st.session_state.enhance_queue = q

    threading.Thread(
        target=_process_files,
        args=(file_list, use_denoise, dn_params, use_dereverb, dr_params,
              use_maxxvolume, mv_params, q,
              st.session_state.enhance_download_results,
              resolve_import_target if has_path_files and source_mode == "Resolve Media Pool" else None,
              pre_normalize, dr_first),
        daemon=True,
    ).start()
    st.rerun()

