"""Einwurf-Erkennung „B" — Adapter für die Analyse-Skripte.

Die Erkennung selbst lebt seit dem Einbau in die App in
modules/multicam_cutter/einwurf_analysespur.py (eine Quelle für App und Analyse).
Hier nur: tabelle.npz → detect(pegel, engine, fps).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from einwurf_analysespur import PARAMS, detect as _detect  # noqa: E402,F401


def detect(d, params=None):
    """d = geladene tabelle.npz (lv_ana0/1, engine, fps)."""
    return _detect([d["lv_ana0"], d["lv_ana1"]], d["engine"], float(d["fps"]), params)
