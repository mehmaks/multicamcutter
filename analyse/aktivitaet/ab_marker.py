"""A/B-Vergleich zweier Schnitte derselben Folge → Marker-EDL nur an den Unterschieden.

A und B müssen dieselbe Grundstruktur haben (gleiche base.edl, kein Pause-Trim), dann
sind die Record-Positionen direkt vergleichbar. Verglichen werden die Einwurf-Schnitte
(Grund `reaction_speaking_reaction` in final.colors.json):
  grün = nur in B, rot = nur in A (an A's Position). Gemeinsame werden nur gezählt.

Aufruf: venv/bin/python3 analyse/aktivitaet/ab_marker.py A_WORKDIR B_WORKDIR AUSGABE.edl --aaf B.aaf
(WORKDIR = Ordner mit final.edl + final.colors.json)
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mund_aktivitaet"))
from marker_edl import frames_to_tc, aaf_timecode  # noqa: E402

EV = re.compile(r"^\d+\s+\S+\s+V\s+C\s+\S+\s+\S+\s+(\d\d:\d\d:\d\d:\d\d)\s+(\d\d:\d\d:\d\d:\d\d)")


def tc(s, nom):
    h, m, sec, f = map(int, s.split(":"))
    return ((h * 60 + m) * 60 + sec) * nom + f


def speaking_cuts(wd, nom, gruende=("reaction_speaking_reaction",)):
    lines = (Path(wd) / "final.edl").read_text(encoding="utf-8").splitlines()
    evs = [(tc(m.group(1), nom), tc(m.group(2), nom), lines[i + 1].split(": ", 1)[-1].strip())
           for i, l in enumerate(lines) if (m := EV.match(l))]
    reasons = [c.get("reason") for c in json.loads((Path(wd) / "final.colors.json").read_text())]
    assert len(evs) == len(reasons), f"{wd}: {len(evs)} Events, {len(reasons)} Gründe"
    return [(s, e, clip, r) for (s, e, clip), r in zip(evs, reasons) if r in gruende]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("out")
    ap.add_argument("--aaf", required=True)
    ap.add_argument("--namen", default="", help="clip=Name,clip=Name")
    ap.add_argument("--gruende", default="reaction_speaking_reaction",
                    help="Komma-Liste der Cutaway-Gründe, z. B. reaction_nodding,reaction_speaking_reaction")
    ap.add_argument("--label-a", default="Nur A (heute)")
    ap.add_argument("--label-b", default="Nur B (Analysespur)")
    x = ap.parse_args()
    start, fps, df = aaf_timecode(x.aaf)
    nom = int(round(fps))
    namen = dict(p.split("=") for p in x.namen.split(",") if p)
    gr = tuple(g.strip() for g in x.gruende.split(",") if g.strip())
    A, B = speaking_cuts(x.a, nom, gr), speaking_cuts(x.b, nom, gr)

    def overlaps(c, other):
        return any(c[2] == o[2] and c[0] < o[1] and o[0] < c[1] for o in other)

    art = {"reaction_speaking_reaction": "Einwurf", "reaction_nodding": "Nicken", "reaction_pause": "Pause"}
    marker = [(c, "ResolveColorGreen", x.label_b) for c in B if not overlaps(c, A)]
    marker += [(c, "ResolveColorRed", x.label_a) for c in A if not overlaps(c, B)]
    shared = sum(1 for c in B if overlaps(c, A))
    out = ["TITLE: A-B Einwuerfe", f"FCM: {'DROP FRAME' if df else 'NON-DROP FRAME'}", ""]
    for i, ((s, e, clip, grund), col, label) in enumerate(sorted(marker, key=lambda m: m[0][0]), 1):
        tin, tout = frames_to_tc(start + s, fps, df), frames_to_tc(start + e, fps, df)
        who = namen.get(clip, clip)
        out += [f"{i:03d}  001  C  V  {tin}  {tout}  {tin}  {tout}",
                f"{art.get(grund, grund)} {who} |C:{col} |M:{label}: {art.get(grund, grund)} {who} |D:{max(0, e - s - 1)}", ""]
    Path(x.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Cutaways: A {len(A)}, B {len(B)}, gemeinsam {shared}; Marker: "
          f"{sum(1 for m in marker if m[2] == x.label_b)} {x.label_b} (grün), "
          f"{sum(1 for m in marker if m[2] == x.label_a)} {x.label_a} (rot) → {x.out}")


if __name__ == "__main__":
    main()
