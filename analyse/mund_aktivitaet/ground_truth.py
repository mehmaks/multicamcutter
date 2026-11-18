"""Mund-Aktivitaet — Test gegen die Ground Truth der Sprachreaktionen.

Datensatz: datasets/speaking-fp/ep*-marker.json (vom User markierte
Sprachreaktions-Cutaways aus echten App-Laeufen: TP / FP / unsicher). Jeder
Marker nennt die Kamera des Cutaways (= die reagierende Person) und das
Quellbild. Der Mund wird DIREKT in diesem Kamerabild ausgewertet — kein Sync,
keine Sprechererkennung noetig.

Die Schwellen sind VORAB festgelegt (aus Folge 61/62, 18.11.2026) und werden
hier NICHT angepasst — sonst waere es kein Test gegen Ueberanpassung:

    TEMPO_THR = 0.0034   Lippen-Tempo (0,33 s), Median der Quantil-0,25-Schwellen
                         der vier Personen aus 61/62
    OPEN_THR  = 0.005    mittlerer innerer Lippenabstand / Gesichtshoehe

Regel je Cutaway (Fenster = der Cutaway-Clip):
    bestaetigt   max Lippen-Tempo >= TEMPO_THR
    verwerfen    sonst, wenn Mund geschlossen (mittlere Oeffnung < OPEN_THR)
    neutral      sonst (bleibt wie heute)

Aufruf: venv/bin/python3 analyse/mund_aktivitaet/ground_truth.py ROHDATEN_ORDNER
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from auswerten import rolling  # noqa: E402

TEMPO_THR = 0.0034
OPEN_THR = 0.005
DATA = ROOT / "datasets" / "speaking-fp"


def main():
    raw_dir = Path(sys.argv[1])
    rows = []
    for mf in sorted(DATA.glob("ep*-marker.json")):
        d = json.loads(mf.read_text(encoding="utf-8"))
        fps = float(d["fps"])
        w = max(3, int(round(0.33 * fps)))
        cache = {}
        for m in d["markers"]:
            if m["label"] not in ("TP", "FP"):
                continue
            cam = m["clip_name"].split(" ")[0]
            if cam not in cache:
                npz = raw_dir / f"mund_{cam}.npz"
                if not npz.exists():
                    print(f"fehlt: {npz.name}")
                    cache[cam] = None
                    continue
                r = np.load(npz, allow_pickle=True)
                gap = r["gap_inner"].astype(float)
                tempo = rolling(np.nanmean, np.abs(np.diff(gap, prepend=np.nan)), w)
                cache[cam] = (gap, tempo, r["face"])
            if cache[cam] is None:
                continue
            gap, tempo, face = cache[cam]
            s, e = m["source_start"], m["source_start"] + m["clip_duration"]
            if e > len(gap):
                continue
            face_share = float(np.mean(face[s:e]))
            t_max = float(np.nanmax(tempo[s:e])) if face_share > 0 else np.nan
            o_mean = float(np.nanmean(gap[s:e])) if face_share > 0 else np.nan
            if face_share < 0.5:
                verdict = "neutral (kein Gesicht)"
            elif t_max >= TEMPO_THR:
                verdict = "bestaetigt"
            elif o_mean < OPEN_THR:
                verdict = "verwerfen"
            else:
                verdict = "neutral"
            rows.append({"ep": d["episode"], "label": m["label"], "cam": cam,
                         "tempo": t_max, "oeffnung": o_mean, "gesicht": face_share,
                         "urteil": verdict, "marker_frame": m["marker_frame"]})

    out = []
    for ep in sorted({r["ep"] for r in rows}) + ["GESAMT"]:
        R = [r for r in rows if ep == "GESAMT" or r["ep"] == ep]
        tp = [r for r in R if r["label"] == "TP"]
        fp = [r for r in R if r["label"] == "FP"]
        def c(L, v):
            return sum(1 for r in L if r["urteil"].startswith(v))
        out.append(
            f"{ep:24} TP {len(tp):2d} / FP {len(fp):2d} | "
            f"verworfen: FP {c(fp, 'verwerfen'):2d}/{len(fp)}, TP {c(tp, 'verwerfen'):2d}/{len(tp)} | "
            f"bestaetigt: TP {c(tp, 'bestaetigt'):2d}/{len(tp)}, FP {c(fp, 'bestaetigt'):2d}/{len(fp)} | "
            f"FP-Rate vorher {len(fp) / max(1, len(R)):.0%} → nachher "
            f"{(len(fp) - c(fp, 'verwerfen')) / max(1, len(R) - c(R, 'verwerfen')):.0%}")
    print("\n".join(out))
    (raw_dir / "ground_truth_ergebnis.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
