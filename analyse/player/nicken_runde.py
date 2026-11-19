"""Analyse-Player — Runde „Nick-Muster": je erkanntem Nicker ein Prüf-Marker mit Clip.

Frage (User, 19.11.): Welche Nick-Muster liefern die meisten Fehlalarme (Trinken statt
Nicken)? Jeder Nicker in `<cam>_reactions.json` trägt sein Muster (`pattern`). Je Nicker:
Marker (Art = Muster, Notiz = Konfidenz) + kurzer Clip der Kamera der nickenden Person
(3 s davor bis 4 s danach, 640 px), synchron zum Ton im Player. Bewertung:
nickt / trinkt / sonstiges.

Stichprobe: je Muster höchstens --max-je-muster Nicker (zufällig, fester Startwert →
reproduzierbar, nicht nach Konfidenz verzerrt); 0 = alle.

Aufruf: venv/bin/python3 analyse/player/nicken_runde.py TESTORDNER [--max-je-muster 50]
  erwartet: TESTORDNER/lauf.json, player.json, player/ (Ton), nicken/ (Engine-Lauf mit
  Nick-Analyse: *_reactions.json + base.edl)
  schreibt: TESTORDNER/player_nicken/
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "modules" / "multicam_cutter"))
from add_reactions_to_edl import parse_resolve_edl, calculate_reference_frames  # noqa: E402

VOR_S, NACH_S = 3.0, 4.0
FARBEN = {"oscillation": "#3ecf7a", "slow_oscillation": "#c792ea", "strong_oscillation": "#ff7eb6"}
NAMEN = {"oscillation": "Muster: oscillation", "slow_oscillation": "Muster: slow_oscillation",
         "strong_oscillation": "Muster: strong_oscillation"}


def lade_reaktionen(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d.get("reactions", d) if isinstance(d, dict) else d


def clip(video, t0, dauer, out):
    if out.exists() and out.stat().st_size > 0:
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t0):.3f}", "-i", str(video),
                    "-t", f"{dauer:.3f}", "-vf", "scale=640:-2", "-an", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(out)], check=True)


def main():
    import argparse
    import random
    ap = argparse.ArgumentParser()
    ap.add_argument("test")
    ap.add_argument("--max-je-muster", type=int, default=50)
    a = ap.parse_args()
    T = Path(a.test)
    cfg = json.loads((T / "lauf.json").read_text(encoding="utf-8"))
    fps = float(cfg["fps"])
    P = cfg["persons"]
    names = [Path(p["video"]).name for p in P]
    N = T / "nicken"
    _, tz = calculate_reference_frames(parse_resolve_edl(str(N / "base.edl"), fps),
                                       [{"name": n, "video": p["video"]} for n, p in zip(names, P)], fps)
    out = T / "player_nicken"
    (out / "clips").mkdir(parents=True, exist_ok=True)

    marker, jobs = [], []
    for k, (p, n) in enumerate(zip(P, names)):
        rj = N / f"{Path(n).stem}_reactions.json"
        if not rj.exists():
            print(f"  ⚠️  keine Reaktionen für {n}")
            continue
        for r in lade_reaktionen(rj):
            if r.get("type") != "nodding":
                continue
            f = int(r["frame"])
            ende = max(int(r.get("peak_frame", f)), f) + int(r.get("tail_frames", 0))
            start, end = f - tz[n], max(ende - tz[n], f - tz[n] + int(fps))
            pat = r.get("pattern") or "?"
            mid = f"nod{k}_{f}"
            c0 = start - int(VOR_S * fps)
            marker.append({"id": mid, "start": int(start), "end": int(end), "person": k, "art": pat,
                           "notiz": f"{NAMEN.get(pat, pat)} · Konfidenz {float(r.get('confidence', 0)):.2f}",
                           "konfidenz": round(float(r.get("confidence", 0)), 3),
                           "clip": f"clips/{mid}.mp4", "clip_start": int(c0)})
            jobs.append((p["video"], (c0 + tz[n]) / fps, VOR_S + NACH_S + (end - start) / fps,
                         out / "clips" / f"{mid}.mp4"))
    from collections import Counter
    gesamt = Counter(m["art"] for m in marker)
    if a.max_je_muster:
        rng = random.Random(19112026)
        wahl = set()
        for pat in gesamt:
            ids = [m["id"] for m in marker if m["art"] == pat]
            wahl |= set(ids if len(ids) <= a.max_je_muster else rng.sample(ids, a.max_je_muster))
        jobs = [j for j, m in zip(jobs, marker) if m["id"] in wahl]
        marker = [m for m in marker if m["id"] in wahl]
    print(f"erkannt je Muster: {dict(gesamt)} → Stichprobe {dict(Counter(m['art'] for m in marker))}")
    print(f"{len(marker)} Nicker — Clips schneiden …", flush=True)
    with ThreadPoolExecutor(6) as ex:
        for i, _ in enumerate(ex.map(lambda j: clip(*j), jobs), 1):
            if i % 25 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)

    mj = {"marker": marker, "warum": False,
          "bewertungen": [["nickt", "✓ Nickt", "#3ecf7a"], ["trinkt", "🥤 Trinkt", "#ff9b3d"],
                          ["sonstiges", "? Sonstiges", "#f2c94c"]],
          "arten": {k: [NAMEN[k], v] for k, v in FARBEN.items()}}
    (out / "marker_runde.json").write_text(json.dumps(mj, ensure_ascii=False), encoding="utf-8")
    pc = json.loads((T / "player.json").read_text(encoding="utf-8"))
    pc["titel"] = pc.get("titel", T.parent.name) + " · Nick-Muster"
    (T / "player_nicken.json").write_text(json.dumps(pc, indent=1, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([str(ROOT / "venv/bin/python3"), str(ROOT / "analyse/player/bauen.py"),
                        str(T / "player_nicken.json"), str(out), "--marker-json", str(out / "marker_runde.json"),
                        "--ton-von", str(T / "player"),
                        "--hinweis", "Nick-Muster-Test: Ist das ein Nicken — oder Trinken / etwas anderes? "
                                     "Rechts oben das Bild der nickenden Person (3 s vorher bis 4 s nachher)."],
                       capture_output=True, text=True)
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-800:])
    (out / "stichprobe.json").write_text(json.dumps({"erkannt_je_muster": dict(gesamt),
                                                     "max_je_muster": a.max_je_muster}), encoding="utf-8")


if __name__ == "__main__":
    main()
