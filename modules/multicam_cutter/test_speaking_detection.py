#!/usr/bin/env python3
"""
Diagnose-Skript: Speaking Detection gegen Resolve-Marker testen.

Liest A1-Clip und Marker aus der aktiven Timeline, läuft die relative
Burst-Erkennung drüber und vergleicht Treffer mit den gesetzten Markern.

Usage:
    python3 test_speaking_detection.py [--rise-db 12.0] [--min-dur 0.25] [--max-dur 1.2]
"""
import sys
import argparse
import numpy as np
import soundfile as sf
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from resolve_bridge.connection import get_resolve
from resolve_bridge.markers import add_marker, delete_markers_by_color


def _rms_windows(audio: np.ndarray, sr: int, window_s: float):
    win = int(sr * window_s)
    n = len(audio) // win
    db = np.zeros(n)
    for i in range(n):
        chunk = audio[i * win:(i + 1) * win]
        db[i] = 20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-9)
    return db


def detect_bursts(audio: np.ndarray, sr: int, fps: float,
                  window_s: float, rise_db: float,
                  min_duration_s: float, max_duration_s: float,
                  timeline_start_frame: int = 0):
    """Detect bursts relative to per-file 10th-percentile baseline."""
    db = _rms_windows(audio, sr, window_s)
    baseline = float(np.percentile(db, 10))
    threshold = baseline + rise_db

    print(f"  Baseline (p10): {baseline:.1f} dBFS")
    print(f"  Threshold:      {threshold:.1f} dBFS  (baseline + {rise_db} dB)")

    min_wins = max(1, int(min_duration_s / window_s))
    max_wins = max(1, int(max_duration_s / window_s))

    bursts = []
    i = 0
    while i < len(db):
        if db[i] > threshold:
            j = i
            while j < len(db) and db[j] > threshold:
                j += 1
            burst_len = j - i
            if min_wins <= burst_len <= max_wins:
                start_s = i * window_s
                end_s   = j * window_s
                peak_db = float(np.max(db[i:j]))
                conf    = min(1.0, 0.5 + (peak_db - threshold) / 20.0)
                tl_frame = timeline_start_frame + round(start_s * fps)
                bursts.append({
                    'start_s':  start_s,
                    'end_s':    end_s,
                    'dur_s':    end_s - start_s,
                    'peak_db':  round(peak_db, 1),
                    'conf':     round(conf, 3),
                    'tl_frame': tl_frame,
                })
            i = j
        else:
            i += 1
    return bursts


