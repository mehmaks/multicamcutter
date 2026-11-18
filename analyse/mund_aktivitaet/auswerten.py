"""Mund-Aktivitaet — Stufe 3: Auswertung gegen die Sprechererkennung.

Liest die Rohdaten aus aufzeichnen.py (je Kamera eine .npz), die Sprecher-EDL
(base.edl aus der Engine) und die Mikrospuren, legt alles auf dieselbe
Timeline und beantwortet die drei vorab festgelegten Fragen:

  K1 Sichtbarkeit   Ist der Mund in >= 80 % der Zeit verwertbar?
  K2 Trennung       Sieht Sprechen im Mund-Signal anders aus als Zuhoeren?
                    (AUC >= 0,85 fuer das beste Merkmal)
  K3 Treffer        Fallen Mund-Ausschlaege des Zuhoerers deutlich haeufiger
                    auf Ausschlaege seines eigenen Mikros als zufaellig?
                    (>= 2x Zufall, Permutationstest p < 0,01)

Keine Schwelle ist fest: Merkmale, Fensterlaengen und Ausloeseschwellen werden
breit durchprobiert. Ergebnis: ergebnis.json, bericht.txt, marker.json.

Aufruf: venv/bin/python3 analyse/mund_aktivitaet/auswerten.py KONFIG.json
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules" / "multicam_cutter"))
from shared.frame_utils import timecode_to_frames as tc_to_frames  # noqa: E402
from build_aaf import _probe_embedded_tc_frames  # noqa: E402

RNG = np.random.default_rng(61)


# ── Laden ────────────────────────────────────────────────────────────────────

def parse_edl(path, fps):
    ev_re = re.compile(r"^\d+\s+\S+\s+\S+\s+C\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", re.M)
    cn_re = re.compile(r"^\*\s*FROM CLIP NAME:\s*(.+)", re.M)
    text = Path(path).read_text()
    out = []
    for ev, cn in zip(ev_re.finditer(text), cn_re.finditer(text)):
        out.append({"clip": cn.group(1).strip(),
                    "src_in": tc_to_frames(ev.group(1), fps),
                    "rec_in": tc_to_frames(ev.group(3), fps),
                    "rec_out": tc_to_frames(ev.group(4), fps)})
    return out


def mic_db_per_frame(wav, fps, sr=16000):
    """Pegel (dBFS, RMS) je Videobild ueber ffmpeg — jede Bit-Tiefe korrekt."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1",
                          "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    spf = sr / fps
    n = int(len(x) / spf)
    idx = (np.arange(n + 1) * spf).astype(np.int64)
    c = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    ms = (c[idx[1:]] - c[idx[:-1]]) / np.maximum(1, idx[1:] - idx[:-1])
    return 10 * np.log10(ms + 1e-12)


# ── Merkmale ─────────────────────────────────────────────────────────────────

def rolling(fn, x, w):
    """Gleitendes fn ueber w Bilder (zentriert), NaN-tolerant."""
    from numpy.lib.stride_tricks import sliding_window_view
    pad = w // 2
    xp = np.concatenate([np.full(pad, np.nan), x, np.full(w - 1 - pad, np.nan)])
    v = sliding_window_view(xp, w)
    with np.errstate(all="ignore"), np.testing.suppress_warnings() as s:
        s.filter(RuntimeWarning)
        return fn(v, axis=1)


def features(rec, fps):
    """Kandidaten-Merkmale je Bild. Bewusst mehrere: reine Oeffnung UND Bewegung."""
    gap = rec["gap_inner"]
    jaw = rec["jaw"]
    dgap = np.abs(np.diff(gap, prepend=np.nan))
    feats = {}
    for ws in (0.33, 0.67, 1.0):
        w = max(3, int(round(ws * fps)))
        feats[f"oeffnung_mittel_{ws}s"] = rolling(np.nanmean, gap, w)
        feats[f"oeffnung_streuung_{ws}s"] = rolling(np.nanstd, gap, w)
        feats[f"lippen_tempo_{ws}s"] = rolling(np.nanmean, dgap, w)
        feats[f"kiefer_mittel_{ws}s"] = rolling(np.nanmean, jaw, w)
        feats[f"kiefer_streuung_{ws}s"] = rolling(np.nanstd, jaw, w)
    return feats


def auc(pos, neg, max_n=40000):
    pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
    if len(pos) < 50 or len(neg) < 50:
        return None
    if len(pos) > max_n:
        pos = RNG.choice(pos, max_n, replace=False)
    if len(neg) > max_n:
        neg = RNG.choice(neg, max_n, replace=False)
    u = mannwhitneyu(pos, neg, alternative="two-sided").statistic
    return float(u / (len(pos) * len(neg)))


