#!/usr/bin/env python3
"""
Video Reaction Analyzer
Analysiert exportierte Multicam-Videos auf Reaktionen
Kann unabhängig von Resolve laufen für Testing
"""

import cv2
import mediapipe as mp
import numpy as np
from pathlib import Path
import json
from collections import deque
import argparse
import configparser
import os
import time


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
    
    def __init__(self, sensitivity='medium', fps=25.0, config=None):
        # MediaPipe Face Mesh
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        # Video FPS (für Speaking-Detection timing)
        self.fps = fps
        
        # Defaults für Config-Werte
        self.min_nod_duration = 0.5  # Default: 0.5 Sekunden
        
        # Lade Sensitivität aus Config wenn vorhanden
        if config and config.has_option('General', 'default_sensitivity'):
            sensitivity = config.get('General', 'default_sensitivity')
        
        # Lade Threshold-Werte aus Config
        nod_threshold_low = 20
        nod_threshold_medium = 15
        nod_threshold_high = 10
        laugh_threshold_low = 1.7
        laugh_threshold_medium = 1.5
        laugh_threshold_high = 1.3
        
        if config:
            if config.has_section('Nodding'):
                nod_threshold_low = config.getfloat('Nodding', 'threshold_low', fallback=20)
                nod_threshold_medium = config.getfloat('Nodding', 'threshold_medium', fallback=15)
                nod_threshold_high = config.getfloat('Nodding', 'threshold_high', fallback=10)
            if config.has_section('Laughing'):
                laugh_threshold_low = config.getfloat('Laughing', 'threshold_low', fallback=1.7)
                laugh_threshold_medium = config.getfloat('Laughing', 'threshold_medium', fallback=1.5)
                laugh_threshold_high = config.getfloat('Laughing', 'threshold_high', fallback=1.3)
        
        # Sensitivität-Einstellungen
        self.sensitivity_settings = {
            'low': {'nod_threshold': nod_threshold_low, 'laugh_threshold': laugh_threshold_low},
            'medium': {'nod_threshold': nod_threshold_medium, 'laugh_threshold': laugh_threshold_medium},
            'high': {'nod_threshold': nod_threshold_high, 'laugh_threshold': laugh_threshold_high}
        }
        self.settings = self.sensitivity_settings.get(sensitivity, self.sensitivity_settings['medium'])
        
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
        
        # Bewegungs-Historie
        # Dynamische Größe basierend auf min_nod_duration
        nod_history_size = max(30, int(self.min_nod_duration * self.fps) + 10)
        self.head_y_history = deque(maxlen=nod_history_size)  # Nicken Y
        self.head_x_history_nod = deque(maxlen=nod_history_size)  # Nicken X (Stuhl-Check)
        self.head_x_history = deque(maxlen=30)  # Kopfschütteln
        self.mouth_history = deque(maxlen=20)  # Lachen
        self.eyebrow_history = deque(maxlen=15)

        # Nod-Cooldown aus Config (verhindert Drift-Loop)
        self.nod_cooldown_frames = 35
        if config and config.has_section('Nodding'):
            self.nod_cooldown_frames = config.getint('Nodding', 'cooldown_frames', fallback=35)

        # Reaktions-Cooldown (verhindert Doppel-Detektionen)
        self.last_nod_frame = -100
        self.last_laugh_frame = -100
    
    def get_landmark_coord(self, landmarks, index, width, height):
        """Holt Landmark-Koordinaten in Pixel"""
        lm = landmarks[index]
        return int(lm.x * width), int(lm.y * height)
    
    def detect_nodding(self, landmarks, frame_number, height, width):
        """Nicken-Erkennung v2.4 mit X-Achsen-Check und Return-to-Baseline"""
        # Nasenpunkt (Landmark 1) — Y und X tracken
        nose_y = landmarks[1].y * height
        nose_x = landmarks[1].x * width
        self.head_y_history.append(nose_y)
        self.head_x_history_nod.append(nose_x)

        min_frames = int(self.min_nod_duration * self.fps)

        if len(self.head_y_history) < min_frames:
            return False, 0.0

        # Cooldown (jetzt konfigurierbar, verhindert Drift-Loop)
        if frame_number - self.last_nod_frame < self.nod_cooldown_frames:
            return False, 0.0

        y_positions = list(self.head_y_history)
        x_positions = list(self.head_x_history_nod)

        y_range = max(y_positions) - min(y_positions)
        x_range = max(x_positions) - min(x_positions)

        # Mindest-Y-Bewegung
        if y_range < self.settings['nod_threshold']:
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

        seg_threshold = max(8, y_range * 0.2)

        # Mittleres Segment muss sich von beiden Rändern abheben
        if not (abs(seg2_avg - seg1_avg) > seg_threshold and
                abs(seg2_avg - seg3_avg) > seg_threshold):
            return False, 0.0

        # Return-to-Baseline: Kopf muss nach dem Nicken zurückkehren
        # seg3 muss nah an seg1 liegen (innerhalb 45% des Bewegungsbereichs)
        if abs(seg3_avg - seg1_avg) > y_range * 0.45:
            return False, 0.0

        confidence = min(y_range / 50.0, 1.0)
        self.last_nod_frame = frame_number
        return True, confidence
    
    def detect_head_shake(self, landmarks, frame_number, width):
        """Erkennt Kopfschütteln (nein-nein)"""
        nose_x = landmarks[1].x * width
        self.head_x_history.append(nose_x)
        
        if len(self.head_x_history) < 30:
            return False, 0.0
        
        positions = list(self.head_x_history)
        movement_range = max(positions) - min(positions)
        
        # Kopfschütteln = horizontale Bewegung
        if movement_range > 25:
            confidence = min(movement_range / 40.0, 1.0)
            return True, confidence
        
        return False, 0.0
    
    def detect_laughing(self, landmarks, frame_number):
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
        
        self.mouth_history.append(mouth_score)
        
        if len(self.mouth_history) < 10:
            return False, 0.0
        
        # Cooldown
        if frame_number - self.last_laugh_frame < 20:  # Mind. 0.66s
            return False, 0.0
        
        # Durchschnitt der letzten Frames
        recent_avg = np.mean(list(self.mouth_history)[-10:])
        baseline_avg = np.mean(list(self.mouth_history)[:10])
        
        # Lachen = deutlich größerer Mund als Baseline
        threshold = self.settings['laugh_threshold']
        if recent_avg > baseline_avg * threshold and mouth_score > 0.003:
            confidence = min((recent_avg / baseline_avg - 1.0), 1.0)
            self.last_laugh_frame = frame_number
            return True, confidence
        
        return False, 0.0
    
    def detect_eyebrow_raise(self, landmarks):
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
        
        self.eyebrow_history.append(avg_dist)
        
        if len(self.eyebrow_history) < 15:
            return False, 0.0
        
        # Augenbrauen hochgezogen = größere Distanz
        baseline = np.mean(list(self.eyebrow_history)[:10])
        current = avg_dist
        
        if current > baseline * 1.3:
            confidence = min((current / baseline - 1.0) * 2, 1.0)
            return True, confidence
        
        return False, 0.0
    
    def analyze_frame(self, frame, frame_number):
        """Analysiert Frame auf alle Reaktionstypen"""
        height, width = frame.shape[:2]
        
        # Konvertiere zu RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb_frame)
        
        reactions = {
            'nodding': {'detected': False, 'confidence': 0.0},
            'head_shake': {'detected': False, 'confidence': 0.0},
            'laughing': {'detected': False, 'confidence': 0.0},
            'eyebrow_raise': {'detected': False, 'confidence': 0.0},
            'face_detected': False
        }
        
        if not results.multi_face_landmarks:
            return reactions
        
        reactions['face_detected'] = True
        landmarks = results.multi_face_landmarks[0].landmark
        
        # Prüfe nur aktivierte Reaktionen
        if self.enabled_reactions.get('nodding', True):
            nod_detected, nod_conf = self.detect_nodding(landmarks, frame_number, height, width)
            reactions['nodding'] = {'detected': nod_detected, 'confidence': nod_conf}
        
        if self.enabled_reactions.get('head_shake', True):
            shake_detected, shake_conf = self.detect_head_shake(landmarks, frame_number, width)
            reactions['head_shake'] = {'detected': shake_detected, 'confidence': shake_conf}
        
        if self.enabled_reactions.get('laughing', True):
            laugh_detected, laugh_conf = self.detect_laughing(landmarks, frame_number)
            reactions['laughing'] = {'detected': laugh_detected, 'confidence': laugh_conf}
        
        if self.enabled_reactions.get('eyebrow_raise', True):
            brow_detected, brow_conf = self.detect_eyebrow_raise(landmarks)
            reactions['eyebrow_raise'] = {'detected': brow_detected, 'confidence': brow_conf}
        
        return reactions


