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
import json
import configparser as _cp
from pathlib import Path

st.title("✂️ Multicam Cutter")

SCRIPT_DIR   = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter"
_cfg_path    = SCRIPT_DIR / "config.ini"
_presets_dir = SCRIPT_DIR / "presets"
_presets_dir.mkdir(exist_ok=True)

# Canonical parameter names (no prefix) — used by preset save/load
_PARAM_NAMES = [
    'min_shot', 'max_shot', 'reaction_dur', 'cleanup_dur', 'randomness',
    'threshold_db', 'min_edit', 'change_delay',
    'min_conf', 'nodding_enabled', 'min_nod_dur', 'pre_roll',
    'speaking_enabled', 'rise_db', 'speaking_min_dur', 'speaking_max_dur', 'speaking_min_conf',
]

tab_bin, tab_folder = st.tabs(["Bin-Workflow", "Ordner-Workflow"])


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
    if not line.startswith("__PROGRESS__"):
        return None, None, None
    parts = line.split()
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


def _load_cfg():
    cfg = _cp.ConfigParser()
    cfg.read(str(_cfg_path))
    return cfg


def _fv(cfg, section, key, default):
    try: return cfg.getfloat(section, key)
    except: return float(default)


def _iv(cfg, section, key, default):
    try: return cfg.getint(section, key)
    except: return int(default)


def _bv(cfg, section, key, default):
    try: return cfg.getboolean(section, key)
    except: return bool(default)


def _render_preset_panel(prefix):
    """Render preset save/load/delete UI. Presets store param names without prefix."""
    preset_names = sorted(p.stem for p in _presets_dir.glob("*.json"))

    pc1, pc2 = st.columns([2, 3])
    with pc1:
        new_name = st.text_input(
            "Preset-Name", placeholder="z.B. Standard Podcast",
            key=f"{prefix}_preset_name_input", label_visibility="collapsed",
        )
        if st.button("💾 Speichern", key=f"{prefix}_btn_save_preset",
                     disabled=not (new_name or '').strip()):
            pdata = {name: st.session_state[f"{prefix}_{name}"]
                     for name in _PARAM_NAMES if f"{prefix}_{name}" in st.session_state}
            safe = new_name.strip().replace('/', '_').replace('\\', '_')
            (_presets_dir / f"{safe}.json").write_text(json.dumps(pdata, indent=2))
            st.toast(f"Preset '{safe}' gespeichert")
            st.rerun()

    with pc2:
        if preset_names:
            ps1, ps2, ps3 = st.columns([3, 1, 1])
            with ps1:
                sel_preset = st.selectbox(
                    "Preset", preset_names,
                    key=f"{prefix}_preset_select", label_visibility="collapsed",
                )
            with ps2:
                if st.button("Laden", key=f"{prefix}_btn_load_preset", use_container_width=True):
                    pdata = json.loads((_presets_dir / f"{sel_preset}.json").read_text())
                    for name, val in pdata.items():
                        # Support old presets that stored keys with s_ prefix
                        bare = name[2:] if (name.startswith('s_') or name.startswith('f_')) else name
                        if bare in _PARAM_NAMES:
                            st.session_state[f"{prefix}_{bare}"] = val
                    st.rerun()
            with ps3:
                if st.button("🗑", key=f"{prefix}_btn_del_preset", use_container_width=True):
                    (_presets_dir / f"{sel_preset}.json").unlink(missing_ok=True)
                    st.rerun()
        else:
            st.caption("Noch keine Presets gespeichert")


