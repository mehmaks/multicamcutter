"""
Multicam Cutter — UI Page
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import re
import streamlit as st
import subprocess
import threading
import queue
import time
import json
import configparser as _cp
from pathlib import Path

st.title(":material/content_cut: Multicam Cutter")
st.caption("Schneidet automatisch zwischen mehreren Kameras, basierend darauf wer gerade spricht. Das Ergebnis ist eine fertige Schnitt-Timeline.")

if "_pending_toast" in st.session_state:
    st.toast(st.session_state.pop("_pending_toast"))

SCRIPT_DIR   = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter"
_cfg_path    = SCRIPT_DIR / "config.ini"
_builtin_presets_dir = SCRIPT_DIR / "presets"
_presets_dir = Path.home() / ".resolve-toolkit" / "multicam_presets"
_presets_dir.mkdir(parents=True, exist_ok=True)

_LUT_HISTORY_FILE = Path.home() / ".resolve-toolkit" / "lut_history.json"


def _load_lut_history() -> list[str]:
    try:
        if _LUT_HISTORY_FILE.exists():
            seen: set[str] = set()
            result: list[str] = []
            for p in json.loads(_LUT_HISTORY_FILE.read_text()):
                if p not in seen and Path(p).is_file():
                    seen.add(p)
                    result.append(p)
                    if len(result) == 10:
                        break
            return result
    except Exception:
        pass
    return []


def _save_lut_to_history(new_path: str) -> None:
    history = _load_lut_history()
    if new_path in history:
        history.remove(new_path)
    history.insert(0, new_path)
    try:
        _LUT_HISTORY_FILE.parent.mkdir(exist_ok=True)
        _LUT_HISTORY_FILE.write_text(json.dumps(history[:10]))
    except Exception:
        pass

# Canonical parameter names (no prefix) — used by preset save/load
_PARAM_NAMES = [
    'min_shot', 'max_shot', 'reaction_dur', 'cleanup_dur', 'randomness',
    'threshold_db', 'min_edit', 'change_delay',
    'min_conf', 'nodding_enabled', 'nod_threshold', 'min_nod_dur', 'pre_roll',
    'speaking_enabled', 'rise_db', 'speaking_min_dur', 'speaking_max_dur', 'speaking_min_conf',
    'speaking_peak', 'totale_simul_dur',
]

_DEFAULTS: dict = {
    'min_shot':          3.0,
    'max_shot':          14.0,
    'reaction_dur':      1.8,
    'cleanup_dur':       1.8,
    'randomness':        0.2,
    'threshold_db':      6.0,
    'min_edit':          1.0,
    'change_delay':      0.3,
    'min_conf':          88,
    'nodding_enabled':   True,
    'nod_threshold':     80.0,
    'min_nod_dur':       0.65,
    'pre_roll':          15,
    'speaking_enabled':  True,
    'rise_db':           10.0,
    'speaking_min_dur':  0.20,
    'speaking_max_dur':  1.5,
    'speaking_min_conf': 90,
    'speaking_peak':     False,
    'totale_simul_dur':  3.0,
}

_resolve_ok = st.session_state.get("resolve_status", ("error",))[0] == "ok"

if _resolve_ok:
    tab_bin, tab_folder = st.tabs(["Bin-Workflow", "Ordner-Workflow"])
else:
    tab_bin  = None
    tab_folder = st.container()


# ── Workflow step definitions ─────────────────────────────────────────────────
# Each entry: (log-keyword, progress 0-1, step label, step_num, total_steps)

BIN_WORKFLOW_STEPS = [
    ("Scanne Bin",              0.04, "Bin scannen",             1, 8),
    ("Waveform-Sync gestartet", 0.08, "Waveform-Sync",           2, 8),
    ("CAM1 ↔ CAM2",            0.14, "Waveform-Sync",           2, 8),
    ("CAM1 ↔ MIC",             0.22, "Waveform-Sync",           2, 8),
    ("Sync abgeschlossen",      0.30, "Waveform-Sync",           2, 8),
    ("Erstelle Sync-Timeline",  0.34, "Sync-Timeline aufbauen",  3, 8),
    ("Base-EDL aus Audio",      0.42, "RMS-Diarisierung",        4, 8),
    ("Nodding-Analyse CAM1",    0.50, "Nodding-Analyse CAM1",    5, 8),
    ("ANALYSE ABGESCHLOSSEN",   0.65, "Nodding-Analyse CAM1",    5, 8),
    ("Nodding-Analyse CAM2",    0.66, "Nodding-Analyse CAM2",    6, 8),
    ("Nodding-Cutaways",        0.85, "Cutaways einfügen",       7, 8),
    ("Parse finale EDL",        0.93, "Cut-Timeline aufbauen",   8, 8),
    ("Erstelle Cut-Timeline",   0.96, "Cut-Timeline aufbauen",   8, 8),
    ("Workflow abgeschlossen",  1.00, "Fertig!",                 8, 8),
]

FOLDER_WORKFLOW_STEPS = [
    ("Scanne Ordner",           0.05, "Ordner scannen",          1, 6),
    ("Waveform-Sync gestartet", 0.12, "Waveform-Sync",           2, 6),
    ("CAM1 ↔ CAM2",            0.20, "Waveform-Sync",           2, 6),
    ("Sync-Offsets",            0.30, "Waveform-Sync",           2, 6),
    ("Base-EDL aus Audio",      0.40, "RMS-Diarisierung",        3, 6),
    ("Nodding-Analyse CAM1",    0.50, "Nodding-Analyse CAM1",    4, 6),
    ("ANALYSE ABGESCHLOSSEN",   0.65, "Nodding-Analyse CAM1",    4, 6),
    ("Nodding-Analyse CAM2",    0.66, "Nodding-Analyse CAM2",    5, 6),
    ("Nodding-Cutaways",        0.85, "Cutaways einfügen",       6, 6),
    ("Workflow abgeschlossen",  1.00, "Fertig!",                 6, 6),
]

# Within these progress ranges, __PROGRESS__ lines are interpolated
_NODDING_RANGES = {"CAM1": (0.50, 0.65), "CAM2": (0.66, 0.85)}


def _advance_progress_step(line, current, steps):
    for keyword, pval, label, step_num, total in steps:
        if keyword in line and pval > current:
            return pval, label, step_num, total
    return current, None, None, None


def _parse_subprogress(line, current_progress):
    # __PROGRESS__ kann nach einem \r-Balken in derselben Pipe-Zeile stehen
    idx = line.find("__PROGRESS__")
    if idx == -1:
        return None, None, None
    parts = line[idx:].split()
    if len(parts) < 3:
        return None, None, None
    try:
        pct, eta = float(parts[1]), parts[2]
    except ValueError:
        return None, None, None
    for cam, (start, end) in _NODDING_RANGES.items():
        if start <= current_progress < end:
            return start + (pct / 100.0) * (end - start), f"Nodding {cam}: {pct:.0f}%", eta
    return None, None, None


def _poll_workflow_ui(prefix, steps):
    """
    Renders a live progress bar + log for a running workflow.
    Also renders the static final state after completion.
    Blocking: enters a while loop until the workflow finishes.
    """
    running_key  = f"{prefix}_running"
    queue_key    = f"{prefix}_queue"
    progress_key = f"{prefix}_progress"
    label_key    = f"{prefix}_label"
    eta_key      = f"{prefix}_eta"
    step_key     = f"{prefix}_step"
    total_key    = f"{prefix}_total"
    log_key      = f"{prefix}_log"

    total_steps = steps[-1][4]

    _prog_ph = st.empty()
    _log_ph  = st.empty()

    def _render():
        _p    = st.session_state.get(progress_key, 0.0)
        _lbl  = st.session_state.get(label_key, "")
        _eta  = st.session_state.get(eta_key, "")
        _step = st.session_state.get(step_key, 0)
        _tot  = st.session_state.get(total_key, total_steps)
        _log  = st.session_state.get(log_key, [])
        with _prog_ph.container():
            st.progress(_p)
            _parts = []
            if _step:
                _parts.append(f"**{_step} von {_tot}**")
            if _lbl:
                _parts.append(_lbl)
            if _eta:
                _parts.append(f"ETA {_eta}")
            if _parts:
                st.caption("  ·  ".join(_parts))
        _log_ph.code("\n".join(_log[-20:]), language=None)

    if st.session_state.get(running_key) and queue_key in st.session_state:
        while st.session_state.get(running_key):
            try:
                _line = st.session_state[queue_key].get(timeout=0.1)
                if _line.startswith("__EXIT__"):
                    _code = int(_line.replace("__EXIT__", ""))
                    st.session_state[running_key]  = False
                    st.session_state[progress_key] = 1.0
                    st.session_state[label_key]    = "Fertig!" if _code == 0 else f"Fehler (Exit {_code})"
                    st.session_state[eta_key]      = ""
                    st.session_state[step_key]     = total_steps
                    st.session_state[total_key]    = total_steps
                    break
                _cur = st.session_state.get(progress_key, 0.0)
                _sp, _sl, _eta = _parse_subprogress(_line, _cur)
                if _sp is not None:
                    st.session_state[progress_key] = _sp
                    st.session_state[label_key]    = _sl
                    st.session_state[eta_key]      = _eta
                else:
                    _np, _nl, _sn, _st = _advance_progress_step(_line, _cur, steps)
                    st.session_state[progress_key] = _np
                    if _nl:
                        st.session_state[label_key] = _nl
                        st.session_state[eta_key]   = ""
                    if _sn is not None:
                        st.session_state[step_key]  = _sn
                        st.session_state[total_key] = _st
                    st.session_state[log_key].append(_line)
            except queue.Empty:
                pass
            _render()
            time.sleep(0.05)
        _render()  # final render after exit
    elif st.session_state.get(progress_key, 0.0) > 0:
        _render()  # static post-completion state


# ── Fortschritts-Modal ────────────────────────────────────────────────────────

@st.dialog("Analyse-Fortschritt", width="large")
def _workflow_dialog(prefix: str, steps: list, preview_paths: list[str]) -> None:
    """Modaler Dialog: Live-Fortschrittsbalken + Face-Mesh-Previews + Daten-Panel + Log."""
    running_key         = f"{prefix}_running"
    queue_key           = f"{prefix}_queue"
    progress_key        = f"{prefix}_progress"
    label_key           = f"{prefix}_label"
    eta_key             = f"{prefix}_eta"
    step_key            = f"{prefix}_step"
    total_key           = f"{prefix}_total"
    log_key             = f"{prefix}_log"
    sync_key            = f"{prefix}_sync_ok"
    face_stats_key      = f"{prefix}_face_stats"
    reactions_key       = f"{prefix}_reactions"
    current_cam_key     = f"{prefix}_current_cam"
    after_analysis_key  = f"{prefix}_after_analysis"
    total_steps = steps[-1][4]

    # ── Layout ───────────────────────────────────────────────────────────────
    _left_col, _right_col = st.columns([3, 2])

    _prev_slots: list = []
    with _left_col:
        if preview_paths:
            _prev_sub_cols = st.columns(len(preview_paths))
            for _pc in _prev_sub_cols:
                _prev_slots.append(_pc.empty())

    with _right_col:
        _data_ph = st.empty()

    _bar_ph = st.empty()
    _cap_ph = st.empty()
    with st.expander("Log", expanded=False):
        _log_ph = st.empty()

    # ── Log-Zeilen-Parser für Datenpanel ─────────────────────────────────────
    def _parse_log_line(line: str) -> None:
        if "Sync-Offsets" in line:
            st.session_state[sync_key] = True
        elif "FEHLER" in line and "Sync" in line:
            st.session_state[sync_key] = False

        m_cam = re.search(r'Nodding-Analyse (CAM\d+)', line)
        if m_cam:
            st.session_state[current_cam_key] = m_cam.group(1)

        if "erkannte Gesichter" in line and "∅" in line:
            _cam = st.session_state.get(current_cam_key, "CAM")
            m_b  = re.search(r'\[(.+?)\]', line)
            if m_b:
                st.session_state.setdefault(face_stats_key, {})[_cam] = m_b.group(1).strip()

        if "ANALYSE ABGESCHLOSSEN" in line:
            st.session_state[after_analysis_key] = True

        if st.session_state.get(after_analysis_key):
            m_r = re.match(r'^\s+(\w+):\s+(\d+)\s*$', line)
            if m_r:
                st.session_state.setdefault(reactions_key, {})[m_r.group(1)] = int(m_r.group(2))

        if "__REACTIONS__" in line:
            idx = line.find("__REACTIONS__")
            for part in line[idx + len("__REACTIONS__"):].strip().split():
                if ":" in part:
                    k, v = part.split(":", 1)
                    try:
                        st.session_state.setdefault(reactions_key, {})[k] = int(v)
                    except ValueError:
                        pass

    # ── Render-Funktionen ────────────────────────────────────────────────────
    def _render_previews() -> None:
        for _slot, _pp in zip(_prev_slots, preview_paths):
            if Path(_pp).exists():
                try:
                    _slot.image(str(_pp), use_container_width=True)
                except Exception:
                    pass

    def _render_data() -> None:
        with _data_ph.container():
            _sync = st.session_state.get(sync_key)
            if _sync is True:
                st.success("Sync erfolgreich")
            elif _sync is False:
                st.error("Sync fehlgeschlagen")
            else:
                st.caption(":material/hourglass_empty: Sync ausstehend...")

            _fstats = st.session_state.get(face_stats_key, {})
            if _fstats:
                st.markdown("**Gesichtserkennung**")
                for _cam, _stat in _fstats.items():
                    st.caption(f"**{_cam}:** {_stat}")

            _react = st.session_state.get(reactions_key, {})
            if _react:
                st.markdown("**Reaktionen**")
                for _rtype, _rcount in _react.items():
                    st.caption(f"{_rtype}: **{_rcount}**")

    def _render() -> None:
        _p    = st.session_state.get(progress_key, 0.0)
        _lbl  = st.session_state.get(label_key, "")
        _eta  = st.session_state.get(eta_key, "")
        _step = st.session_state.get(step_key, 0)
        _tot  = st.session_state.get(total_key, total_steps)
        _log  = st.session_state.get(log_key, [])
        _bar_ph.progress(min(1.0, max(0.0, _p)))
        _parts = []
        if _step:
            _parts.append(f"**{_step} von {_tot}**")
        if _lbl:
            _parts.append(_lbl)
        if _eta:
            _parts.append(f"ETA {_eta}")
        _cap_ph.caption("  ·  ".join(_parts) if _parts else "")
        _log_ph.code("\n".join(_log[-30:]), language=None)

    # ── Poll-Schleife ────────────────────────────────────────────────────────
    if st.session_state.get(running_key) and queue_key in st.session_state:
        while st.session_state.get(running_key):
            try:
                _line = st.session_state[queue_key].get(timeout=0.1)
                if _line.startswith("__EXIT__"):
                    _code = int(_line.replace("__EXIT__", ""))
                    st.session_state[running_key]  = False
                    st.session_state[progress_key] = 1.0
                    st.session_state[label_key]    = "Fertig!" if _code == 0 else f"Fehler (Exit {_code})"
                    st.session_state[eta_key]      = ""
                    st.session_state[step_key]     = total_steps
                    st.session_state[total_key]    = total_steps
                    break
                _cur = st.session_state.get(progress_key, 0.0)
                _sp, _sl, _eta_v = _parse_subprogress(_line, _cur)
                if _sp is not None:
                    st.session_state[progress_key] = _sp
                    st.session_state[label_key]    = _sl
                    st.session_state[eta_key]      = _eta_v
                else:
                    _np, _nl, _sn, _st = _advance_progress_step(_line, _cur, steps)
                    st.session_state[progress_key] = _np
                    if _nl:
                        st.session_state[label_key] = _nl
                        st.session_state[eta_key]   = ""
                    if _sn is not None:
                        st.session_state[step_key]  = _sn
                        st.session_state[total_key] = _st
                    # Nur sichtbare, nicht-interne Zeilen ins Log
                    if _line.strip() and "__PROGRESS__" not in _line and "__REACTIONS__" not in _line:
                        st.session_state[log_key].append(_line)
                _parse_log_line(_line)
            except queue.Empty:
                pass
            _render_previews()
            _render_data()
            _render()
            time.sleep(0.05)
        _render_data()
        _render()

    elif st.session_state.get(progress_key, 0.0) > 0:
        _render_previews()
        _render_data()
        _render()

    # ── Schließen (nach Abschluss) ───────────────────────────────────────────
    if not st.session_state.get(running_key, False):
        if st.button("Schließen", type="primary", use_container_width=True):
            for _pp in preview_paths:
                try:
                    Path(_pp).unlink(missing_ok=True)
                except Exception:
                    pass
            st.session_state[f"show_{prefix}_dialog"] = False
            st.rerun()


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


def _all_presets() -> list[tuple[str, Path, bool]]:
    """Gibt alle Presets zurück als (name, path, is_builtin), alphabetisch sortiert.
    Built-ins zuerst, dann User-Presets. Namenskonflikte: User-Preset gewinnt."""
    entries: dict[str, tuple[Path, bool]] = {}
    for p in sorted(_builtin_presets_dir.glob("*.json")):
        entries[p.stem] = (p, True)
    for p in sorted(_presets_dir.glob("*.json")):
        entries[p.stem] = (p, False)
    user    = sorted([(n, p, bi) for n, (p, bi) in entries.items() if not bi], key=lambda x: x[0].lower())
    builtin = sorted([(n, p, bi) for n, (p, bi) in entries.items() if bi],     key=lambda x: x[0].lower())
    return user + builtin


def _on_preset_change(prefix: str) -> None:
    """on_change-Callback: ausgewähltes Preset als Pending laden."""
    sel = st.session_state.get(f"{prefix}_preset_select")
    if not sel:
        return
    preset_file = _presets_dir / f"{sel}.json"
    if not preset_file.exists():
        preset_file = _builtin_presets_dir / f"{sel}.json"
    if not preset_file.exists():
        return
    pdata = json.loads(preset_file.read_text())
    pending = {}
    for name, val in pdata.items():
        bare = name[2:] if (name.startswith('s_') or name.startswith('f_')) else name
        if bare in _PARAM_NAMES:
            pending[bare] = val
    st.session_state[f"_preset_pending_{prefix}"] = pending


@st.dialog("Preset überschreiben?")
def _confirm_overwrite_preset_dialog() -> None:
    prefix = st.session_state.get("_overwrite_preset_prefix", "")
    name   = st.session_state.get("_overwrite_preset_name", "")
    safe   = st.session_state.get("_overwrite_preset_safe", "")
    st.write(f"Ein Preset mit dem Namen **{name}** existiert bereits. Überschreiben?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Überschreiben", type="primary", icon=":material/save:",
                     use_container_width=True):
            pdata = {n: st.session_state[f"{prefix}_{n}"]
                     for n in _PARAM_NAMES if f"{prefix}_{n}" in st.session_state}
            (_presets_dir / f"{safe}.json").write_text(json.dumps(pdata, indent=2))
            for k in ("_overwrite_preset_prefix", "_overwrite_preset_name", "_overwrite_preset_safe"):
                st.session_state.pop(k, None)
            st.session_state["_clear_preset_name"] = prefix
            st.session_state["_pending_toast"] = f"Preset '{safe}' aktualisiert"
            st.rerun()
    with c2:
        if st.button("Abbrechen", use_container_width=True):
            for k in ("_overwrite_preset_prefix", "_overwrite_preset_name", "_overwrite_preset_safe"):
                st.session_state.pop(k, None)
            st.rerun()


@st.dialog("Preset löschen")
def _confirm_delete_preset_dialog() -> None:
    prefix = st.session_state.get("_del_preset_prefix", "")
    name   = st.session_state.get("_del_preset_name", "")
    st.write(f"Preset **{name}** wirklich löschen?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Löschen", type="primary", icon=":material/delete:",
                     use_container_width=True):
            (_presets_dir / f"{name}.json").unlink(missing_ok=True)
            st.session_state.pop(f"{prefix}_preset_select", None)
            st.session_state.pop("_del_preset_prefix", None)
            st.session_state.pop("_del_preset_name", None)
            st.rerun()
    with c2:
        if st.button("Abbrechen", use_container_width=True):
            st.session_state.pop("_del_preset_prefix", None)
            st.session_state.pop("_del_preset_name", None)
            st.rerun()


def _render_preset_row(prefix: str) -> None:
    """Preset-Selectbox (auto-load bei Auswahl) + Delete-Button in einer Zeile."""
    presets = _all_presets()
    if not presets:
        st.caption("Noch keine Presets gespeichert")
        return
    preset_names  = [name for name, _, _ in presets]
    builtin_names = {name for name, _, bi in presets if bi}

    col_sel, col_del = st.columns([5, 1])
    with col_sel:
        st.selectbox(
            "Preset",
            preset_names,
            format_func=lambda n: f"{n}  ◆" if n in builtin_names else n,
            key=f"{prefix}_preset_select",
            on_change=_on_preset_change,
            args=(prefix,),
        )
        if builtin_names:
            st.caption("◆ Mitgelieferte Vorlage — kann nicht gelöscht werden")
    with col_del:
        st.markdown("<div style='margin-top:1.85rem'></div>", unsafe_allow_html=True)
        sel        = st.session_state.get(f"{prefix}_preset_select")
        is_builtin = sel in builtin_names
        if st.button("", icon=":material/delete:", key=f"{prefix}_btn_del_preset",
                     use_container_width=True, help="Preset löschen",
                     disabled=not sel or is_builtin):
            st.session_state["_del_preset_prefix"] = prefix
            st.session_state["_del_preset_name"]   = sel

    if st.session_state.get("_del_preset_prefix") == prefix:
        _confirm_delete_preset_dialog()


def _render_preset_expander(prefix: str) -> None:
    """Preset speichern."""
    if st.session_state.get("_clear_preset_name") == prefix:
        st.session_state.pop("_clear_preset_name")
        st.session_state[f"{prefix}_preset_name_input"] = ""
    with st.expander("Preset speichern"):
        ni1, ni2 = st.columns([3, 1])
        with ni1:
            new_name = st.text_input(
                "Name", placeholder="z.B. Standard Podcast",
                key=f"{prefix}_preset_name_input",
            )
        with ni2:
            st.markdown("<div style='margin-top:1.85rem'></div>", unsafe_allow_html=True)
            if st.button("", icon=":material/save:", key=f"{prefix}_btn_save_preset",
                         disabled=not (new_name or '').strip(),
                         use_container_width=True, help="Aktuelle Einstellungen als Preset speichern"):
                safe  = new_name.strip().replace('/', '_').replace('\\', '_')
                _name_lower = safe.lower()
                # Case-insensitive Duplikatprüfung über alle bekannten Presets
                _builtin_names = {p.stem.lower() for p in _builtin_presets_dir.glob("*.json")}
                _user_names    = {p.stem.lower(): p.stem for p in _presets_dir.glob("*.json")}
                if _name_lower in _builtin_names:
                    st.toast(f"'{safe}' ist eine mitgelieferte Vorlage und kann nicht überschrieben werden.")
                elif _name_lower in _user_names:
                    st.session_state["_overwrite_preset_prefix"] = prefix
                    st.session_state["_overwrite_preset_name"]   = _user_names[_name_lower]
                    st.session_state["_overwrite_preset_safe"]   = safe
                else:
                    pdata = {n: st.session_state[f"{prefix}_{n}"]
                             for n in _PARAM_NAMES if f"{prefix}_{n}" in st.session_state}
                    (_presets_dir / f"{safe}.json").write_text(json.dumps(pdata, indent=2))
                    st.session_state["_clear_preset_name"] = prefix
                    st.session_state["_pending_toast"] = f"Preset '{safe}' gespeichert"
                    st.rerun()


def _render_settings_panel(prefix):
    """Render 4 settings expanders with widget keys prefixed by `prefix`."""
    D = _DEFAULTS

    with st.expander("Generelle Schnittregeln", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.number_input("Min. Shotlänge (s)", value=D['min_shot'],
                min_value=0.5, step=0.1, format="%.1f", key=f"{prefix}_min_shot",
                help="Wie lange eine Kamera mindestens zu sehen ist, bevor zu einer Reaktion geschnitten werden darf.")
            st.number_input("Max. Shotlänge (s)", value=D['max_shot'],
                min_value=1.0, step=0.5, format="%.1f", key=f"{prefix}_max_shot",
                help="Bleibt eine Kamera länger als dieser Wert ohne Schnitt, wird automatisch zu einer Reaktion gewechselt.")
        with c2:
            st.number_input("Cutaway-Länge (s)", value=D['reaction_dur'],
                min_value=0.5, step=0.1, format="%.1f", key=f"{prefix}_reaction_dur",
                help="Wie lange eine Reaktionsaufnahme mindestens gezeigt wird. Mit Zufallsfaktor kann sie etwas länger ausfallen.")
            st.number_input("Cleanup-Mindestlänge (s)", value=D['cleanup_dur'],
                min_value=0.1, step=0.1, format="%.1f", key=f"{prefix}_cleanup_dur",
                help="Schnitte kürzer als dieser Wert werden am Ende automatisch entfernt.")
        st.slider("Cutaway-Zufallsfaktor", 0.0, 0.5, D['randomness'],
            step=0.05, key=f"{prefix}_randomness",
            help="Wie stark die Länge der Reaktionsaufnahmen variieren darf. Höhere Werte machen den Schnitt weniger maschinell.")

    with st.expander("Sprecher-Erkennung"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("Schwelle (dB)", value=D['threshold_db'],
                min_value=0.5, step=0.5, format="%.1f", key=f"{prefix}_threshold_db",
                help="Wie deutlich lauter jemand sein muss als der andere, damit ein Sprecherwechsel erkannt wird. Höhere Werte schneiden nur bei klarer Dominanz.")
        with c2:
            st.number_input("Min. Segmentlänge (s)", value=D['min_edit'],
                min_value=0.1, step=0.1, format="%.1f", key=f"{prefix}_min_edit",
                help="Sehr kurze Sprechabschnitte werden mit dem nächsten zusammengelegt. Verhindert zu häufiges Hin- und Herschneiden.")
        with c3:
            st.number_input("Wechsel-Verzögerung (s)", value=D['change_delay'],
                min_value=0.0, step=0.05, format="%.2f", key=f"{prefix}_change_delay",
                help="Wie lange jemand durchgehend lauter sein muss, bevor auf ihn geschnitten wird. Verhindert Schnitte bei kurzen Überschneidungen.")

    with st.expander("Cutaway Regeln"):
        # ── Kopfnicken ────────────────────────────────────────────────────────
        st.toggle("Kopfnicken", value=D['nodding_enabled'],
            key=f"{prefix}_nodding_enabled",
            help="Erkennt Kopfnicken der zuhörenden Person und schneidet in diesem Moment auf sie.")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.number_input("Min. Konfidenz (%)", value=D['min_conf'],
                min_value=0, max_value=100, step=1, format="%d", key=f"{prefix}_min_conf",
                help="Wie sicher die Erkennung sein muss, bevor ein Nicken als Schnitt verwendet wird. Höhere Werte vermeiden Fehlschnitte, erkennen dafür weniger Nicken.")
        with c2:
            st.number_input("Nod-Threshold (px)", value=D['nod_threshold'],
                min_value=1.0, step=1.0, format="%.0f", key=f"{prefix}_nod_threshold",
                help="Wie weit sich der Kopf bewegen muss, damit es als Nicken zählt. Kleinere Werte erkennen auch dezentes Nicken.")
        with c3:
            st.number_input("Min. Nod-Dauer (s)", value=D['min_nod_dur'],
                min_value=0.1, step=0.05, format="%.2f", key=f"{prefix}_min_nod_dur",
                help="Wie lang die Kopfbewegung andauern muss, um als echtes Nicken zu gelten. Höhere Werte ignorieren kurze zufällige Bewegungen.")
        with c4:
            st.number_input("Pre-Roll (Frames)", value=D['pre_roll'],
                min_value=0, step=1, key=f"{prefix}_pre_roll",
                help="Der Schnitt wird um diese Anzahl Bilder früher gesetzt, damit die Reaktion natürlicher wirkt.")
        with c5:
            st.toggle("Auto Accuracy", value=True, key=f"{prefix}_auto_accuracy",
                help="Passt die Empfindlichkeit automatisch an, je nachdem wie groß das Gesicht im Bild ist. Sinnvoll wenn Personen unterschiedlich nah an der Kamera sitzen.")

        st.divider()

        # ── Sprachreaktionen ──────────────────────────────────────────────────
        st.toggle("Sprachreaktionen", value=D['speaking_enabled'],
            key=f"{prefix}_speaking_enabled",
            help="Erkennt kurze Einwürfe oder Laute der nicht aktiv sprechenden Person und schneidet in diesem Moment auf sie.")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.number_input("Rise (dB über Baseline)", value=D['rise_db'],
                min_value=1.0, step=0.5, format="%.1f", key=f"{prefix}_rise_db",
                help="Wie deutlich lauter jemand kurz werden muss, um als Reaktion erkannt zu werden. Höhere Werte reagieren nur auf klare Einwürfe wie 'Genau!' oder Lachen.")
        with c2:
            st.number_input("Min. Burst-Dauer (s)", value=D['speaking_min_dur'],
                min_value=0.05, step=0.05, format="%.2f", key=f"{prefix}_speaking_min_dur",
                help="Wie kurz ein Einwurf mindestens sein muss, um erkannt zu werden. Kleinere Werte erfassen auch sehr kurze Laute wie 'Mhm'.")
        with c3:
            st.number_input("Max. Burst-Dauer (s)", value=D['speaking_max_dur'],
                min_value=0.1, step=0.1, format="%.1f", key=f"{prefix}_speaking_max_dur",
                help="Wie lang ein Einwurf maximal sein darf. Längere Töne werden als normales Sprechen gewertet, nicht als Reaktion.")
        with c4:
            st.number_input("Min. Konfidenz (%)", value=D['speaking_min_conf'],
                min_value=0, max_value=100, step=1, format="%d", key=f"{prefix}_speaking_min_conf",
                help="Wie sicher die Erkennung sein muss, bevor ein Einwurf als Schnitt verwendet wird.")
        with c5:
            st.toggle("Peak-Detektion", value=D['speaking_peak'], key=f"{prefix}_speaking_peak",
                help="Reagiert auf den lautesten Moment statt auf den Durchschnittspegel. Empfehlenswert für sehr kurze, knackige Einwürfe.")

    with st.expander("Totale-Cam Schnittlogik"):
        c1, c2 = st.columns(2)
        with c1:
            st.number_input(
                "Min. Simultandauer (s)",
                value=D['totale_simul_dur'],
                min_value=0.5, step=0.5, format="%.1f",
                key=f"{prefix}_totale_simul_dur",
                help="Wie lange beide gleichzeitig sprechen müssen, bevor auf die Totale geschnitten wird.",
            )
        with c2:
            st.caption(
                "Greift nur wenn ein Clip als **Totale** markiert ist. "
                "Erkennt Phasen wo beide Mics gleichzeitig aktiv sind "
                "(kein klarer Dominanzunterschied) und schneidet auf die Totale."
            )


def _collect_settings(prefix):
    """Read current widget values for the given prefix from session_state."""
    p = f"{prefix}_"
    return {
        'min_shot':          st.session_state.get(f"{p}min_shot", 3.0),
        'max_shot':          st.session_state.get(f"{p}max_shot", 14.0),
        'reaction_dur':      st.session_state.get(f"{p}reaction_dur", 1.8),
        'cleanup_dur':       st.session_state.get(f"{p}cleanup_dur", 1.8),
        'randomness':        st.session_state.get(f"{p}randomness", 0.2),
        'threshold_db':      st.session_state.get(f"{p}threshold_db", 6.0),
        'min_edit':          st.session_state.get(f"{p}min_edit", 1.0),
        'change_delay':      st.session_state.get(f"{p}change_delay", 0.3),
        'min_conf':          st.session_state.get(f"{p}min_conf", 88) / 100,
        'nodding_enabled':   st.session_state.get(f"{p}nodding_enabled", True),
        'nod_threshold':     st.session_state.get(f"{p}nod_threshold", 80.0),
        'min_nod_dur':       st.session_state.get(f"{p}min_nod_dur", 0.65),
        'pre_roll':          st.session_state.get(f"{p}pre_roll", 15),
        'speaking_enabled':  st.session_state.get(f"{p}speaking_enabled", True),
        'rise_db':           st.session_state.get(f"{p}rise_db", 10.0),
        'speaking_min_dur':  st.session_state.get(f"{p}speaking_min_dur", 0.20),
        'speaking_max_dur':  st.session_state.get(f"{p}speaking_max_dur", 1.5),
        'speaking_min_conf': st.session_state.get(f"{p}speaking_min_conf", 90) / 100,
        'totale_simul_dur':  st.session_state.get(f"{p}totale_simul_dur", 3.0),
    }


def _save_settings_to_config(v):
    """Persist settings dict to config.ini."""
    save = _cp.ConfigParser()
    save.read(str(_cfg_path))
    for sec, key, val in [
        ('General',          'min_shot_duration',    v['min_shot']),
        ('General',          'reaction_min_duration', v['reaction_dur']),
        ('General',          'max_shot_duration',    v['max_shot']),
        ('General',          'cleanup_min_duration', v['cleanup_dur']),
        ('General',          'cutaway_randomness',   v['randomness']),
        ('RMSDiarization',   'threshold_db',         v['threshold_db']),
        ('RMSDiarization',   'min_edit_duration',    v['min_edit']),
        ('RMSDiarization',   'change_delay',         v['change_delay']),
        ('Detection',        'min_confidence',       v['min_conf']),
        ('Nodding',          'threshold',             v['nod_threshold']),
        ('Nodding',          'min_nod_duration',     v['min_nod_dur']),
        ('CutawayTiming',    'pre_roll_frames',      v['pre_roll']),
        ('SpeakingReaction', 'rise_db',              v['rise_db']),
        ('SpeakingReaction', 'min_duration',         v['speaking_min_dur']),
        ('SpeakingReaction', 'max_duration',         v['speaking_max_dur']),
        ('SpeakingReaction', 'min_confidence',       v['speaking_min_conf']),
        ('TotaleLogic',      'simul_min_duration',   v['totale_simul_dur']),
    ]:
        if sec not in save:
            save[sec] = {}
        save[sec][key] = str(val)
    save['Nodding']['enabled'] = 'true' if v['nodding_enabled'] else 'false'
    save['SpeakingReaction']['enabled'] = 'true' if v['speaking_enabled'] else 'false'
    with open(str(_cfg_path), 'w') as f:
        save.write(f)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Bin-Workflow (nur wenn Resolve verbunden)
# ══════════════════════════════════════════════════════════════════════════════

if tab_bin is not None:
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
        current_bin = mp.GetCurrentFolder().GetName()
        resolve_ok  = True
    except Exception:
        all_bins    = []
        current_bin = None
        resolve_ok  = False

    col1, col2 = st.columns(2)
    with col1:
        if all_bins:
            default_idx = 0
            if current_bin:
                for i, b in enumerate(all_bins):
                    if b.strip() == current_bin:
                        default_idx = i
                        break
            selected_display = st.selectbox(
                "Media Pool Bin",
                options=all_bins,
                index=default_idx,
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

    _VIDEO_EXT = {'.mp4', '.mov', '.mxf', '.r3d', '.ari'}
    _AUDIO_EXT = {'.wav', '.aif', '.aiff'}

    cam_labels = ["CAM1", "CAM2"]
    mic_labels = []

    if resolve_ok and bin_name:
        _cache_key = f"_bin_clips_{bin_name}"
        if _cache_key not in st.session_state:
            def _find_bin_folder(folder, name):
                if folder.GetName() == name:
                    return folder
                for sf in (folder.GetSubFolderList() or []):
                    r = _find_bin_folder(sf, name)
                    if r:
                        return r
                return None
            found = _find_bin_folder(mp.GetRootFolder(), bin_name)
            if found:
                _clips = found.GetClipList() or []
                _cams = sorted([
                    c.GetName() for c in _clips
                    if 'Video' in (c.GetClipProperty('Type') or '')
                ])
                _mics = sorted([
                    c.GetName() for c in _clips
                    if 'Audio' in (c.GetClipProperty('Type') or '')
                    and 'Video' not in (c.GetClipProperty('Type') or '')
                ])
                st.session_state[_cache_key] = (_cams, _mics)
            else:
                st.session_state[_cache_key] = ([], [])

        _scanned_cams, _scanned_mics = st.session_state[_cache_key]
        if len(_scanned_cams) >= 2:
            cam_labels = [Path(_scanned_cams[0]).stem, Path(_scanned_cams[1]).stem]
        mic_labels  = [Path(m).stem for m in _scanned_mics]

    _n_mics      = max(2, len(mic_labels))
    _mic_options = list(range(_n_mics))

    def _mic_name(idx):
        return mic_labels[idx] if idx < len(mic_labels) else f"MIC{idx + 1}"

    col_a, col_b = st.columns(2)
    with col_a:
        fps_bin               = st.number_input("FPS", value=25.0, step=1.0, format="%.1f")
        skip_analysis_b       = st.toggle("Nodding-Analyse überspringen (JSONs existieren)")
        skip_base_edl_b       = st.toggle("Base-EDL überspringen (base.edl existiert)")
    with col_b:
        sync_tl_name = st.text_input(
            "Sync-Timeline Name (optional)",
            placeholder="Standard: '<Cut-Name> Sync'",
        )
        mic_cam1_idx = st.selectbox(
            f"MIC für {cam_labels[0]}",
            options=_mic_options,
            format_func=_mic_name,
            index=min(1, _n_mics - 1),
            help="Welches Mikrofon gehört zu Kamera 1?",
        )
        mic_cam2_idx = st.selectbox(
            f"MIC für {cam_labels[1]}",
            options=_mic_options,
            format_func=_mic_name,
            index=0,
            help="Welches Mikrofon gehört zu Kamera 2?",
        )

    # ── Analyse-Einstellungen ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Analyse-Einstellungen")

    _render_preset_row('s')
    st.divider()
    if "s_min_shot" not in st.session_state and "_preset_pending_s" not in st.session_state:
        _on_preset_change('s')
    if "_preset_pending_s" in st.session_state:
        for _bare, _val in st.session_state.pop("_preset_pending_s").items():
            st.session_state[f"s_{_bare}"] = _val
    _render_settings_panel('s')
    _render_preset_expander('s')
    if st.session_state.get("_overwrite_preset_prefix") == 's':
        _confirm_overwrite_preset_dialog()

    st.divider()
    st.subheader("Workflow")

    start_bin = st.button(
        "Bin-Workflow starten", icon=":material/play_arrow:",
        type="primary",
        disabled=st.session_state.bin_running or not bin_name,
        use_container_width=True,
    )

    if start_bin:
        _v = _collect_settings('s')
        _save_settings_to_config(_v)

        st.session_state.bin_running  = True
        st.session_state.bin_log      = []
        st.session_state.bin_progress = 0.0
        st.session_state.bin_label    = "Starte..."
        st.session_state.bin_step     = 0
        st.session_state.bin_total    = BIN_WORKFLOW_STEPS[-1][4]
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
        if st.session_state.get("s_speaking_peak", False):
            cmd += ["--speaking-mode", "peak"]
        if st.session_state.get("s_auto_accuracy", False):
            cmd.append("--auto-accuracy")

        n_bin_cams = len(_scanned_cams) if '_scanned_cams' in dir() else 2
        st.session_state.bin_preview_paths = [
            f"/tmp/multicam_preview_cam{i + 1}.jpg" for i in range(n_bin_cams)
        ]
        st.session_state.show_bin_dialog = True
        q = queue.Queue()
        threading.Thread(target=_run_script, args=(cmd, q), daemon=True).start()
        st.session_state.bin_queue = q
        st.rerun()

    if st.session_state.get("show_bin_dialog"):
        _workflow_dialog("bin", BIN_WORKFLOW_STEPS,
                         st.session_state.get("bin_preview_paths", []))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Ordner-Workflow  (Hilfs-Funktionen)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False, ttl=300)
def _get_video_thumbnail(video_path_str: str, lut_path_str: str = "") -> bytes | None:
    """Extrahiert den ersten Frame eines Videos als JPEG-Bytes via ffmpeg.
    Wenn lut_path_str gesetzt ist, wird die CUBE-LUT per lut3d-Filter angewendet."""
    try:
        import subprocess as _sp
        _vf = ["-vf", f"lut3d='{lut_path_str}'"] if (lut_path_str and Path(lut_path_str).is_file()) else []
        r = _sp.run(
            ["ffmpeg", "-i", video_path_str] + _vf + ["-vframes", "1",
             "-f", "image2", "-vcodec", "mjpeg", "pipe:1", "-loglevel", "quiet"],
            capture_output=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except Exception:
        pass
    return None


@st.cache_data(show_spinner=False, ttl=300)
def _get_video_fps(video_path_str: str) -> float | None:
    """Liest die Framerate eines Videos via ffprobe aus."""
    try:
        import subprocess as _sp, json as _json
        r = _sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v:0", video_path_str],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            streams = _json.loads(r.stdout).get("streams", [])
            if streams:
                rfr = streams[0].get("r_frame_rate", "")
                if rfr and "/" in rfr:
                    num, den = rfr.split("/")
                    return round(int(num) / int(den), 6)
    except Exception:
        pass
    return None


def _fmt_fps(fps: float) -> str:
    """Formatiert eine Framerate leserlich: 25.0 → '25', 29.97002 → '29.97'."""
    if fps % 1 == 0:
        return f"{fps:.0f}"
    return f"{fps:.3f}".rstrip("0").rstrip(".")


@st.cache_data(show_spinner=False, ttl=300)
def _get_audio_waveform(audio_path_str: str) -> bytes | None:
    """Rendert die Waveform einer Audiodatei als PNG-Bytes via matplotlib."""
    try:
        import io
        import numpy as np
        import soundfile as sf
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        data, _sr = sf.read(audio_path_str, always_2d=True)
        mono = data.mean(axis=1)
        step = max(1, len(mono) // 1000)
        mono = mono[::step]

        fig, ax = plt.subplots(figsize=(3, 0.9))
        fig.patch.set_facecolor('#3d4052')
        ax.set_facecolor('#3d4052')
        ax.fill_between(range(len(mono)), mono, color='#4CAF50', alpha=0.85, linewidth=0)
        ax.axhline(0, color='#4CAF50', linewidth=0.4, alpha=0.5)
        ax.set_xlim(0, max(len(mono) - 1, 1))
        ax.axis('off')
        plt.tight_layout(pad=0.1)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=72, bbox_inches='tight',
                    facecolor='#3d4052')
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Ordner-Workflow
# ══════════════════════════════════════════════════════════════════════════════

with tab_folder:
    st.caption("Resolve-frei: Ordner mit CAM- und MIC-Dateien → final.edl")

    st.subheader("Ordner & Dateien")

    # Picked-Pfad vor Widget-Rendering übernehmen (Streamlit erlaubt kein
    # Setzen eines Widget-Keys nach der Widget-Instanziierung)
    if "_folder_path_pending" in st.session_state:
        st.session_state.folder_path_sel = st.session_state.pop("_folder_path_pending")

    if "folder_path_sel" not in st.session_state:
        st.session_state.folder_path_sel = ""

    _col_path, _col_btn = st.columns([5, 1])
    with _col_path:
        folder_path = st.text_input(
            "Ordner-Pfad",
            placeholder="/Pfad/zur/Episode",
            help="Ordner mit genau 2 Videodateien (.mp4/.mov/.mxf) und 1–2 Audiodateien (.wav/.aif)",
            key="folder_path_sel",
        )
    with _col_btn:
        st.markdown("<div style='margin-top:1.85rem'></div>", unsafe_allow_html=True)
        if st.button("", icon=":material/folder_open:", use_container_width=True, help="Ordner auswählen"):
            _picked = None
            try:
                import subprocess as _subp
                _r = _subp.run(
                    ["osascript", "-e",
                     'POSIX path of (choose folder with prompt "Ordner auswählen")'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    _picked = _r.stdout.strip()
            except Exception:
                st.warning("Ordner-Dialog nicht verfügbar — Pfad bitte manuell eingeben.")
            if _picked:
                st.session_state["_folder_path_pending"] = _picked
                st.rerun()

    _folder_valid = bool(folder_path and Path(folder_path).is_dir())

    if _folder_valid:
        _fld = Path(folder_path)
        _VIDEO_EXT_F = {'.mp4', '.mov', '.mxf', '.r3d', '.ari'}
        _AUDIO_EXT_F = {'.wav', '.aif', '.aiff'}
        _all = sorted(f for f in _fld.iterdir() if f.is_file())
        _f_cams = [f for f in _all if f.suffix.lower() in _VIDEO_EXT_F]
        _f_mics = [f for f in _all if f.suffix.lower() in _AUDIO_EXT_F]

        if len(_f_cams) < 2:
            st.error(f"Mindestens 2 Videodateien erwartet, {len(_f_cams)} gefunden.")
        elif not _f_mics:
            st.error("Keine Audiodateien (.wav/.aif) gefunden.")
        else:
            _default_roles = (
                ["Cam 1", "Cam 2"] + ["Totale"] * max(0, len(_f_cams) - 2)
            )

            _cam_role_options = [f"Cam {i + 1}" for i in range(len(_f_cams))] + ["Totale"]

            st.markdown("**Kamera-Clips**")
            _n_cam_cols = min(len(_f_cams), 4)
            _cam_tile_cols = st.columns(_n_cam_cols)
            _detected_fps: list[float | None] = []
            for _ci, _cf in enumerate(_f_cams):
                with _cam_tile_cols[_ci % _n_cam_cols]:
                    _thumb_slot = st.empty()
                    with st.spinner(""):
                        _lut_path = st.session_state.get("f_lut_path", "")
                        _thumb = _get_video_thumbnail(str(_cf), _lut_path)
                        _fps_val = _get_video_fps(str(_cf))
                    _detected_fps.append(_fps_val)
                    if _thumb:
                        _thumb_slot.image(_thumb, use_container_width=True)
                    else:
                        _thumb_slot.markdown("▷")
                    _fps_label = f" · {_fmt_fps(_fps_val)} fps" if _fps_val else ""
                    st.caption(f"{_cf.name}{_fps_label}")
                    if f"f_cam_role_{_ci}" not in st.session_state:
                        st.session_state[f"f_cam_role_{_ci}"] = _default_roles[_ci]
                    # Validate stored value is still in current options (e.g. after folder change)
                    if st.session_state.get(f"f_cam_role_{_ci}") not in _cam_role_options:
                        st.session_state[f"f_cam_role_{_ci}"] = _default_roles[_ci]
                    st.selectbox(
                        "Rolle",
                        options=_cam_role_options,
                        key=f"f_cam_role_{_ci}",
                        label_visibility="collapsed",
                    )

            # ── FPS-Konsistenzcheck + Auto-Fill ──────────────────────────────
            _valid_fps = [f for f in _detected_fps if f is not None]
            _unique_fps = sorted(set(round(f, 3) for f in _valid_fps))
            if len(_unique_fps) > 1:
                st.warning(
                    f"Clips haben unterschiedliche Frameraten: "
                    + ", ".join(_fmt_fps(f) for f in _unique_fps)
                    + " — bitte FPS-Einstellung manuell überprüfen."
                )
            # Nur bei Ordnerwechsel automatisch befüllen (User-Override bleibt erhalten)
            if _valid_fps and st.session_state.get("_f_fps_last_folder") != folder_path:
                st.session_state["f_fps"] = _valid_fps[0]
                st.session_state["_f_fps_last_folder"] = folder_path

            st.markdown("**Mikrofon-Clips**")
            _close_cam_labels = [
                st.session_state.get(f"f_cam_role_{_ci}", _default_roles[_ci])
                for _ci in range(len(_f_cams))
                if st.session_state.get(f"f_cam_role_{_ci}", _default_roles[_ci]) != "Totale"
            ]
            if not _close_cam_labels:
                _close_cam_labels = ["Cam 1"]

            _n_mic_cols = min(len(_f_mics), 4)
            _mic_tile_cols = st.columns(_n_mic_cols)
            for _mi, _mf in enumerate(_f_mics):
                with _mic_tile_cols[_mi % _n_mic_cols]:
                    _wf_slot = st.empty()
                    with st.spinner(""):
                        _wf = _get_audio_waveform(str(_mf))
                    if _wf:
                        _wf_slot.image(_wf, use_container_width=True)
                    else:
                        _wf_slot.markdown("🎙️")
                    st.caption(_mf.name)
                    _mic_default = _close_cam_labels[min(_mi, len(_close_cam_labels) - 1)]
                    if f"f_mic_assign_{_mi}" not in st.session_state:
                        st.session_state[f"f_mic_assign_{_mi}"] = _mic_default
                    if st.session_state.get(f"f_mic_assign_{_mi}") not in _close_cam_labels:
                        st.session_state[f"f_mic_assign_{_mi}"] = _mic_default
                    st.selectbox(
                        "Zuordnung",
                        options=_close_cam_labels,
                        key=f"f_mic_assign_{_mi}",
                        label_visibility="collapsed",
                    )
    elif folder_path:
        st.error("Ordner nicht gefunden.")

    # ── Analyse-Einstellungen ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Analyse-Einstellungen")

    _render_preset_row('f')
    st.divider()
    if "f_min_shot" not in st.session_state and "_preset_pending_f" not in st.session_state:
        _on_preset_change('f')
    if "_preset_pending_f" in st.session_state:
        for _bare, _val in st.session_state.pop("_preset_pending_f").items():
            st.session_state[f"f_{_bare}"] = _val
    _render_settings_panel('f')
    with st.expander("Andere Einstellungen"):
        fps_folder           = st.number_input("FPS", value=25.0, step=1.0, format="%.1f", key="f_fps")
        skip_analysis_f      = st.toggle("Nodding-Analyse überspringen (JSONs existieren)", key="f_skip_analysis")
        skip_base_edl_f      = st.toggle("Base-EDL überspringen (base.edl existiert)", key="f_skip_base_edl")

        st.divider()
        # Pending pick → History aktualisieren + f_lut_path setzen
        if "_lut_path_pending" in st.session_state:
            _pending_lut = st.session_state.pop("_lut_path_pending")
            _save_lut_to_history(_pending_lut)
            st.session_state["f_lut_path"] = _pending_lut

        _lut_history = _load_lut_history()
        _lut_options = ["(kein LUT)"] + _lut_history
        _cur_lut     = st.session_state.get("f_lut_path", "")
        _lut_idx     = (_lut_history.index(_cur_lut) + 1) if _cur_lut in _lut_history else 0

        _lut_col_sel, _lut_col_btn = st.columns([5, 1])
        with _lut_col_sel:
            _lut_chosen = st.selectbox(
                "LUT (.cube)",
                options=_lut_options,
                index=_lut_idx,
                format_func=lambda p: "(kein LUT)" if p == "(kein LUT)" else Path(p).name,
                help="Optionale CUBE-LUT für Thumbnail-Vorschau (z.B. S-Log2→Rec.709). Zeigt die letzten 10 verwendeten LUTs.",
                key="f_lut_selectbox",
            )
        with _lut_col_btn:
            st.markdown("<div style='margin-top:1.85rem'></div>", unsafe_allow_html=True)
            if st.button("", icon=":material/folder_open:", key="lut_picker_btn", use_container_width=True, help="Neue LUT-Datei auswählen"):
                _picked_lut = None
                try:
                    import subprocess as _subp_lut
                    _r_lut = _subp_lut.run(
                        ["osascript", "-e",
                         'POSIX path of (choose file with prompt "LUT-Datei auswählen (.cube)")'],
                        capture_output=True, text=True, timeout=60,
                    )
                    if _r_lut.returncode == 0 and _r_lut.stdout.strip():
                        _picked_lut = _r_lut.stdout.strip()
                except Exception:
                    st.warning("Datei-Dialog nicht verfügbar.")
                if _picked_lut:
                    st.session_state["_lut_path_pending"] = _picked_lut
                    st.rerun()
        # f_lut_path für Thumbnail-Rendering beim nächsten Rerun aktualisieren
        st.session_state["f_lut_path"] = "" if _lut_chosen == "(kein LUT)" else _lut_chosen

    _render_preset_expander('f')
    if st.session_state.get("_overwrite_preset_prefix") == 'f':
        _confirm_overwrite_preset_dialog()

    st.divider()
    st.subheader("Workflow")

    start_folder = st.button(
        "Ordner-Workflow starten", icon=":material/play_arrow:",
        type="primary",
        disabled=st.session_state.folder_running or not _folder_valid,
        use_container_width=True,
        key="start_folder",
    )

    if start_folder:
        _v = _collect_settings('f')
        _save_settings_to_config(_v)

        st.session_state.folder_running  = True
        st.session_state.folder_log      = []
        st.session_state.folder_progress = 0.0
        st.session_state.folder_label    = "Starte..."
        st.session_state.folder_step     = 0
        st.session_state.folder_total    = FOLDER_WORKFLOW_STEPS[-1][4]
        # Cam-Types und Mic-Zuordnung aus Kachel-Dropdowns ableiten
        _fd_default_roles = (
            ["Cam 1", "Cam 2"] + ["Totale"] * max(0, len(_f_cams) - 2)
        )
        _fd_cam_types = [
            "wide" if st.session_state.get(f"f_cam_role_{_ci}", _fd_default_roles[_ci]) == "Totale"
            else "close"
            for _ci in range(len(_f_cams))
        ]
        _fd_close_labels = [
            st.session_state.get(f"f_cam_role_{_ci}", _fd_default_roles[_ci])
            for _ci in range(len(_f_cams))
            if st.session_state.get(f"f_cam_role_{_ci}", _fd_default_roles[_ci]) != "Totale"
        ] or ["Cam 1"]
        _fd_cam_mics: dict[int, list[int]] = {_ci: [] for _ci in range(len(_f_cams))}
        for _mi in range(len(_f_mics)):
            _lbl = st.session_state.get(
                f"f_mic_assign_{_mi}",
                _fd_close_labels[min(_mi, len(_fd_close_labels) - 1)],
            )
            for _ci in range(len(_f_cams)):
                if st.session_state.get(f"f_cam_role_{_ci}", _fd_default_roles[_ci]) == _lbl:
                    _fd_cam_mics[_ci].append(_mi)
                    break
        _fd_cam_mics_args = [
            ",".join(str(m) for m in _fd_cam_mics[_ci]) or "0"
            for _ci in range(len(_f_cams))
        ]
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "run_from_folder.py"),
            "--folder", folder_path,
            "--fps",    str(fps_folder),
            "--config", str(SCRIPT_DIR / "config.ini"),
            "--cam-types", *_fd_cam_types,
            "--cam-mics",  *_fd_cam_mics_args,
        ]
        if skip_analysis_f:
            cmd.append("--skip-analysis")
        if skip_base_edl_f:
            cmd.append("--skip-base-edl")
        if st.session_state.get("f_speaking_peak", False):
            cmd += ["--speaking-mode", "peak"]
        if st.session_state.get("f_auto_accuracy", False):
            cmd.append("--auto-accuracy")

        st.session_state.folder_preview_paths = [
            f"/tmp/multicam_preview_cam{i + 1}.jpg" for i in range(len(_f_cams))
        ]
        st.session_state.show_folder_dialog = True
        q = queue.Queue()
        threading.Thread(target=_run_script, args=(cmd, q), daemon=True).start()
        st.session_state.folder_queue = q
        st.rerun()

    if st.session_state.get("show_folder_dialog"):
        _workflow_dialog("folder", FOLDER_WORKFLOW_STEPS,
                         st.session_state.get("folder_preview_paths", []))