def runs(mask, min_len):
    """Zusammenhaengende True-Strecken → [(start, ende_exkl)] ab min_len Bildern."""
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    st, en = np.where(d == 1)[0], np.where(d == -1)[0]
    return [(int(s), int(e)) for s, e in zip(st, en) if e - s >= min_len]


# ── Hauptteil ────────────────────────────────────────────────────────────────

def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_dir = Path(cfg["out_dir"])
    fps = float(cfg["fps"])
    offs = cfg["offsets"]
    people = cfg["people"]          # [{name, cam, cam_key, mic, mic_key, npz}]

    edl = parse_edl(cfg["edl"], fps)
    T = max(e["rec_out"] for e in edl)
    cam_tc = {p["cam"]: _probe_embedded_tc_frames(p["cam"], fps) for p in people}

    # Timeline → absolute Position (CAM1-Bezug), wie build_aaf: abs = src + off
    ev0 = edl[0]
    p0 = next(p for p in people if Path(p["cam"]).name == ev0["clip"])
    abs0 = ev0["src_in"] - cam_tc[p0["cam"]] + offs[p0["cam_key"]] - ev0["rec_in"]
    # Gegenprobe an JEDEM Event: dieselbe Abbildung muss ueberall gelten
    bad = 0
    for e in edl:
        p = next(q for q in people if Path(q["cam"]).name == e["clip"])
        exp = abs0 + e["rec_in"] - offs[p["cam_key"]]
        bad += int(e["src_in"] - cam_tc[p["cam"]] != exp)
    print(f"Timeline: {T} Bilder ({T / fps / 60:.1f} min), Abbildung an {len(edl)} Events geprueft, "
          f"Abweichungen: {bad}")
    assert bad == 0, "Timeline-Abbildung inkonsistent"

    t = np.arange(T)
    active = np.full(T, -1, np.int16)            # Index der sprechenden Person laut EDL
    for e in edl:
        k = next(i for i, q in enumerate(people) if Path(q["cam"]).name == e["clip"])
        active[e["rec_in"]:e["rec_out"]] = k

    # Mikros + Mund je Person auf die Timeline legen
    lv, mouth = [], []
    for p in people:
        db = mic_db_per_frame(p["mic"], fps)
        mi = abs0 + t - offs[p["mic_key"]]
        ok = (mi >= 0) & (mi < len(db))
        a = np.full(T, np.nan)
        a[ok] = db[mi[ok]]
        lv.append(a)

        r = np.load(p["npz"], allow_pickle=True)
        names = list(r["bs_names"])
        ci = abs0 + t - offs[p["cam_key"]]
        okc = (ci >= 0) & (ci < int(r["n"]))
        def lay(arr):
            o = np.full(T, np.nan, np.float32)
            o[okc] = arr[ci[okc]]
            return o
        rec = {k: lay(r[k]) for k in ("gap_inner", "gap_outer", "mouth_w", "yaw", "pitch", "face_h")}
        rec["face"] = lay(r["face"].astype(np.float32))
        rec["jaw"] = lay(r["bs"][:, names.index("jawOpen")]) if "jawOpen" in names else np.full(T, np.nan)
        rec["smile"] = lay(np.nanmean(r["bs"][:, [names.index("mouthSmileLeft"),
                                                  names.index("mouthSmileRight")]], axis=1))
        rec["in_range"] = okc
        mouth.append(rec)

    n = len(people)
    deadband_s = float(cfg.get("deadband_s", 1.0))
    marker_merkmal = cfg.get("marker_merkmal", "lippen_tempo_0.33s")
    vergleich_merkmal = cfg.get("vergleich_merkmal", "lippen_tempo_1.0s")
    marker_q = float(cfg.get("marker_quantil", 0.25))
    K3_MERKMALE = [marker_merkmal, vergleich_merkmal]
    # Sprecherwechsel = Stelle, an der die aktive Person laut EDL wechselt
    sw_idx = np.where((active[1:] != active[:-1]) & (active[1:] >= 0) & (active[:-1] >= 0))[0] + 1
    near_switch = np.zeros(T, bool)
    db = int(round(deadband_s * fps))
    for i in sw_idx:
        near_switch[max(0, i - db):i + db] = True
    print(f"Sprecherwechsel: {len(sw_idx)}, Deadband ±{deadband_s} s = "
          f"{near_switch.mean():.1%} der Timeline ausgeblendet")

    # Pegel-Bezug je Mikro: Grundrauschen = 10. Perzentil
    floor = [np.nanpercentile(a, 10) for a in lv]

    res = {"timeline_min": T / fps / 60, "people": [p["name"] for p in people], "per_person": {}}
    markers = []
    lines = []
    for k, p in enumerate(people):
        o = [j for j in range(n) if j != k]
        own, other = lv[k], np.nanmax(np.vstack([lv[j] for j in o]), axis=0)
        excess = own - other                      # eigener Pegel minus lautester anderer
        rec = mouth[k]
        valid = rec["in_range"] & (rec["face"] > 0.5)
        frontal = valid & (np.abs(rec["yaw"]) < 0.5)

        inactive = (active != k) & (active >= 0)
        # Uebersprechen je Person messen: typischer Abstand eigenes ↔ fremdes Mikro,
        # waehrend der andere laut redet (Median). Feste dB-Grenzen passen nicht fuer
        # alle — Sebs Mikro faengt z. B. deutlich mehr von Kim auf als umgekehrt.
        loud_other = other >= np.nanpercentile(other, 60)
        bleed = float(np.nanmedian(excess[inactive & loud_other]))

        # Zustaende (bewusst streng, damit die Bezugsgruppen sauber sind)
        A = (active == k) & (excess >= 6) & (own >= floor[k] + 15)          # spricht sicher
        B = inactive & loud_other & (excess <= bleed + 2)                    # hoert zu, nur Uebersprechen
        C = (own < floor[k] + 6) & (other < np.nanpercentile(other, 25))    # beide still

        vis = {"gesicht_gefunden": float(np.mean(rec["face"][rec["in_range"]] > 0.5)),
               "gesicht_frontal": float(np.mean(frontal[rec["in_range"]])),
               "gesicht_beim_zuhoeren": float(np.mean(valid[inactive])) if inactive.any() else None}

        feats = features(rec, fps)
        sep = {}
        for name, f in feats.items():
            sep[name] = {"A_vs_B": auc(f[A & valid], f[B & valid]),
                         "A_vs_C": auc(f[A & valid], f[C & valid]),
                         "B_vs_C": auc(f[B & valid], f[C & valid])}
        best = max(sep, key=lambda s: abs((sep[s]["A_vs_B"] or 0.5) - 0.5))
        best_auc = sep[best]["A_vs_B"]

        # Wechsel-Deadband (User, 18.11.): X s vor/nach jedem Sprecherwechsel ignorieren —
        # dort lagen in Folge 61 fast alle Fehlalarme (Gruen 15/30, Gelb 19/30 < 1 s).
        listen = inactive & ~near_switch

        # Eigenes Mikro deutlich ueber dem ueblichen Uebersprechen UND hoerbar laut
        own_burst = listen & (excess >= bleed + 8) & (own >= floor[k] + 10)
        own_burst_ev = runs(own_burst, int(0.15 * fps))
        pad = int(0.3 * fps)
        burst_mask = np.zeros(T, bool)
        for s, e in own_burst_ev:
            burst_mask[max(0, s - pad):e + pad] = True
        idx_in = np.where(listen & valid)[0]
        zuh_min = (listen & valid).sum() / fps / 60
        b_min = (B & valid & ~near_switch).sum() / fps / 60

        def k3(f):
            """Sweep breiter Schwellen: Quantile der EIGENEN Sprech-Verteilung."""
            fa = f[A & valid]
            out = []
            for q in (0.10, 0.25, 0.50, 0.75):
                thr = float(np.nanquantile(fa, q))
                trig = listen & valid & (f >= thr)
                ev = runs(trig, int(0.2 * fps))
                if not ev:
                    out.append({"quantil": q, "schwelle": thr, "ausloeser": 0})
                    continue
                hit = np.array([burst_mask[s:e].any() for s, e in ev])
                perm = []
                for _ in range(300):
                    starts = RNG.choice(idx_in, len(ev))
                    perm.append(np.mean([burst_mask[s:s + (e2 - s2)].any()
                                         for s, (s2, e2) in zip(starts, ev)]))
                perm = np.array(perm)
                trig_b = len(runs(B & valid & ~near_switch & (f >= thr), int(0.2 * fps)))
                out.append({
                    "quantil": q, "schwelle": thr, "ausloeser": len(ev),
                    "ausloeser_pro_min_zuhoeren": len(ev) / max(zuh_min, 1e-6),
                    "fehlausloeser_pro_min_reines_zuhoeren": trig_b / max(b_min, 1e-6),
                    "treffer_mikro": float(hit.mean()),
                    "zufall_mikro": float(perm.mean()),
                    "anreicherung": float(hit.mean() / max(perm.mean(), 1e-6)),
                    "p_wert": float((np.sum(perm >= hit.mean()) + 1) / (len(perm) + 1)),
                    "mikro_ausschlaege_mit_mund": float(np.mean(
                        [(trig[max(0, s - pad):e + pad]).any() for s, e in own_burst_ev])) if own_burst_ev else None,
                })
            return out

        sweeps = {name: k3(feats[name]) for name in K3_MERKMALE}

        res["per_person"][p["name"]] = {
            "sichtbarkeit": vis, "uebersprechen_db": bleed,
            "bezugsgruppen_min": {"A_spricht": float((A & valid).sum() / fps / 60),
                                  "B_hoert_zu": float((B & valid).sum() / fps / 60),
                                  "C_still": float((C & valid).sum() / fps / 60)},
            "trennung": sep, "bestes_merkmal": best, "beste_auc_A_vs_B": best_auc,
            "ausloeser_sweep": sweeps, "mikro_ausschlaege_beim_zuhoeren": len(own_burst_ev),
            "deadband_s": deadband_s,
        }

        # Marker: Merkmal + Quantil aus der Konfiguration; je Marker vermerkt, ob ihn
        # das Vergleichsmerkmal (anderes Messfenster) auch gefunden haette.
        def trig_of(name):
            f = feats[name]
            thr = float(np.nanquantile(f[A & valid], marker_q))
            return listen & valid & (f >= thr), f
        trig, f = trig_of(marker_merkmal)
        trig_cmp, _ = trig_of(vergleich_merkmal)
        mouth_ev = runs(trig, int(0.2 * fps))
        tm = np.zeros(T, bool)
        for s, e in mouth_ev:
            tm[max(0, s - pad):e + pad] = True
        for s, e in mouth_ev:
            kind = "mund_und_mikro" if burst_mask[s:e].any() else "nur_mund"
            markers.append({"person": p["name"], "cam": Path(p["cam"]).name, "start": s, "end": e,
                            "art": kind, "smile": float(np.nanmean(rec["smile"][s:e])),
                            "merkmal": float(np.nanmax(f[s:e])),
                            "auch_vergleich": bool(trig_cmp[max(0, s - pad):e + pad].any())})
        for s, e in own_burst_ev:
            if not tm[s:e].any():
                markers.append({"person": p["name"], "cam": Path(p["cam"]).name, "start": s, "end": e,
                                "art": "nur_mikro", "gesicht": float(np.mean(valid[s:e])),
                                "auch_vergleich": bool(trig_cmp[max(0, s - pad):e + pad].any())})

        lines.append(f"── {p['name']} ──")
        lines.append(f"K1 Sichtbarkeit: Gesicht {vis['gesicht_gefunden']:.1%}, frontal "
                     f"{vis['gesicht_frontal']:.1%}, beim Zuhoeren {vis['gesicht_beim_zuhoeren']:.1%}")
        lines.append(f"K2 Trennung: bestes Merkmal {best}, AUC Sprechen↔Zuhoeren {best_auc:.3f}")
        for name, sweep in sweeps.items():
          lines.append(f"K3 [{name}, Deadband {deadband_s} s]")
          for sw in sweep:
            if sw.get("ausloeser"):
                lines.append(f"   Quantil {sw['quantil']:.2f}: {sw['ausloeser']} Ausloeser "
                             f"({sw['ausloeser_pro_min_zuhoeren']:.2f}/min), Mikro-Treffer "
                             f"{sw['treffer_mikro']:.1%} vs Zufall {sw['zufall_mikro']:.1%} "
                             f"→ ×{sw['anreicherung']:.2f}, p={sw['p_wert']:.3f}")

    markers.sort(key=lambda m: m["start"])
    res["marker_anzahl"] = {a: sum(1 for m in markers if m["art"] == a)
                            for a in ("mund_und_mikro", "nur_mund", "nur_mikro")}
    (out_dir / "ergebnis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "marker.json").write_text(json.dumps(markers, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "bericht.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    np.savez_compressed(out_dir / "timeline.npz", active=active, lv=np.vstack(lv),
                        **{f"{people[k]['name']}_{key}": mouth[k][key]
                           for k in range(n) for key in ("gap_inner", "jaw", "face", "yaw", "smile")})
    print("\n".join(lines))
    print("Marker:", res["marker_anzahl"])


if __name__ == "__main__":
    main()
