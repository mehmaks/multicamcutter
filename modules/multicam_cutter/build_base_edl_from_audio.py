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


def combine_audios(paths: list):
    """
    Lädt mehrere WAV-Dateien und kombiniert sie zu einem aggregierten Signal.
    Gibt element-weises Maximum der absoluten Amplituden zurück (OR-Logik:
    die Kamera "spricht", wenn IRGENDEIN ihrer Mikrofone aktiv ist).
    """
    audios, sr = [], None
    for path in paths:
        a, s = load_audio(path)
        if sr is None:
            sr = s
        else:
            assert s == sr, f"Sample rates differ: {s} vs {sr}"
        audios.append(a)
    if len(audios) == 1:
        return audios[0], sr
    n = min(len(a) for a in audios)
    combined = np.max(np.stack([np.abs(a[:n]) for a in audios]), axis=0)
    return combined, sr


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
    # Wechsel wird erst akzeptiert wenn der neue Sprecher delay_wins
    # aufeinanderfolgende Fenster dominant ist. Der Schnitt wird dann
    # rückwirkend auf den Beginn des Streaks gesetzt.
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
            if streak < delay_wins:
                smoothed[i] = current
            else:
                # Streak bestätigt: rückwirkend alle Fenster des Streaks
                # auf den neuen Sprecher setzen
                for j in range(i - streak + 1, i + 1):
                    smoothed[j] = raw
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


def detect_on_speaker_pauses(audio1: np.ndarray, audio2: np.ndarray, sr: int,
                              segments: list, silence_db: float = -40.0,
                              min_pause_s: float = 0.3, padding_s: float = 0.15,
                              window_s: float = 0.02) -> dict:
    """
    Erkennt Sprechpausen innerhalb der On-Segmente jedes Sprechers.

    Für jedes Diarization-Segment wird das ON-Mic (nicht Off-Mic!) auf Stille
    geprüft. Erkannte Pausen werden als Masken-Intervalle zurückgegeben, damit
    die Speaking-Reaction-Baseline während Crossbleed-Abfällen eingefroren wird.

    Returns:
        {'CAM1': [(start_s, end_s), ...], 'CAM2': [(start_s, end_s), ...]}
    """
    min_wins = max(1, int(min_pause_s / window_s))
    pad_wins = int(padding_s / window_s)

    pauses = {'CAM1': [], 'CAM2': []}

    for seg in segments:
        spk = seg['speaker']
        if spk not in ('CAM1', 'CAM2'):
            continue

        on_audio = audio1 if spk == 'CAM1' else audio2
        s = int(seg['start_s'] * sr)
        e = int(seg['end_s'] * sr)
        chunk = on_audio[s:e]

        if len(chunk) < int(window_s * sr):
            continue

        db = compute_rms_db(chunk, sr, window_s)
        silent = db < silence_db

        # Zusammenhängende Stille-Regionen finden
        in_pause = False
        pause_start = 0
        for i in range(len(silent)):
            if silent[i] and not in_pause:
                pause_start = i
                in_pause = True
            elif not silent[i] and in_pause:
                if i - pause_start >= min_wins:
                    ps = max(0, pause_start - pad_wins)
                    pe = min(len(silent), i + pad_wins)
                    ps_s = seg['start_s'] + ps * window_s
                    pe_s = seg['start_s'] + pe * window_s
                    pauses[spk].append((ps_s, pe_s))
                in_pause = False
        if in_pause and len(silent) - pause_start >= min_wins:
            ps = max(0, pause_start - pad_wins)
            pe = min(len(silent), len(silent) + pad_wins)
            ps_s = seg['start_s'] + ps * window_s
            pe_s = seg['start_s'] + pe * window_s
            pauses[spk].append((ps_s, pe_s))

    for spk in pauses:
        pauses[spk].sort()

    total = sum(len(v) for v in pauses.values())
    if total:
        print(f"\n🎭 On-Speaker-Pausen: {len(pauses['CAM1'])} (CAM1), "
              f"{len(pauses['CAM2'])} (CAM2)")

    return pauses


# ─── Speaking Reaction Detection (Rolling-Baseline) ───────────────────────────

def _level_windows(audio: np.ndarray, sr: int, window_s: float,
                   mode: str = 'rms') -> np.ndarray:
    """Per-window level in dBFS. mode='rms' uses RMS, mode='peak' uses peak sample."""
    win = int(sr * window_s)
    n = len(audio) // win
    db = np.zeros(n)
    for i in range(n):
        chunk = audio[i * win:(i + 1) * win]
        if mode == 'peak':
            db[i] = 20 * np.log10(np.max(np.abs(chunk)) + 1e-9)
        else:
            db[i] = 20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-9)
    return db


