"""Eine Folge für den Analyse-Player vorbereiten — alles aus der .multicam der App.

Schritte (jeder wird übersprungen, wenn sein Ergebnis schon existiert):
  1. App-Parameter aus .multicam (Nicken aus), Mikros je Kamera (Splits verbunden)
  2. Engine-Lauf A wie in der App → Sync, base.edl, App-Einwürfe, speaking_debug.json
  3. Analysespuren (sprachspur.py --roh) je Person
  4. Tabelle je Timeline-Bild (tabelle.py)
  5. Schnitte A und B ohne Schnittregeln (lauf.py, params_analyse.json)
  6. Player-Sitzung mit den Unterschieden A/B (analyse/player/bauen.py)

Medien bleiben im Arbeitsordner; alle Testdaten kommen nach TESTORDNER (z. B. ins Archiv).

Aufruf: venv/bin/python3 analyse/aktivitaet/vorbereiten.py ARBEITSORDNER TESTORDNER [--titel T]
Genau 2 Kameras mit je einem Mikro (eine Person je Kamera).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PY = str(ROOT / "venv/bin/python3")
sys.path.insert(0, str(ROOT))

ANALYSE_PARAMS = {"min_shot": 0.5, "max_shot": 9999, "cleanup_dur": 0.2, "randomness": 0,
                  "transition_speaker_change": False, "transition_cutaway_back": [],
                  "cluster_max_gap_frames": 0}


def schritt(text):
    print(f"\n== {text}", flush=True)


def run(cmd, log=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       env={**os.environ, "PYTHONUNBUFFERED": "1"})
    if log:
        Path(log).write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"Fehlgeschlagen: {' '.join(map(str, cmd[:3]))} …\n{(r.stderr or r.stdout)[-1500:]}")
    return r.stdout


def fps_of(video):
    rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=r_frame_rate", "-of", "csv=p=0", str(video)],
                          capture_output=True, text=True, check=True).stdout.strip()
    a, b = rate.split("/")
    return round(float(a) / float(b), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("test")
    ap.add_argument("--titel")
    x = ap.parse_args()
    E, T = Path(x.folder), Path(x.test)
    T.mkdir(parents=True, exist_ok=True)
    mc = json.loads((E / ".multicam").read_text(encoding="utf-8"))
    cams = [c for c in mc["cameras"] if c.get("included", True)]
    if len(cams) != 2 or any(len(c["assigned_mics"]) != 1 for c in cams):
        raise SystemExit("Nur 2 Kameras mit je einem Mikro werden unterstützt.")
    mics = {m["id"]: m for m in mc["mics"]}

    schritt("1. Parameter und Mikros")
    params = {**mc["params"], "nodding_enabled": False}
    (T / "params_app.json").write_text(json.dumps(params, indent=1), encoding="utf-8")
    (T / "params_analyse.json").write_text(json.dumps({**params, **ANALYSE_PARAMS}, indent=1), encoding="utf-8")
    joins = {j[0]: j for j in mc.get("audio_joins") or []}
    for j in mc.get("audio_joins") or []:
        for f in j:
            joins.setdefault(f, j)
    persons = []
    os.environ["MCC_JOIN_DIR"] = str(T / "joined")
    from shared.split_audio import join_group, order_manual_group
    for i, c in enumerate(cams):
        m = mics[c["assigned_mics"][0]]
        path = E / m["filename"]
        if m["filename"] in joins:
            parts = order_manual_group([str(E / f) for f in joins[m["filename"]]])
            path = Path(join_group(parts))
        persons.append({"name": m.get("display_name") or f"P{i + 1}", "video": str(E / c["filename"]),
                        "cam_key": f"CAM{i + 1}", "mic": str(path), "mic_key": f"MIC{i + 1}",
                        "ana": str(T / f"P{i + 1}_analysespur_roh.wav")})
        print(f"  {persons[-1]['name']}: {c['filename']} ← {path.name}")
    fps = fps_of(persons[0]["video"])
    print(f"  {fps} fps")

    schritt("2. Engine-Lauf A (wie die App, Nicken aus)")
    A = T / "A_heute_work"
    if not (A / "base.edl").exists():
        (T / "original").mkdir(exist_ok=True)
        log = run([PY, ROOT / "apps/multicam-cutter/engine/multicam_engine.py", "--folder", E, "--fps", fps,
                   "--params", T / "params_app.json", "--output", T / "original/lauf.aaf",
                   "--cams", *[p["video"] for p in persons], "--mics", *[p["mic"] for p in persons],
                   "--cam-mics", "0", "1", "--cam-types", "close", "close", "--skip-analysis"],
                  log=T / "original/engine.log")
        wd = Path(re.search(r'"work_dir": "([^"]+)"', log).group(1))
        A.mkdir(exist_ok=True)
        for f in wd.iterdir():
            if f.is_file() and f.suffix in (".edl", ".json"):
                shutil.copy(f, A / f.name)
        shutil.copy(T / "original/engine.log", A / "engine.log")
        (T / "work_dir.txt").write_text(str(wd), encoding="utf-8")
    wd = (T / "work_dir.txt").read_text(encoding="utf-8").strip()
    print(f"  Arbeitsordner {wd}")

    schritt("3. Analysespuren")
    for k, p in enumerate(persons):
        if not Path(p["ana"]).exists():
            other = persons[1 - k]["mic"]
            print(run([PY, ROOT / "analyse/sprachspur/sprachspur.py", p["mic"], other,
                       p["ana"].replace("_analysespur_roh.wav", ""), "--roh"]).strip().splitlines()[-2])

    cfg = {"fps": fps, "engine_dir": str(A), "out": str(T / "tabelle.npz"), "persons": persons,
           "tabelle": str(T / "tabelle.npz"), "a_dir": str(A), "folder": str(E), "work_dir": wd}
    (T / "lauf.json").write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")

    schritt("4. Tabelle")
    if not (T / "tabelle.npz").exists():
        run([PY, HERE / "tabelle.py", T / "lauf.json"])

    schritt("5. Schnitte A und B ohne Schnittregeln")
    for q in ("a", "b"):
        if not (T / f"analyse_{q}/lauf.aaf").exists():
            print("  " + run([PY, HERE / "lauf.py", T / "lauf.json", "--quelle", q,
                              "--params", T / "params_analyse.json", "--out", T / f"analyse_{q}"]).strip().splitlines()[-1])

    schritt("6. Player-Sitzung")
    pc = {**cfg, "a_schnitt": str(T / "analyse_a"), "b_schnitt": str(T / "analyse_b"),
          "aaf": str(T / "analyse_b/lauf.aaf"), "titel": x.titel or E.name}
    (T / "player.json").write_text(json.dumps(pc, indent=1, ensure_ascii=False), encoding="utf-8")
    print("  " + run([PY, ROOT / "analyse/player/bauen.py", T / "player.json", T / "player"]).strip().splitlines()[0])

    R = T / "Resolve"
    R.mkdir(exist_ok=True)
    shutil.copy(T / "analyse_a/lauf.aaf", R / f"{E.name} A heute (ohne Schnittregeln).aaf")
    shutil.copy(T / "analyse_b/lauf.aaf", R / f"{E.name} B Analysespur (ohne Schnittregeln).aaf")
    names = ",".join(f"{Path(p['video']).name}={p['name']}" for p in persons)
    print("  " + run([PY, HERE / "ab_marker.py", T / "analyse_a", T / "analyse_b",
                      R / f"{E.name} Marker A-B (ohne Schnittregeln).edl", "--aaf", R / f"{E.name} B Analysespur (ohne Schnittregeln).aaf",
                      "--namen", names]).strip())
    print(f"\nFertig. Player: venv/bin/python3 analyse/player/server.py \"{T / 'player'}\"")


if __name__ == "__main__":
    main()
