"""
Audio Enhance — DeepFilterNet De-Noise & De-Reverb
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
st.caption("De-Noise & De-Reverb via DeepFilterNet")

# ── DeepFilterNet availability check ──────────────────────────────────────────

try:
    from df.enhance import enhance, init_df, load_audio, save_audio
    DF_AVAILABLE = True
except ImportError:
    DF_AVAILABLE = False

if not DF_AVAILABLE:
    st.error("DeepFilterNet ist nicht installiert.")
    st.code("pip install deepfilternet", language="bash")
    st.stop()

# ── Settings ──────────────────────────────────────────────────────────────────

st.subheader("Einstellungen")
col_s1, col_s2, _ = st.columns(3)
with col_s1:
    atten_lim = st.slider(
        "Dämpfungs-Limit (dB)",
        min_value=0, max_value=40, value=0,
        help="0 = maximale Rauschreduktion · höhere Werte = sanfterer Eingriff ins Signal",
    )
with col_s2:
    pf = st.checkbox(
        "Post-Filter",
        value=False,
        help="Reduziert 'musical noise' Artefakte nach der Verarbeitung.",
    )

st.divider()

# ── File selection ─────────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}

st.subheader("Dateien auswählen")
source_mode = st.radio("Quelle", ["Resolve Media Pool", "Ordner / Dateien"], horizontal=True)

# Will be filled by one of the two modes
selected_path_files: list[tuple[str, str]] = []   # (display_name, absolute_path)
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

# ── Processing functions ───────────────────────────────────────────────────────

def _process_path_files(files: list[tuple[str, str]], atten_lim_db: int,
                        enable_pf: bool, q: queue.Queue):
    """Process files with known paths — saves *_enhanced.wav alongside originals."""
    try:
        q.put("Lade DeepFilterNet-Modell …")
        model, df_state, _ = init_df()
        q.put("Modell geladen.\n")
        for name, path_str in files:
            q.put(f"► {name}")
            audio, _ = load_audio(path_str, sr=df_state.sr())
            enhanced = enhance(model, df_state, audio,
                               atten_lim_db=atten_lim_db, enable_pf=enable_pf)
            src = Path(path_str)
            out = src.parent / (src.stem + "_enhanced" + src.suffix)
            save_audio(str(out), enhanced, df_state.sr())
            q.put(f"  ✓ {out.name}\n")
        q.put("__DONE__0")
    except Exception as e:
        q.put(f"Fehler: {e}")
        q.put("__DONE__1")


def _process_uploads(files, atten_lim_db: int, enable_pf: bool, q: queue.Queue):
    """Process uploaded file objects — results stored in session_state for download."""
    results = {}
    try:
        q.put("Lade DeepFilterNet-Modell …")
        model, df_state, _ = init_df()
        q.put("Modell geladen.\n")
        for uf in files:
            q.put(f"► {uf.name}")
            suffix = Path(uf.name).suffix or ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
                tmp_in.write(uf.read())
                tmp_in_path = tmp_in.name
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
                tmp_out_path = tmp_out.name
            try:
                audio, _ = load_audio(tmp_in_path, sr=df_state.sr())
                enhanced = enhance(model, df_state, audio,
                                   atten_lim_db=atten_lim_db, enable_pf=enable_pf)
                save_audio(tmp_out_path, enhanced, df_state.sr())
                with open(tmp_out_path, "rb") as f:
                    out_name = Path(uf.name).stem + "_enhanced.wav"
                    results[out_name] = f.read()
                q.put(f"  ✓ {out_name}\n")
            finally:
                os.unlink(tmp_in_path)
                os.unlink(tmp_out_path)
        st.session_state.enhance_download_results = results
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
can_start      = (has_path_files or has_uploads) and not st.session_state.enhance_running

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
    st.session_state.enhance_running = True
    st.session_state.enhance_log = []
    st.session_state.enhance_download_results = {}
    q = queue.Queue()
    st.session_state.enhance_queue = q
    if has_path_files:
        threading.Thread(
            target=_process_path_files,
            args=(selected_path_files, atten_lim, pf, q),
            daemon=True,
        ).start()
    else:
        threading.Thread(
            target=_process_uploads,
            args=(uploaded_files, atten_lim, pf, q),
            daemon=True,
        ).start()

# ── Log display ───────────────────────────────────────────────────────────────

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

# ── Download buttons (upload mode only) ───────────────────────────────────────

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