def _bursts_rolling(
    audio: np.ndarray, sr: int, fps: float,
    window_s: float,
    attack_window_s: float, release_window_s: float,
    warmup_s: float, rise_db: float,
    min_duration_s: float, max_duration_s: float,
    hold_s: float,
    timeline_start_frame: int,
    mode: str = 'peak',
    decay_hold_s: float = 3.0,
    lookback_s: float = 1.0,
    sustain_margin_db: float = 1.5,
    no_burst_decay_factor: float = 3.0,
    return_debug: bool = False,
    freeze_mask: np.ndarray = None,
):
    """Rolling-Baseline Burst Detection mit Rise-Erkennung (Single-Pass).

    Erkennt Bursts anhand der Baseline-Anstiegsrate (nicht Pegel vs Baseline).
    Burst-Dauer wird durch Peak-Tracking bestimmt: Burst endet, wenn die
    Baseline unter (Peak - sustain_margin_db) fällt.

    Baseline-Decay ist schneller wenn kein Burst aktiv ist (no_burst_decay_factor),
    damit die Baseline nicht durch nicht-ausgelöste Rises hochdriftet.
    """
    db        = _level_windows(audio, sr, window_s, mode=mode)
    attack_n  = max(1, int(attack_window_s  / window_s))
    release_n = max(1, int(release_window_s / window_s))
    max_wins  = max(1, int(max_duration_s   / window_s))
    min_wins  = max(1, int(min_duration_s   / window_s))
    lookback_n = max(1, int(lookback_s      / window_s))
    decay_hold_n = max(0, int(decay_hold_s  / window_s))
    alpha_a   = 1.0 / attack_n
    alpha_r   = 1.0 / release_n

    warmup_n  = max(1, int(warmup_s / window_s))
    start_val = float(np.percentile(db[:warmup_n], 75))

    # ── Single-Pass: Baseline + Rise + Burst-Detection ──────────────────────
    baseline = np.empty(len(db))
    baseline[0] = start_val
    rise = np.zeros(len(db))

    bursts = []
    in_burst = False
    burst_start = 0
    peak = 0.0
    since_attack = 0

    for k in range(1, len(db)):
        # ── Baseline-Update ─────────────────────────────────────────────
        if freeze_mask is not None and freeze_mask[k]:
            # On-Speaker-Pause: Baseline einfrieren, damit Crossbleed-
            # Abfall keinen falschen Rise beim Wiedereinsetzen erzeugt.
            baseline[k] = baseline[k - 1]
        elif db[k] > baseline[k - 1]:
            baseline[k] = baseline[k - 1] + alpha_a * (db[k] - baseline[k - 1])
            since_attack = 0
        else:
            since_attack += 1
            if in_burst:
                # Während Burst: langsamer Decay mit S-Kurve
                if decay_hold_n > 0:
                    t = min(since_attack / decay_hold_n, 1.0)
                    s = t * t * (3.0 - 2.0 * t)
                    eff_alpha = alpha_r * (0.05 + 0.95 * s)
                else:
                    eff_alpha = alpha_r
            else:
                # Kein Burst: schnellerer Decay
                eff_alpha = alpha_r * no_burst_decay_factor
            baseline[k] = baseline[k - 1] + eff_alpha * (db[k] - baseline[k - 1])

        # ── Rise ────────────────────────────────────────────────────────
        lo = max(0, k - lookback_n)
        rise[k] = baseline[k] - baseline[lo]

        # ── Burst State Machine ─────────────────────────────────────────
        if in_burst:
            if baseline[k] > peak:
                peak = baseline[k]
            if baseline[k] < peak - sustain_margin_db:
                burst_len = k - burst_start
                if burst_len >= min_wins:
                    start_s  = burst_start * window_s
                    end_s    = k * window_s
                    avg_rise = float(np.mean(rise[burst_start:k]))
                    conf     = min(1.0, avg_rise / rise_db)
                    tl_frame = timeline_start_frame + round(start_s * fps)
                    bursts.append({
                        'start_s':  start_s,
                        'end_s':    end_s,
                        'dur_s':    end_s - start_s,
                        'tl_frame': tl_frame,
                        'conf':     round(conf, 3),
                    })
                in_burst = False
            elif max_wins > 0 and (k - burst_start) >= max_wins:
                burst_len = k - burst_start
                if burst_len >= min_wins:
                    start_s  = burst_start * window_s
                    end_s    = k * window_s
                    avg_rise = float(np.mean(rise[burst_start:k]))
                    conf     = min(1.0, avg_rise / rise_db)
                    tl_frame = timeline_start_frame + round(start_s * fps)
                    bursts.append({
                        'start_s':  start_s,
                        'end_s':    end_s,
                        'dur_s':    end_s - start_s,
                        'tl_frame': tl_frame,
                        'conf':     round(conf, 3),
                    })
                in_burst = False
        elif rise[k] >= rise_db:
            in_burst = True
            burst_start = k
            peak = baseline[k]

    # Letzten offenen Burst schließen
    if in_burst:
        k = len(db)
        burst_len = k - burst_start
        if burst_len >= min_wins:
            start_s  = burst_start * window_s
            end_s    = k * window_s
            avg_rise = float(np.mean(rise[burst_start:k]))
            conf     = min(1.0, avg_rise / rise_db)
            tl_frame = timeline_start_frame + round(start_s * fps)
            bursts.append({
                'start_s':  start_s,
                'end_s':    end_s,
                'dur_s':    end_s - start_s,
                'tl_frame': tl_frame,
                'conf':     round(conf, 3),
            })

    if return_debug:
        return bursts, db, baseline, rise
    return bursts


