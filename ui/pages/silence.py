"""
Silence Cutter — Composite multi-track silence detection with marker preview
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
import math
import threading
import queue
from pathlib import Path

_log = logging.getLogger("rtk")
from types import SimpleNamespace

import streamlit as st


# ── Schwellwert-Analyse ────────────────────────────────────────────────────────

def _sc_load_audio_numpy(src_path: str, max_sec: int = 0) -> tuple:
    """Lädt Audio via ffmpeg als numpy float32 mono 16 kHz. Gibt (data, sr) zurück."""
    import subprocess, numpy as np
    args = ["ffmpeg", "-y", "-i", src_path, "-ac", "1", "-ar", "16000"]
    if max_sec:
        args += ["-t", str(max_sec)]
    args += ["-f", "f32le", "-"]
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr[-200:].decode(errors='replace')}")
    data = __import__("numpy").frombuffer(r.stdout, dtype=__import__("numpy").float32).copy()
    return data, 16000


def _sc_rms_frames(data, sr: int, frame_ms: int = 20) -> "np.ndarray":
    import numpy as np
    fs = int(sr * frame_ms / 1000)
    n  = len(data) // fs
    frames = data[:n * fs].reshape(n, fs)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    with np.errstate(divide="ignore"):
        db = 20 * np.log10(np.where(rms > 1e-7, rms, 1e-7))
    return db[db > -75]  # digitale Stille rausfiltern


def _sc_suggest_fast(src_path: str, progress_cb=None) -> dict:
    """Schwellwert-Vorschlag via k-means 2-Cluster auf RMS-Werten."""
    import numpy as np

    if progress_cb: progress_cb(0.1, "Audio laden …")
    data, sr = _sc_load_audio_numpy(src_path, max_sec=300)

    if progress_cb: progress_cb(0.5, "RMS-Analyse …")
    db = _sc_rms_frames(data, sr)
    if len(db) < 30:
        raise RuntimeError("Zu wenig auswertbare Frames")

    if progress_cb: progress_cb(0.8, "Cluster-Analyse …")

    # ── k-means 2-Cluster (kein scipy nötig) ──────────────────────────────────
    # Init: 25. und 75. Perzentil als Startzentroide
    c0, c1 = float(np.percentile(db, 25)), float(np.percentile(db, 75))
    for _ in range(40):
        mid    = (c0 + c1) / 2
        lo     = db[db <  mid]
        hi     = db[db >= mid]
        new_c0 = float(lo.mean()) if len(lo) > 0 else c0
        new_c1 = float(hi.mean()) if len(hi) > 0 else c1
        if abs(new_c0 - c0) < 0.05 and abs(new_c1 - c1) < 0.05:
            break
        c0, c1 = new_c0, new_c1

    boundary     = (c0 + c1) / 2
    noise_frames  = db[db <  boundary]
    speech_frames = db[db >= boundary]

    noise_floor  = float(np.median(noise_frames))  if len(noise_frames)  > 0 else c0
    quiet_speech = float(np.percentile(speech_frames, 10)) if len(speech_frames) > 0 else c1
    threshold    = int(round((noise_floor + quiet_speech) / 2))
    threshold    = max(-60, min(-10, threshold))

    # ── Konfidenz ──────────────────────────────────────────────────────────────
    # Fisher-ähnliches Maß: Zentroid-Abstand / mittlere Cluster-Streuung
    # Hoher Wert = Cluster gut getrennt, niedriger Wert = Cluster überlappen stark
    separation   = c1 - c0
    std0 = float(noise_frames.std())  if len(noise_frames)  > 1 else 1.0
    std1 = float(speech_frames.std()) if len(speech_frames) > 1 else 1.0
    fisher_score = separation / max((std0 + std1) / 2, 0.1)

    if fisher_score >= 2.5:
        confidence      = "hoch"
        confidence_note = f"Cluster-Abstand: {separation:.0f} dB, Fisher-Score: {fisher_score:.1f}"
    elif fisher_score >= 1.5:
        confidence      = "mittel"
        confidence_note = (
            f"Cluster-Abstand: {separation:.0f} dB, Fisher-Score: {fisher_score:.1f} — "
            "Ergebnis prüfen, Whisper für mehr Genauigkeit"
        )
    else:
        confidence      = "niedrig"
        confidence_note = (
            f"Cluster-Abstand: {separation:.0f} dB, Fisher-Score: {fisher_score:.1f} — "
            "Verteilung unimodal oder stark überlappend, Whisper empfohlen"
        )

    return {"threshold": threshold,
            "noise_floor": round(noise_floor, 1),
            "quiet_speech": round(quiet_speech, 1),
            "confidence": confidence,
            "confidence_note": confidence_note}


def _sc_suggest_whisper(src_path: str, progress_cb=None) -> dict:
    """Schwellwert-Vorschlag via Whisper-Segmentgrenzen + RMS-Messung."""
    import numpy as np

    if progress_cb: progress_cb(0.05, "Audio laden …")
    data, sr = _sc_load_audio_numpy(src_path)

    if progress_cb: progress_cb(0.15, "Whisper-Modell laden …")
    import whisper as _whisper
    model = _whisper.load_model("tiny")

    if progress_cb: progress_cb(0.3, "Transkription läuft …")
    result   = model.transcribe(src_path, task="transcribe",
                                word_timestamps=False, verbose=False)
    segments = result.get("segments", [])

    if progress_cb: progress_cb(0.85, "Pegel messen …")

    def _seg_db(t0, t1):
        chunk = data[int(t0 * sr): int(t1 * sr)]
        if len(chunk) < sr * 0.05:
            return None
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        return 20 * np.log10(rms) if rms > 1e-7 else None

    duration     = len(data) / sr
    speech_rms, gap_rms = [], []
    prev = 0.0
    for i, seg in enumerate(segments):
        # Nur interne Lücken (zwischen zwei Segmenten) für Noise Floor nutzen —
        # nie die Lücke nach dem letzten Segment, da Whisper dort oft früh stoppt
        if seg["start"] - prev > 0.25 and i > 0:
            v = _seg_db(prev + 0.05, seg["start"] - 0.05)
            if v is not None:
                gap_rms.append(v)
        v = _seg_db(seg["start"], seg["end"])
        if v is not None:
            speech_rms.append(v)
        prev = seg["end"]
    # Trailing gap bewusst weggelassen

    if not speech_rms:
        raise RuntimeError("Whisper erkannte keine Sprache")

    # Coverage-Warnung wenn Whisper < 30 % der Datei abgedeckt hat
    covered_s  = sum(seg["end"] - seg["start"] for seg in segments)
    coverage   = covered_s / duration if duration > 0 else 0.0
    low_coverage = coverage < 0.30

    noise_floor  = float(np.median(gap_rms))     if gap_rms    else float(np.percentile(speech_rms, 5))
    quiet_speech = float(np.percentile(speech_rms, 10))
    threshold    = int(round((noise_floor + quiet_speech) / 2))
    threshold    = max(-60, min(-10, threshold))

    result = {"threshold": threshold,
              "noise_floor": round(noise_floor, 1),
              "quiet_speech": round(quiet_speech, 1),
              "coverage": round(coverage * 100, 0)}
    if low_coverage:
        result["coverage_warning"] = (
            f"Whisper hat nur {coverage*100:.0f} % der Datei als Sprache erkannt — "
            "möglicherweise unvollständige Transkription (lange Pausen, Fremdsprache). "
            "Schwellwert manuell prüfen."
        )
    return result


@st.dialog("Schwellwert analysieren")
def _sc_thresh_dialog():
    """Progress-Dialog für die Schwellwert-Analyse."""
    if "sc_thresh_queue" in st.session_state:
        _tq = st.session_state["sc_thresh_queue"]
        while True:
            try:
                _msg = _tq.get_nowait()
                if isinstance(_msg, tuple) and _msg[0] == "__THRESH_RESULT__":
                    st.session_state["sc_thresh_result"]   = _msg[1]
                elif isinstance(_msg, tuple) and len(_msg) == 3 and _msg[0] == "progress":
                    st.session_state["sc_thresh_progress"] = _msg[1]
                    st.session_state["sc_thresh_status"]   = _msg[2]
                elif isinstance(_msg, str) and _msg.startswith("__DONE__"):
                    st.session_state["sc_thresh_running"]  = False
                elif isinstance(_msg, str) and _msg.startswith("Fehler"):
                    st.session_state["sc_thresh_error"]    = _msg
                    st.session_state["sc_thresh_running"]  = False
            except Exception:
                break

    running = st.session_state.get("sc_thresh_running", False)
    result  = st.session_state.get("sc_thresh_result")
    error   = st.session_state.get("sc_thresh_error")

    if running:
        progress = st.session_state.get("sc_thresh_progress", 0.0)
        status   = st.session_state.get("sc_thresh_status", "Starte …")
        st.progress(progress, text=status)
        st.rerun()
    elif error:
        st.error(error)
        if st.button("Schließen", use_container_width=True):
            st.session_state["sc_thresh_dialog_open"] = False
            st.session_state.pop("sc_thresh_error", None)
            st.rerun()
    elif result:
        st.success(
            f"**Vorschlag: {result['threshold']} dB**\n\n"
            f"Rauschboden: **{result['noise_floor']} dB** · "
            f"Leise Sprache: **{result['quiet_speech']} dB**"
        )
        if result.get("coverage_warning"):
            st.warning(
                f":material/warning: {result['coverage_warning']}",
                icon=None,
            )
        _conf = result.get("confidence")
        if _conf == "niedrig":
            st.warning(
                f":material/warning: Konfidenz **niedrig** — {result.get('confidence_note', '')}",
                icon=None,
            )
        elif _conf == "mittel":
            st.info(
                f":material/info: Konfidenz **mittel** — {result.get('confidence_note', '')}",
                icon=None,
            )
        elif _conf == "hoch":
            st.caption(f":material/check_circle: Konfidenz hoch — {result.get('confidence_note', '')}")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Übernehmen", icon=":material/check:", type="primary",
                         use_container_width=True, key="sc_thresh_apply"):
                st.session_state["_sc_thresh_pending"]    = result["threshold"]
                st.session_state["sc_thresh_result"]      = None
                st.session_state["sc_thresh_dialog_open"] = False
                st.rerun()
        with col2:
            if st.button("Schließen", use_container_width=True, key="sc_thresh_close"):
                st.session_state["sc_thresh_dialog_open"] = False
                st.session_state["sc_thresh_result"]      = None
                st.rerun()


def _render_threshold_suggest(sample_path: str | None) -> None:
    """
    UI-Expander: Schwellwert automatisch ermitteln.
    sample_path = Audiodatei die analysiert wird (None → deaktiviert).
    Schreibt _sc_thresh_pending wenn User „Übernehmen" klickt.
    """
    with st.expander(":material/auto_fix_high: Schwellwert automatisch ermitteln"):
        if not sample_path or not Path(sample_path).exists():
            st.caption("Bitte zuerst eine Datei auswählen.")
            return

        st.caption(f"Datei: `{Path(sample_path).name}`")

        _whisper_ok = True
        try:
            import whisper as _w  # noqa: F401
        except ImportError:
            _whisper_ok = False

        _busy = st.session_state.get("sc_thresh_running", False)
        col_a, col_b = st.columns(2)
        with col_a:
            fast_btn = st.button(
                "Schnell analysieren", icon=":material/bolt:",
                use_container_width=True, key="sc_thresh_fast_btn",
                disabled=_busy,
            )
        with col_b:
            whisper_btn = st.button(
                "Genauer (Whisper)", icon=":material/mic:",
                use_container_width=True, key="sc_thresh_whisper_btn",
                disabled=not _whisper_ok or _busy,
                help=None if _whisper_ok else "Whisper ist nicht installiert",
            )

        if fast_btn or whisper_btn:
            mode = "whisper" if whisper_btn else "fast"
            _q   = queue.Queue()
            st.session_state["sc_thresh_running"]     = True
            st.session_state["sc_thresh_result"]      = None
            st.session_state["sc_thresh_error"]       = None
            st.session_state["sc_thresh_progress"]    = 0.0
            st.session_state["sc_thresh_status"]      = "Starte …"
            st.session_state["sc_thresh_queue"]       = _q
            st.session_state["sc_thresh_dialog_open"] = True

            def _worker(path, m, q):
                def _cb(frac, text):
                    q.put(("progress", frac, text))
                try:
                    fn  = _sc_suggest_whisper if m == "whisper" else _sc_suggest_fast
                    res = fn(path, progress_cb=_cb)
                    q.put(("__THRESH_RESULT__", res))
                    q.put("__DONE__0")
                except Exception as _e:
                    q.put(f"Fehler: {_e}")
                    q.put("__DONE__1")

            threading.Thread(
                target=_worker, args=(sample_path, mode, _q), daemon=True
            ).start()
            st.rerun()

    # Dialog außerhalb des Expanders öffnen
    if st.session_state.get("sc_thresh_dialog_open"):
        _sc_thresh_dialog()


# ── Marker-Ergebnis-Dialog (Resolve-Modus) ─────────────────────────────────────

@st.dialog("Analyse abgeschlossen")
def _marker_result_dialog():
    n       = st.session_state.get("sc_marker_dialog_count", 0)
    col     = st.session_state.get("sc_marker_color", "red")
    total_s = st.session_state.get("sc_marker_dialog_total_s", 0.0)

    if n > 0:
        st.success(f"**{n} Stille-Bereiche** wurden in der Timeline markiert.")
        st.caption(f"Gesamtdauer markierter Stille: **{total_s:.1f}s**")
    else:
        st.info("Keine Stille gefunden — Schwellwert oder Mindestdauer anpassen.")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Einstellungen ändern", use_container_width=True):
            st.session_state.sc_marker_dialog_open = False
            st.rerun()
    with col2:
        if n > 0:
            if st.button(
                "Stille löschen", icon=":material/delete:",
                use_container_width=True, type="primary",
            ):
                st.session_state.sc_cut_triggered      = True
                st.session_state.sc_marker_dialog_open = False
                st.rerun()


st.title(":material/volume_off: Silence Cutter")
st.caption("Erkennt Stille-Pausen in Audioaufnahmen und markiert sie. Das Ergebnis kann direkt als neue Timeline exportiert oder als AAF-Datei gespeichert werden.")

# ── Resolve connection (optional) ─────────────────────────────────────────────

_resolve_ok = False
resolve = tl = None
_project_name = ""

try:
    from resolve_bridge.connection import get_resolve
    from resolve_bridge.timeline_reader import read_timeline
    from resolve_bridge.project_settings import load_page, save_page

    resolve  = get_resolve()
    tl       = read_timeline()
    _project_name = resolve.GetProjectManager().GetCurrentProject().GetName()
    _resolve_ok   = True
except Exception:
    pass

# ── Quelle wählen ─────────────────────────────────────────────────────────────

if _resolve_ok:
    source_mode = st.radio(
        "Quelle", ["Aktive Timeline", "Datei-Pfad"], horizontal=True,
        key="sc_source_mode",
    )
else:
    source_mode = "Datei-Pfad"

# ── Projektabhängige Einstellungen ─────────────────────────────────────────────

_PAGE = "silence_cutter"
_DEFAULTS = {
    "sc_threshold_db":  -40,
    "sc_min_silence_s": 0.8,
    "sc_pre_pad_ms":    150,
    "sc_post_pad_ms":   150,
    "sc_marker_color":  "red",
    "sc_gaps_silence":  True,
}

if _resolve_ok:
    _need_load = (
        st.session_state.get("_sc_loaded_project") != _project_name
        or any(_k not in st.session_state for _k in _DEFAULTS)
    )
    if _need_load:
        _saved = load_page(_project_name, _PAGE)
        for _k, _default in _DEFAULTS.items():
            st.session_state[_k] = _saved.get(_k, _default)
        st.session_state["_sc_loaded_project"] = _project_name
else:
    for _k, _default in _DEFAULTS.items():
        if _k not in st.session_state:
            st.session_state[_k] = _default

# Pending-Schwellwert vor dem ersten Slider-Render eintragen
if "_sc_thresh_pending" in st.session_state:
    st.session_state.pop("sc_threshold_db", None)
    st.session_state["sc_threshold_db"] = st.session_state.pop("_sc_thresh_pending")

# ══════════════════════════════════════════════════════════════════════════════
# RESOLVE TIMELINE MODE
# ══════════════════════════════════════════════════════════════════════════════

if source_mode == "Aktive Timeline":

    # ── Timeline info ──────────────────────────────────────────────────────────

    col1, col2, col3 = st.columns(3)
    col1.metric("Timeline", tl.timeline_name)
    col2.metric("FPS", int(tl.fps))
    col3.metric("Dauer", f"{(tl.timeline_end - tl.timeline_start) / tl.fps / 60:.1f} min")


    # ── Track selection ────────────────────────────────────────────────────────

    st.divider()
    st.subheader("Audio-Spuren")

    _VIDEO_EXT = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}
    audio_tracks_with_clips = {
        idx: clips
        for idx, clips in tl.audio_tracks.items()
        if any(c.file_path for c in clips)
    }

    if not audio_tracks_with_clips:
        st.warning("Keine Audio-Spuren mit Clips gefunden.")
        st.stop()

    def _track_label(idx, clips):
        n    = len(clips)
        name = tl.audio_track_names.get(idx, "Audio")
        has_video = any(Path(c.file_path).suffix.lower() in _VIDEO_EXT for c in clips if c.file_path)
        tag = " · Video→Audio" if has_video else ""
        return f"A{idx} — {name}  ({n} Clip{'s' if n != 1 else ''}){tag}"

    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        selected_tracks = st.multiselect(
            "Spuren für Composite-Analyse",
            options=list(audio_tracks_with_clips.keys()),
            default=list(audio_tracks_with_clips.keys()),
            format_func=lambda x: _track_label(x, audio_tracks_with_clips[x]),
        )
    with col_t2:
        st.markdown("<br>", unsafe_allow_html=True)
        gaps_are_silence = st.toggle(
            "Lücken = Stille",
            key="sc_gaps_silence",
            help="An: Lücken zwischen Clips auf dieser Spur gelten als Stille.\nAus: Nur tatsächlich analysierte Audiobereiche fließen in die Composite-Detection ein.",
        )

    if not selected_tracks:
        st.warning("Mindestens eine Spur auswählen.")
        st.stop()

    # ── Settings ───────────────────────────────────────────────────────────────

    st.divider()
    st.subheader("Einstellungen")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        threshold_db = st.slider(
            "Schwellwert (dB)", -60, -10, key="sc_threshold_db",
            value=int(st.session_state.get("sc_threshold_db", _DEFAULTS["sc_threshold_db"])),
            help="Signale unterhalb dieses Pegels gelten als Stille",
        )
        min_silence_s = st.slider(
            "Mindestdauer Stille (s)", 0.1, 3.0, step=0.1, key="sc_min_silence_s",
            value=float(st.session_state.get("sc_min_silence_s", _DEFAULTS["sc_min_silence_s"])),
            help="Kürzere Pausen werden ignoriert",
        )
    with col_s2:
        pre_pad_ms = st.slider(
            "Pre-Pad (ms)", 0, 500, step=25, key="sc_pre_pad_ms",
            value=int(st.session_state.get("sc_pre_pad_ms", _DEFAULTS["sc_pre_pad_ms"])),
            help="Puffer am Anfang jeder Stille — wird NICHT geschnitten",
        )
        post_pad_ms = st.slider(
            "Post-Pad (ms)", 0, 500, step=25, key="sc_post_pad_ms",
            value=int(st.session_state.get("sc_post_pad_ms", _DEFAULTS["sc_post_pad_ms"])),
            help="Puffer am Ende jeder Stille — wird NICHT geschnitten",
        )

    MARKER_COLOR_OPTIONS = ["red", "pink", "yellow", "green", "blue", "purple", "cyan"]
    marker_color = st.selectbox("Marker-Farbe", MARKER_COLOR_OPTIONS, key="sc_marker_color")

    save_page(_project_name, _PAGE, {k: st.session_state[k] for k in _DEFAULTS})

    # Repräsentativen Clip für Threshold-Analyse ermitteln
    _tl_sample_path = None
    if selected_tracks:
        _first_clips = audio_tracks_with_clips.get(selected_tracks[0], [])
        if _first_clips and _first_clips[0].file_path:
            _tl_sample_path = _first_clips[0].file_path

    _render_threshold_suggest(_tl_sample_path)

    # ── Analyse ────────────────────────────────────────────────────────────────

    st.divider()
    st.subheader("Analyse")

    def _run_analysis(params: dict, q: queue.Queue):
        try:
            from resolve_bridge.silence_cutter import analyze_composite_silence
            from resolve_bridge.markers import add_marker, delete_markers_by_color

            q.put("Starte Analyse …")
            try:
                delete_markers_by_color(params["marker_color"])
                q.put(f"  Alte {params['marker_color']}-Marker gelöscht.")
            except Exception as e:
                _log.exception("Silence Cutter: Marker löschen fehlgeschlagen")
                q.put(f"  ⚠ Marker löschen: {e}")

            segments = analyze_composite_silence(
                audio_tracks     = params["audio_tracks"],
                selected_tracks  = params["selected_tracks"],
                fps              = params["fps"],
                tl_start         = params["tl_start"],
                tl_end           = params["tl_end"],
                threshold_db     = params["threshold_db"],
                min_silence_s    = params["min_silence_s"],
                pre_pad_s        = params["pre_pad_s"],
                post_pad_s       = params["post_pad_s"],
                gaps_are_silence = params["gaps_are_silence"],
                progress_cb      = q.put,
            )

            q.put(f"\n{len(segments)} Stille-Bereiche erkannt.")

            if segments:
                total_s = sum(d for _, d in segments) / params["fps"]
                q.put(f"Setze {len(segments)} Duration-Marker …")
                ok_count = 0
                for frame, dur in segments:
                    result = add_marker(
                        frame=frame, color=params["marker_color"],
                        name="Silence", note=f"{dur / params['fps']:.2f}s", duration=dur,
                    )
                    if result:
                        ok_count += 1
                if ok_count == 0:
                    q.put(f"⚠ AddMarker schlug fehl (0/{len(segments)}). Erster Frame: {segments[0][0]}, tl_start={params['tl_start']}")
                elif ok_count < len(segments):
                    q.put(f"⚠ Nur {ok_count}/{len(segments)} Marker gesetzt.")
                q.put(f"✓ {ok_count} Marker gesetzt — {total_s:.1f}s werden gekürzt.")
            else:
                q.put("Keine Pausen gefunden. Schwellwert anpassen?")

            q.put(("__RESULT__", segments))
            q.put("__DONE__0")
        except Exception as e:
            _log.exception("Silence Cutter: Analyse fehlgeschlagen")
            q.put(f"Fehler: {e}")
            q.put("__DONE__1")

    analyse_btn = st.button(
        "Analysieren & Marker setzen", icon=":material/search:", type="primary",
        disabled=st.session_state.get("silence_running", False),
        use_container_width=True,
    )

    if analyse_btn:
        st.session_state.silence_running          = True
        st.session_state.silence_log              = []
        st.session_state.silence_results          = []
        st.session_state.sc_pending_marker_dialog = True
        st.session_state.sc_analysis_fps          = tl.fps
        st.session_state.sc_marker_dialog_open    = False
        q = queue.Queue()
        st.session_state.silence_queue = q
        threading.Thread(
            target=_run_analysis,
            args=({
                "audio_tracks":     tl.audio_tracks,
                "selected_tracks":  selected_tracks,
                "fps":              tl.fps,
                "tl_start":         tl.timeline_start,
                "tl_end":           tl.timeline_end,
                "threshold_db":     threshold_db,
                "min_silence_s":    min_silence_s,
                "pre_pad_s":        pre_pad_ms / 1000,
                "post_pad_s":       post_pad_ms / 1000,
                "gaps_are_silence": gaps_are_silence,
                "marker_color":     marker_color,
            }, q),
            daemon=True,
        ).start()
        st.rerun()

    # Analyse fertig → Dialog einmalig öffnen
    if (not st.session_state.get("silence_running")
            and st.session_state.get("sc_pending_marker_dialog")):
        _done_results = st.session_state.get("silence_results", [])
        _done_fps     = st.session_state.get("sc_analysis_fps", 25.0)
        st.session_state.sc_marker_dialog_count   = len(_done_results)
        st.session_state.sc_marker_dialog_total_s = (
            sum(d for _, d in _done_results) / _done_fps if _done_results else 0.0
        )
        st.session_state.sc_pending_marker_dialog = False
        st.session_state.sc_marker_dialog_open    = True

    if st.session_state.get("sc_marker_dialog_open"):
        _marker_result_dialog()

    # ── Cut section ────────────────────────────────────────────────────────────

    results = st.session_state.get("silence_results", [])
    if results:
        st.divider()
        st.subheader("Schneiden")

        total_s = sum(d for _, d in results) / tl.fps
        col_r1, col_r2 = st.columns(2)
        col_r1.metric("Erkannte Pausen", len(results))
        col_r2.metric("Einsparung", f"{total_s:.1f}s")

        _default_tl_name = f"{tl.timeline_name} (cut)"
        new_tl_name = st.text_input(
            "Name der neuen Timeline", value=_default_tl_name,
        )
        st.warning(
            "**Cut now** erstellt eine neue Timeline ohne die erkannten Pausen. "
            "Die originale Timeline bleibt erhalten."
        )
        cut_btn = st.button(
            "Cut now", icon=":material/content_cut:", type="primary",
            disabled=st.session_state.get("silence_running", False),
            use_container_width=True,
        )

        if cut_btn or st.session_state.get("sc_cut_triggered"):
            st.session_state.sc_cut_triggered = False
            st.session_state.silence_running  = True
            st.session_state.silence_log      = []
            q = queue.Queue()
            st.session_state.silence_queue = q

            def _run_cut(params, q):
                try:
                    from resolve_bridge.silence_cutter import rebuild_timeline_without_silences
                    q.put(f"Erstelle Timeline '{params['new_tl_name']}' …")
                    rebuild_timeline_without_silences(
                        resolve          = params["resolve"],
                        source_tl_name   = params["source_tl_name"],
                        new_tl_name      = params["new_tl_name"],
                        selected_tracks  = params["selected_tracks"],
                        silence_segments = params["segments"],
                        progress_cb      = q.put,
                    )
                    q.put(f"\n✓ Timeline '{params['new_tl_name']}' erstellt und aktiviert.")
                    q.put("__DONE__0")
                except Exception as e:
                    _log.exception("Silence Cutter: Timeline-Erstellung fehlgeschlagen")
                    q.put(f"Fehler: {e}")
                    q.put("__DONE__1")

            threading.Thread(
                target=_run_cut,
                args=({
                    "resolve":         resolve,
                    "source_tl_name":  tl.timeline_name,
                    "new_tl_name":     new_tl_name.strip() or f"{tl.timeline_name} (cut)",
                    "selected_tracks": selected_tracks,
                    "segments":        results,
                }, q),
                daemon=True,
            ).start()
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DATEI-PFAD MODE
# ══════════════════════════════════════════════════════════════════════════════

else:

    # ── Datei auswählen ───────────────────────────────────────────────────────

    st.divider()
    st.subheader("Datei auswählen")

    _AUDIO_EXT = {".wav", ".mp3", ".aif", ".aiff", ".m4a", ".flac"}
    _VIDEO_EXT = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}
    _ALL_EXT   = _AUDIO_EXT | _VIDEO_EXT

    col_fp1, col_fp2 = st.columns([3, 1])
    with col_fp2:
        st.write("")
        if st.button("", icon=":material/folder_open:", use_container_width=True, key="sc_browse"):
            import subprocess as _sp_dlg
            try:
                _r = _sp_dlg.run(
                    ["osascript", "-e",
                     'POSIX path of (choose file with prompt "Audio- oder Videodatei auswählen")'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    st.session_state["sc_file_path"] = _r.stdout.strip()
            except Exception:
                pass
    with col_fp1:
        _file_path = st.text_input(
            "Dateipfad", key="sc_file_path",
            placeholder="/Volumes/Daten/Interview.mp4",
        )

    _src = Path(_file_path) if _file_path else None
    if _src and not _src.exists():
        st.error("Datei nicht gefunden.")
        st.stop()
    if _src and _src.suffix.lower() not in _ALL_EXT:
        st.error(f"Nicht unterstütztes Format: {_src.suffix}")
        st.stop()

    # ── Settings ───────────────────────────────────────────────────────────────

    st.divider()
    st.subheader("Einstellungen")
    st.caption("Einzeldatei-Analyse — eine Audiospur")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        threshold_db = st.slider(
            "Schwellwert (dB)", -60, -10, key="sc_threshold_db",
            value=int(st.session_state.get("sc_threshold_db", _DEFAULTS["sc_threshold_db"])),
            help="Signale unterhalb dieses Pegels gelten als Stille",
        )
        min_silence_s = st.slider(
            "Mindestdauer Stille (s)", 0.1, 3.0, step=0.1, key="sc_min_silence_s",
            value=float(st.session_state.get("sc_min_silence_s", _DEFAULTS["sc_min_silence_s"])),
            help="Kürzere Pausen werden ignoriert",
        )
    with col_s2:
        pre_pad_ms = st.slider(
            "Pre-Pad (ms)", 0, 500, step=25, key="sc_pre_pad_ms",
            value=int(st.session_state.get("sc_pre_pad_ms", _DEFAULTS["sc_pre_pad_ms"])),
            help="Puffer am Anfang jeder Stille — wird NICHT geschnitten",
        )
        post_pad_ms = st.slider(
            "Post-Pad (ms)", 0, 500, step=25, key="sc_post_pad_ms",
            value=int(st.session_state.get("sc_post_pad_ms", _DEFAULTS["sc_post_pad_ms"])),
            help="Puffer am Ende jeder Stille — wird NICHT geschnitten",
        )

    _render_threshold_suggest(str(_src) if _src else None)

    # ── Analyse ────────────────────────────────────────────────────────────────

    st.divider()
    st.subheader("Analyse")

    def _probe_fps_file(path: str) -> float:
        import subprocess as _sp
        r = _sp.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
        raw = r.stdout.strip()
        if "/" in raw:
            n, d = raw.split("/")
            return float(n) / float(d)
        try:
            return float(raw)
        except ValueError:
            return 25.0

    def _probe_duration_file(path: str) -> float:
        import subprocess as _sp
        r = _sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
        try:
            return float(r.stdout.strip())
        except ValueError:
            return 0.0

    def _render_waveform_png(src_path: str, dur_s: float,
                             silence_segs: list, fps: float) -> bytes | None:
        """Rendert Waveform + rote Stille-Bereiche als PNG-Bytes."""
        import subprocess as _sp, io
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # Audio sehr niedrig samplen — nur für Anzeige, keine Analyse
        r = _sp.run(
            ["ffmpeg", "-y", "-i", src_path, "-ac", "1", "-ar", "200",
             "-f", "f32le", "-"],
            capture_output=True,
        )
        data = np.frombuffer(r.stdout, dtype=np.float32).copy()
        if len(data) < 10:
            return None

        # Min/Max-Envelope auf ~1200 Pixel herunterrechnen
        DISPLAY_W = 1200
        n    = len(data)
        step = max(1, n // DISPLAY_W)
        clipped = data[: (n // step) * step].reshape(-1, step)
        lo = clipped.min(axis=1)
        hi = clipped.max(axis=1)
        t  = np.linspace(0, dur_s, len(lo))

        # Peak-Normalisierung damit die Waveform immer den vollen Raum füllt
        peak = max(abs(lo.min()), abs(hi.max()))
        if peak > 0:
            lo /= peak
            hi /= peak

        fig, ax = plt.subplots(figsize=(12, 1.8), facecolor="#111111")
        ax.set_facecolor("#111111")
        ax.fill_between(t, lo, hi, color="#5b9bd5", alpha=0.9, linewidth=0)
        ax.axhline(0, color="#333333", linewidth=0.5)

        for s_start, s_dur in silence_segs:
            t0 = s_start / fps
            t1 = (s_start + s_dur) / fps
            ax.axvspan(t0, t1, color="#e03131", alpha=0.45, linewidth=0)

        ax.set_xlim(0, dur_s)
        ax.set_ylim(-1, 1)
        ax.tick_params(axis="x", colors="#888888", labelsize=7)
        ax.tick_params(axis="y", left=False, labelleft=False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xlabel("Zeit (s)", color="#888888", fontsize=7)
        plt.tight_layout(pad=0.3)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    def _run_file_analysis(params: dict, q: queue.Queue):
        try:
            from resolve_bridge.silence_cutter import analyze_composite_silence

            path     = params["file_path"]
            fps      = params["fps"]
            dur_s    = params["dur_s"]
            tl_len   = int(math.ceil(dur_s * fps))

            q.put(f"Datei: {Path(path).name}")
            q.put(f"FPS: {fps:.3f}  ·  Dauer: {dur_s:.1f}s  ·  {tl_len} Frames")

            # Fake-Clip-Struktur: eine Spur, ein Clip über die gesamte Datei
            fake_clip = SimpleNamespace(
                file_path          = path,
                timeline_start     = 0,
                timeline_end       = tl_len,
                source_start_frame = 0,
                source_end_frame   = tl_len,
            )
            fake_audio_tracks = {1: [fake_clip]}

            silence_segs = analyze_composite_silence(
                audio_tracks     = fake_audio_tracks,
                selected_tracks  = [1],
                fps              = fps,
                tl_start         = 0,
                tl_end           = tl_len,
                threshold_db     = params["threshold_db"],
                min_silence_s    = params["min_silence_s"],
                pre_pad_s        = params["pre_pad_s"],
                post_pad_s       = params["post_pad_s"],
                gaps_are_silence = True,
                progress_cb      = q.put,
            )

            # Keep-Segmente berechnen (invertierte Stille)
            keep_segs = []
            pos = 0
            for s_start, s_dur in sorted(silence_segs):
                s_end = s_start + s_dur
                if pos < s_start:
                    keep_segs.append({
                        "start": round(pos / fps, 4),
                        "end":   round(s_start / fps, 4),
                    })
                pos = s_end
            if pos < tl_len:
                keep_segs.append({
                    "start": round(pos / fps, 4),
                    "end":   round(tl_len / fps, 4),
                })

            total_silence_s = sum(d for _, d in silence_segs) / fps
            total_keep_s    = sum(s["end"] - s["start"] for s in keep_segs)
            q.put(f"\n{len(silence_segs)} Stille-Bereiche erkannt  ({total_silence_s:.1f}s)")
            q.put(f"{len(keep_segs)} Keep-Segmente  ({total_keep_s:.1f}s)")

            q.put(("__FILE_RESULT__", {"silence": silence_segs, "keep": keep_segs,
                                       "fps": fps, "file_path": path, "dur_s": dur_s}))
            q.put("__DONE__0")

        except Exception as e:
            import traceback
            _log.exception("Silence Cutter: Datei-Verarbeitung fehlgeschlagen")
            q.put(f"Fehler: {e}\n{traceback.format_exc()[-400:]}")
            q.put("__DONE__1")

    analyse_btn = st.button(
        "Analysieren", icon=":material/search:",
        type="primary",
        disabled=not _src or st.session_state.get("silence_running", False),
        use_container_width=True,
    )

    if analyse_btn and _src:
        fps_val = _probe_fps_file(str(_src))
        dur_val = _probe_duration_file(str(_src))
        if dur_val <= 0:
            st.error("Dauer konnte nicht ermittelt werden.")
            st.stop()

        st.session_state.silence_running      = True
        st.session_state.silence_log          = []
        st.session_state.sc_file_results      = None
        st.session_state.sc_waveform_accepted = False
        st.session_state.pop("_sc_wf_cache_key", None)
        q = queue.Queue()
        st.session_state.silence_queue = q

        threading.Thread(
            target=_run_file_analysis,
            args=({
                "file_path":    str(_src),
                "fps":          fps_val,
                "dur_s":        dur_val,
                "threshold_db": threshold_db,
                "min_silence_s": min_silence_s,
                "pre_pad_s":    pre_pad_ms / 1000,
                "post_pad_s":   post_pad_ms / 1000,
            }, q),
            daemon=True,
        ).start()
        st.rerun()

    # ── Ergebnis & AAF-Export ─────────────────────────────────────────────────

    _file_res = st.session_state.get("sc_file_results")

    # Ergebnis aus Queue einlesen (falls gerade fertig)
    if st.session_state.get("silence_running") and "silence_queue" in st.session_state:
        _fq = st.session_state.silence_queue
        while True:
            try:
                _msg = _fq.get_nowait()
                if isinstance(_msg, tuple) and _msg[0] == "__FILE_RESULT__":
                    st.session_state.sc_file_results = _msg[1]
                    _file_res = _msg[1]
                elif isinstance(_msg, str) and _msg.startswith("__DONE__"):
                    st.session_state.silence_running = False
                else:
                    st.session_state.silence_log.append(str(_msg))
            except Exception:
                break

    if _file_res:
        st.divider()
        st.subheader("Ergebnis")

        _keep  = _file_res["keep"]
        _sil   = _file_res["silence"]
        _fps   = _file_res["fps"]
        _fpath = _file_res["file_path"]
        _dur_s = _file_res.get("dur_s", 0.0)

        total_keep_s = sum(s["end"] - s["start"] for s in _keep)
        total_sil_s  = sum(d for _, d in _sil) / _fps

        col_res1, col_res2, col_res3 = st.columns(3)
        col_res1.metric("Keep-Segmente",    len(_keep))
        col_res2.metric("Behalten",         f"{total_keep_s:.1f}s")
        col_res3.metric("Herausgeschnitten", f"{total_sil_s:.1f}s")

        # ── Waveform-Vorschau ─────────────────────────────────────────────────

        _wf_key = f"{_fpath}|{len(_sil)}|{_fps:.4f}"
        if st.session_state.get("_sc_wf_cache_key") != _wf_key:
            with st.spinner("Waveform rendern …"):
                _png = _render_waveform_png(_fpath, _dur_s, _sil, _fps)
            st.session_state["_sc_wf_cache_key"] = _wf_key
            st.session_state["_sc_wf_png"]       = _png

        _png = st.session_state.get("_sc_wf_png")
        if _png:
            st.image(_png, use_container_width=True)
            st.caption(
                ":material/radio_button_checked: Blau = wird behalten  ·  "
                ":material/cancel: Rot = wird entfernt"
            )

        # Accept-Gate — AAF-Export erst nach Bestätigung
        if not st.session_state.get("sc_waveform_accepted"):
            if st.button(
                "Ergebnis übernehmen", icon=":material/check_circle:",
                type="primary", use_container_width=True,
                key="sc_accept_btn",
            ):
                st.session_state["sc_waveform_accepted"] = True
                st.rerun()
        else:
            st.success("Ergebnis übernommen — AAF-Export bereit.")

        if not st.session_state.get("sc_waveform_accepted"):
            st.stop()

        # ── AAF exportieren ───────────────────────────────────────────────────

        st.divider()
        _use_resolve_export = _resolve_ok and source_mode == "Aktive Timeline"

        tl_name_input = st.text_input(
            "Timeline-Name", value=f"{Path(_fpath).stem} (cut)", key="sc_tl_name",
        )

        def _build_silence_aaf(source_path: str, keep_segs: list,
                                output_path: str, fps: float, tl_name: str) -> None:
            import subprocess as _sp
            import aaf2
            from fractions import Fraction

            AUDIO_SR = 48000
            fps_int  = int(round(fps))
            fps_frac = Fraction(fps_int, 1)
            src      = Path(source_path)
            src_uri  = src.resolve().as_uri()

            def _probe(args):
                r = _sp.run(args, capture_output=True, text=True)
                return r.stdout.strip()

            dur_secs = float(_probe(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", source_path]
            ) or 0)
            dur_vid = int(round(dur_secs * fps_int))
            dur_aud = int(round(dur_secs * AUDIO_SR))

            _vinfo = {}
            for line in _probe(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,display_aspect_ratio",
                 "-of", "default=noprint_wrappers=1", source_path]
            ).splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    _vinfo[k.strip()] = v.strip()

            vid_w  = int(_vinfo.get("width",  1920))
            vid_h  = int(_vinfo.get("height", 1080))
            try:
                dar_n, dar_d = _vinfo.get("display_aspect_ratio", "16:9").split(":")
                aspect = Fraction(int(dar_n), int(dar_d))
            except Exception:
                aspect = Fraction(vid_w, vid_h)

            try:
                n_channels = int(_probe(
                    ["ffprobe", "-v", "error", "-select_streams", "a:0",
                     "-show_entries", "stream=channels",
                     "-of", "default=noprint_wrappers=1:nokey=1", source_path]
                ))
            except ValueError:
                n_channels = 2

            import json as _json
            tc_frames = 0
            try:
                _streams = _json.loads(_probe(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_streams", source_path]
                )).get("streams", [])
                for _st in _streams:
                    _tc = _st.get("tags", {}).get("timecode", "")
                    if _tc and _tc.count(":") == 3:
                        hh, mm, ss, ff = (int(x) for x in _tc.split(":"))
                        tc_frames = (hh * 3600 + mm * 60 + ss) * fps_int + ff
                        break
            except Exception:
                pass

            def _make_tape(f, media_kind, phys):
                tape = f.create.SourceMob(); tape.name = ""
                tape.descriptor = f.create.TapeDescriptor()
                tc_seg = f.create.Timecode()
                tc_seg["FPS"].value = fps_int; tc_seg["Drop"].value = False
                tc_seg["Start"].value = tc_frames; tc_seg["Length"].value = dur_vid
                tc_slot = tape.create_timeline_slot(edit_rate=fps_int)
                tc_slot.segment = tc_seg; tc_slot["PhysicalTrackNumber"].value = 1
                if media_kind == "picture":
                    ms = tape.create_picture_slot(edit_rate=fps_int)
                else:
                    ms = tape.create_sound_slot(edit_rate=fps_int)
                ms["PhysicalTrackNumber"].value = phys
                end_sc = f.create.SourceClip(media_kind=media_kind, length=dur_vid)
                ms.segment = end_sc
                return tape, ms

            with aaf2.open(output_path, "w") as f:
                tape_v,  tape_v_slot  = _make_tape(f, "picture", 1)
                tape_a1, tape_a1_slot = _make_tape(f, "sound",   1)
                tape_a2, tape_a2_slot = _make_tape(f, "sound",   2)
                f.content.mobs.append(tape_v)
                f.content.mobs.append(tape_a1)
                f.content.mobs.append(tape_a2)

                mob_vid = f.create.SourceMob(); mob_vid.name = src.stem
                cdci = f.create.CDCIDescriptor()
                cdci["StoredWidth"].value = vid_w; cdci["StoredHeight"].value = vid_h
                cdci["ImageAspectRatio"].value = aspect; cdci["FrameLayout"].value = "FullFrame"
                cdci["HorizontalSubsampling"].value = 2; cdci["ComponentWidth"].value = 8
                cdci["VideoLineMap"].value = [0, 1]
                cdci["SampleRate"].value = fps_frac; cdci["Length"].value = dur_vid
                cdci_loc = f.create.NetworkLocator(); cdci_loc["URLString"].value = src_uri
                cdci["Locator"].value = [cdci_loc]; mob_vid.descriptor = cdci
                fv = mob_vid.create_picture_slot(edit_rate=fps_int)
                fv["PhysicalTrackNumber"].value = 1
                sc_fv = f.create.SourceClip(media_kind="picture", length=dur_vid)
                sc_fv.mob = tape_v; sc_fv.slot = tape_v_slot; sc_fv.start = 0
                fv.segment = sc_fv
                f.content.mobs.append(mob_vid)

                mob_aud = f.create.SourceMob(); mob_aud.name = src.stem
                pcm = f.create.PCMDescriptor()
                pcm["AudioSamplingRate"].value = Fraction(AUDIO_SR, 1)
                pcm["Channels"].value = n_channels
                pcm["QuantizationBits"].value = 16; pcm["BlockAlign"].value = 2
                pcm["AverageBPS"].value = AUDIO_SR * 2
                pcm["SampleRate"].value = Fraction(AUDIO_SR, 1); pcm["Length"].value = dur_aud
                pcm_loc = f.create.NetworkLocator(); pcm_loc["URLString"].value = src_uri
                pcm["Locator"].value = [pcm_loc]; mob_aud.descriptor = pcm
                fa1 = mob_aud.create_sound_slot(edit_rate=fps_int)
                fa1["PhysicalTrackNumber"].value = 1
                sc_fa1 = f.create.SourceClip(media_kind="sound", length=dur_vid)
                sc_fa1.mob = tape_a1; sc_fa1.slot = tape_a1_slot; sc_fa1.start = 0
                fa1.segment = sc_fa1
                fa2 = mob_aud.create_sound_slot(edit_rate=fps_int)
                fa2["PhysicalTrackNumber"].value = 2
                sc_fa2 = f.create.SourceClip(media_kind="sound", length=dur_vid)
                sc_fa2.mob = tape_a2; sc_fa2.slot = tape_a2_slot; sc_fa2.start = 0
                fa2.segment = sc_fa2
                f.content.mobs.append(mob_aud)

                master = f.create.MasterMob(); master.name = src.stem
                m_vid = master.create_picture_slot(edit_rate=fps_int)
                m_vid["PhysicalTrackNumber"].value = 1
                sc_mv = f.create.SourceClip(media_kind="picture", length=dur_vid)
                sc_mv.mob = mob_vid; sc_mv.slot = fv; sc_mv.start = 0; m_vid.segment = sc_mv
                m_a1 = master.create_sound_slot(edit_rate=fps_int)
                m_a1["PhysicalTrackNumber"].value = 1
                sc_ma1 = f.create.SourceClip(media_kind="sound", length=dur_vid)
                sc_ma1.mob = mob_aud; sc_ma1.slot = fa1; sc_ma1.start = 0; m_a1.segment = sc_ma1
                m_a2 = master.create_sound_slot(edit_rate=fps_int)
                m_a2["PhysicalTrackNumber"].value = 2
                sc_ma2 = f.create.SourceClip(media_kind="sound", length=dur_vid)
                sc_ma2.mob = mob_aud; sc_ma2.slot = fa2; sc_ma2.start = 0; m_a2.segment = sc_ma2
                f.content.mobs.append(master)

                comp      = f.create.CompositionMob(tl_name)
                total_fr  = sum(
                    max(1, int(round((s["end"] - s["start"]) * fps_int)))
                    for s in keep_segs
                )

                def _seq(media_kind, master_slot):
                    seq = f.create.Sequence(media_kind=media_kind, length=total_fr)
                    for seg in keep_segs:
                        sf = int(round(seg["start"] * fps_int))
                        lf = max(1, int(round((seg["end"] - seg["start"]) * fps_int)))
                        sc = f.create.SourceClip(media_kind=media_kind, length=lf)
                        sc.mob = master; sc.slot = master_slot; sc.start = sf
                        seq.components.append(sc)
                    return seq

                comp_vid = comp.create_picture_slot(edit_rate=fps_int)
                comp_vid["PhysicalTrackNumber"].value = 1
                comp_vid.segment = _seq("picture", m_vid)
                comp_a1 = comp.create_sound_slot(edit_rate=fps_int)
                comp_a1["PhysicalTrackNumber"].value = 1
                comp_a1.segment = _seq("sound", m_a1)
                comp_a2 = comp.create_sound_slot(edit_rate=fps_int)
                comp_a2["PhysicalTrackNumber"].value = 2
                comp_a2.segment = _seq("sound", m_a2)
                f.content.mobs.append(comp)

        if st.button("AAF exportieren", type="primary", use_container_width=True):
            import subprocess as _sp_dlg
            _save_path = None
            try:
                _safe = f"{Path(_fpath).stem}_{tl_name_input}".replace(" ", "_")
                _r = _sp_dlg.run(
                    ["osascript", "-e",
                     f'POSIX path of (choose file name default name "{_safe}.aaf" '
                     f'with prompt "AAF speichern unter")'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    _save_path = _r.stdout.strip()
                    if not _save_path.endswith(".aaf"):
                        _save_path += ".aaf"
            except Exception:
                st.error("Speicher-Dialog nicht verfügbar.")

            if _save_path:
                try:
                    _build_silence_aaf(
                        source_path = _fpath,
                        keep_segs   = _keep,
                        output_path = _save_path,
                        fps         = _fps,
                        tl_name     = tl_name_input,
                    )
                    st.success(
                        f"AAF gespeichert: `{_save_path}`  \n"
                        f"{len(_keep)} Segmente · {total_keep_s:.1f}s"
                    )
                except Exception as _aaf_err:
                    st.error(f"AAF-Export fehlgeschlagen: {_aaf_err}")
