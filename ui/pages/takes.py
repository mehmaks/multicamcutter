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
import logging
import time
import math
from pathlib import Path

_log = logging.getLogger("rtk")

from modules.take_selector import (
    build_diff_html as _build_diff_html_backend,
    build_takes_aaf as _build_takes_aaf,
    start_words as _start_words,
    text_similarity as _similarity,
)
from shared.ffmpeg_utils import probe_fps as _probe_fps

st.title(":material/theaters: Take Selector")
st.caption("Erkennt in Sprachaufnahmen automatisch Wiederholungen und wählt den besten Take je Abschnitt aus.")

_resolve_ok = st.session_state.get("resolve_status", ("error",))[0] == "ok"

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
    "takes_analysis_running":  False,
    "takes_analysis_queue":    None,
    "takes_progress_queue":       None,
    "takes_show_analysis_dialog": False,
    "takes_analysis_result":   None,
    "takes_selections":        {},
    "takes_show_transcript":   False,
    "takes_transcript_label":  "",
    "takes_transcript_text":   "",
    "takes_file_path_sel":     "",
    "takes_compare_sec":       None,
    "takes_compare_active":    None,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

if "_takes_file_path_pending" in st.session_state:
    st.session_state.takes_file_path_sel = st.session_state.pop("_takes_file_path_pending")


@st.dialog("Transkript")
def _show_transcript_dialog():
    st.caption(st.session_state.takes_transcript_label)
    st.write(st.session_state.takes_transcript_text or "_Kein Text vorhanden._")
    if st.button("Schließen", use_container_width=True):
        st.session_state.takes_show_transcript = False
        st.rerun()


