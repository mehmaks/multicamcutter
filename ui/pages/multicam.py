"""
Multicam Cutter — UI Page
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import subprocess
import threading
import queue
import time
from pathlib import Path
from typing import Optional

st.title("✂️ Multicam Cutter")

SCRIPT_DIR = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter"

tab_bin, tab_timeline = st.tabs(["Bin-Workflow", "Timeline-Workflow"])


# ── Progress step definitions ─────────────────────────────────────────────────
# (log_keyword, progress_0_to_1, display_label)
BIN_STEPS = [
    ("Scanne Bin",               0.04, "Bin scannen..."),
    ("Waveform-Sync gestartet",  0.10, "Waveform-Sync..."),
    ("CAM1 ↔ CAM2",             0.14, "Audio-Sync: CAM1 ↔ CAM2"),
    ("CAM1 ↔ MIC",              0.22, "Audio-Sync: CAM1 ↔ MIC"),
    ("Sync abgeschlossen",       0.30, "Sync abgeschlossen"),
    ("Erstelle Sync-Timeline",   0.33, "Sync-Timeline aufbauen..."),
    ("Nodding-Analyse CAM1",     0.40, "Nodding-Analyse CAM1..."),
    ("ANALYSE ABGESCHLOSSEN",    0.57, "Nodding-Analyse fertig"),
    ("Nodding-Analyse CAM2",     0.58, "Nodding-Analyse CAM2..."),
    ("Base-EDL aus Audio",       0.76, "RMS-Diarisierung..."),
    ("Nodding-Cutaways",         0.88, "Cutaways einfügen..."),
    ("Parse finale EDL",         0.95, "Cut-Timeline aufbauen..."),
    ("Erstelle Cut-Timeline",    0.97, "Cut-Timeline aufbauen..."),
    ("Workflow abgeschlossen",   1.00, "Fertig!"),
]

# Sub-progress ranges for the two nodding analysis steps
# (step_start, step_end) in the master 0–1 space
NODDING_RANGES = {
    "CAM1": (0.40, 0.57),
    "CAM2": (0.58, 0.76),
}


# ── Shared helpers ────────────────────────────────────────────────────────────

def _run_script(cmd, log_queue):
    env = {**os.environ, 'PYTHONUNBUFFERED': '1'}
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
        env=env,
    )
    for line in process.stdout:
        log_queue.put(line.rstrip())
    process.wait()
    log_queue.put(f"__EXIT__{process.returncode}")




# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Bin-Workflow
# ══════════════════════════════════════════════════════════════════════════════

with tab_bin:
    st.caption("Vollautomatisch: Bin scannen → Waveform-Sync → Analyse → Cut-Timeline")

    st.subheader("Bin & Output")

    try:
        from resolve_bridge.connection import get_resolve
        resolve = get_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        mp      = project.GetMediaPool()

        def _collect_bins(folder, depth=0):
            bins = []
            if depth > 0:
                bins.append("  " * (depth - 1) + folder.GetName())
            for sf in (folder.GetSubFolderList() or []):
                bins.extend(_collect_bins(sf, depth + 1))
            return bins

        all_bins    = _collect_bins(mp.GetRootFolder())
        resolve_ok  = True
    except Exception:
        all_bins    = []
        resolve_ok  = False

    col1, col2 = st.columns(2)
    with col1:
        if all_bins:
            selected_display = st.selectbox(
                "Media Pool Bin",
                options=all_bins,
                help="Bin mit CAM (.mp4/.mov/.mxf) und MIC (.wav/.aif) Clips",
            )
            bin_name = selected_display.strip()
        else:
            bin_name = st.text_input(
                "Media Pool Bin (Name)",
                placeholder="z.B. 30 - Ebra",
                help="Resolve nicht verbunden — Namen manuell eingeben",
            )
    with col2:
        output_name_bin = st.text_input(
            "Cut-Timeline Name",
            value="Final Cut",
            help="Name der fertigen Cut-Timeline in Resolve",
        )

    st.divider()
    st.subheader("Optionen")

    col_a, col_b = st.columns(2)
    with col_a:
        fps_bin         = st.number_input("FPS", value=25.0, step=1.0, format="%.1f")
        skip_analysis_b = st.checkbox("Nodding-Analyse überspringen (JSONs existieren)")
        skip_base_edl_b = st.checkbox("Base-EDL überspringen (base.edl existiert)")
    with col_b:
        sync_tl_name = st.text_input(
            "Sync-Timeline Name (optional)",
            placeholder="Standard: '<Cut-Name> Sync'",
        )
        mic_names = ["MIC1 (Index 0)", "MIC2 (Index 1)"]
        mic_cam1_idx = st.selectbox(
            "MIC für CAM1",
            options=[0, 1], format_func=lambda x: mic_names[x],
            index=1,
            help="Welches Mikrofon gehört zu Kamera 1?",
        )
        mic_cam2_idx = st.selectbox(
            "MIC für CAM2",
            options=[0, 1], format_func=lambda x: mic_names[x],
            index=0,
            help="Welches Mikrofon gehört zu Kamera 2?",
        )

    st.divider()
    st.subheader("Workflow")

    start_bin = st.button(
        "▶ Bin-Workflow starten",
        type="primary",
        disabled=st.session_state.bin_running or not bin_name,
        use_container_width=True,
    )

    if start_bin:
        st.session_state.bin_running  = True
        st.session_state.bin_log      = []
        st.session_state.bin_progress = 0.0
        st.session_state.bin_label    = "Starte..."
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "run_from_bin.py"),
            "--bin",    bin_name,
            "--output", output_name_bin,
            "--fps",    str(fps_bin),
            "--config", str(SCRIPT_DIR / "config.ini"),
        ]
        if skip_analysis_b:
            cmd.append("--skip-analysis")
        if skip_base_edl_b:
            cmd.append("--skip-base-edl")
        if sync_tl_name.strip():
            cmd += ["--sync-timeline", sync_tl_name.strip()]
        cmd += ["--mic-cam1", str(mic_cam1_idx), "--mic-cam2", str(mic_cam2_idx)]

        q = queue.Queue()
        threading.Thread(target=_run_script, args=(cmd, q), daemon=True).start()
        st.session_state.bin_queue = q


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Timeline-Workflow
# ══════════════════════════════════════════════════════════════════════════════

with tab_timeline:
    st.caption("Startet aus einer bereits manuell synchronisierten Sync-Timeline in Resolve")

    st.subheader("Aktive Timeline")

    try:
        from resolve_bridge.timeline_reader import read_timeline, get_primary_wav_clip

        tl = read_timeline()

        col1, col2, col3 = st.columns(3)
        col1.metric("Timeline", tl.timeline_name)
        col2.metric("FPS", tl.fps)
        duration_min = (tl.timeline_end - tl.timeline_start) / tl.fps / 60
        col3.metric("Dauer", f"{duration_min:.1f} min")

        if tl.video_tracks and tl.audio_tracks:
            cam1   = tl.video_tracks.get(1, [None])[0]
            cam2   = tl.video_tracks.get(2, [None])[0]
            mic_a1 = get_primary_wav_clip(tl.audio_tracks.get(1, []))
            mic_a2 = get_primary_wav_clip(tl.audio_tracks.get(2, []))

            track_data = []
            if cam1:   track_data.append({"Spur": "V1 (CAM1)",     "Datei": cam1.clip_name,   "Offset": f"{cam1.sync_offset_frames} frames",   "Status": "✅"})
            if cam2:   track_data.append({"Spur": "V2 (CAM2)",     "Datei": cam2.clip_name,   "Offset": f"{cam2.sync_offset_frames} frames",   "Status": "✅"})
            if mic_a1: track_data.append({"Spur": "A1 (MIC→CAM2)", "Datei": mic_a1.clip_name, "Offset": f"{mic_a1.sync_offset_frames} frames", "Status": "✅"})
            if mic_a2: track_data.append({"Spur": "A2 (MIC→CAM1)", "Datei": mic_a2.clip_name, "Offset": f"{mic_a2.sync_offset_frames} frames", "Status": "✅"})

            st.dataframe(track_data, use_container_width=True, hide_index=True)
            for w in (tl.warnings or []):
                st.warning(w)
        else:
            st.warning("Keine Video- oder Audiospuren in der Timeline gefunden.")

    except Exception as e:
        st.error(f"Resolve nicht erreichbar: {e}")
        st.info("Resolve öffnen, Projekt laden und Sync-Timeline aktivieren.")

    st.divider()
    st.subheader("Optionen")

    col_a, col_b = st.columns(2)
    with col_a:
        output_name_tl  = st.text_input("Ausgabe-EDL Name", value="final_resolve.edl", key="tl_output")
        skip_analysis_t = st.checkbox("Nodding-Analyse überspringen", key="tl_skip_analysis")
        skip_base_edl_t = st.checkbox("Base-EDL überspringen", key="tl_skip_base")
    with col_b:
        import_to_resolve = st.checkbox("Fertige Timeline direkt in Resolve importieren", value=True)

    st.divider()
    st.subheader("Workflow")

    start_tl = st.button(
        "▶ Workflow starten",
        type="primary",
        disabled=st.session_state.tl_running,
        use_container_width=True,
        key="start_tl",
    )

    if start_tl:
        st.session_state.tl_running = True
        st.session_state.tl_log = []
        cmd = [sys.executable, str(SCRIPT_DIR / "run_from_resolve.py"),
               "--output", output_name_tl]
        if skip_analysis_t:
            cmd.append("--skip-analysis")
        if skip_base_edl_t:
            cmd.append("--skip-base-edl")
        if import_to_resolve:
            cmd.append("--import-to-resolve")

        q = queue.Queue()
        threading.Thread(target=_run_script, args=(cmd, q), daemon=True).start()
        st.session_state.tl_queue = q
