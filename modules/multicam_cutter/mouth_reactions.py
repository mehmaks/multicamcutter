"""Sprachreaktionen aus Mundbewegung + eigenem Mikro („Mund + Mikro", Beta).

Zusaetzliche QUELLE fuer Sprachreaktionen (kein Filter): Spricht die gerade
NICHT aktive Person einen kurzen Einwurf, bewegt sich ihr Mund UND ihr eigenes
Mikro schlaegt ueber das uebliche Uebersprechen hinaus aus. Solche Einwuerfe
werden als `speaking_reaction` in die vorhandene `<cam>_speaking.json`
eingetragen; PASS 2 behandelt sie wie Audio-Erkennungen (gleiche Abstandsregeln).
Audio-Erkennungen, die der Mund bestaetigt, werden nur markiert, nicht doppelt.

Herleitung + Validierung: apps/multicam-cutter/brain/TODOs.md → „Sprachreaktionen
per Mundbewegung" (Folge 61/62: Mund + Mikro ausserhalb des Deadbands 45/45 echte
Einwuerfe; die App erkannte davon vorher nur ~1/4).

Datenquellen:
- Lippenabstand je Bild aus der Gesichtsanalyse (`<cam>_mouth.npz`, geschrieben
  von video_reaction_analyzer bei `--mouth-out`; nur Off-Sektionen = Zuhoeren)
- base.edl (wer spricht), Mikrospuren (Pegel je Bild, gestreamt via ffmpeg)

Parameter (params): mouth_deadband_s (1.0), mouth_window_s (0.33),
mouth_listen_pctl (93 — Schwelle = Perzentil des reinen Zuhoerens; entspricht
in 61/62 dem 91.–96. Perzentil der frueheren Sprech-Kalibrierung).
"""
import json
import subprocess
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from add_reactions_to_edl import parse_resolve_edl, calculate_reference_frames
from frame_utils import frames_to_timecode


def _mic_db_per_frame(wav, fps, sr=16000, block_s=20):
    """Pegel (dBFS, RMS) je Videobild — gestreamt, damit eine 2-h-Spur nicht
    komplett im Speicher liegt. ffmpeg dekodiert jede Bit-Tiefe korrekt."""
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1",
                             "-ar", str(sr), "-f", "f32le", "-"], stdout=subprocess.PIPE)
    spf = sr / fps
    out, buf, base, k = [], np.zeros(0, np.float32), 0, 0   # base = Sample-Index von buf[0]
    while True:
        raw = proc.stdout.read(int(sr * block_s) * 4)
        if raw:
            buf = np.concatenate([buf, np.frombuffer(raw, np.float32)])
        # alle Bilder abarbeiten, die vollstaendig im Puffer liegen
        while True:
            s, e = int(round(k * spf)), int(round((k + 1) * spf))
            if e - base > len(buf):
                break
            seg = buf[s - base:e - base].astype(np.float64)
            out.append(10 * np.log10(np.mean(seg * seg) + 1e-12))
            k += 1
        drop = int(round(k * spf)) - base
        if drop > 0:
            buf, base = buf[drop:], base + drop
        if not raw:
            break
    proc.wait()
    return np.array(out, np.float32)


def _rolling_nanmean(x, w):
    pad = w // 2
    xp = np.concatenate([np.full(pad, np.nan), x, np.full(w - 1 - pad, np.nan)])
    v = sliding_window_view(xp, w)
    with np.errstate(all="ignore"):
        cnt = np.sum(np.isfinite(v), axis=1)
        s = np.nansum(v, axis=1)
    return np.where(cnt > 0, s / np.maximum(cnt, 1), np.nan)


def _runs(mask, min_len):
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    return [(int(s), int(e)) for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0])
            if e - s >= min_len]