def detect_speaking_reactions(
    audio1: np.ndarray, audio2: np.ndarray, sr: int,
    segments: list,
    fps: float, wav_edl_frame: int,
    cam1_timeline_zero_video: int, cam2_timeline_zero_video: int,
    window_s: float        = 0.05,
    rise_db: float         = 6.0,
    min_duration_s: float  = 0.20,
    max_duration_s: float  = 2.5,
    attack_window_s: float = 0.2,
    release_window_s: float = 20.0,
    warmup_s: float        = 3.0,
    hold_s: float          = 0.0,
    mode: str              = 'peak',
    decay_hold_s: float    = 3.0,
    lookback_s: float      = 1.0,
    sustain_margin_db: float = 1.5,
    on_pauses: dict = None,
) -> tuple:
    """
    Rolling-Baseline Burst Detection auf dem Off-Kamera-Mikrofon.

    Läuft per Diarization-Segment mit Baseline-Reset am Anfang jeder
    Off-Section, damit die Baseline nicht über die gesamte Aufnahme
    wegdriftet.

    on_pauses: Dict {'CAM1': [(s, e), ...], 'CAM2': [(s, e), ...]}
               On-Speaker-Pausen zur Baseline-Maskierung.

    Returns (cam1_reactions, cam2_reactions).
    """
    def _to_reaction(burst, cam_tz):
        edl_frame   = burst['tl_frame']
        video_frame = cam_tz + edl_frame
        if video_frame < 0:
            return None
        f  = edl_frame
        tc = (f"{int(f/fps/3600):02d}:{int(f/fps%3600/60):02d}:"
              f"{int(f/fps%60):02d}:{int(f%fps):02d}")
        return {
            'frame':      int(video_frame),
            'timecode':   tc,
            'type':       'speaking_reaction',
            'confidence': burst['conf'],
            'dur_s':      burst.get('dur_s', 0),
        }

    # Per-Segment Burst-Detection mit frischer Baseline pro Segment.
    # CAM1 spricht → MIC2-Bursts = CAM2-Reaktionen
    # CAM2 spricht → MIC1-Bursts = CAM1-Reaktionen
    cam1_reactions, cam2_reactions = [], []

    for seg in segments:
        seg_start_sample = int(seg['start_s'] * sr)
        seg_end_sample   = int(seg['end_s'] * sr)
        seg_start_edl    = wav_edl_frame + round(seg['start_s'] * fps)

        if seg['speaker'] == 'CAM1':
            seg_audio = audio2[seg_start_sample:seg_end_sample]
            cam_tz = cam2_timeline_zero_video
            target = cam2_reactions
        elif seg['speaker'] == 'CAM2':
            seg_audio = audio1[seg_start_sample:seg_end_sample]
            cam_tz = cam1_timeline_zero_video
            target = cam1_reactions
        else:
            continue

        if len(seg_audio) < int(warmup_s * sr):
            continue

        # Freeze-Mask: On-Speaker-Pausen in Fenster-Koordinaten umrechnen
        seg_freeze = None
        if on_pauses:
            spk = seg['speaker']
            spk_pauses = on_pauses.get(spk, [])
            if spk_pauses:
                win = int(sr * window_s)
                n_wins = len(seg_audio) // win
                seg_freeze = np.zeros(n_wins, dtype=bool)
                seg_s = seg['start_s']
                for ps, pe in spk_pauses:
                    # Pause in lokale Segment-Fenster umrechnen
                    local_start = int((ps - seg_s) / window_s)
                    local_end   = int((pe - seg_s) / window_s)
                    if local_end <= 0 or local_start >= n_wins:
                        continue
                    local_start = max(0, local_start)
                    local_end   = min(n_wins, local_end)
                    seg_freeze[local_start:local_end] = True

        bursts = _bursts_rolling(
            seg_audio, sr, fps, window_s,
            attack_window_s, release_window_s, warmup_s,
            rise_db, min_duration_s, max_duration_s, hold_s,
            timeline_start_frame=seg_start_edl,
            mode=mode,
            decay_hold_s=decay_hold_s,
            lookback_s=lookback_s,
            sustain_margin_db=sustain_margin_db,
            freeze_mask=seg_freeze,
        )

        for b in bursts:
            r = _to_reaction(b, cam_tz)
            if r:
                target.append(r)

    return cam1_reactions, cam2_reactions


