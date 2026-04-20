#!/usr/bin/env python3
"""
Liest die aktive Resolve-Timeline aus, holt die Audio-Clips im
In/Out-markierten Bereich und startet visualize_baseline.py damit.

Verwendung:
    # In Resolve: In/Out-Bereich setzen, dann:
    python tools/visualize_from_resolve.py

    # Oder manuell Timecodes angeben:
    python tools/visualize_from_resolve.py --in-tc 00:05:00:00 --out-tc 00:08:00:00

    # Audio-Tracks angeben (default: A1 + A2):
    python tools/visualize_from_resolve.py --tracks 1 2

    # Nur ein MIC (ohne Diarization):
    python tools/visualize_from_resolve.py --tracks 1

    # Alle Parameter an visualize_baseline.py durchreichen:
    python tools/visualize_from_resolve.py --rise-db 8 --release 30
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve_bridge.connection import get_resolve


def tc_to_frames(tc: str, fps: float) -> int:
    """HH:MM:SS:FF -> absolute frames."""
    parts = tc.split(':')
    if len(parts) != 4:
        raise ValueError(f"Ungültiger Timecode: {tc}")
    h, m, s, f = [int(x) for x in parts]
    return int((h * 3600 + m * 60 + s) * fps + f)


def frames_to_tc(frames: int, fps: float) -> str:
    """Absolute frames -> HH:MM:SS:FF."""
    f = int(frames % fps)
    total_s = int(frames // fps)
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def get_in_out_frames(timeline, fps: float, args):
    """
    Liest In/Out-Markierung aus der Timeline via GetMarkInOut().
    Fallback: CLI-Argumente --in-tc / --out-tc.
    """
    in_frame = None
    out_frame = None

    # Versuch 1: GetMarkInOut() API
    mark_data = timeline.GetMarkInOut()
    if mark_data and 'video' in mark_data:
        v = mark_data['video']
        if v.get('in') is not None:
            in_frame = int(v['in'])
        if v.get('out') is not None:
            out_frame = int(v['out'])

    # Versuch 2: CLI-Argumente (Override)
    if args.in_tc:
        in_frame = tc_to_frames(args.in_tc, fps)
    if args.out_tc:
        out_frame = tc_to_frames(args.out_tc, fps)

    if in_frame is None or out_frame is None:
        print("\n  Kein In/Out-Bereich in der Timeline gesetzt.")
        print("  Bitte In/Out setzen oder manuell angeben: --in-tc HH:MM:SS:FF --out-tc HH:MM:SS:FF")
        sys.exit(1)

    in_tc = frames_to_tc(in_frame, fps)
    out_tc = frames_to_tc(out_frame, fps)
    return in_frame, out_frame, in_tc, out_tc


def find_audio_clip(timeline, track_idx: int, in_frame: int, out_frame: int):
    """Findet den Audio-Clip auf dem Track, der den In/Out-Bereich enthält."""
    items = timeline.GetItemListInTrack('audio', track_idx) or []
    if not items:
        return None

    # Clip finden, der den In-Point enthält
    for clip in items:
        clip_start = int(clip.GetStart())
        clip_end = int(clip.GetEnd())
        if clip_start <= in_frame < clip_end:
            mp_item = clip.GetMediaPoolItem()
            if not mp_item:
                continue
            file_path = mp_item.GetClipProperty('File Path')
            if not file_path or not Path(file_path).exists():
                continue
            return {
                'path': file_path,
                'tl_start': clip_start,
                'left_offset': int(clip.GetLeftOffset()),
                'duration': int(clip.GetDuration()),
                'clip_end': clip_end,
            }

    return None


def main():
    parser = argparse.ArgumentParser(
        description='Resolve In/Out → visualize_baseline.py'
    )
    parser.add_argument('--in-tc', default=None,
                        help='In-Punkt Timecode (HH:MM:SS:FF), wenn nicht aus Resolve lesbar')
    parser.add_argument('--out-tc', default=None,
                        help='Out-Punkt Timecode (HH:MM:SS:FF), wenn nicht aus Resolve lesbar')
    parser.add_argument('--tracks', type=int, nargs='+', default=[1, 2],
                        help='Audio-Track-Nummern (default: 1 2)')
    parser.add_argument('--save', default=None,
                        help='Plot als PNG speichern statt anzeigen')

    # Parameter die an visualize_baseline.py durchgereicht werden
    parser.add_argument('--window', type=float, default=None)
    parser.add_argument('--rise-db', type=float, default=None)
    parser.add_argument('--attack', type=float, default=None)
    parser.add_argument('--release', type=float, default=None)
    parser.add_argument('--warmup', type=float, default=None)
    parser.add_argument('--min-dur', type=float, default=None)
    parser.add_argument('--max-dur', type=float, default=None)
    parser.add_argument('--hold', type=float, default=None)
    parser.add_argument('--mode', choices=['rms', 'peak'], default=None)
    parser.add_argument('--baseline-mode', choices=['ema', 'percentile'], default=None)
    parser.add_argument('--burst-mode', choices=['threshold', 'rise'], default=None)
    parser.add_argument('--lookback', type=float, default=None)
    parser.add_argument('--sustain-margin', type=float, default=None)
    parser.add_argument('--decay-hold', type=float, default=None)
    parser.add_argument('--percentile', type=float, default=None)
    parser.add_argument('--baseline-window', type=float, default=None)
    parser.add_argument('--threshold-db', type=float, default=None)
    parser.add_argument('--change-delay', type=float, default=None)
    parser.add_argument('--min-edit', type=float, default=None)
    parser.add_argument('--linear', action='store_true', default=False)
    parser.add_argument('--compare-attack', type=float, nargs='+', default=None)
    args = parser.parse_args()

    # ── Resolve verbinden ────────────────────────────────────────────────────
    print("Verbinde mit Resolve ...")
    resolve = get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    fps = float(timeline.GetSetting('timelineFrameRate'))
    tl_name = timeline.GetName()
    tl_start = int(timeline.GetStartFrame())

    print(f"  Timeline: {tl_name}  ({fps} fps)")
    print(f"  Start:    Frame {tl_start} ({frames_to_tc(tl_start, fps)})")

    # ── In/Out-Bereich ───────────────────────────────────────────────────────
    in_frame, out_frame, in_tc, out_tc = get_in_out_frames(timeline, fps, args)
    print(f"\n  In:  {in_tc}  (Frame {in_frame})")
    print(f"  Out: {out_tc}  (Frame {out_frame})")
    print(f"  Dauer: {(out_frame - in_frame) / fps:.1f}s")

    # ── Audio-Clips finden ───────────────────────────────────────────────────
    clips = []
    for track_idx in args.tracks:
        info = find_audio_clip(timeline, track_idx, in_frame, out_frame)
        if info:
            print(f"\n  A{track_idx}: {Path(info['path']).name}")
            print(f"    TL-Start: Frame {info['tl_start']}, "
                  f"Left-Offset: {info['left_offset']}, "
                  f"Clip-Ende: Frame {info['clip_end']}")
            clips.append(info)
        else:
            print(f"\n  A{track_idx}: kein Clip im In/Out-Bereich")

    if not clips:
        print("\nKeine Audio-Clips gefunden!")
        return 1

    # ── Timeline-Frames → Source-File-Sekunden umrechnen ─────────────────────
    # Für jeden Clip:
    #   source_frame = left_offset + (timeline_frame - clip_tl_start)
    #   source_seconds = source_frame / fps
    wav_paths = []
    start_s_list = []
    end_s_list = []

    for info in clips:
        # In/Out relativ zum Clip-Start in der Timeline
        src_in = info['left_offset'] + (in_frame - info['tl_start'])
        src_out = info['left_offset'] + (out_frame - info['tl_start'])

        src_in_s = src_in / fps
        src_out_s = src_out / fps

        print(f"\n  {Path(info['path']).name}:")
        print(f"    Source-Range: {src_in_s:.2f}s – {src_out_s:.2f}s")

        wav_paths.append(info['path'])
        start_s_list.append(src_in_s)
        end_s_list.append(src_out_s)

    # ── visualize_baseline.py aufrufen ───────────────────────────────────────
    # venv-Python nutzen (hat matplotlib + numpy), System-Python hat es oft nicht
    venv_python = ROOT / 'venv' / 'bin' / 'python3'
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    script = str(ROOT / 'tools' / 'visualize_baseline.py')
    cmd = [python_exe, script, wav_paths[0],
           '--start', str(start_s_list[0]),
           '--end', str(end_s_list[0])]

    if len(wav_paths) > 1:
        cmd.extend(['--mic2', wav_paths[1]])

    # Durchgereichte Parameter
    passthrough = {
        '--window': args.window,
        '--rise-db': args.rise_db,
        '--attack': args.attack,
        '--release': args.release,
        '--warmup': args.warmup,
        '--min-dur': args.min_dur,
        '--max-dur': args.max_dur,
        '--hold': args.hold,
        '--mode': args.mode,
        '--baseline-mode': args.baseline_mode,
        '--burst-mode': args.burst_mode,
        '--lookback': args.lookback,
        '--sustain-margin': args.sustain_margin,
        '--decay-hold': args.decay_hold,
        '--percentile': args.percentile,
        '--baseline-window': args.baseline_window,
        '--threshold-db': args.threshold_db,
        '--change-delay': args.change_delay,
        '--min-edit': args.min_edit,
    }
    for flag, val in passthrough.items():
        if val is not None:
            cmd.extend([flag, str(val)])

    if args.linear:
        cmd.append('--linear')
    if args.compare_attack:
        cmd.extend(['--compare-attack'] + [str(v) for v in args.compare_attack])
    if args.save:
        cmd.extend(['--save', args.save])

    print(f"\n{'='*60}")
    print(f"  {' '.join(cmd)}")
    print(f"{'='*60}\n")

    return subprocess.call(cmd)


if __name__ == '__main__':
    sys.exit(main())
