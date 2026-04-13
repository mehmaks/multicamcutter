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
from pathlib import Path
st.title("✂️ Multicam Cutter")

SCRIPT_DIR = Path(__file__).parent.parent.parent / "modules" / "multicam_cutter"

tab_bin, tab_timeline = st.tabs(["Bin-Workflow", "Timeline-Workflow"])


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

    # Bin-Clips für sprechende Labels scannen
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

    _n_mics     = max(2, len(mic_labels))
    _mic_options = list(range(_n_mics))

    def _mic_name(idx):
        return mic_labels[idx] if idx < len(mic_labels) else f"MIC{idx + 1}"

    col_a, col_b = st.columns(2)
    with col_a:
        fps_bin               = st.number_input("FPS", value=25.0, step=1.0, format="%.1f")
        skip_analysis_b       = st.checkbox("Nodding-Analyse überspringen (JSONs existieren)")
        skip_base_edl_b       = st.checkbox("Base-EDL überspringen (base.edl existiert)")
        speaking_peak_mode_b  = st.checkbox("Speaking: Peak-Detektion (statt RMS)", help="Misst Peak-Pegel statt RMS pro Fenster — sensitiver für kurze Transients wie 'Mhm'")
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

    import configparser as _cp
    _cfg_path = SCRIPT_DIR / "config.ini"
    _cfg = _cp.ConfigParser()
    _cfg.read(str(_cfg_path))

    # Alle Widget-Keys die in Presets gespeichert werden
    _PRESET_KEYS = [
        's_min_shot', 's_max_shot', 's_reaction_dur', 's_cleanup_dur', 's_randomness',
        's_threshold_db', 's_min_edit', 's_change_delay',
        's_min_conf', 's_nodding_enabled', 's_min_nod_dur', 's_pre_roll',
        's_speaking_enabled', 's_rise_db', 's_speaking_min_dur', 's_speaking_max_dur', 's_speaking_min_conf',
    ]

    _presets_dir = SCRIPT_DIR / "presets"
    _presets_dir.mkdir(exist_ok=True)
    _preset_names = sorted(p.stem for p in _presets_dir.glob("*.json"))

    _pc1, _pc2 = st.columns([2, 3])
    with _pc1:
        _new_preset_name = st.text_input(
            "Preset-Name", placeholder="z.B. Standard Podcast",
            key="preset_name_input", label_visibility="collapsed",
        )
        if st.button("💾 Speichern", key="btn_save_preset",
                     disabled=not (_new_preset_name or '').strip()):
            _pdata = {k: st.session_state[k] for k in _PRESET_KEYS if k in st.session_state}
            _safe  = _new_preset_name.strip().replace('/', '_').replace('\\', '_')
            (_presets_dir / f"{_safe}.json").write_text(json.dumps(_pdata, indent=2))
            st.toast(f"Preset '{_safe}' gespeichert")
            st.rerun()

    with _pc2:
        if _preset_names:
            _ps1, _ps2, _ps3 = st.columns([3, 1, 1])
            with _ps1:
                _sel_preset = st.selectbox(
                    "Preset", _preset_names,
                    key="preset_select", label_visibility="collapsed",
                )
            with _ps2:
                if st.button("Laden", key="btn_load_preset", use_container_width=True):
                    _pdata = json.loads((_presets_dir / f"{_sel_preset}.json").read_text())
                    for _k, _v in _pdata.items():
                        st.session_state[_k] = _v
                    st.rerun()
            with _ps3:
                if st.button("🗑", key="btn_del_preset", use_container_width=True):
                    (_presets_dir / f"{_sel_preset}.json").unlink(missing_ok=True)
                    st.rerun()
        else:
            st.caption("Noch keine Presets gespeichert")

    st.divider()

    def _f(section, key, default):
        try: return _cfg.getfloat(section, key)
        except: return float(default)
    def _i(section, key, default):
        try: return _cfg.getint(section, key)
        except: return int(default)
    def _b(section, key, default):
        try: return _cfg.getboolean(section, key)
        except: return bool(default)

    with st.expander("Schnitt & Cutaways"):
        _c1, _c2 = st.columns(2)
        with _c1:
            s_min_shot = st.number_input("Min. Shotlänge (s)", value=_f('General','min_shot_duration',3.0), min_value=0.5, step=0.1, format="%.1f", key="s_min_shot",
                help="Minimale ON-Camera Shotlänge bevor ein Cutaway gesetzt werden darf")
            s_max_shot = st.number_input("Max. Shotlänge (s)", value=_f('General','max_shot_duration',14.0), min_value=1.0, step=0.5, format="%.1f", key="s_max_shot",
                help="Wird eine Kamera länger nicht geschnitten, erzwingt der Workflow einen Pflicht-Cutaway")
        with _c2:
            s_reaction_dur = st.number_input("Cutaway-Länge (s)", value=_f('General','reaction_min_duration',1.8), min_value=0.5, step=0.1, format="%.1f", key="s_reaction_dur",
                help="Basislänge eines Reaction-Cutaways — tatsächliche Länge variiert um den Zufallsfaktor nach oben")
            s_cleanup_dur = st.number_input("Cleanup-Mindestlänge (s)", value=_f('General','cleanup_min_duration',1.8), min_value=0.1, step=0.1, format="%.1f", key="s_cleanup_dur",
                help="Events kürzer als dieser Wert werden nach dem Zusammenbau der Timeline entfernt")
        s_randomness = st.slider("Cutaway-Zufallsfaktor", 0.0, 0.5, _f('General','cutaway_randomness',0.2), step=0.05, key="s_randomness",
            help="Zufälliger Aufschlag auf die Cutaway-Länge: 0 = immer exakt, 0.2 = bis zu 20 % länger — macht den Schnitt organischer")

    with st.expander("Sprecher-Erkennung (RMS)"):
        _c1, _c2, _c3 = st.columns(3)
        with _c1:
            s_threshold_db = st.number_input("Schwelle (dB)", value=_f('RMSDiarization','threshold_db',6.0), min_value=0.5, step=0.5, format="%.1f", key="s_threshold_db",
                help="dB-Unterschied zwischen beiden Mics nötig um einen Sprecherwechsel zu erkennen — höher = weniger empfindlich")
        with _c2:
            s_min_edit = st.number_input("Min. Segmentlänge (s)", value=_f('RMSDiarization','min_edit_duration',1.0), min_value=0.1, step=0.1, format="%.1f", key="s_min_edit",
                help="Sprechabschnitte kürzer als dieser Wert werden mit dem Nachbarn zusammengeführt")
        with _c3:
            s_change_delay = st.number_input("Wechsel-Verzögerung (s)", value=_f('RMSDiarization','change_delay',0.3), min_value=0.0, step=0.05, format="%.2f", key="s_change_delay",
                help="Sekunden die ein neuer Sprecher konstant dominieren muss bevor der Wechsel akzeptiert wird")

    with st.expander("Nodding-Erkennung"):
        _c1, _c2, _c3 = st.columns(3)
        with _c1:
            s_nodding_enabled = st.checkbox("Aktiviert", value=_b('Nodding','enabled',True), key="s_nodding_enabled",
                help="Nicken als Cutaway-Auslöser verwenden")
            s_min_conf = st.number_input("Min. Konfidenz", value=_f('Detection','min_confidence',0.88), min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key="s_min_conf",
                help="Minimale Erkennungs-Konfidenz eines Nods für Cutaway-Verwendung (0–1) — höher = weniger FPs, mehr FNs")
        with _c2:
            s_min_nod_dur = st.number_input("Min. Nod-Dauer (s)", value=_f('Nodding','min_nod_duration',0.65), min_value=0.1, step=0.05, format="%.2f", key="s_min_nod_dur",
                help="Mindestdauer der Kopfbewegung damit ein Nod als gültig gilt — höher filtert kurze Zuckungen heraus")
        with _c3:
            s_pre_roll = st.number_input("Pre-Roll (Frames)", value=_i('CutawayTiming','pre_roll_frames',15), min_value=0, step=1, key="s_pre_roll",
                help="Frames vor dem ersten erkannten Nod-Event, um den Cutaway-Startpunkt nach vorne zu verschieben")

    with st.expander("Speaking Reactions"):
        _c1, _c2 = st.columns(2)
        with _c1:
            s_speaking_enabled = st.checkbox("Aktiviert", value=_b('SpeakingReaction','enabled',True), key="s_speaking_enabled",
                help="Kurze Einwürfe und Reaktionen der Off-Kamera als Cutaway verwenden")
            s_rise_db = st.number_input("Rise (dB über Baseline)", value=_f('SpeakingReaction','rise_db',10.0), min_value=1.0, step=0.5, format="%.1f", key="s_rise_db",
                help="Mindest-Pegelanstieg über die rollierende Baseline für einen Speaking-Burst — höher = nur deutliche Einwürfe")
            s_speaking_min_conf = st.number_input("Min. Konfidenz", value=_f('SpeakingReaction','min_confidence',0.90), min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key="s_speaking_min_conf",
                help="Minimale Konfidenz für Speaking-Reaction-Cutaways (0–1)")
        with _c2:
            s_speaking_min_dur = st.number_input("Min. Burst-Dauer (s)", value=_f('SpeakingReaction','min_duration',0.20), min_value=0.05, step=0.05, format="%.2f", key="s_speaking_min_dur",
                help="Kürzeste Lautstärke-Spitze die als Speaking-Reaction zählt — kleiner = auch kurze 'Mhm'-Laute")
            s_speaking_max_dur = st.number_input("Max. Burst-Dauer (s)", value=_f('SpeakingReaction','max_duration',1.5), min_value=0.1, step=0.1, format="%.1f", key="s_speaking_max_dur",
                help="Längste Lautstärke-Spitze die noch als Speaking-Reaction gilt — größer = auch längere Einwürfe")

    st.divider()
    st.subheader("Workflow")

    start_bin = st.button(
        "▶ Bin-Workflow starten",
        type="primary",
        disabled=st.session_state.bin_running or not bin_name,
        use_container_width=True,
    )

    if start_bin:
        # Settings in config.ini persistieren bevor der Subprocess startet
        _save = _cp.ConfigParser()
        _save.read(str(_cfg_path))
        for _sec, _key, _val in [
            ('General',        'min_shot_duration',   s_min_shot),
            ('General',        'reaction_min_duration', s_reaction_dur),
            ('General',        'max_shot_duration',   s_max_shot),
            ('General',        'cleanup_min_duration', s_cleanup_dur),
            ('General',        'cutaway_randomness',  s_randomness),
            ('RMSDiarization', 'threshold_db',        s_threshold_db),
            ('RMSDiarization', 'min_edit_duration',   s_min_edit),
            ('RMSDiarization', 'change_delay',        s_change_delay),
            ('Detection',      'min_confidence',      s_min_conf),
            ('Nodding',        'min_nod_duration',    s_min_nod_dur),
            ('CutawayTiming',  'pre_roll_frames',     s_pre_roll),
            ('SpeakingReaction', 'rise_db',           s_rise_db),
            ('SpeakingReaction', 'min_duration',      s_speaking_min_dur),
            ('SpeakingReaction', 'max_duration',      s_speaking_max_dur),
            ('SpeakingReaction', 'min_confidence',    s_speaking_min_conf),
        ]:
            if _sec not in _save:
                _save[_sec] = {}
            _save[_sec][_key] = str(_val)
        _save['Nodding']['enabled'] = 'true' if s_nodding_enabled else 'false'
        _save['SpeakingReaction']['enabled'] = 'true' if s_speaking_enabled else 'false'
        with open(str(_cfg_path), 'w') as _f:
            _save.write(_f)

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
        if speaking_peak_mode_b:
            cmd += ["--speaking-mode", "peak"]

        q = queue.Queue()
        threading.Thread(target=_run_script, args=(cmd, q), daemon=True).start()
        st.session_state.bin_queue = q
        st.rerun()


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
        st.rerun()
