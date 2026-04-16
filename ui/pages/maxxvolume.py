"""
MaxxVolume — Voice Dynamics Processing via ffmpeg
Repliziert die Waves MaxxVolume Speech-Preset-Kette:
  Gate → Upward Compressor → Leveler (AGC) → Limiter

Quellen: Clip aus Media Pool Bin · Aktive Timeline (In/Out oder gesamt) · Ordner
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import threading
import queue
import tempfile
import subprocess
import time
import json
from pathlib import Path

st.title("📢 MaxxVolume")
st.caption("Voice Dynamics · Gate → Upward Compressor → Leveler (AGC) → Limiter · nur für Sprachspuren")

AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv"}

# ── Session state ─────────────────────────────────────────────────────────────

for _k, _v in {
    "mv_running": False,
    "mv_log":     [],
    "mv_queue":   None,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Signal chain visual ───────────────────────────────────────────────────────

st.caption("**Signal-Kette:** `INPUT` → `Gate` → `Upward Compressor` → `Leveler (AGC)` → `Limiter` → `OUTPUT`")
st.divider()

# ── Parameters ────────────────────────────────────────────────────────────────

st.subheader("Parameter")

col1, col2, col3 = st.columns(3)

with col1:
    gate_threshold = st.slider(
        "Gate Threshold",
        min_value=-60.0, max_value=-10.0, value=-39.1, step=0.5,
        format="%.1f dB",
        help="Pegel unterhalb dem das Gate schließt. **Default:** −39.1 dB (MaxxVolume Preset)",
    )
with col2:
    leveler_target = st.slider(
        "Leveler Target",
        min_value=-30.0, max_value=-10.0, value=-20.7, step=0.5,
        format="%.1f LUFS",
        help="Ziel-Loudness des AGC-Levelers. **Default:** −20.7 LUFS (MaxxVolume Preset)",
    )
with col3:
    output_ceiling = st.slider(
        "Output Ceiling",
        min_value=-6.0, max_value=-0.5, value=-1.5, step=0.5,
        format="%.1f dBFS",
        help="True Peak Ceiling für Loudnorm und Brickwall-Limiter. **Default:** −1.5 dBFS",
    )

with st.expander("Erweiterte Parameter"):
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        low_level_gain = st.slider(
            "Low Level Gain (Upward Compressor)",
            min_value=0.0, max_value=24.0, value=17.0, step=0.5,
            format="+%.1f dB",
            help="Maximale Anhebung leiser Passagen. **Default:** +17.0 dB",
        )
    with col_a2:
        high_level_gain = st.slider(
            "High Level Gain (Peak Limiter)",
            min_value=-12.0, max_value=0.0, value=-4.5, step=0.5,
            format="%.1f dB",
            help="Maximale Absenkung lauter Peaks. **Default:** −4.5 dB",
        )

# ── Filter chain builder ──────────────────────────────────────────────────────

def _build_filterchain(gate_db, leveler_lufs, ceiling_dbfs, ll_gain, hl_gain):
    gate_linear  = round(10 ** (gate_db / 20), 6)
    limit_linear = round(min(max(10 ** (ceiling_dbfs / 20), 0.001), 1.0), 6)

    p_gate_out  = round(gate_db + ll_gain, 1)
    p_upper_out = round(-31.5 + ll_gain, 1)
    compand_pts = (
        f"-90/{round(-90 + ll_gain, 1)}"
        f"|{gate_db}/{p_gate_out}"
        f"|-31.5/{p_upper_out}"
        f"|-20/-20|0/0"
    )

    return ", ".join([
        f"agate=threshold={gate_linear}:range=1:attack=10:release=250",
        f"compand=attacks=0.02:decays=0.4:points={compand_pts}:soft-knee=4",
        f"loudnorm=I={leveler_lufs}:TP={ceiling_dbfs}:LRA=9:linear=true",
        f"alimiter=level_in=1:level_out=1:limit={limit_linear}:attack=5:release=50:level=disabled",
    ])

st.divider()

# ── Source selection ──────────────────────────────────────────────────────────

st.subheader("Quelle")

source_mode = st.radio(
    "Quelle", ["Resolve Media Pool", "Aktive Timeline", "Ordner / Dateien"],
    horizontal=True, key="mv_source_mode", label_visibility="collapsed",
)

selected_path_files: list = []   # [(name, path), ...]
resolve_ctx: dict = {}           # holds resolve objects for all modes

# ── Resolve helper: shared connection ─────────────────────────────────────────

_resolve_obj = None
_resolve_error = None

if source_mode in ("Resolve Media Pool", "Aktive Timeline"):
    try:
        from resolve_bridge.connection import get_resolve
        _resolve_obj = get_resolve()
        _project   = _resolve_obj.GetProjectManager().GetCurrentProject()
        _mp        = _project.GetMediaPool()
        _root      = _mp.GetRootFolder()
        resolve_ctx["resolve"]  = _resolve_obj
        resolve_ctx["project"]  = _project
        resolve_ctx["mp"]       = _mp
        resolve_ctx["root"]     = _root
    except Exception as e:
        _resolve_error = str(e)

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

# ── Mode: Resolve Media Pool ──────────────────────────────────────────────────

if source_mode == "Resolve Media Pool":
    if _resolve_error:
        st.error("Resolve nicht verbunden")
        st.caption(_resolve_error)
    else:
        all_bins = _collect_bins(resolve_ctx["root"])
        if not all_bins:
            st.warning("Keine Bins im Media Pool gefunden.")
        else:
            selected_display = st.selectbox("Media Pool Bin", options=all_bins, key="mv_bin")
            bin_name = selected_display.strip() if selected_display else None
            if bin_name:
                folder = _find_folder(resolve_ctx["root"], bin_name)
                if folder:
                    clips = folder.GetClipList() or []
                    _all_ext = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
                    audio_clips = [
                        (c.GetName(), c.GetClipProperty("File Path"))
                        for c in clips
                        if c.GetClipProperty("File Path")
                        and Path(c.GetClipProperty("File Path")).suffix.lower() in _all_ext
                    ]
                    if audio_clips:
                        chosen = st.multiselect(
                            f"Clips in '{bin_name}'",
                            options=[n for n, _ in audio_clips],
                            default=[n for n, _ in audio_clips],
                            key="mv_clip_select",
                        )
                        selected_path_files = [(n, p) for n, p in audio_clips if n in chosen]
                        resolve_ctx["import_folder"] = folder
                        _n_video = sum(
                            1 for _, p in selected_path_files
                            if Path(p).suffix.lower() in VIDEO_EXTENSIONS
                        )
                        if _n_video:
                            st.caption(f"ℹ {_n_video} Videodatei(en) — Audio (Spur 1) wird via ffmpeg extrahiert.")
                    else:
                        st.info("Keine Audio- oder Videodateien in diesem Bin.")

# ── Mode: Aktive Timeline ─────────────────────────────────────────────────────

elif source_mode == "Aktive Timeline":
    if _resolve_error:
        st.error("Resolve nicht verbunden")
        st.caption(_resolve_error)
    else:
        _timeline = _project.GetCurrentTimeline() if resolve_ctx.get("project") else None
        if not _timeline:
            st.warning("Keine aktive Timeline in Resolve gefunden.")
        else:
            _tl_name      = _timeline.GetName()
            _tl_start     = _timeline.GetStartFrame()
            _tl_end       = _timeline.GetEndFrame()
            _tl_dur_frames = _tl_end - _tl_start

            # Try to read in/out points
            try:
                _in_pt  = _timeline.GetCurrentInPoint()
                _out_pt = _timeline.GetCurrentOutPoint()
                _has_inout = (
                    isinstance(_in_pt, int) and isinstance(_out_pt, int)
                    and _out_pt > _in_pt
                )
            except AttributeError:
                _in_pt = _out_pt = None
                _has_inout = False

            col_tl1, col_tl2 = st.columns(2)
            with col_tl1:
                st.info(f"**{_tl_name}**  \n{_tl_dur_frames} Frames total")
            with col_tl2:
                if _has_inout:
                    st.success(
                        f"In/Out gesetzt  \n"
                        f"Frame {_in_pt} → {_out_pt}  \n"
                        f"({_out_pt - _in_pt} Frames)"
                    )
                else:
                    st.caption("Kein In/Out gesetzt — gesamte Timeline wird gerendert.")

            # Target bin for the processed file
            all_bins = _collect_bins(resolve_ctx["root"])
            _bin_sel = st.selectbox(
                "Ziel-Bin (für Import des Ergebnisses)",
                options=all_bins,
                key="mv_tl_bin",
            )
            _tl_target_folder = _find_folder(resolve_ctx["root"], _bin_sel.strip()) if _bin_sel else None

            resolve_ctx.update({
                "timeline":        _timeline,
                "tl_name":         _tl_name,
                "tl_start":        _tl_start,
                "tl_end":          _tl_end,
                "has_inout":       _has_inout,
                "in_pt":           _in_pt,
                "out_pt":          _out_pt,
                "import_folder":   _tl_target_folder,
                "tl_mode":         True,
            })

# ── Mode: Ordner / Dateien ────────────────────────────────────────────────────

elif source_mode == "Ordner / Dateien":
    col_fp1, col_fp2 = st.columns([4, 1])
    with col_fp2:
        st.write("")
        if st.button("📁 Durchsuchen", use_container_width=True, key="mv_browse"):
            import subprocess as _sp_dlg
            try:
                _r = _sp_dlg.run(
                    ["osascript", "-e",
                     'POSIX path of (choose file with prompt "Audio- oder Videodatei auswählen")'],
                    capture_output=True, text=True, timeout=60,
                )
                if _r.returncode == 0 and _r.stdout.strip():
                    st.session_state["mv_file_path"] = _r.stdout.strip()
            except Exception:
                pass
    with col_fp1:
        _fp = st.text_input(
            "Dateipfad", key="mv_file_path",
            placeholder="/Volumes/Media/Interview.mp4",
        )

    if _fp:
        _fp_path = Path(_fp)
        if not _fp_path.exists():
            st.error("Datei nicht gefunden.")
        elif _fp_path.suffix.lower() not in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
            st.error(f"Nicht unterstütztes Format: {_fp_path.suffix}")
        else:
            selected_path_files = [(_fp_path.name, str(_fp_path))]
            st.caption(f"1 Datei ausgewählt: `{_fp_path.name}`")

# ── Processing functions ──────────────────────────────────────────────────────

def _run_ffmpeg_maxxvolume(src_path: str, out_path: str, filterchain: str, q: queue.Queue) -> bool:
    """Run ffmpeg MaxxVolume chain. Returns True on success."""
    cmd = [
        "ffmpeg", "-y", "-i", src_path,
        "-af", filterchain,
        "-ar", "48000",
        "-acodec", "pcm_s24le",
        out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        q.put(f"  Fehler (ffmpeg): {r.stderr[-300:]}")
        return False
    return True


def _get_audio_frames(wav_path: str, fps: float) -> int:
    """Return duration in timeline frames via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", wav_path],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        data = json.loads(r.stdout)
        duration = float(data["streams"][0]["duration"])
        return max(1, int(duration * fps) - 1)
    except Exception:
        return 0


