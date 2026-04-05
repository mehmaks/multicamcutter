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

SCRIPT_DIR = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter"

tab_bin, tab_timeline = st.tabs(["Bin-Workflow", "Timeline-Workflow"])


# ── Shared log helpers ────────────────────────────────────────────────────────

def _run_script(cmd, log_queue):
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


def _render_log(session_key_running, session_key_lines, session_key_queue):
    if st.session_state.get(session_key_running) and session_key_queue in st.session_state:
        log_box = st.empty()
        while st.session_state[session_key_running]:
            try:
                line = st.session_state[session_key_queue].get(timeout=0.1)
                if line.startswith("__EXIT__"):
                    exit_code = int(line.replace("__EXIT__", ""))
                    st.session_state[session_key_running] = False
                    if exit_code == 0:
                        st.success("Workflow erfolgreich abgeschlossen!")
                    else:
                        st.error(f"Workflow fehlgeschlagen (Exit {exit_code})")
                    break
                st.session_state[session_key_lines].append(line)
            except queue.Empty:
                pass
            log_box.code("\n".join(st.session_state[session_key_lines][-50:]), language=None)
            time.sleep(0.05)

    if st.session_state.get(session_key_lines):
        st.code("\n".join(st.session_state[session_key_lines]), language=None)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Bin-Workflow (run_from_bin.py)
# ══════════════════════════════════════════════════════════════════════════════

with tab_bin:
    st.caption("Vollautomatisch: Bin scannen → Waveform-Sync → Analyse → Cut-Timeline")

    # ── Bin-Auswahl ───────────────────────────────────────────────────────────
    st.subheader("Bin & Output")

    try:
        from resolve_bridge.connection import get_resolve
        resolve  = get_resolve()
        project  = resolve.GetProjectManager().GetCurrentProject()
        mp       = project.GetMediaPool()

        def _collect_bins(folder, depth=0):
            bins = []
            name = folder.GetName()
            if depth > 0:
                bins.append("  " * (depth - 1) + name)
            for sf in (folder.GetSubFolderList() or []):
                bins.extend(_collect_bins(sf, depth + 1))
            return bins

        all_bins = _collect_bins(mp.GetRootFolder())
        resolve_ok = True
    except Exception:
        all_bins = []
        resolve_ok = False

    col1, col2 = st.columns(2)
    with col1:
        if all_bins:
            selected_display = st.selectbox(
                "Media Pool Bin",
                options=all_bins,
                help="Bin mit CAM (.mp4/.mov/.mxf) und MIC (.wav/.aif) Clips"
            )
            bin_name = selected_display.strip()
        else:
            bin_name = st.text_input(
                "Media Pool Bin (Name)",
                placeholder="z.B. 30 - Ebra",
                help="Resolve nicht verbunden — Namen manuell eingeben"
            )

    with col2:
        output_name_bin = st.text_input(
            "Cut-Timeline Name",
            value="Final Cut",
            help="Name der fertigen Cut-Timeline in Resolve"
        )

    st.divider()

    # ── Optionen ──────────────────────────────────────────────────────────────
    st.subheader("Optionen")

    col_a, col_b = st.columns(2)
    with col_a:
        fps_bin         = st.number_input("FPS", value=25.0, step=1.0, format="%.1f")
        skip_analysis_b = st.checkbox("Nodding-Analyse überspringen (JSONs existieren)")
    with col_b:
        sync_tl_name = st.text_input(
            "Sync-Timeline Name (optional)",
            placeholder="Standard: '<Cut-Name> Sync'",
        )
        skip_base_edl_b = st.checkbox("Base-EDL überspringen (base.edl existiert)")

    st.divider()

    # ── Start ─────────────────────────────────────────────────────────────────
    st.subheader("Workflow")

    for k, v in [("bin_running", False), ("bin_log", [])]:
        if k not in st.session_state:
            st.session_state[k] = v

    col_start, col_clear = st.columns([3, 1])
    with col_start:
        start_bin = st.button(
            "▶ Bin-Workflow starten",
            type="primary",
            disabled=st.session_state.bin_running or not bin_name,
            use_container_width=True,
        )
    with col_clear:
        if st.button("Log leeren", key="clear_bin", use_container_width=True):
            st.session_state.bin_log = []
            st.rerun()

    if start_bin:
        st.session_state.bin_running = True
        st.session_state.bin_log = []
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

        q = queue.Queue()
        threading.Thread(target=_run_script, args=(cmd, q), daemon=True).start()
        st.session_state.bin_queue = q

    _render_log("bin_running", "bin_log", "bin_queue")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Timeline-Workflow (run_from_resolve.py, manuell synchronisiert)
# ══════════════════════════════════════════════════════════════════════════════

with tab_timeline:
    st.caption("Startet aus einer bereits manuell synchronisierten Sync-Timeline in Resolve")

    # ── Timeline-Info ─────────────────────────────────────────────────────────
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
            if cam1:   track_data.append({"Spur": "V1 (CAM1)",    "Datei": cam1.clip_name,   "Offset": f"{cam1.sync_offset_frames} frames",   "Status": "✅"})
            if cam2:   track_data.append({"Spur": "V2 (CAM2)",    "Datei": cam2.clip_name,   "Offset": f"{cam2.sync_offset_frames} frames",   "Status": "✅"})
            if mic_a1: track_data.append({"Spur": "A1 (MIC→CAM2)","Datei": mic_a1.clip_name, "Offset": f"{mic_a1.sync_offset_frames} frames", "Status": "✅"})
            if mic_a2: track_data.append({"Spur": "A2 (MIC→CAM1)","Datei": mic_a2.clip_name, "Offset": f"{mic_a2.sync_offset_frames} frames", "Status": "✅"})

            st.dataframe(track_data, use_container_width=True, hide_index=True)

            if tl.warnings:
                for w in tl.warnings:
                    st.warning(w)
        else:
            st.warning("Keine Video- oder Audiospuren in der Timeline gefunden.")

    except Exception as e:
        st.error(f"Resolve nicht erreichbar: {e}")
        st.info("Resolve öffnen, Projekt laden und Sync-Timeline aktivieren.")

    st.divider()

    # ── Optionen ──────────────────────────────────────────────────────────────
    st.subheader("Optionen")

    col_a, col_b = st.columns(2)
    with col_a:
        output_name_tl  = st.text_input("Ausgabe-EDL Name", value="final_resolve.edl", key="tl_output")
        skip_analysis_t = st.checkbox("Nodding-Analyse überspringen (JSONs existieren bereits)", key="tl_skip_analysis")
        skip_base_edl_t = st.checkbox("Base-EDL überspringen (base.edl existiert bereits)", key="tl_skip_base")
    with col_b:
        import_to_resolve = st.checkbox("Fertige Timeline direkt in Resolve importieren", value=True)

    st.divider()

    # ── Start ─────────────────────────────────────────────────────────────────
    st.subheader("Workflow")

    for k, v in [("tl_running", False), ("tl_log", [])]:
        if k not in st.session_state:
            st.session_state[k] = v

    col_start2, col_clear2 = st.columns([3, 1])
    with col_start2:
        start_tl = st.button(
            "▶ Workflow starten",
            type="primary",
            disabled=st.session_state.tl_running,
            use_container_width=True,
            key="start_tl",
        )
    with col_clear2:
        if st.button("Log leeren", key="clear_tl", use_container_width=True):
            st.session_state.tl_log = []
            st.rerun()

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

    _render_log("tl_running", "tl_log", "tl_queue")
