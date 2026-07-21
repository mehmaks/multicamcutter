"""Waveform-Sync-Modul — Synchronisiert alle Quellen per Audio-Kreuzkorrelation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import SyncOffsets

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from waveform_sync import sync_sources


class WaveformSyncModule(Module):
    name = "waveform_sync"
    description = "Quellen per Audio-Kreuzkorrelation synchronisieren"
    category = "analysis"

    inputs = ["sources.cameras", "sources.mics"]
    outputs = ["sync.offsets"]

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        cameras = ctx.get("sources.cameras")
        mics = ctx.get("sources.mics")
        fps = ctx.fps

        if len(cameras) < 2:
            # Einzelkamera: kein Sync noetig
            offsets = {cameras[0].name: 0}
            for m in mics:
                offsets[m.name] = 0
            ctx.set("sync.offsets", SyncOffsets(offsets=offsets, fps=fps))
            print("  Einzelkamera — kein Sync noetig")
            return

        if len(cameras) > 2:
            raise NotImplementedError(
                f"Waveform-Sync unterstuetzt aktuell nur 2 Kameras, "
                f"erhalten: {[c.name for c in cameras]}"
            )

        mic_paths = [m.path for m in mics]
        additional = mic_paths[1:] if len(mic_paths) > 1 else None

        offsets = sync_sources([c.path for c in cameras], mic_paths, fps=fps)

        print(f"  Offsets: {offsets}")
        ctx.set("sync.offsets", SyncOffsets(offsets=offsets, fps=fps))
