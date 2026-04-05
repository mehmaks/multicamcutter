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

st.title("✂️ Multicam Cutter")
st.caption("Automatischer EDL-Workflow aus der aktiven Resolve-Timeline")

SCRIPT_DIR = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter"
CONFIG_PATH = SCRIPT_DIR / "config.ini"

# ── Timeline-Info ─────────────────────────────────────────────────────────────

st.subheader("Timeline")

try:
    from resolve_bridge.timeline_reader import read_timeline, get_primary_wav_clip

    tl = read_timeline()

    col1, col2, col3 = st.columns(3)
    col1.metric("Timeline", tl.timeline_name)
    col2.metric("FPS", tl.fps)
    duration_min = (tl.timeline_end - tl.timeline_start) / tl.fps / 60
    col3.metric("Dauer", f"{duration_min:.1f} min")

    # Spuren anzeigen
    if tl.video_tracks and tl.audio_tracks:
        cam1 = tl.video_tracks.get(1, [None])[0]
        cam2 = tl.video_tracks.get(2, [None])[0]
        mic_a1 = get_primary_wav_clip(tl.audio_tracks.get(1, []))
        mic_a2 = get_primary_wav_clip(tl.audio_tracks.get(2, []))

        track_data = []
        if cam1: track_data.append({"Spur": "V1 (CAM1)", "Datei": cam1.clip_name, "Offset": f"{cam1.sync_offset_frames} frames", "Status": "✅"})
        if cam2: track_data.append({"Spur": "V2 (CAM2)", "Datei": cam2.clip_name, "Offset": f"{cam2.sync_offset_frames} frames", "Status": "✅"})
        if mic_a1: track_data.append({"Spur": "A1 (MIC→CAM2)", "Datei": mic_a1.clip_name, "Offset": f"{mic_a1.sync_offset_frames} frames", "Status": "✅"})
        if mic_a2: track_data.append({"Spur": "A2 (MIC→CAM1)", "Datei": mic_a2.clip_name, "Offset": f"{mic_a2.sync_offset_frames} frames", "Status": "✅"})

        st.dataframe(track_data, use_container_width=True, hide_index=True)

        if tl.warnings:
            for w in tl.warnings:
                st.warning(w)
    else:
        st.warning("Keine Video- oder Audiospuren in der Timeline gefunden.")
        st.stop()

except Exception as e:
    st.error(f"Resolve nicht erreichbar: {e}")
    st.info("Resolve öffnen, Projekt laden und Sync-Timeline aktivieren.")
    st.stop()

st.divider()

# ── Optionen ──────────────────────────────────────────────────────────────────

st.subheader("Optionen")

col_a, col_b = st.columns(2)

with col_a:
    output_name = st.text_input("Ausgabe-EDL Name", value="final_resolve.edl")
    skip_analysis = st.checkbox("Nodding-Analyse überspringen (JSONs existieren bereits)")
    skip_base_edl = st.checkbox("Base-EDL überspringen (base.edl existiert bereits)")

with col_b:
    import_to_resolve = st.checkbox("Fertige Timeline direkt in Resolve importieren", value=True)
    sensitivity = st.select_slider(
        "Nodding-Sensitivität",
        options=["low", "medium", "high"],
        value="medium"
    )

st.divider()

# ── Workflow starten ───────────────────────────────────────────────────────────

st.subheader("Workflow")

if "running" not in st.session_state:
    st.session_state.running = False
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []

def run_workflow(output_name, skip_analysis, skip_base_edl, import_to_resolve, log_queue):
    script = str(SCRIPT_DIR / "run_from_resolve.py")
    cmd = [sys.executable, script, "--output", output_name]
    if skip_analysis:
        cmd.append("--skip-analysis")
    if skip_base_edl:
        cmd.append("--skip-base-edl")
    if import_to_resolve:
        cmd.append("--import-to-resolve")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in process.stdout:
        log_queue.put(line.rstrip())
    process.wait()
    log_queue.put(f"__EXIT__{process.returncode}")

col_start, col_clear = st.columns([3, 1])

with col_start:
    start_btn = st.button(
        "▶ Workflow starten",
        type="primary",
        disabled=st.session_state.running,
        use_container_width=True,
    )

with col_clear:
    if st.button("Log leeren", use_container_width=True):
        st.session_state.log_lines = []
        st.rerun()

if start_btn:
    st.session_state.running = True
    st.session_state.log_lines = []
    log_queue = queue.Queue()
    thread = threading.Thread(
        target=run_workflow,
        args=(output_name, skip_analysis, skip_base_edl, import_to_resolve, log_queue),
        daemon=True,
    )
    thread.start()
    st.session_state.log_queue = log_queue
    st.session_state.thread = thread

# Log-Output anzeigen
if st.session_state.running and "log_queue" in st.session_state:
    log_box = st.empty()
    while st.session_state.running:
        try:
            line = st.session_state.log_queue.get(timeout=0.1)
            if line.startswith("__EXIT__"):
                exit_code = int(line.replace("__EXIT__", ""))
                st.session_state.running = False
                if exit_code == 0:
                    st.success("Workflow erfolgreich abgeschlossen!")
                else:
                    st.error(f"Workflow fehlgeschlagen (Exit {exit_code})")
                break
            st.session_state.log_lines.append(line)
        except queue.Empty:
            pass
        log_box.code("\n".join(st.session_state.log_lines[-50:]), language=None)
        time.sleep(0.05)

if st.session_state.log_lines:
    st.code("\n".join(st.session_state.log_lines), language=None)
