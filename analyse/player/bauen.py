"""Analyse-Player — Sitzungsordner bauen (Daten + Ton) für server.py / player.html.

Legt in AUSGABE an:
  manifest.json   Zeitachse, Personen, Spuren-Index, Ereignisse, Prüf-Marker
  kurven.bin      Float32-Kurven je Timeline-Bild (Index in manifest["kurven"])
  ton_original.m4a / ton_analysespur.m4a   Stereo: links Person 0, rechts Person 1,
                  Bild 0 der Timeline = Sekunde 0 der Datei
Prüf-Marker = Einwurf-Schnitte, die nur in A oder nur in B vorkommen (aus den
Schnitten ohne Schnittregeln). Bewertungen schreibt der Player nach labels.json.

Aufruf: venv/bin/python3 analyse/player/bauen.py CONFIG.json AUSGABE [--ohne-ton]
CONFIG: lauf.json aus analyse/aktivitaet (+ "a_schnitt", "b_schnitt", "aaf")
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analyse" / "aktivitaet"))
sys.path.insert(0, str(ROOT / "analyse" / "mund_aktivitaet"))
sys.path.insert(0, str(ROOT / "modules" / "multicam_cutter"))
from einwurf_b import detect  # noqa: E402
from marker_edl import aaf_timecode  # noqa: E402
from add_reactions_to_edl import parse_resolve_edl, calculate_reference_frames  # noqa: E402

EV = re.compile(r"^\d+\s+\S+\s+V\s+C\s+\S+\s+\S+\s+(\d\d:\d\d:\d\d:\d\d)\s+(\d\d:\d\d:\d\d:\d\d)")


def tc(s, nom):
    h, m, sec, f = map(int, s.split(":"))
    return ((h * 60 + m) * 60 + sec) * nom + f


def schnitt(wd, nom, names):
    lines = (Path(wd) / "final.edl").read_text(encoding="utf-8").splitlines()
    evs = [(tc(m.group(1), nom), tc(m.group(2), nom), lines[i + 1].split(": ", 1)[-1].strip())
           for i, l in enumerate(lines) if (m := EV.match(l))]
    reasons = [c.get("reason") for c in json.loads((Path(wd) / "final.colors.json").read_text())]
    return [[s, e, names.index(c) if c in names else -1, r] for (s, e, c), r in zip(evs, reasons)]


def a_debug(path, n, persons_cam):
    """A-Erkennung (App, Original-Spur) aus speaking_debug.json → Kurven je Person + Ereignisse."""
    D = json.loads(Path(path).read_text(encoding="utf-8"))
    fps, w = D["fps"], D["window_s"]
    cur = {k: {c: np.full(n, np.nan, np.float32) for c in ("db", "base", "thr", "freeze")} for k in (0, 1)}
    ev = {k: [] for k in (0, 1)}
    rise = D["params"]["rise_db"]
    for s in D["segments"]:
        if "db" not in s:
            continue
        k = persons_cam.index(s["reaction_cam"])
        f0 = s["start_edl_frame"]
        idx = np.arange(len(s["db"]))
        fr = np.round(f0 + idx * w * fps).astype(int)
        # auf Bilder auffüllen: jedes Bild bekommt den Wert seines 50-ms-Fensters
        for j in range(len(fr)):
            a, b = fr[j], (fr[j + 1] if j + 1 < len(fr) else fr[j] + int(round(w * fps)))
            a, b = max(0, a), min(n, b)
            if a >= b:
                continue
            cur[k]["db"][a:b] = s["db"][j]
            cur[k]["base"][a:b] = s["baseline"][j]
            cur[k]["thr"][a:b] = s["baseline"][j] + rise
            cur[k]["freeze"][a:b] = s["freeze"][j]
        for art, lst in (("erkannt", s["bursts"]), ("verworfen", s["rejected"]), ("regel_a", s["fp_dropped"])):
            for x in lst:
                a = int(round(f0 + x["start_s"] * fps))
                b = int(round(f0 + x["end_s"] * fps))
                grund = {"erkannt": "erkannt", "verworfen": "zu kurz" if "min_duration" in x.get("reason", "")
                         else x.get("reason", "?"), "regel_a": "Regel A (Gleichtakt)"}[art]
                ev[k].append([a, b, art, grund, round(float(x.get("conf", 0)), 2)])
    return cur, ev, D


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("out")
    ap.add_argument("--ohne-ton", action="store_true")
    ap.add_argument("--neu-gegen", help="manifest.json einer früheren Runde: Prüf-Marker = nur die "
                    "B-Erkennungen, die dort noch nicht vorkamen; Ton wird per Hardlink übernommen")
    ap.add_argument("--hinweis", default="", help="Text, der bei jedem Marker als Hintergrund steht")
    x = ap.parse_args()
    cfg = json.loads(Path(x.config).read_text(encoding="utf-8"))
    out = Path(x.out)
    out.mkdir(parents=True, exist_ok=True)
    d = np.load(cfg["tabelle"], allow_pickle=True)
    fps = float(d["fps"])
    nom = int(round(fps))
    eng = d["engine"]
    n = len(eng)
    persons = cfg["persons"]
    names = [Path(p["video"]).name for p in persons]
    start, _, df = aaf_timecode(cfg["aaf"])

    kurven, blobs = [], []

    def add(name, arr):
        a = np.asarray(arr, np.float32)
        a = np.where(np.isfinite(a), a, np.nan).astype(np.float32)
        kurven.append({"name": name, "offset": sum(b.size for b in blobs)})
        blobs.append(a)

    b_res, b_params = detect(d)
    a_cur, a_ev, a_D = a_debug(Path(cfg["a_dir"]) / "speaking_debug.json", n, ["CAM1", "CAM2"])
    personen = []
    for k, p in enumerate(persons):
        ana = np.maximum(d[f"lv_ana{k}"], -110)
        add(f"ana{k}", ana)
        add(f"orig{k}", np.maximum(d[f"lv_orig{k}"], -110))
        add(f"b_umg{k}", b_res[k]["umgebung"])
        add(f"b_erw{k}", b_res[k]["erwartet"])
        add(f"b_roh{k}", b_res[k]["roh"])
        if k == 0:
            add("puffer", b_res[0]["puffer"])
        for c in ("db", "base", "thr", "freeze"):
            add(f"a_{c}{k}", a_cur[k][c])
        adb = a_cur[k]["db"][np.isfinite(a_cur[k]["db"])]
        personen.append({
            "name": p["name"], "kamera": names[k],
            "b_leise": b_res[k]["leise"], "b_gain_db": b_res[k]["gain_db"],
            "b_sprache_db": b_res[k]["sprache_db"],
            "bereich_ana": [float(np.percentile(ana, 1)) - 3, float(np.percentile(ana, 99.9)) + 3],
            "bereich_a": [float(np.percentile(adb, 1)) - 3, float(np.percentile(adb, 99.9)) + 3],
            "b_events": [[int(s), int(e)] for s, e in b_res[k]["events"]],
            "b_verworfen": [[int(s), int(e), r] for s, e, r in b_res[k]["rejected"]],
            "a_events": a_ev[k],
        })
    (out / "kurven.bin").write_bytes(np.concatenate(blobs).tobytes())

    A = schnitt(cfg["a_schnitt"], nom, names)
    B = schnitt(cfg["b_schnitt"], nom, names)
    sp = lambda L: [c for c in L if c[3] == "reaction_speaking_reaction"]  # noqa: E731

    def overlaps(c, other):
        return any(c[2] == o[2] and c[0] < o[1] and o[0] < c[1] for o in other)

    marker = [{"id": f"b{c[0]}_{c[2]}", "start": c[0], "end": c[1], "person": c[2], "art": "nur_b"}
              for c in sp(B) if not overlaps(c, sp(A))]
    marker += [{"id": f"a{c[0]}_{c[2]}", "start": c[0], "end": c[1], "person": c[2], "art": "nur_a"}
               for c in sp(A) if not overlaps(c, sp(B))]
    if x.neu_gegen:
        alt = json.loads(Path(x.neu_gegen).read_text(encoding="utf-8"))
        marker = []
        for k, P in enumerate(personen):
            prev = alt["personen"][k]["b_events"]
            for s, e in P["b_events"]:
                if not any(ps < e + 15 and pe > s - 15 for ps, pe in prev):
                    marker.append({"id": f"n{s}_{k}", "start": max(0, s - 15), "end": e, "person": k, "art": "neu"})
    marker.sort(key=lambda m: m["start"])

    # Sprecher als Läufe
    ch = np.flatnonzero(np.diff(eng) != 0) + 1
    bnd = np.concatenate([[0], ch, [n]])
    sprecher = [[int(s), int(e), int(eng[s])] for s, e in zip(bnd[:-1], bnd[1:])]

    manifest = {
        "titel": cfg.get("titel", Path(cfg["folder"]).name), "fps": fps, "n": n,
        "start_tc": start, "drop_frame": bool(df), "personen": personen, "kurven": kurven,
        "sprecher": sprecher, "schnitt_a": A, "schnitt_b": B, "marker": marker,
        "b_params": b_params, "a_params": a_D["params"],
        "ton": {"original": "ton_original.m4a", "analysespur": "ton_analysespur.m4a"},
        "hinweis": x.hinweis,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    print(f"{len(marker)} Prüf-Marker, {len(kurven)} Kurven → {out}")

    if x.neu_gegen:
        import os
        for f in ("ton_original.m4a", "ton_analysespur.m4a"):
            src, dst = Path(x.neu_gegen).parent / f, out / f
            if src.exists() and not dst.exists():
                os.link(src, dst)
        return
    if x.ohne_ton:
        return
    # Ton: Timeline-Bild 0 ↔ Mikrobild abs0 − off_mic (wie tabelle.py)
    log = (Path(cfg["a_dir"]) / "engine.log")
    log = log.read_text(encoding="utf-8") if log.exists() else \
        (Path(cfg["tabelle"]).parent / "original" / "engine.log").read_text(encoding="utf-8")
    offsets = json.loads(re.search(r'"sync_result", "offsets": (\{[^}]*\})', log).group(1))
    events = parse_resolve_edl(str(Path(cfg["a_dir"]) / "base.edl"), fps)
    _, tzvf = calculate_reference_frames(
        events, [{"name": nm, "video": p["video"]} for nm, p in zip(names, persons)], fps)
    abs0 = tzvf[names[0]] + offsets.get(persons[0]["cam_key"], 0)
    for art, key in (("original", "mic"), ("analysespur", "ana")):
        cmd = ["ffmpeg", "-y", "-v", "error"]
        filt = []
        for k, p in enumerate(persons):
            t0 = (abs0 - offsets.get(p["mic_key"], 0)) / fps
            lv = d[f"lv_orig{k}"] if art == "original" else d[f"lv_ana{k}"]
            gain = -12 - float(np.nanpercentile(lv[eng == k], 99))   # laute Sprache → ca. −12 dBFS RMS
            if t0 >= 0:
                cmd += ["-ss", f"{t0:.4f}", "-i", p[key]]
                filt.append(f"[{k}:a]aformat=channel_layouts=mono,volume={gain:.1f}dB[c{k}]")
            else:
                cmd += ["-i", p[key]]
                filt.append(f"[{k}:a]aformat=channel_layouts=mono,adelay={-t0 * 1000:.0f},"
                            f"volume={gain:.1f}dB[c{k}]")
        filt.append("[c0][c1]join=inputs=2:channel_layout=stereo,alimiter=limit=0.95[o]")
        cmd += ["-filter_complex", ";".join(filt), "-map", "[o]", "-t", f"{n / fps:.3f}",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", str(out / f"ton_{art}.m4a")]
        print(f"Ton {art} …", flush=True)
        subprocess.run(cmd, check=True)
    print("fertig")


if __name__ == "__main__":
    main()
