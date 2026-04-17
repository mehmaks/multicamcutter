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

    def _build_diff_html(ref_words, take_words, color, min_d):
        """Inline diff: deletions from ref = gray strikethrough, changes/insertions = colored mark."""
        opcodes = _dl.SequenceMatcher(None, ref_words, take_words, autojunk=False).get_opcodes()
        parts = []
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                parts.append(_html_mod.escape(" ".join(take_words[j1:j2])))
            else:
                block_len = max(i2 - i1, j2 - j1)
                if block_len < min_d:
                    # Treat as equal — show take's version (or skip if pure deletion)
                    if j1 < j2:
                        parts.append(_html_mod.escape(" ".join(take_words[j1:j2])))
                else:
                    if tag in ("replace", "delete") and i1 < i2:
                        deleted = _html_mod.escape(" ".join(ref_words[i1:i2]))
                        parts.append(
                            f"<del style='color:#9ca3af;text-decoration-color:#9ca3af'>{deleted}</del>"
                        )
                    if tag in ("replace", "insert") and j1 < j2:
                        inserted = _html_mod.escape(" ".join(take_words[j1:j2]))
                        parts.append(
                            f"<mark style='background:{color}28;border-bottom:2px solid {color};"
                            f"padding:0 2px;border-radius:2px;color:#3d3a2a'>{inserted}</mark>"
                        )
        return " ".join(parts)

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

