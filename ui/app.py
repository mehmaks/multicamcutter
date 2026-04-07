"""
resolve-toolkit — Main UI
Run with: streamlit run ui/app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import queue as _queue
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

import streamlit as st

st.set_page_config(
    page_title="resolve-toolkit",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state — initialise all workflow keys before sidebar runs ───────────

_DEFAULTS = {
    "bin_running":  False, "bin_log": [], "bin_progress": 0.0,
    "bin_label": "", "bin_eta": "",
    "tl_running":   False, "tl_log":  [],
    "enhance_running": False, "enhance_log": [], "enhance_download_results": {},
    "silence_running": False, "silence_log": [], "silence_results": [],
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Progress helpers (used by sidebar log) ────────────────────────────────────

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

NODDING_RANGES = {"CAM1": (0.40, 0.57), "CAM2": (0.58, 0.76)}


def _advance_progress(line, current, steps):
    for keyword, pval, plabel in steps:
        if keyword in line and pval > current:
            return pval, plabel
    return current, None


def _parse_subprogress(line, current_progress):
    if not line.startswith("__PROGRESS__"):
        return None, None, None
    parts = line.split()
    if len(parts) < 3:
        return None, None, None
    try:
        pct, eta = float(parts[1]), parts[2]
    except ValueError:
        return None, None, None
    for cam, (start, end) in NODDING_RANGES.items():
        if start <= current_progress < end:
            return start + (pct / 100.0) * (end - start), f"Nodding {cam}: {pct:.0f}%", eta
    return None, None, None


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("resolve-toolkit")
    st.caption("Automated video editing tools")
    st.divider()

    # ── Resolve connection status ─────────────────────────────────────────────

    def _check_resolve():
        from resolve_bridge.connection import get_resolve
        resolve = get_resolve()
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        tl = project.GetCurrentTimeline() if project else None
        return (
            project.GetName() if project else None,
            tl.GetName() if tl else None,
        )

    def _run_resolve_check():
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_check_resolve)
                project_name, tl_name = future.result(timeout=2.0)
            st.session_state.resolve_status = ("ok", project_name, tl_name)
        except FuturesTimeout:
            st.session_state.resolve_status = ("timeout", None, None)
        except Exception:
            st.session_state.resolve_status = ("error", None, None)

    if "resolve_status" not in st.session_state:
        _run_resolve_check()

    status, project_name, tl_name = st.session_state.resolve_status

    st.subheader("DaVinci Resolve")
    if status == "ok":
        st.success("Verbunden")
        if project_name:
            st.caption(f"Projekt: **{project_name}**")
        if tl_name:
            st.caption(f"Timeline: **{tl_name}**")
    elif status == "timeout":
        st.warning("Antwortet nicht")
    else:
        st.error("Nicht verbunden")
        st.caption("Resolve öffnen und Projekt laden")

    if st.button("↻ Aktualisieren", use_container_width=True):
        _run_resolve_check()
        st.rerun()

    # ── Workflow Log ──────────────────────────────────────────────────────────

    st.divider()

    # Determine which workflow is active
    if st.session_state.bin_running:
        _active = "bin"
    elif st.session_state.tl_running:
        _active = "tl"
    elif st.session_state.enhance_running:
        _active = "enhance"
    elif st.session_state.silence_running:
        _active = "silence"
    else:
        _active = None

    # Find last non-empty log for display after completion
    _last_log = next(
        (st.session_state[k] for k in ("bin_log", "tl_log", "enhance_log", "silence_log")
         if st.session_state.get(k)),
        []
    )

    if _active:
        st.subheader("Workflow Log")

    if _active == "bin" and "bin_queue" in st.session_state:
        _prog_ph  = st.empty()
        _log_ph   = st.empty()
        while st.session_state.bin_running:
            try:
                _line = st.session_state.bin_queue.get(timeout=0.1)
                if _line.startswith("__EXIT__"):
                    _code = int(_line.replace("__EXIT__", ""))
                    st.session_state.bin_running = False
                    st.session_state.bin_progress = 1.0
                    st.session_state.bin_label = "Fertig!" if _code == 0 else f"Fehler (Exit {_code})"
                    st.session_state.bin_eta = ""
                    break
                _cur = st.session_state.bin_progress
                _sp, _sl, _eta = _parse_subprogress(_line, _cur)
                if _sp is not None:
                    st.session_state.bin_progress = _sp
                    st.session_state.bin_label = _sl
                    st.session_state.bin_eta = f"ETA {_eta}"
                else:
                    _np, _nl = _advance_progress(_line, _cur, BIN_STEPS)
                    st.session_state.bin_progress = _np
                    if _nl:
                        st.session_state.bin_label = _nl
                        st.session_state.bin_eta = ""
                    st.session_state.bin_log.append(_line)
            except _queue.Empty:
                pass
            with _prog_ph.container():
                st.progress(st.session_state.bin_progress)
                _lbl = st.session_state.bin_label
                _eta = st.session_state.bin_eta
                st.caption(f"**{_lbl}**{'  ' + _eta if _eta else ''}" if _lbl else "")
            _log_ph.code("\n".join(st.session_state.bin_log[-50:]), language=None)
            time.sleep(0.05)

    elif _active == "tl" and "tl_queue" in st.session_state:
        _log_ph = st.empty()
        while st.session_state.tl_running:
            try:
                _line = st.session_state.tl_queue.get(timeout=0.1)
                if _line.startswith("__EXIT__"):
                    st.session_state.tl_running = False
                    break
                st.session_state.tl_log.append(_line)
            except _queue.Empty:
                pass
            _log_ph.code("\n".join(st.session_state.tl_log[-50:]), language=None)
            time.sleep(0.05)

    elif _active == "silence" and "silence_queue" in st.session_state:
        _log_ph = st.empty()
        while st.session_state.silence_running:
            try:
                _line = st.session_state.silence_queue.get(timeout=0.1)
                if isinstance(_line, tuple) and _line[0] == "__RESULT__":
                    st.session_state.silence_results = _line[1]
                elif _line.startswith("__DONE__"):
                    st.session_state.silence_running = False
                    break
                else:
                    st.session_state.silence_log.append(_line)
            except _queue.Empty:
                pass
            _log_ph.code("\n".join(st.session_state.silence_log[-50:]), language=None)
            time.sleep(0.05)

    elif _active == "enhance" and "enhance_queue" in st.session_state:
        _log_ph = st.empty()
        while st.session_state.enhance_running:
            try:
                _line = st.session_state.enhance_queue.get(timeout=0.1)
                if _line.startswith("__DONE__"):
                    st.session_state.enhance_running = False
                    break
                st.session_state.enhance_log.append(_line)
            except _queue.Empty:
                pass
            _log_ph.code("\n".join(st.session_state.enhance_log[-50:]), language=None)
            time.sleep(0.05)

    if _last_log and not _active:
        st.subheader("Letzter Log")
        st.code("\n".join(_last_log[-30:]), language=None)
        if st.button("Log leeren", use_container_width=True, key="sidebar_clear_log"):
            for _k in ("bin_log", "tl_log", "enhance_log"):
                st.session_state[_k] = []
            st.session_state.bin_progress = 0.0
            st.session_state.bin_label = ""
            st.rerun()

    st.divider()
    st.caption("github.com/mehmaks/resolve-toolkit")

# ── Navigation ────────────────────────────────────────────────────────────────

page = st.navigation([
    st.Page("pages/multicam.py",  title="Multicam Cutter", icon="✂️"),
    st.Page("pages/enhance.py",   title="Audio Enhance",   icon="🎙️"),
    st.Page("pages/silence.py",   title="Silence Cutter",  icon="🔇"),
    st.Page("pages/resolve.py",   title="Resolve Bridge",  icon="🔗"),
    st.Page("pages/config.py",    title="Config",          icon="⚙️"),
])

page.run()
