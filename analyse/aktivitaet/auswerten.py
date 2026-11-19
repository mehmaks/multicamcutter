"""Aktivität je Spur — Stufe 2: gegen die Mundbewegung messen.

Eingabe: tabelle.npz aus tabelle.py. Referenz ist der Mund (Lippen-Tempo, 1 s
geglättet): „spricht" = deutlich mehr Lippenbewegung als die andere Person
(z-Score-Differenz > 1). Das ist in ~3/4 der Bilder eindeutig.

Messungen:
  1. Wie gut trennt die EIGENE Spur Sprechen/Schweigen der eigenen Person? (AUC)
  2. Abstand eigene Sprache ↔ Übersprechen je Spur
  3. Sprechererkennung: heute (base.edl) vs. „Aktivität je Spur" (gleiche Glättung:
     Wechsel nach 0,3 s, Mindestlänge 1 s) — Übereinstimmung + Zahl der Schnitte
  4. Schnitt-Timing an eindeutigen Sprecherwechseln (heute)
  5. Einwurf-Kandidaten (Zuhörer-Spur über Schwelle, 0,15–2,5 s, außerhalb ±1 s um
     Schnitte): Anteil mit Mundbewegung — verglichen mit dem Zufallsanteil

Aufruf: venv/bin/python3 analyse/aktivitaet/auswerten.py TABELLE.npz
"""
import sys

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from mouth_reactions import _rolling_nanmean  # noqa: E402


def runs(m, minlen=1):
    p = np.concatenate([[0], m.astype(np.int8), [0]])
    df = np.diff(p)
    return [(s, e) for s, e in zip(np.flatnonzero(df == 1), np.flatnonzero(df == -1)) if e - s >= minlen]


def hang(mask, n):
    n = max(1, n)
    return swv(np.concatenate([np.zeros(n - 1, bool), mask]), n).any(1)


def auc(score, lab):
    m = np.isfinite(score) & (lab >= 0)
    s, l = score[m], lab[m]
    r = np.argsort(np.argsort(s))
    n1 = l.sum()
    n0 = len(l) - n1
    return (r[l == 1].sum() - n1 * (n1 - 1) / 2) / (n1 * n0)


def diar(a0, a1, fps, delay=0.3, min_edit=1.0):
    n = len(a0)
    dom = np.full(n, -1)
    dom[a0 & ~a1] = 0
    dom[a1 & ~a0] = 1
    cur = 0 if a0[:1000].sum() >= a1[:1000].sum() else 1
    out = np.empty(n, int)
    streak = st = 0
    dw = int(delay * fps)
    for i in range(n):
        if dom[i] == 1 - cur:
            if streak == 0:
                st = i
            streak += 1
            if streak >= dw:
                out[st:i + 1] = 1 - cur
                cur = 1 - cur
                streak = 0
        else:
            streak = 0
        out[i] = cur
    ch = np.flatnonzero(np.diff(out)) + 1
    b = np.concatenate([[0], ch, [n]])
    for s, e in zip(b[:-1], b[1:]):
        if e - s < min_edit * fps and s > 0:
            out[s:e] = out[s - 1]
    return out