def tc_to_s(tc: str, fps: float) -> float:
    """HH:MM:SS:FF → seconds"""
    parts = tc.split(':')
    if len(parts) == 4:
        h, m, s, f = parts
        return int(h)*3600 + int(m)*60 + int(s) + int(f)/fps
    return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rise-db',  type=float, default=12.0)
    parser.add_argument('--min-dur',  type=float, default=0.25)
    parser.add_argument('--max-dur',     type=float, default=1.2)
    parser.add_argument('--window',      type=float, default=0.05)
    parser.add_argument('--clear',    action='store_true',
                        help='Löscht vorhandene Green/Red Marker vor dem Lauf')
    args = parser.parse_args()

    # ── Resolve verbinden ────────────────────────────────────────────────────
    resolve  = get_resolve()
    project  = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    fps      = float(timeline.GetSetting('timelineFrameRate'))
    tl_name  = timeline.GetName()
    print(f"\n{'='*60}")
    print(f"Timeline: {tl_name}  ({fps} fps)")
    print(f"{'='*60}")

    # ── Marker lesen ─────────────────────────────────────────────────────────
    raw_markers = timeline.GetMarkers() or {}
    # Keys are frame offsets from timeline start
    tl_start_frame = int(timeline.GetStartFrame())
    markers = []
    for frame_offset, data in sorted(raw_markers.items()):
        abs_frame = tl_start_frame + int(frame_offset)
        markers.append({
            'frame': abs_frame,
            'time_s': abs_frame / fps,
            'name':  data.get('name', ''),
            'color': data.get('color', ''),
        })
    print(f"\n🔖 Marker ({len(markers)} gesetzt):")
    for m in markers:
        print(f"   Frame {m['frame']:6d}  ({m['time_s']:.2f}s)  [{m['color']}] {m['name']}")

    # ── A1 Clip lesen ────────────────────────────────────────────────────────
    a1_items = timeline.GetItemListInTrack('audio', 1) or []
    if not a1_items:
        print("\n✗ Keine Clips auf A1 gefunden.")
        return 1

    clip = a1_items[0]
    mp_item   = clip.GetMediaPoolItem()
    file_path = mp_item.GetClipProperty('File Path') if mp_item else None
    if not file_path or not Path(file_path).exists():
        print(f"\n✗ Datei nicht gefunden: {file_path}")
        return 1

    clip_tl_start = int(clip.GetStart())
    clip_src_start_frame = int(clip.GetLeftOffset())  # frames from file start

    print(f"\n🎙  A1 Clip: {Path(file_path).name}")
    print(f"   Timeline-Start: Frame {clip_tl_start}")
    print(f"   Source-Offset:  Frame {clip_src_start_frame}")

    # ── Audio laden ──────────────────────────────────────────────────────────
    audio, sr = sf.read(file_path, dtype='float32', always_2d=False)
    if audio.ndim > 1:
        audio = audio[:, 0]  # erstes Kanal

    # Nur den Teil laden der in der Timeline liegt
    src_start_sample = int(clip_src_start_frame / fps * sr)
    clip_dur_frames  = int(clip.GetDuration())
    src_end_sample   = src_start_sample + int(clip_dur_frames / fps * sr)
    audio = audio[src_start_sample:src_end_sample]

    print(f"   Dauer: {len(audio)/sr:.1f}s  ({len(audio)} samples @ {sr} Hz)")

    # ── Burst-Erkennung ──────────────────────────────────────────────────────
    print(f"\n🔍 Burst-Erkennung  (rise={args.rise_db} dB, "
          f"min={args.min_dur}s, max={args.max_dur}s)")
    bursts = detect_bursts(
        audio, sr, fps,
        window_s=args.window,
        rise_db=args.rise_db,
        min_duration_s=args.min_dur,
        max_duration_s=args.max_dur,
        timeline_start_frame=clip_tl_start,
    )

    print(f"\n  Gefunden: {len(bursts)} Burst(s)\n")
    for b in bursts:
        tl_s = b['tl_frame'] / fps
        print(f"  ▶ {b['start_s']:6.2f}s – {b['end_s']:5.2f}s  "
              f"({b['dur_s']:.2f}s)  peak={b['peak_db']:5.1f} dBFS  "
              f"conf={b['conf']:.2f}  →  TL-Frame {b['tl_frame']} ({tl_s:.2f}s)")

    # ── Vergleich mit Markern ─────────────────────────────────────────────────
    if markers:
        print(f"\n📊 Abgleich Bursts ↔ Marker (±{args.max_dur:.1f}s Toleranz):\n")
        for m in markers:
            m_tl_s = m['time_s']
            hit = None
            for b in bursts:
                b_tl_s = b['tl_frame'] / fps
                if abs(b_tl_s - m_tl_s) <= args.max_dur:
                    hit = b
                    break
            status = "✅ GETROFFEN" if hit else "❌ VERPASST"
            offset = f"  Δ={hit['tl_frame']/fps - m_tl_s:+.2f}s" if hit else ""
            print(f"  {status}  Marker @ {m_tl_s:.2f}s  [{m['name'] or m['color']}]{offset}")

    # ── True/False Positive trennen ───────────────────────────────────────────
    marker_times = [m['time_s'] for m in markers]
    true_pos  = []
    false_pos = []
    for b in bursts:
        b_tl_s = b['tl_frame'] / fps
        if any(abs(b_tl_s - mt) <= args.max_dur for mt in marker_times):
            true_pos.append(b)
        else:
            false_pos.append(b)

    print(f"\n⚠️  Mögliche False Positives: {len(false_pos)}")
    for b in false_pos:
        print(f"   @ {b['tl_frame']/fps:.2f}s  ({b['dur_s']:.2f}s, "
              f"peak={b['peak_db']:.1f} dBFS, conf={b['conf']:.2f})")

    # ── Marker in Resolve setzen ──────────────────────────────────────────────
    print(f"\n📍 Setze Resolve-Marker...")
    if args.clear:
        delete_markers_by_color('green')
        delete_markers_by_color('red')
        print("   Vorhandene Green/Red Marker gelöscht.")

    added_tp = added_fp = 0
    for b in true_pos:
        dur_frames = max(1, round(b['dur_s'] * fps))
        ok = add_marker(
            frame=b['tl_frame'],
            color='green',
            name=f"SR hit {b['conf']:.2f}",
            note=f"peak={b['peak_db']:.1f} dBFS  dur={b['dur_s']:.2f}s",
            duration=dur_frames,
        )
        added_tp += bool(ok)

    for b in false_pos:
        dur_frames = max(1, round(b['dur_s'] * fps))
        ok = add_marker(
            frame=b['tl_frame'],
            color='red',
            name=f"SR fp {b['conf']:.2f}",
            note=f"peak={b['peak_db']:.1f} dBFS  dur={b['dur_s']:.2f}s",
            duration=dur_frames,
        )
        added_fp += bool(ok)

    print(f"   ✅ Green (Treffer):          {added_tp}")
    print(f"   🔴 Red   (False Positives):  {added_fp}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
