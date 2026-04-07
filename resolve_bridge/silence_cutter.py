"""
Composite silence detection and timeline rebuild for multi-track audio.
"""

import numpy as np
import soundfile as sf
from pathlib import Path


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

            try:
                info = sf.info(str(path))
                sr = info.samplerate
                spf = sr / fps  # samples per frame

                start_sample = int(clip.source_start_frame * spf)
                end_sample   = int(clip.source_end_frame   * spf)
                block_size   = max(1, int(spf))
                tl_offset    = clip.timeline_start - tl_start

                frame_idx = 0
                for block in sf.blocks(str(path), blocksize=block_size,
                                        start=start_sample, stop=end_sample,
                                        dtype="float32"):
                    tl_frame = tl_offset + frame_idx
                    if 0 <= tl_frame < tl_length:
                        mono = block.mean(axis=1) if block.ndim > 1 else block
                        rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
                        if rms > threshold_linear:
                            silence_mask[tl_frame] = False
                    frame_idx += 1

            except Exception as e:
                if progress_cb:
                    progress_cb(f"  ⚠ Fehler Spur {track_idx}: {e}")

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
            results.append((cut_start + tl_start, cut_end - cut_start))

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
    audio_transition_frames: int,
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
    # Default timeline has 1 video + 1 stereo audio track
    new_tl.DeleteTrack("audio", 1)
    for _ in range(a_count):
        new_tl.AddTrack("audio", "mono")

    # ── Helper: append a clip segment to new timeline ─────────────────────────
    def _append_segment(mi, src_start: int, src_end: int,
                        track_idx: int, media_type: int,
                        fade_in: int, fade_out: int):
        if src_end <= src_start:
            return
        clip_info = {
            "mediaPoolItem": mi,
            "startFrame":    src_start,
            "endFrame":      src_end,
            "trackIndex":    track_idx,
            "mediaType":     media_type,
        }
        items = new_tl.AppendToTimeline([clip_info])
        if items and audio_transition_frames > 0 and media_type == 2:
            item = items[0]
            try:
                if fade_in:
                    item.SetProperty("audioFadeInLength", fade_in)
                if fade_out:
                    item.SetProperty("audioFadeOutLength", fade_out)
            except Exception:
                pass

    # ── Video tracks — copy unchanged ─────────────────────────────────────────
    # We need at least 1 video track; add them if needed
    for _ in range(v_count):
        new_tl.AddTrack("video")

    for v_idx in range(1, v_count + 1):
        items = source_tl.GetItemListInTrack("video", v_idx) or []
        for item in items:
            mi_obj = item.GetMediaPoolItem()
            if mi_obj is None:
                continue
            _append_segment(
                mi_obj,
                item.GetSourceStartFrame(),
                item.GetSourceEndFrame(),
                v_idx, 1,
                0, 0,
            )
            if progress_cb:
                progress_cb(f"  Video V{v_idx}: {item.GetName()}")

    # ── Audio tracks ──────────────────────────────────────────────────────────
    for a_idx in range(1, a_count + 1):
        items = source_tl.GetItemListInTrack("audio", a_idx) or []
        for item in sorted(items, key=lambda x: x.GetStart()):
            mi_obj = item.GetMediaPoolItem()
            if mi_obj is None:
                continue

            item_tl_start = item.GetStart()
            item_tl_end   = item.GetEnd()
            src_start_off = item.GetSourceStartFrame()

            if a_idx in selected_tracks:
                # Cut silence out of this track
                keep_segs = _compute_keep_segments(item_tl_start, item_tl_end, silence_segments)
                n = len(keep_segs)
                for seg_i, (ks, ke) in enumerate(keep_segs):
                    # Convert timeline keep range to source frames
                    src_s = src_start_off + (ks - item_tl_start)
                    src_e = src_start_off + (ke - item_tl_start)
                    fade_in  = audio_transition_frames if seg_i > 0    else 0
                    fade_out = audio_transition_frames if seg_i < n - 1 else 0
                    _append_segment(mi_obj, src_s, src_e, a_idx, 2, fade_in, fade_out)
                if progress_cb:
                    progress_cb(f"  Audio A{a_idx}: {item.GetName()} → {n} Segmente")
            else:
                # Copy track unchanged
                _append_segment(
                    mi_obj,
                    src_start_off,
                    item.GetSourceEndFrame(),
                    a_idx, 2, 0, 0,
                )
                if progress_cb:
                    progress_cb(f"  Audio A{a_idx}: {item.GetName()} (unverändert)")

    project.SetCurrentTimeline(new_tl)
    return new_tl_name
