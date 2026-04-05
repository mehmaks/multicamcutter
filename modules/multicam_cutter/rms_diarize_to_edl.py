#!/usr/bin/env python3
"""
RMS-basiertes Audio-Diarization Test-Script
Analysiert zwei Mikrofon-Spuren und erstellt eine EDL basierend darauf,
welche Spur zu welchem Zeitpunkt dominiert.

Resolve-äquivalente Parameter:
  --min-edit-duration  → Minimum Edit Duration (default: 1.0s)
  --change-delay       → Edit Change Delay (default: 0.3s)
"""

import argparse
import wave
import numpy as np
from pathlib import Path


def load_audio(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, 'rb') as wf:
        sr = wf.getframerate()
        n_ch = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_ch > 1:
        audio = audio.reshape(-1, n_ch).mean(axis=1)
    return audio, sr


def compute_rms_db(audio: np.ndarray, sr: int, window_s: float) -> np.ndarray:
    win = int(sr * window_s)
    hop = win  # kein Overlap, direkte Fenster
    rms_db = []
    for i in range(0, len(audio) - win, hop):
        chunk = audio[i:i+win]
        rms = np.sqrt(np.mean(chunk**2))
        rms_db.append(20 * np.log10(rms + 1e-9))
    return np.array(rms_db)


def frames_to_timecode(frames: int, fps: float = 25.0) -> str:
    total_seconds = frames / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    frame = int(frames % fps)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame:02d}"


