"""Aktivität je Spur — Stufe 1: gemeinsame Tabelle je Timeline-Bild bauen.

Versuch (19.11.2026, Folge 61): Statt „welches Mikro ist lauter?" (Vergleich, nötig
wegen Übersprechen) fragen wir auf der Analysespur „ist diese Spur aktiv?" — je Spur
einzeln. Diese Stufe rechnet nur Rohwerte auf eine gemeinsame Zeitachse:

  lv_orig[k]  Pegel (dBFS, RMS je Bild) des Original-Mikros von Person k
  lv_ana[k]   Pegel der Analysespur (`sprachspur.py --roh`) von Person k
  tempo[k]    Lippen-Tempo = gleitender Mittelwert |Δ innerer Lippenabstand|
              (0,33 s) aus der Mundaufzeichnung der Kamera von Person k
              (`analyse/mund_aktivitaet/aufzeichnen.py`, ganzes Video)
  engine      wer laut heutiger Sprechererkennung (base.edl) dran ist: 0/1, −1 sonst

Zeitachse = Timeline-Bilder von base.edl, Umrechnung wie in mouth_reactions.py
(calculate_reference_frames): Kamerabild = t + tzvf[cam], Mikrobild = abs0 + t − off_mic.

Aufruf: venv/bin/python3 analyse/aktivitaet/tabelle.py CONFIG.json
CONFIG: {"fps", "engine_dir" (mit base.edl + engine.log), "out",
         "persons": [{"name", "video", "cam_key", "mic", "mic_key", "ana", "mouth_npz"}, ...]}
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "modules" / "multicam_cutter"))
from add_reactions_to_edl import parse_resolve_edl, calculate_reference_frames  # noqa: E402
from mouth_reactions import _mic_db_per_frame, _rolling_nanmean  # noqa: E402


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    fps = float(cfg["fps"])
    ed = Path(cfg["engine_dir"])
    log = (ed / "engine.log").read_text(encoding="utf-8")
    offsets = json.loads(re.search(r'"sync_result", "offsets": (\{[^}]*\})', log).group(1))
    persons = cfg["persons"]

    events = parse_resolve_edl(str(ed / "base.edl"), fps)
    names = [Path(p["video"]).name for p in persons]
    _, tzvf = calculate_reference_frames(
        events, [{"name": n, "video": p["video"]} for n, p in zip(names, persons)], fps)
    T = max(e.record_out_frame for e in events)
    t = np.arange(T)
    engine = np.full(T, -1, np.int8)
    for e in events:
        if e.clip_name in names:
            engine[e.record_in_frame:e.record_out_frame] = names.index(e.clip_name)
    abs0 = tzvf[names[0]] + offsets.get(persons[0]["cam_key"], 0)

    def mic_levels(path, key):
        dbs = _mic_db_per_frame(path, fps)
        mi = abs0 + t - offsets.get(key, 0)
        ok = (mi >= 0) & (mi < len(dbs))
        a = np.full(T, np.nan, np.float32)
        a[ok] = dbs[mi[ok]]
        return a

    out = {"fps": fps, "engine": engine, "names": np.array([p["name"] for p in persons])}
    w = max(3, int(round(0.33 * fps)))
    for k, (p, n) in enumerate(zip(persons, names)):
        print(f"{p['name']}: Pegel Original …", flush=True)
        out[f"lv_orig{k}"] = mic_levels(p["mic"], p["mic_key"])
        print(f"{p['name']}: Pegel Analysespur …", flush=True)
        out[f"lv_ana{k}"] = mic_levels(p["ana"], p["mic_key"])
        r = np.load(p["mouth_npz"], allow_pickle=True)
        gap = r["gap_inner"]
        ci = t + tzvf[n]
        ok = (ci >= 0) & (ci < len(gap))
        g = np.full(T, np.nan, np.float32)
        g[ok] = gap[ci[ok]]
        out[f"gap{k}"] = g
        out[f"tempo{k}"] = _rolling_nanmean(np.abs(np.diff(g, prepend=np.nan)), w).astype(np.float32)
        print(f"  Gesicht in {np.isfinite(g).mean():.0%} der Timeline-Bilder", flush=True)
    np.savez_compressed(cfg["out"], **out)
    print(f"→ {cfg['out']}  ({T} Bilder, {T / fps / 60:.1f} min)")


if __name__ == "__main__":
    main()