@st.dialog("Inhaltlicher Vergleich", width="large")
def _show_compare_dialog():
    import difflib as _dl
    import html as _html_mod

    # Trigger konsumieren → in _active überführen (überlebt dialog-lokale Reruns)
    _trigger = st.session_state.get("takes_compare_sec")
    if _trigger is not None:
        st.session_state.takes_compare_active = _trigger
        st.session_state.takes_compare_sec = None

    sec_i = st.session_state.get("takes_compare_active")
    if sec_i is None:
        return

    _takes = st.session_state.takes_analysis_result["sections"][sec_i]["takes"]
    _ref_i = max(range(len(_takes)), key=lambda i: _takes[i]["n_words"])
    _ref_w = _takes[_ref_i]["text"].split()

    # Per-take color palette
    _COLORS = ["#ff6b6b", "#ffd93d", "#6bcb77", "#4d96ff", "#ff6b9d", "#c77dff", "#ff9f43"]

    # Fragment filter — live, triggers rerender on change
    min_diff = st.slider(
        "Fragment-Filter (min. Wörter)",
        min_value=1, max_value=8, value=2,
        help="Unterschiede kürzer als dieser Wert werden als identisch gewertet und nicht markiert.",
    )

    st.caption(f"Referenz: **Take {_ref_i + 1}** — {_takes[_ref_i]['n_words']} Wörter")

    # Reference block
    _ref_text = _html_mod.escape(" ".join(_ref_w))
    st.markdown(
        f"<div style='background:#ecebe3;padding:10px 14px;border-radius:6px;"
        f"border-left:4px solid #d3d2ca;margin:6px 0;line-height:1.75'>"
        f"<span style='color:#6b7280;font-size:0.75rem'>Take {_ref_i + 1} · Referenz</span><br>"
        f"<span style='color:#3d3a2a'>{_ref_text}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    _build_diff_html = _build_diff_html_backend

    # Per-take diff blocks
    for j, take in enumerate(_takes):
        if j == _ref_i:
            continue
        color = _COLORS[j % len(_COLORS)]
        take_words = take["text"].split()
        diff_html  = _build_diff_html(_ref_w, take_words, color, min_diff)
        st.markdown(
            f"<div style='background:#ecebe3;padding:10px 14px;border-radius:6px;"
            f"border-left:4px solid {color};margin:6px 0;line-height:1.75'>"
            f"<span style='color:{color};font-size:0.75rem'>Take {j + 1}"
            f" · {take['n_words']} Wörter</span><br>"
            f"<span style='color:#3d3a2a'>{diff_html}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        "<small style='color:#6b7280'>"
        "<del style='color:#9ca3af'>durchgestrichen</del> = in Referenz, im Take weggefallen &nbsp;·&nbsp; "
        "<mark style='background:#4d96ff28;border-bottom:2px solid #4d96ff;"
        "padding:0 2px;border-radius:2px;color:#3d3a2a'>markiert</mark> = verändert oder neu"
        "</small>",
        unsafe_allow_html=True,
    )

    st.divider()
    if st.button("Schließen", use_container_width=True):
        st.session_state.takes_compare_active = None
        st.rerun()


@st.dialog("Analyse-Fortschritt", dismissible=False)
def _takes_analysis_dialog():
    _pq = st.session_state.get("takes_progress_queue")
    _aq = st.session_state.get("takes_analysis_queue")

    _bar_ph = st.empty()
    _cap_ph = st.empty()

    if st.session_state.get("takes_analysis_running"):
        while True:
            _status, _value = None, None
            if _pq and not _pq.empty():
                _status, _value = _pq.get_nowait()

            if _status == "__DONE__":
                if _aq and not _aq.empty():
                    _res = _aq.get_nowait()
                    if isinstance(_res, dict) and "error" not in _res:
                        st.session_state.takes_analysis_result = _res
                        st.session_state.takes_selections = {
                            i: sec["selected_idx"]
                            for i, sec in enumerate(_res["sections"])
                        }
                    elif isinstance(_res, dict):
                        st.session_state.takes_analysis_error = _res.get("error", "")
                st.session_state.takes_analysis_running = False
                _bar_ph.progress(1.0)
                _cap_ph.caption("Fertig!")
                break

            if _value is not None:
                _bar_ph.progress(float(_value))
            if _status:
                _cap_ph.caption(_status)
            time.sleep(0.05)

    else:
        _bar_ph.progress(1.0)
        _cap_ph.caption("Fertig!")

    if not st.session_state.get("takes_analysis_running"):
        _err = st.session_state.pop("takes_analysis_error", None)
        if _err:
            st.error(f"Fehler: {_err}")
        if st.button("Schließen", type="primary", use_container_width=True):
            st.session_state.takes_show_analysis_dialog = False
            st.rerun()


# ── Analysis queue polling (before any widgets) ────────────────────────────────
# (Fallback: falls Dialog geschlossen wurde während Analyse noch lief)

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

# ── Dialog trigger ────────────────────────────────────────────────────────────

if st.session_state.get("takes_show_analysis_dialog"):
    _takes_analysis_dialog()

# ── Settings ──────────────────────────────────────────────────────────────────

st.subheader("Erkennungs-Parameter")

_col_model, _ = st.columns([1, 3])
with _col_model:
    whisper_model = st.selectbox(
        "Whisper-Modell",
        options=["tiny", "base", "small", "medium", "large"],
        index=2,
        help="Größere Modelle erkennen Text genauer, brauchen aber länger und mehr RAM. "
             "small/medium empfohlen für genauen Inhaltsvergleich.",
    )
col_s1, col_s2, col_s3, col_s4 = st.columns(4)
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
with col_s4:
    min_section_length = st.slider(
        "Min. Sektion-Länge (%)",
        min_value=0, max_value=80, value=30, step=5,
        help="Sektionen, deren längster Take kürzer als dieser Prozentsatz des längsten "
             "Takes überhaupt ist, werden ignoriert. Filtert Mikrofontests, kurze Einwürfe "
             "und Zwischenbemerkungen heraus.",
    )

st.divider()

# ── File selection ─────────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}

st.subheader("Clip auswählen")
if _resolve_ok:
    source_mode = st.radio("Quelle", ["Resolve Media Pool", "Datei-Pfad"], horizontal=True,
                           key="takes_source_mode")
else:
    source_mode = "Datei-Pfad"

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
        all_bins = sorted(_collect_bins(root), key=lambda s: s.strip().lower())
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
                        file_clips    = sorted(file_clips, key=lambda x: x[0].lower())
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
    import subprocess as _subp_pick
    _col_path, _col_btn = st.columns([5, 1])
    with _col_path:
        file_path_str = st.text_input(
            "Dateipfad", placeholder="/Volumes/Media/Recording/clip.mp4",
            key="takes_file_path_sel",
        )
    with _col_btn:
        st.markdown("<div style='margin-top:1.85rem'></div>", unsafe_allow_html=True)
        if st.button("", icon=":material/folder_open:", use_container_width=True, help="Datei auswählen"):
            _picked = None
            try:
                _r = _subp_pick.run(
                    ["osascript", "-e",
                     'POSIX path of (choose file with prompt "Clip auswählen")'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    _picked = _r.stdout.strip()
            except Exception:
                st.warning("Datei-Dialog nicht verfügbar — Pfad bitte manuell eingeben.")
            if _picked:
                st.session_state["_takes_file_path_pending"] = _picked
                st.rerun()
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
        st.caption(f"Quelle: `{_fname}` · Whisper {whisper_model}")
    with col_a2:
        analyse_clicked = st.button(
            "Analysieren",
            disabled=st.session_state.takes_analysis_running,
            use_container_width=True,
        )

    if analyse_clicked and not st.session_state.takes_analysis_running:
        _aq = queue.Queue()
        _pq = queue.Queue()
        st.session_state.takes_analysis_queue      = _aq
        st.session_state.takes_progress_queue      = _pq
        st.session_state.takes_analysis_running    = True
        st.session_state.takes_show_analysis_dialog = True
        st.session_state.takes_analysis_result     = None
        st.session_state.takes_selections          = {}

        def _run_takes_analysis(file_path, q, pause_thr, sim_thr, min_cov, min_sec_len, model_name, progress_q):
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
                        progress_q.put(("__DONE__", 1.0))
                        return
                    audio_path = _audio_tmp
                else:
                    audio_path = file_path

                # Probe audio duration for progress calculation
                import re as _re, io as _io
                _dur_r = _sp.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                    capture_output=True, text=True,
                )
                try:
                    _audio_dur = float(_dur_r.stdout.strip())
                except (ValueError, AttributeError):
                    _audio_dur = 0.0

                # Stdout interceptor: parses Whisper's "[mm:ss.mmm --> ...]" lines
                _ts_re = _re.compile(r'\[(\d+):(\d+\.\d+)')
                _orig_stdout = sys.stdout

                class _WhisperProgress(_io.TextIOBase):
                    def write(self, s):
                        for m in _ts_re.finditer(s):
                            ts = float(m.group(1)) * 60 + float(m.group(2))
                            pct = min(ts / _audio_dur, 1.0) if _audio_dur > 0 else 0
                            progress_q.put(("Transkribiere … {:d}%".format(int(pct * 100)), 0.1 + pct * 0.8))
                        _orig_stdout.write(s)
                        return len(s)
                    def flush(self):
                        _orig_stdout.flush()

                # Transcribe
                progress_q.put(("Modell wird geladen …", 0.05))
                model  = whisper.load_model(model_name)
                progress_q.put(("Transkribiere … 0%", 0.10))
                sys.stdout = _WhisperProgress()
                try:
                    result = model.transcribe(
                        audio_path,
                        word_timestamps=True,
                        verbose=True,
                        condition_on_previous_text=False,
                    )
                finally:
                    sys.stdout = _orig_stdout
                progress_q.put(("Takes werden analysiert …", 0.92))

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
                    progress_q.put(("__DONE__", 1.0))
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

                # Filter short sections relative to the longest take overall
                discarded_raw = []
                if min_sec_len > 0 and sections_raw:
                    global_max = max(len(t) for takes in sections_raw for t in takes)
                    threshold  = global_max * (min_sec_len / 100)
                    kept, discarded_raw = [], []
                    for takes in sections_raw:
                        (kept if max(len(t) for t in takes) >= threshold else discarded_raw).append(takes)
                    sections_raw = kept

                # Merge adjacent sections whose content is similar
                # (filtered-out segments break grouping → neighbouring script takes end up separate)
                if len(sections_raw) > 1:
                    merged = [sections_raw[0]]
                    for takes in sections_raw[1:]:
                        ref_words = _start_words(max(merged[-1], key=len))
                        cur_words = _start_words(max(takes,       key=len))
                        if _similarity(ref_words, cur_words) >= sim_thr:
                            merged[-1].extend(takes)
                        else:
                            merged.append(takes)
                    sections_raw = merged

                discarded_takes = [
                    {
                        "start": round(max(0.0, t[0]["start"] - PRE_ROLL), 3),
                        "end":   round(t[-1]["end"] + POST_ROLL, 3),
                    }
                    for takes in discarded_raw for t in takes
                ]

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
                    "sections":        result_sections,
                    "file_path":       file_path,
                    "discarded_takes": discarded_takes,
                })
                progress_q.put(("__DONE__", 1.0))

            except Exception as exc:
                import traceback
                _log.exception("Take Selector: Analyse-Fehler")
                q.put({"error": f"{exc}\n\n{traceback.format_exc()[-800:]}"})
                progress_q.put(("__DONE__", 1.0))
            finally:
                if _audio_tmp and Path(_audio_tmp).exists():
                    try:
                        Path(_audio_tmp).unlink()
                    except Exception:
                        pass

        threading.Thread(
            target=_run_takes_analysis,
            args=(_fpath, _aq, pause_threshold, similarity_threshold, min_coverage, min_section_length, whisper_model, _pq),
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


def _fmt(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


for i, section in enumerate(sections):
    takes   = section["takes"]
    sel_idx = selections.get(i, section["selected_idx"])
    sel     = takes[sel_idx]
    n_t     = len(takes)

    with st.expander(
        f"Sektion {i + 1}  ·  {n_t} Take{'s' if n_t > 1 else ''}  ·  "
        f"Take {sel_idx + 1} ausgewählt  ·  "
        f"{_fmt(sel['start'])} – {_fmt(sel['end'])}  ({sel['end'] - sel['start']:.1f}s)",
        expanded=True,
    ):
        if n_t > 1:
            if st.button(
                "Inhalt vergleichen",
                icon=":material/bar_chart:",
                key=f"takes_cmp_{i}",
                help="Zeigt welche Informationen in welchen Takes vorhanden oder abweichend sind.",
            ):
                st.session_state.takes_compare_sec = i
                st.rerun()

        for j, take in enumerate(takes):
            is_sel   = (j == sel_idx)
            cov_pct  = int(take["coverage"] * 100)
            dur      = take["end"] - take["start"]

            col_btn, col_info, col_tr = st.columns([1, 8, 1])
            with col_btn:
                if st.button(
                    "",
                    icon=":material/check_circle:" if is_sel else ":material/radio_button_unchecked:",
                    key=f"takes_btn_{i}_{j}",
                    type="primary" if is_sel else "secondary",
                    use_container_width=True,
                    help="Diesen Take auswählen",
                ):
                    st.session_state.takes_selections[i] = j
                    st.rerun()
            with col_info:
                st.caption(
                    f"**Take {j + 1}**  ·  "
                    f"{_fmt(take['start'])} – {_fmt(take['end'])}  ({dur:.1f}s)  ·  "
                    f"{take['n_words']} Wörter  ·  {cov_pct}% Vollständigkeit"
                    + ("  ← **ausgewählt**" if is_sel else "")
                )
                st.write(
                    f"_{take['text'][:150]}{'…' if len(take['text']) > 150 else ''}_"
                )
            with col_tr:
                if st.button(
                    "",
                    icon=":material/description:",
                    key=f"takes_tr_{i}_{j}",
                    use_container_width=True,
                    help="Vollständiges Transkript anzeigen",
                ):
                    st.session_state.takes_transcript_label = (
                        f"Sektion {i + 1} · Take {j + 1} · "
                        f"{take['start']:.1f}s – {take['end']:.1f}s"
                    )
                    st.session_state.takes_transcript_text  = take["text"]
                    st.session_state.takes_show_transcript  = True
                    st.rerun()

if st.session_state.get("takes_show_transcript"):
    _show_transcript_dialog()

if st.session_state.get("takes_compare_sec") is not None:
    _show_compare_dialog()

# ── Waveform-Übersicht ────────────────────────────────────────────────────────

st.divider()
st.subheader("Clip-Übersicht")

try:
    import subprocess as _sp_wf
    import numpy as _np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt

    _WF_SR = 200  # samples/s für Anzeige

    _wf_proc = _sp_wf.run(
        ["ffmpeg", "-i", _result["file_path"],
         "-map", "0:a:0", "-ac", "1", "-ar", str(_WF_SR),
         "-f", "f32le", "pipe:1"],
        capture_output=True,
    )
    _wf = _np.frombuffer(_wf_proc.stdout, dtype=_np.float32)
    _wf_t = _np.arange(len(_wf)) / _WF_SR

    _fig, _ax = _plt.subplots(figsize=(14, 2.5))
    _fig.patch.set_facecolor("#0e1117")
    _ax.set_facecolor("#0e1117")

    # Waveform
    _ax.plot(_wf_t, _wf, color="#ffffff", linewidth=0.3)

    # Verworfene Takes (rot)
    for _dt in _result.get("discarded_takes", []):
        _ax.axvspan(_dt["start"], _dt["end"], alpha=0.25, color="#ff4444", linewidth=0)

    # Alle behaltenen Takes (hellgrau)
    for _sec in sections:
        for _take in _sec["takes"]:
            _ax.axvspan(_take["start"], _take["end"], alpha=0.15, color="#ffffff", linewidth=0)

    # Ausgewählte Takes (grün)
    for _i, _sec in enumerate(sections):
        _sel_take = _sec["takes"][selections.get(_i, _sec["selected_idx"])]
        _ax.axvspan(_sel_take["start"], _sel_take["end"], alpha=0.35, color="#00c853", linewidth=0)

    _ax.set_xlim(0, _wf_t[-1] if len(_wf_t) else 1)
    _ax.set_xlabel("Zeit (s)", color="#888888", fontsize=8)
    _ax.tick_params(colors="#888888", labelsize=7)
    for _spine in _ax.spines.values():
        _spine.set_visible(False)

    _plt.tight_layout(pad=0.3)
    st.pyplot(_fig)
    _plt.close(_fig)

    st.caption("🟩 Ausgewählter Take · ░ Weiterer Take · 🟥 Herausgefiltert (Min. Sektion-Länge)")

except Exception as _wf_err:
    st.caption(f"Waveform nicht verfügbar: {_wf_err}")

# ── Timeline-Export ───────────────────────────────────────────────────────────

st.divider()
_use_resolve_export = _resolve_ok and source_mode == "Resolve Media Pool"
st.subheader("Timeline schneiden" if _use_resolve_export else "AAF exportieren")

col_tl1, col_tl2 = st.columns([2, 3])
with col_tl1:
    timeline_name = st.text_input("Timeline-Name", value="Best Takes", key="takes_tl_name")
with col_tl2:
    st.write("")
    st.caption(
        f"{n_sections} Takes · Gesamtdauer: {total_dur:.1f}s  "
        f"({total_dur / 60:.1f} min)"
    )

if _use_resolve_export:
    _rcol1, _rcol2 = st.columns(2)
    cut_clicked       = _rcol1.button("Best Takes",    icon=":material/content_cut:", type="primary", use_container_width=True)
    cut_multi_clicked = _rcol2.button("Alle Takes (V1/V2)", icon=":material/content_cut:", type="secondary", use_container_width=True)

    def _resolve_connect():
        from resolve_bridge.connection import get_resolve
        resolve  = get_resolve()
        project  = resolve.GetProjectManager().GetCurrentProject()
        mp       = project.GetMediaPool()
        fps_str  = project.GetSetting("timelineFrameRate")
        fps      = float(fps_str) if fps_str else 25.0

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
        return project, mp, fps, mpi

    if cut_clicked:
        selected_takes = [
            sections[i]["takes"][selections.get(i, sections[i]["selected_idx"])]
            for i in range(n_sections)
        ]
        try:
            project, mp, fps, mpi = _resolve_connect()
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

    if cut_multi_clicked:
        # Alle Takes (nicht gefilterte) chronologisch, Best Takes auf V2
        all_takes_ordered = []
        for _i in range(n_sections):
            _best_idx = selections.get(_i, sections[_i]["selected_idx"])
            for _j, _take in enumerate(sections[_i]["takes"]):
                all_takes_ordered.append({**_take, "is_best": _j == _best_idx})
        all_takes_ordered.sort(key=lambda t: t["start"])

        try:
            project, mp, fps, mpi = _resolve_connect()
            tl = mp.CreateEmptyTimeline(timeline_name)
            if tl is None:
                st.error("Timeline konnte nicht erstellt werden.")
                st.stop()
            project.SetCurrentTimeline(tl)
            tl.AddTrack("video")   # V2

            record_frame = 0
            for _take in all_takes_ordered:
                _sf  = int(math.floor(_take["start"] * fps))
                _ef  = max(_sf + 1, int(math.ceil(_take["end"] * fps)) - 1)
                _dur = _ef - _sf
                mp.AppendToTimeline([{
                    "mediaPoolItem": mpi,
                    "startFrame":    _sf,
                    "endFrame":      _ef,
                    "trackIndex":    2 if _take["is_best"] else 1,
                    "recordFrame":   record_frame,
                }])
                record_frame += _dur

            _n_best   = sum(1 for t in all_takes_ordered if t["is_best"])
            _n_others = len(all_takes_ordered) - _n_best
            st.success(
                f"Timeline **{timeline_name}** mit {len(all_takes_ordered)} Takes erstellt "
                f"({_n_best} Best auf V2, {_n_others} weitere auf V1)."
            )
        except Exception as _cut_err:
            st.error(f"Fehler beim Timeline-Aufbau: {_cut_err}")

else:
    # ── AAF-Export (kein Resolve oder Datei-Pfad-Modus) ───────────────────────


    def _choose_save_path(default_name: str) -> str | None:
        import subprocess as _sp_dlg
        try:
            _r = _sp_dlg.run(
                ["osascript", "-e",
                 f'POSIX path of (choose file name default name "{default_name}.aaf" '
                 f'with prompt "AAF speichern unter")'],
                capture_output=True, text=True, timeout=60,
            )
            if _r.returncode == 0 and _r.stdout.strip():
                path = _r.stdout.strip()
                return path if path.endswith(".aaf") else path + ".aaf"
        except Exception:
            st.error("Speicher-Dialog nicht verfügbar.")
        return None

    _aaf_col1, _aaf_col2 = st.columns(2)
    _aaf_best_clicked  = _aaf_col1.button("AAF Best Takes",         type="primary",   use_container_width=True)
    _aaf_multi_clicked = _aaf_col2.button("AAF Alle Takes (V1/V2)", type="secondary", use_container_width=True)

    _clip_stem = Path(_result["file_path"]).stem

    if _aaf_best_clicked:
        _save_path = _choose_save_path(f"{_clip_stem}_{timeline_name}".replace(" ", "_"))
        if _save_path:
            selected_takes = [
                sections[i]["takes"][selections.get(i, sections[i]["selected_idx"])]
                for i in range(n_sections)
            ]
            try:
                _build_takes_aaf(
                    _result["file_path"], selected_takes,
                    _save_path, fps=_probe_fps(_result["file_path"]), tl_name=timeline_name,
                )
                st.success(
                    f"AAF gespeichert: `{_save_path}`  \n"
                    f"{n_sections} Takes · {total_dur:.1f}s"
                )
            except Exception as _aaf_err:
                st.error(f"AAF-Export fehlgeschlagen: {_aaf_err}")

    if _aaf_multi_clicked:
        _safe_name = f"{_clip_stem}_{timeline_name}_V1V2".replace(" ", "_")
        _save_path = _choose_save_path(_safe_name)
        if _save_path:
            # Alle Takes chronologisch, best_set als Menge von Indizes
            _all_takes_ordered = []
            for _i in range(n_sections):
                _best_idx = selections.get(_i, sections[_i]["selected_idx"])
                for _j, _take in enumerate(sections[_i]["takes"]):
                    _all_takes_ordered.append({**_take, "_is_best": _j == _best_idx})
            _all_takes_ordered.sort(key=lambda t: t["start"])
            _best_set = {idx for idx, t in enumerate(_all_takes_ordered) if t["_is_best"]}

            try:
                _build_takes_aaf(
                    _result["file_path"], _all_takes_ordered,
                    _save_path, fps=_probe_fps(_result["file_path"]),
                    tl_name=timeline_name, best_set=_best_set,
                )
                _n_best   = len(_best_set)
                _n_others = len(_all_takes_ordered) - _n_best
                st.success(
                    f"AAF gespeichert: `{_save_path}`  \n"
                    f"{len(_all_takes_ordered)} Takes ({_n_best} Best auf V2, {_n_others} weitere auf V1)"
                )
            except Exception as _aaf_err:
                st.error(f"AAF-Export fehlgeschlagen: {_aaf_err}")
