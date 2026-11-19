"""Einwürfe aus der Analysespur („Einwurf-Erkennung B", Beta).

Ersetzt die Einwurf-Erkennung der Basis-EDL (Anstieg über wandernde Grundlinie +
Regel A) durch eine Erkennung auf der ANALYSESPUR: jedes Mikro ohne das Übersprechen
der anderen Person und ohne Grundrauschen. Dort hebt sich ein kurzes „Mhm"/„Ja" klar
ab — erkannt wird es so, wie das Auge die Waveform liest (lokaler Vergleich).

Herleitung + Sichtung: analyse/aktivitaet/ (Analyse-Player), Folge 61: 368/381 nur-B
Treffer echt, Folge 62: 296/309; Rest fast nur Geräusche (Atmen, Klopfen).

1) Analysespur (wie analyse/sprachspur/sprachspur.py --roh, aber IN STÜCKEN und ohne
   WAV — gebraucht wird nur der Pegel je Videobild):
   Sprachband 120–5000 Hz → je Frequenz Übersprechen abziehen (|H(f)|² = Median
   eigen/anders, wo das andere Mikro klar dominiert; Übersubtraktion β=2) →
   Rauschboden abziehen (aus leisen Momenten des Originals, α=3).
   Drei Durchgänge über den Ton (16 kHz, als Rohdatei im Arbeitsordner): Energien je
   STFT-Fenster → Statistik (Stichprobe) → Analysespur + Pegel je Bild.
2) Erkennung (detect): ein Hügel auf der Spur des Zuhörers zählt, wenn er
   - ≥ 80. Perzentil der Umgebung (±3 s, OHNE eigene Sprache) + 6 dB liegt,
   - ≥ erwartetes Übersprechen (Sprecher-Spur, lautester Wert ±0,2 s, + gelernter
     Abstand) + 12 dB liegt,
   - ≥ Median eigene Sprache − 12 dB liegt;
   Lücken ≤ 0,2 s schließen, dann ≥ 0,1 s; Einwürfe < 0,5 s Abstand verbinden,
   > max_s verwerfen; nicht ±1 s um Sprecherwechsel (Deadband).
"""
import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter1d, percentile_filter
from scipy.signal import butter, istft, sosfiltfilt, stft

SR = 16000
NFFT = 1024
HOP = 256
CHUNK = 3750 * HOP          # 60 s
MARGIN = 64 * HOP           # ~1 s Kontext je Seite (Filter + STFT-Ränder)

PARAMS = {
    "umgebung_s": 6.0, "umgebung_pctl": 80, "umgebung_db": 6.0, "umgebung_ohne_eigene": True,
    "uebersprechen_db": 12.0, "hall_s": 0.4, "leise_db": 12.0,
    "luecke_s": 0.2, "min_s": 0.1, "zusammen_s": 0.5, "max_s": 2.5, "deadband_s": 1.0,
}


# ── 1) Analysespur → Pegel je Videobild ──────────────────────────────────────

