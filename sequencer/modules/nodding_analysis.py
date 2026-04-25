"""Nodding-Analysis-Modul — Video-Reaktionserkennung per Subprocess."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.module import SubprocessModule
from sequencer.types import ReactionData

_SCRIPT = Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter" / "video_reaction_analyzer_v2.4.py"


class NoddingAnalysisModule(SubprocessModule):
    name = "nodding_analysis"
    description = "Video-Reaktionen erkennen (Nicken, Lachen, etc.)"
    category = "analysis"

    inputs = ["sources.cameras"]
    outputs = ["reactions.nodding"]
    optional_inputs = ["off_sections"]

    script_path = str(_SCRIPT)

    schema = {
        "expanders": [{
            "key": "nodding",
            "label": "Nodding-Analyse",
            "rows": [{
                "columns": 1,
                "params": [
                    {"name": "enabled", "widget": "toggle", "default": True,
                     "label": "Aktiviert", "column": 0},
                ],
            }],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        return not params.get("enabled", True)

    def _build_command(self, ctx: PipelineContext, params: Dict[str, Any],
                       work_dir: Path) -> List[str]:
        # Wird nicht direkt genutzt — run() ueberschrieben
        return []

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        """Fuehrt Nodding-Analyse pro Kamera als Subprocess aus."""
        import subprocess
        import sys

        cameras = ctx.get("sources.cameras")
        off_sections = ctx.get("off_sections") if ctx.has("off_sections") else {}
        work_dir = ctx.work_dir
        fps = ctx.fps

        results = {}
        total_cams = len(cameras)

        for i, cam in enumerate(cameras):
            json_out = work_dir / f"{Path(cam.path).stem}_reactions.json"
            cmd = [
                sys.executable, str(_SCRIPT),
                cam.path,
                "--output", str(json_out),
                "--fps", str(fps),
            ]

            # Off-Sections fuer Optimierung
            if cam.name in off_sections and off_sections[cam.name]:
                off_path = work_dir / f"{cam.name}_off_sections.json"
                off_path.write_text(json.dumps(off_sections[cam.name]))
                cmd += ["--off-sections", str(off_path)]

            # Config-Pfad
            config_path = params.get("config_path", "")
            if config_path:
                cmd += ["--config", config_path]

            # LUT
            lut_path = params.get("lut_path", "")
            if lut_path:
                cmd += ["--lut", lut_path]

            # Auto-Accuracy
            if params.get("auto_accuracy", False):
                cmd += ["--auto-accuracy"]

            ctx.report_progress(i / total_cams, f"Nodding-Analyse {cam.name}")

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  {cam.name}: Nodding-Analyse fehlgeschlagen")
                print(f"    {result.stderr[-500:]}")
                results[cam.name] = ReactionData(cam_name=cam.name, reactions=[], fps=fps)
                continue

            # Ergebnis laden
            if json_out.exists():
                data = json.loads(json_out.read_text())
                reactions = data.get("reactions", [])
                print(f"  {cam.name}: {len(reactions)} Reaktionen")
                results[cam.name] = ReactionData(
                    cam_name=cam.name, reactions=reactions, fps=fps,
                )
            else:
                results[cam.name] = ReactionData(cam_name=cam.name, reactions=[], fps=fps)

        ctx.set("reactions.nodding", results)
