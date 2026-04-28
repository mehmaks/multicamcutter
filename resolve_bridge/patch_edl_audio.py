"""
Reads an existing video-only EDL and appends continuous audio tracks
(MIC1/MIC2) derived directly from the current Resolve timeline.

The audio clips run uncut — only the video is cut.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve_bridge.timeline_reader import read_timeline, get_primary_wav_clip


from shared.frame_utils import (
    frames_to_timecode as frames_to_tc,
    timecode_to_frames as tc_to_frames,
)


def build_audio_edl_entries(tl, start_event_num: int, fps: float) -> list[str]:
    """
    Returns EDL lines for continuous MIC1 (A1) and MIC2 (A2) tracks.
    Channel A1 = Audio Track 1, A2 = Audio Track 2 in Resolve EDL format.
    """
    lines = []
    # MIC1=A1 (track 1), MIC2=A2 (track 2)
    assignments = [(1, "A1"), (2, "A2")]

    for track_idx, channel in assignments:
        clips = tl.audio_tracks.get(track_idx)
        if not clips:
            print(f"  Warnung: Audiospur {track_idx} leer — übersprungen.")
            continue

        wav = get_primary_wav_clip(clips)
        if wav is None:
            print(f"  Warnung: Kein WAV auf Audiospur {track_idx} — übersprungen.")
            continue

        # Source timecodes
        src_start_frames = tc_to_frames(wav.start_tc, fps) + wav.source_start_frame
        duration_frames = wav.timeline_end - wav.timeline_start  # how long it sits in timeline
        src_end_frames = src_start_frames + duration_frames

        # Record timecodes (where it lands in the new timeline)
        rec_in_frames = wav.timeline_start  # e.g. 140
        rec_out_frames = wav.timeline_end   # e.g. 109133

        src_in  = frames_to_tc(src_start_frames, fps)
        src_out = frames_to_tc(src_end_frames, fps)
        rec_in  = frames_to_tc(rec_in_frames, fps)
        rec_out = frames_to_tc(rec_out_frames, fps)

        clip_name = os.path.basename(wav.file_path)
        n = start_event_num + (track_idx - 1)

        lines.append(f"{n:03d}  AX       {channel:<5} C        {src_in} {src_out} {rec_in} {rec_out}")
        lines.append(f"* FROM CLIP NAME: {clip_name}")
        lines.append("")

        print(f"  {channel}: {clip_name}")
        print(f"    Source:  {src_in} → {src_out}")
        print(f"    Record:  {rec_in} → {rec_out}")

    return lines


def patch_edl_with_audio(input_edl: str, output_edl: str, timeline_name: str = None):
    print(f"Lese Timeline aus Resolve...")
    tl = read_timeline(timeline_name)
    fps = tl.fps

    print(f"Timeline: {tl.timeline_name} ({fps} fps)")
    print()

    # Bestehende EDL einlesen
    with open(input_edl, "r") as f:
        existing = f.read().rstrip()

    # Letzten Event-Index ermitteln
    last_num = 0
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped and stripped[0].isdigit():
            try:
                last_num = max(last_num, int(stripped.split()[0]))
            except (ValueError, IndexError):
                pass

    print(f"Bestehende EDL: {last_num} Video-Events")
    print(f"Hänge Audio-Spuren an...")

    audio_lines = build_audio_edl_entries(tl, last_num + 1, fps)

    with open(output_edl, "w") as f:
        f.write(existing)
        f.write("\n\n")
        f.write("\n".join(audio_lines))

    print()
    print(f"Gespeichert: {output_edl}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",    required=True, help="Video-EDL (Eingabe)")
    parser.add_argument("--output",   required=True, help="EDL mit Audio (Ausgabe)")
    parser.add_argument("--timeline", default=None,  help="Name der Sync-Timeline (default: aktive Timeline)")
    args = parser.parse_args()
    patch_edl_with_audio(args.input, args.output, args.timeline)