def write_edl(events: list, output_path: str, mic1_clip: str, mic2_clip: str, fps: float):
    with open(output_path, 'w') as f:
        f.write("TITLE: RMS Diarization\n")
        f.write("FCM: NON-DROP FRAME\n\n")
        for i, ev in enumerate(events, 1):
            clip = mic1_clip if ev['speaker'] == 'MIC1' else mic2_clip
            src_in  = frames_to_timecode(ev['start_frame'], fps)
            src_out = frames_to_timecode(ev['end_frame'], fps)
            rec_in  = frames_to_timecode(ev['start_frame'], fps)
            rec_out = frames_to_timecode(ev['end_frame'], fps)
            f.write(f"{i:03d}  AX       AA    C        {src_in} {src_out} {rec_in} {rec_out}\n")
            f.write(f"* FROM CLIP NAME: {clip}\n\n")
    print(f"\n✓ EDL geschrieben: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='RMS Diarization → EDL')
    parser.add_argument('--mic1', required=True, help='Mikrofon-Spur 1 (WAV)')
    parser.add_argument('--mic2', required=True, help='Mikrofon-Spur 2 (WAV)')
    parser.add_argument('--mic1-clip', default='CAM1.MP4', help='Clip-Name in EDL für MIC1')
    parser.add_argument('--mic2-clip', default='CAM2.MP4', help='Clip-Name in EDL für MIC2')
    parser.add_argument('--output', '-o', default='rms_diarization.edl')
    parser.add_argument('--fps', type=float, default=25.0)
    parser.add_argument('--min-edit-duration', type=float, default=1.0,
                        help='Minimale Shot-Länge in Sekunden (default: 1.0)')
    parser.add_argument('--change-delay', type=float, default=0.3,
                        help='Wie lange neue Spur dominieren muss bevor geschnitten wird (default: 0.3s)')
    parser.add_argument('--threshold-db', type=float, default=6.0,
                        help='Mindest-Pegelunterschied für Dominanz in dB (default: 6.0)')
    parser.add_argument('--analysis-window', type=float, default=0.05,
                        help='Analyse-Fenstergröße in Sekunden (default: 0.05s = 50ms)')
    args = parser.parse_args()

    print("=" * 70)
    print("🎙️  RMS DIARIZATION → EDL")
    print("=" * 70)
    print(f"\nParameter:")
    print(f"  Min Edit Duration : {args.min_edit_duration}s")
    print(f"  Change Delay      : {args.change_delay}s")
    print(f"  Threshold         : {args.threshold_db} dB")
    print(f"  Analysis Window   : {args.analysis_window*1000:.0f}ms")

    # Audio laden
    print(f"\n📂 Lade Audio...")
    audio1, sr1 = load_audio(args.mic1)
    audio2, sr2 = load_audio(args.mic2)
    assert sr1 == sr2, f"Sample rates stimmen nicht überein: {sr1} vs {sr2}"
    sr = sr1

    # Auf gleiche Länge kürzen
    n = min(len(audio1), len(audio2))
    audio1, audio2 = audio1[:n], audio2[:n]
    duration_s = n / sr
    print(f"  Länge: {duration_s/60:.1f} min ({duration_s:.1f}s)")

    # RMS pro Fenster berechnen
    print(f"\n📊 Berechne RMS-Pegel...")
    rms1 = compute_rms_db(audio1, sr, args.analysis_window)
    rms2 = compute_rms_db(audio2, sr, args.analysis_window)
    n_win = min(len(rms1), len(rms2))
    rms1, rms2 = rms1[:n_win], rms2[:n_win]

    # Dominanz pro Fenster bestimmen
    # 'MIC1', 'MIC2', oder None (Stille / unklar)
    diff = rms1 - rms2
    dominant = np.full(n_win, None, dtype=object)
    dominant[diff >  args.threshold_db] = 'MIC1'
    dominant[diff < -args.threshold_db] = 'MIC2'

    win_s = args.analysis_window
    delay_wins = int(args.change_delay / win_s)
    min_edit_wins = int(args.min_edit_duration / win_s)

    # Edit Change Delay: Neuer Speaker muss `delay_wins` Fenster
    # konsistent dominieren bevor wir wechseln
    smoothed = list(dominant)
    current = None
    consecutive_new = 0

    for i in range(n_win):
        raw = dominant[i]
        if raw == current or raw is None:
            consecutive_new = 0
            smoothed[i] = current
        else:
            consecutive_new += 1
            if consecutive_new >= delay_wins:
                current = raw
                smoothed[i] = current
            else:
                smoothed[i] = current  # noch beim alten Speaker

    # Segmente bilden (zusammenhängende gleiche Speaker)
    segments = []
    if n_win > 0:
        seg_start = 0
        seg_speaker = smoothed[0]
        for i in range(1, n_win):
            if smoothed[i] != seg_speaker:
                segments.append({'speaker': seg_speaker, 'start': seg_start, 'end': i})
                seg_start = i
                seg_speaker = smoothed[i]
        segments.append({'speaker': seg_speaker, 'start': seg_start, 'end': n_win})

    # Min Edit Duration: kurze Segmente mit Nachbarn mergen
    merged = True
    while merged:
        merged = False
        new_segs = []
        i = 0
        while i < len(segments):
            seg = segments[i]
            dur_wins = seg['end'] - seg['start']
            if dur_wins < min_edit_wins and seg['speaker'] is not None:
                # Zu kurz → mit längerem Nachbarn mergen
                prev_dur = segments[i-1]['end'] - segments[i-1]['start'] if i > 0 else 0
                next_dur = segments[i+1]['end'] - segments[i+1]['start'] if i < len(segments)-1 else 0
                if prev_dur >= next_dur and i > 0:
                    new_segs[-1]['end'] = seg['end']
                elif i < len(segments) - 1:
                    segments[i+1]['start'] = seg['start']
                    i += 1
                    continue
                merged = True
            else:
                new_segs.append(seg)
            i += 1
        segments = new_segs

    # None-Segmente (Stille) dem vorherigen Speaker zuordnen
    for i, seg in enumerate(segments):
        if seg['speaker'] is None:
            if i > 0:
                seg['speaker'] = segments[i-1]['speaker']
            elif i < len(segments) - 1:
                seg['speaker'] = segments[i+1]['speaker']
            else:
                seg['speaker'] = 'MIC1'  # Fallback

    # Benachbarte gleiche Speaker mergen
    final = []
    for seg in segments:
        if final and final[-1]['speaker'] == seg['speaker']:
            final[-1]['end'] = seg['end']
        else:
            final.append(dict(seg))

    # In Frames (für EDL) konvertieren
    events = []
    for seg in final:
        start_s = seg['start'] * win_s
        end_s = seg['end'] * win_s
        events.append({
            'speaker': seg['speaker'],
            'start_s': start_s,
            'end_s': end_s,
            'start_frame': int(round(start_s * args.fps)),
            'end_frame': int(round(end_s * args.fps)),
        })

    # Statistik
    print(f"\n📈 Ergebnis:")
    print(f"  Segmente gesamt: {len(events)}")
    mic1_s = sum(e['end_s'] - e['start_s'] for e in events if e['speaker'] == 'MIC1')
    mic2_s = sum(e['end_s'] - e['start_s'] for e in events if e['speaker'] == 'MIC2')
    print(f"  MIC1 ({args.mic1_clip}): {mic1_s/60:.1f} min ({mic1_s/duration_s*100:.1f}%)")
    print(f"  MIC2 ({args.mic2_clip}): {mic2_s/60:.1f} min ({mic2_s/duration_s*100:.1f}%)")

    dur_list = [e['end_s'] - e['start_s'] for e in events]
    print(f"\n  Shot-Längen:")
    print(f"    Min:  {min(dur_list):.1f}s")
    print(f"    Max:  {max(dur_list):.1f}s")
    print(f"    Mean: {np.mean(dur_list):.1f}s")

    # EDL schreiben
    write_edl(events, args.output, args.mic1_clip, args.mic2_clip, args.fps)

    print("\n" + "=" * 70)
    print("✅ FERTIG")
    print("=" * 70)
    print(f"  EDL: {args.output}")
    print(f"  Events: {len(events)}")
    print()


if __name__ == '__main__':
    main()
