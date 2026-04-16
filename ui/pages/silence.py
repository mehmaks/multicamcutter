"""
Silence Cutter — Composite multi-track silence detection with marker preview
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import math
import threading
import queue
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

st.title("🔇 Silence Cutter")
st.caption("Composite Silence Detection · Duration-Marker Preview · Ripple Cut")

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
        "Quelle", ["Resolve Timeline", "Datei-Pfad"], horizontal=True,
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
    if st.session_state.get("_sc_loaded_project") != _project_name:
        _saved = load_page(_project_name, _PAGE)
        for _k, _default in _DEFAULTS.items():
            st.session_state[_k] = _saved.get(_k, _default)
        st.session_state["_sc_loaded_project"] = _project_name
else:
    for _k, _default in _DEFAULTS.items():
        if _k not in st.session_state:
            st.session_state[_k] = _default

# ══════════════════════════════════════════════════════════════════════════════
# RESOLVE TIMELINE MODE
# ══════════════════════════════════════════════════════════════════════════════

if source_mode == "Resolve Timeline":

    # ── Timeline info ──────────────────────────────────────────────────────────

    col1, col2, col3 = st.columns(3)
    col1.metric("Timeline", tl.timeline_name)
    col2.metric("FPS", int(tl.fps))
    col3.metric("Dauer", f"{(tl.timeline_end - tl.timeline_start) / tl.fps / 60:.1f} min")

    for w in (tl.warnings or []):
        st.warning(w)

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
            help="Signale unterhalb dieses Pegels gelten als Stille",
        )
        min_silence_s = st.slider(
            "Mindestdauer Stille (s)", 0.1, 3.0, step=0.1, key="sc_min_silence_s",
            help="Kürzere Pausen werden ignoriert",
        )
    with col_s2:
        pre_pad_ms = st.slider(
            "Pre-Pad (ms)", 0, 500, step=25, key="sc_pre_pad_ms",
            help="Puffer am Anfang jeder Stille — wird NICHT geschnitten",
        )
        post_pad_ms = st.slider(
            "Post-Pad (ms)", 0, 500, step=25, key="sc_post_pad_ms",
            help="Puffer am Ende jeder Stille — wird NICHT geschnitten",
        )

    MARKER_COLOR_OPTIONS = ["red", "pink", "yellow", "green", "blue", "purple", "cyan"]
    marker_color = st.selectbox("Marker-Farbe", MARKER_COLOR_OPTIONS, key="sc_marker_color")

    save_page(_project_name, _PAGE, {k: st.session_state[k] for k in _DEFAULTS})

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
            q.put(f"Fehler: {e}")
            q.put("__DONE__1")

    analyse_btn = st.button(
        "🔍 Analysieren & Marker setzen", type="primary",
        disabled=st.session_state.get("silence_running", False),
        use_container_width=True,
    )

    if analyse_btn:
        st.session_state.silence_running = True
        st.session_state.silence_log     = []
        st.session_state.silence_results = []
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

    # ── Cut section ────────────────────────────────────────────────────────────

    results = st.session_state.get("silence_results", [])
    if results:
        st.divider()
        st.subheader("Schneiden")

        total_s = sum(d for _, d in results) / tl.fps
        col_r1, col_r2 = st.columns(2)
        col_r1.metric("Erkannte Pausen", len(results))
        col_r2.metric("Einsparung", f"{total_s:.1f}s")

        new_tl_name = st.text_input(
            "Name der neuen Timeline", value=f"{tl.timeline_name} (cut)",
        )
        st.warning(
            "**Cut now** erstellt eine neue Timeline ohne die erkannten Pausen. "
            "Die originale Timeline bleibt erhalten."
        )
        confirmed = st.checkbox("Ich habe die Marker geprüft und möchte schneiden.")
        cut_btn   = st.button(
            "✂️ Cut now", type="primary",
            disabled=not confirmed or st.session_state.get("silence_running", False),
            use_container_width=True,
        )

        if cut_btn:
            st.session_state.silence_running = True
            st.session_state.silence_log     = []
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
        if st.button("📁 Durchsuchen", use_container_width=True, key="sc_browse"):
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
            help="Signale unterhalb dieses Pegels gelten als Stille",
        )
        min_silence_s = st.slider(
            "Mindestdauer Stille (s)", 0.1, 3.0, step=0.1, key="sc_min_silence_s",
            help="Kürzere Pausen werden ignoriert",
        )
    with col_s2:
        pre_pad_ms = st.slider(
            "Pre-Pad (ms)", 0, 500, step=25, key="sc_pre_pad_ms",
            help="Puffer am Anfang jeder Stille — wird NICHT geschnitten",
        )
        post_pad_ms = st.slider(
            "Post-Pad (ms)", 0, 500, step=25, key="sc_post_pad_ms",
            help="Puffer am Ende jeder Stille — wird NICHT geschnitten",
        )

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
                                       "fps": fps, "file_path": path}))
            q.put("__DONE__0")

        except Exception as e:
            import traceback
            q.put(f"Fehler: {e}\n{traceback.format_exc()[-400:]}")
            q.put("__DONE__1")

    analyse_btn = st.button(
        "🔍 Analysieren",
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

        st.session_state.silence_running     = True
        st.session_state.silence_log         = []
        st.session_state.sc_file_results     = None
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

        _keep = _file_res["keep"]
        _sil  = _file_res["silence"]
        _fps  = _file_res["fps"]
        _fpath = _file_res["file_path"]

        total_keep_s = sum(s["end"] - s["start"] for s in _keep)
        total_sil_s  = sum(d for _, d in _sil) / _fps

        col_res1, col_res2, col_res3 = st.columns(3)
        col_res1.metric("Keep-Segmente",    len(_keep))
        col_res2.metric("Behalten",         f"{total_keep_s:.1f}s")
        col_res3.metric("Herausgeschnitten", f"{total_sil_s:.1f}s")

        # ── AAF exportieren ───────────────────────────────────────────────────

        st.divider()
        _use_resolve_export = _resolve_ok and source_mode == "Resolve Timeline"

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
