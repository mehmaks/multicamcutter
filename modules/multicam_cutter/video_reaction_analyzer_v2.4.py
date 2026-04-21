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
from pathlib import Path
import json
import subprocess
from collections import deque
import argparse
import configparser
import os
import time
import urllib.request


_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
_MODEL_PATH = Path(__file__).parent / "face_landmarker.task"


def _ensure_model():
    """Lädt face_landmarker.task herunter falls nicht vorhanden."""
    if _MODEL_PATH.exists():
        return
    print(f"⬇ face_landmarker.task nicht gefunden — lade herunter...")
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    print(f"✓ Modell gespeichert: {_MODEL_PATH}")


def load_config(config_path='config.ini'):
    """Lädt Konfiguration aus config.ini"""
    config = configparser.ConfigParser()
    
    # Suche config.ini im aktuellen Verzeichnis oder im Skript-Verzeichnis
    search_paths = [
        config_path,
        os.path.join(os.path.dirname(__file__), config_path),
        os.path.join(os.getcwd(), config_path)
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            config.read(path)
            print(f"✓ Config geladen: {path}")
            return config
    
    print(f"⚠️  config.ini nicht gefunden, nutze Default-Werte")
    return None


class AdvancedReactionDetector:
    """Verbesserte Reaktionserkennung mit mehr Features"""
    
    def __init__(self, sensitivity='medium', fps=25.0, config=None, auto_accuracy=False):
        # Anzahl gleichzeitig erkannter Gesichter (konfigurierbar für Totalen / Zweier-Shots)
        max_faces = 1
        if config and config.has_section('Detection'):
            max_faces = config.getint('Detection', 'max_faces', fallback=1)

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
        
        # Defaults für Config-Werte
        self.min_nod_duration = 0.5  # Default: 0.5 Sekunden
        
        # Lade Sensitivität aus Config wenn vorhanden
        if config and config.has_option('General', 'default_sensitivity'):
            sensitivity = config.get('General', 'default_sensitivity')
        
        # Nodding-Threshold: einzelner Wert (kalibriert für calibration_height px)
        self.nod_threshold = 80.0
        if config and config.has_section('Nodding'):
            self.nod_threshold = config.getfloat('Nodding', 'threshold', fallback=80.0)

        # Laughing-Threshold: weiterhin sensitiv-abhängig
        laugh_threshold_low = 1.7
        laugh_threshold_medium = 1.5
        laugh_threshold_high = 1.3
        if config and config.has_section('Laughing'):
            laugh_threshold_low = config.getfloat('Laughing', 'threshold_low', fallback=1.7)
            laugh_threshold_medium = config.getfloat('Laughing', 'threshold_medium', fallback=1.5)
            laugh_threshold_high = config.getfloat('Laughing', 'threshold_high', fallback=1.3)

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
        
        if config:
            if config.has_section('Nodding'):
                self.enabled_reactions['nodding'] = config.getboolean('Nodding', 'enabled', fallback=True)
                self.min_nod_duration = config.getfloat('Nodding', 'min_nod_duration', fallback=0.5)
            if config.has_section('HeadShake'):
                self.enabled_reactions['head_shake'] = config.getboolean('HeadShake', 'enabled', fallback=True)
            if config.has_section('Laughing'):
                self.enabled_reactions['laughing'] = config.getboolean('Laughing', 'enabled', fallback=True)
            if config.has_section('EyebrowRaise'):
                self.enabled_reactions['eyebrow_raise'] = config.getboolean('EyebrowRaise', 'enabled', fallback=True)
        
        # Nod-Cooldown aus Config (verhindert Drift-Loop)
        self.nod_cooldown_frames = 35
        if config and config.has_section('Nodding'):
            self.nod_cooldown_frames = config.getint('Nodding', 'cooldown_frames', fallback=35)

        # Kalibrierungs-Auflösung: Thresholds wurden für diese Höhe eingestellt
        self.calibration_height = 2160
        if config and config.has_section('Detection'):
            self.calibration_height = config.getint('Detection', 'calibration_height', fallback=2160)

        # Auto Accuracy: skaliert Nodding-Threshold dynamisch auf erkannte Gesichtsgröße
        # Referenz-Gesichtshöhe = 0.45 (normiert auf Frame-Höhe), gemessen an einem
        # nahaufnahme-typischen Podcast-Frame mit einer Person (gute Erkennungsrate).
        self.auto_accuracy = auto_accuracy
        self._auto_accuracy_ref = 0.45

        # Per-Gesicht-Historien (keyed by Sortier-Index = links→rechts-Position im Frame)
        # Separate Deques pro Gesicht verhindern Vermischung bei mehreren Personen
        self._nod_history_size = max(30, int(self.min_nod_duration * self.fps) + 10)
        self._face_states: dict = {}

    def _get_face_state(self, face_idx: int) -> dict:
        """Gibt den Zustand (Historien + Cooldowns) für ein Gesicht zurück, legt ihn bei Bedarf an."""
        if face_idx not in self._face_states:
            self._face_states[face_idx] = {
                'head_y_history':     deque(maxlen=self._nod_history_size),
                'head_x_history_nod': deque(maxlen=self._nod_history_size),
                'head_x_history':     deque(maxlen=30),
                'mouth_history':      deque(maxlen=20),
                'eyebrow_history':    deque(maxlen=15),
                'last_nod_frame':     -100,
                'last_laugh_frame':   -100,
            }
        return self._face_states[face_idx]

    def reset_history(self):
        """Setzt alle Bewegungs-Historien zurück (beim Betreten einer neuen Off-Sektion)."""
        self._face_states.clear()
    
    def get_landmark_coord(self, landmarks, index, width, height):
        """Holt Landmark-Koordinaten in Pixel"""
        lm = landmarks[index]
        return int(lm.x * width), int(lm.y * height)
    
    def detect_nodding(self, landmarks, frame_number, height, width, state: dict):
        """Nicken-Erkennung v2.4 mit X-Achsen-Check und Return-to-Baseline"""
        # Nasenpunkt (Landmark 1) — Y und X tracken
        nose_y = landmarks[1].y * height
        nose_x = landmarks[1].x * width
        state['head_y_history'].append(nose_y)
        state['head_x_history_nod'].append(nose_x)

        min_frames = int(self.min_nod_duration * self.fps)

        if len(state['head_y_history']) < min_frames:
            return False, 0.0

        # Cooldown (jetzt konfigurierbar, verhindert Drift-Loop)
        if frame_number - state['last_nod_frame'] < self.nod_cooldown_frames:
            return False, 0.0

        y_positions = list(state['head_y_history'])
        x_positions = list(state['head_x_history_nod'])

        y_range = max(y_positions) - min(y_positions)
        x_range = max(x_positions) - min(x_positions)

        # Skaliere Pixel-Threshold auf tatsächliche Auflösung
        res_scale = height / self.calibration_height
        effective_nod_threshold = self.nod_threshold * res_scale

        # Auto Accuracy: Threshold proportional zur erkannten Gesichtsgröße skalieren.
        # Kleinere Gesichter (z.B. Totale mit 2 Personen) erzeugen kleinere Landmark-Deltas
        # → Threshold wird proportional reduziert, sodass Nickbewegungen nicht verfehlt werden.
        if self.auto_accuracy:
            face_height_norm = abs(landmarks[10].y - landmarks[152].y)
            if face_height_norm > 0.05:  # Mindestgröße, um Rauschen zu vermeiden
                face_scale = max(0.3, min(2.0, face_height_norm / self._auto_accuracy_ref))
                effective_nod_threshold *= face_scale

        # Mindest-Y-Bewegung
        if y_range < effective_nod_threshold:
            return False, 0.0

        # X-Achsen-Check: wenn horizontale Bewegung ≥ 70% der vertikalen,
        # ist es wahrscheinlich Drehstuhl-Sway oder Körperbewegung → kein Nicken
        if x_range >= y_range * 0.7:
            return False, 0.0

        # Auf-Ab-Auf Pattern (3 Segmente)
        third = len(y_positions) // 3
        seg1_avg = np.mean(y_positions[:third])
        seg2_avg = np.mean(y_positions[third:2*third])
        seg3_avg = np.mean(y_positions[2*third:])

        seg_threshold = max(8 * res_scale, y_range * 0.2)

        # Richtungsumkehr erzwingen: seg2 muss sich von seg1 entfernen,
        # seg3 muss in die Gegenrichtung zurückkehren (echte Oszillation).
        # Monotoner Drift (z.B. 100→107→114) wird so ausgeschlossen.
        d1 = seg2_avg - seg1_avg  # Hinbewegung
        d2 = seg3_avg - seg2_avg  # Rückbewegung
        if not (abs(d1) > seg_threshold and abs(d2) > seg_threshold):
            return False, 0.0
        # Vorzeichen müssen verschieden sein (Richtungsumkehr)
        if (d1 > 0) == (d2 > 0):
            return False, 0.0

        # Return-to-Baseline: Kopf muss nach dem Nicken zurückkehren
        # seg3 muss nah an seg1 liegen (innerhalb 45% des Bewegungsbereichs)
        if abs(seg3_avg - seg1_avg) > y_range * 0.45:
            return False, 0.0

        # Confidence basiert auf dem schwächsten Segment-Übergang:
        # Beide Richtungen (hin UND zurück) müssen stark sein für hohe Konfidenz.
        # Normalisiert auf halben Threshold — conf=1.0 erst wenn der schwächere
        # Übergang allein schon 50% des Thresholds erreicht.
        seg_delta_min = min(abs(seg2_avg - seg1_avg), abs(seg2_avg - seg3_avg))
        confidence = min(seg_delta_min / (effective_nod_threshold * 0.5), 1.0)
        state['last_nod_frame'] = frame_number
        return True, confidence
    
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
                det, conf = self.detect_nodding(landmarks, frame_number, height, width, state)
                if det and conf > reactions['nodding']['confidence']:
                    reactions['nodding'] = {'detected': True, 'confidence': conf}

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
                  config=None, off_sections=None, preview_path=None, auto_accuracy=False,
                  lut_path=None):
    """
    Analysiert Video auf Reaktionen

    Args:
        video_path: Pfad zum Video
        output_json: Pfad für JSON-Output (optional)
        sensitivity: 'low', 'medium', 'high'
        show_preview: Zeigt Live-Preview während Analyse
        config: ConfigParser-Objekt (optional)
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
    analysis_width = 0
    if config and config.has_section('Detection'):
        analysis_width = config.getint('Detection', 'analysis_width', fallback=0)

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
    if config and config.has_section('Debug'):
        _debug_limit = config.getboolean('Debug', 'limit_frames', fallback=False)
        if _debug_limit:
            _max_frames = config.getint('Debug', 'max_analysis_frames', fallback=10000)
            total_frames = min(total_frames, _max_frames)
            duration_sec = total_frames / fps

    print(f"FPS: {fps}")
    print(f"Frames: {total_frames}" + (f" (Debug-Limit: {_max_frames})" if _debug_limit else ""))
    print(f"Dauer: {duration_sec:.1f} Sekunden\n")

    frame_bytes = frame_w * frame_h * 3

    # Detector initialisieren mit Config und FPS
    detector = AdvancedReactionDetector(sensitivity=sensitivity, fps=fps, config=config, auto_accuracy=auto_accuracy)

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
                tc = frame_num / fps
                all_reactions.append({
                    'frame':      frame_num,
                    'timecode':   f"{int(tc // 60):02d}:{tc % 60:06.3f}",
                    'type':       reaction_type,
                    'confidence': round(data['confidence'], 3),
                })

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
            if _max_frames and analyzed >= _max_frames:
                break
            n_frames = sec_end - sec_start
            if _max_frames:
                n_frames = min(n_frames, _max_frames - analyzed)
            start_s  = sec_start / fps
            ff_cmd = [
                'ffmpeg', '-ss', f'{start_s:.6f}', '-i', str(video_path),
            ] + vf_arg + [
                '-frames:v', str(n_frames),
                '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-an', 'pipe:1',
            ]
            ff_proc = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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
    parser.add_argument('--config', default='config.ini',
                        help='Pfad zur Config-Datei (default: config.ini)')
    parser.add_argument('--off-sections', default=None,
                        help='JSON-Datei mit [[start_frame, end_frame], ...] — nur diese Bereiche werden analysiert')
    parser.add_argument('--preview-path', default=None,
                        help='Pfad für Live-Preview-JPEG (wird jede Sekunde überschrieben)')
    parser.add_argument('--auto-accuracy', action='store_true',
                        help='Nodding-Threshold dynamisch an erkannte Gesichtsgröße anpassen')
    parser.add_argument('--lut', default=None,
                        help='Pfad zu einer .cube LUT-Datei (wird per lut3d auf die Frames angewendet)')

    args = parser.parse_args()
    
    # Lade Config
    config = load_config(args.config)
    
    # Validiere Video-Pfad
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"✗ Video nicht gefunden: {video_path}")
        return 1
    
    # Sensitivity: Commandline überschreibt Config
    sensitivity = args.sensitivity
    if not sensitivity and config and config.has_option('General', 'default_sensitivity'):
        sensitivity = config.get('General', 'default_sensitivity')
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

    # Analysiere mit Config
    reactions = analyze_video(
        video_path,
        output_json=output_json,
        sensitivity=sensitivity,
        show_preview=args.preview,
        config=config,
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
