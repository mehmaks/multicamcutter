"""
Zentrale Pfad-Registry für das gesamte Projekt.

Alle Module, die auf Config, Schemas, Docs oder Logs zugreifen,
importieren ihre Pfade von hier statt sie selbst zu berechnen.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Konfiguration ────────────────────────────────────────────────────────────
CONFIG_DIR       = ROOT / "config"
CONFIG_INI       = CONFIG_DIR / "config.ini"
CONFIG_TEMPLATE  = CONFIG_DIR / "config.template.ini"
NODDING_PATTERNS = CONFIG_DIR / "nodding_patterns.json"
CLIP_IGNORE      = CONFIG_DIR / "clip_ignore_prompts.json"
PRESETS_DIR      = CONFIG_DIR / "presets"
PROJECT_SETTINGS = CONFIG_DIR / "project_settings"
SCHEMAS_DIR      = CONFIG_DIR / "schemas"

# ── Dokumentation & Logs ─────────────────────────────────────────────────────
DOCS_DIR = ROOT / "docs"
LOGS_DIR = ROOT / "logs"

# ── Module ───────────────────────────────────────────────────────────────────
MULTICAM_DIR = ROOT / "modules" / "multicam_cutter"
