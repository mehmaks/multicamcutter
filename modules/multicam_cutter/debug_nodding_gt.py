#!/usr/bin/env python3
"""Debug-Script: Landmark-Daten an Ground-Truth-Positionen extrahieren
und durch die Pattern-Checks laufen lassen.

Analysiert nur die relevanten Bereiche um die GT-Frames herum
und gibt detaillierte Diagnostik aus, warum kein Pattern matcht.
"""

import sys
import json
import subprocess
import math
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

# ── Konfig ──
VIDEO = "/Volumes/Jardani/Projekte/2025 - Jena United/Aktueller Schnitt/33 - Sabrina Lytsch/C7754.MP4"
FPS = 25.0

# GT-Positionen in C7754-Source-Frames
# Clip-Start-TC: 05:36:34:02 (aus ffprobe Metadata, = Abs.Frame 504852 @25fps)
# Formel: source_frame = (TC_abs_frames - 504852)
GT_REGIONS = [
    ("GT1", 5604, 5623),   # 05:40:18:06 – 05:40:18:25
    ("GT2", 5715, 5748),   # 05:40:22:17 – 05:40:23:00
    ("GT3", 6588, 6612),   # 05:40:57:12 – 05:40:58:12  (ungefähr)
    ("GT4", 7479, 7545),   # 05:41:33:06 – 05:41:35:19
    ("GT5", 7626, 7668),   # 05:41:39:00 – 05:41:40:18
    ("GT6", 7923, 7969),   # 05:41:51:00 – 05:41:52:21
    ("GT7", 7990, 8030),   # 05:41:53:16 – 05:41:55:06
]

# Analyse-Fenster: N Frames vor GT-Start bis N Frames nach GT-Ende
PADDING = 75  # 3 Sekunden vor/nach

PATTERNS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "nodding_patterns.json"

def load_patterns():
    data = json.loads(PATTERNS_PATH.read_text())
    return data['global'], [p for p in data['patterns'] if p.get('enabled', True)]

