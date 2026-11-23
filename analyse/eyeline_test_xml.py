#!/usr/bin/env python3
"""Test-XML für den Eyeline-Abgleich (nur Bild, zwei Kameras, nicht synchron).

Abschnitt 1 – Kalibrierung: dieselbe Kamera mit bekannten Basic-Motion-Werten
(Mitte 0/0, vert +0.1, horiz +0.1, Skalierung 120 %). Daran lesen wir ab, wie Premiere
und Resolve <center> deuten (Einheit, Richtung).

Abschnitt 2 – Eyeline: abwechselnd Referenz-Kamera (unverändert) und angepasste Kamera.
V1 = mit Anpassung, V2 = dieselben Clips ohne Anpassung (deaktiviert) zum Umschalten.

Annahme für Abschnitt 2 (wird durch die Kalibrierung geprüft): vert in Bildhöhen-
Anteilen, positiv = nach unten.

Aufruf: venv/bin/python3 analyse/eyeline_test_xml.py REF.MP4 ANPASS.MP4 OUT.xml
        --ref-y 0.335 --anpass-y 0.309 [--start-min 10] [--paare 10] [--clip-s 6]
"""
import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules/multicam_cutter"))
import build_xml as bx  # noqa: E402


def transform(ref_y, y):
    """Skalierung s (≥1) und Verschiebung t (Bildhöhen-Anteil, + = runter), sodass die
    Augenlinie y auf ref_y landet, ohne Rand. Skalierung um die Bildmitte:
    y' = 0.5 + s·(y−0.5) + t, Rand frei solange |t| ≤ (s−1)/2.
    Runter (ref_y > y): s ≥ ref_y/y (Oberkante bleibt bündig);
    rauf  (ref_y < y): s ≥ (1−ref_y)/(1−y) (Unterkante bündig)."""
    if abs(ref_y - y) < 1e-4:
        return 1.0, 0.0
    s = ref_y / y if ref_y > y else (1 - ref_y) / (1 - y)
    t = ref_y - 0.5 - s * (y - 0.5)
    return s, t


def motion(scale=None, horiz=0.0, vert=0.0):
    p = ""
    if scale is not None:
        p += ("<parameter><parameterid>scale</parameterid><name>Scale</name><valuemin>0"
              f"</valuemin><valuemax>1000</valuemax><value>{scale:.2f}</value></parameter>")
    p += ("<parameter><parameterid>center</parameterid><name>Center</name>"
          f"<value><horiz>{horiz:.5f}</horiz><vert>{vert:.5f}</vert></value></parameter>")
    return ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid>"
            "<effectcategory>motion</effectcategory><effecttype>motion</effecttype>"
            f"<mediatype>video</mediatype>{p}</effect></filter>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("anpass")
    ap.add_argument("out")
    ap.add_argument("--ref-y", type=float, required=True)
    ap.add_argument("--anpass-y", type=float, required=True)
    ap.add_argument("--fps", type=float, default=29.97)
    ap.add_argument("--start-min", type=float, default=10)
    ap.add_argument("--paare", type=int, default=10)
    ap.add_argument("--clip-s", type=float, default=6)
    x = ap.parse_args()

    fps = x.fps
    fi = int(round(fps))
    ntsc = "TRUE" if abs(fps - fi) > 0.01 else "FALSE"
    rate = f"<rate><timebase>{fi}</timebase><ntsc>{ntsc}</ntsc></rate>"
    df = bx._detect_dropframe(x.ref)
    if df is None:
        df = bx._is_dropframe(fps)
    w, h = bx._probe_video_info(x.ref)

    dateien = {}

    def datei(p):
        if p in dateien:
            return f'<file id="{dateien[p][0]}"/>', dateien[p][1]
        fid = f"file-{len(dateien) + 1}"
        dur = bx._probe_duration_frames(p, fps)
        tc = bx._probe_embedded_tc_frames(p, fps, dropframe=df)
        vw, vh = bx._probe_video_info(p)
        dateien[p] = (fid, dur)
        return (f'<file id="{fid}"><name>{escape(Path(p).name)}</name><pathurl>{bx._url(p)}</pathurl>'
                f"{rate}<duration>{dur}</duration><timecode>{rate}<string>{bx._tc_string(tc, fi, df)}"
                f"</string><frame>{tc}</frame><displayformat>{'DF' if df else 'NDF'}</displayformat>"
                f"<reel><name>{escape(Path(p).stem)}</name></reel></timecode><media><video>"
                f"<samplecharacteristics>{rate}<width>{vw}</width><height>{vh}</height>"
                f"</samplecharacteristics></video></media></file>"), dur

    n = {"i": 0}

    def clip(p, name, start, src_in, laenge, filt="", enabled=True):
        n["i"] += 1
        fdef, dur = datei(p)
        return (f'<clipitem id="clip-{n["i"]}"><name>{escape(name)}</name>'
                f"<enabled>{'TRUE' if enabled else 'FALSE'}</enabled><duration>{dur}</duration>{rate}"
                f"<start>{start}</start><end>{start + laenge}</end><in>{src_in}</in>"
                f"<out>{src_in + laenge}</out>{fdef}{filt}</clipitem>")

    s, t = transform(x.ref_y, x.anpass_y)
    print(f"Anpassung {Path(x.anpass).name}: Skalierung {s*100:.1f} %, "
          f"Verschiebung {t*100:+.2f} % der Bildhöhe ({t*h:+.0f} px)")

    lang = int(x.clip_s * fps)
    src = int(x.start_min * 60 * fps)
    v1, v2 = [], []
    rec = 0
    kal = [("KAL Mitte 0/0", motion(100, 0, 0)),
           ("KAL vert +0.1", motion(100, 0, 0.1)),
           ("KAL horiz +0.1", motion(100, 0.1, 0)),
           ("KAL Skalierung 120", motion(120, 0, 0))]
    for name, f in kal:
        v1.append(clip(x.anpass, name, rec, src, lang, f))
        rec += lang
    for i in range(x.paare):
        a = src + i * 2 * lang
        v1.append(clip(x.ref, "Referenz", rec, a, lang))
        v2.append(clip(x.ref, "Referenz", rec, a, lang, enabled=False))
        rec += lang
        v1.append(clip(x.anpass, f"Eyeline {s*100:.1f} % / vert {t:+.4f}", rec, a + lang, lang,
                       motion(s * 100, 0, t)))
        v2.append(clip(x.anpass, "Original", rec, a + lang, lang, enabled=False))
        rec += lang

    titel = "Eyeline-Test"
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
           f'<xmeml version="4"><sequence id="sequence-1"><name>{titel}</name><duration>{rec}</duration>'
           f"{rate}<timecode>{rate}<string>{bx._tc_string(0, fi, df)}</string><frame>0</frame>"
           f"<displayformat>{'DF' if df else 'NDF'}</displayformat></timecode><media><video><format>"
           f"<samplecharacteristics>{rate}<width>{w}</width><height>{h}</height></samplecharacteristics>"
           f"</format><track>{''.join(v1)}</track><track>{''.join(v2)}</track></video></media>"
           "</sequence></xmeml>\n")
    Path(x.out).write_text(xml, encoding="utf-8")
    print(f"✓ {x.out} ({rec / fps:.0f} s)")


if __name__ == "__main__":
    main()
