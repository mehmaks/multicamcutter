"""Ingest-Modul — Universeller Quellen-Adapter.

Nimmt eine Quelle an (Resolve-Bin, Ordner oder Einzeldatei) und
erzeugt einen einheitlichen Datenstrom aus Kameras und Mikrofonen.
Downstream-Module sehen nur noch sources.cameras und sources.mics —
die Herkunft ist transparent.

TODO: Batch-Modus (folder_batch) — bei Ordner-Input mit Unterordnern
als "Loop-Machine" fungieren: pro Unterordner die gesamte Pipeline
einmal durchlaufen. Erfordert Zusammenspiel mit Pipeline-Runner
(äußerer Loop statt innerer).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import MediaSource

# Dateiendungen
_VIDEO_EXTS = {'.mp4', '.mov', '.mxf', '.r3d', '.ari', '.braw'}
_AUDIO_EXTS = {'.wav', '.aif', '.aiff', '.flac'}


class IngestModule(Module):
    name = "ingest"
    description = "Quellen einlesen (Resolve-Bin, Ordner oder Datei)"
    category = "io"

    inputs = []
    outputs = ["sources.cameras", "sources.mics", "sources.mode"]
    optional_inputs = []

    schema = {
        "expanders": [{
            "key": "ingest",
            "label": "Quelle",
            "rows": [{
                "columns": 1,
                "params": [{
                    "name": "source_mode",
                    "widget": "selectbox",
                    "options": ["resolve_bin", "folder", "file"],
                    "default": "resolve_bin",
                    "label": "Quell-Modus",
                    "help": "Resolve-Bin, Ordner oder Einzeldatei",
                    "column": 0,
                }],
            }],
        }],
    }

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        mode = params.get("source_mode", "resolve_bin")

        if mode == "resolve_bin":
            cameras, mics = self._ingest_resolve_bin(params)
        elif mode == "folder":
            cameras, mics = self._ingest_folder(params)
        elif mode == "file":
            cameras, mics = self._ingest_file(params)
        else:
            raise ValueError(f"Unbekannter Ingest-Modus: {mode}")

        if not cameras:
            raise ValueError("Keine Kamera-Quellen gefunden")

        ctx.set("sources.cameras", cameras)
        ctx.set("sources.mics", mics)
        ctx.set("sources.mode", mode)

        cam_names = [c.name for c in cameras]
        mic_names = [m.name for m in mics]
        print(f"  Kameras: {cam_names}")
        print(f"  Mikrofone: {mic_names}")

    # ── Resolve-Bin ──────────────────────────────────────────

    def _ingest_resolve_bin(
        self, params: Dict[str, Any]
    ) -> tuple[List[MediaSource], List[MediaSource]]:
        """Scannt einen Resolve Media Pool Bin nach Video- und Audio-Clips."""
        bin_name = params.get("bin_name", "")
        if not bin_name:
            raise ValueError("Kein Bin-Name angegeben")

        try:
            from resolve_bridge.connection import get_resolve
            resolve = get_resolve()
            pm = resolve.GetProjectManager()
            project = pm.GetCurrentProject()
            mp = project.GetMediaPool()
        except Exception as e:
            raise RuntimeError(f"Resolve-Verbindung fehlgeschlagen: {e}") from e

        folder = self._find_bin(mp.GetRootFolder(), bin_name)
        if not folder:
            raise ValueError(f"Bin '{bin_name}' nicht gefunden")

        cameras = []
        mics = []
        for clip in folder.GetClipList():
            props = clip.GetClipProperty()
            name = props.get("Clip Name", props.get("File Name", ""))
            path = props.get("File Path", "")
            clip_type = props.get("Type", "")

            if clip_type == "Video" or clip_type == "Video + Audio":
                cameras.append(MediaSource(
                    name=name, path=path,
                    source_type="camera", clip_item=clip,
                ))
            elif clip_type == "Audio":
                mics.append(MediaSource(
                    name=name, path=path,
                    source_type="mic", clip_item=clip,
                ))

        cameras.sort(key=lambda s: s.name)
        mics.sort(key=lambda s: s.name)
        return cameras, mics

    def _find_bin(self, folder, name: str):
        """Rekursive Suche nach einem Bin im Media Pool."""
        if folder.GetName() == name:
            return folder
        for sub in folder.GetSubFolderList():
            found = self._find_bin(sub, name)
            if found:
                return found
        return None

    # ── Ordner ───────────────────────────────────────────────

    def _ingest_folder(
        self, params: Dict[str, Any]
    ) -> tuple[List[MediaSource], List[MediaSource]]:
        """Scannt einen Ordner nach Video- und Audio-Dateien."""
        folder_path = Path(params.get("folder_path", ""))
        if not folder_path.exists():
            raise ValueError(f"Ordner nicht gefunden: {folder_path}")

        cameras = []
        mics = []

        for f in sorted(folder_path.iterdir()):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in _VIDEO_EXTS:
                cameras.append(MediaSource(
                    name=f.name, path=str(f), source_type="camera",
                ))
            elif ext in _AUDIO_EXTS:
                mics.append(MediaSource(
                    name=f.name, path=str(f), source_type="mic",
                ))

        return cameras, mics

    # ── Einzeldatei ──────────────────────────────────────────

    def _ingest_file(
        self, params: Dict[str, Any]
    ) -> tuple[List[MediaSource], List[MediaSource]]:
        """Nimmt eine einzelne Datei als Quelle."""
        file_path = Path(params.get("file_path", ""))
        if not file_path.exists():
            raise ValueError(f"Datei nicht gefunden: {file_path}")

        ext = file_path.suffix.lower()
        if ext in _VIDEO_EXTS:
            return [MediaSource(
                name=file_path.name, path=str(file_path), source_type="camera",
            )], []
        elif ext in _AUDIO_EXTS:
            return [], [MediaSource(
                name=file_path.name, path=str(file_path), source_type="mic",
            )]
        else:
            raise ValueError(
                f"Unbekannter Dateityp: {ext} "
                f"(erwartet: {_VIDEO_EXTS | _AUDIO_EXTS})"
            )