def main():
    d = np.load(sys.argv[1], allow_pickle=True)
    fps = float(d["fps"])
    names = list(d["names"])
    eng = d["engine"]
    n = len(eng)
    lv = {src: [np.maximum(d[f"lv_{src}{k}"], -110) for k in (0, 1)] for src in ("orig", "ana")}

    mt = [_rolling_nanmean(np.log(d[f"tempo{k}"] + 1e-4), int(fps)) for k in (0, 1)]
    zz = [(m - np.nanmean(m)) / np.nanstd(m) for m in mt]
    diff = zz[0] - zz[1]
    ref = np.full(n, -1)
    ref[diff > 1.0] = 0
    ref[diff < -1.0] = 1
    print(f"Referenz (Mund) eindeutig in {(ref >= 0).mean():.0%} der Bilder")

    print("\n1+2) Eigene Spur")
    for k in (0, 1):
        lab = np.full(n, -1)
        lo, hi = np.nanpercentile(mt[k], [40, 70])
        lab[mt[k] <= lo] = 0
        lab[mt[k] >= hi] = 1
        for src in ("orig", "ana"):
            x = lv[src][k]
            print(f"  {names[k]} {src:4s} AUC {auc(x, lab):.3f} | eigene Sprache {np.median(x[ref == k]):.1f} dB, "
                  f"Übersprechen Median {np.median(x[ref == 1 - k]):.1f} / 90 % {np.percentile(x[ref == 1 - k], 90):.1f} dB")

    print("\n3) Sprechererkennung (eindeutige Bilder)")
    m = ref >= 0
    print(f"  heute (base.edl)              {(eng[m] == ref[m]).mean():.1%}  Schnitte {(np.diff(eng) != 0).sum()}")
    for src in ("ana", "orig"):
        for off in (0, 3, -3):
            thr = [(np.median(x[x > np.percentile(x, 75)]) + np.median(x[x < np.percentile(x, 50)])) / 2 + off
                   for x in lv[src]]
            act = [hang(lv[src][k] > thr[k], int(0.3 * fps)) for k in (0, 1)]
            lab = diar(act[0], act[1], fps)
            print(f"  Aktivität {src:4s} {thr[0]:.0f}/{thr[1]:.0f} dB    {(lab[m] == ref[m]).mean():.1%}  "
                  f"Schnitte {(np.diff(lab) != 0).sum()}  (beide aktiv {(act[0] & act[1]).mean():.0%})")

    print("\n4) Schnitt-Timing heute")
    segs = sorted((s, e, k) for k in (0, 1) for s, e in runs(ref == k, int(2 * fps)))
    pts = [((e1 + s2) // 2, e1, s2) for (s1, e1, k1), (s2, e2, k2) in zip(segs, segs[1:])
           if k1 != k2 and s2 - e1 < 3 * fps]
    ec = np.flatnonzero(np.diff(eng) != 0) + 1
    dist = []
    for mid, e1, s2 in pts:
        c = ec[np.argmin(np.abs(ec - mid))]
        dist.append((c - e1) / fps if c < e1 else (c - s2) / fps if c > s2 else 0.0)
    dist = np.array(dist)
    print(f"  {len(pts)} eindeutige Wechsel; Schnitt im Wechselfenster {np.mean(dist == 0):.0%}, "
          f"sonst Median {np.median(np.abs(dist[dist != 0])):.2f} s daneben")

    print("\n5) Einwurf-Kandidaten mit Mundbewegung")
    near = np.zeros(n, bool)
    for c in ec:
        near[max(0, c - int(fps)):c + int(fps)] = True
    rng = np.random.default_rng(0)
    for k in (0, 1):
        tp = d[f"tempo{k}"]
        listen = (eng == 1 - k) & ~near
        mouth = hang(tp >= np.nanpercentile(tp[listen], 93), 9)
        idx = rng.choice(np.flatnonzero(listen), 3000)
        chance = np.mean([mouth[max(0, a - 9):a + int(0.6 * fps) + 9].any() for a in idx])
        print(f"  {names[k]}: Zufall {chance:.0%}")
        for src in ("orig", "ana"):
            x = lv[src][k]
            own, bleed = np.median(x[ref == k]), np.median(x[ref == 1 - k])
            for frac in (0.4, 0.5, 0.6):
                th = bleed + frac * (own - bleed)
                mg = []
                for s, e in runs(listen & (x > th), int(0.15 * fps)):
                    if e - s > 2.5 * fps:
                        continue
                    if mg and s - mg[-1][1] < 0.5 * fps:
                        mg[-1] = (mg[-1][0], e)
                    else:
                        mg.append((s, e))
                ok = sum(1 for s, e in mg if mouth[max(0, s - 9):e + 9].any())
                print(f"    {src:4s} Schwelle {th:6.1f} dB: {len(mg):4d} Kandidaten, mit Mund {ok:4d} "
                      f"({ok / max(1, len(mg)):.0%})")


if __name__ == "__main__":
    main()
