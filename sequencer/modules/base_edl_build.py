"""Base-EDL-Build-Modul — Wandelt Diarization-Segmente in EDL-Events um."""

from __future__ import annotations

from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.frame_utils import get_reference_frame
from sequencer.module import Module
from sequencer.types import EDLEvent, FrameMapping


class BaseEDLBuildModule(Module):
    name = "base_edl_build"
    description = "Diarization-Segmente in Schnitt-Events umwandeln"
    category = "editing"

    inputs = ["diarization.segments", "sources.cameras", "sync.offsets"]
    outputs = ["events.base", "frame_mapping"]
    optional_inputs = ["simultaneous_speech"]

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        diarization = ctx.get("diarization.segments")
        cameras = ctx.get("sources.cameras")
        sync = ctx.get("sync.offsets")
        fps = ctx.fps

        segments = diarization.segments
        cam_names = [c.name for c in cameras]

        # Referenz-Frames pro Kamera
        reference_frames = {}
        for cam in cameras:
            ref, tc = get_reference_frame(cam.path, fps)
            reference_frames[cam.name] = ref
            if tc:
                print(f"  {cam.name}: TC={tc} → Ref={ref}")

        # EDL-Frames und Timeline-Zero berechnen
        offsets = sync.offsets
        cam_edl_frames = {}
        for cam in cameras:
            # Offset relativ zur Referenz-Kamera
            cam_edl_frames[cam.name] = offsets.get(cam.name, 0)

        # Shift damit kein negativer Record-Frame entsteht
        min_offset = min(cam_edl_frames.values())
        cam_shift = max(0, -min_offset)

        timeline_zero_video_frames = {}
        for cam in cameras:
            edl_frame = cam_edl_frames[cam.name] + cam_shift
            timeline_zero_video_frames[cam.name] = 0 - edl_frame

        # wav_edl_frame: wo im EDL-Koordinatensystem startet das Audio
        mic_names = list(offsets.keys())
        wav_offset = 0
        for name in mic_names:
            if name.startswith("MIC"):
                wav_offset = offsets[name]
                break
        wav_edl_frame = wav_offset + cam_shift

        # Segmente in Events umwandeln
        events: List[EDLEvent] = []
        skipped = 0

        for seg in segments:
            edl_start = round(seg['start_s'] * fps) + wav_edl_frame
            edl_end = round(seg['end_s'] * fps) + wav_edl_frame

            speaker = seg['speaker']
            if speaker not in cam_names:
                skipped += 1
                continue

            # Skip/Trim bei negativen Frames
            if edl_end <= 0:
                skipped += 1
                continue
            if edl_start < 0:
                edl_start = 0

            ref = reference_frames[speaker]
            tz = timeline_zero_video_frames[speaker]
            video_start = tz + edl_start
            video_end = tz + edl_end

            if video_start < 0:
                skipped += 1
                continue
            if edl_end <= edl_start:
                continue

            events.append(EDLEvent(
                clip_name=speaker,
                source_in_frame=ref + video_start,
                source_out_frame=ref + video_end,
                record_in_frame=edl_start,
                record_out_frame=edl_end,
                fps=fps,
                reason="speaker",
            ))

        if skipped:
            print(f"  {skipped} Segmente uebersprungen (vor Kamera-Start)")

        print(f"  {len(events)} Base-Events erstellt")

        frame_mapping = FrameMapping(
            reference_frames=reference_frames,
            timeline_zero_video_frames=timeline_zero_video_frames,
            fps=fps,
        )

        ctx.set("events.base", events)
        ctx.set("frame_mapping", frame_mapping)
