#!/usr/bin/env python3
"""Eyeline-Messung je Kamera (Vorstufe für den Eyeline-Abgleich im XML-Export).

Misst über die ganze Datei verteilt (alle --step Sekunden ein Bild) die Augenhöhe und
die Gesichtsgröße (Augenabstand) jedes erkannten Gesichts. Pro Kamera: Median über alle
Bilder, bei mehreren Personen der Mittelwert ihrer Augenhöhen.

Werte relativ zur Bildhöhe (0 = oben, 1 = unten). Nur lesend, schreibt nichts in die Folge.

Aufruf: venv/bin/python3 analyse/eyeline_messung.py VIDEO1 VIDEO2 … [--step 5] [--json out.json]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

ROOT = Path(__file__).resolve().parents[1]
MODELL = ROOT / "modules/multicam_cutter/face_landmarker.task"

# Augenmitte: Mittel aus äußerem und innerem Lidwinkel je Auge
L_AUGE = (33, 133)
R_AUGE = (362, 263)


def messe(video, step, max_faces):
    opts = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MODELL)),
        running_mode=mp_vision.RunningMode.IMAGE, num_faces=max_faces)
    lm = mp_vision.FaceLandmarker.create_from_options(opts)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    proben = []  # je Bild: Liste von (x, augen_y, augenabstand) relativ
    for f in range(0, n, max(1, int(step * fps))):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        if not ok:
            continue
        klein = cv2.resize(img, (w // 3, h // 3))
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                                 data=cv2.cvtColor(klein, cv2.COLOR_BGR2RGB)))
        gesichter = []
        for g in res.face_landmarks or []:
            lx = (g[L_AUGE[0]].x + g[L_AUGE[1]].x) / 2
            ly = (g[L_AUGE[0]].y + g[L_AUGE[1]].y) / 2
            rx = (g[R_AUGE[0]].x + g[R_AUGE[1]].x) / 2
            ry = (g[R_AUGE[0]].y + g[R_AUGE[1]].y) / 2
            abstand = np.hypot((rx - lx) * w, (ry - ly) * h) / h
            gesichter.append(((lx + rx) / 2, (ly + ry) / 2, abstand))
        proben.append((f / fps, gesichter))
    cap.release()
    return {"w": w, "h": h, "fps": fps, "proben": proben}


def reihe(video, rate, max_faces, breite=1280):
    """Zeitreihe: ffmpeg dekodiert fortlaufend (schneller als Einzelsprünge) und gibt
    `rate` Bilder je Sekunde aus. Je Bild: (sekunde, [(x, augen_y, augenabstand), …])."""
    import subprocess
    opts = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MODELL)),
        running_mode=mp_vision.RunningMode.IMAGE, num_faces=max_faces)
    lm = mp_vision.FaceLandmarker.create_from_options(opts)
    cap = cv2.VideoCapture(str(video))
    w0, h0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    w, h = breite, int(round(breite * h0 / w0 / 2)) * 2
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vf",
                          f"fps={rate},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE)
    out, i = [], 0
    while True:
        buf = p.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        img = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=img))
        gs = []
        for g in res.face_landmarks or []:
            lx = (g[L_AUGE[0]].x + g[L_AUGE[1]].x) / 2
            ly = (g[L_AUGE[0]].y + g[L_AUGE[1]].y) / 2
            rx = (g[R_AUGE[0]].x + g[R_AUGE[1]].x) / 2
            ry = (g[R_AUGE[0]].y + g[R_AUGE[1]].y) / 2
            gs.append([round((lx + rx) / 2, 4), round((ly + ry) / 2, 4),
                       round(float(np.hypot((rx - lx) * w, (ry - ly) * h) / h), 4)])
        out.append([round(i / rate, 2), gs])
        i += 1
    p.wait()
    return out


def auswerten(name, m):
    alle = [g for _, gs in m["proben"] for g in gs]
    mit = sum(1 for _, gs in m["proben"] if gs)
    if not alle:
        print(f"{name}: kein Gesicht gefunden")
        return None
    # Personen nach x-Position trennen (links/rechts), je Person Median
    xs = np.array([g[0] for g in alle])
    anzahl = max(len(gs) for _, gs in m["proben"])
    personen = []
    if anzahl > 1:
        grenzen = np.quantile(xs, np.linspace(0, 1, anzahl + 1))
        for i in range(anzahl):
            sel = [g for g in alle if grenzen[i] <= g[0] <= grenzen[i + 1]]
            personen.append(sel)
    else:
        personen = [alle]
    werte = []
    for p in personen:
        ys = np.array([g[1] for g in p])
        ab = np.array([g[2] for g in p])
        werte.append({"x": float(np.median([g[0] for g in p])),
                      "augen_y": float(np.median(ys)),
                      "augen_y_p10": float(np.quantile(ys, .1)),
                      "augen_y_p90": float(np.quantile(ys, .9)),
                      "augenabstand": float(np.median(ab))})
    eyeline = float(np.mean([v["augen_y"] for v in werte]))
    print(f"\n{name}: {mit}/{len(m['proben'])} Bilder mit Gesicht, {len(werte)} Person(en)")
    for v in werte:
        print(f"  Person bei x={v['x']:.2f}: Augenhöhe {v['augen_y']*100:.1f} % "
              f"(10–90 %: {v['augen_y_p10']*100:.1f}–{v['augen_y_p90']*100:.1f}), "
              f"Augenabstand {v['augenabstand']*100:.1f} % der Bildhöhe")
    print(f"  → Eyeline der Kamera: {eyeline*100:.1f} %")
    return {"eyeline": eyeline, "personen": werte, "bilder": len(m["proben"]), "mit_gesicht": mit}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--step", type=float, default=5.0)
    ap.add_argument("--max-faces", type=int, default=3)
    ap.add_argument("--json")
    ap.add_argument("--reihe", type=float, default=0,
                    help="statt Stichproben: Zeitreihe mit N Bildern/s → --json")
    x = ap.parse_args()
    erg = {}
    if x.reihe:
        for v in x.videos:
            print(f"Zeitreihe {Path(v).name} …", file=sys.stderr, flush=True)
            erg[Path(v).name] = reihe(v, x.reihe, x.max_faces)
            print(f"  {len(erg[Path(v).name])} Bilder", file=sys.stderr, flush=True)
        Path(x.json).write_text(json.dumps(erg))
        return
    for v in x.videos:
        print(f"Messe {Path(v).name} …", file=sys.stderr, flush=True)
        erg[Path(v).name] = auswerten(Path(v).name, messe(v, x.step, x.max_faces))
    if x.json:
        Path(x.json).write_text(json.dumps(erg, indent=2))


if __name__ == "__main__":
    main()
