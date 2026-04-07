"""
Silence Cutter — Composite multi-track silence detection with marker preview
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import threading
import queue
from pathlib import Path

st.title("🔇 Silence Cutter")
st.caption("Composite Silence Detection · Duration-Marker Preview · Ripple Cut")

# ── Resolve connection ─────────────────────────────────────────────────────────

try:
    from resolve_bridge.connection import get_resolve
    from resolve_bridge.timeline_reader import read_timeline

    resolve  = get_resolve()
    tl       = read_timeline()
    resolve_ok = True
except Exception as e:
    st.error(f"Resolve nicht verbunden: {e}")
    st.info("Resolve öffnen, Projekt laden und eine Timeline aktivieren.")
    st.stop()

# ── Timeline info ──────────────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)
col1.metric("Timeline", tl.timeline_name)
col2.metric("FPS", int(tl.fps))
col3.metric("Dauer", f"{(tl.timeline_end - tl.timeline_start) / tl.fps / 60:.1f} min")

for w in (tl.warnings or []):
    st.warning(w)

# ── Track selection ────────────────────────────────────────────────────────────

st.divider()
st.subheader("Audio-Spuren")

from resolve_bridge.timeline_reader import get_primary_wav_clip

wav_tracks = {
    idx: clips
    for idx, clips in tl.audio_tracks.items()
    if any(get_primary_wav_clip([c]) for c in clips)
}

if not wav_tracks:
    st.warning("Keine Audio-Spuren mit WAV-Clips gefunden.")
    st.stop()

track_labels = {
    idx: f"A{idx} — {tl.audio_track_names.get(idx, 'Audio')}  ({len(clips)} Clip{'s' if len(clips) != 1 else ''})"
    for idx, clips in wav_tracks.items()
}

col_t1, col_t2 = st.columns([3, 1])
with col_t1:
    selected_tracks = st.multiselect(
        "Spuren für Composite-Analyse",
        options=list(wav_tracks.keys()),
        default=list(wav_tracks.keys()),
        format_func=lambda x: track_labels[x],
    )
with col_t2:
    st.markdown("<br>", unsafe_allow_html=True)
    gaps_are_silence = st.toggle(
        "Lücken = Stille",
        value=True,
        help="An: Lücken zwischen Clips auf dieser Spur gelten als Stille.\nAus: Nur tatsächlich analysierte Audiobereiche fließen in die Composite-Detection ein.",
    )

if not selected_tracks:
    st.warning("Mindestens eine Spur auswählen.")
    st.stop()

# ── Settings ───────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Einstellungen")

col_s1, col_s2 = st.columns(2)
with col_s1:
    threshold_db = st.slider(
        "Schwellwert (dB)", -60, -10, -40,
        help="Signale unterhalb dieses Pegels gelten als Stille",
    )
    min_silence_s = st.slider(
        "Mindestdauer Stille (s)", 0.1, 3.0, 0.8, step=0.1,
        help="Kürzere Pausen werden ignoriert",
    )
with col_s2:
    pre_pad_ms = st.slider(
        "Pre-Pad (ms)", 0, 500, 150, step=25,
        help="Puffer am Anfang jeder Stille — wird NICHT geschnitten",
    )
    post_pad_ms = st.slider(
        "Post-Pad (ms)", 0, 500, 150, step=25,
        help="Puffer am Ende jeder Stille — wird NICHT geschnitten",
    )

MARKER_COLOR_OPTIONS = ["red", "pink", "yellow", "green", "blue", "purple", "cyan"]
marker_color = st.selectbox("Marker-Farbe", MARKER_COLOR_OPTIONS, index=0)

# ── Analyse ────────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Analyse")

def _run_analysis(params: dict, q: queue.Queue):
    """Runs composite silence detection and sets duration markers."""
    try:
        from resolve_bridge.silence_cutter import analyze_composite_silence
        from resolve_bridge.markers import add_marker, delete_markers_by_color

        q.put("Starte Analyse …")

        # Delete old markers of this color
        try:
            delete_markers_by_color(params["marker_color"])
            q.put(f"  Alte {params['marker_color']}-Marker gelöscht.")
        except Exception as e:
            q.put(f"  ⚠ Marker löschen: {e}")

        def _cb(msg):
            q.put(msg)

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
            progress_cb      = _cb,
        )

        q.put(f"\n{len(segments)} Stille-Bereiche erkannt.")

        if segments:
            # Set duration markers
            total_frames = sum(d for _, d in segments)
            total_s = total_frames / params["fps"]
            q.put(f"Setze {len(segments)} Duration-Marker …")
            for frame, dur in segments:
                add_marker(
                    frame    = frame,
                    color    = params["marker_color"],
                    name     = "Silence",
                    note     = f"{dur / params['fps']:.2f}s",
                    duration = dur,
                )
            q.put(f"✓ Marker gesetzt — {total_s:.1f}s werden gekürzt.")
        else:
            q.put("Keine Pausen gefunden. Schwellwert anpassen?")

        q.put(("__RESULT__", segments))
        q.put("__DONE__0")

    except Exception as e:
        q.put(f"Fehler: {e}")
        q.put("__DONE__1")


analyse_btn = st.button(
    "🔍 Analysieren & Marker setzen",
    type="primary",
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

# ── Cut section ────────────────────────────────────────────────────────────────

results = st.session_state.get("silence_results", [])
if results:
    st.divider()
    st.subheader("Schneiden")

    total_s = sum(d for _, d in results) / tl.fps
    col_r1, col_r2 = st.columns(2)
    col_r1.metric("Erkannte Pausen", len(results))
    col_r2.metric("Einsparung", f"{total_s:.1f}s")

    audio_transition = st.checkbox(
        "Audio-Transition (2 Frames Fade an jedem Schnitt)",
        value=False,
    )

    new_tl_name = st.text_input(
        "Name der neuen Timeline",
        value=f"{tl.timeline_name} (cut)",
    )

    st.warning(
        "**Cut now** erstellt eine neue Timeline ohne die erkannten Pausen. "
        "Die originale Timeline bleibt erhalten."
    )
    confirmed = st.checkbox("Ich habe die Marker geprüft und möchte schneiden.")

    cut_btn = st.button(
        "✂️ Cut now",
        type="primary",
        disabled=not confirmed or st.session_state.get("silence_running", False),
        use_container_width=True,
    )

    if cut_btn:
        st.session_state.silence_running = True
        st.session_state.silence_log = []
        q = queue.Queue()
        st.session_state.silence_queue = q

        def _run_cut(params, q):
            try:
                from resolve_bridge.silence_cutter import rebuild_timeline_without_silences
                q.put(f"Erstelle Timeline '{params['new_tl_name']}' …")

                rebuild_timeline_without_silences(
                    resolve                 = params["resolve"],
                    source_tl_name          = params["source_tl_name"],
                    new_tl_name             = params["new_tl_name"],
                    selected_tracks         = params["selected_tracks"],
                    silence_segments        = params["segments"],
                    audio_transition_frames = 2 if params["audio_transition"] else 0,
                    progress_cb             = lambda m: q.put(m),
                )
                q.put(f"\n✓ Timeline '{params['new_tl_name']}' erstellt und aktiviert.")
                q.put("__DONE__0")
            except Exception as e:
                q.put(f"Fehler: {e}")
                q.put("__DONE__1")

        threading.Thread(
            target=_run_cut,
            args=({
                "resolve":          resolve,
                "source_tl_name":   tl.timeline_name,
                "new_tl_name":      new_tl_name.strip() or f"{tl.timeline_name} (cut)",
                "selected_tracks":  selected_tracks,
                "segments":         results,
                "audio_transition": audio_transition,
            }, q),
            daemon=True,
        ).start()
