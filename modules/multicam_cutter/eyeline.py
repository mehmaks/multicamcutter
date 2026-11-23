"""Eyeline-Abgleich für den XML-Export: alle Sprecher teilen sich eine Augenlinie.

Ablauf (User 23.11., an Folge 58 erprobt):
1. **Messen** — nur in den aktiven Clips (User 23.11.: beim Zuhören setzen sich Leute
   anders hin, greifen zum Glas — das verfälscht die Eyeline), ab Clipstart alle 0,4 s,
   mind. 3 Bilder je Clip. `messe_clips` liest die Clips am Stück (Cache im Arbeitsordner).
2. **Ziel-Linie T** — einmal je Folge, fest: so gewählt, dass die mittlere nötige
   Vergrößerung über alle aktiven Clips minimal ist. Alle Kameras dürfen wandern (auch
   die mit dem größten Gesicht). Jeder Clip wird gegen T gerechnet, nie gegen den
   Nachbar-Clip — Anpassungen können sich dadurch nicht aufschaukeln.
3. **Je Clip** — Augenhöhe = Median der Proben im Clip (= wo die Person überwiegend ist). Skalierung nur
   so weit, wie die Verschiebung ohne Rand braucht, gedeckelt (`max_scale`). Mehrere
   Personen auf einer Kamera: Mittel ihrer Augenhöhen. Würde ein Gesicht angeschnitten
   → dieser Clip bleibt unangepasst.

**Goldener Schnitt** (optional, `drittel=True`, User 23.11.): Ziel-Linie T = `linie_y` (von
oben, Standard 0,382). Kameras mit genau einer Person (`einzel`) werden zusätzlich waagerecht
verschoben: Augenmitte auf `linie_x` von der linken bzw. rechten Kante — links, wenn die
Person (Median über ihre Clips) in der linken Bildhälfte sitzt, sonst rechts. Die Seite gilt
je Kamera, nicht je Clip (kein Springen). Die maximale Vergrößerung gilt weiter; reicht sie
nicht, geht es so weit Richtung Linie wie möglich. (Erst als Drittel erprobt — 1/3 war dem
User zu extrem und lief fast immer in den Deckel.)

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


def ziel_bilder(bereiche, fps: float, abstand_s: float = 0.4, mindestens: int = 3) -> list:
    """Messbilder in den Bereichen [(von, bis)]: ab Clipstart alle `abstand_s`; kurze
    Clips bekommen trotzdem `mindestens` Bilder, gleichmäßig verteilt."""
    schritt = max(1, int(round(abstand_s * fps)))
    out = set()
    for a, b in bereiche:
        a, b = int(a), int(b)
        if b <= a:
            continue
        regel = range(a, b, schritt)
        if len(regel) >= mindestens:
            out.update(regel)
        else:
            out.update(int(a + (b - a) * (k + 0.5) / mindestens) for k in range(mindestens))
    return sorted(out)


def messe_clips(video, bereiche, fps: float, vorhanden=None, abstand_s: float = 0.4,
                max_faces: int = 1, breite: int = 960, modell=None, fortschritt=None) -> dict:
    """Misst die Augen in den Bereichen (= aktive Clips, Video-Frames) alle `abstand_s`.
    Liest am Stück statt Einzelbilder anzuspringen: ein Sprung kostet bei 4K-Material
    0,4–0,6 s, Durchdekodieren ~140–190 Bilder/s (Folge 63, 23.11.). Gesprungen wird nur
    über Lücken > 3 s. Bilder aus `vorhanden` (Cache) werden übersprungen."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    vorhanden = vorhanden or {}
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w0, h0 = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    ziele = [f for f in ziel_bilder(bereiche, fps, abstand_s) if f not in vorhanden and 0 <= f < n]
    if not ziele:
        cap.release()
        return {}
    modell = modell or (Path(__file__).parent / "face_landmarker.task")
    lm = mp_vision.FaceLandmarker.create_from_options(mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(modell)),
        running_mode=mp_vision.RunningMode.IMAGE, num_faces=max(1, max_faces)))
    hb = int(round(breite * h0 / w0)) if w0 else breite * 9 // 16
    sprung_ab = int(3 * fps)
    pos = None                      # nächstes Bild, das der Decoder liefert
    out = {}
    for k, f in enumerate(ziele):
        if pos is None or f < pos or f - pos > sprung_ab:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            pos = f
        while pos < f:
            cap.grab()
            pos += 1
        ok, img = cap.read()
        pos += 1
        if ok:
            klein = cv2.cvtColor(cv2.resize(img, (breite, hb)), cv2.COLOR_BGR2RGB)
            res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=klein))
            out[f] = augen(res.face_landmarks, breite, hb)
        if fortschritt and k % 50 == 0:
            fortschritt(k / len(ziele))
    cap.release()
    lm.close()
    return out


def messe_alle(kameras: list, fps: float, abstand_s: float = 0.4, fortschritt=None) -> dict:
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
        erg[k["idx"]] = messe_clips(k["video"], k.get("bereiche") or [], fps, k["proben"],
                                    abstand_s, k.get("max_faces", 1), fortschritt=fb)

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
                 messer=None, drittel: bool = False, einzel=None,
                 linie_x: float = 0.382, linie_y: float = 0.382):
        """`messer`: optional f({cam: [(von, bis)]}) → {cam: {frame: gesichter}} — misst
        beim ersten `festlegen` die Augen in den aktiven Clips nach, wo Proben fehlen."""
        self.fps = fps
        self.messer = messer
        self.drittel = bool(drittel)
        # Linien als Anteil: y von oben, x von der linken bzw. rechten Kante (0.382 = gold. Schnitt)
        self.linie_x, self.linie_y = float(linie_x), float(linie_y)
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
        # Goldener Schnitt: Ziel-x je Einzel-Kamera (Seite aus der Bildhälfte der Person)
        self.ziel_x = {}
        if self.drittel:
            for c in self.einzel:
                xs = [g[0] for _, _, gs in self.reihen.get(c, []) for g in gs]
                if xs:
                    self.ziel_x[c] = self.linie_x if float(np.median(xs)) < 0.5 else 1 - self.linie_x

    # ── Messwerte je Clip ────────────────────────────────────────────────────
    def _fenster(self, cam, a, b):
        """Proben im Clip selbst; nur wenn dort keine Augen erkannt wurden, schrittweise
        ein breiteres Fenster um die Clipmitte (3/8/20 s)."""
        r = self.reihen.get(cam)
        if not r:
            return []
        frames = [z[0] for z in r]
        m = (a + b) // 2
        for min_s in (0, 3, 8, 20):
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
            self.T = self.linie_y
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
