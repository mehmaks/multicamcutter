"""
Per-project settings persistence.

Settings are stored as JSON files, one per Resolve project name:
  modules/multicam_cutter/project_settings/<project_name>.json

Each file holds settings for all pages:
  { "silence_cutter": { "threshold_db": -40, ... }, "multicam": { ... } }

Usage:
    from resolve_bridge.project_settings import load_page, save_page

    settings = load_page(project_name, "silence_cutter")
    save_page(project_name, "silence_cutter", {"threshold_db": -35, ...})
"""

import json
import re
from pathlib import Path

from shared.paths import PROJECT_SETTINGS
_SETTINGS_DIR = PROJECT_SETTINGS


def _safe_filename(name: str) -> str:
    """Converts a project name to a safe filename."""
    return re.sub(r"[^\w\-. ]", "_", name).strip() or "unnamed"


def _path(project_name: str) -> Path:
    return _SETTINGS_DIR / f"{_safe_filename(project_name)}.json"


def load_page(project_name: str, page: str) -> dict:
    """Returns saved settings dict for the given project + page, or {} if none."""
    p = _path(project_name)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get(page, {})
    except Exception:
        return {}


def save_page(project_name: str, page: str, settings: dict):
    """Merges settings into the project file for the given page."""
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(project_name)
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[page] = settings
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
