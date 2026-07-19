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

# ── User-schreibbare Konfiguration (Mac-App) ─────────────────────────────────
# Gebündelte Configs liegen im .app read-only (_internal/config). User-Overrides
# gehören nach Application Support — derselbe Ordner wie die Presets der Mac-App
# (~/Library/Application Support/MulticamCutter/, siehe EngineController.presetsDir).
USER_CONFIG_DIR   = Path.home() / "Library" / "Application Support" / "MulticamCutter"
USER_CLIP_PROMPTS = USER_CONFIG_DIR / "clip_prompts.json"

def effective_clip_prompts_path() -> Path:
    """CLIP-Ignore-Prompts: user-editierte Datei bevorzugen, sonst gebündelte Defaults."""
    return USER_CLIP_PROMPTS if USER_CLIP_PROMPTS.exists() else CLIP_IGNORE

# ── Dokumentation & Logs ─────────────────────────────────────────────────────
DOCS_DIR = ROOT / "docs"
LOGS_DIR = ROOT / "logs"

# ── Module ───────────────────────────────────────────────────────────────────
MULTICAM_DIR = ROOT / "modules" / "multicam_cutter"