def analyze_region(cap, landmarker, start_frame, end_frame, region_name,
                   globals_cfg, patterns, width, height):
    """Analysiert eine Region und gibt Diagnostik pro Frame aus."""

    analysis_start = max(0, start_frame - PADDING)
    analysis_end = end_frame + PADDING

    cap.set(1, analysis_start)  # CV2 CAP_PROP_POS_FRAMES
    actual_pos = int(cap.get(1))
    actual_ms = cap.get(0)  # CAP_PROP_POS_MSEC
    print(f"  SEEK: requested={analysis_start}, actual_frame={actual_pos}, "
          f"actual_ms={actual_ms:.0f} (expected_ms={analysis_start*1000/FPS:.0f})")

    nose_y_buf = []
    nose_x_buf = []
    bridge_y_buf = []
    tilt_buf = []
    yaw_buf = []
    frame_nums = []

    k = globals_cfg['smooth_kernel']
    nod_threshold = globals_cfg['nod_threshold']
    calibration_height = globals_cfg['calibration_height']
    auto_acc_ref = globals_cfg['auto_accuracy_ref']

    print(f"\n{'='*70}")
    print(f"{region_name}: Source-Frames {start_frame}-{end_frame} "
          f"(dur={end_frame-start_frame}f/{(end_frame-start_frame)/FPS:.2f}s)")
    print(f"  Analysiere Frames {analysis_start}-{analysis_end}")
    print(f"{'='*70}")

    frame_idx = analysis_start
    face_found_count = 0

    while frame_idx <= analysis_end:
        ret, frame = cap.read()
        if not ret:
            break

        rgb = frame[:, :, ::-1]
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts_ms = int(frame_idx * 1000 / FPS)
        results = landmarker.detect_for_video(mp_image, ts_ms)

        if results.face_landmarks:
            lm = results.face_landmarks[0]
            ny = lm[1].y * height
            nx = lm[1].x * width
            by = lm[6].y * height

            # Kopfneigung + Yaw tracken
            tilt_val = math.atan2(
                lm[10].x * width - lm[152].x * width,
                lm[152].y * height - lm[10].y * height,
            )
            tilt_buf.append(tilt_val)

            left_eye_x = lm[33].x * width
            right_eye_x = lm[263].x * width
            bx = lm[6].x * width
            eye_span = right_eye_x - left_eye_x
            yaw_ratio = (bx - left_eye_x) / eye_span if abs(eye_span) > 1.0 else 0.5
            yaw_buf.append(yaw_ratio)
            yaw_dev = abs(yaw_ratio - 0.5) * 2.0

            if frame_idx == start_frame:
                print(f"  TILT: {math.degrees(tilt_val):.1f}°  "
                      f"YAW: ratio={yaw_ratio:.3f} dev={yaw_dev:.2f}")

            # Per-Frame-Log im GT-Bereich (nur für detaillierte Analyse)
            if start_frame <= frame_idx <= end_frame:
                print(f"    f{frame_idx}: nose_y={ny:.1f} nose_x={nx:.1f} "
                      f"chin_y={lm[152].y*height:.1f} forehead_y={lm[10].y*height:.1f}")

            nose_y_buf.append(ny)
            nose_x_buf.append(nx)
            bridge_y_buf.append(by)
            frame_nums.append(frame_idx)
            face_found_count += 1

            # Threshold berechnen
            res_scale = height / calibration_height
            thr = nod_threshold * res_scale
            face_h = abs(lm[10].y - lm[152].y)  # forehead to chin (normalized)
            if face_h > 0.05:
                face_scale = max(0.3, min(2.0, face_h / auto_acc_ref))
                thr_adj = thr * face_scale
            else:
                thr_adj = thr

            # Ab genug Frames: Pattern-Check
            if len(nose_y_buf) >= 15:
                y_arr = np.array(nose_y_buf)
                x_arr = np.array(nose_x_buf)
                b_arr = np.array(bridge_y_buf)
                t_arr = np.array(tilt_buf)
                yw_arr = np.array(yaw_buf)

                for pat in patterns:
                    result = check_pattern_debug(pat, y_arr, x_arr, b_arr, thr_adj, k, FPS, t_arr, yw_arr)
                    if result['passed']:
                        print(f"\n  *** DETECTION at frame {frame_idx} via '{pat['name']}' "
                              f"conf={result['confidence']:.3f} ***")
                    elif frame_idx >= start_frame and frame_idx <= end_frame:
                        # Nur innerhalb GT-Bereich: Failure-Reason ausgeben
                        if result['fail_reason'] not in ('amplitude', 'reversals'):
                            # Nur "interessante" Failures loggen
                            print(f"  Frame {frame_idx} [{pat['name']}]: "
                                  f"FAIL={result['fail_reason']}  "
                                  f"y_range={result.get('y_range', 0):.1f}  "
                                  f"x_range={result.get('x_range', 0):.1f}  "
                                  f"revs={result.get('reversals', 0)}  "
                                  f"corr={result.get('corr', 0):.3f}  "
                                  f"thr={thr_adj:.1f}")
        else:
            nose_y_buf.append(nose_y_buf[-1] if nose_y_buf else 0)
            nose_x_buf.append(nose_x_buf[-1] if nose_x_buf else 0)
            bridge_y_buf.append(bridge_y_buf[-1] if bridge_y_buf else 0)
            tilt_buf.append(tilt_buf[-1] if tilt_buf else 0)
            yaw_buf.append(yaw_buf[-1] if yaw_buf else 0.5)
            frame_nums.append(frame_idx)

        frame_idx += 1

    print(f"\n  Gesichter erkannt: {face_found_count}/{analysis_end - analysis_start + 1}")

    # Signal-Zusammenfassung über GT-Bereich
    gt_indices = [i for i, fn in enumerate(frame_nums) if start_frame <= fn <= end_frame]
    if gt_indices and nose_y_buf:
        gt_y = np.array([nose_y_buf[i] for i in gt_indices])
        gt_x = np.array([nose_x_buf[i] for i in gt_indices])
        gt_b = np.array([bridge_y_buf[i] for i in gt_indices])

        y_range = gt_y.max() - gt_y.min()
        x_range = gt_x.max() - gt_x.min()

        # Velocity
        if len(gt_y) >= 3:
            vel = np.diff(gt_y)
            revs = sum(1 for i in range(1, len(vel)) if vel[i-1] * vel[i] < 0)
        else:
            revs = 0

        # Correlation
        if len(gt_y) >= 5:
            vel_y = np.diff(gt_y)
            vel_b = np.diff(gt_b)
            n = min(len(vel_y), len(vel_b))
            corr = float(np.corrcoef(vel_y[:n], vel_b[:n])[0, 1])
            if np.isnan(corr):
                corr = 0
        else:
            corr = 0

        res_scale = height / calibration_height
        thr = nod_threshold * res_scale

        print(f"\n  Signal im GT-Bereich ({len(gt_indices)} frames):")
        print(f"    Y-Range:    {y_range:.1f} px  (threshold ~{thr:.1f})")
        print(f"    X-Range:    {x_range:.1f} px  (x/y ratio: {x_range/max(y_range,0.01):.2f})")
        print(f"    Reversals:  {revs}")
        print(f"    Nose-Bridge Corr: {corr:.3f}")
        print(f"    Y min/max:  {gt_y.min():.1f} / {gt_y.max():.1f}")

    return nose_y_buf, nose_x_buf, bridge_y_buf, frame_nums


