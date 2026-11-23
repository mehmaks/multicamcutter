"""Eyeline-Abgleich für den XML-Export: alle Sprecher teilen sich eine Augenlinie.

Ablauf (User 23.11., an Folge 58 erprobt):
1. **Messen** — Augenhöhe je Kamera etwa einmal je Sekunde. Die Reaktionsanalyse liefert
   Proben für ihre Off-Sektionen kostenlos mit (`--eyeline-out`); den Rest misst
   `messe_luecken` per Einzelbild-Sprung (alle `schritt_s` Sekunden).
2. **Ziel-Linie T** — einmal je Folge, fest: so gewählt, dass die mittlere nötige
   Vergrößerung über alle aktiven Clips minimal ist. Alle Kameras dürfen wandern (auch
   die mit dem größten Gesicht). Jeder Clip wird gegen T gerechnet, nie gegen den
   Nachbar-Clip — Anpassungen können sich dadurch nicht aufschaukeln.
3. **Je Clip** — Augenhöhe = Median der Proben im Clip (mind. 3-s-Fenster). Skalierung nur
   so weit, wie die Verschiebung ohne Rand braucht, gedeckelt (`max_scale`). Mehrere
   Personen auf einer Kamera: Mittel ihrer Augenhöhen. Würde ein Gesicht angeschnitten
   → dieser Clip bleibt unangepasst.

**Place on Third** (optional, `drittel=True`, User 23.11.): Ziel-Linie T = oberes Drittel
(1/3). Kameras mit genau einer Person (`einzel`) werden zusätzlich waagerecht verschoben:
Augenmitte auf den Schnittpunkt der oberen mit der linken bzw. rechten Drittel-Linie —
links, wenn die Person (Median über die ganze Folge) in der linken Bildhälfte sitzt,
sonst rechts. Die Seite gilt je Kamera, nicht je Clip (kein Springen). Die maximale
Vergrößerung gilt weiter; reicht sie nicht, geht es so weit Richtung Drittel wie möglich.

Koordinaten relativ zum Bild (0 = oben/links, 1 = unten/rechts). XML-Einheiten
(kalibriert 23.11. in Premiere UND Resolve): Basic Motion `center` vert 0.1 = 10 % der
Bildhöhe nach unten, horiz 0.1 = 10 % der Breite nach rechts; Skalierung um die Mitte.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

L_AUGE = (33, 133)
R_AUGE = (362, 263)
# Gesichtsumriss relativ zum Augenabstand (für den Anschnitt-Schutz, großzügig)
_OBEN, _UNTEN, _SEITE = 2.0, 2.6, 1.6


def augen(face_landmarks, w, h):
    """[[x, augen_y, augenabstand_rel_hoehe], …] je Gesicht."""
    out = []
    for g in face_landmarks or []:
        lx, ly = (g[L_AUGE[0]].x + g[L_AUGE[1]].x) / 2, (g[L_AUGE[0]].y + g[L_AUGE[1]].y) / 2
        rx, ry = (g[R_AUGE[0]].x + g[R_AUGE[1]].x) / 2, (g[R_AUGE[0]].y + g[R_AUGE[1]].y) / 2
        out.append([round((lx + rx) / 2, 4), round((ly + ry) / 2, 4),
                    round(float(np.hypot((rx - lx) * w, (ry - ly) * h) / h), 4)])
    return out


def lade_proben(pfad) -> dict:
    """Analyzer-Proben {video_frame: [gesichter]} (leer, wenn nicht vorhanden)."""
    try:
        d = json.loads(Path(pfad).read_text(encoding="utf-8"))
        return {int(f): g for f, g in d.get("samples", [])}
    except Exception:
        return {}


def messe_luecken(video, vorhanden: dict, fps: float, bereiche=None, schritt_s: float = 4.0,
                  max_faces: int = 1, breite: int = 960, modell=None, fortschritt=None) -> dict:
    """Misst Augen in `bereiche` ([(von, bis)] Video-Frames; None = ganze Datei) alle
    `schritt_s` (kurze Bereiche: einmal in der Mitte), wo keine Probe näher als
    `schritt_s/2` liegt. Einzelbild-Sprünge statt Durchdekodieren: bei 4K-Material ist
    Dekodieren/Lesen der ganzen Datei der Engpass (Folge 58: 107 GB, ~0,4 s je Sprung).
    Gemessen an Folge 58: ganze Datei alle 3 s ≈ 21 min — deshalb nur die Bereiche, in
    denen die Kamera im Schnitt zu sehen ist."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    modell = modell or (Path(__file__).parent / "face_landmarker.task")
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w0, h0 = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    schritt = max(1, int(round(schritt_s * fps)))
    halb = schritt // 2
    belegt = np.array(sorted(vorhanden), dtype=np.int64)

    def frei(f):
        if not len(belegt):
            return True
        i = np.searchsorted(belegt, f)
        nah = min(abs(int(belegt[j]) - f) for j in (i - 1, i) if 0 <= j < len(belegt))
        return nah > halb

    if bereiche is None:
        bereiche = [(0, n)]
    kandidaten = set()
    for a, b in bereiche:
        a, b = max(0, int(a)), min(n - 1, int(b))
        if b <= a:
            continue
        if b - a <= schritt:
            kandidaten.add((a + b) // 2)
        else:
            kandidaten.update(range(a + halb, b, schritt))
    ziele = sorted(f for f in kandidaten if frei(f))
    if not ziele:
        cap.release()
        return {}
    lm = mp_vision.FaceLandmarker.create_from_options(mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(modell)),
        running_mode=mp_vision.RunningMode.IMAGE, num_faces=max(1, max_faces)))
    hb = int(round(breite * h0 / w0)) if w0 else breite * 9 // 16
    out = {}
    for k, f in enumerate(ziele):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        if ok:
            klein = cv2.cvtColor(cv2.resize(img, (breite, hb)), cv2.COLOR_BGR2RGB)
            res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=klein))
            out[f] = augen(res.face_landmarks, breite, hb)
        if fortschritt and k % 20 == 0:
            fortschritt(k / len(ziele))
    cap.release()
    lm.close()
    return out