def add_mouth_reactions(base_edl, cams, offsets, fps, params, decision_log=None):
    """cams: genau 2 Eintraege {video, cam_key ('CAM1'), mic, mic_key ('MIC1'),
    mouth_npz, speaking_json}. Ergaenzt/markiert in den speaking_json-Dateien.
    Gibt eine Zusammenfassung je Kamera zurueck."""
    deadband_s = float(params.get("mouth_deadband_s", 1.0))
    window_s = float(params.get("mouth_window_s", 0.33))
    pctl = float(params.get("mouth_listen_pctl", 93))
    max_dur = float(params.get("speaking_max_dur", 2.5))

    events = parse_resolve_edl(str(base_edl), fps)
    names = [Path(c["video"]).name for c in cams]
    _, tzvf = calculate_reference_frames(
        events, [{"name": n, "video": c["video"]} for n, c in zip(names, cams)], fps)
    if any(n not in tzvf for n in names):
        print("  ⚠️  Mund-Reaktionen: Kamera ohne Bezug in base.edl — uebersprungen")
        return {}
    T = max(e.record_out_frame for e in events)
    t = np.arange(T)

    # Wer spricht (laut base.edl): Index in cams, -1 = unbekannt/Totale
    active = np.full(T, -1, np.int16)
    for e in events:
        if e.clip_name in names:
            active[e.record_in_frame:e.record_out_frame] = names.index(e.clip_name)
    sw = np.where((active[1:] != active[:-1]) & (active[1:] >= 0) & (active[:-1] >= 0))[0] + 1
    near_switch = np.zeros(T, bool)
    db = int(round(deadband_s * fps))
    for i in sw:
        near_switch[max(0, i - db):i + db] = True

    # abs = Kamerabild + Kamera-Offset; Timeline 0 ↔ abs0 (ueber CAM-Bezug von PASS 2)
    abs0 = tzvf[names[0]] + offsets.get(cams[0]["cam_key"], 0)

    lv, gaps = [], []
    for c, n in zip(cams, names):
        dbs = _mic_db_per_frame(c["mic"], fps)
        mi = abs0 + t - offsets.get(c["mic_key"], 0)
        ok = (mi >= 0) & (mi < len(dbs))
        a = np.full(T, np.nan, np.float32)
        a[ok] = dbs[mi[ok]]
        lv.append(a)
        g = np.full(T, np.nan, np.float32)
        if Path(c["mouth_npz"]).exists():
            r = np.load(c["mouth_npz"])
            ci = r["frames"].astype(np.int64) - tzvf[n]          # Kamerabild → Timeline
            okc = (ci >= 0) & (ci < T)
            g[ci[okc]] = r["gap"][okc]
        gaps.append(g)

    summary = {}
    w = max(3, int(round(window_s * fps)))
    pad = int(round(0.3 * fps))
    for k, (c, n) in enumerate(zip(cams, names)):
        own, other = lv[k], lv[1 - k]
        excess = own - other
        inactive = (active == 1 - k)
        listen = inactive & ~near_switch
        valid = np.isfinite(gaps[k])
        if valid.sum() < 60 * fps:
            print(f"  Mund-Reaktionen {n}: zu wenig Gesichtsdaten — uebersprungen")
            continue
        floor = float(np.nanpercentile(own, 10))
        loud_other = other >= np.nanpercentile(other, 60)
        bleed = float(np.nanmedian(excess[inactive & loud_other]))
        tempo = _rolling_nanmean(np.abs(np.diff(gaps[k], prepend=np.nan)), w)
        pure = inactive & loud_other & (excess <= bleed + 2) & np.isfinite(tempo)
        if pure.sum() < 30 * fps:
            print(f"  Mund-Reaktionen {n}: zu wenig reines Zuhoeren zum Eichen — uebersprungen")
            continue
        thr = float(np.percentile(tempo[pure], pctl))

        burst = listen & (excess >= bleed + 8) & (own >= floor + 10)
        burst_ev = _runs(burst, int(0.15 * fps))
        bmask = np.zeros(T, bool)
        for s, e in burst_ev:
            bmask[max(0, s - pad):e + pad] = True
        trig_ev = _runs(listen & valid & (tempo >= thr), int(0.2 * fps))
        green = [(s, e) for s, e in trig_ev if bmask[s:e].any()]

        # Einwuerfe: Treffer < 1,5 s Abstand zusammenfassen, lange Strecken = kein Einwurf
        clusters = []
        for s, e in green:
            if clusters and s - clusters[-1][1] <= int(1.5 * fps):
                clusters[-1][1] = max(clusters[-1][1], e)
            else:
                clusters.append([s, e])
        clusters = [(s, e) for s, e in clusters if (e - s) / fps <= max_dur]

        # Mit vorhandenen Audio-Erkennungen abgleichen
        sp = Path(c["speaking_json"])
        data = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"fps": fps, "reactions": []}
        reacts = data.setdefault("reactions", [])
        tol = int(1.0 * fps)
        added = confirmed = 0
        for s, e in clusters:
            # Einsatz = frueherer Beginn von Mundbewegung und Mikro-Ausschlag
            onset = min([s] + [bs for bs, be in burst_ev if be >= s - pad and bs <= e + pad])
            hit = [r for r in reacts if r.get("type") == "speaking_reaction"
                   and onset - tol <= r["frame"] - tzvf[n] <= e + tol]
            if hit:
                for r in hit:
                    if not r.get("mund_bestaetigt"):
                        r["mund_bestaetigt"] = True
                        confirmed += 1
                continue
            vf = int(onset + tzvf[n])
            reacts.append({"frame": vf, "timecode": frames_to_timecode(vf, fps),
                           "type": "speaking_reaction", "confidence": 1.0,
                           "dur_s": round((e - s) / fps, 2), "source": "mund"})
            added += 1
            if decision_log is not None:
                decision_log.append({"pass": "mouth", "action": "add",
                                     "timecode": frames_to_timecode(onset, fps),
                                     "cam": n, "dur_s": round((e - s) / fps, 2)})
        reacts.sort(key=lambda r: r["frame"])
        sp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        summary[n] = {"schwelle": thr, "uebersprechen_db": bleed, "einwuerfe": len(clusters),
                      "neu": added, "bestaetigt": confirmed}
        print(f"  Mund-Reaktionen {n}: {len(clusters)} Einwürfe → {added} neu, "
              f"{confirmed} Audio-Erkennungen bestätigt (Schwelle {thr:.4f}, "
              f"Übersprechen {bleed:.1f} dB, Deadband ±{deadband_s:g} s)")
    return summary
