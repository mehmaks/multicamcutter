"""
Take Selector — Automatic best-take detection for scripted recordings.
Whisper word timestamps + text similarity → retake detection → last complete take per section.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import threading
import queue
import tempfile
import time
import math
from pathlib import Path

st.title("🎬 Take Selector")
st.caption("Erkennt Absätze und Wiederholungen in geskripteten Aufnahmen — wählt automatisch den besten Take.")

# ── Library check ─────────────────────────────────────────────────────────────

try:
    import whisper as _whisper_lib
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

if not WHISPER_AVAILABLE:
    st.error("Whisper nicht installiert — `pip install openai-whisper`")
    st.stop()

# ── Session state ─────────────────────────────────────────────────────────────

for _k, _v in {
    "takes_analysis_running": False,
    "takes_analysis_queue":   None,
    "takes_analysis_result":  None,
    "takes_selections":       {},
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Analysis queue polling (before any widgets) ────────────────────────────────

if st.session_state.takes_analysis_running and st.session_state.takes_analysis_queue:
    _aq = st.session_state.takes_analysis_queue
    if not _aq.empty():
        _result = _aq.get_nowait()
        st.session_state.takes_analysis_running = False
        if isinstance(_result, dict) and "error" not in _result:
            st.session_state.takes_analysis_result = _result
            st.session_state.takes_selections = {
                i: sec["selected_idx"]
                for i, sec in enumerate(_result["sections"])
            }
        st.rerun()

# ── Settings ──────────────────────────────────────────────────────────────────

with st.expander("Erkennungs-Parameter", expanded=True):
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        pause_threshold = st.slider(
            "Pause-Schwelle (s)",
            min_value=0.3, max_value=5.0, value=1.5, step=0.1,
            help="Stille länger als dieser Wert trennt Takes oder Sektionen voneinander.",
        )
    with col_s2:
        similarity_threshold = st.slider(
            "Ähnlichkeits-Schwelle",
            min_value=0.2, max_value=0.9, value=0.5, step=0.05,
            help="Wie ähnlich muss der Anfang eines Segments dem Anfang der aktuellen Sektion sein, "
                 "um als Wiederholung (neuer Take) gewertet zu werden? "
                 "Höher = strenger (weniger Sektionen, mehr Takes pro Sektion).",
        )
    with col_s3:
        min_coverage = st.slider(
            "Min. Take-Vollständigkeit",
            min_value=0.3, max_value=1.0, value=0.7, step=0.05,
            help="Ein Take gilt als vollständig, wenn er mindestens diesen Anteil "
                 "der Wörter des längsten Takes dieser Sektion enthält. "
                 "Unvollständige Takes am Ende werden übersprungen.",
        )

st.divider()

# ── File selection ─────────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}

st.subheader("Clip auswählen")
source_mode = st.radio("Quelle", ["Resolve Media Pool", "Datei-Pfad"], horizontal=True,
                        key="takes_source_mode")

selected_file = None  # (name, path)

if source_mode == "Resolve Media Pool":

    def _collect_bins(folder, depth=0):
        bins = []
        if depth > 0:
            bins.append("  " * (depth - 1) + folder.GetName())
        for sf in (folder.GetSubFolderList() or []):
            bins.extend(_collect_bins(sf, depth + 1))
        return bins

    def _find_folder(folder, name):
        if folder.GetName() == name:
            return folder
        for sf in (folder.GetSubFolderList() or []):
            found = _find_folder(sf, name)
            if found:
                return found
        return None

    try:
        from resolve_bridge.connection import get_resolve
        resolve  = get_resolve()
        project  = resolve.GetProjectManager().GetCurrentProject()
        mp       = project.GetMediaPool()
        root     = mp.GetRootFolder()
        all_bins = _collect_bins(root)
        if all_bins:
            sel_bin  = st.selectbox("Media Pool Bin", options=all_bins, key="takes_mp_bin")
            bin_name = sel_bin.strip() if sel_bin else None
            if bin_name:
                folder = _find_folder(root, bin_name)
                if folder:
                    clips = folder.GetClipList() or []
                    _all_ext = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
                    file_clips = [
                        (c.GetName(), c.GetClipProperty("File Path"))
                        for c in clips
                        if c.GetClipProperty("File Path")
                        and Path(c.GetClipProperty("File Path")).suffix.lower() in _all_ext
                    ]
                    if file_clips:
                        clip_names    = [n for n, _ in file_clips]
                        chosen_name   = st.selectbox("Clip", options=clip_names, key="takes_mp_clip")
                        chosen_path   = next((p for n, p in file_clips if n == chosen_name), None)
                        if chosen_path:
                            selected_file = (chosen_name, chosen_path)
                    else:
                        st.info("Keine Audio/Video-Clips in diesem Bin.")
        else:
            st.warning("Keine Bins im Media Pool gefunden.")
    except Exception as _e:
        st.error("Resolve nicht verbunden")
        st.caption(str(_e))

else:
    file_path_str = st.text_input(
        "Dateipfad", placeholder="/Volumes/Media/Recording/clip.mp4",
        key="takes_file_path",
    )
    if file_path_str:
        _p = Path(file_path_str)
        if _p.exists() and _p.suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
            selected_file = (_p.name, str(_p))
        elif _p.exists():
            st.warning("Format nicht unterstützt.")
        else:
            st.error("Datei nicht gefunden.")

# ── Analysis ──────────────────────────────────────────────────────────────────

if selected_file:
    st.divider()
    _fname, _fpath = selected_file
    col_a1, col_a2 = st.columns([4, 1])
    with col_a1:
        st.caption(f"Quelle: `{_fname}` · Whisper base")
    with col_a2:
        analyse_clicked = st.button(
            "Analysieren",
            disabled=st.session_state.takes_analysis_running,
            use_container_width=True,
        )

    if st.session_state.takes_analysis_running:
        st.info("Analyse läuft …")
        time.sleep(1)
        st.rerun()

    if analyse_clicked and not st.session_state.takes_analysis_running:
        _aq = queue.Queue()
        st.session_state.takes_analysis_queue   = _aq
        st.session_state.takes_analysis_running = True
        st.session_state.takes_analysis_result  = None
        st.session_state.takes_selections       = {}

        def _run_takes_analysis(file_path, q, pause_thr, sim_thr, min_cov):
            _audio_tmp = None
            try:
                import whisper
                import subprocess as _sp
                import difflib

                _VIDEO_EXT = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}

                # Extract audio from video if needed
                if Path(file_path).suffix.lower() in _VIDEO_EXT:
                    _audio_tmp = tempfile.mktemp(suffix=".wav")
                    r = _sp.run(
                        ["ffmpeg", "-y", "-i", file_path,
                         "-map", "0:a:0", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                         _audio_tmp],
                        capture_output=True, encoding="utf-8", errors="replace",
                    )
                    if r.returncode != 0:
                        q.put({"error": f"Audio-Extraktion fehlgeschlagen:\n{r.stderr[-300:]}"})
                        return
                    audio_path = _audio_tmp
                else:
                    audio_path = file_path

                # Transcribe
                model  = whisper.load_model("base")
                result = model.transcribe(
                    audio_path,
                    word_timestamps=True,
                    verbose=False,
                    condition_on_previous_text=False,
                )

                # Flatten words: keep raw (display) and clean (comparison)
                words = []
                for seg in result.get("segments", []):
                    for w in seg.get("words", []):
                        raw   = w["word"].strip()
                        clean = "".join(c for c in raw.lower() if c.isalnum())
                        if clean:
                            words.append({
                                "raw":   raw,
                                "clean": clean,
                                "start": w["start"],
                                "end":   w["end"],
                            })

                if not words:
                    q.put({"error": "Keine Wörter erkannt — ggf. Pause-Schwelle verringern."})
                    return

                # Split into segments at pauses
                segments = []
                current  = [words[0]]
                for w in words[1:]:
                    if w["start"] - current[-1]["end"] >= pause_thr:
                        segments.append(current)
                        current = [w]
                    else:
                        current.append(w)
                segments.append(current)

                def _start_words(seg, n=10):
                    return [w["clean"] for w in seg[:n]]

                def _similarity(a, b):
                    return difflib.SequenceMatcher(None, a, b).ratio()

                # Group segments into sections (list of takes per section)
                sections_raw = [[segments[0]]]
                for seg in segments[1:]:
                    ref   = _start_words(sections_raw[-1][0])  # first take of current section
                    this  = _start_words(seg)
                    if _similarity(ref, this) >= sim_thr:
                        sections_raw[-1].append(seg)           # new take, same section
                    else:
                        sections_raw.append([seg])             # new section

                PRE_ROLL  = 0.4
                POST_ROLL = 0.6

                result_sections = []
                for takes in sections_raw:
                    max_words = max(len(t) for t in takes)

                    # Last take that covers >= min_cov of the longest take
                    selected_idx = len(takes) - 1
                    for idx in range(len(takes) - 1, -1, -1):
                        if len(takes[idx]) / max_words >= min_cov:
                            selected_idx = idx
                            break

                    take_data = []
                    for t in takes:
                        display_text = " ".join(w["raw"] for w in t)
                        t_start      = max(0.0, t[0]["start"] - PRE_ROLL)
                        t_end        = t[-1]["end"] + POST_ROLL
                        coverage     = len(t) / max_words
                        take_data.append({
                            "start":    round(t_start, 3),
                            "end":      round(t_end, 3),
                            "text":     display_text,
                            "n_words":  len(t),
                            "coverage": round(coverage, 2),
                        })

                    # Section label from longest take, first ~10 words
                    longest_take = max(takes, key=len)
                    label = " ".join(w["raw"] for w in longest_take[:10])

                    result_sections.append({
                        "label":        label,
                        "takes":        take_data,
                        "selected_idx": selected_idx,
                    })

                q.put({
                    "sections":  result_sections,
                    "file_path": file_path,
                })

            except Exception as exc:
                import traceback
                q.put({"error": f"{exc}\n\n{traceback.format_exc()[-800:]}"})
            finally:
                if _audio_tmp and Path(_audio_tmp).exists():
                    try:
                        Path(_audio_tmp).unlink()
                    except Exception:
                        pass

        threading.Thread(
            target=_run_takes_analysis,
            args=(_fpath, _aq, pause_threshold, similarity_threshold, min_coverage),
            daemon=True,
        ).start()
        st.rerun()

# ── Results ────────────────────────────────────────────────────────────────────

_result = st.session_state.takes_analysis_result
if not _result:
    st.stop()

if "error" in _result:
    st.error(f"Analyse fehlgeschlagen: {_result['error']}")
    st.stop()

sections   = _result["sections"]
selections = st.session_state.takes_selections

n_sections  = len(sections)
n_takes_all = sum(len(s["takes"]) for s in sections)
total_dur   = sum(
    sections[i]["takes"][selections.get(i, sections[i]["selected_idx"])]["end"] -
    sections[i]["takes"][selections.get(i, sections[i]["selected_idx"])]["start"]
    for i in range(n_sections)
)

st.divider()
st.subheader("Erkannte Sektionen")

col_info1, col_info2, col_info3 = st.columns(3)
col_info1.metric("Sektionen", n_sections)
col_info2.metric("Takes gesamt", n_takes_all)
col_info3.metric("Gesamtdauer (gewählt)", f"{total_dur:.1f}s")

if st.button("Alle Auswahlen zurücksetzen", use_container_width=False):
    st.session_state.takes_selections = {
        i: sec["selected_idx"] for i, sec in enumerate(sections)
    }
    st.rerun()

st.divider()

for i, section in enumerate(sections):
    takes   = section["takes"]
    sel_idx = selections.get(i, section["selected_idx"])
    sel     = takes[sel_idx]
    n_t     = len(takes)

    _exp_open = f"takes_sec_open_{i}" not in st.session_state
    st.session_state[f"takes_sec_open_{i}"] = True

    with st.expander(
        f"Sektion {i + 1}  ·  {n_t} Take{'s' if n_t > 1 else ''}  ·  "
        f"Take {sel_idx + 1} ausgewählt  ·  "
        f"{sel['start']:.1f}s – {sel['end']:.1f}s  ({sel['end'] - sel['start']:.1f}s)",
        expanded=_exp_open,
    ):
        for j, take in enumerate(takes):
            is_sel   = (j == sel_idx)
            is_auto  = (j == section["selected_idx"])
            cov_pct  = int(take["coverage"] * 100)
            dur      = take["end"] - take["start"]
            auto_tag = " · Auto" if is_auto else ""

            col_btn, col_info = st.columns([1, 9])
            with col_btn:
                if st.button(
                    "✓" if is_sel else "○",
                    key=f"takes_btn_{i}_{j}",
                    type="primary" if is_sel else "secondary",
                    use_container_width=True,
                    help="Diesen Take auswählen",
                ):
                    st.session_state.takes_selections[i] = j
                    st.rerun()
            with col_info:
                st.caption(
                    f"**Take {j + 1}**{auto_tag}  ·  "
                    f"{take['start']:.1f}s – {take['end']:.1f}s  ({dur:.1f}s)  ·  "
                    f"{take['n_words']} Wörter  ·  {cov_pct}% Vollständigkeit"
                    + ("  ← **ausgewählt**" if is_sel else "")
                )
                st.write(
                    f"_{take['text'][:150]}{'…' if len(take['text']) > 150 else ''}_"
                )

# ── Timeline-Export ───────────────────────────────────────────────────────────

st.divider()
st.subheader("Timeline schneiden")

col_tl1, col_tl2 = st.columns([2, 3])
with col_tl1:
    timeline_name = st.text_input("Timeline-Name", value="Best Takes", key="takes_tl_name")
with col_tl2:
    st.write("")
    st.caption(
        f"{n_sections} Takes · Gesamtdauer: {total_dur:.1f}s  "
        f"({total_dur / 60:.1f} min)"
    )

cut_clicked = st.button("✂️ Timeline schneiden", type="primary", use_container_width=True)

if cut_clicked:
    selected_takes = [
        sections[i]["takes"][selections.get(i, sections[i]["selected_idx"])]
        for i in range(n_sections)
    ]

    try:
        from resolve_bridge.connection import get_resolve

        resolve    = get_resolve()
        project    = resolve.GetProjectManager().GetCurrentProject()
        mp         = project.GetMediaPool()
        fps_str    = project.GetSetting("timelineFrameRate")
        fps        = float(fps_str) if fps_str else 25.0

        def _find_clip_by_path(folder, path):
            for c in (folder.GetClipList() or []):
                if c.GetClipProperty("File Path") == path:
                    return c
            for sf in (folder.GetSubFolderList() or []):
                found = _find_clip_by_path(sf, path)
                if found:
                    return found
            return None

        mpi = _find_clip_by_path(mp.GetRootFolder(), _result["file_path"])
        if mpi is None:
            st.error(
                "Clip nicht im Media Pool gefunden. "
                "Bitte den Clip zuerst in Resolve importieren."
            )
            st.stop()

        tl = mp.CreateEmptyTimeline(timeline_name)
        if tl is None:
            st.error("Timeline konnte nicht erstellt werden.")
            st.stop()

        project.SetCurrentTimeline(tl)

        for take in selected_takes:
            start_fr = int(math.floor(take["start"] * fps))
            end_fr   = max(start_fr + 1, int(math.ceil(take["end"] * fps)) - 1)
            mp.AppendToTimeline([{
                "mediaPoolItem": mpi,
                "startFrame":    start_fr,
                "endFrame":      end_fr,
            }])

        st.success(
            f"Timeline **{timeline_name}** mit {len(selected_takes)} Takes erstellt. "
            f"Gesamtdauer: {total_dur:.1f}s"
        )

    except Exception as _cut_err:
        st.error(f"Fehler beim Timeline-Aufbau: {_cut_err}")
