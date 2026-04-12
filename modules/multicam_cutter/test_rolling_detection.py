#!/usr/bin/env python3
"""
Diagnose-Skript: Rolling-Baseline Speaking Detection gegen Resolve-Marker testen.

Statt eines statischen Schwellwerts (10th-Perzentil pro Segment) wird eine
gleitende Mittelwert-Baseline berechnet. Ein Burst wird erkannt wenn das
aktuelle RMS-Fenster den laufenden Mittelwert der letzten N Sekunden um
mehr als rise_db überschreitet.

Vorteil: Passt sich automatisch an langsam verändernde Crossbleed-Pegel an.
Ein "Mhm" ist ein kurzer steiler Ausschlag, der schneller kommt als die
Baseline sich anpassen kann.

Setup in Resolve:
  1. Sync-Timeline öffnen
  2. A1-Clip auswählen (MIC des off-camera Sprechers)
  3. Blaue Marker auf erkennbare Reaktionen setzen (Referenz-Cutaways)
  4. Script ausführen

Usage:
    python3 test_rolling_detection.py
    python3 test_rolling_detection.py --rise-db 10.0 --baseline-window 3.0
    python3 test_rolling_detection.py --rise-db 8.0 --min-dur 0.2 --max-dur 1.5 --clear
"""
import sys
import argparse
import numpy as np
import soundfile as sf
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from resolve_bridge.connection import get_resolve
from resolve_bridge.markers import add_marker, delete_markers_by_color


# ── Kernfunktion: Rolling-Baseline Burst Detection ────────────────────────────

def _rms_windows(audio: np.ndarray, sr: int, window_s: float) -> np.ndarray:
    win = int(sr * window_s)
    n = len(audio) // win
    db = np.zeros(n)
    for i in range(n):
        chunk = audio[i * win:(i + 1) * win]
        db[i] = 20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-9)
    return db