# ─── Totale-Cam Simultansprechen-Erkennung ────────────────────────────────────

def detect_simultaneous_speech(audio1: np.ndarray, audio2: np.ndarray, sr: int,
                                window_s: float, threshold_db: float,
                                min_duration_s: float) -> list:
    """
    Erkennt Zeiträume wo beide Mics gleichzeitig aktiv sind (kein klarer Dominanzunterschied).
    Returns: Liste von (start_s, end_s) Tupeln.
    """
    NOISE_FLOOR_DB = -50.0  # unter diesem Pegel gilt ein Mic als "still"

    rms1 = compute_rms_db(audio1, sr, window_s)
    rms2 = compute_rms_db(audio2, sr, window_s)
    n = min(len(rms1), len(rms2))
    rms1, rms2 = rms1[:n], rms2[:n]

    diff         = np.abs(rms1 - rms2)
    both_active  = (rms1 > NOISE_FLOOR_DB) & (rms2 > NOISE_FLOOR_DB)
    simultaneous = both_active & (diff < threshold_db)

    min_wins = max(1, int(min_duration_s / window_s))
    segments, in_seg, start_i = [], False, 0
    for i in range(n):
        if simultaneous[i] and not in_seg:
            in_seg, start_i = True, i
        elif not simultaneous[i] and in_seg:
            in_seg = False
            if (i - start_i) >= min_wins:
                segments.append((start_i * window_s, i * window_s))
    if in_seg and (n - start_i) >= min_wins:
        segments.append((start_i * window_s, n * window_s))

    return segments


def _slice_event(event: dict, start_frame: int, end_frame: int, fps: float) -> dict:
    """Schneidet einen Teilbereich aus einem bestehenden EDL-Event heraus."""
    orig_rec_start = timecode_to_frames(event['record_in'],  fps)
    orig_src_start = timecode_to_frames(event['source_in'],  fps)
    offset = start_frame - orig_rec_start
    dur    = end_frame   - start_frame
    return {
        'clip_name':  event['clip_name'],
        'source_in':  frames_to_timecode(orig_src_start + offset,         fps),
        'source_out': frames_to_timecode(orig_src_start + offset + dur,   fps),
        'record_in':  frames_to_timecode(start_frame,   fps),
        'record_out': frames_to_timecode(end_frame,     fps),
    }


