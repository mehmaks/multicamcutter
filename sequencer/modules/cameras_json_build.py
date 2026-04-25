"""Cameras-JSON-Build-Modul — Aggregiert Kamera-Metadaten fuer Cutaway-Insertion."""

from __future__ import annotations

from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module


class CamerasJsonBuildModule(Module):
    name = "cameras_json_build"
    description = "Kamera-Konfiguration fuer Cutaway-Engine zusammenbauen"
    category = "editing"

    inputs = ["sources.cameras", "sources.mics", "frame_mapping"]
    outputs = ["cameras_config"]
    optional_inputs = ["reactions.nodding", "reactions.speaking"]

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        cameras = ctx.get("sources.cameras")
        mics = ctx.get("sources.mics")
        frame_mapping = ctx.get("frame_mapping")

        nodding = ctx.get("reactions.nodding") if ctx.has("reactions.nodding") else {}
        speaking = ctx.get("reactions.speaking") if ctx.has("reactions.speaking") else {}

        configs = []
        for cam in cameras:
            name = cam.name
            cam_reactions = []

            # Nodding-Reaktionen
            if name in nodding:
                cam_reactions.extend(nodding[name].reactions)

            # Speaking-Reaktionen
            if name in speaking:
                cam_reactions.extend(speaking[name].reactions)

            configs.append({
                "name": name,
                "video": cam.path,
                "type": params.get(f"cam_type_{name}", "close"),
                "reference_frame": frame_mapping.reference_frames.get(name, 0),
                "timeline_zero_video": frame_mapping.timeline_zero_video_frames.get(name, 0),
                "reactions": cam_reactions,
                "mics": [m.path for m in mics],
            })

        print(f"  {len(configs)} Kameras konfiguriert")
        for c in configs:
            print(f"    {c['name']}: {c['type']}, {len(c['reactions'])} Reaktionen")

        ctx.set("cameras_config", configs)
