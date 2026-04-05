#!/usr/bin/env python3
"""
Build Base EDL from Audio (RMS Diarization)
Erstellt Base-Timeline aus zwei Mikrofon-Spuren via RMS-Pegelvergleich.

TC-Umrechnung identisch zu add_reactions_to_edl.py:
    reference_frame      = ffprobe embedded TC (frames)
    timeline_zero_video  = 0 - cam_edl_frame   (welcher Video-Frame liegt bei EDL Frame 0)
    video_frame          = timeline_zero_video + edl_frame
    source_tc_frame      = reference_frame + video_frame
"""

import argparse
import json
import subprocess
import wave
import numpy as np
from pathlib import Path


# ─── Timecode-Hilfsfunktionen (unverändert aus add_reactions_to_edl.py) ───────

def timecode_to_frames(tc: str, fps: float = 25.0) -> int:
    parts = tc.split(':')
    hours, minutes, seconds, frames = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return int((hours * 3600 + minutes * 60 + seconds) * fps + frames)


def frames_to_timecode(frames: int, fps: float = 25.0) -> str:
    if frames < 0:
        frames = 0
    total_seconds = frames / fps
    hours   = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    frame   = int(frames % fps)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame:02d}"


def get_reference_frame(video_path: str, fps: float) -> int:
    """Liest embedded TC via ffprobe → Reference Frame (identisch zu add_reactions_to_edl.py)"""
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
               '-show_format', '-show_streams', str(video_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)

        # format tags zuerst
        tc = data.get('format', {}).get('tags', {}).get('timecode')
        if not tc:
            for stream in data.get('streams', []):
                tc = stream.get('tags', {}).get('timecode')
                if tc:
                    break

        if tc:
            return timecode_to_frames(tc, fps), tc
    except Exception as e:
        print(f"  ⚠️  ffprobe Fehler ({Path(video_path).name}): {e}")
    return None, None


# ─── Audio-Analyse ─────────────────────────────────────────────────────────────

def load_audio(path: str):
    with wave.open(path, 'rb') as wf:
        sr  = wf.getframerate()
        n_ch = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_ch > 1:
        audio = audio.reshape(-1, n_ch).mean(axis=1)
    return audio, sr


def compute_rms_db(audio: np.ndarray, sr: int, window_s: float) -> np.ndarray:
    win = int(sr * window_s)
    rms_db = []
    for i in range(0, len(audio) - win, win):
        chunk = audio[i:i+win]
        rms = np.sqrt(np.mean(chunk**2))
        rms_db.append(20 * np.log10(rms + 1e-9))
    return np.array(rms_db)


def rms_diarize(audio1: np.ndarray, audio2: np.ndarray, sr: int,
                window_s: float, threshold_db: float,
                change_delay_s: float, min_edit_s: float):
    """
    RMS-Pegelvergleich → Segmente mit 'CAM1'/'CAM2' Speaker-Label.
    audio1 = Mikrofon für CAM1, audio2 = Mikrofon für CAM2.
    """
    rms1 = compute_rms_db(audio1, sr, window_s)
    rms2 = compute_rms_db(audio2, sr, window_s)
    n = min(len(rms1), len(rms2))
    rms1, rms2 = rms1[:n], rms2[:n]

    diff = rms1 - rms2
    dominant = np.full(n, None, dtype=object)
    dominant[diff >  threshold_db] = 'CAM1'
    dominant[diff < -threshold_db] = 'CAM2'

    # Change-Delay smoothing
    delay_wins = max(1, int(change_delay_s / window_s))
    smoothed = list(dominant)
    current, streak = None, 0
    for i in range(n):
        raw = dominant[i]
        if raw == current or raw is None:
            streak = 0
            smoothed[i] = current
        else:
            streak += 1
            smoothed[i] = current if streak < delay_wins else raw
            if streak >= delay_wins:
                current = raw

    # Rohe Segmente
    segments, seg_start, seg_spk = [], 0, smoothed[0]
    for i in range(1, n):
        if smoothed[i] != seg_spk:
            segments.append({'speaker': seg_spk, 'start': seg_start, 'end': i})
            seg_start, seg_spk = i, smoothed[i]
    segments.append({'speaker': seg_spk, 'start': seg_start, 'end': n})

    # Min-Edit-Duration merge
    min_wins = max(1, int(min_edit_s / window_s))
    changed = True
    while changed:
        changed = False
        out, i = [], 0
        while i < len(segments):
            seg = segments[i]
            if (seg['end'] - seg['start']) < min_wins and seg['speaker'] is not None:
                prev_dur = segments[i-1]['end'] - segments[i-1]['start'] if i > 0 else 0
                next_dur = segments[i+1]['end'] - segments[i+1]['start'] if i < len(segments)-1 else 0
                if prev_dur >= next_dur and out:
                    out[-1]['end'] = seg['end']
                elif i < len(segments) - 1:
                    segments[i+1]['start'] = seg['start']
                    i += 1
                    continue
                changed = True
            else:
                out.append(seg)
            i += 1
        segments = out

    # None → Nachbar
    for i, seg in enumerate(segments):
        if seg['speaker'] is None:
            seg['speaker'] = segments[i-1]['speaker'] if i > 0 else \
                             (segments[i+1]['speaker'] if i < len(segments)-1 else 'CAM1')

    # Nachbarn mergen
    final = []
    for seg in segments:
        s_s = seg['start'] * window_s
        e_s = seg['end']   * window_s
        if final and final[-1]['speaker'] == seg['speaker']:
            final[-1]['end_s'] = e_s
        else:
            final.append({'speaker': seg['speaker'], 'start_s': s_s, 'end_s': e_s})

    return final


