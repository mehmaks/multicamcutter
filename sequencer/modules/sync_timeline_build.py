"""Sync-Timeline-Build-Modul — Erstellt die Sync-Timeline in Resolve."""

from __future__ import annotations

from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module


class SyncTimelineBuildModule(Module):
    name = "sync_timeline_build"
    description = "Sync-Timeline in Resolve erstellen"
    category = "resolve"

    inputs = ["sources.cameras", "sources.mics", "sync.offsets"]
    outputs = []
    optional_inputs = ["sources.mode"]

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        # Nur bei Resolve-Bin-Modus ausfuehren
        if ctx.has("sources.mode"):
            return ctx.get("sources.mode") != "resolve_bin"
        return False

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        cameras = ctx.get("sources.cameras")
        mics = ctx.get("sources.mics")
        sync = ctx.get("sync.offsets")

        # Pruefen ob Resolve-Clips vorhanden
        has_clips = all(c.clip_item is not None for c in cameras)
        if not has_clips:
            print("  Keine Resolve-Clips — Sync-Timeline uebersprungen")
            return

        # TODO: Bestehende build_sync_timeline() Logik aus run_from_bin.py
        # hierher extrahieren. Aktuell Platzhalter.
        print("  Sync-Timeline-Build: noch nicht migriert (Platzhalter)")
        print(f"  Kameras: {[c.name for c in cameras]}")
        print(f"  Mics: {[m.name for m in mics]}")
        print(f"  Offsets: {sync.offsets}")
