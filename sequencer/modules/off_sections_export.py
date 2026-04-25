"""Off-Sections-Export-Modul — Berechnet Off-Kamera-Bereiche fuer Nodding-Optimierung."""

from __future__ import annotations

from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module


class OffSectionsExportModule(Module):
    name = "off_sections_export"
    description = "Off-Kamera-Sektionen berechnen (fuer Nodding-Analyse)"
    category = "analysis"

    inputs = ["diarization.segments", "frame_mapping"]
    outputs = ["off_sections"]

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        diarization = ctx.get("diarization.segments")
        frame_mapping = ctx.get("frame_mapping")
        fps = frame_mapping.fps
        tzvf = frame_mapping.timeline_zero_video_frames

        segments = diarization.segments
        cam_names = list(tzvf.keys())

        # Pro Kamera: in welchen Frames ist sie Off-Kamera?
        off_sections = {}

        for cam_name in cam_names:
            off_frames = []
            other_names = [n for n in cam_names if n != cam_name]
            cam_tzvf = tzvf[cam_name]

            for seg in segments:
                # Wenn ein anderer Sprecher aktiv ist, ist diese Kamera off
                if seg['speaker'] in other_names:
                    wav_edl_frame = params.get("wav_edl_frame", 0)
                    edl_s = round(seg['start_s'] * fps) + wav_edl_frame
                    edl_e = round(seg['end_s'] * fps) + wav_edl_frame
                    v_s = cam_tzvf + edl_s
                    v_e = cam_tzvf + edl_e
                    if v_s >= 0 and v_e > v_s:
                        off_frames.append([int(v_s), int(v_e)])

            off_sections[cam_name] = off_frames
            total_off_s = sum(e - s for s, e in off_frames) / fps if off_frames else 0
            print(f"  {cam_name}: {len(off_frames)} Off-Sektionen ({total_off_s / 60:.1f} min)")

        ctx.set("off_sections", off_sections)
