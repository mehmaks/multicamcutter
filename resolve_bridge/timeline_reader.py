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
    timeline_end: int         # frame where clip ends in the timeline
    source_start_frame: int   # frame where clip starts in the source file
    source_end_frame: int     # frame where clip ends in the source file
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
            timeline_end=item.GetEnd(),
            source_start_frame=src_start,
            source_end_frame=item.GetSourceEndFrame(),
            sync_offset_frames=tl_start - src_start,  # adjusted per reference below
            start_tc=start_tc,
        ))
    return clips


def read_timeline(timeline_name: str = None) -> TimelineData:
    """
    Reads a Resolve timeline and returns a TimelineData object.
    If timeline_name is given, that timeline is used (and set as current).
    Otherwise, the currently active timeline is used.
    Sync offsets are relative to the earliest clip across all tracks.
    """
    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        raise RuntimeError("Kein Projekt in DaVinci Resolve geöffnet.")

    if timeline_name:
        timeline = None
        for i in range(1, project.GetTimelineCount() + 1):
            t = project.GetTimelineByIndex(i)
            if t.GetName() == timeline_name:
                timeline = t
                project.SetCurrentTimeline(t)
                break
        if timeline is None:
            raise RuntimeError(f"Timeline '{timeline_name}' nicht gefunden.")
    else:
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


def read_offsets_from_timeline(cam_paths: list[str], mic_paths: list[str]) -> dict[str, int]:
    """
    Liest Sync-Offsets aus der aktuell aktiven Resolve-Timeline.

    Mappt die gegebenen Bin-Files (cam_paths, mic_paths) per File-Path auf
    Clips der Timeline und liefert ein Offsets-Dict wie sync_sources():
      {'CAM1': 0, 'CAM2': int, 'MIC1': int, 'MIC2': int, ...}
    Alle Werte in Frames, relativ zu CAM1.

    Erwartete Timeline-Struktur: für jedes Bin-File mindestens ein Clip an
    der vom User platzierten Sync-Position. Bei mehreren Clips desselben
    Files wird der erste verwendet. Pfade werden zum Vergleich NFC-normalisiert
    und absolut aufgelöst, um macOS-HFS/APFS-Encoding-Unterschiede zu glätten.
    """
    import unicodedata

    def _norm(p: str) -> str:
        return unicodedata.normalize('NFC', os.path.realpath(p)) if p else ''

    data = read_timeline()

    # Build path → (timeline_start - source_start) lookup from all clips
    path_to_abs_offset: dict[str, int] = {}
    for clips in list(data.video_tracks.values()) + list(data.audio_tracks.values()):
        for clip in clips:
            key = _norm(clip.file_path)
            if key and key not in path_to_abs_offset:
                path_to_abs_offset[key] = clip.timeline_start - clip.source_start_frame

    def _lookup(label: str, path: str) -> int:
        key = _norm(path)
        if key not in path_to_abs_offset:
            raise RuntimeError(
                f"{label}: Datei nicht in der aktuellen Resolve-Timeline gefunden: {path}. "
                f"Bitte den Clip in der Sync-Timeline platzieren."
            )
        return path_to_abs_offset[key]

    cam1_abs = _lookup('CAM1', cam_paths[0])

    offsets: dict[str, int] = {'CAM1': 0}
    for i, cp in enumerate(cam_paths[1:], start=2):
        offsets[f'CAM{i}'] = _lookup(f'CAM{i}', cp) - cam1_abs
    for i, mp in enumerate(mic_paths, start=1):
        offsets[f'MIC{i}'] = _lookup(f'MIC{i}', mp) - cam1_abs

    return offsets
