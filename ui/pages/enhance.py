"""
Audio Enhance — DeepFilterNet (De-Noise) + Resemble Enhance (De-Reverb)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import threading
import queue
import time
import tempfile
from pathlib import Path

st.title("🎙️ Audio Enhance")
st.caption("De-Noise via DeepFilterNet · De-Reverb via Resemble Enhance")

# ── Library availability ───────────────────────────────────────────────────────

try:
    from df.enhance import enhance as df_enhance, init_df, load_audio, save_audio as df_save
    DF_AVAILABLE = True
except ImportError:
    DF_AVAILABLE = False

try:
    from resemble_enhance.enhancer.inference import enhance as re_enhance
    RE_AVAILABLE = True
except ImportError:
    RE_AVAILABLE = False

if not DF_AVAILABLE and not RE_AVAILABLE:
    st.error("Keine Enhancement-Bibliothek installiert.")
    st.code("pip install deepfilternet\npip install git+https://github.com/resemble-ai/resemble-enhance.git",
            language="bash")
    st.stop()

# ── Pipeline ──────────────────────────────────────────────────────────────────

st.subheader("Pipeline")
col_p1, col_p2 = st.columns(2)
with col_p1:
    use_denoise = st.checkbox(
        "De-Noise (DeepFilterNet)",
        value=True,
        disabled=not DF_AVAILABLE,
        help="Nicht installiert — pip install deepfilternet" if not DF_AVAILABLE else "",
    )
with col_p2:
    use_dereverb = st.checkbox(
        "De-Reverb (Resemble Enhance)",
        value=False,
        disabled=not RE_AVAILABLE,
        help="Nicht installiert — pip install git+https://github.com/resemble-ai/resemble-enhance.git" if not RE_AVAILABLE else
             "Modell wird beim ersten Start heruntergeladen (~1 GB)",
    )

if not use_denoise and not use_dereverb:
    st.warning("Mindestens eine Pipeline-Stufe auswählen.")

# ── Settings ──────────────────────────────────────────────────────────────────

if use_denoise and DF_AVAILABLE:
    with st.expander("De-Noise Einstellungen", expanded=True):
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            atten_lim = st.slider(
                "Dämpfungs-Limit (dB)",
                min_value=0, max_value=40, value=0,
                help="0 = maximale Rauschreduktion · höhere Werte = sanfterer Eingriff",
            )
        with col_s2:
            pf = st.checkbox(
                "Post-Filter",
                value=False,
                help="Reduziert 'musical noise' Artefakte nach der Verarbeitung.",
            )

if use_dereverb and RE_AVAILABLE:
    with st.expander("De-Reverb Einstellungen", expanded=True):
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            nfe = st.slider(
                "Qualitätsstufen (NFE)",
                min_value=8, max_value=64, value=32, step=8,
                help="Anzahl der Diffusions-Schritte. Mehr = besser, aber langsamer.",
            )
            lambd = st.slider(
                "De-Reverb-Stärke (λ)",
                min_value=0.0, max_value=1.0, value=0.5, step=0.05,
                help="0 = nur Rauschreduktion ohne Hall-Entfernung · 1 = maximale Hall-Entfernung",
            )
        with col_r2:
            st.caption("**Hinweis:** Das Modell (~1 GB) wird beim ersten Start automatisch heruntergeladen.")
            st.caption("Verarbeitung läuft auf CPU/MPS — De-Reverb dauert je nach Dateigröße einige Minuten.")

st.divider()

# ── File selection ─────────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}

st.subheader("Dateien auswählen")
source_mode = st.radio("Quelle", ["Resolve Media Pool", "Ordner / Dateien"], horizontal=True)

selected_path_files: list = []   # list of (display_name, absolute_path)
uploaded_files = []

# ── Mode A: Resolve Media Pool ─────────────────────────────────────────────────

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
            selected_display = st.selectbox(
                "Media Pool Bin",
                options=all_bins,
                help="Bin mit Audio-Clips (WAV, MP3, AIF)",
            )
            bin_name = selected_display.strip() if selected_display else None
            if bin_name:
                folder = _find_folder(root, bin_name)
                if folder:
                    clips = folder.GetClipList() or []
                    audio_clips = [
                        (c.GetName(), c.GetClipProperty("File Path"))
                        for c in clips
                        if c.GetClipProperty("File Path")
                        and Path(c.GetClipProperty("File Path")).suffix.lower() in AUDIO_EXTENSIONS
                    ]
                    if audio_clips:
                        chosen = st.multiselect(
                            f"Audio-Clips in '{bin_name}'",
                            options=[n for n, _ in audio_clips],
                            default=[n for n, _ in audio_clips],
                        )
                        selected_path_files = [(n, p) for n, p in audio_clips if n in chosen]
                    else:
                        st.info("Keine Audio-Dateien (WAV / MP3 / AIF) in diesem Bin gefunden.")
                else:
                    st.warning(f"Bin '{bin_name}' nicht gefunden.")

    except Exception as e:
        st.error("Resolve nicht verbunden")
        st.caption(str(e))
        st.info("Resolve öffnen und ein Projekt laden, dann hier neu laden.")

# ── Mode B: Ordner / Dateien ──────────────────────────────────────────────────

else:
    col_path, col_btn = st.columns([4, 1])
    with col_path:
        folder_path_str = st.text_input(
            "Ordner-Pfad",
            placeholder="/Volumes/Media/Recording_2024-04-07",
            key="enhance_folder_path",
        )
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        scan_clicked = st.button("Scannen", use_container_width=True)

    if "enhance_scanned_files" not in st.session_state:
        st.session_state.enhance_scanned_files = []

    if scan_clicked and folder_path_str:
        p = Path(folder_path_str)
        if p.is_dir():
            found = sorted(
                (f for f in p.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS),
                key=lambda f: f.name,
            )
            st.session_state.enhance_scanned_files = [(f.name, str(f)) for f in found]
            if not found:
                st.warning("Keine Audio-Dateien in diesem Ordner gefunden.")
        else:
            st.error("Ordner nicht gefunden.")
            st.session_state.enhance_scanned_files = []

    if st.session_state.enhance_scanned_files:
        chosen = st.multiselect(
            "Dateien auswählen",
            options=[n for n, _ in st.session_state.enhance_scanned_files],
            default=[n for n, _ in st.session_state.enhance_scanned_files],
            key="enhance_folder_select",
        )
        selected_path_files = [
            (n, p) for n, p in st.session_state.enhance_scanned_files if n in chosen
        ]

    st.markdown("**Oder Dateien per Drag & Drop:**")
    uploaded_files = st.file_uploader(
        "WAV / MP3 / AIF",
        type=["wav", "mp3", "aif", "aiff"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    ) or []

# ── Processing ─────────────────────────────────────────────────────────────────

def _run_pipeline(in_path: str, out_path: str,
                  use_dn: bool, dn_params: dict,
                  use_dr: bool, dr_params: dict,
                  q: queue.Queue):
    """Run De-Noise and/or De-Reverb on a single file. Writes result to out_path."""
    import torch
    current = in_path

    if use_dn:
        q.put("  De-Noise …")
        model, df_state, _ = init_df()
        audio, _ = load_audio(current, sr=df_state.sr())
        enhanced = df_enhance(model, df_state, audio,
                              atten_lim_db=dn_params["atten_lim"],
                              enable_pf=dn_params["pf"])
        tmp = tempfile.mktemp(suffix=".wav")
        df_save(tmp, enhanced, df_state.sr())
        current = tmp

    if use_dr:
        q.put("  De-Reverb …")
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        import torchaudio
        wav, sr = torchaudio.load(current)
        wav = wav.mean(0)  # mono
        enhanced_wav, new_sr = re_enhance(
            wav, sr, device,
            nfe=dr_params["nfe"],
            solver="midpoint",
            lambd=dr_params["lambd"],
            tau=0.5,
        )
        torchaudio.save(out_path, enhanced_wav.unsqueeze(0).cpu(), new_sr)
    else:
        import shutil
        shutil.copy2(current, out_path)

    # Cleanup temp file from De-Noise stage
    if use_dn and current != in_path and Path(current).exists():
        Path(current).unlink()


def _process_files(files: list, use_dn: bool, dn_params: dict,
                   use_dr: bool, dr_params: dict,
                   q: queue.Queue, result_store: dict = None):
    """
    Process a list of (name, path_or_bytes, is_path) entries.
    If is_path=True: saves *_enhanced.wav alongside original.
    If is_path=False: stores result bytes in result_store[name].
    """
    try:
        q.put("Starte Verarbeitung …\n")
        for name, source, is_path in files:
            q.put(f"► {name}")
            suffix = Path(name).suffix or ".wav"

            if is_path:
                src = Path(source)
                out = src.parent / (src.stem + "_enhanced" + src.suffix)
                _run_pipeline(str(src), str(out), use_dn, dn_params, use_dr, dr_params, q)
                q.put(f"  ✓ gespeichert: {out.name}\n")
            else:
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
                    tmp_in.write(source)
                    tmp_in_path = tmp_in.name
                tmp_out_path = tempfile.mktemp(suffix=".wav")
                try:
                    _run_pipeline(tmp_in_path, tmp_out_path,
                                  use_dn, dn_params, use_dr, dr_params, q)
                    with open(tmp_out_path, "rb") as f:
                        result_store[Path(name).stem + "_enhanced.wav"] = f.read()
                    q.put(f"  ✓ bereit zum Download\n")
                finally:
                    for p in [tmp_in_path, tmp_out_path]:
                        if Path(p).exists():
                            Path(p).unlink()

        q.put("__DONE__0")
    except Exception as e:
        q.put(f"Fehler: {e}")
        q.put("__DONE__1")


# ── Run ────────────────────────────────────────────────────────────────────────

st.divider()

for k, v in [("enhance_running", False), ("enhance_log", []),
             ("enhance_download_results", {})]:
    if k not in st.session_state:
        st.session_state[k] = v

has_path_files = len(selected_path_files) > 0
has_uploads    = len(uploaded_files) > 0
pipeline_ok    = use_denoise or use_dereverb
can_start      = (has_path_files or has_uploads) and pipeline_ok and not st.session_state.enhance_running

col_run, col_clear = st.columns([3, 1])
with col_run:
    start = st.button(
        "▶ Enhance starten",
        type="primary",
        disabled=not can_start,
        use_container_width=True,
    )
with col_clear:
    if st.button("Log leeren", use_container_width=True, key="enhance_clear"):
        st.session_state.enhance_log = []
        st.session_state.enhance_download_results = {}
        st.session_state.enhance_scanned_files = []
        st.rerun()

if start:
    dn_params = {"atten_lim": atten_lim if use_denoise else 0,
                 "pf": pf if use_denoise else False}
    dr_params = {"nfe": nfe if use_dereverb else 32,
                 "lambd": lambd if use_dereverb else 0.5}

    if has_path_files:
        file_list = [(n, p, True) for n, p in selected_path_files]
    else:
        file_list = [(uf.name, uf.read(), False) for uf in uploaded_files]

    st.session_state.enhance_running = True
    st.session_state.enhance_log = []
    st.session_state.enhance_download_results = {}
    q = queue.Queue()
    st.session_state.enhance_queue = q

    threading.Thread(
        target=_process_files,
        args=(file_list, use_denoise, dn_params, use_dereverb, dr_params,
              q, st.session_state.enhance_download_results),
        daemon=True,
    ).start()

# ── Log ───────────────────────────────────────────────────────────────────────

if st.session_state.enhance_running and "enhance_queue" in st.session_state:
    log_ph = st.empty()
    while st.session_state.enhance_running:
        try:
            line = st.session_state.enhance_queue.get(timeout=0.1)
            if line.startswith("__DONE__"):
                exit_code = int(line.replace("__DONE__", ""))
                st.session_state.enhance_running = False
                if exit_code == 0:
                    st.success("Fertig!")
                else:
                    st.error("Verarbeitung fehlgeschlagen — siehe Log.")
                break
            st.session_state.enhance_log.append(line)
        except queue.Empty:
            pass
        log_ph.code("\n".join(st.session_state.enhance_log[-40:]), language=None)
        time.sleep(0.05)

if st.session_state.enhance_log:
    st.code("\n".join(st.session_state.enhance_log), language=None)

# ── Download (upload-Modus) ───────────────────────────────────────────────────

if st.session_state.enhance_download_results:
    st.subheader("Download")
    for fname, data in st.session_state.enhance_download_results.items():
        st.download_button(
            label=f"⬇ {fname}",
            data=data,
            file_name=fname,
            mime="audio/wav",
            key=f"dl_{fname}",
        )
