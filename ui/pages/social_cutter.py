"""
Social Cutter — Schrittweiser Wizard für Social-Media-Clips.

Generiert aus Talking-Head + B-Roll einen fast-paced, ~30s Rohschnitt
über eine mehrstufige Pipeline mit Review nach jedem Schritt.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
import threading
import queue
from pathlib import Path

import streamlit as st

from ui.schema_renderer import load_schema, get_defaults, render_settings_panel, collect_settings
from modules.silence_cutter import (
    suggest_threshold_fast as _sc_suggest_fast,
    suggest_threshold_whisper as _sc_suggest_whisper,
    render_waveform_png as _render_waveform_png,
)
from shared.ffmpeg_utils import probe_fps as _probe_fps, probe_duration as _probe_dur

_log = logging.getLogger("rtk.social_cutter")

# ── Schema + Defaults ────────────────────────────────────────────────────────

_SCHEMA = load_schema("social_cutter")
_DEFAULTS = get_defaults(_SCHEMA)

# ── Step-Definitionen ────────────────────────────────────────────────────────

_STEPS = [
    ("Input",             ":material/upload_file:"),
    ("Silence Cut",       ":material/volume_off:"),
    ("Transkription",     ":material/mic:"),
    ("Phrasengrenzen",    ":material/format_quote:"),
    ("Redundanz",         ":material/compare_arrows:"),
    ("Segment-Montage",   ":material/view_timeline:"),
    ("Zoom / Reframing",  ":material/zoom_in:"),
    ("B-Roll",            ":material/movie:"),
    ("Voice Leveler",     ":material/graphic_eq:"),
    ("Anwenden",          ":material/check_circle:"),
]


# ── Session-State Init ───────────────────────────────────────────────────────

def _init_state():
    """Session-State mit Defaults initialisieren.  Pipeline-State aus /tmp/ laden."""
    if "soc_step" not in st.session_state:
        st.session_state["soc_step"] = 0
    from modules.social_cutter.types import SocialCutterState
    st.session_state["soc_state"] = SocialCutterState.load()


# ── Step-Navigation ──────────────────────────────────────────────────────────

def _render_step_bar():
    """Horizontale Step-Leiste oben."""
    current = st.session_state["soc_step"]
    cols = st.columns(len(_STEPS))
    for i, (name, icon) in enumerate(_STEPS):
        with cols[i]:
            if i < current:
                st.markdown(f"~~{icon} {name}~~")
            elif i == current:
                st.markdown(f"**{icon} {name}**")
            else:
                st.caption(f"{icon} {name}")


def _nav_buttons(can_back: bool = True, can_next: bool = True, next_label: str = "Weiter"):
    """Zurück/Weiter Buttons am Ende jedes Steps."""
    current = st.session_state["soc_step"]
    col_l, col_r = st.columns(2)
    with col_l:
        if can_back and current > 0:
            if st.button(":material/arrow_back: Zurück", use_container_width=True,
                         key=f"soc_back_{current}"):
                st.session_state["soc_step"] = current - 1
                st.rerun()
    with col_r:
        if can_next:
            if st.button(f":material/arrow_forward: {next_label}", type="primary",
                         use_container_width=True, key=f"soc_next_{current}"):
                st.session_state["soc_step"] = current + 1
                st.rerun()


# ── Resolve-Erkennung ──────────────────────────────────────────────────────

_resolve_ok = False
_resolve_tl = None
_resolve_tl_name = ""
_resolve_project_name = ""
_resolve_fps = 25.0
_resolve_v1_path = ""

try:
    from resolve_bridge.connection import get_resolve as _get_resolve_soc
    from resolve_bridge.timeline_reader import read_timeline as _read_timeline_soc

    _resolve_obj = _get_resolve_soc()
    _resolve_project_name = _resolve_obj.GetProjectManager().GetCurrentProject().GetName()
    _resolve_tl = _read_timeline_soc()
    _resolve_tl_name = _resolve_tl.timeline_name
    _resolve_fps = _resolve_tl.fps
    _resolve_ok = True

    # Ersten V1-Clip als Talking-Head vorschlagen
    v1_clips = _resolve_tl.video_tracks.get(1, [])
    if v1_clips:
        _resolve_v1_path = v1_clips[0].file_path
except Exception:
    pass


# ── Step 0: Input ────────────────────────────────────────────────────────────

def _render_step_input():
    """Schritt 0: Dateiauswahl und B-Roll-Kategorien."""
    st.subheader("Input")

    state = st.session_state["soc_state"]

    # ── Resolve-Status ────────────────────────────────────────────────────
    if _resolve_ok:
        st.success(
            f":material/link: **Resolve verbunden** — "
            f"Projekt: *{_resolve_project_name}* · "
            f"Timeline: *{_resolve_tl_name}* · "
            f"FPS: {_resolve_fps}"
        )
        v1_clips = _resolve_tl.video_tracks.get(1, [])
        if v1_clips:
            st.caption(f"V1: {len(v1_clips)} Clip(s) — {Path(v1_clips[0].file_path).name}")
        else:
            st.warning("Keine Clips auf V1 gefunden.")
    else:
        st.info(":material/link_off: Resolve nicht verbunden — Datei-Pfad manuell eingeben.")

    # ── Quelle wählen ─────────────────────────────────────────────────────
    if _resolve_ok:
        source_mode = st.radio(
            "Quelle", ["Resolve Timeline (V1)", "Datei-Pfad"],
            horizontal=True, key="soc_source_mode",
        )
    else:
        source_mode = "Datei-Pfad"

    if source_mode == "Resolve Timeline (V1)" and _resolve_ok:
        v1_clips = _resolve_tl.video_tracks.get(1, [])
        if _resolve_v1_path and Path(_resolve_v1_path).exists() and v1_clips:
            clip = v1_clips[0]
            # source_start/end_frame is 0-based (no TC offset).
            # Use source fps from ffprobe (may differ from timeline fps).
            from resolve_bridge.silence_cutter import _probe_source_fps
            _src_fps = _probe_source_fps(_resolve_v1_path) or _resolve_fps
            clip_start = clip.source_start_frame / _src_fps
            clip_end = clip.source_end_frame / _src_fps
            if (state.src_path != _resolve_v1_path
                    or state.src_start_s != clip_start
                    or state.src_end_s != clip_end):
                state.src_path = _resolve_v1_path
                state.src_start_s = clip_start
                state.src_end_s = clip_end
                state.save()
            clip_dur = clip_end - clip_start
            st.caption(
                f"Talking-Head: `{Path(_resolve_v1_path).name}` "
                f"({clip_start:.1f}s \u2013 {clip_end:.1f}s, {clip_dur:.1f}s)"
            )
        else:
            st.warning("V1-Clip nicht gefunden oder kein Clip auf V1.")
    else:
        manual = st.text_input(
            "Talking-Head Datei",
            value=state.src_path,
            placeholder="/Pfad/zur/talking_head.mov",
            key="soc_talking_head_input",
            help="Pfad zur Talking-Head Videodatei (9:16, Single Camera).",
        )
        if manual and manual != state.src_path:
            state.src_path = manual
            state.src_start_s = 0.0
            state.src_end_s = 0.0
            state.save()

    talking_head = state.src_path

    # ── B-Roll ────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("**B-Roll**")

    if _resolve_ok:
        st.caption(
            'Clips im Media Pool mit Keyword **"b-roll"** werden als B-Roll erkannt. '
            "Weitere Keywords des Clips bestimmen die Kategorie "
            '(z.B. "b-roll, doktor" \u2192 Kategorie "doktor").'
        )

        if st.button("Media Pool scannen", icon=":material/search:", key="soc_scan_broll"):
            try:
                from resolve_bridge.social_cutter import scan_broll_keywords
                found = scan_broll_keywords()
                state.broll_categories = found
                state.save()
            except Exception as e:
                st.error(f"Scan fehlgeschlagen: {e}")

        if state.broll_categories:
            st.success(f"{len(state.broll_categories)} Kategorien, "
                       f"{sum(len(c.clip_paths) for c in state.broll_categories)} Clips gefunden.")
            for cat in state.broll_categories:
                with st.expander(f"**{cat.name}** ({len(cat.clip_paths)} Clips)"):
                    for p in cat.clip_paths:
                        st.caption(f"`{Path(p).name}`")
        elif st.session_state.get("soc_scan_broll"):
            st.info('Keine Clips mit Keyword "b-roll" gefunden.')

    else:
        st.caption("Ordner mit thematisch sortiertem B-Roll-Material.")

        if "soc_broll_cats" not in st.session_state:
            st.session_state["soc_broll_cats"] = []

        cats = st.session_state["soc_broll_cats"]

        for i, cat in enumerate(cats):
            col_name, col_path, col_del = st.columns([2, 4, 1])
            with col_name:
                cats[i]["name"] = st.text_input(
                    "Kategorie", value=cat["name"], key=f"soc_cat_name_{i}",
                    label_visibility="collapsed",
                )
            with col_path:
                cats[i]["path"] = st.text_input(
                    "Pfad", value=cat["path"], key=f"soc_cat_path_{i}",
                    label_visibility="collapsed",
                )
            with col_del:
                if st.button(":material/delete:", key=f"soc_cat_del_{i}"):
                    cats.pop(i)
                    st.rerun()

        if st.button(":material/add: Kategorie hinzufügen", key="soc_add_cat"):
            cats.append({"name": "", "path": ""})
            st.rerun()

    # ── Validierung ───────────────────────────────────────────────────────
    has_input = bool(talking_head and Path(talking_head).exists())
    if talking_head and not Path(talking_head).exists():
        st.warning("Datei nicht gefunden.")

    _nav_buttons(can_back=False, can_next=has_input)


# ── Step 1: Silence Cut ─────────────────────────────────────────────────────

@st.dialog("Schwellwert analysieren")
def _sc_dialog():
    """Progress-Dialog für Silence-Threshold-Analyse."""
    q = st.session_state.get("soc_sc_queue")
    if q:
        while True:
            try:
                msg = q.get_nowait()
                if isinstance(msg, tuple) and msg[0] == "__RESULT__":
                    st.session_state["soc_sc_result"] = msg[1]
                elif isinstance(msg, tuple) and len(msg) == 3 and msg[0] == "progress":
                    st.session_state["soc_sc_progress"] = msg[1]
                    st.session_state["soc_sc_status"] = msg[2]
                elif isinstance(msg, str) and msg.startswith("__DONE__"):
                    st.session_state["soc_sc_running"] = False
                elif isinstance(msg, str) and msg.startswith("Fehler"):
                    st.session_state["soc_sc_error"] = msg
                    st.session_state["soc_sc_running"] = False
            except Exception:
                break

    running = st.session_state.get("soc_sc_running", False)
    result = st.session_state.get("soc_sc_result")
    error = st.session_state.get("soc_sc_error")

    if running:
        st.progress(
            st.session_state.get("soc_sc_progress", 0.0),
            text=st.session_state.get("soc_sc_status", "Starte …"),
        )
        st.rerun()
    elif error:
        st.error(error)
        if st.button("Schließen", use_container_width=True):
            st.session_state["soc_sc_dialog_open"] = False
            st.session_state.pop("soc_sc_error", None)
            st.rerun()
    elif result:
        st.success(
            f"**Vorschlag: {result['threshold']} dB**\n\n"
            f"Rauschboden: **{result['noise_floor']} dB** · "
            f"Leise Sprache: **{result['quiet_speech']} dB**"
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Übernehmen", icon=":material/check:", type="primary",
                         use_container_width=True, key="soc_sc_apply"):
                st.session_state["soc_silence_threshold_db"] = result["threshold"]
                st.session_state["soc_sc_result"] = None
                st.session_state["soc_sc_dialog_open"] = False
                st.rerun()
        with c2:
            if st.button("Schließen", use_container_width=True, key="soc_sc_close"):
                st.session_state["soc_sc_dialog_open"] = False
                st.session_state["soc_sc_result"] = None
                st.rerun()


def _render_step_silence():
    """Schritt 1: Silence Cut — Analyse + Timeline-Schnitt in Resolve."""
    st.subheader("Silence Cut")

    state = st.session_state["soc_state"]
    settings = collect_settings(_SCHEMA, "soc")
    render_settings_panel(_SCHEMA, "soc", expert=st.session_state.get("expert_mode", False),
                          filter_keys=["silence"])

    src = state.src_path

    # ── Silence Cut ausführen ──────────────────────────────────────────────
    # WICHTIG: Dieser Block muss VOR dem Auto-Suggest-Dialog stehen,
    # weil der Dialog st.rerun() aufruft und alles darunter blockiert.
    st.divider()

    # Ergebnis bereits vorhanden?
    if state.silence_segments:
        total_keep = sum(s.end_s - s.start_s for s in state.silence_segments)
        st.success(f"{len(state.silence_segments)} Keep-Segmente ({total_keep:.1f}s)")
        if _resolve_ok:
            new_name = st.session_state.get("soc_sc_new_tl_name", "")
            if new_name:
                st.caption(f"Timeline: **{new_name}**")
        if st.button("Erneut analysieren", key="soc_sc_rerun"):
            state.silence_segments = []
            state.save()
            st.session_state["soc_sc_cut_done"] = False
            st.rerun()
        _nav_buttons()
        return

    # Progress / Queue Polling
    if st.session_state.get("soc_sc_cut_running"):
        st.progress(
            st.session_state.get("soc_sc_cut_progress", 0.0),
            text=st.session_state.get("soc_sc_cut_status", "Starte \u2026"),
        )
        q = st.session_state.get("soc_sc_cut_queue")
        if q:
            while True:
                try:
                    msg = q.get_nowait()
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        st.session_state["soc_sc_cut_progress"] = msg[1]
                        st.session_state["soc_sc_cut_status"] = msg[2]
                    elif isinstance(msg, tuple) and msg[0] == "__RESULT__":
                        from modules.social_cutter.types import SilenceSegment
                        state.silence_segments = [
                            SilenceSegment(start_s=s["start"], end_s=s["end"])
                            for s in msg[1]
                        ]
                        state.save()
                        st.session_state["soc_sc_cut_running"] = False
                        st.session_state["soc_sc_cut_done"] = True
                    elif isinstance(msg, str) and msg.startswith("Fehler"):
                        st.session_state["soc_sc_cut_error"] = msg
                        st.session_state["soc_sc_cut_running"] = False
                except Exception:
                    break
        st.rerun()
    elif st.session_state.get("soc_sc_cut_error"):
        st.error(st.session_state["soc_sc_cut_error"])

    # Timeline-Name (Resolve-Modus)
    if _resolve_ok:
        default_name = f"{_resolve_tl_name} (social cut)"
        new_tl_name = st.text_input(
            "Name der neuen Timeline", value=default_name, key="soc_sc_tl_name_input",
        )
        st.caption(
            "Erstellt eine neue Timeline ohne die erkannten Pausen. "
            "Die originale Timeline bleibt erhalten."
        )

    # ── Start-Button ──────────────────────────────────────────────────────
    if src and Path(src).exists():
        if st.button(
            "Silence Cut ausf\u00fchren", icon=":material/content_cut:", type="primary",
            disabled=st.session_state.get("soc_sc_cut_running", False),
            key="soc_sc_cut_start",
        ):
            q = queue.Queue()
            st.session_state["soc_sc_cut_running"] = True
            st.session_state["soc_sc_cut_error"] = None
            st.session_state["soc_sc_cut_progress"] = 0.0
            st.session_state["soc_sc_cut_queue"] = q

            if _resolve_ok:
                # ── Resolve-Modus: Timeline analysieren + neue Timeline bauen ──
                st.session_state["soc_sc_new_tl_name"] = new_tl_name.strip() or default_name

                def _cut_worker_resolve(tl_data, tl_name, new_name, s, q_):
                    def _cb(frac, text):
                        q_.put(("progress", frac, text))
                    try:
                        from resolve_bridge.connection import get_resolve
                        from resolve_bridge.silence_cutter import (
                            analyze_composite_silence,
                            rebuild_timeline_without_silences,
                        )

                        resolve = get_resolve()
                        fps = tl_data.fps
                        tl_start = tl_data.timeline_start
                        tl_end = tl_data.timeline_end

                        _cb(0.1, "Stille-Erkennung auf Timeline \u2026")

                        silence_segs = analyze_composite_silence(
                            audio_tracks=tl_data.audio_tracks,
                            selected_tracks=list(tl_data.audio_tracks.keys()),
                            fps=fps, tl_start=tl_start, tl_end=tl_end,
                            threshold_db=s.get("silence_threshold_db", -38),
                            min_silence_s=s.get("silence_min_s", 0.5),
                            pre_pad_s=s.get("silence_pre_pad_ms", 100) / 1000.0,
                            post_pad_s=s.get("silence_post_pad_ms", 100) / 1000.0,
                            gaps_are_silence=True,
                            progress_cb=lambda msg: (
                                _cb(0.3, str(msg)) if isinstance(msg, str) else None
                            ),
                        )

                        if not silence_segs:
                            _cb(1.0, "Keine Stille erkannt.")
                            clip_dur = (tl_end - tl_start) / fps
                            q_.put(("__RESULT__", [
                                {"start": 0.0, "end": round(clip_dur, 4)}
                            ]))
                            return

                        total_silence_s = sum(d for _, d in silence_segs) / fps
                        _cb(0.4, f"{len(silence_segs)} Stille-Bereiche "
                                 f"({total_silence_s:.1f}s) \u2014 schneide Timeline \u2026")

                        rebuild_timeline_without_silences(
                            resolve=resolve,
                            source_tl_name=tl_name,
                            new_tl_name=new_name,
                            selected_tracks=list(tl_data.audio_tracks.keys()),
                            silence_segments=silence_segs,
                            progress_cb=lambda msg: (
                                _cb(0.7, str(msg)) if isinstance(msg, str) else None
                            ),
                        )

                        _cb(0.9, "Keep-Segmente berechnen \u2026")

                        # Silence \u2192 Keep-Segmente invertieren (clip-relativ: 0 = Clip-Start)
                        keep = []
                        pos = tl_start
                        for s_start, s_dur in sorted(silence_segs):
                            s_end = s_start + s_dur
                            if pos < s_start:
                                keep.append({
                                    "start": round((pos - tl_start) / fps, 4),
                                    "end": round((s_start - tl_start) / fps, 4),
                                })
                            pos = s_end
                        if pos < tl_end:
                            keep.append({
                                "start": round((pos - tl_start) / fps, 4),
                                "end": round((tl_end - tl_start) / fps, 4),
                            })

                        _cb(1.0, f"\u2713 Timeline \u201E{new_name}\u201C erstellt "
                                 f"\u2014 {len(keep)} Segmente, "
                                 f"{total_silence_s:.1f}s entfernt")
                        q_.put(("__RESULT__", keep))
                    except Exception as e:
                        _log.exception("Social Cutter: Silence Cut fehlgeschlagen")
                        q_.put(f"Fehler: {e}")

                threading.Thread(
                    target=_cut_worker_resolve,
                    args=(_resolve_tl, _resolve_tl_name,
                          st.session_state["soc_sc_new_tl_name"], settings, q),
                    daemon=True,
                ).start()

            else:
                # ── Datei-Modus: Nur Analyse, kein Timeline-Rebuild ───────
                def _cut_worker_file(path, s, q_):
                    import math
                    from types import SimpleNamespace
                    def _cb(frac, text):
                        q_.put(("progress", frac, text))
                    try:
                        from resolve_bridge.silence_cutter import analyze_composite_silence

                        fps = _probe_fps(path)
                        dur_s = _probe_dur(path)
                        tl_len = int(math.ceil(dur_s * fps))

                        _cb(0.1, "Stille-Erkennung \u2026")

                        fake_clip = SimpleNamespace(
                            file_path=path,
                            timeline_start=0, timeline_end=tl_len,
                            source_start_frame=0, source_end_frame=tl_len,
                        )

                        silence_segs = analyze_composite_silence(
                            audio_tracks={1: [fake_clip]},
                            selected_tracks=[1],
                            fps=fps, tl_start=0, tl_end=tl_len,
                            threshold_db=s.get("silence_threshold_db", -38),
                            min_silence_s=s.get("silence_min_s", 0.5),
                            pre_pad_s=s.get("silence_pre_pad_ms", 100) / 1000.0,
                            post_pad_s=s.get("silence_post_pad_ms", 100) / 1000.0,
                            gaps_are_silence=True,
                            progress_cb=lambda msg: (
                                _cb(0.3, str(msg)) if isinstance(msg, str) else None
                            ),
                        )

                        _cb(0.8, "Keep-Segmente berechnen \u2026")

                        keep = []
                        pos = 0
                        for s_start, s_dur in sorted(silence_segs):
                            s_end = s_start + s_dur
                            if pos < s_start:
                                keep.append({
                                    "start": round(pos / fps, 4),
                                    "end": round(s_start / fps, 4),
                                })
                            pos = s_end
                        if pos < tl_len:
                            keep.append({
                                "start": round(pos / fps, 4),
                                "end": round(tl_len / fps, 4),
                            })

                        _cb(1.0, f"{len(keep)} Keep-Segmente")
                        q_.put(("__RESULT__", keep))
                    except Exception as e:
                        q_.put(f"Fehler: {e}")

                threading.Thread(
                    target=_cut_worker_file, args=(src, settings, q), daemon=True,
                ).start()

            st.rerun()
    else:
        st.warning("Keine Quelldatei vorhanden.")

    # ── Schwellwert automatisch ermitteln (optional) ─────────────────────
    # Steht am Ende, weil der Dialog bei st.rerun() alles darunter blockt.
    if src and Path(src).exists():
        st.divider()
        with st.expander(":material/auto_fix_high: Schwellwert automatisch ermitteln"):
            busy = st.session_state.get("soc_sc_running", False)
            c_a, c_b = st.columns(2)
            with c_a:
                fast_btn = st.button(
                    "Schnell analysieren", icon=":material/bolt:",
                    use_container_width=True, disabled=busy, key="soc_sc_fast",
                )
            with c_b:
                whisper_ok = True
                try:
                    import whisper  # noqa: F401
                except ImportError:
                    whisper_ok = False
                whisper_btn = st.button(
                    "Genauer (Whisper)", icon=":material/mic:",
                    use_container_width=True, disabled=not whisper_ok or busy,
                    key="soc_sc_whisper",
                )

            if fast_btn or whisper_btn:
                mode = "whisper" if whisper_btn else "fast"
                q = queue.Queue()
                st.session_state["soc_sc_running"] = True
                st.session_state["soc_sc_result"] = None
                st.session_state["soc_sc_error"] = None
                st.session_state["soc_sc_progress"] = 0.0
                st.session_state["soc_sc_status"] = "Starte \u2026"
                st.session_state["soc_sc_queue"] = q
                st.session_state["soc_sc_dialog_open"] = True

                def _suggest_worker(path, m, q_):
                    def _cb(frac, text):
                        q_.put(("progress", frac, text))
                    try:
                        fn = _sc_suggest_whisper if m == "whisper" else _sc_suggest_fast
                        res = fn(path, progress_cb=_cb)
                        q_.put(("__RESULT__", res))
                        q_.put("__DONE__")
                    except Exception as e:
                        q_.put(f"Fehler: {e}")

                threading.Thread(target=_suggest_worker, args=(src, mode, q), daemon=True).start()
                st.rerun()

    # Dialog am Ende — sein st.rerun() blockiert nichts Wichtiges mehr
    if st.session_state.get("soc_sc_dialog_open"):
        _sc_dialog()

    _nav_buttons(can_next=bool(state.silence_segments))


# ── Step 2: Transkription ────────────────────────────────────────────────────

def _render_step_transcription():
    """Schritt 2: Whisper-Transkription."""
    st.subheader("Transkription")

    state = st.session_state["soc_state"]
    settings = collect_settings(_SCHEMA, "soc")

    if state.transcript:
        st.success(f"{len(state.transcript.words)} Wörter transkribiert.")
        st.text_area(
            "Transkript", value=state.transcript.full_text,
            height=200, disabled=True, key="soc_transcript_text",
        )
        _nav_buttons()
        return

    if not state.src_path or not Path(state.src_path).exists():
        st.warning("Keine Quelldatei vorhanden.")
        _nav_buttons(can_next=False)
        return

    if state.has_clip_range:
        clip_dur = state.src_end_s - state.src_start_s
        st.caption(f"Clip-Bereich: {state.src_start_s:.1f}s \u2013 "
                   f"{state.src_end_s:.1f}s ({clip_dur:.1f}s)")

    model_name = settings.get("whisper_model", "medium")

    if st.session_state.get("soc_tr_running"):
        st.progress(
            st.session_state.get("soc_tr_progress", 0.0),
            text=st.session_state.get("soc_tr_status", "Starte \u2026"),
        )
        q = st.session_state.get("soc_tr_queue")
        if q:
            while True:
                try:
                    msg = q.get_nowait()
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        st.session_state["soc_tr_progress"] = msg[1]
                        st.session_state["soc_tr_status"] = msg[2]
                    elif isinstance(msg, tuple) and msg[0] == "__RESULT__":
                        state.transcript = msg[1]
                        state.save()
                        st.session_state["soc_tr_running"] = False
                    elif isinstance(msg, str) and msg.startswith("Fehler"):
                        st.session_state["soc_tr_error"] = msg
                        st.session_state["soc_tr_running"] = False
                except Exception:
                    break
        st.rerun()
    elif st.session_state.get("soc_tr_error"):
        st.error(st.session_state["soc_tr_error"])

    if st.button(
        f"Transkription starten (Whisper {model_name})",
        icon=":material/mic:", type="primary",
        disabled=st.session_state.get("soc_tr_running", False),
        key="soc_tr_start",
    ):
        q = queue.Queue()
        st.session_state["soc_tr_running"] = True
        st.session_state["soc_tr_error"] = None
        st.session_state["soc_tr_progress"] = 0.0
        st.session_state["soc_tr_status"] = "Starte \u2026"
        st.session_state["soc_tr_queue"] = q

        def _worker(state_ref, model, q_):
            def _cb(frac, text):
                q_.put(("progress", frac, text))
            try:
                # Clip-Audio extrahieren (nur Clip-Bereich, nicht ganze Datei)
                if state_ref.has_clip_range:
                    _cb(0.02, "Clip-Audio extrahieren \u2026")
                audio_path = state_ref.extract_clip_audio()

                from modules.social_cutter.transcribe import transcribe
                result = transcribe(audio_path, model_name=model, progress_cb=_cb)
                q_.put(("__RESULT__", result))
            except Exception as e:
                q_.put(f"Fehler: {e}")

        threading.Thread(target=_worker, args=(state, model_name, q), daemon=True).start()
        st.rerun()

    _nav_buttons(can_next=state.transcript is not None)


# ── Step 3: Phrasengrenzen ───────────────────────────────────────────────────

def _render_step_phrase_boundaries():
    """Schritt 3: Phrasengrenzen-Erkennung."""
    st.subheader("Phrasengrenzen")

    state = st.session_state["soc_state"]
    settings = collect_settings(_SCHEMA, "soc")

    if not state.transcript:
        st.warning("Bitte zuerst die Transkription durchführen.")
        _nav_buttons(can_next=False)
        return

    if state.phrase_boundaries:
        st.success(f"{len(state.phrase_boundaries)} Phrasengrenzen erkannt.")
        for b in state.phrase_boundaries:
            icon = ":material/stop:" if b.pitch_trend == "falling" else (
                ":material/trending_up:" if b.pitch_trend == "rising" else ":material/remove:")
            st.caption(
                f"{icon} **{b.time_s:.2f}s** — "
                f"\u201E{b.word_before}\u201C | \u201E{b.word_after}\u201C — "
                f"{b.boundary_type.value} ({b.confidence:.0%}, {b.pitch_trend})"
            )
        _nav_buttons()
        return

    if st.session_state.get("soc_pb_running"):
        st.progress(
            st.session_state.get("soc_pb_progress", 0.0),
            text=st.session_state.get("soc_pb_status", "Starte \u2026"),
        )
        q = st.session_state.get("soc_pb_queue")
        if q:
            while True:
                try:
                    msg = q.get_nowait()
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        st.session_state["soc_pb_progress"] = msg[1]
                        st.session_state["soc_pb_status"] = msg[2]
                    elif isinstance(msg, tuple) and msg[0] == "__RESULT__":
                        state.phrase_boundaries = msg[1]
                        state.save()
                        st.session_state["soc_pb_running"] = False
                    elif isinstance(msg, str) and msg.startswith("Fehler"):
                        st.session_state["soc_pb_error"] = msg
                        st.session_state["soc_pb_running"] = False
                except Exception:
                    break
        st.rerun()
    elif st.session_state.get("soc_pb_error"):
        st.error(st.session_state["soc_pb_error"])

    if st.button(
        "Phrasengrenzen erkennen",
        icon=":material/format_quote:", type="primary",
        disabled=st.session_state.get("soc_pb_running", False),
        key="soc_pb_start",
    ):
        q = queue.Queue()
        st.session_state["soc_pb_running"] = True
        st.session_state["soc_pb_error"] = None
        st.session_state["soc_pb_progress"] = 0.0
        st.session_state["soc_pb_status"] = "Starte \u2026"
        st.session_state["soc_pb_queue"] = q

        def _worker(state_ref, prefs, q_):
            def _cb(frac, text):
                q_.put(("progress", frac, text))
            try:
                # Clip-Audio (bereits extrahiert oder Quelldatei)
                audio_path = state_ref.extract_clip_audio()

                from modules.social_cutter.phrase_boundaries import detect_phrase_boundaries
                result = detect_phrase_boundaries(
                    transcript=state_ref.transcript,
                    audio_path=audio_path,
                    silence_segments=state_ref.silence_segments,
                    prefer_falls=prefs["prefer_falls"],
                    min_gap_ms=prefs["min_gap_ms"],
                    progress_cb=_cb,
                )
                q_.put(("__RESULT__", result))
            except Exception as e:
                q_.put(f"Fehler: {e}")

        threading.Thread(
            target=_worker,
            args=(state, settings, q),
            daemon=True,
        ).start()
        st.rerun()

    _nav_buttons(can_next=bool(state.phrase_boundaries))


# ── Step 4: Redundanz ────────────────────────────────────────────────────────

def _render_step_redundancy():
    """Schritt 4: Redundanz-Erkennung + User-Auswahl."""
    st.subheader("Redundanz-Erkennung")

    state = st.session_state["soc_state"]
    settings = collect_settings(_SCHEMA, "soc")

    if not state.phrase_boundaries:
        st.warning("Bitte zuerst die Phrasengrenzen erkennen.")
        _nav_buttons(can_next=False)
        return

    # Sätze aus Phrasengrenzen ableiten (falls noch nicht geschehen)
    if not state.sentences:
        from modules.social_cutter.phrase_boundaries import split_into_sentences
        min_conf = settings.get("phrase_min_confidence", 0.5)
        state.sentences = split_into_sentences(
            state.transcript, state.phrase_boundaries, min_confidence=min_conf,
        )
        state.save()

    # Redundanz-Analyse
    if not state.redundancy_groups and not st.session_state.get("soc_rd_done"):
        if st.session_state.get("soc_rd_running"):
            st.progress(
                st.session_state.get("soc_rd_progress", 0.0),
                text=st.session_state.get("soc_rd_status", "Starte …"),
            )
            q = st.session_state.get("soc_rd_queue")
            if q:
                while True:
                    try:
                        msg = q.get_nowait()
                        if isinstance(msg, tuple) and msg[0] == "progress":
                            st.session_state["soc_rd_progress"] = msg[1]
                            st.session_state["soc_rd_status"] = msg[2]
                        elif isinstance(msg, tuple) and msg[0] == "__RESULT__":
                            state.redundancy_groups = msg[1]
                            state.save()
                            st.session_state["soc_rd_running"] = False
                            st.session_state["soc_rd_done"] = True
                        elif isinstance(msg, str) and msg.startswith("Fehler"):
                            st.session_state["soc_rd_error"] = msg
                            st.session_state["soc_rd_running"] = False
                    except Exception:
                        break
            st.rerun()
        elif st.session_state.get("soc_rd_error"):
            st.error(st.session_state["soc_rd_error"])

        if st.button(
            "Redundanzen erkennen", icon=":material/compare_arrows:", type="primary",
            disabled=st.session_state.get("soc_rd_running", False), key="soc_rd_start",
        ):
            q = queue.Queue()
            st.session_state["soc_rd_running"] = True
            st.session_state["soc_rd_error"] = None
            st.session_state["soc_rd_progress"] = 0.0
            st.session_state["soc_rd_queue"] = q

            threshold = settings.get("similarity_threshold", 0.75)

            def _worker(sents, thr, q_):
                def _cb(frac, text):
                    q_.put(("progress", frac, text))
                try:
                    from modules.social_cutter.redundancy import detect_redundancy
                    result = detect_redundancy(sents, similarity_threshold=thr, progress_cb=_cb)
                    q_.put(("__RESULT__", result))
                except Exception as e:
                    q_.put(f"Fehler: {e}")

            threading.Thread(target=_worker, args=(state.sentences, threshold, q), daemon=True).start()
            st.rerun()

        _nav_buttons(can_next=False)
        return

    # Ergebnis anzeigen
    groups = state.redundancy_groups
    if not groups:
        st.success("Keine Redundanzen gefunden.")
        _nav_buttons()
        return

    st.info(f"{len(groups)} Redundanz-Gruppen gefunden.")

    for gi, group in enumerate(groups):
        with st.expander(
            f"Gruppe {gi + 1} — Ähnlichkeit: {group.similarity:.0%}",
            expanded=gi == 0,
        ):
            selected = group.selected_index if group.selected_index is not None else 0
            options = [f"[{s.index}] {s.text[:80]}{'…' if len(s.text) > 80 else ''}" for s in group.sentences]
            choice = st.radio(
                "Behalten:", options, index=selected,
                key=f"soc_rd_group_{gi}", label_visibility="collapsed",
            )
            group.selected_index = options.index(choice)

    _nav_buttons()


# ── Step 5: Segment-Montage ────────────────────────────────────────────────

def _render_step_assembly():
    """Schritt 5: Segmente zusammenfügen + Dauer prüfen."""
    st.subheader("Segment-Montage")

    state = st.session_state["soc_state"]
    settings = collect_settings(_SCHEMA, "soc")

    if not state.sentences:
        st.warning("Bitte vorherige Schritte abschließen.")
        _nav_buttons(can_next=False)
        return

    # Redundanz-Auswahl anwenden
    from modules.social_cutter.redundancy import apply_selections
    kept = apply_selections(state.sentences, state.redundancy_groups)

    # Segmente assemblieren
    from modules.social_cutter.segment_assembly import assemble_segments, estimate_duration

    target_s = settings.get("target_duration_s", 30.0)
    tail_ms = settings.get("tail_ms", 100.0)

    segments = assemble_segments(kept, state.silence_segments, target_duration_s=target_s, tail_ms=tail_ms)
    state.final_segments = segments
    state.save()

    total = estimate_duration(segments)

    # Dauer-Anzeige
    col_dur, col_target = st.columns(2)
    with col_dur:
        color = "normal" if total <= target_s * 1.1 else "off"
        st.metric("Gesamtdauer", f"{total:.1f}s", delta=f"{total - target_s:+.1f}s")
    with col_target:
        st.metric("Zieldauer", f"{target_s:.0f}s")

    if total > target_s * 1.1:
        st.warning(f"Die Montage ist {total - target_s:.1f}s länger als das Ziel. "
                   "Segmente können unten entfernt werden.")

    # Segment-Liste mit Entfernen-Option
    st.divider()
    remove_indices = set()
    for seg in segments:
        col_idx, col_text, col_dur, col_del = st.columns([1, 6, 2, 1])
        with col_idx:
            st.caption(f"#{seg.index}")
        with col_text:
            st.caption(seg.transcript_text[:100] + ("…" if len(seg.transcript_text) > 100 else ""))
        with col_dur:
            st.caption(f"{seg.duration_s:.1f}s")
        with col_del:
            if st.button(":material/delete:", key=f"soc_seg_del_{seg.index}"):
                remove_indices.add(seg.index)

    if remove_indices:
        state.final_segments = [s for s in segments if s.index not in remove_indices]
        state.save()
        st.rerun()

    _nav_buttons(can_next=bool(segments))


# ── Step 6: Zoom / Reframing ──────────────────────────────────────────────

def _render_step_zoom():
    """Schritt 6: Zoom-Tier-Zuweisung + Face Detection."""
    st.subheader("Zoom / Reframing")

    state = st.session_state["soc_state"]
    settings = collect_settings(_SCHEMA, "soc")
    render_settings_panel(_SCHEMA, "soc", expert=st.session_state.get("expert_mode", False),
                          filter_keys=["zoom"])

    if not state.final_segments:
        st.warning("Bitte vorherige Schritte abschließen.")
        _nav_buttons(can_next=False)
        return

    # Zoom bereits zugewiesen?
    has_zoom = any(s.zoom is not None for s in state.final_segments)

    if has_zoom:
        st.success("Zoom-Tiers zugewiesen.")
        _render_zoom_table(state.final_segments)
        _nav_buttons()
        return

    src = state.src_path

    if st.session_state.get("soc_zm_running"):
        st.progress(
            st.session_state.get("soc_zm_progress", 0.0),
            text=st.session_state.get("soc_zm_status", "Starte …"),
        )
        q = st.session_state.get("soc_zm_queue")
        if q:
            while True:
                try:
                    msg = q.get_nowait()
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        st.session_state["soc_zm_progress"] = msg[1]
                        st.session_state["soc_zm_status"] = msg[2]
                    elif isinstance(msg, tuple) and msg[0] == "__RESULT__":
                        state.final_segments = msg[1]
                        state.save()
                        st.session_state["soc_zm_running"] = False
                    elif isinstance(msg, str) and msg.startswith("Fehler"):
                        st.session_state["soc_zm_error"] = msg
                        st.session_state["soc_zm_running"] = False
                except Exception:
                    break
        st.rerun()
    elif st.session_state.get("soc_zm_error"):
        st.error(st.session_state["soc_zm_error"])

    if st.button(
        "Zoom analysieren", icon=":material/zoom_in:", type="primary",
        disabled=st.session_state.get("soc_zm_running", False), key="soc_zm_start",
    ):
        q = queue.Queue()
        st.session_state["soc_zm_running"] = True
        st.session_state["soc_zm_error"] = None
        st.session_state["soc_zm_progress"] = 0.0
        st.session_state["soc_zm_queue"] = q

        tier_config = {
            "wide": settings.get("zoom_wide", 1.0),
            "medium": settings.get("zoom_medium", 1.18),
            "close": settings.get("zoom_close", 1.30),
            "tight": settings.get("zoom_tight", 1.45),
        }
        safe_area = {
            "x": settings.get("safe_x", 0.05),
            "y": settings.get("safe_y", 0.12),
            "w": settings.get("safe_w", 0.90),
            "h": settings.get("safe_h", 0.76),
        }

        def _worker(state_ref, segments, tc, sa, q_):
            def _cb(frac, text):
                q_.put(("progress", frac, text))
            try:
                from modules.social_cutter.zoom_assignment import (
                    analyze_audio_prosody, detect_face_positions, assign_zoom_tiers,
                )
                fps = _probe_fps(state_ref.src_path)

                # Audio-Prosodie auf Clip-Audio (nicht ganze Quelldatei)
                _cb(0.05, "Audio-Prosodie \u2026")
                clip_audio = state_ref.extract_clip_audio()
                prosody = analyze_audio_prosody(
                    clip_audio, segments, state_ref.transcript, progress_cb=_cb,
                )

                # Face Detection auf Quelldatei mit Source-Offset
                _cb(0.5, "Face Detection \u2026")
                faces = detect_face_positions(
                    state_ref.src_path, segments, fps,
                    source_offset_s=state_ref.src_start_s,
                    progress_cb=_cb,
                )

                _cb(0.9, "Zoom-Tiers zuweisen \u2026")
                result = assign_zoom_tiers(segments, prosody, faces,
                                           safe_area=sa, tier_config=tc)
                q_.put(("__RESULT__", result))
            except Exception as e:
                q_.put(f"Fehler: {e}")

        threading.Thread(
            target=_worker,
            args=(state, state.final_segments, tier_config, safe_area, q),
            daemon=True,
        ).start()
        st.rerun()

    _nav_buttons(can_next=has_zoom)


def _render_zoom_table(segments: list):
    """Zeigt Zoom-Übersicht als Tabelle."""
    rows = []
    for seg in segments:
        if seg.zoom:
            rows.append({
                "#": seg.index,
                "Tier": seg.zoom.tier.value.upper(),
                "Scale": f"{seg.zoom.scale:.2f}x",
                "Pan": f"{seg.zoom.pan:.0f}px",
                "Tilt": f"{seg.zoom.tilt:.0f}px",
                "Text": seg.transcript_text[:50] + ("…" if len(seg.transcript_text) > 50 else ""),
            })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)


# ── Step 7: B-Roll ────────────────────────────────────────────────────────

def _collect_broll_categories():
    """Sammelt B-Roll-Kategorien aus State (Resolve-Keywords) oder manuellen Ordnern."""
    state = st.session_state["soc_state"]

    # Aus JSON-State (Resolve-Keywords oder vorheriger Scan)
    if state.broll_categories:
        return state.broll_categories

    # Ordner-basiert (Fallback für Nicht-Resolve-Modus)
    from modules.social_cutter.types import BRollCategory
    cats_raw = st.session_state.get("soc_broll_cats", [])
    categories = []
    for c in cats_raw:
        name = c.get("name", "").strip()
        path = c.get("path", "").strip()
        if name and path and Path(path).exists():
            clip_paths = [
                str(p) for p in Path(path).iterdir()
                if p.suffix.lower() in {".mp4", ".mov", ".mxf", ".avi", ".mkv"}
            ]
            if clip_paths:
                categories.append(BRollCategory(name=name, clip_paths=clip_paths))
    return categories


def _render_step_broll():
    """Schritt 7: B-Roll-Zuordnung."""
    st.subheader("B-Roll")

    state = st.session_state["soc_state"]
    settings = collect_settings(_SCHEMA, "soc")
    render_settings_panel(_SCHEMA, "soc", expert=st.session_state.get("expert_mode", False),
                          filter_keys=["broll"])

    if not state.final_segments:
        st.warning("Bitte vorherige Schritte abschließen.")
        _nav_buttons(can_next=False)
        return

    # B-Roll-Kategorien: Resolve-Keywords oder Ordner
    categories = _collect_broll_categories()
    if not categories:
        st.info("Keine B-Roll-Kategorien vorhanden. "
                "In Schritt 0 Media Pool scannen oder Ordner anlegen.")
        _nav_buttons()
        return

    st.caption(f"{len(categories)} Kategorien, "
               f"{sum(len(c.clip_paths) for c in categories)} Clips")

    # Bereits zugewiesen?
    has_broll = any(s.broll is not None for s in state.final_segments)

    if has_broll:
        st.success("B-Roll-Vorschläge erstellt.")
        _render_broll_suggestions(state.final_segments)
        _nav_buttons()
        return

    if st.session_state.get("soc_br_running"):
        st.progress(
            st.session_state.get("soc_br_progress", 0.0),
            text=st.session_state.get("soc_br_status", "Starte …"),
        )
        q = st.session_state.get("soc_br_queue")
        if q:
            while True:
                try:
                    msg = q.get_nowait()
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        st.session_state["soc_br_progress"] = msg[1]
                        st.session_state["soc_br_status"] = msg[2]
                    elif isinstance(msg, tuple) and msg[0] == "__RESULT__":
                        state.final_segments = msg[1]
                        state.save()
                        st.session_state["soc_br_running"] = False
                    elif isinstance(msg, str) and msg.startswith("Fehler"):
                        st.session_state["soc_br_error"] = msg
                        st.session_state["soc_br_running"] = False
                except Exception:
                    break
        st.rerun()
    elif st.session_state.get("soc_br_error"):
        st.error(st.session_state["soc_br_error"])

    if st.button(
        "B-Roll zuordnen", icon=":material/movie:", type="primary",
        disabled=st.session_state.get("soc_br_running", False), key="soc_br_start",
    ):
        q = queue.Queue()
        st.session_state["soc_br_running"] = True
        st.session_state["soc_br_error"] = None
        st.session_state["soc_br_progress"] = 0.0
        st.session_state["soc_br_queue"] = q

        def _worker(segs, cats, s, q_):
            def _cb(frac, text):
                q_.put(("progress", frac, text))
            try:
                from modules.social_cutter.broll_matching import suggest_broll_placements
                result = suggest_broll_placements(
                    segs, cats,
                    max_broll_density=s.get("max_broll_density", 0.4),
                    min_segment_duration_s=s.get("min_broll_segment_s", 2.0),
                    enable_splitscreen=s.get("enable_splitscreen", False),
                    splitscreen_threshold_s=s.get("splitscreen_threshold_s", 3.0),
                    progress_cb=_cb,
                )
                q_.put(("__RESULT__", result))
            except Exception as e:
                q_.put(f"Fehler: {e}")

        threading.Thread(
            target=_worker,
            args=(state.final_segments, categories, settings, q),
            daemon=True,
        ).start()
        st.rerun()

    _nav_buttons(can_next=False)


def _render_broll_suggestions(segments: list):
    """Zeigt B-Roll-Vorschläge mit Accept/Reject."""
    for seg in segments:
        if seg.broll is None:
            continue
        b = seg.broll
        col_seg, col_cat, col_clip, col_score, col_act = st.columns([1, 2, 3, 1, 1])
        with col_seg:
            st.caption(f"#{seg.index}")
        with col_cat:
            st.caption(b.category_name)
        with col_clip:
            st.caption(Path(b.clip_path).name)
        with col_score:
            st.caption(f"{b.match_score:.0%}")
        with col_act:
            if st.button(":material/close:", key=f"soc_br_reject_{seg.index}"):
                seg.broll = None
                st.rerun()


# ── Step 8: Voice Leveler ────────────────────────────────────────────────────

def _render_step_voice_leveler():
    """Schritt 8: Voice Leveler Einstellungen."""
    st.subheader("Voice Leveler")

    settings = collect_settings(_SCHEMA, "soc")
    render_settings_panel(_SCHEMA, "soc", expert=st.session_state.get("expert_mode", False),
                          filter_keys=["voice_leveler"])

    run_vl = settings.get("run_voice_leveler", True)
    preset = settings.get("leveler_preset", "loud")

    if run_vl:
        st.info(f"Voice Leveler wird mit Preset **{preset}** angewendet.")
    else:
        st.info("Voice Leveler ist deaktiviert.")

    _nav_buttons()


# ── Step 9: Anwenden ──────────────────────────────────────────────────────

def _render_step_apply():
    """Schritt 9: Zusammenfassung + auf Timeline anwenden."""
    st.subheader("Auf Timeline anwenden")

    state = st.session_state["soc_state"]
    settings = collect_settings(_SCHEMA, "soc")

    if not state.final_segments:
        st.warning("Keine Segmente vorhanden.")
        _nav_buttons(can_next=False)
        return

    # Zusammenfassung
    from modules.social_cutter.segment_assembly import estimate_duration

    total = estimate_duration(state.final_segments)
    n_zoom = sum(1 for s in state.final_segments if s.zoom is not None)
    n_broll = sum(1 for s in state.final_segments if s.broll is not None)

    st.markdown("### Zusammenfassung")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Segmente", len(state.final_segments))
    with col2:
        st.metric("Dauer", f"{total:.1f}s")
    with col3:
        st.metric("Zoom", f"{n_zoom}/{len(state.final_segments)}")
    with col4:
        st.metric("B-Roll", n_broll)

    if settings.get("run_voice_leveler", True):
        st.caption(f"Voice Leveler: **{settings.get('leveler_preset', 'loud')}**")

    st.divider()

    # Anwenden-Status
    if st.session_state.get("soc_apply_running"):
        st.progress(
            st.session_state.get("soc_apply_progress", 0.0),
            text=st.session_state.get("soc_apply_status", "Starte …"),
        )
        q = st.session_state.get("soc_apply_queue")
        if q:
            while True:
                try:
                    msg = q.get_nowait()
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        st.session_state["soc_apply_progress"] = msg[1]
                        st.session_state["soc_apply_status"] = msg[2]
                    elif isinstance(msg, tuple) and msg[0] == "__DONE__":
                        st.session_state["soc_apply_running"] = False
                        st.session_state["soc_apply_done"] = True
                        st.session_state["soc_apply_result"] = msg[1]
                    elif isinstance(msg, str) and msg.startswith("Fehler"):
                        st.session_state["soc_apply_error"] = msg
                        st.session_state["soc_apply_running"] = False
                except Exception:
                    break
        st.rerun()
    elif st.session_state.get("soc_apply_error"):
        st.error(st.session_state["soc_apply_error"])
    elif st.session_state.get("soc_apply_done"):
        result = st.session_state.get("soc_apply_result", {})
        st.success(
            f"Timeline angepasst: "
            f"{result.get('zoom_count', 0)} Zoom-Clips, "
            f"{result.get('broll_count', 0)} B-Roll-Clips"
        )
        _nav_buttons(can_back=True, can_next=False)
        return

    if st.button(
        "Auf Timeline anwenden", icon=":material/check_circle:", type="primary",
        key="soc_apply_start",
    ):
        q = queue.Queue()
        st.session_state["soc_apply_running"] = True
        st.session_state["soc_apply_error"] = None
        st.session_state["soc_apply_progress"] = 0.0
        st.session_state["soc_apply_queue"] = q

        def _worker(segments, s, q_):
            def _cb(frac, text):
                q_.put(("progress", frac, text))
            try:
                result = {}
                fps = _probe_fps(state.src_path)

                # Zoom anwenden
                _cb(0.2, "Zoom-Parameter setzen …")
                try:
                    from resolve_bridge.social_cutter import apply_zoom_params
                    result["zoom_count"] = apply_zoom_params(segments, fps)
                except Exception as e:
                    _log.warning("Zoom anwenden fehlgeschlagen: %s", e)
                    result["zoom_count"] = 0

                # B-Roll platzieren
                _cb(0.5, "B-Roll platzieren …")
                try:
                    from resolve_bridge.social_cutter import place_broll
                    result["broll_count"] = place_broll(segments, fps)
                except Exception as e:
                    _log.warning("B-Roll platzieren fehlgeschlagen: %s", e)
                    result["broll_count"] = 0

                # Voice Leveler
                if s.get("run_voice_leveler", True):
                    _cb(0.7, "Voice Leveler …")
                    try:
                        from modules.voice_leveler import build_filterchain, run_ffmpeg_processing
                        preset = s.get("leveler_preset", "loud")
                        # Voice Leveler arbeitet auf exportiertem Audio
                        # Hier nur Hinweis — konkreter Export/Re-Import via Resolve
                        _log.info("Voice Leveler Preset: %s (manueller Export empfohlen)", preset)
                    except ImportError:
                        _log.warning("Voice Leveler nicht verfügbar")

                _cb(1.0, "Fertig.")
                q_.put(("__DONE__", result))
            except Exception as e:
                q_.put(f"Fehler: {e}")

        threading.Thread(
            target=_worker,
            args=(state.final_segments, settings, q),
            daemon=True,
        ).start()
        st.rerun()

    _nav_buttons(can_back=True, can_next=False)


# ── Main ─────────────────────────────────────────────────────────────────────

_init_state()

st.title("Social Cutter")
_render_step_bar()
st.divider()

_step = st.session_state["soc_step"]

# Reset in Sidebar
with st.sidebar:
    if st.button("Pipeline zurücksetzen", icon=":material/restart_alt:", key="soc_reset"):
        from modules.social_cutter.types import SocialCutterState
        SocialCutterState.clear()
        st.session_state["soc_step"] = 0
        st.session_state["soc_state"] = SocialCutterState()
        st.rerun()

if _step == 0:
    _render_step_input()
elif _step == 1:
    _render_step_silence()
elif _step == 2:
    _render_step_transcription()
elif _step == 3:
    _render_step_phrase_boundaries()
elif _step == 4:
    _render_step_redundancy()
elif _step == 5:
    _render_step_assembly()
elif _step == 6:
    _render_step_zoom()
elif _step == 7:
    _render_step_broll()
elif _step == 8:
    _render_step_voice_leveler()
elif _step == 9:
    _render_step_apply()
