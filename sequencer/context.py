"""PipelineContext — State-Machine für den Pipeline-Datenfluss."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set


class PipelineContext:
    """Key-Value Store der zwischen Pipeline-Modulen weitergereicht wird.

    Jedes Modul liest seine deklarierten Inputs und schreibt seine Outputs.
    Der Context trackt welche Keys gesetzt wurden, damit die Pipeline
    fehlende Abhängigkeiten vor der Ausführung erkennen kann.
    """

    def __init__(self, work_dir: Path, fps: float = 25.0):
        self._store: Dict[str, Any] = {}
        self._set_keys: Set[str] = set()
        self._timestamps: Dict[str, float] = {}
        self.work_dir = work_dir
        self.fps = fps
        self._progress_callback: Optional[Callable[[float, str], None]] = None

    def set(self, key: str, value: Any) -> None:
        """Setzt einen Wert im Context."""
        self._store[key] = value
        self._set_keys.add(key)
        self._timestamps[key] = time.time()

    def get(self, key: str) -> Any:
        """Liest einen Wert. Wirft KeyError wenn nicht gesetzt."""
        if key not in self._set_keys:
            raise KeyError(
                f"Context-Key '{key}' wurde nicht gesetzt. "
                f"Verfügbar: {sorted(self._set_keys)}"
            )
        return self._store[key]

    def has(self, key: str) -> bool:
        """Prüft ob ein Key gesetzt wurde."""
        return key in self._set_keys

    def keys(self) -> Set[str]:
        """Alle gesetzten Keys."""
        return set(self._set_keys)

    def remove(self, key: str) -> None:
        """Entfernt einen Key aus dem Context."""
        self._store.pop(key, None)
        self._set_keys.discard(key)
        self._timestamps.pop(key, None)

    def report_progress(self, fraction: float, message: str = "") -> None:
        """Fortschritt melden (wird vom Pipeline-Runner an die UI weitergeleitet)."""
        if self._progress_callback:
            self._progress_callback(fraction, message)

    def set_progress_callback(self, callback: Callable[[float, str], None]) -> None:
        self._progress_callback = callback

    def snapshot_keys(self) -> Dict[str, str]:
        """Gibt eine Übersicht aller Keys mit Typ-Info zurück (für Debugging)."""
        result = {}
        for key in sorted(self._set_keys):
            val = self._store[key]
            type_name = type(val).__name__
            if isinstance(val, list):
                type_name = f"List[{len(val)}]"
            elif isinstance(val, dict):
                type_name = f"Dict[{len(val)}]"
            result[key] = type_name
        return result