def _render_settings_panel(prefix):
    """Render 4 settings expanders with widget keys prefixed by `prefix`."""
    cfg = _load_cfg()

    with st.expander("Schnitt & Cutaways"):
        c1, c2 = st.columns(2)
        with c1:
            st.number_input("Min. Shotlänge (s)", value=_fv(cfg,'General','min_shot_duration',3.0),
                min_value=0.5, step=0.1, format="%.1f", key=f"{prefix}_min_shot",
                help="Minimale ON-Camera Shotlänge bevor ein Cutaway gesetzt werden darf")
            st.number_input("Max. Shotlänge (s)", value=_fv(cfg,'General','max_shot_duration',14.0),
                min_value=1.0, step=0.5, format="%.1f", key=f"{prefix}_max_shot",
                help="Wird eine Kamera länger nicht geschnitten, erzwingt der Workflow einen Pflicht-Cutaway")
        with c2:
            st.number_input("Cutaway-Länge (s)", value=_fv(cfg,'General','reaction_min_duration',1.8),
                min_value=0.5, step=0.1, format="%.1f", key=f"{prefix}_reaction_dur",
                help="Basislänge eines Reaction-Cutaways — tatsächliche Länge variiert um den Zufallsfaktor nach oben")
            st.number_input("Cleanup-Mindestlänge (s)", value=_fv(cfg,'General','cleanup_min_duration',1.8),
                min_value=0.1, step=0.1, format="%.1f", key=f"{prefix}_cleanup_dur",
                help="Events kürzer als dieser Wert werden nach dem Zusammenbau der Timeline entfernt")
        st.slider("Cutaway-Zufallsfaktor", 0.0, 0.5, _fv(cfg,'General','cutaway_randomness',0.2),
            step=0.05, key=f"{prefix}_randomness",
            help="Zufälliger Aufschlag auf die Cutaway-Länge: 0 = immer exakt, 0.2 = bis zu 20 % länger — macht den Schnitt organischer")

    with st.expander("Sprecher-Erkennung (RMS)"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("Schwelle (dB)", value=_fv(cfg,'RMSDiarization','threshold_db',6.0),
                min_value=0.5, step=0.5, format="%.1f", key=f"{prefix}_threshold_db",
                help="dB-Unterschied zwischen beiden Mics nötig um einen Sprecherwechsel zu erkennen — höher = weniger empfindlich")
        with c2:
            st.number_input("Min. Segmentlänge (s)", value=_fv(cfg,'RMSDiarization','min_edit_duration',1.0),
                min_value=0.1, step=0.1, format="%.1f", key=f"{prefix}_min_edit",
                help="Sprechabschnitte kürzer als dieser Wert werden mit dem Nachbarn zusammengeführt")
        with c3:
            st.number_input("Wechsel-Verzögerung (s)", value=_fv(cfg,'RMSDiarization','change_delay',0.3),
                min_value=0.0, step=0.05, format="%.2f", key=f"{prefix}_change_delay",
                help="Sekunden die ein neuer Sprecher konstant dominieren muss bevor der Wechsel akzeptiert wird")

    with st.expander("Nodding-Erkennung"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.checkbox("Aktiviert", value=_bv(cfg,'Nodding','enabled',True),
                key=f"{prefix}_nodding_enabled",
                help="Nicken als Cutaway-Auslöser verwenden")
            st.number_input("Min. Konfidenz", value=_fv(cfg,'Detection','min_confidence',0.88),
                min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key=f"{prefix}_min_conf",
                help="Minimale Erkennungs-Konfidenz eines Nods für Cutaway-Verwendung (0–1) — höher = weniger FPs, mehr FNs")
        with c2:
            st.number_input("Min. Nod-Dauer (s)", value=_fv(cfg,'Nodding','min_nod_duration',0.65),
                min_value=0.1, step=0.05, format="%.2f", key=f"{prefix}_min_nod_dur",
                help="Mindestdauer der Kopfbewegung damit ein Nod als gültig gilt — höher filtert kurze Zuckungen heraus")
        with c3:
            st.number_input("Pre-Roll (Frames)", value=_iv(cfg,'CutawayTiming','pre_roll_frames',15),
                min_value=0, step=1, key=f"{prefix}_pre_roll",
                help="Frames vor dem ersten erkannten Nod-Event, um den Cutaway-Startpunkt nach vorne zu verschieben")

    with st.expander("Speaking Reactions"):
        c1, c2 = st.columns(2)
        with c1:
            st.checkbox("Aktiviert", value=_bv(cfg,'SpeakingReaction','enabled',True),
                key=f"{prefix}_speaking_enabled",
                help="Kurze Einwürfe und Reaktionen der Off-Kamera als Cutaway verwenden")
            st.number_input("Rise (dB über Baseline)", value=_fv(cfg,'SpeakingReaction','rise_db',10.0),
                min_value=1.0, step=0.5, format="%.1f", key=f"{prefix}_rise_db",
                help="Mindest-Pegelanstieg über die rollierende Baseline für einen Speaking-Burst — höher = nur deutliche Einwürfe")
            st.number_input("Min. Konfidenz", value=_fv(cfg,'SpeakingReaction','min_confidence',0.90),
                min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key=f"{prefix}_speaking_min_conf",
                help="Minimale Konfidenz für Speaking-Reaction-Cutaways (0–1)")
        with c2:
            st.number_input("Min. Burst-Dauer (s)", value=_fv(cfg,'SpeakingReaction','min_duration',0.20),
                min_value=0.05, step=0.05, format="%.2f", key=f"{prefix}_speaking_min_dur",
                help="Kürzeste Lautstärke-Spitze die als Speaking-Reaction zählt — kleiner = auch kurze 'Mhm'-Laute")
            st.number_input("Max. Burst-Dauer (s)", value=_fv(cfg,'SpeakingReaction','max_duration',1.5),
                min_value=0.1, step=0.1, format="%.1f", key=f"{prefix}_speaking_max_dur",
                help="Längste Lautstärke-Spitze die noch als Speaking-Reaction gilt — größer = auch längere Einwürfe")


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
        'min_conf':          st.session_state.get(f"{p}min_conf", 0.88),
        'nodding_enabled':   st.session_state.get(f"{p}nodding_enabled", True),
        'min_nod_dur':       st.session_state.get(f"{p}min_nod_dur", 0.65),
        'pre_roll':          st.session_state.get(f"{p}pre_roll", 15),
        'speaking_enabled':  st.session_state.get(f"{p}speaking_enabled", True),
        'rise_db':           st.session_state.get(f"{p}rise_db", 10.0),
        'speaking_min_dur':  st.session_state.get(f"{p}speaking_min_dur", 0.20),
        'speaking_max_dur':  st.session_state.get(f"{p}speaking_max_dur", 1.5),
        'speaking_min_conf': st.session_state.get(f"{p}speaking_min_conf", 0.90),
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
        ('Nodding',          'min_nod_duration',     v['min_nod_dur']),
        ('CutawayTiming',    'pre_roll_frames',      v['pre_roll']),
        ('SpeakingReaction', 'rise_db',              v['rise_db']),
        ('SpeakingReaction', 'min_duration',         v['speaking_min_dur']),
        ('SpeakingReaction', 'max_duration',         v['speaking_max_dur']),
        ('SpeakingReaction', 'min_confidence',       v['speaking_min_conf']),
    ]:
        if sec not in save:
            save[sec] = {}
        save[sec][key] = str(val)
    save['Nodding']['enabled'] = 'true' if v['nodding_enabled'] else 'false'
    save['SpeakingReaction']['enabled'] = 'true' if v['speaking_enabled'] else 'false'
    with open(str(_cfg_path), 'w') as f:
        save.write(f)


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
        skip_analysis_b       = st.checkbox("Nodding-Analyse überspringen (JSONs existieren)")
        skip_base_edl_b       = st.checkbox("Base-EDL überspringen (base.edl existiert)")
        speaking_peak_mode_b  = st.checkbox("Speaking: Peak-Detektion (statt RMS)",
            help="Misst Peak-Pegel statt RMS pro Fenster — sensitiver für kurze Transients wie 'Mhm'")
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

    _render_preset_panel('s')
    st.divider()
    _render_settings_panel('s')

    st.divider()
    st.subheader("Workflow")

    start_bin = st.button(
        "▶ Bin-Workflow starten",
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
        if speaking_peak_mode_b:
            cmd += ["--speaking-mode", "peak"]

        q = queue.Queue()
        threading.Thread(target=_run_script, args=(cmd, q), daemon=True).start()
        st.session_state.bin_queue = q
        st.rerun()

    # ── Fortschrittsanzeige ───────────────────────────────────────────────────
    if st.session_state.bin_running or st.session_state.get('bin_progress', 0.0) > 0:
        st.divider()
        _poll_workflow_ui('bin', BIN_WORKFLOW_STEPS)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Ordner-Workflow
# ══════════════════════════════════════════════════════════════════════════════

with tab_folder:
    st.caption("Resolve-frei: Ordner mit CAM- und MIC-Dateien → final.edl")

    st.subheader("Ordner & Dateien")

    folder_path = st.text_input(
        "Ordner-Pfad",
        placeholder="/Pfad/zur/Episode",
        help="Ordner mit genau 2 Videodateien (.mp4/.mov/.mxf) und 1–2 Audiodateien (.wav/.aif)",
    )

    _folder_valid = bool(folder_path and Path(folder_path).is_dir())

    if _folder_valid:
        _fld = Path(folder_path)
        _VIDEO_EXT_F = {'.mp4', '.mov', '.mxf', '.r3d', '.ari'}
        _AUDIO_EXT_F = {'.wav', '.aif', '.aiff'}
        _all = sorted(f for f in _fld.iterdir() if f.is_file())
        _f_cams = [f for f in _all if f.suffix.lower() in _VIDEO_EXT_F]
        _f_mics = [f for f in _all if f.suffix.lower() in _AUDIO_EXT_F]

        if len(_f_cams) >= 2 and _f_mics:
            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"CAM1: `{_f_cams[0].name}`")
                st.caption(f"CAM2: `{_f_cams[1].name}`")
            with col2:
                for i, m in enumerate(_f_mics):
                    st.caption(f"MIC{i+1}: `{m.name}`")
            if len(_f_cams) > 2:
                st.warning(f"{len(_f_cams) - 2} weitere Videodatei(en) werden ignoriert.")
        elif len(_f_cams) < 2:
            st.error(f"Mindestens 2 Videodateien erwartet, {len(_f_cams)} gefunden.")
        else:
            st.error("Keine Audiodateien (.wav/.aif) gefunden.")
    elif folder_path:
        st.error("Ordner nicht gefunden.")

    st.divider()
    st.subheader("Optionen")

    _f_n_mics = max(2, len(_f_mics) if _folder_valid else 2)
    _f_mic_options = list(range(_f_n_mics))

    def _f_mic_name(idx):
        if _folder_valid and idx < len(_f_mics):
            return Path(_f_mics[idx]).stem
        return f"MIC{idx + 1}"

    col_a, col_b = st.columns(2)
    with col_a:
        fps_folder            = st.number_input("FPS", value=25.0, step=1.0, format="%.1f", key="f_fps")
        skip_analysis_f       = st.checkbox("Nodding-Analyse überspringen (JSONs existieren)", key="f_skip_analysis")
        skip_base_edl_f       = st.checkbox("Base-EDL überspringen (base.edl existiert)", key="f_skip_base_edl")
        speaking_peak_mode_f  = st.checkbox("Speaking: Peak-Detektion (statt RMS)", key="f_speaking_peak",
            help="Misst Peak-Pegel statt RMS pro Fenster — sensitiver für kurze Transients wie 'Mhm'")
    with col_b:
        mic_cam1_f = st.selectbox(
            "MIC für CAM1",
            options=_f_mic_options,
            format_func=_f_mic_name,
            index=min(1, _f_n_mics - 1),
            key="f_mic_cam1",
            help="Welches Mikrofon gehört zu Kamera 1?",
        )
        mic_cam2_f = st.selectbox(
            "MIC für CAM2",
            options=_f_mic_options,
            format_func=_f_mic_name,
            index=0,
            key="f_mic_cam2",
            help="Welches Mikrofon gehört zu Kamera 2?",
        )

    # ── Analyse-Einstellungen ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Analyse-Einstellungen")

    _render_preset_panel('f')
    st.divider()
    _render_settings_panel('f')

    st.divider()
    st.subheader("Workflow")

    start_folder = st.button(
        "▶ Ordner-Workflow starten",
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
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "run_from_folder.py"),
            "--folder", folder_path,
            "--fps",    str(fps_folder),
            "--config", str(SCRIPT_DIR / "config.ini"),
            "--mic-cam1", str(mic_cam1_f),
            "--mic-cam2", str(mic_cam2_f),
        ]
        if skip_analysis_f:
            cmd.append("--skip-analysis")
        if skip_base_edl_f:
            cmd.append("--skip-base-edl")
        if speaking_peak_mode_f:
            cmd += ["--speaking-mode", "peak"]

        q = queue.Queue()
        threading.Thread(target=_run_script, args=(cmd, q), daemon=True).start()
        st.session_state.folder_queue = q
        st.rerun()

    # ── Fortschrittsanzeige ───────────────────────────────────────────────────
    if st.session_state.folder_running or st.session_state.get('folder_progress', 0.0) > 0:
        st.divider()
        _poll_workflow_ui('folder', FOLDER_WORKFLOW_STEPS)