def _process_timeline(ctx: dict, filterchain: str, q: queue.Queue):
    """Render timeline audio → MaxxVolume → re-import → place on new timeline track."""
    project   = ctx["project"]
    mp        = ctx["mp"]
    timeline  = ctx["timeline"]
    tl_name   = ctx["tl_name"]
    tl_start  = ctx["tl_start"]
    has_inout = ctx["has_inout"]
    in_pt     = ctx["in_pt"]
    out_pt    = ctx["out_pt"]
    imp_folder = ctx.get("import_folder")

    tmp_dir = tempfile.mkdtemp()
    src_name = f"{tl_name}_maxxvol_src"

    try:
        # 1. Render audio from timeline
        q.put(f"► {tl_name}")
        q.put(f"  Render-Einstellungen: Audio-Only WAV 24-bit 48kHz"
              + (" (In/Out)" if has_inout else " (gesamt)"))

        render_settings = {
            "ExportVideo":    False,
            "ExportAudio":    True,
            "Format":         "wav",
            "AudioCodec":     "Linear PCM",
            "AudioBitDepth":  24,
            "AudioSampleRate": 48000,
            "TargetDir":      tmp_dir,
            "CustomName":     src_name,
        }
        if has_inout:
            render_settings["SelectAllFrames"] = False
            render_settings["MarkIn"]          = in_pt
            render_settings["MarkOut"]         = out_pt
        else:
            render_settings["SelectAllFrames"] = True

        project.SetRenderSettings(render_settings)
        job_id = project.AddRenderJob()
        project.StartRendering(job_id)

        q.put("  Rendert …")
        while True:
            status = project.GetRenderJobStatus(job_id)
            job_status = status.get("JobStatus", "")
            if job_status == "Complete":
                break
            if job_status in ("Failed", "Cancelled"):
                raise RuntimeError(f"Resolve Render fehlgeschlagen: {status}")
            completion = status.get("CompletionPercentage", 0)
            q.put(f"  … {completion:.0f}%")
            time.sleep(1.0)

        # 2. Find rendered file
        rendered = next(Path(tmp_dir).glob("*.wav"), None)
        if not rendered:
            raise RuntimeError("Keine WAV-Datei im Render-Output gefunden.")
        q.put(f"  ✓ Render abgeschlossen: {rendered.name}")

        # 3. MaxxVolume via ffmpeg
        out_path = Path(tmp_dir) / f"{tl_name}_maxxvol.wav"
        q.put("  Verarbeite mit MaxxVolume …")
        if not _run_ffmpeg_maxxvolume(str(rendered), str(out_path), filterchain, q):
            return

        rendered.unlink()   # remove intermediate render file

        # 4. Import result into Media Pool
        if imp_folder:
            mp.SetCurrentFolder(imp_folder)
        imported = mp.ImportMedia([str(out_path)])
        mp_item = imported[0] if imported else None

        if mp_item:
            q.put(f"  ✓ In Resolve importiert: {out_path.name}")
        else:
            q.put(f"  ⚠ Import fehlgeschlagen — Datei liegt in: {out_path}")
            return

        # 5. Place on new audio track in timeline
        try:
            fps_str = timeline.GetSetting("timelineFrameRate")
            fps = float(fps_str) if fps_str else 25.0
        except Exception:
            fps = 25.0

        total_frames = _get_audio_frames(str(out_path), fps)
        record_frame = in_pt if has_inout else tl_start
        new_track_idx = timeline.GetTrackCount("audio") + 1

        q.put(f"  Füge auf Audio-Track {new_track_idx} ab Frame {record_frame} ein …")
        result = mp.AppendToTimeline([{
            "mediaPoolItem": mp_item,
            "startFrame":    0,
            "endFrame":      total_frames,
            "trackIndex":    new_track_idx,
            "recordFrame":   record_frame,
            "mediaType":     2,   # audio
        }])

        if result:
            q.put(f"  ✓ Auf Audio-Track {new_track_idx} platziert\n")
        else:
            q.put("  ⚠ Automatisches Platzieren nicht möglich — Clip ist im Bin, bitte manuell auf neuen Track ziehen.\n")

    except Exception as e:
        q.put(f"  Fehler: {e}\n")
    finally:
        # Clean up temp dir (rendered source already unlinked; keep output for safety)
        try:
            for f in Path(tmp_dir).glob("*_src*.wav"):
                f.unlink()
        except Exception:
            pass


