"""Schnitt mit fester Sprechererkennung (base.edl aus dem A-Lauf) neu bauen.

--quelle a: Einwürfe der App (A, aus a_dir)   --quelle b: Einwürfe aus einwurf_b.py
Schreibt die <cam>_speaking.json in den Arbeitsordner der Engine und lässt sie mit
--skip-base-edl laufen: gleiche Sprechererkennung, nur Einwürfe/Parameter anders.
Für die Auswertung: --params mit abgeschalteten Schnittregeln (params_analyse.json),
damit Mindestabstände usw. Erkennungen nicht verdecken (User-Wunsch 19.11.).

Aufruf: venv/bin/python3 analyse/aktivitaet/lauf.py CONFIG.json --quelle a|b --params P.json --out DIR
CONFIG: wie tabelle.json, zusätzlich "tabelle", "a_dir" (Kopie des A-Arbeitsordners
        mit base.edl + App-Einwürfen), "folder", "work_dir" (Engine-Arbeitsordner)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "modules" / "multicam_cutter"))
from einwurf_b import detect  # noqa: E402
from frame_utils import frames_to_timecode  # noqa: E402
from add_reactions_to_edl import parse_resolve_edl, calculate_reference_frames  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--quelle", choices=["a", "b"], required=True)
    ap.add_argument("--params", required=True)
    ap.add_argument("--out", required=True)
    x = ap.parse_args()
    cfg = json.loads(Path(x.config).read_text(encoding="utf-8"))
    a_dir, out = Path(cfg["a_dir"]), Path(x.out)
    out.mkdir(parents=True, exist_ok=True)
    persons = cfg["persons"]
    names = [Path(p["video"]).name for p in persons]

    if x.quelle == "a":
        for n in names:
            shutil.copy(a_dir / f"{Path(n).stem}_speaking.json", out / f"{Path(n).stem}_speaking.json")
    else:
        d = np.load(cfg["tabelle"], allow_pickle=True)
        fps = float(d["fps"])
        events = parse_resolve_edl(str(a_dir / "base.edl"), fps)
        _, tzvf = calculate_reference_frames(
            events, [{"name": n, "video": p["video"]} for n, p in zip(names, persons)], fps)
        res, params = detect(d)
        for k, n in enumerate(names):
            rs = [{"frame": int(s + tzvf[n]), "timecode": frames_to_timecode(int(s + tzvf[n]), fps),
                   "type": "speaking_reaction", "confidence": 1.0, "dur_s": round((e - s) / fps, 2),
                   "source": "analysespur"} for s, e in res[k]["events"]]
            (out / f"{Path(n).stem}_speaking.json").write_text(
                json.dumps({"fps": fps, "reactions": rs}, indent=1), encoding="utf-8")
            print(f"{persons[k]['name']}: {len(rs)} Einwürfe")
        (out / "einwurf_b_params.json").write_text(json.dumps(params, indent=1), encoding="utf-8")

    # Engine-Arbeitsordner: A-Stand (base.edl usw.) wiederherstellen, Einwürfe hinein
    wd = Path(cfg["work_dir"])
    for f in a_dir.iterdir():
        if f.is_file() and f.suffix in (".edl", ".json"):
            shutil.copy(f, wd / f.name)
    for f in out.glob("*_speaking.json"):
        shutil.copy(f, wd / f.name)
    aaf = out / "lauf.aaf"
    if aaf.exists():
        aaf.unlink()
    cmd = [str(ROOT / "venv/bin/python3"), str(ROOT / "apps/multicam-cutter/engine/multicam_engine.py"),
           "--folder", cfg["folder"], "--fps", str(cfg["fps"]), "--params", x.params,
           "--output", str(aaf), "--cams", *[p["video"] for p in persons],
           "--mics", *[p["mic"] for p in persons], "--cam-mics", *[str(i) for i in range(len(persons))],
           "--cam-types", *["close"] * len(persons), "--skip-analysis", "--skip-base-edl"]
    log = subprocess.run(cmd, capture_output=True, text=True,
                         env={**os.environ, "PYTHONUNBUFFERED": "1"}).stdout
    (out / "engine.log").write_text(log, encoding="utf-8")
    if not aaf.exists():
        raise SystemExit(f"Engine-Lauf fehlgeschlagen, siehe {out / 'engine.log'}")
    for f in ("final.edl", "final.colors.json", "decision_log.json", "params.json"):
        shutil.copy(wd / f, out / f)
    m = re.findall(r"Speaking-Cutaways: (\d+)", log)
    print(f"→ {aaf} (Einwurf-Cutaways PASS 2: {m[-1] if m else '?'})")


if __name__ == "__main__":
    main()