with st.expander("Erkennungs-Parameter", expanded=True):
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

    def _build_takes_aaf(source_path: str, takes: list, output_path: str,
                         fps: float, tl_name: str, best_set: set | None = None) -> None:
        """
        best_set: set of indices into `takes` that are "best takes" (multi-track mode).
                  None → single V1 track with all takes (legacy mode).
        """
        import subprocess as _sp_aaf
        import aaf2
        from fractions import Fraction

        def _probe_duration(path: str) -> float:
            r = _sp_aaf.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True,
            )
            try:
                return float(r.stdout.strip())
            except (ValueError, AttributeError):
                return 0.0

        def _probe_video(path: str) -> dict:
            r = _sp_aaf.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,display_aspect_ratio",
                 "-of", "default=noprint_wrappers=1", path],
                capture_output=True, text=True,
            )
            info = {}
            for line in r.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    info[k.strip()] = v.strip()
            return info

        def _probe_audio_channels(path: str) -> int:
            r = _sp_aaf.run(
                ["ffprobe", "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=channels",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True,
            )
            try:
                return int(r.stdout.strip())
            except (ValueError, AttributeError):
                return 2

        def _probe_timecode(path: str, fps: int) -> int:
            """Liest den Start-Timecode aus dem tmcd-Track der Quelldatei (in Frames)."""
            import json as _json
            r = _sp_aaf.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", path],
                capture_output=True, text=True,
            )
            try:
                data = _json.loads(r.stdout)
                for stream in data.get("streams", []):
                    tc_str = stream.get("tags", {}).get("timecode", "")
                    if tc_str and tc_str.count(":") == 3:
                        hh, mm, ss, ff = (int(x) for x in tc_str.split(":"))
                        return (hh * 3600 + mm * 60 + ss) * fps + ff
            except Exception:
                pass
            return 0

        AUDIO_SR = 48000
        fps_int  = int(round(fps))
        fps_frac = Fraction(fps_int, 1)
        src      = Path(source_path)
        src_uri  = src.resolve().as_uri()   # file:///Volumes/... — voller Pfad wie DaVinci

        dur_secs   = _probe_duration(source_path)
        dur_vid    = int(round(dur_secs * fps_int))
        dur_aud    = int(round(dur_secs * AUDIO_SR))
        vid_info   = _probe_video(source_path)
        vid_w      = int(vid_info.get("width",  1920))
        vid_h      = int(vid_info.get("height", 1080))
        dar_str    = vid_info.get("display_aspect_ratio", "16:9")
        try:
            dar_n, dar_d = dar_str.split(":")
            aspect = Fraction(int(dar_n), int(dar_d))
        except Exception:
            aspect = Fraction(vid_w, vid_h)
        n_channels = _probe_audio_channels(source_path)
        tc_frames  = _probe_timecode(source_path, fps_int)

        def _make_tape(f, media_kind, phys, tc_frames, dur_vid, fps_int):
            """Erstellt einen TapeDescriptor-SourceMob (TC-Träger, wie DaVinci)."""
            tape      = f.create.SourceMob()
            tape.name = ""
            tape.descriptor = f.create.TapeDescriptor()

            tc_seg = f.create.Timecode()
            tc_seg["FPS"].value    = fps_int
            tc_seg["Drop"].value   = False
            tc_seg["Start"].value  = tc_frames
            tc_seg["Length"].value = dur_vid
            tc_slot = tape.create_timeline_slot(edit_rate=fps_int)
            tc_slot.segment = tc_seg
            tc_slot["PhysicalTrackNumber"].value = 1

            if media_kind == "picture":
                media_slot = tape.create_picture_slot(edit_rate=fps_int)
            else:
                media_slot = tape.create_sound_slot(edit_rate=fps_int)
            media_slot["PhysicalTrackNumber"].value = phys
            end_sc = f.create.SourceClip(media_kind=media_kind, length=dur_vid)
            media_slot.segment = end_sc  # mob=None → Ende der Kette
            return tape, media_slot

        with aaf2.open(output_path, "w") as f:
            # ── TapeDescriptor-Mobs (TC-Träger, ein Mob pro Track) ──
            tape_v,  tape_v_slot  = _make_tape(f, "picture", 1, tc_frames, dur_vid, fps_int)
            tape_a1, tape_a1_slot = _make_tape(f, "sound",   1, tc_frames, dur_vid, fps_int)
            tape_a2, tape_a2_slot = _make_tape(f, "sound",   2, tc_frames, dur_vid, fps_int)
            f.content.mobs.append(tape_v)
            f.content.mobs.append(tape_a1)
            f.content.mobs.append(tape_a2)

            # ── CDCIDescriptor SourceMob (Video, URL → Quelldatei) ──
            mob_vid      = f.create.SourceMob()
            mob_vid.name = src.stem

            cdci = f.create.CDCIDescriptor()
            cdci["StoredWidth"].value           = vid_w
            cdci["StoredHeight"].value          = vid_h
            cdci["ImageAspectRatio"].value      = aspect
            cdci["FrameLayout"].value           = "FullFrame"
            cdci["HorizontalSubsampling"].value = 2
            cdci["ComponentWidth"].value        = 8
            cdci["VideoLineMap"].value          = [0, 1]
            cdci["SampleRate"].value            = fps_frac
            cdci["Length"].value                = dur_vid
            cdci_loc = f.create.NetworkLocator()
            cdci_loc["URLString"].value = src_uri
            cdci["Locator"].value = [cdci_loc]
            mob_vid.descriptor = cdci

            fv = mob_vid.create_picture_slot(edit_rate=fps_int)
            fv["PhysicalTrackNumber"].value = 1
            sc_fv = f.create.SourceClip(media_kind="picture", length=dur_vid)
            sc_fv.mob = tape_v; sc_fv.slot = tape_v_slot; sc_fv.start = 0
            fv.segment = sc_fv
            f.content.mobs.append(mob_vid)

            # ── PCMDescriptor SourceMob (Audio, URL → Quelldatei) ──
            mob_aud      = f.create.SourceMob()
            mob_aud.name = src.stem

            pcm = f.create.PCMDescriptor()
            pcm["AudioSamplingRate"].value = Fraction(AUDIO_SR, 1)
            pcm["Channels"].value         = n_channels
            pcm["QuantizationBits"].value = 16
            pcm["BlockAlign"].value       = 2
            pcm["AverageBPS"].value       = AUDIO_SR * 2
            pcm["SampleRate"].value       = Fraction(AUDIO_SR, 1)
            pcm["Length"].value           = dur_aud   # in Samples, wie DaVinci
            pcm_loc = f.create.NetworkLocator()
            pcm_loc["URLString"].value = src_uri
            pcm["Locator"].value = [pcm_loc]
            mob_aud.descriptor = pcm

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

            # ── MasterMob ──
            master      = f.create.MasterMob()
            master.name = src.stem

            m_vid = master.create_picture_slot(edit_rate=fps_int)
            m_vid["PhysicalTrackNumber"].value = 1
            sc_mv = f.create.SourceClip(media_kind="picture", length=dur_vid)
            sc_mv.mob = mob_vid; sc_mv.slot = fv; sc_mv.start = 0
            m_vid.segment = sc_mv

            m_a1 = master.create_sound_slot(edit_rate=fps_int)
            m_a1["PhysicalTrackNumber"].value = 1
            sc_ma1 = f.create.SourceClip(media_kind="sound", length=dur_vid)
            sc_ma1.mob = mob_aud; sc_ma1.slot = fa1; sc_ma1.start = 0
            m_a1.segment = sc_ma1

            m_a2 = master.create_sound_slot(edit_rate=fps_int)
            m_a2["PhysicalTrackNumber"].value = 2
            sc_ma2 = f.create.SourceClip(media_kind="sound", length=dur_vid)
            sc_ma2.mob = mob_aud; sc_ma2.slot = fa2; sc_ma2.start = 0
            m_a2.segment = sc_ma2

            f.content.mobs.append(master)

            # ── CompositionMob ──
            comp     = f.create.CompositionMob(tl_name)
            total_fr = sum(max(1, int(round((t["end"] - t["start"]) * fps_int))) for t in takes)

            def _seq(media_kind, master_slot, skip_indices=None):
                """Sequence mit SourceClips; Positionen in skip_indices werden als Filler eingefügt."""
                seq = f.create.Sequence(media_kind=media_kind, length=total_fr)
                for idx, take in enumerate(takes):
                    sf = int(round(take["start"] * fps_int))
                    lf = max(1, int(round((take["end"] - take["start"]) * fps_int)))
                    if skip_indices is not None and idx in skip_indices:
                        # Filler (SourceClip ohne Mob = Gap)
                        fill = f.create.SourceClip(media_kind=media_kind, length=lf)
                        seq.components.append(fill)
                    else:
                        sc      = f.create.SourceClip(media_kind=media_kind, length=lf)
                        sc.mob  = master; sc.slot = master_slot; sc.start = sf
                        seq.components.append(sc)
                return seq

            if best_set is None:
                # Einzelne V1-Spur, alle Takes
                comp_vid = comp.create_picture_slot(edit_rate=fps_int)
                comp_vid["PhysicalTrackNumber"].value = 1
                comp_vid.segment = _seq("picture", m_vid)
            else:
                # V1: nur Nicht-Best-Takes (Best-Take-Positionen = Filler)
                non_best = set(range(len(takes))) - best_set
                comp_vid1 = comp.create_picture_slot(edit_rate=fps_int)
                comp_vid1["PhysicalTrackNumber"].value = 1
                comp_vid1.segment = _seq("picture", m_vid, skip_indices=best_set)

                # V2: nur Best-Takes (Nicht-Best-Positionen = Filler)
                comp_vid2 = comp.create_picture_slot(edit_rate=fps_int)
                comp_vid2["PhysicalTrackNumber"].value = 2
                comp_vid2.segment = _seq("picture", m_vid, skip_indices=non_best)

            # Audio: alle Takes auf beiden Spuren (unabhängig von V1/V2)
            comp_a1 = comp.create_sound_slot(edit_rate=fps_int)
            comp_a1["PhysicalTrackNumber"].value = 1
            comp_a1.segment = _seq("sound", m_a1)

            comp_a2 = comp.create_sound_slot(edit_rate=fps_int)
            comp_a2["PhysicalTrackNumber"].value = 2
            comp_a2.segment = _seq("sound", m_a2)

            f.content.mobs.append(comp)

    def _probe_fps(file_path: str) -> float:
        import subprocess as _sp_fps
        _fps_r = _sp_fps.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1",
             file_path],
            capture_output=True, text=True,
        )
        _fps_raw = _fps_r.stdout.strip()
        if "/" in _fps_raw:
            _n, _d = _fps_raw.split("/")
            return float(_n) / float(_d)
        return float(_fps_raw) if _fps_raw else 25.0

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