def _process_files(files: list, filterchain: str, q: queue.Queue,
                   resolve_import: tuple = None):
    """Process bin/folder clips through MaxxVolume."""
    for name, src_path in files:
        q.put(f"► {name}")
        src = Path(src_path)

        # Extract audio from video if needed
        current = str(src)
        _video_tmp = None
        if src.suffix.lower() in VIDEO_EXTENSIONS:
            q.put("  Audio-Extraktion via ffmpeg …")
            _video_tmp = tempfile.mktemp(suffix=".wav")
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-map", "0:a:0",
                 "-acodec", "pcm_s24le", _video_tmp],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            if r.returncode != 0:
                q.put(f"  Fehler (ffmpeg extract): {r.stderr[-200:]}")
                continue
            current = _video_tmp

        out_path = src.parent / f"{src.stem}_maxxvol.wav"
        q.put("  Verarbeite …")
        ok = _run_ffmpeg_maxxvolume(current, str(out_path), filterchain, q)

        if _video_tmp and Path(_video_tmp).exists():
            Path(_video_tmp).unlink()

        if not ok:
            continue

        q.put(f"  ✓ gespeichert: {out_path.name}")

        if resolve_import and out_path.exists():
            try:
                _mp, _folder = resolve_import
                _mp.SetCurrentFolder(_folder)
                _mp.ImportMedia([str(out_path)])
                q.put("  ✓ in Resolve importiert")
            except Exception as _e:
                q.put(f"  ⚠ Resolve-Import fehlgeschlagen: {_e}")
        q.put("")


