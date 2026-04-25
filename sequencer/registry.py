"""Modul-Registry — Discovery und Tool-Presets."""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Type

from sequencer.module import Module

_MODULES_PACKAGE = "sequencer.modules"
_PRESETS_DIR = Path(__file__).parent / "presets"


class Registry:
    """Verwaltet verfügbare Module und Tool-Presets."""

    _modules: Dict[str, Type[Module]] = {}
    _discovered: bool = False

    @classmethod
    def discover(cls) -> None:
        """Auto-Import aller Module aus sequencer/modules/."""
        if cls._discovered:
            return

        try:
            pkg = importlib.import_module(_MODULES_PACKAGE)
        except ImportError:
            return

        for _importer, modname, _ispkg in pkgutil.iter_modules(pkg.__path__):
            mod = importlib.import_module(f"{_MODULES_PACKAGE}.{modname}")
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Module)
                    and attr is not Module
                    and getattr(attr, "name", "")
                ):
                    cls._modules[attr.name] = attr

        cls._discovered = True

    @classmethod
    def register(cls, module_class: Type[Module]) -> Type[Module]:
        """Manuell ein Modul registrieren (auch als Decorator nutzbar)."""
        name = module_class.name
        if not name:
            raise ValueError(f"{module_class.__name__} hat keinen 'name' gesetzt")
        cls._modules[name] = module_class
        return module_class

    @classmethod
    def get(cls, name: str) -> Type[Module]:
        """Modul-Klasse nach Name holen."""
        cls.discover()
        if name not in cls._modules:
            raise KeyError(
                f"Modul '{name}' nicht gefunden. "
                f"Verfügbar: {sorted(cls._modules.keys())}"
            )
        return cls._modules[name]

    @classmethod
    def all_modules(cls) -> Dict[str, Type[Module]]:
        """Alle registrierten Module."""
        cls.discover()
        return dict(cls._modules)

    @classmethod
    def catalog(cls) -> List[Dict]:
        """Modul-Katalog für UI-Darstellung."""
        cls.discover()
        return [
            {
                "name": m.name,
                "description": m.description,
                "category": m.category,
                "inputs": m.inputs,
                "outputs": m.outputs,
                "optional_inputs": m.optional_inputs,
                "schema": m.schema,
            }
            for m in cls._modules.values()
        ]

    @classmethod
    def load_preset(cls, preset_name: str) -> List[Module]:
        """Tool-Preset laden (geordnete Modul-Kette).

        Args:
            preset_name: Name des Presets (z.B. "multicam_cutter")

        Returns:
            Liste von instanziierten Modulen in Ausführungsreihenfolge.
        """
        cls.discover()
        path = _PRESETS_DIR / f"{preset_name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Preset '{preset_name}' nicht gefunden: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        modules = []

        for step in data.get("steps", []):
            module_name = step["module"]
            module_cls = cls.get(module_name)
            modules.append(module_cls())

        return modules

    @classmethod
    def list_presets(cls) -> List[Dict]:
        """Alle verfügbaren Presets auflisten."""
        presets = []
        if _PRESETS_DIR.exists():
            for path in sorted(_PRESETS_DIR.glob("*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                presets.append({
                    "name": path.stem,
                    "title": data.get("name", path.stem),
                    "description": data.get("description", ""),
                    "steps": len(data.get("steps", [])),
                })
        return presets

    @classmethod
    def reset(cls) -> None:
        """Registry zurücksetzen (für Tests)."""
        cls._modules.clear()
        cls._discovered = False