def _decode(path, raw):
    """Mono, 16 kHz, float32 als Rohdatei (wird per memmap stückweise gelesen)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-ac", "1", "-ar", str(SR),
                    "-f", "f32le", str(raw)], check=True)
    return np.memmap(raw, dtype=np.float32, mode="r")


def _segment(x, a, b, shift=0):
    """x[a−shift : b−shift] mit Nullen außerhalb (shift = Versatz in Samples)."""
    a2, b2 = a - shift, b - shift
    out = np.zeros(b - a, np.float32)
    lo, hi = max(a2, 0), min(b2, len(x))
    if hi > lo:
        out[lo - a2:hi - a2] = x[lo:hi]
    return out


def _chunks(n):
    for c0 in range(0, n, CHUNK):
        yield c0, min(n, c0 + CHUNK)


def _spektren(x0, x1, shift1, c0, c1, sos):
    """STFT beider Mikros für den Kern [c0, c1) mit Rand-Kontext. Liefert (O, R, k0, k1):
    Spalten k0:k1 sind die STFT-Fenster, deren Mitte im Kern liegt."""
    a, b = c0 - MARGIN, c1 + MARGIN
    s0 = sosfiltfilt(sos, _segment(x0, a, b))
    s1 = sosfiltfilt(sos, _segment(x1, a, b, shift1))
    _, _, O = stft(s0, SR, nperseg=NFFT, noverlap=NFFT - HOP)
    _, _, R = stft(s1, SR, nperseg=NFFT, noverlap=NFFT - HOP)
    k0 = MARGIN // HOP
    k1 = k0 + -(-(c1 - c0) // HOP)
    return O, R, k0, min(k1, O.shape[1])


def analysespur_pegel(mic0, mic1, shift1, fps, work_dir, log=print):
    """Pegel (dBFS RMS) je Videobild der Analysespuren beider Personen, im Bildraster
    von mic0 (Bild 0 = Start von mic0). shift1 = Samples (16 kHz), um die mic1 später
    startet als mic0. Gibt (pegel0, pegel1, info) zurück."""
    work_dir = Path(work_dir)
    raw0, raw1 = work_dir / "_ana_mic0.f32", work_dir / "_ana_mic1.f32"
    try:
        x0, x1 = _decode(mic0, raw0), _decode(mic1, raw1)
        n = len(x0)
        sos = butter(4, [120, 5000], btype="band", fs=SR, output="sos")

        # Durchgang 1: Energie je STFT-Fenster
        eo, er = [], []
        for c0, c1 in _chunks(n):
            O, R, k0, k1 = _spektren(x0, x1, shift1, c0, c1, sos)
            eo.append(np.sum(np.abs(O[:, k0:k1]) ** 2, 0))
            er.append(np.sum(np.abs(R[:, k0:k1]) ** 2, 0))
        eo, er = np.concatenate(eo), np.concatenate(er)
        dom0 = (er >= 4 * eo) & (er >= np.percentile(er, 70))     # anderer spricht → Übersprechen in mic0
        dom1 = (eo >= 4 * er) & (eo >= np.percentile(eo, 70))
        quiet = (eo + er) <= np.percentile(eo + er, 10)

        # Durchgang 2: Statistik aus einer gleichmäßigen Stichprobe (Median ist robust)
        def pick(mask, cap=20000):
            idx = np.flatnonzero(mask)
            keep = np.zeros(len(mask), bool)
            keep[idx[::max(1, len(idx) // cap)]] = True
            return keep
        p0, p1, pq = pick(dom0), pick(dom1), pick(quiet)
        r0, r1, q0, q1 = [], [], [], []
        g = 0
        for c0, c1 in _chunks(n):
            O, R, k0, k1 = _spektren(x0, x1, shift1, c0, c1, sos)
            Po, Pr = np.abs(O[:, k0:k1]) ** 2, np.abs(R[:, k0:k1]) ** 2
            sl = slice(g, g + (k1 - k0))
            r0.append(Po[:, p0[sl]] / (Pr[:, p0[sl]] + 1e-20))
            r1.append(Pr[:, p1[sl]] / (Po[:, p1[sl]] + 1e-20))
            q0.append(Po[:, pq[sl]])
            q1.append(Pr[:, pq[sl]])
            g += k1 - k0
        H0 = np.median(np.concatenate(r0, 1), 1)[:, None]
        H1 = np.median(np.concatenate(r1, 1), 1)[:, None]
        N0 = np.median(np.concatenate(q0, 1), 1)[:, None]
        N1 = np.median(np.concatenate(q1, 1), 1)[:, None]
        del r0, r1, q0, q1

        # Durchgang 3: Analysespur je Stück → Energie je Videobild
        spf = SR / fps
        nf = int(n / spf) + 1
        bnd = np.round(np.arange(nf + 1) * spf).astype(np.int64)
        acc = [np.zeros(nf), np.zeros(nf)]
        cnt = np.zeros(nf)
        for c0, c1 in _chunks(n):
            O, R, _, _ = _spektren(x0, x1, shift1, c0, c1, sos)
            Po, Pr = np.abs(O) ** 2, np.abs(R) ** 2
            idx = np.arange(c0, c1)
            fi = np.searchsorted(bnd, idx, side="right") - 1
            cnt += np.bincount(fi, minlength=nf)[:nf]
            for k, (X, P_own, P_oth, H, Nn) in enumerate(((O, Po, Pr, H0, N0), (R, Pr, Po, H1, N1))):
                S = X * np.clip(1 - 2.0 * H * P_oth / (P_own + 1e-20), 0, 1)
                A = S * np.clip(1 - 3.0 * Nn / (np.abs(S) ** 2 + 1e-20), 0, 1)
                _, y = istft(A, SR, nperseg=NFFT, noverlap=NFFT - HOP)
                y = np.clip(y[MARGIN:MARGIN + (c1 - c0)], -1, 1)
                if len(y) < c1 - c0:
                    y = np.pad(y, (0, c1 - c0 - len(y)))
                acc[k] += np.bincount(fi, weights=y.astype(np.float64) ** 2, minlength=nf)[:nf]
        with np.errstate(divide="ignore", invalid="ignore"):
            pegel = [10 * np.log10(a / np.maximum(cnt, 1) + 1e-12) for a in acc]
        info = {"minuten": round(n / SR / 60, 1),
                "uebersprechen_gelernt": [round(float(dom0.mean()), 3), round(float(dom1.mean()), 3)]}
        return pegel[0].astype(np.float32), pegel[1].astype(np.float32), info
    finally:
        for r in (raw0, raw1):
            try:
                r.unlink()
            except OSError:
                pass


# ── 2) Erkennung ─────────────────────────────────────────────────────────────

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


def detect(pegel, engine, fps, params=None):
    """pegel = [Pegel Person 0, Person 1] je Timeline-Bild (dB), engine = wer laut
    Sprechererkennung spricht (0/1, −1 sonst). Gibt je Person ein Dict mit Ereignissen
    (Timeline-Bilder) und den Kurven für die Analyse zurück."""
    p = {**PARAMS, **(params or {})}
    n = len(engine)
    ec = np.flatnonzero(np.diff(engine) != 0) + 1
    near = np.zeros(n, bool)
    db = int(round(p["deadband_s"] * fps))
    for c in ec:
        near[max(0, c - db):c + db] = True
    X = [np.nan_to_num(np.maximum(np.asarray(v, float), -110), nan=-110) for v in pegel]
    res = []
    for k in (0, 1):
        x, o = X[k], X[1 - k]
        listen = engine == 1 - k
        if listen.sum() < fps * 10 or (engine == k).sum() < fps * 10:
            res.append({"events": [], "rejected": [], "roh": np.zeros(n, np.float32),
                        "puffer": near.astype(np.float32), "umgebung": np.full(n, np.nan),
                        "erwartet": np.full(n, np.nan), "leise": np.nan, "gain_db": np.nan,
                        "sprache_db": np.nan})
            continue
        sel = listen & (o >= np.percentile(o[listen], 60))
        gain = float(np.median(x[sel] - o[sel]))
        erwartet = maximum_filter1d(o, max(1, int(p["hall_s"] * fps))) + gain
        xu = np.where(engine == k, -110.0, x) if p["umgebung_ohne_eigene"] else x
        umgebung = percentile_filter(xu, p["umgebung_pctl"], size=int(p["umgebung_s"] * fps))
        sprache = float(np.median(x[engine == k]))
        thr = np.maximum(np.maximum(umgebung + p["umgebung_db"], erwartet + p["uebersprechen_db"]),
                         sprache - p["leise_db"])
        m = listen & ~near & (x >= thr)
        cand = _merge(_runs(m), int(round(p["luecke_s"] * fps)))
        ok, rej = [], []
        for s, e in cand:
            (ok if e - s >= p["min_s"] * fps else rej).append((s, e, "zu kurz"))
        events = []
        for s, e in _merge([(s, e) for s, e, _ in ok], int(round(p["zusammen_s"] * fps))):
            if e - s > p["max_s"] * fps:
                rej.append((s, e, "zu lang"))
            else:
                events.append((int(s), int(e)))
        res.append({"roh": (listen & (x >= thr)).astype(np.float32), "puffer": near.astype(np.float32),
                    "events": events, "rejected": [(int(s), int(e), r) for s, e, r in rej],
                    "umgebung": umgebung + p["umgebung_db"], "erwartet": erwartet + p["uebersprechen_db"],
                    "leise": sprache - p["leise_db"], "gain_db": gain, "sprache_db": sprache})
    return res, p


# ── 3) Engine-Schritt ────────────────────────────────────────────────────────

def _start_versatz(mic0, mic1, off0, off1, fps):
    """Samples (16 kHz), um die mic1 später startet als mic0. Gleicher Rekorder mit
    BWF-Zeitstempel → samplegenau; sonst aus dem Sync (bildgenau)."""
    try:
        from shared.split_audio import read_wav_info
        a, b = read_wav_info(mic0), read_wav_info(mic1)
        if a and b and a.get("time_ref") is not None and b.get("time_ref") is not None:
            d = b["time_ref"] / b["sample_rate"] - a["time_ref"] / a["sample_rate"]
            if abs(d - (off1 - off0) / fps) < 2.0:          # Plausibilität gegen den Sync
                return int(round(d * SR))
    except Exception:
        pass
    return int(round((off1 - off0) / fps * SR))


def add_analysespur_reactions(base_edl, cams, offsets, fps, params, work_dir):
    """cams: genau 2 Einträge {video, cam_key ('CAM1'), mic, mic_key ('MIC1'),
    speaking_json}. ERSETZT die Einwürfe in den speaking_json-Dateien durch die
    Erkennung auf der Analysespur. Gibt eine Zusammenfassung zurück."""
    from add_reactions_to_edl import parse_resolve_edl, calculate_reference_frames
    from frame_utils import frames_to_timecode

    events = parse_resolve_edl(str(base_edl), fps)
    names = [Path(c["video"]).name for c in cams]
    _, tzvf = calculate_reference_frames(
        events, [{"name": n, "video": c["video"]} for n, c in zip(names, cams)], fps)
    if any(n not in tzvf for n in names):
        raise RuntimeError("Kamera ohne Bezug in base.edl")
    T = max(e.record_out_frame for e in events)
    t = np.arange(T)
    engine = np.full(T, -1, np.int8)
    for e in events:
        if e.clip_name in names:
            engine[e.record_in_frame:e.record_out_frame] = names.index(e.clip_name)

    off0 = offsets.get(cams[0]["mic_key"], 0)
    off1 = offsets.get(cams[1]["mic_key"], 0)
    shift1 = _start_versatz(cams[0]["mic"], cams[1]["mic"], off0, off1, fps)
    print(f"  Analysespur rechnen (Übersprechen und Rauschen entfernen)…", flush=True)
    p0, p1, info = analysespur_pegel(cams[0]["mic"], cams[1]["mic"], shift1, fps, work_dir)
    # Timeline-Bild t ↔ Bild von mic0: abs0 + t − off_mic0 (wie mouth_reactions/PASS 2)
    abs0 = tzvf[names[0]] + offsets.get(cams[0]["cam_key"], 0)
    mi = abs0 + t - off0
    ok = (mi >= 0) & (mi < len(p0))
    pegel = []
    for p in (p0, p1):
        a = np.full(T, -110.0, np.float32)
        a[ok] = p[mi[ok]]
        pegel.append(a)

    bp = {}
    if params.get("speaking_max_dur") is not None:
        bp["max_s"] = float(params["speaking_max_dur"])
    # Slider „Treffsicherheit" Sprachreaktionen: Abstand über Umgebung bzw. erwartetem
    # Übersprechen; Deadband um Sprecherwechsel. Ohne Angabe = gesichtete Werte.
    for key, pk in (("umgebung_db", "speaking_umgebung_db"), ("uebersprechen_db", "speaking_uebersprechen_db"),
                    ("deadband_s", "speaking_deadband_s")):
        if params.get(pk) is not None:
            bp[key] = float(params[pk])
    res, used = detect(pegel, engine, fps, bp)

    summary = {"analysespur": info}
    for k, (c, n) in enumerate(zip(cams, names)):
        sp = Path(c["speaking_json"])
        alt = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"fps": fps, "reactions": []}
        n_alt = len([r for r in alt.get("reactions", []) if r.get("type") == "speaking_reaction"])
        rs = []
        for s, e in res[k]["events"]:
            vf = int(s + tzvf[n])
            rs.append({"frame": vf, "timecode": frames_to_timecode(vf, fps), "type": "speaking_reaction",
                       "confidence": 1.0, "dur_s": round((e - s) / fps, 2), "source": "analysespur"})
        sp.write_text(json.dumps({"fps": fps, "reactions": rs, "quelle": "analysespur"},
                                 indent=2, ensure_ascii=False), encoding="utf-8")
        summary[n] = {"einwuerfe": len(rs), "vorher": n_alt}
        print(f"  Einwürfe aus der Analysespur {n}: {len(rs)} (bisherige Erkennung: {n_alt})", flush=True)
    return summary
