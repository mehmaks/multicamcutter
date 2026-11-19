"""Einwurf-Erkennung „B" auf der Analysespur — wie das Auge die Waveform liest.

Ein Hügel auf der Spur des Zuhörers (während die andere Person spricht) zählt, wenn er
  - über der UMGEBUNG liegt:   Pegel ≥ 80. Perzentil der letzten/nächsten 3 s + umgebung_db
    (ohne die eigene Sprache der Person — sonst ist die Schwelle nahe Sprecherwechseln zu hoch)
  - über dem ERWARTETEN Übersprechen liegt: Pegel ≥ (Sprecher-Spur, lautester Wert
    in ±0,2 s) + gelernter Abstand + uebersprechen_db
  - nicht viel leiser als die eigene Sprache ist: ≥ Median eigene Sprache − leise_db
Danach (Fix 19.11., Feedback 06:55/09:02): Lücken ≤ luecke_s innerhalb eines Einwurfs
schließen — bei gleichzeitigem Sprechen flackern die Bedingungen bildweise —, ERST dann
Mindestlänge prüfen. Einwürfe < zusammen_s Abstand werden verbunden, > max_s verworfen.
Nicht innerhalb ±deadband_s um einen Sprecherwechsel.

Zeitachse: Timeline-Bilder aus tabelle.py (base.edl).
"""
import numpy as np
from scipy.ndimage import maximum_filter1d, percentile_filter

PARAMS = {
    "umgebung_s": 6.0, "umgebung_pctl": 80, "umgebung_db": 6.0,
    "uebersprechen_db": 12.0, "hall_s": 0.4, "leise_db": 12.0,
    "luecke_s": 0.2, "min_s": 0.1, "zusammen_s": 0.5, "max_s": 2.5, "deadband_s": 1.0,
    # Runde 2 (Sichtung 61): Nahe Sprecherwechseln enthielt das Umgebungsfenster die EIGENE
    # Sprache der Person → Schwelle zu hoch, echte Einwürfe verpasst. Eigene Sprache raus.
    "umgebung_ohne_eigene": True,
}


def _runs(m):
    p = np.concatenate([[0], m.astype(np.int8), [0]])
    df = np.diff(p)
    return list(zip(np.flatnonzero(df == 1), np.flatnonzero(df == -1)))


def _merge(runs, gap):
    out = []
    for s, e in runs:
        if out and s - out[-1][1] <= gap:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def detect(d, params=None):
    """d = geladene tabelle.npz. Gibt je Person k ein Dict mit Kurven und Ereignissen."""
    p = {**PARAMS, **(params or {})}
    fps = float(d["fps"])
    eng = d["engine"]
    n = len(eng)
    ec = np.flatnonzero(np.diff(eng) != 0) + 1
    near = np.zeros(n, bool)
    db = int(round(p["deadband_s"] * fps))
    for c in ec:
        near[max(0, c - db):c + db] = True
    X = [np.maximum(d[f"lv_ana{k}"], -110).astype(float) for k in (0, 1)]
    res = []
    for k in (0, 1):
        x, o = X[k], X[1 - k]
        listen = eng == 1 - k
        sel = listen & (o >= np.percentile(o[listen], 60))
        gain = float(np.median(x[sel] - o[sel]))
        erwartet = maximum_filter1d(o, max(1, int(p["hall_s"] * fps))) + gain
        xu = np.where(eng == k, -110.0, x) if p["umgebung_ohne_eigene"] else x
        umgebung = percentile_filter(xu, p["umgebung_pctl"], size=int(p["umgebung_s"] * fps))
        sprache = float(np.median(x[eng == k]))
        thr = np.maximum(np.maximum(umgebung + p["umgebung_db"], erwartet + p["uebersprechen_db"]),
                         sprache - p["leise_db"])
        m = listen & ~near & (x >= thr)
        cand = _merge(_runs(m), int(round(p["luecke_s"] * fps)))
        ok, rej = [], []
        for s, e in cand:
            (ok if e - s >= p["min_s"] * fps else rej).append((s, e, "zu kurz"))
        ev = _merge([(s, e) for s, e, _ in ok], int(round(p["zusammen_s"] * fps)))
        events = []
        for s, e in ev:
            if e - s > p["max_s"] * fps:
                rej.append((s, e, "zu lang"))
            else:
                events.append((int(s), int(e)))
        res.append({"roh": (listen & (x >= thr)).astype(np.float32), "puffer": near.astype(np.float32),
                    "events": events, "rejected": [(int(s), int(e), r) for s, e, r in rej],
                    "umgebung": umgebung + p["umgebung_db"], "erwartet": erwartet + p["uebersprechen_db"],
                    "leise": sprache - p["leise_db"], "gain_db": gain, "sprache_db": sprache})
    return res, p
