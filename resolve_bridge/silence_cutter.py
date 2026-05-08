"""
Composite silence detection and timeline rebuild for multi-track audio.
"""

import subprocess
import tempfile
import numpy as np
import soundfile as sf
from pathlib import Path

_VIDEO_EXT = {".mp4", ".mov", ".mxf", ".r3d", ".braw", ".avi", ".mkv", ".mts", ".m2ts"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _probe_source_fps(path: str) -> float:
    """Returns the video stream's frame rate from ffprobe, or 0.0 if unavailable."""
    import json as _json
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True,
        )
        for stream in _json.loads(r.stdout).get("streams", []):
            if stream.get("codec_type") == "video":
                rfr = stream.get("r_frame_rate", "")
                if "/" in rfr:
                    num, den = rfr.split("/")
                    if int(den) > 0:
                        return int(num) / int(den)
    except Exception:
        pass
    return 0.0


def _tc_start_frames(path: str, fps: float) -> int:
    """Returns embedded start timecode as frame count, or 0 if not found."""
    import json as _json, re
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True,
        )
        for stream in _json.loads(r.stdout).get("streams", []):
            tc = stream.get("tags", {}).get("timecode", "")
            if not tc:
                continue
            # Support both non-drop "HH:MM:SS:FF" and drop-frame "HH:MM:SS;FF"
            m = re.match(r"(\d+):(\d+):(\d+)[:;](\d+)", tc)
            if m:
                h, mn, s, f = (int(x) for x in m.groups())
                return (h * 3600 + mn * 60 + s) * int(round(fps)) + f
    except Exception:
        pass
    return 0


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyze_composite_silence(
    audio_tracks: dict,
    selected_tracks: list,
    fps: float,
    tl_start: int,
    tl_end: int,
    threshold_db: float,
    min_silence_s: float,
    pre_pad_s: float,
    post_pad_s: float,
    gaps_are_silence: bool,
    progress_cb=None,
) -> list:
    """
    Composite silence detection across multiple audio tracks.

    A frame is considered silence only when ALL selected tracks are simultaneously
    below threshold_db at that timeline position.

    Returns list of (abs_start_frame, duration_frames) after applying padding.
    """
    tl_length = tl_end - tl_start
    threshold_linear = 10 ** (threshold_db / 20.0)

    # True = silent at this timeline frame (start all-silent, mark active frames)
    silence_mask = np.ones(tl_length, dtype=bool)

    for track_idx in selected_tracks:
        clips = audio_tracks.get(track_idx, [])

        if not gaps_are_silence:
            # Mark frames not covered by any clip on this track as NOT silence
            # so uncovered gaps are excluded from cutting
            covered = np.zeros(tl_length, dtype=bool)
            for clip in clips:
                s = max(0, clip.timeline_start - tl_start)
                e = min(tl_length, clip.timeline_end - tl_start)
                covered[s:e] = True
            silence_mask[~covered] = False

        for clip in clips:
            if not clip.file_path:
                continue
            path = Path(clip.file_path)
            if not path.exists():
                if progress_cb:
                    progress_cb(f"  ⚠ Nicht gefunden: {path.name}")
                continue

            if progress_cb:
                progress_cb(f"  Spur {track_idx}: {path.name}")

            tmp_wav = None
            try:
                read_path    = path
                start_sample = 0
                end_sample   = None  # None → read to EOF

                if path.suffix.lower() in _VIDEO_EXT:
                    # Extract only the clip's portion with -ss/-t so that
                    # start_sample=0 always maps to the clip's in-point.
                    #
                    # Use source fps from ffprobe for the seek calculation.
                    # Deriving source fps from tl_duration/source_duration
                    # introduces a ~5 frame error because Resolve's
                    # GetEnd()-GetStart() and GetSourceEndFrame()-GetSourceStartFrame()
                    # can differ by 1 frame (exclusive/inclusive boundary).
                    #
                    # GetSourceStartFrame() is 0-based (does NOT include
                    # the file's embedded start timecode).
                    clip_tl_dur_s    = (clip.timeline_end - clip.timeline_start) / fps
                    source_fps       = _probe_source_fps(str(path)) or fps
                    clip_start_s     = clip.source_start_frame / source_fps
                    clip_dur_s       = clip_tl_dur_s
                    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    tmp.close()
                    tmp_wav = Path(tmp.name)
                    subprocess.run(
                        ["ffmpeg", "-y",
                         "-i", str(path),
                         "-ss", f"{clip_start_s:.6f}",
                         "-t",  f"{clip_dur_s:.6f}",
                         "-map", "0:a:0", "-acodec", "pcm_s16le",
                         "-ar", "16000", "-ac", "1", str(tmp_wav)],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    read_path = tmp_wav
                else:
                    # Native audio file: use source_start/end frames directly.
                    # (Computed after sf.info() below once spf is known.)
                    pass

                info       = sf.info(str(read_path))
                sr         = info.samplerate
                total_samp = info.frames
                spf        = sr / fps  # samples per frame
                block_size = max(1, int(spf))
                tl_offset  = clip.timeline_start - tl_start

                if path.suffix.lower() not in _VIDEO_EXT:
                    # Audio file: position by source frames
                    start_sample = int(clip.source_start_frame * spf)
                    end_sample   = int(clip.source_end_frame   * spf)

                    # TC-offset guard: if source frames exceed file length,
                    # try to subtract the embedded start timecode.
                    if start_sample >= total_samp and total_samp > 0:
                        tc_off = _tc_start_frames(str(path), fps)
                        if tc_off > 0:
                            start_sample = max(0, int((clip.source_start_frame - tc_off) * spf))
                            end_sample   = max(start_sample,
                                               int((clip.source_end_frame - tc_off) * spf))
                            if progress_cb:
                                progress_cb(
                                    f"  ℹ TC-Offset {tc_off} Fr. erkannt ({path.name})"
                                )
                        else:
                            if progress_cb:
                                progress_cb(
                                    f"  ⚠ {path.name}: source_start={clip.source_start_frame} "
                                    f"liegt außerhalb der Dateilänge "
                                    f"({total_samp/sr:.1f}s) — Clip wird übersprungen"
                                )
                            continue

                    # Clamp end_sample to file length
                    if end_sample is not None:
                        end_sample = min(end_sample, total_samp)

                frame_idx   = 0
                active_cnt  = 0
                for block in sf.blocks(str(read_path), blocksize=block_size,
                                       start=start_sample, stop=end_sample,
                                       dtype="float32"):
                    tl_frame = tl_offset + frame_idx
                    if 0 <= tl_frame < tl_length:
                        mono = block.mean(axis=1) if block.ndim > 1 else block
                        rms  = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
                        if rms > threshold_linear:
                            silence_mask[tl_frame] = False
                            active_cnt += 1
                    frame_idx += 1

                if progress_cb and frame_idx == 0:
                    progress_cb(
                        f"  ⚠ {path.name}: keine Frames gelesen "
                        f"(src {clip.source_start_frame}–{clip.source_end_frame}, "
                        f"tl_off {tl_offset}) — Dateilänge {total_samp/sr:.1f}s"
                    )

            except Exception as e:
                if progress_cb:
                    progress_cb(f"  ⚠ Fehler Spur {track_idx}: {e}")
            finally:
                if tmp_wav and tmp_wav.exists():
                    tmp_wav.unlink(missing_ok=True)

    # Find contiguous silent regions
    padded = np.pad(silence_mask.astype(np.int8), (1, 1), constant_values=0)
    diff   = np.diff(padded)
    starts = np.where(diff == 1)[0]
    ends   = np.where(diff == -1)[0]

    min_frames  = max(1, int(min_silence_s * fps))
    pre_frames  = int(pre_pad_s  * fps)
    post_frames = int(post_pad_s * fps)

    results = []
    for s, e in zip(starts, ends):
        if (e - s) < min_frames:
            continue
        cut_start = s + pre_frames
        cut_end   = e - post_frames
        if cut_end > cut_start:
            results.append((int(cut_start + tl_start), int(cut_end - cut_start)))

    return results


# ── Timeline rebuild (ripple cut) ─────────────────────────────────────────────

def _compute_keep_segments(tl_start: int, tl_end: int, silences: list) -> list:
    """
    Given a clip range [tl_start, tl_end] and a list of (start, dur) silences,
    returns the list of (keep_start, keep_end) timeline ranges to preserve.
    """
    keep = []
    pos = tl_start
    for s_start, s_dur in sorted(silences):
        s_end = s_start + s_dur
        if s_end <= tl_start or s_start >= tl_end:
            continue
        s_start = max(s_start, tl_start)
        s_end   = min(s_end,   tl_end)
        if pos < s_start:
            keep.append((pos, s_start))
        pos = s_end
    if pos < tl_end:
        keep.append((pos, tl_end))
    return keep


def _find_media_item(mp, file_path: str):
    """Recursively search Media Pool for a clip by file path."""
    def _search(folder):
        for item in (folder.GetClipList() or []):
            if item.GetClipProperty("File Path") == file_path:
                return item
        for sf in (folder.GetSubFolderList() or []):
            found = _search(sf)
            if found:
                return found
        return None
    return _search(mp.GetRootFolder())


def rebuild_timeline_without_silences(
    resolve,
    source_tl_name: str,
    new_tl_name: str,
    selected_tracks: list,
    silence_segments: list,
    progress_cb=None,
) -> str:
    """
    Creates a new timeline that is a copy of source_tl_name with silence
    segments removed from selected_tracks. All other tracks are copied as-is.

    Returns the name of the created timeline.
    """
    pm      = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    mp      = project.GetMediaPool()

    # Find source timeline
    source_tl = None
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t.GetName() == source_tl_name:
            source_tl = t
            break
    if source_tl is None:
        raise RuntimeError(f"Timeline '{source_tl_name}' nicht gefunden.")

    fps      = float(source_tl.GetSetting("timelineFrameRate") or 25.0)
    tl_start = source_tl.GetStartFrame()
    tl_end   = source_tl.GetEndFrame()

    # ── Collect all clips from all tracks ─────────────────────────────────────
    v_count = source_tl.GetTrackCount("video")
    a_count = source_tl.GetTrackCount("audio")

    # Build clip_dicts for AppendToTimeline
    # Structure: list of {"mediaPoolItem", "startFrame", "endFrame",
    #                      "trackIndex", "mediaType", "recordFrame"}
    # We'll collect one "column" of clips per output frame position.
    # Instead: build per-track segment lists, then interleave into AppendToTimeline calls.

    # For each output track we build an ordered list of clip-dicts
    # video tracks first (unchanged), then audio tracks (silence removed on selected)

    # ── Create new empty timeline ─────────────────────────────────────────────
    if progress_cb:
        progress_cb(f"Erstelle neue Timeline: {new_tl_name}")

    new_tl = mp.CreateEmptyTimeline(new_tl_name)
    if new_tl is None:
        raise RuntimeError(f"Konnte Timeline '{new_tl_name}' nicht erstellen.")

    # Set matching FPS
    new_tl.SetSetting("timelineFrameRate", str(int(fps)))

    # ── Remove default tracks, add correct number of audio tracks ─────────────
    # Default timeline has 1 video + 1 stereo audio track.
    # DeleteTrack may not exist in older Resolve versions (returns None instead
    # of raising AttributeError), so we guard with callable().
    _delete_track = getattr(new_tl, "DeleteTrack", None)
    if callable(_delete_track):
        try:
            _delete_track("audio", 1)
            tracks_to_add = a_count
        except Exception:
            tracks_to_add = max(0, a_count - 1)
    else:
        tracks_to_add = max(0, a_count - 1)
    for _ in range(tracks_to_add):
        new_tl.AddTrack("audio", "mono")

    # ── Precompute global keep segments with record positions ─────────────────
    # Each entry: (tl_keep_start, tl_keep_end, record_start_in_new_tl)
    # All tracks use the same record positions so they stay in sync.
    global_keeps = []
    _pos = tl_start
    _rec = 0
    for _ss, _sd in sorted(silence_segments):
        _se = _ss + _sd
        if _se <= tl_start or _ss >= tl_end:
            continue
        _ss = max(_ss, tl_start)
        _se = min(_se, tl_end)
        if _pos < _ss:
            global_keeps.append((_pos, _ss, _rec))
            _rec += _ss - _pos
        _pos = _se
    if _pos < tl_end:
        global_keeps.append((_pos, tl_end, _rec))

    def _append_segment(mi, src_start: int, src_end: int,
                        track_idx: int, media_type: int, record_frame: int):
        if src_end <= src_start:
            return
        mp.AppendToTimeline([{
            "mediaPoolItem": mi,
            "startFrame":    src_start,
            "endFrame":      src_end,
            "trackIndex":    track_idx,
            "mediaType":     media_type,
            "recordFrame":   record_frame,
        }])

    def _place_clip(item, track_idx: int, media_type: int, label: str):
        """Place a single source clip cut to global_keeps."""
        mi_obj = item.GetMediaPoolItem()
        if mi_obj is None:
            return
        item_tl_start = item.GetStart()
        item_tl_end   = item.GetEnd()
        src_off       = item.GetSourceStartFrame()
        n = 0
        for tl_ks, tl_ke, rec_start in global_keeps:
            clip_ks = max(item_tl_start, tl_ks)
            clip_ke = min(item_tl_end,   tl_ke)
            if clip_ke <= clip_ks:
                continue
            src_s = src_off + (clip_ks - item_tl_start)
            src_e = src_off + (clip_ke - item_tl_start)
            rec   = rec_start + (clip_ks - tl_ks)
            _append_segment(mi_obj, src_s, src_e, track_idx, media_type, rec)
            n += 1
        if progress_cb:
            progress_cb(f"  {label} → {n} Segmente")

    # ── Video tracks ──────────────────────────────────────────────────────────
    for _ in range(v_count - 1):
        new_tl.AddTrack("video")

    for v_idx in range(1, v_count + 1):
        for item in sorted(source_tl.GetItemListInTrack("video", v_idx) or [],
                           key=lambda x: x.GetStart()):
            _place_clip(item, v_idx, 1, f"Video V{v_idx}: {item.GetName()}")

    # ── Audio tracks ──────────────────────────────────────────────────────────
    for a_idx in range(1, a_count + 1):
        for item in sorted(source_tl.GetItemListInTrack("audio", a_idx) or [],
                           key=lambda x: x.GetStart()):
            _place_clip(item, a_idx, 2, f"Audio A{a_idx}: {item.GetName()}")

    project.SetCurrentTimeline(new_tl)
    return new_tl_name
