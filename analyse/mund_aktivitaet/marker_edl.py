"""Mund-Aktivitaet — Marker-EDL fuer Resolve ("Timeline-Marker aus EDL importieren").

Format wie eine von Resolve exportierte Marker-EDL:

    001  001  C  V  01:00:10;12  01:00:12;22  01:00:10;12  01:00:12;22
    Notiztext |C:ResolveColorPurple |M:Markername |D:69

IN/OUT stehen doppelt (Source = Record), `D` = Dauer in Bildern − 1 (so exportiert
Resolve selbst; 0 = Punkt-Marker mit IN = OUT).
Drop-Frame-Timecodes mit ';', sonst ':' — muss zum TC-Modus der Timeline passen.

Aufruf: venv/bin/python3 analyse/mund_aktivitaet/marker_edl.py MARKER.json AUSGABE.edl --aaf PRUEF.aaf

Start-TC, Drop-Frame und Bildrate kommen aus dem Timecode-Slot der AAF-Timeline —
die Marker-EDL hat damit garantiert denselben TC wie die AAF.
"""
import argparse
import json
from pathlib import Path

FARBE = {                      # Marker-Art → Resolve-Farbe + Kurzname
    "mund_und_mikro": ("ResolveColorGreen", "Mund + Mikro"),
    "nur_mund":       ("ResolveColorYellow", "Nur Mund"),
    "nur_mikro":      ("ResolveColorBlue", "Nur Mikro"),
}


def frames_to_tc(n: int, fps: float, df: bool) -> str:
    """Bildindex → Timecode. Drop-Frame nach SMPTE 12M (2 bzw. 4 Nummern je Minute
    ausgelassen, ausser jede 10. Minute)."""
    nom = int(round(fps))
    if df:
        drop = 4 if nom >= 59 else 2
        per_10min = nom * 600 - drop * 9
        per_min = nom * 60 - drop
        d, m = divmod(n, per_10min)
        if m > drop:
            n += drop * 9 * d + drop * ((m - drop) // per_min)
        else:
            n += drop * 9 * d
    f = n % nom
    s = (n // nom) % 60
    mi = (n // (nom * 60)) % 60
    h = n // (nom * 3600)
    sep = ";" if df else ":"
    return f"{h:02d}:{mi:02d}:{s:02d}{sep}{f:02d}"


def tc_to_frames(tc: str, fps: float, df: bool) -> int:
    p = tc.replace(";", ":").split(":")
    h, m, s, f = (int(x) for x in p)
    nom = int(round(fps))
    n = (h * 3600 + m * 60 + s) * nom + f
    if df:
        drop = 4 if nom >= 59 else 2
        tm = 60 * h + m
        n -= drop * (tm - tm // 10)
    return n


def aaf_timecode(path):
    """(start_frames, fps, drop) aus dem Timecode-Slot der Top-Level-Composition."""
    import aaf2
    with aaf2.open(str(path), "r") as f:
        for comp in f.content.toplevel():
            for slot in comp.slots:
                seg = slot.segment
                if type(seg).__name__ == "Timecode":
                    er = slot.edit_rate
                    return int(seg["Start"].value), float(er.numerator) / er.denominator, bool(seg["Drop"].value)
    raise RuntimeError(f"Kein Timecode-Slot in {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("marker")
    ap.add_argument("out")
    ap.add_argument("--aaf", required=True, help="AAF der Pruef-Timeline (TC-Quelle)")
    ap.add_argument("--title", default="Mund-Aktivitaet")
    a = ap.parse_args()

    start, a.fps, a.df = aaf_timecode(a.aaf)
    print(f"TC aus AAF: Start {frames_to_tc(start, a.fps, a.df)}, {a.fps:.3f} fps, "
          f"{'Drop-Frame' if a.df else 'Non-Drop'}")
    markers = json.loads(Path(a.marker).read_text(encoding="utf-8"))
    out = [f"TITLE: {a.title}", f"FCM: {'DROP FRAME' if a.df else 'NON-DROP FRAME'}", ""]
    for i, m in enumerate(sorted(markers, key=lambda x: x["start"]), 1):
        color, label = FARBE[m["art"]]
        s, e = start + m["start"], start + m["end"]
        tin = frames_to_tc(s, a.fps, a.df)
        tout = tin if e - s <= 1 else frames_to_tc(e, a.fps, a.df)   # Punkt-Marker: IN = OUT
        note = (m.get("notiz") or label).replace("|", "/").replace("\n", " ")
        out.append(f"{i:03d}  001  C  V  {tin}  {tout}  {tin}  {tout}")
        # Wie Resolves eigener Export (Beispiel: 10;12 → 12;22 = 70 Bilder, D:69):
        # OUT = IN + Dauer, D = Dauer − 1. Punkt-Marker: IN = OUT, D:0.
        out.append(f"{note} |C:{color} |M:{m['person']}: {label} |D:{max(0, e - s - 1)}")
        out.append("")
    Path(a.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(markers)} Marker → {a.out}")


if __name__ == "__main__":
    main()