def analyze_video(video_path, output_json=None, sensitivity='medium', show_preview=False, config=None):
    """
    Analysiert Video auf Reaktionen
    
    Args:
        video_path: Pfad zum Video
        output_json: Pfad für JSON-Output (optional)
        sensitivity: 'low', 'medium', 'high'
        show_preview: Zeigt Live-Preview während Analyse
        config: ConfigParser-Objekt (optional)
    """
    print(f"\n{'='*60}")
    print(f"Analysiere Video: {video_path}")
    print(f"Sensitivität: {sensitivity}")
    print(f"{'='*60}\n")
    
    # Öffne Video
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"✗ Fehler: Konnte Video nicht öffnen")
        return None
    
    # Video-Infos
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps
    
    print(f"FPS: {fps}")
    print(f"Frames: {total_frames}")
    print(f"Dauer: {duration_sec:.1f} Sekunden\n")
    
    # Detector initialisieren mit Config und FPS
    detector = AdvancedReactionDetector(sensitivity=sensitivity, fps=fps, config=config)
    
    # Zeige aktivierte Reaktionstypen
    enabled_types = [k for k, v in detector.enabled_reactions.items() if v]
    print(f"Aktivierte Reaktionstypen: {', '.join(enabled_types)}\n")
    
    # Reaktionen sammeln
    all_reactions = []
    frame_number = 0
    
    print("Verarbeitung läuft...")
    
    # Für ETA-Berechnung
    start_time = time.time()
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Analysiere Frame
        reactions = detector.analyze_frame(frame, frame_number)
        
        # Speichere signifikante Reaktionen
        for reaction_type, data in reactions.items():
            if reaction_type == 'face_detected':
                continue
            
            if data['detected'] and data['confidence'] > 0.5:
                timecode = frame_number / fps
                all_reactions.append({
                    'frame': frame_number,
                    'timecode': f"{int(timecode // 60):02d}:{timecode % 60:06.3f}",
                    'type': reaction_type,
                    'confidence': round(data['confidence'], 3)
                })
                # Logging entfernt - Progress Bar nicht stören
        
        # Preview
        if show_preview and reactions['face_detected']:
            # Zeichne Reaktions-Indikator
            if reactions['nodding']['detected']:
                cv2.putText(frame, "NODDING", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            if reactions['laughing']['detected']:
                cv2.putText(frame, "LAUGHING", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            
            cv2.imshow('Reaction Detection', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        frame_number += 1
        
        # Progress Bar (einzeilig, überschreibend)
        if frame_number % 25 == 0 or frame_number == total_frames:  # Update alle 25 Frames (1 Sekunde)
            progress = (frame_number / total_frames)
            bar_length = 40
            filled = int(bar_length * progress)
            bar = '█' * filled + '░' * (bar_length - filled)
            percent = progress * 100
            
            # ETA Berechnung
            elapsed = time.time() - start_time
            if elapsed > 1 and frame_number > 0:  # Warte 1 Sekunde für stabile FPS
                fps_processing = frame_number / elapsed
                remaining_frames = total_frames - frame_number
                eta_seconds = remaining_frames / fps_processing
                eta_min = int(eta_seconds // 60)
                eta_sec = int(eta_seconds % 60)
                eta_str = f" | ETA: {eta_min}:{eta_sec:02d}"
            else:
                eta_str = " | ETA: --:--"
            
            print(f'\r  Analysiere: [{bar}] {percent:.1f}% ({frame_number}/{total_frames}){eta_str}', end='', flush=True)
    
    print()  # Neue Zeile nach Progress Bar
    cap.release()
    if show_preview:
        cv2.destroyAllWindows()
    
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
    
    # Analysiere mit Config
    reactions = analyze_video(
        video_path,
        output_json=output_json,
        sensitivity=sensitivity,
        show_preview=args.preview,
        config=config
    )
    
    if reactions is not None:
        print("\n✓✓✓ Fertig!")
        return 0
    else:
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
