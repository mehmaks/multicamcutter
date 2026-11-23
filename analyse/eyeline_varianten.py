#!/usr/bin/env python3
"""Eyeline-Varianten auf eine fertige Mehrspur-XML anwenden (Test, nicht Teil der App).

Eingaben: XML aus dem Export (build_xml) + Zeitreihe aus eyeline_messung.py --reihe.
Je Variante wird jedem Video-Clip ein Basic-Motion-Filter (Skalierung + vert) gegeben:

  kamera     ein fester Wert je Kamera (Median über die ganze Folge)
  abschnitt  Wert je Sitz-Abschnitt (neuer Abschnitt erst, wenn sich die Augenhöhe
             dauerhaft verschiebt)
  clip       Wert je Clip (Median der Augenhöhe im Clip)

Ziel-Linie T für alle Varianten gleich: so gewählt, dass die größte nötige Skalierung
über alle Kameras minimal ist (Referenz darf mitwandern). XML-Einheiten (kalibriert
23.11.): vert 0.1 = 10 % der Bildhöhe nach unten, in Premiere und Resolve gleich.

Aufruf: venv/bin/python3 analyse/eyeline_varianten.py IN.xml REIHE.json OUTDIR [--max-scale 1.15]
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


def skal(T, y):
    """Mindest-Skalierung, um Augenhöhe y ohne Rand auf T zu bringen (um Bildmitte)."""
    if abs(T - y) < 1e-6:
        return 1.0
    return T / y if T > y else (1 - T) / (1 - y)


def transform(T, y, max_s):
    s = min(skal(T, y), max_s)
    t = T - 0.5 - s * (y - 0.5)
    lim = (s - 1) / 2
    return s, max(-lim, min(lim, t))


def augen_reihe(samples):
    """[(sek, augen_y)] — bei mehreren Gesichtern das größte (Close: die Person vorn)."""
    out = []
    for sek, gs in samples:
        if gs:
            g = max(gs, key=lambda g: g[2])
            out.append((sek, g[1]))
    return np.array(out)


def abschnitte(r, fenster=60, schwelle=0.015, dauer=30):
    """Sitz-Abschnitte: gleitender Median (fenster s); ein neuer Abschnitt beginnt, wenn der
    gleitende Median `dauer` s am Stück mehr als `schwelle` vom Abschnitts-Median abweicht.
    Rückgabe: Liste (start_s, ende_s, median_y)."""
    t, y = r[:, 0], r[:, 1]
    gl = np.array([np.median(y[(t >= s - fenster / 2) & (t <= s + fenster / 2)]) for s in t])
    grenzen, start, abw_seit = [0.0], 0, None
    for i in range(len(t)):
        ref = np.median(y[start:i + 1])
        if abs(gl[i] - ref) > schwelle:
            abw_seit = abw_seit if abw_seit is not None else i
            if t[i] - t[abw_seit] >= dauer:
                grenzen.append(t[abw_seit])
                start, abw_seit = abw_seit, None
        else:
            abw_seit = None
    grenzen.append(t[-1] + 1)
    return [(a, b, float(np.median(y[(t >= a) & (t < b)]))) for a, b in zip(grenzen, grenzen[1:])]


def clip_y(r, a, b, min_fenster=3.0):
    if b - a < min_fenster:
        m = (a + b) / 2
        a, b = m - min_fenster / 2, m + min_fenster / 2
    sel = r[(r[:, 0] >= a) & (r[:, 0] <= b), 1]
    return float(np.median(sel)) if len(sel) else None


def motion(scale, vert):
    return ET.fromstring(
        "<filter><effect><name>Basic Motion</name><effectid>basic</effectid>"
        "<effectcategory>motion</effectcategory><effecttype>motion</effecttype>"
        "<mediatype>video</mediatype><parameter><parameterid>scale</parameterid><name>Scale</name>"
        f"<valuemin>0</valuemin><valuemax>1000</valuemax><value>{scale * 100:.2f}</value></parameter>"
        "<parameter><parameterid>center</parameterid><name>Center</name>"
        f"<value><horiz>0</horiz><vert>{vert:.5f}</vert></value></parameter></effect></filter>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml")
    ap.add_argument("reihe")
    ap.add_argument("outdir")
    ap.add_argument("--max-scale", type=float, default=1.15)
    ap.add_argument("--fps", type=float, default=29.97)
    x = ap.parse_args()

    reihen = {k: augen_reihe(v) for k, v in json.loads(Path(x.reihe).read_text()).items()}
    med = {k: float(np.median(r[:, 1])) for k, r in reihen.items()}
    # Ziel-Linie: minimiert die größte nötige Skalierung
    kand = np.linspace(min(med.values()), max(med.values()), 401)
    T = float(min(kand, key=lambda T: max(skal(T, y) for y in med.values())))
    print("Augenhöhe je Kamera (Median):", {k: f"{v*100:.1f} %" for k, v in med.items()})
    print(f"Ziel-Linie T = {T*100:.2f} %")
    absch = {k: abschnitte(r) for k, r in reihen.items()}
    for k, a in absch.items():
        print(f"{k}: {len(a)} Abschnitt(e): " +
              ", ".join(f"{s/60:.0f}–{e/60:.0f} min {y*100:.1f} %" for s, e, y in a))

    Path(x.outdir).mkdir(parents=True, exist_ok=True)
    stamm = Path(x.xml).name.split(".")[0]
    for variante in ("kamera", "abschnitt", "clip"):
        baum = ET.parse(x.xml)
        wurzel = baum.getroot()
        namen = {f.get("id"): f.findtext("name") for f in wurzel.iter("file") if f.find("name") is not None}
        seq = wurzel.find("sequence")
        seq.find("name").text = f"{seq.findtext('name')} – Eyeline {variante}"
        stats = {}
        for track in seq.find("media").find("video").findall("track"):
            for ci in track.findall("clipitem"):
                f = ci.find("file")
                cam = namen.get(f.get("id")) if f is not None else None
                if cam not in reihen:
                    continue
                a, b = int(ci.findtext("in")) / x.fps, int(ci.findtext("out")) / x.fps
                if variante == "kamera":
                    y = med[cam]
                elif variante == "abschnitt":
                    m = (a + b) / 2
                    y = next((yy for s, e, yy in absch[cam] if s <= m < e), med[cam])
                else:
                    y = clip_y(reihen[cam], a, b) or med[cam]
                s, t = transform(T, y, x.max_scale)
                for alt in ci.findall("filter"):
                    ci.remove(alt)
                ci.append(motion(s, t))
                if ci.findtext("enabled") == "TRUE":
                    stats.setdefault(cam, []).append(s)
        ziel = Path(x.outdir) / f"{stamm} Eyeline {variante}.xml"
        text = ET.tostring(wurzel, encoding="unicode")
        ziel.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + text, encoding="utf-8")
        print(f"\n{variante}: {ziel.name}")
        for cam, ss in stats.items():
            ss = np.array(ss) * 100
            print(f"  {cam}: Skalierung {ss.min():.1f}–{ss.max():.1f} % (Median {np.median(ss):.1f} %), "
                  f"{len(ss)} aktive Clips")


if __name__ == "__main__":
    main()
