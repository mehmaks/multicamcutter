"""Cut-Timeline-Build-Modul — Erstellt die finale Schnitt-Timeline in Resolve."""

from __future__ import annotations

from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module


class CutTimelineBuildModule(Module):
    name = "cut_timeline_build"
    description = "Finale Schnitt-Timeline in Resolve erstellen"
    category = "resolve"

    inputs = ["cut_events", "sources.cameras", "sources.mics", "sync.offsets"]
    outputs = []
    optional_inputs = ["audio_keeps", "sources.mode"]

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        if ctx.has("sources.mode"):
            return ctx.get("sources.mode") != "resolve_bin"
        return False

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        cut_events = ctx.get("cut_events")
        cameras = ctx.get("sources.cameras")
        mics = ctx.get("sources.mics")
        sync = ctx.get("sync.offsets")
        audio_keeps = ctx.get("audio_keeps") if ctx.has("audio_keeps") else None

        has_clips = all(c.clip_item is not None for c in cameras)
        if not has_clips:
            print("  Keine Resolve-Clips — Cut-Timeline uebersprungen")
            return

        # TODO: Bestehende build_cut_timeline() Logik aus run_from_bin.py
        # hierher extrahieren. Aktuell Platzhalter.
        print("  Cut-Timeline-Build: noch nicht migriert (Platzhalter)")
        print(f"  {len(cut_events)} Events")
        print(f"  Audio-Keeps: {'ja' if audio_keeps else 'nein'}")