def check_pattern_debug(pat, y_arr, x_arr, b_arr, thr, k, fps,
                        tilt_arr=None, yaw_arr=None):
    """Pattern-Check mit detailliertem Failure-Reporting."""
    f = pat['filters']
    result = {'passed': False, 'fail_reason': 'unknown', 'confidence': 0}

    win_frames = int(pat['window_s'] * fps)
    y = y_arr[-win_frames:]
    x = x_arr[-win_frames:]
    b = b_arr[-win_frames:]

    y_range = float(y.max() - y.min())
    x_range = float(x.max() - x.min())
    result['y_range'] = y_range
    result['x_range'] = x_range

    # X-Drift mit Tilt- und Yaw-Korrektur
    x_drift_ratio = f.get('x_drift_ratio', 0.7)
    expected_x_total = 0.0
    tilt_deg = 0.0
    yaw_dev = 0.0
    if tilt_arr is not None and len(tilt_arr) > 0:
        t = tilt_arr[-win_frames:]
        median_tilt = float(np.median(t))
        tilt_deg = math.degrees(median_tilt)
        expected_x_total += y_range * abs(math.tan(median_tilt))
    if yaw_arr is not None and len(yaw_arr) > 0:
        yw = yaw_arr[-win_frames:]
        median_yaw = float(np.median(yw))
        yaw_dev = abs(median_yaw - 0.5) * 2.0
        expected_x_total += y_range * yaw_dev * 1.2
    corrected_x = max(0.0, x_range - expected_x_total)
    result['tilt_deg'] = tilt_deg
    result['yaw_dev'] = yaw_dev
    result['corrected_x'] = corrected_x
    if y_range > 0 and corrected_x >= x_drift_ratio * (y_range ** 0.7):
        limit = x_drift_ratio * (y_range ** 0.7)
        result['fail_reason'] = (f'x_drift (corr_x={corrected_x:.1f} >= '
                                 f'{x_drift_ratio}*{y_range:.1f}^0.7={limit:.1f}, '
                                 f'raw_x={x_range:.1f}, tilt={tilt_deg:.1f}°, '
                                 f'yaw_dev={yaw_dev:.2f})')
        return result

    # Smooth + Velocity
    y_smooth = np.convolve(y, np.ones(k) / k, mode='valid')
    b_smooth = np.convolve(b, np.ones(k) / k, mode='valid')
    vel_y = np.diff(y_smooth)
    vel_b = np.diff(b_smooth)

    rev_indices = [i for i in range(1, len(vel_y)) if vel_y[i-1] * vel_y[i] < 0]
    reversals = len(rev_indices)
    result['reversals'] = reversals

    min_rev = f.get('min_reversals', 0)
    max_rev = f.get('max_reversals')
    if reversals < min_rev:
        result['fail_reason'] = f'reversals ({reversals} < {min_rev})'
        return result
    if max_rev is not None and reversals > max_rev:
        result['fail_reason'] = f'max_reversals ({reversals} > {max_rev})'
        return result

    # Correlation
    corr = 0.0
    if len(vel_y) >= 5 and len(vel_b) >= 5:
        n = min(len(vel_y), len(vel_b))
        corr = float(np.corrcoef(vel_y[:n], vel_b[:n])[0, 1])
        if np.isnan(corr):
            corr = 0.0
    result['corr'] = corr

    min_corr = f.get('min_correlation', 0.85)
    if corr < min_corr:
        result['fail_reason'] = f'correlation ({corr:.3f} < {min_corr})'
        return result

    # Frequency
    pattern_revs = rev_indices[-min_rev:] if min_rev > 0 else rev_indices
    max_gap = f.get('max_reversal_gap')
    if max_gap is not None and len(pattern_revs) >= 2:
        rev_gaps = np.diff(pattern_revs)
        median_gap = float(np.median(rev_gaps))
        if median_gap > max_gap:
            result['fail_reason'] = f'frequency (median_gap={median_gap:.1f} > {max_gap})'
            return result

    # Oscillation range
    if len(pattern_revs) >= 2:
        typical_gap = int(np.median(np.diff(pattern_revs)))
    else:
        typical_gap = max_gap or 7
    osc_start = max(0, pattern_revs[0] - typical_gap) if pattern_revs else 0
    osc_y = y_smooth[osc_start:]
    osc_y_range = float(osc_y.max() - osc_y.min())

    # Damping
    half_amplitudes = []
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
        else:
            damping_ratio = 0.5

        min_damp = f.get('min_damping')
        if min_damp is not None and len(half_amplitudes) >= 3:
            if damping_ratio < min_damp:
                result['fail_reason'] = f'damping ({damping_ratio:.2f} < {min_damp})'
                return result

    # Amplitude ratio
    min_amp_ratio = f.get('min_amplitude_ratio')
    if min_amp_ratio is not None and len(half_amplitudes) >= 2:
        ratio = half_amplitudes[1] / half_amplitudes[0] if half_amplitudes[0] > 0 else 0
        if ratio < min_amp_ratio:
            result['fail_reason'] = f'amplitude_ratio ({ratio:.2f} < {min_amp_ratio})'
            return result

    # Amplitude threshold
    amp_factor = f.get('amplitude_factor', 1.0)
    effective_thr = thr * amp_factor

    dyn = f.get('dynamic_threshold')
    if dyn and dyn.get('enabled') and len(pattern_revs) >= 2:
        osc_strength = min(len(pattern_revs) / 4.0, 1.0) * corr
        max_red = dyn.get('max_reduction', 0.4)
        effective_thr = thr * (1.0 - max_red * osc_strength)

    if osc_y_range < effective_thr:
        result['fail_reason'] = (f'amplitude (osc_range={osc_y_range:.1f} < '
                                 f'eff_thr={effective_thr:.1f} '
                                 f'[base_thr={thr:.1f} * amp_factor={amp_factor}])')
        return result

    # Passed!
    result['passed'] = True
    result['fail_reason'] = None

    # Confidence
    c = pat['confidence']
    weights = c['weights']
    scores = {}
    median_gap = float(np.median(np.diff(pattern_revs))) if len(pattern_revs) >= 2 else 0
    damping_ratio = damping_ratio if 'damping_ratio' in dir() else 0.5

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

    confidence = sum(weights[wk] * scores[wk] for wk in weights if wk in scores)
    confidence *= c.get('multiplier', 1.0)
    confidence = min(confidence, c.get('max', 1.0))
    result['confidence'] = confidence

    return result


def main():
    import cv2

    globals_cfg, patterns = load_patterns()
    print(f"Patterns: {[p['name'] for p in patterns]}")
    print(f"Threshold: {globals_cfg['nod_threshold']}")
    print(f"Video: {VIDEO}")

    cap = cv2.VideoCapture(VIDEO)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Resolution: {width}x{height}, Frames: {total}")

    # MediaPipe FaceLandmarker (Tasks API)
    model_path = Path(__file__).parent / "face_landmarker.task"
    base_options = mp_tasks.BaseOptions(model_asset_path=str(model_path))
    options = mp_vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(options)

    for name, start, end in GT_REGIONS:
        # Neuen Landmarker pro Region (Timestamp muss monoton steigend sein)
        landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        analyze_region(cap, landmarker, start, end, name,
                       globals_cfg, patterns, width, height)
        landmarker.close()

    cap.release()
    print(f"\n{'='*70}")
    print("Debug abgeschlossen")


if __name__ == '__main__':
    main()