def _run_all(source_mode, selected_path_files, ctx, filterchain, q):
    try:
        q.put("Starte MaxxVolume-Verarbeitung …\n")
        if source_mode == "Aktive Timeline" and ctx.get("tl_mode"):
            _process_timeline(ctx, filterchain, q)
        else:
            imp = (ctx["mp"], ctx.get("import_folder")) if ctx.get("import_folder") else None
            _process_files(selected_path_files, filterchain, q, resolve_import=imp)
        q.put("__DONE__0")
    except Exception as e:
        q.put(f"Fehler: {e}")
        q.put("__DONE__1")

# ── Can we start? ─────────────────────────────────────────────────────────────

_tl_ready    = source_mode == "Aktive Timeline" and resolve_ctx.get("tl_mode")
_files_ready = source_mode != "Aktive Timeline" and bool(selected_path_files)
can_start    = (_tl_ready or _files_ready) and not st.session_state.mv_running

# ── Run ───────────────────────────────────────────────────────────────────────

st.divider()

if st.button("▶ MaxxVolume starten", type="primary", disabled=not can_start,
             use_container_width=True, key="mv_start"):
    filterchain = _build_filterchain(gate_threshold, leveler_target, output_ceiling,
                                     low_level_gain, high_level_gain)
    st.session_state.mv_running = True
    st.session_state.mv_log = []
    q = queue.Queue()
    st.session_state.mv_queue = q

    # snapshot ctx to avoid Streamlit re-render issues in thread
    _ctx_snap = dict(resolve_ctx)
    _mode_snap = source_mode
    _files_snap = list(selected_path_files)

    threading.Thread(
        target=_run_all,
        args=(_mode_snap, _files_snap, _ctx_snap, filterchain, q),
        daemon=True,
    ).start()
    st.rerun()

# ── Log ───────────────────────────────────────────────────────────────────────

if st.session_state.mv_running or st.session_state.mv_log:
    st.divider()
    st.subheader("Log")

    if st.session_state.mv_running and st.session_state.mv_queue:
        q = st.session_state.mv_queue
        while not q.empty():
            msg = q.get_nowait()
            if msg.startswith("__DONE__"):
                st.session_state.mv_running = False
                break
            st.session_state.mv_log.append(msg)

    st.code("\n".join(st.session_state.mv_log), language=None)

    if st.session_state.mv_running:
        time.sleep(2)
        st.rerun()
