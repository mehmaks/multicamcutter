"""Module-Basisklassen für Pipeline-Module."""

from __future__ import annotations

import json
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from sequencer.context import PipelineContext


class Module(ABC):
    """Basisklasse für alle Pipeline-Module.

    Jedes Modul deklariert seine Inputs (was es aus dem Context liest)
    und Outputs (was es in den Context schreibt). Die Pipeline validiert
    vor der Ausführung, dass alle Abhängigkeiten erfüllt sind.
    """

    name: str = ""
    description: str = ""
    category: str = "analysis"       # "io" | "analysis" | "editing" | "resolve"

    inputs: List[str] = []
    outputs: List[str] = []
    optional_inputs: List[str] = []

    # JSON-Schema für konfigurierbare Parameter (multicam_params.json-Format)
    schema: Dict = {}

    @abstractmethod
    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        """Modul ausführen — liest aus ctx, schreibt in ctx."""
        ...

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        """True wenn dieses Modul übersprungen werden soll (z.B. Feature deaktiviert)."""
        return False

    @property
    def requires_resolve(self) -> bool:
        return self.category == "resolve"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} '{self.name}'>"


class SubprocessModule(Module):
    """Modul das in einem separaten Python-Prozess läuft.

    Nützlich für Module die eine andere Python-Version brauchen (z.B. py39
    für MediaPipe) oder GPU-intensiv sind (CLIP-Filter).
    """

    script_path: str = ""
    python_executable: str = ""      # Leer = sys.executable

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        work_dir = ctx.work_dir
        self._serialize_inputs(ctx, work_dir, params)
        cmd = self._build_command(ctx, params, work_dir)
        self._run_subprocess(cmd, ctx)
        self._deserialize_outputs(ctx, work_dir)

    @abstractmethod
    def _build_command(
        self,
        ctx: PipelineContext,
        params: Dict[str, Any],
        work_dir: Path,
    ) -> List[str]:
        """CLI-Kommando zusammenbauen."""
        ...

    def _serialize_inputs(
        self,
        ctx: PipelineContext,
        work_dir: Path,
        params: Dict[str, Any],
    ) -> None:
        """Inputs aus dem Context auf Disk schreiben (Override in Subklasse)."""
        pass

    def _deserialize_outputs(self, ctx: PipelineContext, work_dir: Path) -> None:
        """Outputs von Disk zurück in den Context laden (Override in Subklasse)."""
        pass

    def _run_subprocess(self, cmd: List[str], ctx: PipelineContext) -> None:
        """Subprocess starten und Fortschritt parsen."""
        python = self.python_executable or sys.executable
        full_cmd = [python] + cmd

        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Subprocess-Modul '{self.name}' fehlgeschlagen "
                f"(exit code {result.returncode}):\n{result.stderr[-2000:]}"
            )