def insert_totale_events(events: list, simul_segments: list, fps: float,
                          totale_clip: str, totale_ref: int,
                          totale_timeline_zero_video: int,
                          wav_edl_frame: int) -> list:
    """
    Teilt bestehende EDL-Events an Simultansprechen-Phasen auf und
    fügt an deren Stelle einen Totale-Clip ein.
    """
    if not simul_segments or not totale_clip or totale_ref is None:
        return events

    # Simultansprechen-Segmente in EDL-Frames umrechnen
    simul_edl = []
    for start_s, end_s in simul_segments:
        s = max(0, round(start_s * fps) + wav_edl_frame)
        e = round(end_s * fps) + wav_edl_frame
        if e > s:
            simul_edl.append((s, e))

    result = []
    for event in events:
        ev_start = timecode_to_frames(event['record_in'],  fps)
        ev_end   = timecode_to_frames(event['record_out'], fps)

        # Überlappende Simultansegmente finden und auf diesen Event clippen
        overlaps = [
            (max(s, ev_start), min(e, ev_end))
            for s, e in simul_edl
            if e > ev_start and s < ev_end
        ]

        if not overlaps:
            result.append(event)
            continue

        cursor = ev_start
        for simul_start, simul_end in sorted(overlaps):
            if cursor < simul_start:
                result.append(_slice_event(event, cursor, simul_start, fps))

            tot_video_start = totale_timeline_zero_video + simul_start
            tot_video_end   = totale_timeline_zero_video + simul_end
            if tot_video_start >= 0:
                result.append({
                    'clip_name':  totale_clip,
                    'source_in':  frames_to_timecode(totale_ref + tot_video_start, fps),
                    'source_out': frames_to_timecode(totale_ref + tot_video_end,   fps),
                    'record_in':  frames_to_timecode(simul_start, fps),
                    'record_out': frames_to_timecode(simul_end,   fps),
                })
            cursor = simul_end

        if cursor < ev_end:
            result.append(_slice_event(event, cursor, ev_end, fps))

    return result


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

    # Audio (nargs='+' erlaubt mehrere MICs pro Kamera)
    parser.add_argument('--mic-cam1', required=True, nargs='+',
                        help='Mikrofon-Spur(en) für CAM1 (WAV). Mehrere Pfade = aggregiert.')
    parser.add_argument('--mic-cam2', required=True, nargs='+',
                        help='Mikrofon-Spur(en) für CAM2 (WAV). Mehrere Pfade = aggregiert.')

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
    # Speaking reaction output (optional)
    parser.add_argument('--speaking-reactions-cam1-out', default=None,
                        help='JSON output path for CAM1 speaking reactions')
    parser.add_argument('--speaking-reactions-cam2-out', default=None,
                        help='JSON output path for CAM2 speaking reactions')
    parser.add_argument('--speaking-rise-db',       type=float, default=6.0)
    parser.add_argument('--speaking-min-duration',  type=float, default=0.20)
    parser.add_argument('--speaking-max-duration',  type=float, default=2.5)
    parser.add_argument('--speaking-attack-window', type=float, default=0.2)
    parser.add_argument('--speaking-release-window',type=float, default=20.0)
    parser.add_argument('--speaking-warmup',        type=float, default=3.0)
    parser.add_argument('--speaking-hold',          type=float, default=0.0)
    parser.add_argument('--speaking-mode',          choices=['rms', 'peak'], default='peak')
    parser.add_argument('--speaking-mask-min-pause', type=float, default=0.3,
                        help='Min. Pausenlänge des On-Sprechers für Baseline-Freeze (s)')
    parser.add_argument('--speaking-mask-padding',   type=float, default=0.15,
                        help='Padding um On-Speaker-Pausen für Baseline-Freeze (s)')
    # Off-sections output (für Nodding-Analyse Optimierung)
    parser.add_argument('--cam1-off-sections-out', default=None,
                        help='JSON-Ausgabe: Video-Frame-Ranges in denen CAM1 die Off-Kamera ist')
    parser.add_argument('--cam2-off-sections-out', default=None,
                        help='JSON-Ausgabe: Video-Frame-Ranges in denen CAM2 die Off-Kamera ist')
    # Totale-Cam Simultansprechen-Logik
    parser.add_argument('--totale-video',          default=None,
                        help='Totale-Cam Video-Datei (für embedded TC via ffprobe)')
    parser.add_argument('--totale-clip',           default=None,
                        help='Totale-Cam Clip-Name in der EDL')
    parser.add_argument('--totale-edl-frame',      type=int, default=0,
                        help='EDL-Frame bei dem die Totale-Cam Frame 0 liegt (Standard: 0 = wie CAM1)')
    parser.add_argument('--totale-simul-min-duration', type=float, default=3.0,
                        help='Mindestdauer Simultansprechen bevor auf Totale geschnitten wird (s)')
    # Pause-Trimming
    parser.add_argument('--pause-trim',           action='store_true',
                        help='Überlange Sprechpausen an Diarization-Grenzen trimmen')
    parser.add_argument('--max-pause',            type=float, default=1.0,
                        help='Max. erlaubte Pausendauer in Sekunden (default: 1.0)')
    parser.add_argument('--pause-silence-db',     type=float, default=-40.0,
                        help='dB-Schwelle unter der Stille erkannt wird (default: -40)')
    parser.add_argument('--pause-search-radius',  type=float, default=3.0,
                        help='Suchradius um jede Grenze in Sekunden (default: 3.0)')
    parser.add_argument('--pause-min-duration',   type=float, default=0.3,
                        help='Mindest-Pausendauer für Erkennung (default: 0.3)')
    parser.add_argument('--pause-cut-mode',       choices=['l-cut', 'middle', 'j-cut'],
                        default='middle',
                        help='Video-Schnittmodus in der Pause (default: middle)')
    parser.add_argument('--audio-trims-out',      default=None,
                        help='JSON-Ausgabe: Audio-Keep-Regionen für MIC-Platzierung')
    # Pause-Cutaway (Stille-Cutaway)
    parser.add_argument('--pause-cutaway-json-out', default=None,
                        help='JSON-Ausgabe: On-Speaker-Pausen als Cutaway-Kandidaten')
    parser.add_argument('--pause-cutaway-min-pause', type=float, default=2.0,
                        help='Min. Pausenlänge für Stille-Cutaway (s, default: 2.0)')
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

    # Früheste Kamera bestimmt den Timeline-Ursprung.
    # Wenn eine Kamera einen negativen edl_frame hat (sie startete vor der Referenz-Kamera),
    # werden alle Offsets verschoben, sodass die früheste Kamera bei EDL-Frame 0 beginnt.
    _cam_shift = max(0, -min(args.cam1_edl_frame, args.cam2_edl_frame))
    if _cam_shift > 0:
        args.cam1_edl_frame += _cam_shift
        args.cam2_edl_frame += _cam_shift
        args.wav_edl_frame  += _cam_shift
        print(f"\n  ℹ️  Früheste Kamera als Timeline-Ursprung: Offsets um +{_cam_shift} Frames "
              f"(+{_cam_shift / args.fps:.2f}s) verschoben.")

    # TC-Umrechnung identisch zu add_reactions_to_edl.py:
    #   timeline_zero_video = 0 - cam_edl_frame
    #   video_frame         = timeline_zero_video + edl_frame
    #   source_tc_frame     = reference_frame + video_frame
    cam1_timeline_zero_video = 0 - args.cam1_edl_frame
    cam2_timeline_zero_video = 0 - args.cam2_edl_frame

    print(f"  CAM1 ({args.cam1_clip}): embedded TC {cam1_tc} = {cam1_ref} frames")
    print(f"        EDL Frame 0 liegt bei Video Frame {cam1_timeline_zero_video}")
    print(f"  CAM2 ({args.cam2_clip}): embedded TC {cam2_tc} = {cam2_ref} frames")
    print(f"        EDL Frame 0 liegt bei Video Frame {cam2_timeline_zero_video}")

    if args.wav_edl_frame < 0:
        pre_s = abs(args.wav_edl_frame) / args.fps
        print(f"\n  ⚠️  WAV startete {pre_s:.1f}s VOR den Kameras (wav_edl_frame={args.wav_edl_frame}).")
        print(f"      Die ersten {pre_s:.1f}s des Podcasts haben keine Kamera-Coverage")
        print(f"      und fehlen daher in der Cut-Timeline.")

    # ── 2. Audio laden & diarisieren ──────────────────────────────────────────
    print("\n📂 Lade Audio...")
    print(f"  CAM1 ({len(args.mic_cam1)} MIC(s)): {[Path(p).name for p in args.mic_cam1]}")
    audio_cam1, sr1 = combine_audios(args.mic_cam1)
    print(f"  CAM2 ({len(args.mic_cam2)} MIC(s)): {[Path(p).name for p in args.mic_cam2]}")
    audio_cam2, sr2 = combine_audios(args.mic_cam2)
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

        # Symmetrischer Fallback: CAM2 noch nicht gestartet → CAM1
        if speaker == 'CAM2' and edl_start < args.cam2_edl_frame:
            if edl_end <= args.cam2_edl_frame:
                speaker = 'CAM1'  # ganzes Segment vor CAM2-Start → CAM1
            else:
                # Segment überlappt CAM2-Start: aufteilen
                # Teil vor CAM2-Start → CAM1
                edl_end_pre = args.cam2_edl_frame
                cam1_video_start = cam1_timeline_zero_video + edl_start
                cam1_video_end   = cam1_timeline_zero_video + edl_end_pre
                if cam1_video_start >= 0 and edl_end_pre > edl_start:
                    events.append({
                        'clip_name':  args.cam1_clip,
                        'source_in':  frames_to_timecode(cam1_ref + cam1_video_start, args.fps),
                        'source_out': frames_to_timecode(cam1_ref + cam1_video_end,   args.fps),
                        'record_in':  frames_to_timecode(edl_start,    args.fps),
                        'record_out': frames_to_timecode(edl_end_pre,  args.fps),
                    })
                # Rest des Segments → CAM2 (ab cam2_edl_frame)
                edl_start = args.cam2_edl_frame
                speaker = 'CAM2'

        # Skip segments entirely before the record timeline start
        if edl_end <= 0:
            skipped += 1
            continue
        # Trim segments that overlap the record timeline start
        if edl_start < 0:
            edl_start = 0

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

    if events:
        first = events[0]
        first_record_s  = timecode_to_frames(first['record_in'],  args.fps) / args.fps
        first_source_s  = (timecode_to_frames(first['source_in'], args.fps) -
                           (cam1_ref if first['clip_name'] == args.cam1_clip else cam2_ref)) / args.fps
        pre_podcast_s   = -args.wav_edl_frame / args.fps
        print(f"\n  ℹ️  Erster Cut-Event:")
        print(f"       Record-Startpunkt:  {first['record_in']}  ({first_record_s:.1f}s in der Audio-Spur)")
        print(f"       Source (Video):      {first['source_in']}  ({first_source_s:.1f}s in {first['clip_name']})")
        if args.wav_edl_frame < 0:
            print(f"       → WAV startete {pre_podcast_s:.1f}s vor den Kameras."
                  f" Diese {pre_podcast_s:.1f}s Podcast fehlen im Cut.")

    # ── 4. Totale-Cam Simultansprechen-Logik ─────────────────────────────────
    if args.totale_clip and args.totale_video:
        print(f"\n🎬 Totale-Cam Simultansprechen-Erkennung (min. {args.totale_simul_min_duration}s)...")
        totale_ref, totale_tc = get_reference_frame(args.totale_video, args.fps)
        if totale_ref is not None:
            totale_edl_frame         = args.totale_edl_frame + _cam_shift
            totale_timeline_zero_vid = 0 - totale_edl_frame
            simul_segs = detect_simultaneous_speech(
                audio_cam1, audio_cam2, sr1,
                args.analysis_window, args.threshold_db,
                args.totale_simul_min_duration,
            )
            print(f"  {len(simul_segs)} Simultansprechen-Segment(e) erkannt")
            for s, e in simul_segs:
                print(f"    {s:.1f}s – {e:.1f}s  ({e - s:.1f}s)")
            if simul_segs:
                events = insert_totale_events(
                    events, simul_segs, args.fps,
                    args.totale_clip, totale_ref,
                    totale_timeline_zero_vid,
                    args.wav_edl_frame,
                )
                print(f"  ✓ Totale-Events eingefügt — EDL hat jetzt {len(events)} Events")
        else:
            print(f"  ⚠️  Konnte embedded TC der Totale nicht lesen — Logik übersprungen.")

    # ── 5. Statistik ──────────────────────────────────────────────────────────
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

    # ── 6. Off-Sektionen schreiben (für Nodding-Analyse) ─────────────────────
    if args.cam1_off_sections_out or args.cam2_off_sections_out:
        cam1_off, cam2_off = [], []
        for seg in segments:
            edl_s = round(seg['start_s'] * args.fps) + args.wav_edl_frame
            edl_e = round(seg['end_s']   * args.fps) + args.wav_edl_frame
            if seg['speaker'] == 'CAM2':
                # CAM2 spricht → CAM1 ist Off-Kamera
                v_s = cam1_timeline_zero_video + edl_s
                v_e = cam1_timeline_zero_video + edl_e
                if v_s >= 0 and v_e > v_s:
                    cam1_off.append([int(v_s), int(v_e)])
            elif seg['speaker'] == 'CAM1':
                # CAM1 spricht → CAM2 ist Off-Kamera
                v_s = cam2_timeline_zero_video + edl_s
                v_e = cam2_timeline_zero_video + edl_e
                if v_s >= 0 and v_e > v_s:
                    cam2_off.append([int(v_s), int(v_e)])
        if args.cam1_off_sections_out:
            Path(args.cam1_off_sections_out).write_text(json.dumps(cam1_off))
            total_off_s = sum(e - s for s, e in cam1_off) / args.fps
            print(f"  CAM1 Off-Sektionen: {len(cam1_off)} Segmente ({total_off_s/60:.1f} min)")
        if args.cam2_off_sections_out:
            Path(args.cam2_off_sections_out).write_text(json.dumps(cam2_off))
            total_off_s = sum(e - s for s, e in cam2_off) / args.fps
            print(f"  CAM2 Off-Sektionen: {len(cam2_off)} Segmente ({total_off_s/60:.1f} min)")

    # ── 6b. Pause-Detection (optional) ──────────────────────────────────────
    # Nur erkennen und als JSON speichern — Anwendung erfolgt später in
    # run_from_bin.py auf die finalen cut_events (nach Cutaway-Einfügung),
    # damit tzvf in add_reactions_to_edl.py korrekt bleibt.
    if args.pause_trim:
        from pause_trim_edl import detect_pauses, save_pauses
        pauses = detect_pauses(
            events, audio_cam1, audio_cam2, sr1,
            args.wav_edl_frame, args.fps,
            silence_db=args.pause_silence_db,
            search_radius_s=args.pause_search_radius,
            min_pause_s=args.pause_min_duration,
        )
        if pauses and args.audio_trims_out:
            save_pauses(pauses, args.audio_trims_out)
        elif not pauses:
            print("  Keine trimmbare Pausen gefunden")

    # ── 7. EDL schreiben ──────────────────────────────────────────────────────
    write_edl(events, args.output)

    # ── 8. Speaking Reactions (optional) ─────────────────────────────────────
    if args.speaking_reactions_cam1_out or args.speaking_reactions_cam2_out:
        print(f"\n🗣️  Erkenne Speaking Reactions (mode={args.speaking_mode})...")

        # On-Speaker-Pausen erkennen für Baseline-Freeze
        _on_pauses = detect_on_speaker_pauses(
            audio_cam1, audio_cam2, sr1, segments,
            silence_db=args.pause_silence_db,
            min_pause_s=args.speaking_mask_min_pause,
            padding_s=args.speaking_mask_padding,
        )

        cam1_sr, cam2_sr = detect_speaking_reactions(
            audio_cam1, audio_cam2, sr1,
            segments,
            args.fps, args.wav_edl_frame,
            cam1_timeline_zero_video, cam2_timeline_zero_video,
            window_s=args.analysis_window,
            rise_db=args.speaking_rise_db,
            min_duration_s=args.speaking_min_duration,
            max_duration_s=args.speaking_max_duration,
            attack_window_s=args.speaking_attack_window,
            release_window_s=args.speaking_release_window,
            warmup_s=args.speaking_warmup,
            hold_s=args.speaking_hold,
            mode=args.speaking_mode,
            on_pauses=_on_pauses,
        )
        print(f"  CAM1 Reactions: {len(cam1_sr)}, CAM2 Reactions: {len(cam2_sr)}")
        if args.speaking_reactions_cam1_out:
            Path(args.speaking_reactions_cam1_out).write_text(
                json.dumps({'fps': args.fps, 'reactions': cam1_sr}, indent=2)
            )
        if args.speaking_reactions_cam2_out:
            Path(args.speaking_reactions_cam2_out).write_text(
                json.dumps({'fps': args.fps, 'reactions': cam2_sr}, indent=2)
            )

    # ── 9. Pause-Cutaway-Kandidaten exportieren (optional) ─────────────────
    if args.pause_cutaway_json_out:
        print(f"\n🔇 Erkenne Stille-Pausen für Cutaways (min {args.pause_cutaway_min_pause}s)...")
        _cutaway_pauses = detect_on_speaker_pauses(
            audio_cam1, audio_cam2, sr1, segments,
            silence_db=args.pause_silence_db,
            min_pause_s=args.pause_cutaway_min_pause,
            padding_s=0.0,
        )
        # Audio-Sekunden → Timeline-Frames
        pause_list = []
        for spk in ('CAM1', 'CAM2'):
            for ps, pe in _cutaway_pauses.get(spk, []):
                sf = round(ps * args.fps) + args.wav_edl_frame
                ef = round(pe * args.fps) + args.wav_edl_frame
                if ef > sf:
                    pause_list.append({
                        'start_frame': sf,
                        'end_frame': ef,
                        'speaker': spk,
                    })
        pause_list.sort(key=lambda p: p['start_frame'])
        Path(args.pause_cutaway_json_out).write_text(
            json.dumps({'fps': args.fps, 'pauses': pause_list}, indent=2)
        )
        print(f"  {len(pause_list)} Pause-Cutaway-Kandidaten exportiert")

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
