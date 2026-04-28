#!/usr/bin/env python3
"""
Video Reaction Analyzer
Analysiert exportierte Multicam-Videos auf Reaktionen
Kann unabhängig von Resolve laufen für Testing
"""

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision
import numpy as np
import math
from pathlib import Path
import json
import subprocess
from collections import deque
import argparse
import os
import time
import urllib.request


_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
_MODEL_PATH = Path(__file__).parent / "face_landmarker.task"
_ROOT = Path(__file__).resolve().parent.parent.parent
_PATTERNS_PATH = _ROOT / "config" / "nodding_patterns.json"


def _load_nod_patterns(path=None):
    """Lädt Nodding-Pattern-Definitionen aus JSON."""
    p = path or _PATTERNS_PATH
    with open(p, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['global'], [pat for pat in data['patterns'] if pat.get('enabled', True)]


def _ensure_model():
    """Lädt face_landmarker.task herunter falls nicht vorhanden."""
    if _MODEL_PATH.exists():
        return
    print(f"⬇ face_landmarker.task nicht gefunden — lade herunter...")
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    print(f"✓ Modell gespeichert: {_MODEL_PATH}")


def load_params(params_path: str = None) -> dict:
    """Lädt Parameter aus params.json."""
    if params_path and os.path.exists(params_path):
        params = json.loads(Path(params_path).read_text())
        print(f"✓ Params geladen: {params_path}")
        return params
    print("⚠️  params.json nicht gefunden, nutze Default-Werte")
    return {}


class AdvancedReactionDetector:
    """Verbesserte Reaktionserkennung mit mehr Features"""
    
    def __init__(self, sensitivity='medium', fps=25.0, params=None, auto_accuracy=False):
        if params is None:
            params = {}
        # Anzahl gleichzeitig erkannter Gesichter (konfigurierbar für Totalen / Zweier-Shots)
        max_faces = int(params.get('max_faces', 1))

        # MediaPipe FaceLandmarker (Tasks API, mediapipe >= 0.10)
        _ensure_model()
        base_options = mp_tasks.BaseOptions(model_asset_path=str(_MODEL_PATH))
        options = mp_vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_faces=max_faces,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.face_landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        self._last_result = None  # letztes FaceLandmarker-Ergebnis (für Preview-Overlay)

        # Video FPS (für Speaking-Detection timing)
        self.fps = fps

        # Lade Sensitivität aus Params wenn vorhanden
        if params.get('default_sensitivity'):
            sensitivity = params['default_sensitivity']

        # ── Nodding: Pattern-basierter Detektor (Parameter aus nodding_patterns.json) ──
        self._nod_globals, self._nod_patterns = _load_nod_patterns()
        self._nod_threshold = self._nod_globals['nod_threshold']
        self._nod_cooldown_frames = int(self._nod_globals['cooldown_s'] * fps)
        self._nod_auto_accuracy_ref = self._nod_globals['auto_accuracy_ref']
        self._nod_smooth_kernel = self._nod_globals['smooth_kernel']
        self._nod_calibration_height = self._nod_globals['calibration_height']
        self._nod_settle_frames = int(self._nod_globals.get('settle_s', 0) * fps)
        # Buffer-Größe = längstes Pattern-Window
        max_window = max(p['window_s'] for p in self._nod_patterns)
        self._nod_window_frames = int(max_window * fps)

        # Laughing-Threshold: weiterhin sensitiv-abhängig
        laugh_threshold_low = 1.7
        laugh_threshold_medium = 1.5
        laugh_threshold_high = 1.3
        if 'laugh_threshold_low' in params:
            laugh_threshold_low = float(params['laugh_threshold_low'])
        if 'laugh_threshold_medium' in params:
            laugh_threshold_medium = float(params['laugh_threshold_medium'])
        if 'laugh_threshold_high' in params:
            laugh_threshold_high = float(params['laugh_threshold_high'])

        laugh_settings = {
            'low':    {'laugh_threshold': laugh_threshold_low},
            'medium': {'laugh_threshold': laugh_threshold_medium},
            'high':   {'laugh_threshold': laugh_threshold_high},
        }
        self.settings = laugh_settings.get(sensitivity, laugh_settings['medium'])

        # Reaktionstypen Enables aus Config laden
        self.enabled_reactions = {
            'nodding': True,
            'head_shake': True,
            'laughing': True,
            'eyebrow_raise': True
        }

        if 'nodding_enabled' in params:
            self.enabled_reactions['nodding'] = bool(params['nodding_enabled'])
        if 'head_shake_enabled' in params:
            self.enabled_reactions['head_shake'] = bool(params['head_shake_enabled'])
        if 'laughing_enabled' in params:
            self.enabled_reactions['laughing'] = bool(params['laughing_enabled'])
        if 'eyebrow_raise_enabled' in params:
            self.enabled_reactions['eyebrow_raise'] = bool(params['eyebrow_raise_enabled'])

        # Kalibrierungs-Auflösung (für andere Detektoren wie HeadShake)
        self.calibration_height = self._nod_calibration_height
        if 'calibration_height' in params:
            self.calibration_height = int(params['calibration_height'])

        # Auto Accuracy: immer aktiv im Pattern-Detektor (über face_h Skalierung)
        self.auto_accuracy = auto_accuracy

        # Per-Gesicht-Historien (keyed by Sortier-Index = links→rechts-Position im Frame)
        # Separate Deques pro Gesicht verhindern Vermischung bei mehreren Personen
        self._face_states: dict = {}

    def _get_face_state(self, face_idx: int) -> dict:
        """Gibt den Zustand (Historien + Cooldowns) für ein Gesicht zurück, legt ihn bei Bedarf an."""
        if face_idx not in self._face_states:
            wf = self._nod_window_frames
            self._face_states[face_idx] = {
                'nose_y':           deque(maxlen=wf),
                'nose_x':           deque(maxlen=wf),
                'bridge_y':         deque(maxlen=wf),
                'head_tilt':        deque(maxlen=wf),
                'head_yaw':         deque(maxlen=wf),
                'head_x_history':   deque(maxlen=30),
                'mouth_history':    deque(maxlen=20),
                'eyebrow_history':  deque(maxlen=15),
                'last_nod_frame':   -999,
                'last_laugh_frame': -100,
                '_pending_conf':    0,
                '_pending_first':   0,
                '_pending_frame':   0,
                '_pending_start':   0,
                '_pending_tail':    0,
            }
        return self._face_states[face_idx]

    def reset_history(self):
        """Setzt alle Bewegungs-Historien zurück (beim Betreten einer neuen Off-Sektion).
        Pending Nod-Detections werden verworfen — sie gehören zur vorigen Sektion."""
        self._face_states.clear()
    
    def get_landmark_coord(self, landmarks, index, width, height):
        """Holt Landmark-Koordinaten in Pixel"""
        lm = landmarks[index]
        return int(lm.x * width), int(lm.y * height)
    
    def _check_nod_pattern(self, pat, y_arr, x_arr, b_arr, thr,
                           tilt_arr=None, yaw_arr=None):
        """Prüft ein einzelnes Nodding-Pattern gegen die Signaldaten.
        Returns (passed, confidence, pattern_offset) — pattern_offset ist die
        Anzahl Frames vom aktuellen Frame zurück zum Beginn des Patterns
        (erste Bewegung vor dem ersten Reversal). 0 bei Nicht-Detection."""
        f = pat['filters']
        c = pat['confidence']
        k = self._nod_smooth_kernel

        # Window zuschneiden
        win_frames = int(pat['window_s'] * self.fps)
        y = y_arr[-win_frames:]
        x = x_arr[-win_frames:]
        b = b_arr[-win_frames:]

        y_range = y.max() - y.min()
        x_range = x.max() - x.min()

        FAIL = (False, 0.0, 0, 0)

        # X-Drift-Check mit Tilt- und Yaw-Korrektur
        #
        # Zwei geometrische Effekte erzeugen erwartete X-Komponenten beim Nicken:
        # 1) Tilt: Kopf seitlich geneigt → Nicken hat X-Anteil = y * |tan(tilt)|
        # 2) Yaw:  Kopf zur Seite gedreht (Halbprofil) → Nicken erzeugt
        #    Bogen-Projektion mit X-Anteil proportional zur Drehung
        #
        # Nur die darüber hinausgehende X-Bewegung gilt als echter Drift.
        x_drift_ratio = f.get('x_drift_ratio', 0.7)
        expected_x_total = 0.0
        if tilt_arr is not None and len(tilt_arr) > 0:
            t = tilt_arr[-win_frames:]
            median_tilt = float(np.median(t))
            expected_x_total += y_range * abs(math.tan(median_tilt))
        if yaw_arr is not None and len(yaw_arr) > 0:
            yw = yaw_arr[-win_frames:]
            median_yaw = float(np.median(yw))
            yaw_dev = abs(median_yaw - 0.5) * 2.0  # 0=frontal, 1=Profil
            expected_x_total += y_range * yaw_dev * 1.2
        corrected_x = max(0.0, x_range - expected_x_total)
        if y_range > 0 and corrected_x >= x_drift_ratio * (y_range ** 0.7):
            return FAIL

        # Glätten + Velocities
        y_smooth = np.convolve(y, np.ones(k) / k, mode='valid')
        b_smooth = np.convolve(b, np.ones(k) / k, mode='valid')
        vel_y = np.diff(y_smooth)
        vel_b = np.diff(b_smooth)

        # Richtungsumkehrungen
        rev_indices = []
        for i in range(1, len(vel_y)):
            if vel_y[i - 1] * vel_y[i] < 0:
                rev_indices.append(i)
        reversals = len(rev_indices)

        # Reversal-Range prüfen
        min_rev = f.get('min_reversals', 0)
        max_rev = f.get('max_reversals')
        if reversals < min_rev:
            return FAIL
        if max_rev is not None and reversals > max_rev:
            return FAIL

        # Pattern-relevante Reversals: die letzten min_rev bilden das Pattern
        pattern_revs = rev_indices[-min_rev:] if min_rev > 0 else rev_indices

        # Nose↔Bridge Korrelation
        if len(vel_y) >= 5 and len(vel_b) >= 5:
            n = min(len(vel_y), len(vel_b))
            corr = float(np.corrcoef(vel_y[:n], vel_b[:n])[0, 1])
            if np.isnan(corr):
                corr = 0.0
        else:
            corr = 0.0

        min_corr = f.get('min_correlation', 0.85)
        if corr < min_corr:
            return FAIL

        # Frequenz-Check (nur wenn max_reversal_gap definiert)
        median_gap = 0.0
        max_gap = f.get('max_reversal_gap')
        if max_gap is not None and len(pattern_revs) >= 2:
            rev_gaps = np.diff(pattern_revs)
            median_gap = float(np.median(rev_gaps))
            if median_gap > max_gap:
                return FAIL

        # Oszillations-Bereich: von einer Gap-Länge vor dem ersten
        # Pattern-Reversal bis zum Fenster-Ende. Damit messen Amplitude,
        # Dämpfung und Ratio nur die tatsächliche Oszillation.
        if len(pattern_revs) >= 2:
            typical_gap = int(np.median(np.diff(pattern_revs)))
        else:
            typical_gap = max_gap or 7
        osc_start = max(0, pattern_revs[0] - typical_gap)
        osc_y = y_smooth[osc_start:]
        osc_y_range = float(osc_y.max() - osc_y.min())

        # Dämpfung + Halbamplituden (nur über Pattern-Reversals)
        damping_ratio = 0.5
        half_amplitudes = []
        min_damp = f.get('min_damping')
        if len(pattern_revs) >= 2:
            osc_bounds = [osc_start] + list(pattern_revs) + [len(y_smooth) - 1]
            for i in range(len(osc_bounds) - 1):
                seg = y_smooth[osc_bounds[i]:osc_bounds[i + 1] + 1]
                if len(seg) >= 2:
                    half_amplitudes.append(seg.max() - seg.min())
            if len(half_amplitudes) >= 3:
                dc = sum(1 for i in range(1, len(half_amplitudes) - 1)
                         if half_amplitudes[i + 1] <= half_amplitudes[i] * 1.1)
                damping_ratio = dc / (len(half_amplitudes) - 2)
            if min_damp is not None and len(half_amplitudes) >= 3:
                if damping_ratio < min_damp:
                    return FAIL

        # Mindest-Verhältnis der 2. Halbschwingung zur 1.
        min_amp_ratio = f.get('min_amplitude_ratio')
        if min_amp_ratio is not None and len(half_amplitudes) >= 2:
            ratio = half_amplitudes[1] / half_amplitudes[0] if half_amplitudes[0] > 0 else 0
            if ratio < min_amp_ratio:
                return FAIL

        # Amplitude-Threshold (gegen Oszillations-Range, nicht Fenster-Range)
        amp_factor = f.get('amplitude_factor', 1.0)
        effective_thr = thr * amp_factor

        # Dynamischer Threshold (nur wenn konfiguriert)
        dyn = f.get('dynamic_threshold')
        if dyn and dyn.get('enabled') and len(pattern_revs) >= 2:
            osc_strength = min(len(pattern_revs) / 4.0, 1.0) * corr
            max_red = dyn.get('max_reduction', 0.4)
            effective_thr = thr * (1.0 - max_red * osc_strength)

        if osc_y_range < effective_thr:
            return FAIL

        # Return-to-Baseline (nur wenn konfiguriert)
        max_drift_ratio = f.get('return_to_baseline')
        baseline_drift = 0.0
        if max_drift_ratio is not None:
            n_edge = max(3, len(y_smooth) // 5)
            start_mean = np.mean(y_smooth[:n_edge])
            end_mean = np.mean(y_smooth[-n_edge:])
            baseline_drift = abs(end_mean - start_mean)
            if baseline_drift > y_range * max_drift_ratio:
                return FAIL

        # V-Form Geschwindigkeit (nur wenn konfiguriert)
        max_v_dur = f.get('max_v_duration_s')
        if max_v_dur is not None and reversals >= 1:
            rev_pos = rev_indices[0]
            total_len = len(y_smooth)
            max_v_frames = int(max_v_dur * self.fps)
            if total_len - rev_pos > max_v_frames and rev_pos > max_v_frames:
                return FAIL

        # ── Pattern-Start-Offset berechnen ───────────────────────────
        # Die letzten min_reversals Umkehrungen bilden das auslösende Pattern.
        # rev_indices[-min_rev] ist der Beginn dieser Gruppe im vel_y-Array.
        # + k korrigiert für convolve(valid) + diff.
        pattern_rev_idx = rev_indices[-min_rev] if min_rev <= len(rev_indices) else rev_indices[0]
        pattern_start_in_window = pattern_rev_idx + k
        pattern_offset = len(y) - pattern_start_in_window

        # ── Alle Filter bestanden → Confidence berechnen ─────────────
        weights = c['weights']
        scores = {}

        if 'reversals' in weights:
            scores['reversals'] = min((reversals - 1) / 5.0, 1.0)
        if 'frequency' in weights:
            scores['frequency'] = max(0, 1.0 - (median_gap - 2) / 8.0) if median_gap > 0 else 0.5
        if 'damping' in weights:
            scores['damping'] = damping_ratio
        if 'correlation' in weights:
            scores['correlation'] = min((corr - min_corr) / max(0.01, 1.0 - min_corr), 1.0)
        if 'amplitude' in weights:
            scores['amplitude'] = max(0.0, min((y_range / effective_thr - 1.0) * 2.0 + 0.5, 1.0))
        if 'return_to_baseline' in weights:
            max_dr = max_drift_ratio if max_drift_ratio else 0.45
            scores['return_to_baseline'] = max(0.0, 1.0 - baseline_drift / (y_range * max_dr))

        confidence = sum(weights[wk] * scores[wk] for wk in weights if wk in scores)
        confidence *= c.get('multiplier', 1.0)
        confidence = min(confidence, c.get('max', 1.0))

        # tail_frames: geschätzte Ausklingzeit nach dem letzten Reversal
        # (ein typical_gap = eine halbe Schwingung Nachlauf)
        last_rev_in_window = rev_indices[-1] + k
        tail_frames = typical_gap

        return True, confidence, pattern_offset, tail_frames

    def _fire_pending_nod(self, state):
        """Feuert eine ausstehende Nod-Detection und räumt den Pending-State auf.
        Returns (True, confidence, first_frame, peak_frame, tail_frames, pattern_name).
        first_frame  = erster Detection-Frame (Cutaway-Ankerpunkt).
        peak_frame   = Frame mit höchster Confidence (für Dauer-Berechnung).
        tail_frames  = geschätzte Ausklingzeit nach dem letzten Reversal."""
        conf = state['_pending_conf']
        first_frame = state['_pending_first']
        peak_frame = state['_pending_frame']
        tail_frames = state.get('_pending_tail', 0)
        pattern_name = state.get('_pending_pattern', '')
        state['last_nod_frame'] = peak_frame
        state['_pending_conf'] = 0
        state['_pending_first'] = 0
        state['_pending_frame'] = 0
        state['_pending_start'] = 0
        state['_pending_tail'] = 0
        state['_pending_pattern'] = ''
        state['nose_y'].clear()
        state['nose_x'].clear()
        state['bridge_y'].clear()
        return True, conf, first_frame, peak_frame, tail_frames, pattern_name

    def detect_nodding(self, landmarks, frame_number, height, width, state: dict):
        """Pattern-basierte Nicken-Erkennung mit Delayed-Fire.

        Nach erster Detection wird eine Beobachtungsphase (settle_s) gestartet.
        Während dieser Phase wird weiter geprüft — kommt eine stärkere Detection,
        wird deren Confidence übernommen. Am Ende der Phase feuert die Detection.

        Returns (detected, confidence, first_frame, peak_frame, tail_frames).
        first_frame  = Frame der ersten Detection (Cutaway-Ankerpunkt).
        peak_frame   = Frame mit höchster Confidence (für Dauer-Berechnung).
        tail_frames  = geschätzte Ausklingzeit nach dem letzten Reversal.
        """
        # Landmarks tracken: Nase (L1) und Nasenrücken (L6)
        nose_y = landmarks[1].y * height
        nose_x = landmarks[1].x * width
        bridge_y = landmarks[6].y * height
        state['nose_y'].append(nose_y)
        state['nose_x'].append(nose_x)
        state['bridge_y'].append(bridge_y)

        # Kopfneigung tracken (Stirn L10 → Kinn L152) für Tilt-Korrektur im X-Drift-Check
        tilt = math.atan2(
            landmarks[10].x * width - landmarks[152].x * width,
            landmarks[152].y * height - landmarks[10].y * height,
        )
        state['head_tilt'].append(tilt)

        # Yaw-Schätzung: Nasenrücken-Position relativ zu den Augen-Landmarks
        # yaw_ratio ≈ 0.5 → frontal, Abweichung → Kopf gedreht
        left_eye_x = landmarks[33].x * width
        right_eye_x = landmarks[263].x * width
        bridge_x = landmarks[6].x * width
        eye_span = right_eye_x - left_eye_x
        if abs(eye_span) > 1.0:
            yaw_ratio = (bridge_x - left_eye_x) / eye_span
        else:
            yaw_ratio = 0.5
        state['head_yaw'].append(yaw_ratio)

        min_frames = max(15, int(0.4 * self.fps))
        NO = (False, 0.0, frame_number, frame_number, 0, '')
        if len(state['nose_y']) < min_frames:
            return NO

        settle = self._nod_settle_frames

        # ── Settle-Phase aktiv: beobachten ob stärkere Detection kommt ──
        if state['_pending_conf'] > 0:
            # Pattern-Check weiterführen (Buffer wird NICHT geleert)
            y_arr = np.array(state['nose_y'])
            x_arr = np.array(state['nose_x'])
            b_arr = np.array(state['bridge_y'])
            t_arr = np.array(state['head_tilt'])
            yw_arr = np.array(state['head_yaw'])

            res_scale = height / self._nod_calibration_height
            thr = self._nod_threshold * res_scale
            face_h = abs(landmarks[10].y - landmarks[152].y)
            if face_h > 0.05:
                face_scale = max(0.3, min(2.0, face_h / self._nod_auto_accuracy_ref))
                thr *= face_scale

            for pat in self._nod_patterns:
                passed, conf, _, tail = self._check_nod_pattern(
                    pat, y_arr, x_arr, b_arr, thr, t_arr, yw_arr)
                if passed and conf > state['_pending_conf']:
                    state['_pending_conf'] = conf
                    state['_pending_frame'] = frame_number
                    state['_pending_tail'] = tail
                    state['_pending_pattern'] = pat['name']

            # Settle-Window abgelaufen → feuern
            if frame_number - state['_pending_start'] >= settle:
                return self._fire_pending_nod(state)

            return NO

        # ── Kein Pending: normaler Cooldown-Check ──
        if frame_number - state['last_nod_frame'] <= self._nod_cooldown_frames:
            return NO

        # Signale vorbereiten
        y_arr = np.array(state['nose_y'])
        x_arr = np.array(state['nose_x'])
        b_arr = np.array(state['bridge_y'])
        t_arr = np.array(state['head_tilt'])
        yw_arr = np.array(state['head_yaw'])

        # Threshold skalieren auf Auflösung und Gesichtsgröße
        res_scale = height / self._nod_calibration_height
        thr = self._nod_threshold * res_scale
        face_h = abs(landmarks[10].y - landmarks[152].y)
        if face_h > 0.05:
            face_scale = max(0.3, min(2.0, face_h / self._nod_auto_accuracy_ref))
            thr *= face_scale

        # Alle Patterns prüfen — höchste Confidence gewinnt
        best_conf = 0.0
        best_offset = 0
        best_tail = 0
        best_pattern = None
        for pat in self._nod_patterns:
            passed, conf, offset, tail = self._check_nod_pattern(
                pat, y_arr, x_arr, b_arr, thr, t_arr, yw_arr)
            if passed and conf > best_conf:
                best_conf = conf
                best_offset = offset
                best_tail = tail
                best_pattern = pat['name']

        if best_conf > 0:
            # Pattern-Start: aktueller Frame minus Offset zum ersten Reversal
            pattern_start_frame = frame_number - best_offset
            if settle > 0:
                # Settle-Phase starten — noch nicht feuern
                state['_pending_conf'] = best_conf
                state['_pending_first'] = pattern_start_frame
                state['_pending_frame'] = frame_number
                state['_pending_start'] = frame_number
                state['_pending_tail'] = best_tail
                state['_pending_pattern'] = best_pattern
                return NO
            else:
                # Kein Settle → sofort feuern (altes Verhalten)
                state['last_nod_frame'] = frame_number
                state['nose_y'].clear()
                state['nose_x'].clear()
                state['bridge_y'].clear()
                return True, best_conf, pattern_start_frame, frame_number, best_tail, best_pattern

        return NO
    
    def detect_head_shake(self, landmarks, frame_number, width, state: dict):
        """Erkennt Kopfschütteln (nein-nein)"""
        nose_x = landmarks[1].x * width
        state['head_x_history'].append(nose_x)

        if len(state['head_x_history']) < 30:
            return False, 0.0

        positions = list(state['head_x_history'])
        movement_range = max(positions) - min(positions)
        
        # Kopfschütteln = horizontale Bewegung (Thresholds skaliert auf tatsächliche Auflösung)
        calibration_width = self.calibration_height * 16 / 9
        res_scale_x = width / calibration_width
        if movement_range > 25 * res_scale_x:
            confidence = min(movement_range / (40.0 * res_scale_x), 1.0)
            return True, confidence
        
        return False, 0.0
    
    def detect_laughing(self, landmarks, frame_number, state: dict):
        """Verbesserte Lach-Erkennung"""
        # Mundpunkte: Oberlippe (13), Unterlippe (14)
        # Mundwinkel: Links (78), Rechts (308)
        upper_lip = landmarks[13]
        lower_lip = landmarks[14]
        left_mouth = landmarks[78]
        right_mouth = landmarks[308]

        # Vertikale Mundöffnung
        mouth_open_v = abs(upper_lip.y - lower_lip.y)

        # Horizontale Mundbreite (Lachen = breiterer Mund)
        mouth_width = abs(left_mouth.x - right_mouth.x)

        # Kombinierter Mouth-Score
        mouth_score = mouth_open_v * mouth_width

        state['mouth_history'].append(mouth_score)

        if len(state['mouth_history']) < 10:
            return False, 0.0

        # Cooldown
        if frame_number - state['last_laugh_frame'] < 20:  # Mind. 0.66s
            return False, 0.0

        # Durchschnitt der letzten Frames
        recent_avg = np.mean(list(state['mouth_history'])[-10:])
        baseline_avg = np.mean(list(state['mouth_history'])[:10])

        # Lachen = deutlich größerer Mund als Baseline
        threshold = self.settings['laugh_threshold']
        if recent_avg > baseline_avg * threshold and mouth_score > 0.003:
            confidence = min((recent_avg / baseline_avg - 1.0), 1.0)
            state['last_laugh_frame'] = frame_number
            return True, confidence

        return False, 0.0
    
    def detect_eyebrow_raise(self, landmarks, state: dict):
        """Erkennt Augenbrauen hochziehen (Überraschung)"""
        # Augenbrauen-Landmarks: 70, 300 (über den Augen)
        # Augen-Landmarks: 159, 386 (Augenmitte)
        left_brow = landmarks[70]
        right_brow = landmarks[300]
        left_eye = landmarks[159]
        right_eye = landmarks[386]

        # Distanz Augenbraue zu Auge
        left_dist = abs(left_brow.y - left_eye.y)
        right_dist = abs(right_brow.y - right_eye.y)
        avg_dist = (left_dist + right_dist) / 2

        state['eyebrow_history'].append(avg_dist)

        if len(state['eyebrow_history']) < 15:
            return False, 0.0

        # Augenbrauen hochgezogen = größere Distanz
        baseline = np.mean(list(state['eyebrow_history'])[:10])
        current = avg_dist

        if current > baseline * 1.3:
            confidence = min((current / baseline - 1.0) * 2, 1.0)
            return True, confidence

        return False, 0.0
    
    def analyze_frame(self, frame, frame_number):
        """
        Analysiert Frame auf alle Reaktionstypen.

        Bei mehreren erkannten Gesichtern (num_faces > 1) wird OR-Logik verwendet:
        Reagiert IRGENDEINES der Gesichter → Reaktion registrieren (höchste Confidence).
        Gesichter werden nach x-Position sortiert (links→rechts) für stabiles per-Gesicht-Tracking.
        """
        height, width = frame.shape[:2]

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = int(frame_number * 1000 / self.fps)
        result = self.face_landmarker.detect_for_video(mp_image, timestamp_ms)
        self._last_result = result

        n_faces = len(result.face_landmarks) if result.face_landmarks else 0
        reactions = {
            'nodding':      {'detected': False, 'confidence': 0.0},
            'head_shake':   {'detected': False, 'confidence': 0.0},
            'laughing':     {'detected': False, 'confidence': 0.0},
            'eyebrow_raise':{'detected': False, 'confidence': 0.0},
            'face_detected': n_faces > 0,
            'face_count':    n_faces,
        }

        if not result.face_landmarks:
            return reactions

        # Sortiere Gesichter nach x-Position der Nase (links→rechts) für stabiles Tracking
        sorted_faces = sorted(result.face_landmarks, key=lambda lm: lm[1].x)

        for face_idx, landmarks in enumerate(sorted_faces):
            state = self._get_face_state(face_idx)

            if self.enabled_reactions.get('nodding', True):
                det, conf, first_frame, peak_frame, tail, pat_name = self.detect_nodding(landmarks, frame_number, height, width, state)
                if det and conf > reactions['nodding']['confidence']:
                    reactions['nodding'] = {
                        'detected': True, 'confidence': conf,
                        'frame': first_frame, 'peak_frame': peak_frame,
                        'tail_frames': tail, 'pattern': pat_name,
                    }

            if self.enabled_reactions.get('head_shake', True):
                det, conf = self.detect_head_shake(landmarks, frame_number, width, state)
                if det and conf > reactions['head_shake']['confidence']:
                    reactions['head_shake'] = {'detected': True, 'confidence': conf}

            if self.enabled_reactions.get('laughing', True):
                det, conf = self.detect_laughing(landmarks, frame_number, state)
                if det and conf > reactions['laughing']['confidence']:
                    reactions['laughing'] = {'detected': True, 'confidence': conf}

            if self.enabled_reactions.get('eyebrow_raise', True):
                det, conf = self.detect_eyebrow_raise(landmarks, state)
                if det and conf > reactions['eyebrow_raise']['confidence']:
                    reactions['eyebrow_raise'] = {'detected': True, 'confidence': conf}

        return reactions


def _write_preview_frame(frame, detector, reactions, cam_label: str, preview_path: str) -> None:
    """Zeichnet Face-Landmarks und Reaktions-Labels auf einen Frame und speichert als JPEG."""
    try:
        preview = frame.copy()
        h, w = preview.shape[:2]

        # Alle Landmark-Punkte als kleine Kreise zeichnen
        result = detector._last_result
        if result and result.face_landmarks:
            for lm_list in result.face_landmarks:
                for lm in lm_list:
                    cv2.circle(preview, (int(lm.x * w), int(lm.y * h)), 1, (0, 255, 80), -1)

        # Reaktions-Labels oben links
        y_pos = 30
        for rtype, data in reactions.items():
            if rtype in ('face_detected', 'face_count'):
                continue
            if isinstance(data, dict) and data.get('detected'):
                cv2.putText(preview, rtype.upper(), (10, y_pos),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 80), 2, cv2.LINE_AA)
                y_pos += 32

        # Kamera-Label oben rechts
        label_size, _ = cv2.getTextSize(cam_label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.putText(preview, cam_label, (w - label_size[0] - 10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        cv2.imwrite(preview_path, preview, [cv2.IMWRITE_JPEG_QUALITY, 75])
    except Exception:
        pass


def analyze_video(video_path, output_json=None, sensitivity='medium', show_preview=False,
                  params=None, off_sections=None, preview_path=None, auto_accuracy=False,
                  lut_path=None):
    """
    Analysiert Video auf Reaktionen

    Args:
        video_path: Pfad zum Video
        output_json: Pfad für JSON-Output (optional)
        sensitivity: 'low', 'medium', 'high'
        show_preview: Zeigt Live-Preview während Analyse
        params: Parameter-Dict (optional)
        off_sections: Liste von [start_frame, end_frame] Paaren (Video-Frame-Nummern).
                      Nur diese Bereiche werden mit MediaPipe analysiert. Alle anderen
                      Frames werden übersprungen (dekodiert aber nicht inferiert).
    """
    print(f"\n{'='*60}")
    print(f"Analysiere Video: {video_path}")
    print(f"Sensitivität: {sensitivity}")
    print(f"{'='*60}\n")

    # Video-Metadaten via ffprobe
    probe = subprocess.run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,avg_frame_rate,nb_frames,duration',
        '-of', 'json', str(video_path),
    ], capture_output=True, text=True)
    if probe.returncode != 0:
        print(f"✗ Fehler: ffprobe konnte Video nicht lesen")
        return None

    stream = json.loads(probe.stdout)['streams'][0]
    orig_width  = int(stream['width'])
    orig_height = int(stream['height'])
    fps_num, fps_den = stream.get('avg_frame_rate', '25/1').split('/')
    fps = float(fps_num) / float(fps_den)
    total_frames = int(stream['nb_frames']) if stream.get('nb_frames') else \
                   int(float(stream.get('duration', 0)) * fps)
    duration_sec = total_frames / fps

    # Decode-Auflösung bestimmen (ffmpeg skaliert direkt beim Dekodieren)
    if params is None:
        params = {}
    analysis_width = int(params.get('analysis_width', 0))

    # Video-Filter zusammenbauen (LUT + optionales Resize)
    _vf_filters = []
    if lut_path and Path(lut_path).is_file():
        _vf_filters.append(f"lut3d='{lut_path}'")
        print(f"LUT: {Path(lut_path).name}")

    if analysis_width and analysis_width < orig_width:
        scale_h = int(orig_height * analysis_width / orig_width)
        scale_h += scale_h % 2  # muss gerade sein
        frame_w, frame_h = analysis_width, scale_h
        _vf_filters.append(f'scale={frame_w}:{frame_h}')
        print(f"Video: {orig_width}×{orig_height} → Analyse-Auflösung: {frame_w}×{frame_h}")
    else:
        frame_w, frame_h = orig_width, orig_height
        print(f"Video: {orig_width}×{orig_height} (kein Resize)")

    vf_arg = ['-vf', ','.join(_vf_filters)] if _vf_filters else []

    # Debug: Frame-Limit aus Config lesen
    _debug_limit = False
    _max_frames = None
    if params.get('debug_limit_frames', False):
        _debug_limit = True
        _max_frames = int(params.get('debug_max_analysis_frames', 10000))
        total_frames = min(total_frames, _max_frames)
        duration_sec = total_frames / fps

    print(f"FPS: {fps}")
    print(f"Frames: {total_frames}" + (f" (Debug-Limit: {_max_frames})" if _debug_limit else ""))
    print(f"Dauer: {duration_sec:.1f} Sekunden\n")

    frame_bytes = frame_w * frame_h * 3

    # Detector initialisieren mit Config und FPS
    detector = AdvancedReactionDetector(sensitivity=sensitivity, fps=fps, params=params, auto_accuracy=auto_accuracy)

    # Zeige aktivierte Reaktionstypen
    enabled_types = [k for k, v in detector.enabled_reactions.items() if v]
    print(f"Aktivierte Reaktionstypen: {', '.join(enabled_types)}")

    # Off-Sektionen vorbereiten
    _off_sections = sorted(off_sections, key=lambda x: x[0]) if off_sections else None
    if _off_sections:
        total_off_frames = sum(e - s for s, e in _off_sections)
        print(f"Off-Sektionen: {len(_off_sections)} Segmente "
              f"({total_off_frames / fps / 60:.1f} min von {total_frames / fps / 60:.1f} min)")
    print()

    all_reactions = []
    print("Verarbeitung läuft...")
    start_time = time.time()

    def _collect_reactions(reactions, frame_num):
        for reaction_type, data in reactions.items():
            if reaction_type in ('face_detected', 'face_count'):
                continue
            if data['detected'] and data['confidence'] > 0.2:
                actual_frame = data.get('frame', frame_num)
                tc = actual_frame / fps
                entry = {
                    'frame':      actual_frame,
                    'timecode':   f"{int(tc // 60):02d}:{tc % 60:06.3f}",
                    'type':       reaction_type,
                    'confidence': round(data['confidence'], 3),
                }
                if 'peak_frame' in data:
                    entry['peak_frame'] = data['peak_frame']
                if 'tail_frames' in data:
                    entry['tail_frames'] = data['tail_frames']
                if data.get('pattern'):
                    entry['pattern'] = data['pattern']
                all_reactions.append(entry)

    def _log_face_counts(face_counts: list, label: str):
        """Gibt Verteilung + Stabilitäts-Warnung für eine Liste von Gesichts-Zählwerten aus."""
        if not face_counts:
            return
        from collections import Counter
        dist = Counter(face_counts)
        total = len(face_counts)
        mode  = dist.most_common(1)[0][0]
        avg   = sum(face_counts) / total
        dist_str = '  '.join(
            f"{k} Gesicht{'er' if k != 1 else ''}: {v/total*100:.0f}%"
            for k, v in sorted(dist.items())
        )
        instability = sum(1 for c in face_counts if c != mode) / total
        lines = [f"  {label}: ∅{avg:.1f} erkannte Gesichter  [{dist_str}]"]
        if dist.get(0, 0) / total > 0.3:
            lines.append(f"  ⚠  Kein Gesicht in {dist[0]/total*100:.0f}% der Frames — Kamera zu seitlich?")
        if instability > 0.25 and len(dist) > 1:
            lines.append(f"  ⚠  Instabil: {instability*100:.0f}% der Frames weichen vom häufigsten Wert ({mode}) ab")
        for l in lines:
            print(l)

    def _progress(done, total, label=''):
        progress = done / total if total else 1.0
        bar = '█' * int(40 * progress) + '░' * (40 - int(40 * progress))
        elapsed = time.time() - start_time
        if elapsed > 1 and done > 0:
            eta_s = (total - done) / (done / elapsed)
            eta_str = f" | ETA: {int(eta_s//60)}:{int(eta_s%60):02d}"
            eta_prog = f"{int(eta_s//60)}:{int(eta_s%60):02d}"
        else:
            eta_str = " | ETA: --:--"
            eta_prog = "--:--"
        print(f'\r  Analysiere{label}: [{bar}] {progress*100:.1f}% ({done}/{total}){eta_str}',
              end='', flush=True)
        print(f'__PROGRESS__ {progress*100:.1f} {eta_prog}', flush=True)

    all_face_counts = []  # Gesamt-Tracking über alle Sektionen / das gesamte Video

    if _off_sections:
        # ── Seeking-Modus: ein ffmpeg-Aufruf pro Off-Sektion ─────────────────
        # Nur das tatsächlich benötigte Material wird dekodiert.
        analyzed = 0
        for sec_idx, (sec_start, sec_end) in enumerate(_off_sections):
            if _max_frames and sec_start >= _max_frames:
                break
            n_frames = sec_end - sec_start
            if _max_frames and sec_end > _max_frames:
                n_frames = _max_frames - sec_start
            start_s  = sec_start / fps
            ff_cmd = [
                'ffmpeg', '-ss', f'{start_s:.6f}', '-i', str(video_path),
            ] + vf_arg + [
                '-frames:v', str(n_frames),
                '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-an', 'pipe:1',
            ]
            ff_proc = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            # Pending Nod-Detections der vorigen Sektion feuern bevor State geleert wird
            for fs in detector._face_states.values():
                if fs.get('_pending_conf', 0) > 0:
                    _, conf, first_f, peak_f, tail_f, pat_n = detector._fire_pending_nod(fs)
                    if conf > 0.2:
                        tc = first_f / fps
                        entry = {
                            'frame': first_f,
                            'timecode': f"{int(tc // 60):02d}:{tc % 60:06.3f}",
                            'type': 'nodding',
                            'confidence': round(conf, 3),
                            'peak_frame': peak_f,
                            'tail_frames': tail_f,
                        }
                        if pat_n:
                            entry['pattern'] = pat_n
                        all_reactions.append(entry)
            detector.reset_history()
            local = 0
            sec_face_counts = []
            while local < n_frames:
                raw = ff_proc.stdout.read(frame_bytes)
                if len(raw) < frame_bytes:
                    break
                actual_frame = sec_start + local
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((frame_h, frame_w, 3))
                reactions = detector.analyze_frame(frame, actual_frame)
                _collect_reactions(reactions, actual_frame)
                sec_face_counts.append(reactions['face_count'])
                local   += 1
                analyzed += 1
                if preview_path and local % max(1, int(fps * 5)) == 0:
                    _write_preview_frame(frame, detector, reactions,
                                         Path(video_path).stem, preview_path)
                if analyzed % 25 == 0 or analyzed == total_off_frames:
                    _progress(analyzed, total_off_frames)
                    _by = {}
                    for r in all_reactions:
                        _by[r['type']] = _by.get(r['type'], 0) + 1
                    if _by:
                        print(f"__REACTIONS__ {' '.join(f'{k}:{v}' for k,v in _by.items())}", flush=True)
            ff_proc.stdout.close()
            ff_proc.wait()
            all_face_counts.extend(sec_face_counts)
            print()  # Zeilenumbruch nach Progress
            _log_face_counts(
                sec_face_counts,
                f"Sektion {sec_idx + 1}/{len(_off_sections)} "
                f"(Frame {sec_start}–{sec_end}, {n_frames/fps:.0f}s)"
            )

    else:
        # ── Vollständige Analyse: ein ffmpeg-Aufruf für das gesamte Video ────
        _frames_v = ['-frames:v', str(total_frames)] if _debug_limit and _max_frames else []
        ff_cmd = ['ffmpeg', '-i', str(video_path)] + vf_arg + _frames_v + \
                 ['-f', 'rawvideo', '-pix_fmt', 'bgr24', '-an', 'pipe:1']
        ff_proc = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        frame_number = 0
        while True:
            if _max_frames and frame_number >= _max_frames:
                break
            raw = ff_proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((frame_h, frame_w, 3))
            reactions = detector.analyze_frame(frame, frame_number)
            _collect_reactions(reactions, frame_number)
            all_face_counts.append(reactions['face_count'])

            if show_preview and reactions['face_detected']:
                preview = frame.copy()
                if reactions['nodding']['detected']:
                    cv2.putText(preview, "NODDING", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                if reactions['laughing']['detected']:
                    cv2.putText(preview, "LAUGHING", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                cv2.imshow('Reaction Detection', preview)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            if preview_path and frame_number % max(1, int(fps * 5)) == 0:
                _write_preview_frame(frame, detector, reactions,
                                     Path(video_path).stem, preview_path)

            frame_number += 1
            if frame_number % 25 == 0 or frame_number == total_frames:
                _progress(frame_number, total_frames)
                _by = {}
                for r in all_reactions:
                    _by[r['type']] = _by.get(r['type'], 0) + 1
                if _by:
                    print(f"__REACTIONS__ {' '.join(f'{k}:{v}' for k,v in _by.items())}", flush=True)
        ff_proc.stdout.close()
        ff_proc.wait()

    # Letzte Pending Nod-Detections feuern (Ende der letzten Sektion / des Videos)
    for fs in detector._face_states.values():
        if fs.get('_pending_conf', 0) > 0:
            _, conf, first_f, peak_f, tail_f, pat_n = detector._fire_pending_nod(fs)
            if conf > 0.2:
                tc = first_f / fps
                entry = {
                    'frame': first_f,
                    'timecode': f"{int(tc // 60):02d}:{tc % 60:06.3f}",
                    'type': 'nodding',
                    'confidence': round(conf, 3),
                    'peak_frame': peak_f,
                    'tail_frames': tail_f,
                }
                if pat_n:
                    entry['pattern'] = pat_n
                all_reactions.append(entry)

    print()  # Neue Zeile nach Progress Bar
    if show_preview:
        cv2.destroyAllWindows()

    # Gesamt-Gesichts-Statistik
    if all_face_counts:
        label = "Gesamt" if not _off_sections else f"Gesamt ({len(_off_sections)} Sektionen)"
        _log_face_counts(all_face_counts, label)

    # Ergebnisse
    print(f"\n{'='*60}")
    print(f"ANALYSE ABGESCHLOSSEN")
    print(f"{'='*60}")
    print(f"Reaktionen gefunden: {len(all_reactions)}")
    
    # Nach Typ gruppieren
    by_type = {}
    for r in all_reactions:
        rtype = r['type']
        by_type[rtype] = by_type.get(rtype, 0) + 1
    
    for rtype, count in by_type.items():
        print(f"  {rtype}: {count}")
    
    # JSON exportieren
    if output_json:
        output_data = {
            'video_path': str(video_path),
            'fps': fps,
            'total_frames': total_frames,
            'duration_seconds': duration_sec,
            'sensitivity': sensitivity,
            'reactions': all_reactions
        }
        
        with open(output_json, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"\n✓ Ergebnisse gespeichert: {output_json}")
    
    return all_reactions


def main():
    parser = argparse.ArgumentParser(description='Analysiere Video auf Reaktionen')
    parser.add_argument('video', help='Pfad zum Video')
    parser.add_argument('--output', '-o', help='Output JSON-Datei')
    parser.add_argument('--sensitivity', '-s', choices=['low', 'medium', 'high'], 
                        help='Erkennungs-Sensitivität (überschreibt config.ini)')
    parser.add_argument('--preview', '-p', action='store_true', 
                        help='Zeige Live-Preview')
    parser.add_argument('--params', default=None,
                        help='Pfad zur params.json mit Modul-Parametern')
    parser.add_argument('--off-sections', default=None,
                        help='JSON-Datei mit [[start_frame, end_frame], ...] — nur diese Bereiche werden analysiert')
    parser.add_argument('--preview-path', default=None,
                        help='Pfad für Live-Preview-JPEG (wird jede Sekunde überschrieben)')
    parser.add_argument('--auto-accuracy', action='store_true',
                        help='Nodding-Threshold dynamisch an erkannte Gesichtsgröße anpassen')
    parser.add_argument('--lut', default=None,
                        help='Pfad zu einer .cube LUT-Datei (wird per lut3d auf die Frames angewendet)')

    args = parser.parse_args()
    
    # Lade Params
    params = load_params(args.params)

    # Validiere Video-Pfad
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"✗ Video nicht gefunden: {video_path}")
        return 1

    # Sensitivity: Commandline überschreibt Params
    sensitivity = args.sensitivity
    if not sensitivity and params.get('default_sensitivity'):
        sensitivity = params['default_sensitivity']
    if not sensitivity:
        sensitivity = 'medium'
    
    # Output-Pfad
    output_json = args.output
    if not output_json:
        output_json = video_path.stem + '_reactions.json'
    
    # Off-Sektionen laden (optional)
    off_sections = None
    if args.off_sections:
        off_sections_path = Path(args.off_sections)
        if off_sections_path.exists():
            off_sections = json.loads(off_sections_path.read_text())
        else:
            print(f"⚠️  --off-sections Datei nicht gefunden: {args.off_sections} — analysiere alle Frames")

    # Analysiere mit Params
    reactions = analyze_video(
        video_path,
        output_json=output_json,
        sensitivity=sensitivity,
        show_preview=args.preview,
        params=params,
        off_sections=off_sections,
        preview_path=args.preview_path,
        auto_accuracy=args.auto_accuracy,
        lut_path=args.lut,
    )
    
    if reactions is not None:
        print("\n✓✓✓ Fertig!")
        return 0
    else:
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