# ─── EDL schreiben ─────────────────────────────────────────────────────────────

def write_edl(events: list, output_path: str, title: str = "Audio Base Timeline"):
    with open(output_path, 'w') as f:
        f.write(f"TITLE: {title}\n")
        f.write("FCM: NON-DROP FRAME\n\n")
        for i, ev in enumerate(events, 1):
            f.write(f"{i:03d}  AX       V     C        "
                    f"{ev['source_in']} {ev['source_out']} "
                    f"{ev['record_in']} {ev['record_out']}\n")
            f.write(f"* FROM CLIP NAME: {ev['clip_name']}\n\n")
    print(f"\n✓ EDL geschrieben: {output_path}")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Build Base EDL from Audio (RMS)')

    # Audio
    parser.add_argument('--mic-cam1', required=True, help='Mikrofon-Spur für CAM1 (WAV)')
    parser.add_argument('--mic-cam2', required=True, help='Mikrofon-Spur für CAM2 (WAV)')

    # Video (für ffprobe embedded TC)
    parser.add_argument('--cam1-video', required=True, help='CAM1 Video-Datei')
    parser.add_argument('--cam2-video', required=True, help='CAM2 Video-Datei')
    parser.add_argument('--cam1-clip',  required=True, help='CAM1 Clip-Name in der EDL')
    parser.add_argument('--cam2-clip',  required=True, help='CAM2 Clip-Name in der EDL')

    # Sync-Offsets (vom User aus Resolve)
    parser.add_argument('--wav-edl-frame',  type=int, required=True,
                        help='EDL-Frame bei dem WAV Frame 0 liegt')
    parser.add_argument('--cam1-edl-frame', type=int, required=True,
                        help='EDL-Frame bei dem CAM1 Frame 0 liegt')
    parser.add_argument('--cam2-edl-frame', type=int, required=True,
                        help='EDL-Frame bei dem CAM2 Frame 0 liegt')

    # RMS-Parameter
    parser.add_argument('--min-edit-duration', type=float, default=1.0)
    parser.add_argument('--change-delay',       type=float, default=0.3)
    parser.add_argument('--threshold-db',        type=float, default=6.0)
    parser.add_argument('--analysis-window',     type=float, default=0.05)

    parser.add_argument('--fps',    type=float, default=25.0)
    parser.add_argument('--output', '-o', default='base.edl')
    args = parser.parse_args()

    print("=" * 70)
    print("🎙️  BUILD BASE EDL FROM AUDIO")
    print("=" * 70)

    # ── 1. Reference Frames via ffprobe ───────────────────────────────────────
    print("\n🎯 Lese embedded Timecodes...")
    cam1_ref, cam1_tc = get_reference_frame(args.cam1_video, args.fps)
    cam2_ref, cam2_tc = get_reference_frame(args.cam2_video, args.fps)

    if cam1_ref is None or cam2_ref is None:
        print("✗ Konnte embedded TC nicht lesen. Abbruch.")
        return 1

    # TC-Umrechnung identisch zu add_reactions_to_edl.py:
    #   timeline_zero_video = 0 - cam_edl_frame
    #   video_frame         = timeline_zero_video + edl_frame
    #   source_tc_frame     = reference_frame + video_frame
    cam1_timeline_zero_video = 0 - args.cam1_edl_frame   # = -535
    cam2_timeline_zero_video = 0 - args.cam2_edl_frame   # =    0

    print(f"  CAM1 ({args.cam1_clip}): embedded TC {cam1_tc} = {cam1_ref} frames")
    print(f"        EDL Frame 0 liegt bei Video Frame {cam1_timeline_zero_video}")
    print(f"  CAM2 ({args.cam2_clip}): embedded TC {cam2_tc} = {cam2_ref} frames")
    print(f"        EDL Frame 0 liegt bei Video Frame {cam2_timeline_zero_video}")

    # ── 2. Audio laden & diarisieren ──────────────────────────────────────────
    print("\n📂 Lade Audio...")
    audio_cam1, sr1 = load_audio(args.mic_cam1)
    audio_cam2, sr2 = load_audio(args.mic_cam2)
    assert sr1 == sr2, f"Sample rates differ: {sr1} vs {sr2}"
    n = min(len(audio_cam1), len(audio_cam2))
    audio_cam1, audio_cam2 = audio_cam1[:n], audio_cam2[:n]
    duration_s = n / sr1
    print(f"  Länge: {duration_s/60:.1f} min")

    print("\n📊 RMS-Diarization...")
    segments = rms_diarize(
        audio_cam1, audio_cam2, sr1,
        args.analysis_window, args.threshold_db,
        args.change_delay, args.min_edit_duration
    )
    print(f"  {len(segments)} Segmente erkannt")

    # ── 3. Audio-Segmente → EDL-Events ────────────────────────────────────────
    print("\n🔨 Baue EDL-Events...")
    events = []
    skipped = 0

    for seg in segments:
        # Audio-Zeit → EDL-Frame
        edl_start = round(seg['start_s'] * args.fps) + args.wav_edl_frame
        edl_end   = round(seg['end_s']   * args.fps) + args.wav_edl_frame

        speaker = seg['speaker']

        # Prüfe ob zugewiesene Kamera bereits läuft, sonst Fallback
        if speaker == 'CAM1' and edl_start < args.cam1_edl_frame:
            if edl_end <= args.cam1_edl_frame:
                speaker = 'CAM2'  # ganzes Segment vor CAM1-Start → CAM2
            else:
                # Segment überlappt CAM1-Start: aufteilen
                # Teil vor CAM1-Start → CAM2
                edl_end_pre = args.cam1_edl_frame
                cam2_video_start = cam2_timeline_zero_video + edl_start
                cam2_video_end   = cam2_timeline_zero_video + edl_end_pre
                if cam2_video_start >= 0 and edl_end_pre > edl_start:
                    events.append({
                        'clip_name':  args.cam2_clip,
                        'source_in':  frames_to_timecode(cam2_ref + cam2_video_start, args.fps),
                        'source_out': frames_to_timecode(cam2_ref + cam2_video_end,   args.fps),
                        'record_in':  frames_to_timecode(edl_start,    args.fps),
                        'record_out': frames_to_timecode(edl_end_pre,  args.fps),
                    })
                # Rest des Segments → CAM1 (ab cam1_edl_frame)
                edl_start = args.cam1_edl_frame
                speaker = 'CAM1'

        # Berechne Source TCs für das (ggf. angepasste) Segment
        if speaker == 'CAM1':
            ref  = cam1_ref
            tz   = cam1_timeline_zero_video
            clip = args.cam1_clip
        else:
            ref  = cam2_ref
            tz   = cam2_timeline_zero_video
            clip = args.cam2_clip

        video_start = tz + edl_start
        video_end   = tz + edl_end

        if video_start < 0:
            skipped += 1
            continue

        if edl_end <= edl_start:
            continue

        events.append({
            'clip_name':  clip,
            'source_in':  frames_to_timecode(ref + video_start, args.fps),
            'source_out': frames_to_timecode(ref + video_end,   args.fps),
            'record_in':  frames_to_timecode(edl_start,         args.fps),
            'record_out': frames_to_timecode(edl_end,           args.fps),
        })

    if skipped:
        print(f"  ⚠️  {skipped} Segmente übersprungen (vor Kamera-Start, kein Fallback möglich)")

    # ── 4. Statistik ──────────────────────────────────────────────────────────
    cam1_evts = [e for e in events if e['clip_name'] == args.cam1_clip]
    cam2_evts = [e for e in events if e['clip_name'] == args.cam2_clip]

    def dur_s(ev):
        from_tc = lambda tc: sum(int(x)*f for x,f in zip(tc.split(':'), [3600*args.fps, 60*args.fps, args.fps, 1]))
        return (from_tc(ev['record_out']) - from_tc(ev['record_in'])) / args.fps

    cam1_s = sum(dur_s(e) for e in cam1_evts)
    cam2_s = sum(dur_s(e) for e in cam2_evts)
    total  = cam1_s + cam2_s

    print(f"\n📈 Ergebnis:")
    print(f"  Events: {len(events)}")
    print(f"  {args.cam1_clip}: {cam1_s/60:.1f} min ({cam1_s/total*100:.0f}%)")
    print(f"  {args.cam2_clip}: {cam2_s/60:.1f} min ({cam2_s/total*100:.0f}%)")

    # ── 5. EDL schreiben ──────────────────────────────────────────────────────
    write_edl(events, args.output)

    print("\n" + "=" * 70)
    print("✅ FERTIG")
    print("=" * 70)
    print(f"  Base-EDL: {args.output}")
    print(f"  Nächster Schritt: add_reactions_to_edl.py --resolve-edl {args.output} ...")
    print("=" * 70)
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