def detect_bursts_rolling(
    audio: np.ndarray, sr: int, fps: float,
    window_s: float,
    attack_window_s: float,
    release_window_s: float,
    warmup_s: float,
    rise_db: float,
    min_duration_s: float,
    max_duration_s: float,
    hold_s: float = 0.0,
    timeline_start_frame: int = 0,
    return_debug: bool = False,
):
    """
    Einseitige Baseline mit Event-Reset:
    - Baseline folgt dem Signal nur nach OBEN (geglättet über attack_window_s)
    - Während Stille/Pausen: Baseline hält den letzten Pegel (kein Abfall)
    - Nach jedem validen Burst: Baseline ab Burst-Ende auf aktuellen Pegel resetten

    Zwei-Pass-Ansatz:
    Pass 1: Initiale einseitige Baseline berechnen (ohne Resets)
    Pass 2: Bursts erkennen; nach jedem validen Burst Baseline ab dort neu berechnen
    """
    db = _rms_windows(audio, sr, window_s)
    attack_n  = max(1, int(attack_window_s / window_s))
    release_n = max(1, int(release_window_s / window_s))
    min_wins  = max(1, int(min_duration_s / window_s))
    max_wins  = max(1, int(max_duration_s / window_s))
    hold_wins = int(hold_s / window_s)
    alpha_a   = 1.0 / attack_n   # schnell hoch
    alpha_r   = 1.0 / release_n  # langsam runter

    def _build_baseline(db, start_idx, start_val):
        """Asymmetrische Baseline: steigt schnell (attack), fällt langsam (release)."""
        b = np.empty(len(db))
        b[:start_idx] = 0.0
        b[start_idx] = start_val
        for k in range(start_idx + 1, len(db)):
            if db[k] > b[k - 1]:
                b[k] = b[k - 1] + alpha_a * (db[k] - b[k - 1])
            else:
                b[k] = b[k - 1] + alpha_r * (db[k] - b[k - 1])
        return b

    # Pass 1: initiale Baseline — Startwert aus Perzentil der ersten warmup_s Sekunden
    # Damit startet die Baseline bereits auf Crossbleed-Niveau statt bei db[0]
    warmup_n    = max(1, int(warmup_s / window_s))
    start_val   = float(np.percentile(db[:warmup_n], 75))
    baseline = _build_baseline(db, 0, start_val)

    print(f"  Fenster:  {window_s*1000:.0f}ms  ({len(db)} Fenster total)")
    print(f"  Baseline: Attack {attack_window_s:.1f}s / Release {release_window_s:.0f}s / Warmup {warmup_s:.1f}s (p75), Reset nach Burst")
    print(f"  Rise:     {rise_db} dB über Baseline")
    print(f"  Dauer:    {min_duration_s*1000:.0f}ms – {max_duration_s*1000:.0f}ms  Hold: {hold_s*1000:.0f}ms")

    # Pass 2: Bursts erkennen + Baseline nach jedem validen Burst resetten
    bursts = []
    i = 0
    while i < len(db):
        if db[i] > baseline[i] + rise_db:
            j = i
            hold_count = 0
            while j < len(db):
                if db[j] > baseline[j] + rise_db:
                    hold_count = 0
                    j += 1
                elif hold_count < hold_wins:
                    hold_count += 1
                    j += 1
                else:
                    break
            # actual_end: letztes Fenster über dem Schwellwert (Hold-Tail abschneiden)
            # burst_len:  gesamte Spanne inkl. Hold-Brücken (für min/max-Dauer-Check)
            actual_end = j - hold_count
            burst_len = j - i
            if min_wins <= burst_len <= max_wins:
                start_s  = i * window_s
                end_s    = actual_end * window_s
                peak_db  = float(np.max(db[i:actual_end]))
                avg_rise = float(np.mean(db[i:actual_end] - baseline[i:actual_end]))
                conf     = min(1.0, 0.5 + avg_rise / 20.0)
                tl_frame = timeline_start_frame + round(start_s * fps)
                bursts.append({
                    'start_s':  start_s,
                    'end_s':    end_s,
                    'dur_s':    end_s - start_s,
                    'peak_db':  round(peak_db, 1),
                    'baseline': round(float(baseline[i]), 1),
                    'rise':     round(avg_rise, 1),
                    'conf':     round(conf, 3),
                    'tl_frame': tl_frame,
                })
                # Reset: Baseline ab Burst-Ende neu aufbauen — vom PRE-BURST-Niveau,
                # nicht vom Post-Burst-Signal (db[j]). Der Burst ist ein Transient;
                # der Hintergrundpegel hat sich nicht geändert. Dadurch bleibt die
                # Baseline nach einem Crossbleed-Burst niedrig genug, um den nächsten
                # echten Speech-Event zu erkennen.
                if actual_end < len(db):
                    new_baseline = _build_baseline(db, actual_end, baseline[i])
                    baseline[actual_end:] = new_baseline[actual_end:]
            i = actual_end if actual_end > i else i + 1
        else:
            i += 1
    if return_debug:
        return bursts, baseline, db
    return bursts


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Rolling-Baseline Speaking Detection Test')
    parser.add_argument('--rise-db',          type=float, default=10.0,
                        help='Mindestanstieg über Rolling-Mean (default: 10.0 dB)')
    parser.add_argument('--attack-window',    type=float, default=1.0,
                        help='Glättungsfenster für Baseline-Anstieg in Sekunden (default: 1.0)')
    parser.add_argument('--release-window',   type=float, default=20.0,
                        help='Glättungsfenster für Baseline-Abfall in Sekunden (default: 20.0)')
    parser.add_argument('--warmup',           type=float, default=3.0,
                        help='Sekunden am Clip-Anfang für Baseline-Vorinitialisierung via p75 (default: 3.0)')
    parser.add_argument('--min-dur',          type=float, default=0.20,
                        help='Minimale Burst-Dauer in Sekunden (default: 0.20)')
    parser.add_argument('--max-dur',          type=float, default=1.5,
                        help='Maximale Burst-Dauer in Sekunden (default: 1.5)')
    parser.add_argument('--hold',             type=float, default=0.0,
                        help='Hold-Zeit in Sekunden: Burst bleibt aktiv wenn Pegel kurz unter Schwellwert fällt (default: 0.0)')
    parser.add_argument('--window',           type=float, default=0.05,
                        help='RMS-Fenstergröße in Sekunden (default: 0.05)')
    parser.add_argument('--track',            type=int,   default=1,
                        help='Audio-Spur (default: 1 = A1)')
    parser.add_argument('--clear',            action='store_true',
                        help='Vorhandene Green/Red Marker vor dem Lauf löschen')
    parser.add_argument('--debug-baseline',   action='store_true',
                        help='Beim letzten Clip alle 5 Frames einen Cyan-Marker mit Baseline- und dB-Wert setzen')
    args = parser.parse_args()

    # ── Resolve verbinden ────────────────────────────────────────────────────
    resolve  = get_resolve()
    project  = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    fps      = float(timeline.GetSetting('timelineFrameRate'))
    tl_name  = timeline.GetName()

    print(f"\n{'='*60}")
    print(f"Timeline: {tl_name}  ({fps} fps)")
    print(f"Rolling-Baseline Detection")
    print(f"{'='*60}")

    # ── Marker lesen ─────────────────────────────────────────────────────────
    raw_markers   = timeline.GetMarkers() or {}
    tl_start_frame = int(timeline.GetStartFrame())
    markers = []
    for frame_offset, data in sorted(raw_markers.items()):
        abs_frame = tl_start_frame + int(frame_offset)
        markers.append({
            'frame':  abs_frame,
            'time_s': abs_frame / fps,
            'name':   data.get('name', ''),
            'color':  data.get('color', ''),
        })

    ref_markers = [m for m in markers if m['color'].lower() not in ('green', 'red', 'cyan')]
    print(f"\n🔖 Referenz-Marker ({len(ref_markers)} gesetzt):")
    for m in ref_markers:
        print(f"   Frame {m['frame']:6d}  ({m['time_s']:.2f}s)  [{m['color']}] {m['name']}")

    # ── Alle Clips auf gewählter Spur verarbeiten ────────────────────────────
    items = timeline.GetItemListInTrack('audio', args.track) or []
    if not items:
        print(f"\n✗ Keine Clips auf A{args.track} gefunden.")
        return 1

    print(f"\n🎙  A{args.track}: {len(items)} Clip(s)")

    # ── Rolling-Baseline Detection über alle Clips ───────────────────────────
    print(f"\n🔍 Rolling-Baseline Detection:")
    bursts = []
    debug_clip_data = None  # (clip_tl_start, baseline, db, clip_dur_frames) für letzten Clip
    for clip in items:
        mp_item   = clip.GetMediaPoolItem()
        file_path = mp_item.GetClipProperty('File Path') if mp_item else None
        if not file_path or not Path(file_path).exists():
            print(f"   ⚠ Datei nicht gefunden: {file_path} — übersprungen")
            continue

        clip_tl_start        = int(clip.GetStart())
        clip_src_start_frame = int(clip.GetLeftOffset())
        clip_dur_frames      = int(clip.GetDuration())

        audio, sr = sf.read(file_path, dtype='float32', always_2d=False)
        if audio.ndim > 1:
            audio = audio[:, 0]

        src_start_sample = int(clip_src_start_frame / fps * sr)
        src_end_sample   = src_start_sample + int(clip_dur_frames / fps * sr)
        audio = audio[src_start_sample:src_end_sample]

        print(f"\n   [{Path(file_path).name}]  TL-Start: {clip_tl_start}  Dauer: {len(audio)/sr:.1f}s")

        is_last_clip = (clip == items[-1])
        result = detect_bursts_rolling(
            audio, sr, fps,
            window_s=args.window,
            attack_window_s=args.attack_window,
            release_window_s=args.release_window,
            warmup_s=args.warmup,
            rise_db=args.rise_db,
            min_duration_s=args.min_dur,
            max_duration_s=args.max_dur,
            hold_s=args.hold,
            timeline_start_frame=clip_tl_start,
            return_debug=(args.debug_baseline and is_last_clip),
        )
        if args.debug_baseline and is_last_clip:
            clip_bursts, bl_arr, db_arr = result
            debug_clip_data = (clip_tl_start, bl_arr, db_arr, clip_dur_frames)
        else:
            clip_bursts = result
        bursts.extend(clip_bursts)

    print(f"\n  Gefunden: {len(bursts)} Burst(s)\n")
    for b in bursts:
        tl_s = b['tl_frame'] / fps
        print(f"  ▶ {b['start_s']:6.2f}s – {b['end_s']:5.2f}s  "
              f"({b['dur_s']:.2f}s)  "
              f"peak={b['peak_db']:5.1f} dBFS  "
              f"baseline={b['baseline']:5.1f}  "
              f"rise={b['rise']:4.1f} dB  "
              f"conf={b['conf']:.2f}  "
              f"→  TL-Frame {b['tl_frame']} ({tl_s:.2f}s)")

    # ── Abgleich mit Markern ─────────────────────────────────────────────────
    if ref_markers:
        tol = args.max_dur
        print(f"\n📊 Abgleich Bursts ↔ Marker (±{tol:.1f}s Toleranz):\n")
        for m in ref_markers:
            m_tl_s = m['time_s']
            hit = next((b for b in bursts if abs(b['tl_frame']/fps - m_tl_s) <= tol), None)
            status = "✅ GETROFFEN" if hit else "❌ VERPASST"
            offset = f"  Δ={hit['tl_frame']/fps - m_tl_s:+.2f}s" if hit else ""
            print(f"  {status}  Marker @ {m_tl_s:.2f}s  [{m['name'] or m['color']}]{offset}")

    # ── True/False Positives ─────────────────────────────────────────────────
    marker_times = [m['time_s'] for m in ref_markers]
    true_pos, false_pos = [], []
    for b in bursts:
        b_tl_s = b['tl_frame'] / fps
        if any(abs(b_tl_s - mt) <= args.max_dur for mt in marker_times):
            true_pos.append(b)
        else:
            false_pos.append(b)

    if ref_markers:
        print(f"\n  ✅ True Positives:   {len(true_pos)}")
        print(f"  🔴 False Positives:  {len(false_pos)}")
        if bursts:
            precision = len(true_pos) / len(bursts)
            print(f"  📈 Precision:        {precision:.0%}")

    print(f"\n⚠️  False Positives:")
    for b in false_pos:
        print(f"   @ {b['tl_frame']/fps:.2f}s  "
              f"({b['dur_s']:.2f}s, peak={b['peak_db']:.1f} dBFS, "
              f"baseline={b['baseline']:.1f}, rise={b['rise']:.1f} dB, conf={b['conf']:.2f})")

    # ── Marker in Resolve setzen ──────────────────────────────────────────────
    print(f"\n📍 Setze Resolve-Marker...")
    if args.clear:
        delete_markers_by_color('green')
        delete_markers_by_color('red')
        print("   Vorhandene Green/Red Marker gelöscht.")
    if args.debug_baseline:
        delete_markers_by_color('cyan')
        print("   Vorhandene Cyan Marker gelöscht.")

    added_tp = added_fp = 0
    for b in true_pos:
        dur_frames = max(1, round(b['dur_s'] * fps))
        ok = add_marker(
            frame=b['tl_frame'],
            color='green',
            name=f"RB hit {b['conf']:.2f}",
            note=f"peak={b['peak_db']:.1f} baseline={b['baseline']:.1f} rise={b['rise']:.1f}dB dur={b['dur_s']:.2f}s",
            duration=dur_frames,
        )
        added_tp += bool(ok)

    for b in false_pos:
        dur_frames = max(1, round(b['dur_s'] * fps))
        ok = add_marker(
            frame=b['tl_frame'],
            color='red',
            name=f"RB fp {b['conf']:.2f}",
            note=f"peak={b['peak_db']:.1f} baseline={b['baseline']:.1f} rise={b['rise']:.1f}dB dur={b['dur_s']:.2f}s",
            duration=dur_frames,
        )
        added_fp += bool(ok)

    print(f"   ✅ Green (Treffer):         {added_tp}")
    print(f"   🔴 Red   (False Positives): {added_fp}")

    # ── Debug: Baseline-Marker auf letztem Clip ───────────────────────────────
    if args.debug_baseline and debug_clip_data:
        clip_tl_start, bl_arr, db_arr, clip_dur_frames = debug_clip_data
        added_debug = 0
        for frame_offset in range(0, clip_dur_frames, 5):
            win_idx = int(frame_offset / fps / args.window)
            if win_idx >= len(bl_arr):
                break
            tl_f = clip_tl_start + frame_offset
            ok = add_marker(
                frame=tl_f,
                color='cyan',
                name=f"{bl_arr[win_idx]:.1f}",
                note=f"db={db_arr[win_idx]:.1f} baseline={bl_arr[win_idx]:.1f} rise={db_arr[win_idx]-bl_arr[win_idx]:.1f}dB",
                duration=1,
            )
            added_debug += bool(ok)
        print(f"   🔵 Cyan  (Baseline-Debug):  {added_debug}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
