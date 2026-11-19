"""Sprachspur — Gegenprobe an der Ground Truth der Sprachreaktionen.

Datensatz: datasets/speaking-fp/ep*-marker.json — jede Sprachreaktion, die die App
damals gesetzt hat, vom User als TP (echt) / FP (Fehlalarm) markiert, mit Kamera und
Quellbild. Für jede Folge:
  1. Mikro↔Kamera-Zuordnung bestimmen: beide Varianten auf den Originalen laufen
     lassen, die Variante nehmen, die mehr markierte Cutaways wiedererzeugt.
  2. Analysespuren rechnen (sprachspur.py, beide Mikros).
  3. Gleiche Erkennung auf den Analysespuren, Sync fest von den Originalen.
  4. Je Marker: auf Original erkannt? auf Analysespur erkannt?
Ziel: echte (TP) bleiben, Fehlalarme (FP) werden weniger — nicht mehr.

Ergebnisse dauerhaft in <Folge>/_Sprachspur-Test/.

Aufruf: venv/bin/python3 analyse/sprachspur/ground_truth.py PARAMS.json ARBEITSORDNER
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "apps/multicam-cutter/engine/multicam_engine.py"
PY = str(ROOT / "venv/bin/python3")
BASE = Path("/Volumes/JENA UNITED")

EPISODES = {
    "ep01-mario-koch": ("45 - Mario Koch", ["C9320", "C7814"], ["MIC1.WAV", "MIC2.WAV"]),
    "ep02-sarah-jung": ("47 - Sarah Jung", ["C9730", "jena_0002"], ["MIC1.WAV", "MIC2.WAV"]),
    "ep03-danny-mueller": ("44 - Danny Müller", ["C7804", "C8789"], ["MIC1.WAV", "MIC2.WAV"]),
    "ep04-robin-tutzschke": ("46 - Dr Robin Tutzschke", ["C9322", "C7816"], ["MIC1_Orig.WAV", "MIC2_Orig.WAV"]),
}


def run_engine(folder, cams, mics, cam_mics, params, out_dir, manual=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [PY, str(ENGINE), "--folder", str(folder), "--fps", "25", "--params", str(params),
           "--output", str(out_dir / "lauf.aaf"), "--cams", *[str(c) for c in cams],
           "--mics", *[str(m) for m in mics], "--cam-mics", *cam_mics,
           "--cam-types", "close", "close", "--skip-analysis"]
    for path, off in (manual or {}).items():
        cmd += ["--manual-offset", f"{path}={off}"]
    import os
    log = subprocess.run(cmd, capture_output=True, text=True,
                         env={**os.environ, "PYTHONUNBUFFERED": "1"}).stdout
    (out_dir / "engine.log").write_text(log, encoding="utf-8")
    m = re.search(r'"work_dir": "([^"]+)"', log)
    if not m:
        raise RuntimeError(f"Engine-Lauf fehlgeschlagen, siehe {out_dir / 'engine.log'}")
    wd = Path(m.group(1))
    for f in list(wd.glob("*_speaking.json")) + [wd / "base.edl"]:
        (out_dir / f.name).write_bytes(f.read_bytes())
    offs = json.loads(re.search(r'"sync_result", "offsets": (\{[^}]*\})', log).group(1))
    return offs


def detections(out_dir, cam):
    p = out_dir / f"{cam}_speaking.json"
    return [r["frame"] for r in json.loads(p.read_text())["reactions"]] if p.exists() else []


def score(markers, out_dir, fps=25):
    """Je Marker: wurde an dieser Stelle (Cutaway-Clip ± 1 s) eine Sprachreaktion erkannt?"""
    res = []
    for m in markers:
        cam = m["clip_name"].split(" ")[0]
        det = detections(out_dir, cam)
        s, e = m["source_start"] - fps, m["source_start"] + m["clip_duration"] + fps
        res.append(any(s <= f <= e for f in det))
    return res


def main():
    params, work = Path(sys.argv[1]), Path(sys.argv[2])
    total = {"TP": [0, 0, 0], "FP": [0, 0, 0]}          # [Anzahl, Original, Analysespur]
    for ep, (folder_name, cam_names, mic_names) in EPISODES.items():
        folder = BASE / folder_name
        out = folder / "_Sprachspur-Test"
        cams = [folder / f"{c}.MP4" for c in cam_names]
        mics = [folder / m for m in mic_names]
        markers = [m for m in json.loads((ROOT / f"datasets/speaking-fp/{ep}-marker.json").read_text())["markers"]
                   if m["label"] in ("TP", "FP")]
        print(f"\n== {ep} ({len(markers)} Marker)", flush=True)

        # 1) Zuordnung: welche Variante erzeugt die markierten Cutaways wieder?
        best = None
        for cm in (["0", "1"], ["1", "0"]):
            d = out / f"original_{''.join(cm)}"
            offs = run_engine(folder, cams, mics, cm, params, d)
            hit = sum(score(markers, d))
            print(f"   Zuordnung cam-mics {cm}: {hit}/{len(markers)} Marker wiedererzeugt", flush=True)
            if best is None or hit > best[1]:
                best = (cm, hit, d, offs)
        cm, _, d_orig, offs = best

        # 2) Analysespuren rechnen (je Mikro, das andere als Übersprech-Referenz)
        ana = [out / f"{Path(m).stem}_analysespur.wav" for m in mics]
        for own, other, a in ((mics[0], mics[1], ana[0]), (mics[1], mics[0], ana[1])):
            if not a.exists():
                pre = str(a).replace("_analysespur.wav", "")
                r = subprocess.run([PY, str(Path(__file__).parent / "sprachspur.py"), str(own), str(other), pre],
                                   capture_output=True, text=True)
                print("   " + " | ".join(l for l in r.stdout.splitlines() if "Abstand" in l), flush=True)

        # 3) Gleiche Erkennung auf den Analysespuren, Sync fest von den Originalen
        manual = {str(ana[0]): offs["MIC1"], str(ana[1]): offs["MIC2"]}
        d_ana = out / "analysespur"
        run_engine(folder, cams, ana, cm, params, d_ana, manual=manual)

        # 4) Auswertung je Marker
        so, sa = score(markers, d_orig), score(markers, d_ana)
        for lab in ("TP", "FP"):
            idx = [i for i, m in enumerate(markers) if m["label"] == lab]
            o, a = sum(so[i] for i in idx), sum(sa[i] for i in idx)
            total[lab][0] += len(idx); total[lab][1] += o; total[lab][2] += a
            print(f"   {lab}: {len(idx):2d} markiert | heute erkannt: Original {o} → Analysespur {a}", flush=True)
        n_o = sum(len(detections(d_orig, c)) for c in cam_names)
        n_a = sum(len(detections(d_ana, c)) for c in cam_names)
        print(f"   Sprachreaktionen gesamt (ganze Folge): Original {n_o} → Analysespur {n_a}", flush=True)

    print("\n== GESAMT")
    for lab, (n, o, a) in total.items():
        print(f"   {lab}: {n} markiert | erkannt Original {o} → Analysespur {a}")


if __name__ == "__main__":
    main()
