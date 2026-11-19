"""Tabelle mit den Analysespur-Pegeln der PRODUKTIONS-Rechnung (Engine-Modul) statt der
Versuchs-WAVs — für den Abgleich „was macht die App anders als der Sichtungsstand?".

Unterschied zur Versuchs-Tabelle: Beide Spuren liegen samplegenau übereinander (BWF-
Zeitstempel), Pegel im Bildraster von Mikro 1 — wie in der Engine.

Aufruf: venv/bin/python3 analyse/aktivitaet/tabelle_produktion.py LAUF.json AUSGABE.npz
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "modules" / "multicam_cutter"))
sys.path.insert(0, str(ROOT))
import einwurf_analysespur as ea  # noqa: E402
from add_reactions_to_edl import parse_resolve_edl, calculate_reference_frames  # noqa: E402


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    fps = float(cfg["fps"])
    P = cfg["persons"]
    d = dict(np.load(cfg["tabelle"], allow_pickle=True))
    A = Path(cfg["a_dir"])
    log = (A / "engine.log") if (A / "engine.log").exists() else Path(cfg["tabelle"]).parent / "original/engine.log"
    off = json.loads(re.search(r'"sync_result", "offsets": (\{[^}]*\})', log.read_text(encoding="utf-8")).group(1))
    names = [Path(p["video"]).name for p in P]
    _, tz = calculate_reference_frames(parse_resolve_edl(str(A / "base.edl"), fps),
                                       [{"name": n, "video": p["video"]} for n, p in zip(names, P)], fps)
    o0, o1 = off[P[0]["mic_key"]], off[P[1]["mic_key"]]
    p0, p1, info = ea.analysespur_pegel(P[0]["mic"], P[1]["mic"], ea._start_versatz(P[0]["mic"], P[1]["mic"], o0, o1, fps),
                                        fps, tempfile.gettempdir())
    t = np.arange(len(d["engine"]))
    mi = tz[names[0]] + off[P[0]["cam_key"]] + t - o0
    ok = (mi >= 0) & (mi < len(p0))
    for k, p in enumerate((p0, p1)):
        a = np.full(len(t), -110.0, np.float32)
        a[ok] = p[mi[ok]]
        d[f"lv_ana{k}"] = a
    np.savez_compressed(sys.argv[2], **d)
    print(f"→ {sys.argv[2]} ({info})")


if __name__ == "__main__":
    main()
