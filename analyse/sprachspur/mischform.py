"""Sprachspur — Mischform an der Ground Truth testen.

Mischform: Kandidaten für Sprachreaktionen auf der Analysespur suchen (ohne
Lautstärke-Anpassung, `sprachspur.py --roh`), Sprechererkennung, Pausen und
Regel A weiter auf den Originalen. Je Folge:
  - Kontrolllauf Originale OHNE Mischform → muss dem Lauf aus ground_truth.py
    (Ordner original_10) gleichen (Regression: Code ohne Mischform unverändert)
  - Mischform-Lauf
Ausgabe je Folge: TP/FP-Marker erkannt (Original / reine Analysespur aus dem
ersten Test / Mischform) und wie viele Kandidaten Regel A verworfen hat.

Aufruf: venv/bin/python3 analyse/sprachspur/mischform.py PARAMS.json
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ground_truth import EPISODES, BASE, ROOT, PY, run_engine, score, detections  # noqa: E402

MAPPING = ["1", "0"]   # aus ground_truth.py: bei allen vier Folgen erzeugt diese Zuordnung die Marker


def roh_track(mic, other, out):
    a = out / f"{Path(mic).stem}_analysespur_roh.wav"
    if not a.exists():
        subprocess.run([PY, str(Path(__file__).parent / "sprachspur.py"), str(mic), str(other),
                        str(a).replace("_analysespur_roh.wav", ""), "--roh"], check=True,
                       capture_output=True)
    return a


def fp_count(log_path):
    t = Path(log_path).read_text(encoding="utf-8") if Path(log_path).exists() else ""
    m = re.findall(r"FP-Filter \(Regel A[^)]*\): (\d+) Kandidaten verworfen", t)
    return int(m[-1]) if m else None


def main():
    params = json.loads(Path(sys.argv[1]).read_text())
    total = {lab: [0, 0, 0, 0] for lab in ("TP", "FP")}    # n, Original, Analysespur, Mischform
    for ep, (folder_name, cam_names, mic_names) in EPISODES.items():
        folder = BASE / folder_name
        out = folder / "_Sprachspur-Test"
        cams = [folder / f"{c}.MP4" for c in cam_names]
        mics = [folder / m for m in mic_names]
        markers = [m for m in json.loads((ROOT / f"datasets/speaking-fp/{ep}-marker.json").read_text())["markers"]
                   if m["label"] in ("TP", "FP")]
        print(f"\n== {ep}", flush=True)

        roh = [roh_track(mics[0], mics[1], out), roh_track(mics[1], mics[0], out)]

        # Kontrolllauf (Regression)
        p_ctrl = out / "params_kontrolle.json"
        p_ctrl.write_text(json.dumps(params), encoding="utf-8")
        d_ctrl = out / "kontrolle"
        run_engine(folder, cams, mics, MAPPING, p_ctrl, d_ctrl)
        same = all(detections(d_ctrl, c) == detections(out / "original_10", c) for c in cam_names)
        print(f"   Kontrolle (ohne Mischform) = erster Test: {'identisch' if same else 'ABWEICHUNG!'}", flush=True)

        # Mischform: Analysespur je Kamera = Analysespur ihres Mikros
        p_mix = out / "params_mischform.json"
        p_mix.write_text(json.dumps({**params,
                                     "speaking_detect_mic_cam1": [str(roh[int(MAPPING[0])])],
                                     "speaking_detect_mic_cam2": [str(roh[int(MAPPING[1])])]}),
                         encoding="utf-8")
        d_mix = out / "mischform"
        run_engine(folder, cams, mics, MAPPING, p_mix, d_mix)

        so, sa, sm = score(markers, d_ctrl), score(markers, out / "analysespur"), score(markers, d_mix)
        for lab in ("TP", "FP"):
            idx = [i for i, m in enumerate(markers) if m["label"] == lab]
            row = [len(idx), sum(so[i] for i in idx), sum(sa[i] for i in idx), sum(sm[i] for i in idx)]
            total[lab] = [a + b for a, b in zip(total[lab], row)]
            print(f"   {lab}: {row[0]:2d} markiert | erkannt: Original {row[1]} · nur Analysespur {row[2]} · "
                  f"Mischform {row[3]}", flush=True)
        n = [sum(len(detections(d, c)) for c in cam_names) for d in (d_ctrl, out / "analysespur", d_mix)]
        print(f"   Sprachreaktionen gesamt: Original {n[0]} · nur Analysespur {n[1]} · Mischform {n[2]}")
        print(f"   Regel A verworfen: Original {fp_count(d_ctrl / 'engine.log')} · "
              f"Mischform {fp_count(d_mix / 'engine.log')}", flush=True)

    print("\n== GESAMT (Original · nur Analysespur · Mischform)")
    for lab, (n, o, a, m) in total.items():
        print(f"   {lab}: {n} markiert | {o} · {a} · {m}")


if __name__ == "__main__":
    main()
