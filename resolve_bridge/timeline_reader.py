"""
Reads the current Resolve timeline and extracts all data needed
for the multicam_cutter pipeline:
  - File paths per video/audio track
  - Sync offsets derived from timeline positions
  - Warnings for problematic track layouts
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from .connection import get_resolve


@dataclass
class TrackClip:
    file_path: str
    clip_name: str
    timeline_start: int       # frame where clip starts in the timeline
    source_start_frame: int   # frame where clip starts in the source file
    sync_offset_frames: int   # timeline_start - source_start_frame (relative to reference)
    start_tc: str             # embedded start timecode from source


@dataclass
class TimelineData:
    timeline_name: str
    fps: float
    timeline_start: int
    timeline_end: int
    video_tracks: dict[int, list[TrackClip]]   # track_index → clips
    audio_tracks: dict[int, list[TrackClip]]   # track_index → clips
    audio_track_names: dict[int, str]          # track_index → track name
    warnings: list[str] = field(default_factory=list)


def _is_video_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".r3d"}


def _is_audio_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".wav", ".aif", ".aiff", ".mp3", ".flac"}


def _read_clips(timeline, track_type: str, track_index: int) -> list[TrackClip]:
    items = timeline.GetItemListInTrack(track_type, track_index)
    if not items:
        return []

    clips = []
    for item in items:
        mi = item.GetMediaPoolItem()
        if mi is None:
            continue
        file_path = mi.GetClipProperty("File Path") or ""
        start_tc  = mi.GetClipProperty("Start TC") or ""
        tl_start  = item.GetStart()
        src_start = item.GetSourceStartFrame()

        clips.append(TrackClip(
            file_path=file_path,
            clip_name=item.GetName(),
            timeline_start=tl_start,
            source_start_frame=src_start,
            sync_offset_frames=tl_start - src_start,  # adjusted per reference below
            start_tc=start_tc,
        ))
    return clips


def read_timeline() -> TimelineData:
    """
    Reads the current Resolve timeline and returns a TimelineData object.
    Sync offsets are relative to the earliest clip across all tracks.
    """
    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        raise RuntimeError("Kein Projekt in DaVinci Resolve geöffnet.")

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("Keine aktive Timeline in DaVinci Resolve.")

    fps = float(timeline.GetSetting("timelineFrameRate") or 25.0)

    video_tracks = {}
    audio_tracks = {}
    audio_track_names = {}
    warnings = []

    # Read video tracks
    v_count = timeline.GetTrackCount("video")
    for i in range(1, v_count + 1):
        clips = _read_clips(timeline, "video", i)
        if clips:
            video_tracks[i] = clips

    # Read audio tracks
    a_count = timeline.GetTrackCount("audio")
    for i in range(1, a_count + 1):
        name = timeline.GetTrackName("audio", i)
        audio_track_names[i] = name
        clips = _read_clips(timeline, "audio", i)
        if clips:
            audio_tracks[i] = clips

    # Find the global reference offset (earliest timeline_start - source_start across all clips)
    all_offsets = []
    for clips in list(video_tracks.values()) + list(audio_tracks.values()):
        for clip in clips:
            all_offsets.append(clip.timeline_start - clip.source_start_frame)
    ref_offset = min(all_offsets) if all_offsets else 0

    # Adjust sync_offset_frames relative to the reference
    for clips in list(video_tracks.values()) + list(audio_tracks.values()):
        for clip in clips:
            clip.sync_offset_frames = (clip.timeline_start - clip.source_start_frame) - ref_offset

    # Warnings: audio tracks with mixed clips (WAV + video file)
    for idx, clips in audio_tracks.items():
        if len(clips) > 1:
            track_name = audio_track_names.get(idx, f"Audio {idx}")
            video_clips_on_track = [c for c in clips if _is_video_file(c.file_path)]
            if video_clips_on_track:
                names = ", ".join(c.clip_name for c in video_clips_on_track)
                warnings.append(
                    f"Audiospur {idx} ('{track_name}') enthält {len(clips)} Clips — "
                    f"darunter Kamera-Audiodaten: {names}. "
                    f"Bitte diese Überbleibsel entfernen."
                )
            else:
                warnings.append(
                    f"Audiospur {idx} ('{track_name}') enthält {len(clips)} Clips. "
                    f"Erwartet wird genau 1 WAV-Clip pro Spur."
                )

    return TimelineData(
        timeline_name=timeline.GetName(),
        fps=fps,
        timeline_start=timeline.GetStartFrame(),
        timeline_end=timeline.GetEndFrame(),
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
        audio_track_names=audio_track_names,
        warnings=warnings,
    )


def get_primary_wav_clip(clips: list[TrackClip]) -> Optional[TrackClip]:
    """Returns the first WAV clip from a list (ignores video file clips)."""
    for clip in clips:
        if _is_audio_file(clip.file_path):
            return clip
    return None