def messe_alle(kameras: list, fps: float, schritt_s: float = 4.0, fortschritt=None) -> dict:
    """kameras: [{"idx", "video", "proben" (dict), "max_faces", "bereiche"}] → {idx: neue Proben}.
    Kameras parallel (OpenCV/MediaPipe geben den GIL frei)."""
    anteile = {k["idx"]: 0.0 for k in kameras}
    sperre = threading.Lock()
    erg = {}

    def lauf(k):
        def fb(a):
            with sperre:
                anteile[k["idx"]] = a
                if fortschritt:
                    fortschritt(sum(anteile.values()) / len(anteile))
        erg[k["idx"]] = messe_luecken(k["video"], k["proben"], fps, k.get("bereiche"), schritt_s,
                                      k.get("max_faces", 1), fortschritt=fb)

    threads = [threading.Thread(target=lauf, args=(k,)) for k in kameras]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return erg


def skal(T, y):
    """Mindest-Skalierung (um die Bildmitte), um Augenhöhe y ohne Rand auf T zu bringen."""
    if abs(T - y) < 1e-6:
        return 1.0
    return T / y if T > y else (1 - T) / (1 - y)


class EyelinePlan:
    """Bewegung je Clip für build_xml. `proben`: {cam_idx: {video_frame: [gesichter]}}."""

    def __init__(self, proben: dict, fps: float, max_scale: float = 1.15,
                 zooms: dict = None, min_abweichung: float = 0.01, hoehe_zu_breite: float = 9 / 16,
                 messer=None, drittel: bool = False, einzel=None):
        """`messer`: optional f({cam: [(von, bis)]}) → {cam: {frame: gesichter}} — misst
        beim ersten `festlegen` die Augen in den aktiven Clips nach, wo Proben fehlen."""
        self.fps = fps
        self.messer = messer
        self.drittel = bool(drittel)
        self.einzel = set(einzel or [])
        self.proben = {c: dict(d) for c, d in proben.items()}
        self.hzb = hoehe_zu_breite
        self.max_scale = max(1.0, max_scale)
        self.zooms = zooms or {}
        self.min_abw = min_abweichung
        self._reihen_bauen()
        self.T = None
        self.stat = {}

    def _reihen_bauen(self):
        self.reihen = {}
        for c, d in self.proben.items():
            zeilen = []
            for f in sorted(d):
                gs = d[f]
                if gs:
                    zeilen.append((f, float(np.mean([g[1] for g in gs])), gs))
            if zeilen:
                self.reihen[c] = zeilen
        # Place on Third: Ziel-x je Einzel-Kamera (Seite aus der Bildhälfte der Person)
        self.ziel_x = {}
        if self.drittel:
            for c in self.einzel:
                xs = [g[0] for _, _, gs in self.reihen.get(c, []) for g in gs]
                if xs:
                    self.ziel_x[c] = 1 / 3 if float(np.median(xs)) < 0.5 else 2 / 3

    # ── Messwerte je Clip ────────────────────────────────────────────────────
    def _fenster(self, cam, a, b):
        """Proben im Clip (mind. 3 s um die Mitte); ohne Treffer schrittweise breiter."""
        r = self.reihen.get(cam)
        if not r:
            return []
        frames = [z[0] for z in r]
        m = (a + b) // 2
        for min_s in (3, 8, 20):
            min_len = int(min_s * self.fps)
            aa, bb = (a, b) if b - a >= min_len else (m - min_len // 2, m + min_len // 2)
            i0, i1 = np.searchsorted(frames, aa), np.searchsorted(frames, bb, side="right")
            if i1 > i0:
                return r[i0:i1]
        return []

    def clip_y(self, cam, a, b):
        w = self._fenster(cam, a, b)
        return float(np.median([z[1] for z in w])) if w else None

    # ── Ziel-Linie ───────────────────────────────────────────────────────────
    def festlegen(self, aktive_clips):
        """aktive_clips: [(cam, src_in, src_out)] der im Schnitt sichtbaren Clips.
        Setzt die Statistik zurück (je XML-Fassung einmal aufgerufen)."""
        self.stat = {}
        if self.messer is not None:
            bereiche = {}
            for cam, a, b in aktive_clips:
                if cam in self.proben:
                    bereiche.setdefault(cam, []).append((a, b))
            neu = self.messer(bereiche) or {}
            for cam, d in neu.items():
                self.proben.setdefault(cam, {}).update(d)
            self.messer = None          # nur einmal (build_xml läuft je Fassung)
            self._reihen_bauen()
        ys = []
        for cam, a, b in aktive_clips:
            y = self.clip_y(cam, a, b)
            if y is not None:
                ys.append((self.zooms.get(cam, 1.0), y))
        if not ys:
            self.T = None
            return None
        if self.drittel:
            self.T = 1 / 3
            return self.T
        lo = min(y for _, y in ys) - 0.02
        hi = max(y for _, y in ys) + 0.02

        def kosten(T):
            return float(np.mean([min(max(z, skal(T, y)) / z, self.max_scale) for z, y in ys]))

        self.T = float(min(np.linspace(lo, hi, 300), key=kosten))
        return self.T

    # ── Bewegung je Clip ─────────────────────────────────────────────────────
    def bewegung(self, cam, a, b, aktiv=True):
        """(skalierung, vert, horiz) oder None (= wie bisher: nur der Totalen-Zoom)."""
        if self.T is None or cam not in self.reihen:
            return None
        z = self.zooms.get(cam, 1.0)
        w = self._fenster(cam, a, b)
        if not w:
            return None
        y = float(np.median([s[1] for s in w]))
        Tx = self.ziel_x.get(cam)
        if Tx is not None:
            x = float(np.median([g[0] for s in w for g in s[2]]))
        st = self.stat.setdefault(cam, {"skal": [], "gedeckelt": 0, "angeschnitten": 0})
        passt_y = abs(0.5 + z * (y - 0.5) - self.T) < self.min_abw
        passt_x = Tx is None or abs(0.5 + z * (x - 0.5) - Tx) < self.min_abw
        if passt_y and passt_x:
            if aktiv:
                st["skal"].append(z)
            return None
        roh = max(z, skal(self.T, y), skal(Tx, x) if Tx is not None else 1.0)
        S = min(roh, z * self.max_scale)
        lim = (S - 1) / 2
        t = max(-lim, min(lim, self.T - 0.5 - S * (y - 0.5)))
        h = max(-lim, min(lim, Tx - 0.5 - S * (x - 0.5))) if Tx is not None else 0.0
        # Anschnitt-Schutz: sichtbarer Quellbereich nach Skalierung/Verschiebung
        y0, y1 = 0.5 + (0 - 0.5 - t) / S, 0.5 + (1 - 0.5 - t) / S
        x0, x1 = 0.5 + (0 - 0.5 - h) / S, 0.5 + (1 - 0.5 - h) / S
        gesichter = [g for s in w for g in s[2]]
        if gesichter:
            # 10-%-Perzentil der Ränder: einzelne Ausreißer-Proben kippen den Clip nicht
            oben = np.quantile([g[1] - _OBEN * g[2] for g in gesichter], 0.1)
            unten = np.quantile([g[1] + _UNTEN * g[2] for g in gesichter], 0.9)
            links = np.quantile([g[0] - _SEITE * g[2] * self.hzb for g in gesichter], 0.1)
            rechts = np.quantile([g[0] + _SEITE * g[2] * self.hzb for g in gesichter], 0.9)
            war_drin = (oben >= 0 and unten <= 1 and links >= 0 and rechts <= 1)
            jetzt_drin = (oben >= y0 and unten <= y1 and links >= x0 and rechts <= x1)
            if war_drin and not jetzt_drin:
                if aktiv:
                    st["angeschnitten"] += 1
                    st["skal"].append(z)
                return None
        if aktiv:
            st["skal"].append(S)
            if roh > S + 1e-6:
                st["gedeckelt"] += 1
        return S, t, h

    def zusammenfassung(self):
        """{cam: {median, max, gedeckelt, angeschnitten, clips}} (Skalierung in %)."""
        out = {}
        for cam, st in self.stat.items():
            if not st["skal"]:
                continue
            s = np.array(st["skal"]) * 100
            out[cam] = {"median": round(float(np.median(s)), 1), "max": round(float(s.max()), 1),
                        "gedeckelt": st["gedeckelt"], "angeschnitten": st["angeschnitten"],
                        "clips": len(s)}
        return out
