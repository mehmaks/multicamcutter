#!/usr/bin/env python3
"""
Liest Marker aus der aktiven Resolve-Timeline und mappt sie auf Events
aus der timeline_manifest.json (Speaker, Nodding, Speaking, MaxTime).

Usage:
    python3 marker_to_reactions.py [--analyse-dir DIR] [--tolerance 2.0]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from resolve_bridge.connection import get_resolve


def frames_to_tc(frames: int, fps: float) -> str:
    total_frames = int(frames)
    f = total_frames % int(fps)
    total_s = total_frames // int(fps)
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def tc_to_frames(tc: str, fps: float) -> int:
    parts = tc.strip().split(':')
    h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return int((h * 3600 + m * 60 + s) * fps + f)


def find_clip_at_frame(clips, frame):
    for clip in clips:
        if clip['tl_start'] <= frame < clip['tl_end']:
            return clip
    return None


def main():
    parser = argparse.ArgumentParser(description='Map Resolve markers to analyse events')
    parser.add_argument('--analyse-dir', type=str, default=None)
    parser.add_argument('--tolerance', type=float, default=2.0,
                        help='Toleranz in Sekunden (default: 2.0)')
    parser.add_argument('--color', type=str, default=None,
                        help='Nur Marker dieser Farbe')
    args = parser.parse_args()

    # ── Resolve ──────────────────────────────────────────────────────────────
    resolve = get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        print("Keine aktive Timeline.")
        return 1

    fps = float(timeline.GetSetting("timelineFrameRate") or 25.0)
    tl_start_frame = int(timeline.GetStartFrame())
    print(f"Timeline: {timeline.GetName()}  ({fps} fps)")

    # ── Video-Clips auf Timeline ─────────────────────────────────────────────
    video_clips = []
    for i in range(1, timeline.GetTrackCount("video") + 1):
        for item in (timeline.GetItemListInTrack("video", i) or []):
            mi = item.GetMediaPoolItem()
            if mi is None:
                continue
            video_clips.append({
                'name': item.GetName(),
                'file_path': mi.GetClipProperty("File Path") or "",
                'tl_start': int(item.GetStart()),
                'tl_end': int(item.GetEnd()),
                'src_start': int(item.GetLeftOffset()),
                'track': i,
            })
    video_clips.sort(key=lambda c: c['tl_start'])
    print(f"Video-Clips auf Timeline: {len(video_clips)}")

    # ── Marker ───────────────────────────────────────────────────────────────
    raw_markers = timeline.GetMarkers() or {}
    markers = []
    for frame_offset, data in sorted(raw_markers.items()):
        color = data.get('color', '')
        if args.color and color.lower() != args.color.lower():
            continue
        markers.append({
            'frame': tl_start_frame + int(frame_offset),
            'name': data.get('name', ''),
            'color': color,
            'note': data.get('note', ''),
        })
    print(f"Marker: {len(markers)}")

    # ── Analyse-Dir ermitteln ────────────────────────────────────────────────
    analyse_dir = args.analyse_dir
    if not analyse_dir:
        for clip in video_clips:
            candidate = Path(clip['file_path']).parent / "analyse"
            if candidate.exists():
                analyse_dir = str(candidate)
                break
    if not analyse_dir:
        print("Kein analyse-Ordner gefunden. Bitte --analyse-dir angeben.")
        return 1

    # ── Manifest + Cameras laden ─────────────────────────────────────────────
    manifest_path = Path(analyse_dir) / "timeline_manifest.json"
    cameras_path = Path(analyse_dir) / "cameras.json"

    with open(manifest_path) as fh:
        manifest = json.load(fh)
    with open(cameras_path) as fh:
        cameras = json.load(fh)

    # CAM-Index → Clip-Dateiname (CAM1=cameras[0], CAM2=cameras[1], ...)
    cam_to_file = {}
    for i, cam in enumerate(cameras):
        cam_to_file[f"CAM{i+1}"] = Path(cam['name']).stem  # z.B. "C5835"
    print(f"Kamera-Mapping: {cam_to_file}")

    # Manifest in Source-Frame-Bereiche umwandeln, pro Clip
    # Jedes Event deckt [source_frame, next_event.source_frame) ab
    manifest_events = []
    for j, ev in enumerate(manifest):
        clip_stem = cam_to_file.get(ev['clip'], ev['clip'])
        src_frame = ev['source_frame']
        # End-Frame = Source-Frame des nächsten Events auf demselben Clip, oder +inf
        src_end = float('inf')
        for k in range(j + 1, len(manifest)):
            nxt = manifest[k]
            nxt_stem = cam_to_file.get(nxt['clip'], nxt['clip'])
            if nxt_stem == clip_stem:
                src_end = nxt['source_frame']
                break
        manifest_events.append({
            'clip': clip_stem,
            'src_start': src_frame,
            'src_end': src_end,
            'reason': ev['reason'],
            'record_tc': ev['record_tc'],
            'idx': ev['idx'],
        })

    reasons_count = {}
    for e in manifest_events:
        reasons_count[e['reason']] = reasons_count.get(e['reason'], 0) + 1
    print(f"Manifest-Events: {len(manifest_events)}  {reasons_count}")

    # ── Marker → Manifest matchen ────────────────────────────────────────────
    tol_frames = int(args.tolerance * fps)

    print(f"\n{'='*120}")
    print(f"{'#':<5} {'Color':<7} {'TL-Fr':>7} {'Clip':<12} {'Src-Fr':>8} {'Src-TC':<14} "
          f"{'Manifest-Match':<55} {'Note'}")
    print(f"{'='*120}")

    matched = 0
    unmatched_markers = []

    for i, m in enumerate(markers):
        clip = find_clip_at_frame(video_clips, m['frame'])
        if not clip:
            label = m['name'] or f"M{i+1}"
            print(f"{label:<5} {m['color']:<7} {m['frame']:>7}  {'-- kein Clip --':<12}")
            unmatched_markers.append((i + 1, m, 'kein Clip'))
            continue

        src_frame = m['frame'] - clip['tl_start'] + clip['src_start']
        src_tc = frames_to_tc(src_frame, fps)
        clip_stem = Path(clip['file_path']).stem

        # Exaktes Match: Marker-Source-Frame liegt im Manifest-Event-Bereich
        exact_match = None
        for ev in manifest_events:
            if ev['clip'] == clip_stem and ev['src_start'] <= src_frame < ev['src_end']:
                exact_match = ev
                break

        # Nahestes Match mit Toleranz
        near_match = None
        near_dist = float('inf')
        for ev in manifest_events:
            if ev['clip'] != clip_stem:
                continue
            dist = min(abs(src_frame - ev['src_start']),
                       abs(src_frame - ev['src_end']) if ev['src_end'] != float('inf') else float('inf'))
            if dist < near_dist:
                near_dist = dist
                near_match = ev

        match_str = ""
        if exact_match:
            match_str = (f"#{exact_match['idx']:>4} [{exact_match['reason']}] "
                         f"rec={exact_match['record_tc']} "
                         f"src={exact_match['src_start']}-{int(exact_match['src_end']) if exact_match['src_end'] != float('inf') else '?'}")
            matched += 1
        elif near_match and near_dist <= tol_frames:
            delta_s = near_dist / fps
            match_str = (f"~{delta_s:.1f}s → #{near_match['idx']:>4} [{near_match['reason']}] "
                         f"rec={near_match['record_tc']}")
            matched += 1
        else:
            delta_s = near_dist / fps if near_match else 0
            reason = near_match['reason'] if near_match else '?'
            match_str = f"KEIN MATCH (nächstes: {delta_s:.1f}s → [{reason}])"
            unmatched_markers.append((i + 1, m, match_str))

        label = m['name'] or f"M{i+1}"
        note = m['note'][:40] if m['note'] else ""
        print(f"{label:<5} {m['color']:<7} {m['frame']:>7} {clip['name']:<12} "
              f"{src_frame:>8} {src_tc:<14} {match_str:<55} {note}")

    # ── Zusammenfassung ──────────────────────────────────────────────────────
    total = len(markers)
    print(f"\n{'─'*120}")
    print(f"Gesamt: {total} Marker, {matched} gematcht ({matched/total*100:.0f}%), "
          f"{total - matched} ohne Match ({(total-matched)/total*100:.0f}%)")

    if unmatched_markers:
        print(f"\nNicht gematchte Marker:")
        for num, m, reason in unmatched_markers:
            note = f"  [{m['note'][:60]}]" if m['note'] else ""
            print(f"  M{num}: Frame {m['frame']}{note}  → {reason}")

    return 0


if __name__ == '__main__':
    main()
