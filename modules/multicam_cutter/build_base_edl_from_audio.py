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
import numpy as np
from pathlib import Path

from frame_utils import timecode_to_frames, frames_to_timecode, get_reference_frame


# ─── Audio-Analyse ─────────────────────────────────────────────────────────────

def load_audio(path: str):
    """
    Mono-Audio als float32 laden — Dekodierung ueber ffmpeg, damit JEDE
    Bit-Tiefe korrekt gelesen wird (16/24/32-bit PCM, float).

    Der fruehere wave+int16-Weg hat 24-bit-WAVs fehlinterpretiert: 3 Bytes je
    Sample als 2 gelesen → 1,5-fache Laenge und Rauschen statt Ton. Folge war
    eine komplett degenerierte Diarisierung (Realfall 23.07.: pegelidentische
    Seiten, 1 Segment, alles Simultan — siehe CLAUDE.md → Fixed Bugs). Der
    Waveform-Sync dekodiert seit jeher ueber ffmpeg und war deshalb korrekt.
    """
    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    try:
        sr = int(float(probe.stdout.strip()))
    except ValueError:
        raise RuntimeError(f"ffprobe: keine Sample-Rate fuer {path}: "
                           f"{probe.stderr.strip()[:200]}")
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-f", "f32le", "-"],
        capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg fehlgeschlagen fuer {path}:\n"
                           + result.stderr.decode(errors="replace")[-300:])
    audio = np.frombuffer(result.stdout, dtype=np.float32)
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


def rms_diarize_n(audios: list, sr: int, window_s: float, threshold_db: float,
                  change_delay_s: float, min_edit_s: float,
                  labels: list, silence_gates_db: list):
    """
    N-fache RMS-Diarisierung → Segmente mit Kamera-Label als Speaker.

    Pro Fenster gewinnt die LAUTESTE Kamera-Gruppe, aber nur wenn ihr Vorsprung
    zum Zweitplatzierten groesser als threshold_db ist — sonst None (keine klare
    Dominanz). Liegt JEDE Gruppe unter IHREM Silence-Gate, spricht niemand → None.

    audios[k]           = (kombiniertes) Mikrofonsignal fuer Kamera labels[k]
    silence_gates_db[k] = Stille-Schwelle fuer diese Gruppe

    Bei genau 2 Gruppen ist das Ergebnis identisch zur frueheren binaeren
    Differenz-Logik (siehe rms_diarize-Shim + test_diarize.py). Das ist die
    Regressions-Invariante, die den Umbau auf N traegt: fuer K=2 ist
    „Vorsprung Platz1→Platz2 > threshold" exakt |rms1-rms2| > threshold, und
    „jede Gruppe unter Gate" exakt das alte both_quiet.
    """
    assert len(audios) == len(labels) == len(silence_gates_db) >= 1, \
        "audios, labels und silence_gates_db muessen gleich lang und nicht leer sein"

    rms = [compute_rms_db(a, sr, window_s) for a in audios]
    n = min(len(r) for r in rms)
    mat = np.stack([r[:n] for r in rms], axis=1)          # (n, K)
    gates = np.asarray(silence_gates_db, dtype=float)     # (K,)
    label_arr = np.array(labels, dtype=object)
    rows = np.arange(n)

    if mat.shape[1] == 1:
        leader = np.zeros(n, dtype=int)
        margin = np.full(n, np.inf)
    else:
        order  = np.argsort(mat, axis=1)                  # aufsteigend
        leader = order[:, -1]                             # lauteste Gruppe
        second = order[:, -2]                             # zweitlauteste
        margin = mat[rows, leader] - mat[rows, second]    # Vorsprung Platz 1 → 2

    dominant = np.full(n, None, dtype=object)
    clear = margin > threshold_db                         # klare Dominanz?
    dominant[clear] = label_arr[leader][clear]

    # Stille-Gate: nur wenn JEDE Gruppe unter IHRER Schwelle liegt → niemand.
    all_quiet = np.all(mat < gates, axis=1)
    dominant[all_quiet] = None

    default_label = labels[0]

    # ── Ab hier WOERTLICH die fruehere binaere Logik (label-agnostisch) ──
    # Change-Delay smoothing: ein Wechsel wird erst akzeptiert, wenn der neue
    # Sprecher delay_wins Fenster in Folge dominant ist; der Schnitt wird dann
    # rueckwirkend auf den Streak-Beginn gesetzt.
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
                             (segments[i+1]['speaker'] if i < len(segments)-1 else default_label)

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


def rms_diarize(audio1: np.ndarray, audio2: np.ndarray, sr: int,
                window_s: float, threshold_db: float,
                change_delay_s: float, min_edit_s: float,
                silence_gate_db: float = -55.0,
                silence_gate_db2: float = None):
    """
    Binaerer N=2-Shim auf rms_diarize_n — byte-identisch zur frueheren Logik.
    Erhalten fuer run_from_resolve, den sequencer-Pfad und als Regressionsanker.
    audio1 = Mikrofon fuer CAM1, audio2 = Mikrofon fuer CAM2.
    """
    if silence_gate_db2 is None:
        silence_gate_db2 = silence_gate_db
    return rms_diarize_n([audio1, audio2], sr, window_s, threshold_db,
                         change_delay_s, min_edit_s,
                         labels=['CAM1', 'CAM2'],
                         silence_gates_db=[silence_gate_db, silence_gate_db2])


def build_base_edl_n(cameras: list, person_audios: dict, sr: int, fps: float,
                     wav_edl_frame: int, window_s: float, threshold_db: float,
                     change_delay_s: float, min_edit_s: float,
                     silence_gates_db: dict):
    """
    N-fache Basis-EDL: diarisiert ueber PERSONEN (ein Mikro je Person) und
    schneidet jedes Sprech-Segment auf die ENGSTE Kamera, die diese Person zeigt.

    Das ist der additive Weg fuer >2 Personen — der binaere 2-Personen-Pfad
    (main() + rms_diarize-Shim) bleibt davon UNBERUEHRT und damit byte-identisch.

    cameras: Liste von Dicts mit
        'clip'      – Clip-Name in der EDL
        'mics'      – Personen-IDs (Mic-Pfade), die diese Kamera zeigt
        'edl_frame' – EDL-Frame, bei dem Frame 0 dieser Kamera liegt
        'ref'       – embedded-TC-Frame (get_reference_frame(video)[0])
        'name'      – (fuer shot_sizes; darf = clip sein)
    person_audios:    {Personen-ID: np.ndarray}, alle mit Sample-Rate sr
    silence_gates_db: {Personen-ID: float} Stille-Schwelle je Person
    wav_edl_frame:    EDL-Frame, bei dem Audio-Frame 0 liegt

    Rueckgabe: EDL-Events (gleiche Struktur wie der binaere Pfad).
    """
    from shot_sizes import ladder_for_person

    # Stabile Personen-Reihenfolge aus den Kamera-Zuordnungen (kein dict-Zufall).
    persons = []
    for cam in cameras:
        for pid in (cam.get('mics') or []):
            if pid not in persons:
                persons.append(pid)
    if not persons:
        return []

    audios = [person_audios[p] for p in persons]
    gates  = [silence_gates_db[p] for p in persons]

    # Frueheste Kamera = Timeline-Ursprung (wie im binaeren Pfad). Verschiebt nur
    # die Record-Positionen; die Source-Frames sind davon unabhaengig.
    cam_shift = max(0, -min(c['edl_frame'] for c in cameras))

    segments = rms_diarize_n(audios, sr, window_s, threshold_db,
                             change_delay_s, min_edit_s,
                             labels=persons, silence_gates_db=gates)

    events, skipped = [], 0
    for seg in segments:
        person    = seg['speaker']
        edl_start = round(seg['start_s'] * fps) + wav_edl_frame + cam_shift
        edl_end   = round(seg['end_s']   * fps) + wav_edl_frame + cam_shift

        # Engste Kamera, die diese Person zeigt UND bei edl_start schon laeuft.
        # ladder_for_person liefert die Kameras engste-zuerst; die erste, deren
        # (verschobener) Start <= edl_start ist, gewinnt. Laeuft die engste noch
        # nicht, greift automatisch die naechstgroessere (bis zur Totale).
        ladder = ladder_for_person(cameras, person)
        cam = next((c for c in ladder
                    if (c['edl_frame'] + cam_shift) <= edl_start), None)
        if cam is None:
            skipped += 1
            continue

        e_frame     = cam['edl_frame'] + cam_shift
        video_start = edl_start - e_frame
        video_end   = edl_end   - e_frame
        events.append({
            'clip_name':  cam['clip'],
            'source_in':  frames_to_timecode(cam['ref'] + video_start, fps),
            'source_out': frames_to_timecode(cam['ref'] + video_end,   fps),
            'record_in':  frames_to_timecode(edl_start, fps),
            'record_out': frames_to_timecode(edl_end,   fps),
        })

    if skipped:
        print(f"  {skipped} Segmente uebersprungen (keine Kamera dieser Person "
              f"war zum Zeitpunkt schon gestartet)")
    return events


def detect_on_speaker_pauses(audio1: np.ndarray, audio2: np.ndarray, sr: int,
                              segments: list, silence_db: float = -40.0,
                              silence_db2: float = None,
                              min_pause_s: float = 0.3, padding_s: float = 0.15,
                              window_s: float = 0.02) -> dict:
    """
    Erkennt Sprechpausen innerhalb der On-Segmente jedes Sprechers.

    Für jedes Diarization-Segment wird das ON-Mic (nicht Off-Mic!) auf Stille
    geprüft. Erkannte Pausen werden als Masken-Intervalle zurückgegeben, damit
    die Speaking-Reaction-Baseline während Crossbleed-Abfällen eingefroren wird.

    Args:
        silence_db: Schwelle für audio1 (CAM1-Mic)
        silence_db2: Schwelle für audio2 (CAM2-Mic), wenn None = silence_db

    Returns:
        {'CAM1': [(start_s, end_s), ...], 'CAM2': [(start_s, end_s), ...]}
    """
    if silence_db2 is None:
        silence_db2 = silence_db
    min_wins = max(1, int(min_pause_s / window_s))
    pad_wins = int(padding_s / window_s)

    pauses = {'CAM1': [], 'CAM2': []}

    for seg in segments:
        spk = seg['speaker']
        if spk not in ('CAM1', 'CAM2'):
            continue

        on_audio = audio1 if spk == 'CAM1' else audio2
        _thresh = silence_db if spk == 'CAM1' else silence_db2
        s = int(seg['start_s'] * sr)
        e = int(seg['end_s'] * sr)
        chunk = on_audio[s:e]

        if len(chunk) < int(window_s * sr):
            continue

        db = compute_rms_db(chunk, sr, window_s)
        silent = db < _thresh

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
    rejected_sink: list = None,
    post_freeze_refractory_s: float = 0.0,
    freeze_hold_max_s: float = 0.0,
    freeze_release_margin_db: float = 3.0,
    level_floor_pct: float = None,
):
    """Rolling-Baseline Burst Detection mit Rise-Erkennung (Single-Pass).

    Erkennt Bursts anhand der Baseline-Anstiegsrate (nicht Pegel vs Baseline).
    Burst-Dauer wird durch Peak-Tracking bestimmt: Burst endet, wenn die
    Baseline unter (Peak - sustain_margin_db) fällt.

    Baseline-Decay ist schneller wenn kein Burst aktiv ist (no_burst_decay_factor),
    damit die Baseline nicht durch nicht-ausgelöste Rises hochdriftet.
    """
    db        = _level_windows(audio, sr, window_s, mode=mode)
    if level_floor_pct is not None and len(db):
        # Analysespur (Übersprechen/Rauschen herausgerechnet) kann nahezu digital
        # still sein → ohne Boden sinkt die Grundlinie ins Bodenlose und jedes
        # winzige Restgeräusch wirkt wie ein großer Anstieg.
        db = np.maximum(db, float(np.percentile(db, level_floor_pct)))
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

    # Sperrfrist nach dem Loesen des Freeze. Messung an echtem Material:
    # FPs starten 0,10-1,40 s nach dem Freeze-Ende, echte Reaktionen fruehestens
    # nach 1,00 s. Ursache: das On-Mic ist wieder laut (Freeze faellt), das
    # Crossbleed auf dem Off-Mic braucht aber laenger zurueck — in dieser Luecke
    # faellt die Baseline dreifach schnell (no_burst_decay_factor) und das
    # zurueckkehrende Crossbleed erzeugt einen falschen Rise.
    # Bewusst NICHT laenger einfrieren: das haelt die Baseline an und
    # unterdrueckt auch echte Reaktionen. Hier wird nur das AUSLOESEN gesperrt,
    # die Baseline laeuft normal weiter.
    refractory_n = max(0, int(post_freeze_refractory_s / window_s))
    last_frozen_k = -10 ** 9

    # Adaptiver Freeze: Die Maske endet, sobald das ON-Mic wieder laut ist. Das
    # Crossbleed auf dem OFF-Mic braucht aber laenger zurueck. Genau in dieser
    # Luecke faellt die Baseline (dreifach schnell) und erzeugt beim Eintreffen
    # des Crossbleeds den falschen Rise. Deshalb weiter halten, solange der
    # Pegel noch unter dem eingefrorenen Wert liegt — aber nur so lange wie
    # noetig und hoechstens freeze_hold_max_s. Pauschal laenger einzufrieren
    # deckt zu viel ab und kostet echte Reaktionen (siehe brain/
    # Sprachreaktionen-Parameter.md, Versuch 1).
    hold_max_n  = max(0, int(freeze_hold_max_s / window_s))
    frozen_val  = None
    held        = 0

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
            last_frozen_k = k
            frozen_val = baseline[k]
            held = 0
        elif (frozen_val is not None and held < hold_max_n
              and db[k] < frozen_val - freeze_release_margin_db):
            # Maske vorbei, Pegel aber noch nicht zurueck -> weiter halten.
            baseline[k] = baseline[k - 1]
            last_frozen_k = k
            held += 1
        elif db[k] > baseline[k - 1]:
            frozen_val = None
            baseline[k] = baseline[k - 1] + alpha_a * (db[k] - baseline[k - 1])
            since_attack = 0
        else:
            frozen_val = None
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
                elif rejected_sink is not None:
                    rejected_sink.append({
                        'start_s': round(burst_start * window_s, 3),
                        'end_s':   round(k * window_s, 3),
                        'reason':  'kuerzer_als_min_duration',
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
                elif rejected_sink is not None:
                    rejected_sink.append({
                        'start_s': round(burst_start * window_s, 3),
                        'end_s':   round(k * window_s, 3),
                        'reason':  'kuerzer_als_min_duration',
                    })
                in_burst = False
        # ">=" statt ">": bei refractory_n == 0 muss die Bedingung IMMER wahr
        # sein, sonst blockiert der Default das Ausloesen waehrend eingefrorener
        # Fenster — das liess der Originalcode zu (kostete 4 Detektionen).
        elif rise[k] >= rise_db and (k - last_frozen_k) >= refractory_n:
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
        elif rejected_sink is not None:
            rejected_sink.append({
                'start_s': round(burst_start * window_s, 3),
                'end_s':   round(k * window_s, 3),
                'reason':  'kuerzer_als_min_duration',
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
    debug_sink: list = None,
    post_freeze_refractory_s: float = 0.0,
    freeze_hold_max_s: float = 0.0,
    freeze_release_margin_db: float = 3.0,
    fp_filter: bool = False,
    fp_corr_max: float = 0.75,
    fp_on_rise_db: float = 999.0,   # Regel B: an Episode 2 durchgefallen, siehe unten
    fp_takeover_s: float = 0.0,     # Regel C: Nutzen marginal, kostet TPs
    det_audio1: np.ndarray = None,  # Mischform (Versuch): Kandidaten auf der
    det_audio2: np.ndarray = None,  # Analysespur suchen, Regel A auf den Originalen
    det_floor_pct: float = 5.0,
) -> tuple:
    """
    Rolling-Baseline Burst Detection auf dem Off-Kamera-Mikrofon.

    Läuft per Diarization-Segment mit Baseline-Reset am Anfang jeder
    Off-Section, damit die Baseline nicht über die gesamte Aufnahme
    wegdriftet.

    on_pauses: Dict {'CAM1': [(s, e), ...], 'CAM2': [(s, e), ...]}
               On-Speaker-Pausen zur Baseline-Maskierung.
    debug_sink: Optionale Liste. Wenn gesetzt, wird pro Segment ein Record mit
               Pegel-, Baseline-, Rise- und Freeze-Verlauf angehaengt
               (Dev-Modus, siehe speaking_debug.json). Ohne Sink aendert sich
               am Verhalten nichts.

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
    _fp_count = {'verworfen': 0}

    def _fp_reject(b, off_db, on_db, seg, nxt_speaker, react_cam):
        """Drei unabhaengige FP-Ursachen. Gibt den Grund zurueck oder None.

        Hergeleitet aus 22 vom Nutzer markierten Cutaways (16 FP / 6 TP);
        Messwerte und Schwellen in brain/Sprachreaktionen-Parameter.md.
        """
        k0 = int(b['start_s'] / window_s)
        k1 = min(len(off_db), int(b['end_s'] / window_s))
        lb = max(1, int(1.0 / window_s))
        if k0 >= len(off_db) or k1 <= k0:
            return None

        # C) Wortuebernahme: Das ist keine Reaktion, sondern der Beginn des
        #    eigenen Redebeitrags — direkt danach wechselt die Diarisierung
        #    auf genau diese Kamera.
        if (fp_takeover_s > 0 and nxt_speaker == react_cam
                and (seg['end_s'] - (seg['start_s'] + b['start_s'])) <= fp_takeover_s):
            return 'wortuebernahme'

        pre = slice(max(0, k0 - lb), k0)
        if on_db is not None and len(on_db) >= k1:
            # B) Das ON-Mic steigt mit: der Sprecher redet weiter, das ist
            #    Uebersprechen und keine Reaktion.
            if fp_on_rise_db < 999:
                on_rise = float(np.median(on_db[k0:k1]) - np.median(on_db[pre]))
                if on_rise >= fp_on_rise_db:
                    return 'on_mic_steigt'

            # A) Beide Huellkurven laufen im Gleichtakt -> reines Crossbleed.
            if fp_corr_max <= 1.0:
                lo = max(0, k0 - int(3.0 / window_s))
                hi = min(len(off_db), k0 + int(2.0 / window_s))
                a_ = np.asarray(off_db[lo:hi], dtype=float)
                b_ = np.asarray(on_db[lo:hi], dtype=float)
                if len(a_) >= 20 and a_.std() > 0.1 and b_.std() > 0.1:
                    if float(np.corrcoef(a_, b_)[0, 1]) >= fp_corr_max:
                        return 'gleichtakt'
        return None

    for si, seg in enumerate(segments):
        seg_start_sample = int(seg['start_s'] * sr)
        seg_end_sample   = int(seg['end_s'] * sr)
        seg_start_edl    = wav_edl_frame + round(seg['start_s'] * fps)

        if seg['speaker'] == 'CAM1':
            seg_audio = audio2[seg_start_sample:seg_end_sample]
            on_audio  = audio1[seg_start_sample:seg_end_sample]
            det_src   = det_audio2
            cam_tz = cam2_timeline_zero_video
            target = cam2_reactions
        elif seg['speaker'] == 'CAM2':
            seg_audio = audio1[seg_start_sample:seg_end_sample]
            on_audio  = audio2[seg_start_sample:seg_end_sample]
            det_src   = det_audio1
            cam_tz = cam1_timeline_zero_video
            target = cam1_reactions
        else:
            continue
        # Mischform: Kandidaten auf der Analysespur (dort heben sich leise Einwürfe
        # ab), alles andere — insbesondere Regel A — weiter auf den Originalen.
        det_seg = (det_src[seg_start_sample:seg_end_sample]
                   if det_src is not None else None)

        if len(seg_audio) < int(warmup_s * sr):
            # Segment kuerzer als die Warmup-Phase: hier wird gar nicht erst
            # nach Reaktionen gesucht. Im Debug festhalten, sonst verschwindet
            # der Fall spurlos.
            if debug_sink is not None:
                debug_sink.append({
                    'speaker': seg['speaker'],
                    'start_s': round(seg['start_s'], 3),
                    'end_s':   round(seg['end_s'], 3),
                    'skipped': 'segment_kuerzer_als_warmup',
                })
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

        _dbg      = debug_sink is not None
        _need     = _dbg or fp_filter      # Kurven auch fuer den Nachfilter noetig
        _rejected = [] if _dbg else None
        _res = _bursts_rolling(
            det_seg if det_seg is not None else seg_audio, sr, fps, window_s,
            attack_window_s, release_window_s, warmup_s,
            rise_db, min_duration_s, max_duration_s, hold_s,
            timeline_start_frame=seg_start_edl,
            mode=mode,
            decay_hold_s=decay_hold_s,
            lookback_s=lookback_s,
            sustain_margin_db=sustain_margin_db,
            freeze_mask=seg_freeze,
            post_freeze_refractory_s=post_freeze_refractory_s,
            freeze_hold_max_s=freeze_hold_max_s,
            freeze_release_margin_db=freeze_release_margin_db,
            return_debug=_need,
            rejected_sink=_rejected,
            level_floor_pct=det_floor_pct if det_seg is not None else None,
        )
        if _need:
            bursts, _db, _base, _rise = _res
        else:
            bursts = _res
        _on_db = (_level_windows(on_audio, sr, window_s, mode=mode)
                  if _need else None)

        # Regel A braucht die ORIGINAL-Pegel des Zuhörer-Mikros (dort ist das
        # Übersprechen als Gleichtakt sichtbar) — nicht die der Analysespur.
        _ra_db = (_level_windows(seg_audio, sr, window_s, mode=mode)
                  if (fp_filter and det_seg is not None) else
                  (_db if fp_filter else None))
        _fp_dropped = []
        if fp_filter:
            react_cam   = 'CAM2' if seg['speaker'] == 'CAM1' else 'CAM1'
            nxt_speaker = (segments[si + 1]['speaker']
                           if si + 1 < len(segments) else None)
            _kept = []
            for b in bursts:
                why = _fp_reject(b, _ra_db, _on_db, seg, nxt_speaker, react_cam)
                if why:
                    _fp_dropped.append(dict(b, fp_reason=why))
                else:
                    _kept.append(b)
            bursts = _kept
            _fp_count['verworfen'] += len(_fp_dropped)

        emitted = []
        for b in bursts:
            r = _to_reaction(b, cam_tz)
            emitted.append(r is not None)
            if r:
                target.append(r)

        if _dbg:
            # Freeze defensiv auf die Kurvenlaenge bringen (sollte identisch
            # sein: beide rechnen len // int(sr * window_s)).
            if seg_freeze is not None:
                _fz = [int(v) for v in seg_freeze[:len(_db)]]
                _fz += [0] * (len(_db) - len(_fz))
            else:
                _fz = [0] * len(_db)
            debug_sink.append({
                'speaker':         seg['speaker'],
                'reaction_cam':    'CAM2' if seg['speaker'] == 'CAM1' else 'CAM1',
                'off_mic':         'MIC2' if seg['speaker'] == 'CAM1' else 'MIC1',
                'start_s':         round(seg['start_s'], 3),
                'end_s':           round(seg['end_s'], 3),
                'start_edl_frame': seg_start_edl,
                'db':       [round(float(v), 1) for v in _db],
                # Pegel des ON-Mics (des Sprechenden) im selben Raster. Der
                # Detektor sieht ihn nicht — fuer die Diagnose ist er aber
                # entscheidend: steigen beide Mics gleichzeitig, ist es
                # zurueckkehrendes Crossbleed und keine Reaktion.
                'db_on':    [round(float(v), 1) for v in _on_db[:len(_db)]],
                'fp_dropped': _fp_dropped,
                'baseline': [round(float(v), 1) for v in _base],
                'rise':     [round(float(v), 1) for v in _rise],
                'freeze':   _fz,
                'bursts':   [dict(b, emitted=e) for b, e in zip(bursts, emitted)],
                'rejected': _rejected,
            })

    if fp_filter:
        print(f"  FP-Filter (Regel A{'' if det_audio1 is None else ', Mischform'}): "
              f"{_fp_count['verworfen']} Kandidaten verworfen")
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


def insert_transition_events(events: list, fps: float,
                            resolve_bridge,
                            bridge_len_frames, min_shot_frames: int,
                            return_min_factor: float = 2.5) -> list:
    """Setzt bei Sprecherwechseln eine Zwischeneinstellung davor.

    Aus `Close P1 → Close P2` wird `Close P1 → Bruecke → Close P2`. Die Bruecke
    ist die kleinste Kamera, die BEIDE zeigt (siehe transition_rule.py).

    WOHER DIE ZEIT KOMMT: vom EINGEHENDEN Event. Die Bruecke belegt dessen erste
    Frames, danach folgt der Rest als Nahaufnahme. Man hoert den neuen Sprecher
    also bereits, waehrend noch das weite Bild steht, und schneidet dann hinein.

    WANN GAR NICHT (User, 21.07.): Ist das eingehende Event zu kurz, bleibt es
    unangetastet — es wird NICHT die Bruecke ueber die ganze Laenge gezogen. Eine
    Verlaengerung haette den Sprecher unsichtbar gemacht: aus A-B-A wuerde A-T-A,
    B haette gesprochen und waere nie zu sehen.

    Die 2,5x-Schwelle (`return_min_factor`) gilt NUR dem HINWEG eines A-B-A:
    "Ist B lang genug, um ueber die Totale HINEINzuschneiden?" Eine kurze
    Zwischenrede totalisiert man nicht — das wird hektisch, und die Bruecke wuerde
    B zusaetzlich kuerzen.

    Der RUECKWEG (B→A) ist davon unberuehrt: er frisst A, nicht B, und ist eine
    weiche Landung zurueck zum Sprecher. Fuer ihn zaehlt nur, dass A nach der
    Bruecke noch min_shot uebrig hat (`want + min_shot`) — dieselbe Bedingung wie
    beim gewoehnlichen Weitergang A-B-C.

    Kurzes B ergibt damit A-B-T-A: Hinweg unterdrueckt (B bleibt ungekuerzt),
    Rueckweg gebaut, B durch den transition-bewussten PASS-3-Schutz gehalten.

    resolve_bridge(von_clip, nach_clip) -> (clip, ref, timeline_zero_video) oder
    None. BEWUSST je Uebergang befragt, nicht einmal global: unter binaerer
    Diarisierung ist das Ergebnis zwar konstant, aber das ist eine Eigenschaft
    der heutigen Einschraenkung. Mit N-facher Diarisierung kann jedes
    Personenpaar eine andere kleinste gemeinsame Kamera haben, und schon bei
    zwei gleich weiten Kameras waere „immer dieselbe" ein Verstoss gegen die
    Dynamik-Regel.

    bridge_len_frames: Aufruf ohne Argumente, liefert je Uebergang eine Laenge
    (der Zufallsfaktor soll pro Schnitt neu wuerfeln, nicht einmal global).
    """
    if resolve_bridge is None or len(events) < 2:
        return events

    result = [events[0]]
    inserted = too_short = already = skipped_offcam = 0

    for i in range(1, len(events)):
        prev, event = events[i - 1], events[i]
        if prev['clip_name'] == event['clip_name']:
            result.append(event)
            continue

        chosen = resolve_bridge(prev['clip_name'], event['clip_name'])
        if not chosen:
            result.append(event)          # keine gemeinsame Kamera -> wie bisher
            continue
        bridge_clip, bridge_ref, bridge_timeline_zero_video = chosen

        # Stehen wir bereits im weiten Bild, waere eine Bruecke ein Schnitt auf
        # dieselbe Kamera. Massgeblich ist das AUSGEGEBENE, nicht das Original.
        if result[-1]['clip_name'] == bridge_clip:
            already += 1
            result.append(event)
            continue

        ev_start = timecode_to_frames(event['record_in'],  fps)
        ev_end   = timecode_to_frames(event['record_out'], fps)

        vid_start = bridge_timeline_zero_video + ev_start
        if vid_start < 0:
            skipped_offcam += 1           # Bruecken-Kamera laeuft noch nicht
            result.append(event)
            continue

        want   = bridge_len_frames()
        ev_len = ev_end - ev_start

        # Die 2,5x-Schwelle gilt NUR dem Hinweg. Sie beantwortet: „Ist B lang
        # genug, um ueber die Totale HINEINzuschneiden?" — eine kurze Zwischenrede
        # totalisiert man nicht, das wird hektisch. Der Rueckweg ist etwas anderes:
        # er frisst A, nicht B, und ist eine weiche Landung zurueck zum Sprecher.
        # Fuer ihn ist die Laenge von B egal (User, 22.07.); massgeblich ist nur,
        # dass das zurueckkehrende A nach der Bruecke noch min_shot uebrig hat.
        #
        # Kurzes B ist damit voll abgedeckt: der Hinweg baut keine Totale (B < 2,5x)
        # und laesst B ungekuerzt, der Rueckweg landet weich, und der
        # transition-bewusste PASS-3-Schutz haelt B in der Timeline. → A-B-T-A.
        nxt = events[i + 1] if i + 1 < len(events) else None
        forward_aba = nxt is not None and nxt['clip_name'] == prev['clip_name']

        if forward_aba:                       # A→B mit Rueckkehr zu A: Hinweg-Gate
            required = int(round(return_min_factor * min_shot_frames))
        else:                                 # Rueckweg oder A→B→C: A braucht Platz
            required = want + min_shot_frames

        if ev_len < required:
            too_short += 1
            result.append(event)
            continue

        bridge_end = ev_start + want
        inserted += 1
        result.append({
            'clip_name':  bridge_clip,
            'source_in':  frames_to_timecode(bridge_ref + vid_start, fps),
            'source_out': frames_to_timecode(bridge_ref + bridge_timeline_zero_video + bridge_end, fps),
            'record_in':  frames_to_timecode(ev_start,   fps),
            'record_out': frames_to_timecode(bridge_end, fps),
            'reason':     'transition',
        })
        result.append(_slice_event(event, bridge_end, ev_end, fps))

    if inserted or too_short or already or skipped_offcam:
        msg = f"  {inserted} Uebergangs-Einstellung(en) bei Sprecherwechseln"
        if too_short:
            msg += f"; {too_short} entfallen (Sprechbeitrag zu kurz)"
        if already:
            msg += f"; {already} entfallen (stand bereits im weiten Bild)"
        if skipped_offcam:
            msg += f"; {skipped_offcam} ausgelassen (Bruecken-Kamera noch nicht gestartet)"
        print(msg)
    return result


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
            f.write(f"* FROM CLIP NAME: {ev['clip_name']}\n")
            # Begruendung mitschreiben, sonst geht sie beim Wiedereinlesen
            # verloren: add_reactions setzt dann pauschal 'speaker'. Betraf die
            # Uebergangs-Einstellungen — im AAF hiessen sie 'Sprecher' statt
            # 'Uebergang', und der Schutz in PASS 3 konnte nie greifen.
            if ev.get('reason') and ev['reason'] != 'speaker':
                f.write(f"* CUT REASON: {ev['reason']}\n")
            f.write("\n")
    print(f"\n✓ EDL geschrieben: {output_path}")


def detect_simultaneous_speech_n(person_audios: dict, persons: list, sr: int,
                                 window_s: float, threshold_db: float,
                                 min_duration_s: float) -> list:
    """
    N-Version von detect_simultaneous_speech. Ein Fenster gilt als simultan, wenn
    >=2 Personen ueber dem Noise-Floor liegen UND der Abstand der zwei lautesten
    aktiven Personen < threshold_db ist (keine klare Dominanz).

    Rueckgabe: Liste {start_s, end_s, persons:[beteiligte Personen-IDs]}. Bei
    genau 2 Personen entspricht das dem binaeren Verhalten (both_active &
    |rms1-rms2| < threshold).
    """
    NOISE_FLOOR_DB = -50.0
    rms = [compute_rms_db(person_audios[p], sr, window_s) for p in persons]
    n = min(len(r) for r in rms)
    mat = np.stack([r[:n] for r in rms], axis=1)      # (n, K)
    active = mat > NOISE_FLOOR_DB

    win_persons = [None] * n
    for i in range(n):
        act_idx = np.where(active[i])[0]
        if len(act_idx) < 2:
            continue
        top2 = np.sort(mat[i, act_idx])[::-1][:2]     # zwei lauteste Aktiven
        if (top2[0] - top2[1]) < threshold_db:
            win_persons[i] = [persons[j] for j in act_idx]

    min_wins = max(1, int(min_duration_s / window_s))
    segments, i = [], 0
    while i < n:
        if win_persons[i] is None:
            i += 1
            continue
        j, involved = i, set()
        while j < n and win_persons[j] is not None:
            involved.update(win_persons[j])
            j += 1
        if (j - i) >= min_wins:
            segments.append({'start_s': i * window_s, 'end_s': j * window_s,
                             'persons': sorted(involved)})
        i = j
    return segments


def insert_totale_events_n(events: list, simul_segments: list, cameras: list,
                           fps: float, wav_edl_frame: int, cam_shift: int) -> list:
    """
    N-Version von insert_totale_events: legt waehrend Simultan-Sprechen die
    KLEINSTE Kamera, die ALLE beteiligten Personen zeigt (smallest_containing),
    ueber die Events — je Region die passende, statt einer festen Totale.
    """
    from shot_sizes import smallest_containing
    if not simul_segments:
        return events

    regions = []
    for seg in simul_segments:
        cam = smallest_containing(cameras, seg['persons'])
        if cam is None:
            continue                                   # keine Kamera zeigt alle
        s = max(0, round(seg['start_s'] * fps) + wav_edl_frame + cam_shift)
        e = round(seg['end_s'] * fps) + wav_edl_frame + cam_shift
        if e > s:
            regions.append((s, e, cam))

    result = []
    for event in events:
        ev_start = timecode_to_frames(event['record_in'],  fps)
        ev_end   = timecode_to_frames(event['record_out'], fps)
        overlaps = [(max(s, ev_start), min(e, ev_end), cam)
                    for s, e, cam in regions if e > ev_start and s < ev_end]
        if not overlaps:
            result.append(event)
            continue
        cursor = ev_start
        for simul_start, simul_end, cam in sorted(overlaps, key=lambda r: r[0]):
            if cursor < simul_start:
                result.append(_slice_event(event, cursor, simul_start, fps))
            e_frame = cam['edl_frame'] + cam_shift
            tot_video_start = simul_start - e_frame
            tot_video_end   = simul_end   - e_frame
            if tot_video_start >= 0:
                result.append({
                    'clip_name':  cam['clip'],
                    'source_in':  frames_to_timecode(cam['ref'] + tot_video_start, fps),
                    'source_out': frames_to_timecode(cam['ref'] + tot_video_end,   fps),
                    'record_in':  frames_to_timecode(simul_start, fps),
                    'record_out': frames_to_timecode(simul_end,   fps),
                })
            cursor = simul_end
        if cursor < ev_end:
            result.append(_slice_event(event, cursor, ev_end, fps))
    return result


def compute_off_sections_n(events: list, cameras: list, cam_shift: int,
                           fps: float) -> dict:
    """
    Fuer jede Kamera die VIDEO-Frame-Ranges, in denen sie NICHT die On-Kamera ist
    (sie zeigt dann einen Zuhoerer/Reaktor). Die Nicken-Analyse muss nur diese
    Bereiche ansehen — bei N Kameras waere die volle Analyse sonst enorm teuer.

    Mirror der binaeren Off-Sektionen (CAM1 off, wenn CAM2 spricht), fuer N: Kamera
    X ist off in jedem Event, dessen Clip != X ist. Video-Frame = Timeline-Frame -
    (X.edl_frame + cam_shift), nur solange die Kamera schon Material hat (>= 0).
    """
    off = {c['clip']: [] for c in cameras}
    e_frame = {c['clip']: c['edl_frame'] + cam_shift for c in cameras}
    for ev in events:
        on_clip = ev['clip_name']
        rec_s = timecode_to_frames(ev['record_in'],  fps)
        rec_e = timecode_to_frames(ev['record_out'], fps)
        for c in cameras:
            clip = c['clip']
            if clip == on_clip:
                continue
            v_s = rec_s - e_frame[clip]
            v_e = rec_e - e_frame[clip]
            if v_s >= 0 and v_e > v_s:
                off[clip].append([int(v_s), int(v_e)])
    return off


# ─── N-Personen-Pfad ────────────────────────────────────────────────────────────

def _run_n_path(args):
    """Basis-EDL fuer >2 Personen. Liest die Kamera-Spezifikation aus
    args.cams_json, richtet die Personen-Mics auf einen gemeinsamen Zeitursprung
    aus, diarisiert ueber Personen und schneidet jede auf ihre engste Kamera
    (build_base_edl_n). Umgeht den gesamten binaeren main()-Code.

    cams_json-Format:
        {"cameras": [{"clip","video","mics":[...Mic-Pfade...],"edl_frame"}],
         "mic_offsets": {Mic-Pfad: Frame-Offset relativ zu CAM1}}
    """
    spec = json.loads(Path(args.cams_json).read_text(encoding='utf-8'))
    cameras_in = spec['cameras']
    mic_offsets = spec.get('mic_offsets', {})

    print("=" * 70)
    print(f"🎙️  BUILD BASE EDL — {len(cameras_in)} Kameras, N Personen")
    print("=" * 70)

    # Alle unterschiedlichen Personen-Mics (Reihenfolge stabil).
    persons = []
    for cam in cameras_in:
        for m in cam['mics']:
            if m not in persons:
                persons.append(m)
    if not persons:
        print("✗ Keine Personen-Mics in --cams-json. Abbruch.")
        return 1

    print("\n📂 Lade Personen-Audio...")
    person_audio, sr = {}, None
    for m in persons:
        a, s = load_audio(m)
        sr = s if sr is None else sr
        assert s == sr, f"Sample rates differ: {s} vs {sr}"
        person_audio[m] = a
        print(f"  {Path(m).name}: {len(a)/s/60:.1f} min")

    # Auf gemeinsamen Zeitursprung ausrichten: die frueheste Person ist Frame 0,
    # spaeter startende werden vorne mit Stille aufgefuellt — sonst stimmt die
    # Diarisierungs-Zeitachse ueber die Mics nicht. Bei einem Mehrspur-Recorder
    # (gleiche Offsets) passiert hier nichts.
    o_min = min(int(mic_offsets.get(m, 0)) for m in persons)
    for m in persons:
        pad_frames = int(mic_offsets.get(m, 0)) - o_min
        if pad_frames > 0:
            pad = np.zeros(int(round(pad_frames / args.fps * sr)),
                           dtype=person_audio[m].dtype)
            person_audio[m] = np.concatenate([pad, person_audio[m]])
    wav_edl_frame = o_min

    # Silence-Gate je Person (adaptiv wie im binaeren Pfad: kmeans-Schwelle - 15,
    # oder manueller Override).
    gates = {}
    if args.pause_silence_db is not None:
        gates = {m: args.pause_silence_db - 15 for m in persons}
        print(f"\n🔇 Silence-Schwelle: {args.pause_silence_db:.0f} dB (manuell)")
    else:
        from shared.audio_analysis import suggest_threshold_kmeans
        for m in persons:
            th = suggest_threshold_kmeans(person_audio[m], sr)
            gates[m] = float(th['threshold']) - 15
        print("\n🔇 Silence-Schwelle je Person adaptiv (K-Means).")

    # Kameras mit embedded-TC-Ref anreichern.
    print("\n🎯 Lese embedded Timecodes...")
    cameras = []
    for cam in cameras_in:
        ref, tc = get_reference_frame(cam['video'], args.fps)
        if ref is None:
            print(f"✗ Konnte embedded TC nicht lesen fuer {cam['clip']}. Abbruch.")
            return 1
        print(f"  {cam['clip']}: TC {tc} = {ref} frames, zeigt {len(cam['mics'])} Person(en)")
        cameras.append({'name': cam['clip'], 'clip': cam['clip'],
                        'mics': cam['mics'], 'edl_frame': int(cam['edl_frame']),
                        'ref': ref})

    print(f"\n📊 N-Diarisierung ({len(persons)} Personen, "
          f"threshold={args.threshold_db:.1f} dB)...")
    base_events = build_base_edl_n(
        cameras, person_audio, sr, args.fps, wav_edl_frame,
        args.analysis_window, args.threshold_db,
        args.change_delay, args.min_edit_duration, gates)
    print(f"  {len(base_events)} Events (Grundschnitt)")

    # Degenerierte Diarisierung abfangen — wie im binaeren Pfad: ein einziges
    # Event ueber eine lange Aufnahme heisst, die Personen-Mics unterscheiden
    # sich nirgends klar. Klare Meldung statt sinnloser Ein-Event-EDL.
    _dur_s = max(len(a) for a in person_audio.values()) / sr
    if len(base_events) <= 1 and _dur_s > 300:
        print("\n✗ Die Sprechererkennung findet keine klaren Unterschiede zwischen "
              "den Personen-Mikrofonen.")
        print(f"  In {_dur_s / 60:.1f} Minuten ergibt sich nur ein einziger "
              "Sprecher-Abschnitt — so laesst sich nicht bestimmen, wer wann "
              "spricht.")
        print("  Haeufigste Ursachen: gleicher Mix auf allen Spuren (statt "
              "Einzelspuren), Limiter/AGC am Recorder, extremes Uebersprechen.")
        print("  Bitte die Spuren einzeln anhoeren (Play-Knopf im Schritt "
              "Personen): Ist auf jeder Spur die EIGENE Person deutlich lauter?")
        return 1

    cam_shift = max(0, -min(c['edl_frame'] for c in cameras))

    # Off-Sektionen je Kamera schreiben (nur Zuhoerer-Frames → Nicken-Analyse muss
    # nicht das volle Material je Kamera durchrechnen). Aus dem GRUNDSCHNITT, also
    # der Sprecher-Struktur — analog zum binaeren Pfad. Namensschema passt zu dem,
    # was run_analysis erwartet: <video_stem>_off_sections.json neben der EDL.
    out_dir = Path(args.output).parent
    off = compute_off_sections_n(base_events, cameras, cam_shift, args.fps)
    print("\n📄 Off-Sektionen (Zuhoerer-Frames je Kamera):")
    for clip, ranges in off.items():
        (out_dir / (Path(clip).stem + '_off_sections.json')).write_text(
            json.dumps(ranges), encoding='utf-8')
        total_s = sum(e - s for s, e in ranges) / args.fps
        print(f"  {clip}: {len(ranges)} Segmente ({total_s / 60:.1f} min)")

    # Simultan-Sprechen → kleinste Kamera, die ALLE Beteiligten zeigt (Totale).
    events = base_events
    simul = detect_simultaneous_speech_n(
        person_audio, persons, sr, args.analysis_window, args.threshold_db,
        args.totale_simul_min_duration)
    if simul:
        print(f"\n  {len(simul)} Simultan-Region(en) → kleinste gemeinsame Kamera")
        events = insert_totale_events_n(base_events, simul, cameras, args.fps,
                                        wav_edl_frame, cam_shift)
        print(f"  {len(events)} Events (nach Simultan→Totale)")

    # Uebergangsregel (Bildsprache): bei jedem Sprecherwechsel ueber die kleinste
    # Kamera schneiden, die BEIDE Sprecher zeigt. Bewusst hier auf der ruhigen
    # Basis-EDL (vor den Cutaways). Der Resolver liefert je Uebergang die
    # smallest_containing der beiden Sprecher-Personen — genau der N-Fall, fuer
    # den insert_transition_events schon gebaut ist.
    if args.transition_on_speaker_change:
        import random as _rnd
        from shot_sizes import smallest_containing
        persons_by_clip = {c['clip']: (c.get('mics') or []) for c in cameras}
        ref_by_clip     = {c['clip']: c['ref'] for c in cameras}
        tzv_by_clip     = {c['clip']: -(c['edl_frame'] + cam_shift) for c in cameras}
        base_f, rnd_f = args.transition_min_shot, args.transition_randomness

        def _bridge_len():
            factor = 1.0 + _rnd.uniform(0.0, rnd_f) if rnd_f > 0 else 1.0
            return max(1, int(round(base_f * factor * args.fps)))

        def _resolve(_from_clip, _to_clip):
            ppl = sorted(set(persons_by_clip.get(_from_clip, [])) |
                         set(persons_by_clip.get(_to_clip, [])))
            cam = smallest_containing(cameras, ppl) if ppl else None
            if cam is None:
                return None
            return (cam['clip'], ref_by_clip[cam['clip']], tzv_by_clip[cam['clip']])

        print("\n🎬 Uebergangsregel (Sprecherwechsel)...")
        events = insert_transition_events(
            events, args.fps, _resolve, _bridge_len,
            int(args.transition_min_shot * args.fps),
            return_min_factor=args.transition_return_factor)
        print(f"  {len(events)} Events (nach Uebergaengen)")

    write_edl(events, args.output)
    return 0


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Build Base EDL from Audio (RMS)')

    # N-Personen-Pfad (>2 Sprecher): umgeht den gesamten binaeren Code unten.
    parser.add_argument('--cams-json', default=None,
                        help='JSON-Spezifikation fuer >2 Personen. Wenn gesetzt, '
                             'wird der binaere 2-Personen-Pfad komplett umgangen '
                             '(siehe _run_n_path / build_base_edl_n).')

    # Audio (nargs='+' erlaubt mehrere MICs pro Kamera). Ohne --cams-json Pflicht.
    parser.add_argument('--mic-cam1', nargs='+',
                        help='Mikrofon-Spur(en) für CAM1 (WAV). Mehrere Pfade = aggregiert.')
    parser.add_argument('--mic-cam2', nargs='+',
                        help='Mikrofon-Spur(en) für CAM2 (WAV). Mehrere Pfade = aggregiert.')

    # Video (für ffprobe embedded TC). Ohne --cams-json Pflicht.
    parser.add_argument('--cam1-video', help='CAM1 Video-Datei')
    parser.add_argument('--cam2-video', help='CAM2 Video-Datei')
    parser.add_argument('--cam1-clip',  help='CAM1 Clip-Name in der EDL')
    parser.add_argument('--cam2-clip',  help='CAM2 Clip-Name in der EDL')

    # Sync-Offsets (vom User aus Resolve). Ohne --cams-json Pflicht.
    parser.add_argument('--wav-edl-frame',  type=int,
                        help='EDL-Frame bei dem WAV Frame 0 liegt')
    parser.add_argument('--cam1-edl-frame', type=int,
                        help='EDL-Frame bei dem CAM1 Frame 0 liegt')
    parser.add_argument('--cam2-edl-frame', type=int,
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
    parser.add_argument('--speaking-fp-filter', action='store_true',
                        help='FP-Nachfilter fuer Sprachreaktionen (drei Ursachen, '
                             'siehe brain/Sprachreaktionen-Parameter.md). Default aus.')
    parser.add_argument('--speaking-fp-corr', type=float, default=0.75,
                        help='A: verwerfen ab dieser Huellkurven-Korrelation Off/On. '
                             '>1.0 = Regel aus.')
    parser.add_argument('--speaking-fp-on-rise', type=float, default=999.0,
                        help='B: verwerfen ab diesem On-Mic-Anstieg in dB. '
                             '999 = Regel aus.')
    parser.add_argument('--speaking-detect-mic-cam1', nargs='+', default=None,
                        help='Versuch Mischform: Analysespur(en) fuer die Kandidatensuche CAM1')
    parser.add_argument('--speaking-detect-mic-cam2', nargs='+', default=None,
                        help='Versuch Mischform: Analysespur(en) fuer die Kandidatensuche CAM2')
    parser.add_argument('--speaking-fp-takeover', type=float, default=0.0,
                        help='C: verwerfen, wenn der Burst so viele Sekunden vor dem '
                             'Segmentende liegt UND danach diese Cam spricht. 0 = aus.')
    parser.add_argument('--speaking-freeze-hold-max', type=float, default=0.0,
                        help='Adaptiver Freeze: max. Sekunden, die ueber die Maske '
                             'hinaus gehalten wird, solange der Pegel nicht zurueck '
                             'ist. 0 = aus (Verhalten wie bisher).')
    parser.add_argument('--speaking-freeze-release-margin', type=float, default=3.0,
                        help='Toleranz in dB: ab wann der Pegel als zurueckgekehrt gilt.')
    parser.add_argument('--speaking-post-freeze-refractory', type=float, default=0.0,
                        help='Sperrfrist in s nach dem Loesen des Baseline-Freeze. '
                             '0 = aus (Verhalten wie bisher).')
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
    parser.add_argument('--transition-on-speaker-change', action='store_true',
                        help='Uebergangsregel: bei jedem Sprecherwechsel ueber die '
                             'kleinste gemeinsame Einstellung schneiden '
                             '(siehe brain/Bildsprache.md).')
    parser.add_argument('--transition-min-shot', type=float, default=2.3,
                        help='Basislaenge der Uebergangs-Einstellung in Sekunden. '
                             'Folgt der allgemeinen Mindest-Schnittlaenge.')
    parser.add_argument('--transition-return-factor', type=float, default=2.5,
                        help='Im Muster A-B-A muss B mindestens dieses Vielfache '
                             'der Mindest-Schnittlaenge dauern, damit eine Bruecke '
                             'eingebaut wird. Sonst bleibt der kurze Beitrag stehen.')
    parser.add_argument('--transition-randomness', type=float, default=0.0,
                        help='Zufallsfaktor auf die Brueckenlaenge, einseitig '
                             '(verlaengert nur) — wie bei den Cutaways.')
    parser.add_argument('--totale-simul-min-duration', type=float, default=3.0,
                        help='Mindestdauer Simultansprechen bevor auf Totale geschnitten wird (s)')
    # Pause-Trimming
    parser.add_argument('--pause-trim',           action='store_true',
                        help='Überlange Sprechpausen an Diarization-Grenzen trimmen')
    parser.add_argument('--max-pause',            type=float, default=1.0,
                        help='Max. erlaubte Pausendauer in Sekunden (default: 1.0)')
    parser.add_argument('--pause-silence-db',     type=float, default=None,
                        help='dB-Schwelle unter der Stille erkannt wird (default: adaptiv via K-Means)')
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

    # N-Personen-Pfad: eigener Weg, umgeht den binaeren Code komplett.
    if args.cams_json:
        return _run_n_path(args)

    # Binaerer 2-Personen-Pfad: die paarweisen Argumente sind dann Pflicht.
    _need = {'--mic-cam1': args.mic_cam1, '--mic-cam2': args.mic_cam2,
             '--cam1-video': args.cam1_video, '--cam2-video': args.cam2_video,
             '--cam1-clip': args.cam1_clip, '--cam2-clip': args.cam2_clip,
             '--wav-edl-frame': args.wav_edl_frame,
             '--cam1-edl-frame': args.cam1_edl_frame,
             '--cam2-edl-frame': args.cam2_edl_frame}
    _missing = [k for k, v in _need.items() if v is None]
    if _missing:
        parser.error("ohne --cams-json erforderlich: " + ", ".join(_missing))

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

    # ── Pegel-Normalisierung: Median-dB ausgleichen ──────────────────────────
    # Unterschiedlich laut aufgenommene Mics verzerren alle Pegelvergleiche.
    # Korrektur auf Sample-Ebene, damit alle downstream Passes profitieren.
    _rms1 = compute_rms_db(audio_cam1, sr1, args.analysis_window)
    _rms2 = compute_rms_db(audio_cam2, sr1, args.analysis_window)
    _median1 = float(np.median(_rms1))
    _median2 = float(np.median(_rms2))
    _offset_db = (_median1 - _median2) / 2.0
    if abs(_offset_db) > 0.1:
        # dB → linearer Gain-Faktor, auf Samples anwenden
        _gain1 = 10 ** (-_offset_db / 20.0)
        _gain2 = 10 ** (+_offset_db / 20.0)
        audio_cam1 = (audio_cam1 * _gain1).astype(audio_cam1.dtype)
        audio_cam2 = (audio_cam2 * _gain2).astype(audio_cam2.dtype)
        print(f"\n🔊 Pegel-Normalisierung:")
        print(f"  Median vor Korrektur: MIC1={_median1:.1f} dB, MIC2={_median2:.1f} dB")
        print(f"  Korrektur: MIC1 {-_offset_db:+.1f} dB, MIC2 {+_offset_db:+.1f} dB")
        # Post-Normalisierung: RMS neu berechnen für Diagnostik
        _rms1_post = compute_rms_db(audio_cam1, sr1, args.analysis_window)
        _rms2_post = compute_rms_db(audio_cam2, sr1, args.analysis_window)
        _diff_post = _rms1_post[:min(len(_rms1_post), len(_rms2_post))] \
                   - _rms2_post[:min(len(_rms1_post), len(_rms2_post))]
        print(f"  Nach Korrektur: Median MIC1={float(np.median(_rms1_post)):.1f} dB, "
              f"MIC2={float(np.median(_rms2_post)):.1f} dB")
        _above = int(np.sum(np.abs(_diff_post) > args.threshold_db))
        _total = len(_diff_post)
        print(f"  Fenster über Schwelle ({args.threshold_db:.0f} dB): "
              f"{_above}/{_total} ({100*_above/_total:.0f}%)")
    else:
        print(f"\n🔊 Pegel-Check: MIC1={_median1:.1f} dB, MIC2={_median2:.1f} dB (kein Ausgleich nötig)")

    # ── Adaptive Silence-Schwelle (K-Means auf normalisiertem Original) ──
    # Pro Kanal, damit asymmetrische Aufnahmen (z.B. Mic weiter weg)
    # jeweils die passende Grenze zwischen Sprache und Stille haben.
    _th1 = _th2 = None   # K-Means-Rohwerte, fuer speaking_debug.json
    if args.pause_silence_db is not None:
        silence_db_cam1 = args.pause_silence_db
        silence_db_cam2 = args.pause_silence_db
        # Für On-Speaker-Pausen: gleicher Wert bei manuellem Override
        pause_db_cam1 = args.pause_silence_db
        pause_db_cam2 = args.pause_silence_db
        print(f"\n🔇 Silence-Schwelle: {args.pause_silence_db:.0f} dB (manuell, beide Kanäle)")
    else:
        from shared.audio_analysis import suggest_threshold_kmeans
        _th1 = suggest_threshold_kmeans(audio_cam1, sr1)
        _th2 = suggest_threshold_kmeans(audio_cam2, sr1)
        # threshold: Mitte zwischen Noise und Sprache → für echte Stille
        silence_db_cam1 = float(_th1['threshold'])
        silence_db_cam2 = float(_th2['threshold'])
        # Baseline-Freeze: quiet_speech + 3 dB Headroom.
        # quiet_speech ist die untere Grenze erkannter Sprache — alles
        # darunter ist "keine Sprache". +3 dB damit auch Momente knapp
        # unter der Sprachgrenze den Freeze auslösen.
        pause_db_cam1 = float(_th1['quiet_speech']) + 3
        pause_db_cam2 = float(_th2['quiet_speech']) + 3
        print(f"\n🔇 Adaptive Silence-Schwelle:")
        print(f"  MIC1: Stille={silence_db_cam1:.0f} dB, Pause={pause_db_cam1:.0f} dB [{_th1['confidence']}] "
              f"(Noise: {_th1['noise_floor']:.0f})")
        print(f"  MIC2: Stille={silence_db_cam2:.0f} dB, Pause={pause_db_cam2:.0f} dB [{_th2['confidence']}] "
              f"(Noise: {_th2['noise_floor']:.0f})")

    _analysis1, _analysis2 = audio_cam1, audio_cam2

    # ── Pegel-Normalisierung (RMS) ───────────────────────────────────────────
    # RMS statt Median, weil Energie-Mittel Bursts korrekt gewichtet —
    # relevant für Speaking-Reaction und Pause-Trimming downstream.
    _rms1_pg = compute_rms_db(_analysis1, sr1, args.analysis_window)
    _rms2_pg = compute_rms_db(_analysis2, sr1, args.analysis_window)
    _active1 = _rms1_pg
    _active2 = _rms2_pg
    # RMS in dB-Domain = 10*log10(mean(10^(dB/10)))  (Energie-Mittel)
    def _rms_mean_db(db_values):
        return float(10 * np.log10(np.mean(10 ** (db_values / 10)) + 1e-12))
    _rms1_pg_db = _rms_mean_db(_active1) if len(_active1) > 0 else _rms_mean_db(_rms1_pg)
    _rms2_pg_db = _rms_mean_db(_active2) if len(_active2) > 0 else _rms_mean_db(_rms2_pg)
    # Beide Kanäle auf gemeinsamen Ziel-RMS bringen (Mittelwert beider).
    # RMS statt Median gewichtet energiereiche Bursts korrekt.
    _target_pg = (_rms1_pg_db + _rms2_pg_db) / 2.0
    _gain1_pg = 10 ** ((_target_pg - _rms1_pg_db) / 20.0)
    _gain2_pg = 10 ** ((_target_pg - _rms2_pg_db) / 20.0)
    _analysis1 = (_analysis1 * _gain1_pg).astype(_analysis1.dtype)
    _analysis2 = (_analysis2 * _gain2_pg).astype(_analysis2.dtype)
    print(f"\n🔊 Pegel-Normalisierung (RMS):")
    print(f"  RMS: MIC1={_rms1_pg_db:.1f} dB, MIC2={_rms2_pg_db:.1f} dB → Ziel: {_target_pg:.1f} dB")
    print(f"  Korrektur: MIC1 {_target_pg - _rms1_pg_db:+.1f} dB, MIC2 {_target_pg - _rms2_pg_db:+.1f} dB")

    print(f"\n📊 RMS-Diarization (threshold={args.threshold_db:.1f} dB)...")
    segments = rms_diarize(
        _analysis1, _analysis2, sr1,
        args.analysis_window, args.threshold_db,
        args.change_delay, args.min_edit_duration,
        silence_gate_db=silence_db_cam1 - 15,
        silence_gate_db2=silence_db_cam2 - 15,
    )
    print(f"  {len(segments)} Segmente erkannt")

    # ── Degenerierte Diarisierung abfangen ────────────────────────────────────
    # EIN Segment ueber eine lange Aufnahme heisst: die beiden Seiten
    # unterscheiden sich praktisch nirgends um mehr als die Schwelle — wer wann
    # spricht, ist nicht bestimmbar. Frueher lief das weiter, alles galt als
    # Simultan-Sprechen, die EDL bestand nur aus der Totale und die Statistik
    # starb an einer Division durch Null (Realfall 22.07.: 131 min, 0 von
    # 156824 Fenstern ueber der Schwelle, Median beider Seiten ~-6 dB).
    if len(segments) <= 1 and duration_s > 300:
        _r1 = compute_rms_db(_analysis1, sr1, args.analysis_window)
        _r2 = compute_rms_db(_analysis2, sr1, args.analysis_window)
        _n = min(len(_r1), len(_r2))
        _above = int(np.sum(np.abs(_r1[:_n] - _r2[:_n]) > args.threshold_db))
        print("\n✗ Die Sprechererkennung findet keinen Unterschied zwischen den "
              "beiden Ton-Seiten.")
        print(f"  In {duration_s / 60:.1f} Minuten liegt der Pegelunterschied nur in "
              f"{_above} von {_n} Fenstern ueber {args.threshold_db:.0f} dB — zu "
              f"wenig, um zu bestimmen, wer wann spricht.")
        print("  Haeufigste Ursachen:")
        print("  - Die Spuren enthalten (fast) dasselbe Signal: z. B. wurde der MIX "
              "des Recorders exportiert statt der Einzelspuren.")
        print("  - Ein Limiter/AGC am Recorder hat die Pegelunterschiede eingeebnet.")
        print("  - Extremes Uebersprechen (Mikrofone sehr nah beieinander).")
        print("  Bitte die Spuren einzeln anhoeren (Play-Knopf im Schritt "
              "Personen): Ist auf jeder Spur wirklich die EIGENE Person deutlich "
              "lauter als alle anderen?")
        return 1

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
                _analysis1, _analysis2, sr1,
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


    # ── Uebergangsregel: Sprecherwechsel ueber die kleinste gemeinsame Cam ────
    # Bewusst HIER, auf der noch ruhigen Basis-EDL, und nicht am Ende der
    # Pipeline: hier hat die Bruecke Platz. Nach dem Einfuegen der Cutaways
    # muesste sie sich zwischen bereits dichte Schnitte draengeln.
    if args.transition_on_speaker_change and args.totale_clip and args.totale_video:
        import random as _rnd
        from shot_sizes import shot_level  # noqa: F401  (Doku: Leiter, s. Bildsprache.md)
        totale_ref2, _ = get_reference_frame(args.totale_video, args.fps)
        if totale_ref2 is not None:
            _tzv = 0 - (args.totale_edl_frame + _cam_shift)
            base_f = args.transition_min_shot
            rnd_f  = args.transition_randomness

            def _bridge_len():
                factor = 1.0 + _rnd.uniform(0.0, rnd_f) if rnd_f > 0 else 1.0
                return max(1, int(round(base_f * factor * args.fps)))

            # Heute genau eine Bruecke — der Resolver wird trotzdem je Uebergang
            # befragt, damit N-fache Diarisierung und mehrere gleich weite
            # Kameras spaeter ohne Umbau moeglich sind.
            def _resolve(_from_clip, _to_clip):
                return (args.totale_clip, totale_ref2, _tzv)

            print("\n🎬 Uebergangsregel (Sprecherwechsel)...")
            events = insert_transition_events(
                events, args.fps, _resolve, _bridge_len,
                int(args.transition_min_shot * args.fps),
                return_min_factor=args.transition_return_factor,
            )
        else:
            print("  ⚠ Uebergangsregel uebersprungen: kein Timecode auf der Bruecken-Kamera")

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
    # total kann 0 sein, wenn KEIN Event auf CAM1/CAM2 liegt (z. B. nur Totale
    # nach degenerierter Diarisierung) — frueher Division durch Null genau hier
    # (Realfall 22.07.: Spuren pegelidentisch, 1 Segment, alles Simultan).
    if total > 0:
        print(f"  {args.cam1_clip}: {cam1_s/60:.1f} min ({cam1_s/total*100:.0f}%)")
        print(f"  {args.cam2_clip}: {cam2_s/60:.1f} min ({cam2_s/total*100:.0f}%)")
    else:
        print(f"  ⚠ Kein Event auf {args.cam1_clip}/{args.cam2_clip} — "
              f"EDL besteht nur aus Totale/Bruecken.")

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
            Path(args.cam1_off_sections_out).write_text(json.dumps(cam1_off), encoding='utf-8')
            total_off_s = sum(e - s for s, e in cam1_off) / args.fps
            print(f"  CAM1 Off-Sektionen: {len(cam1_off)} Segmente ({total_off_s/60:.1f} min)")
        if args.cam2_off_sections_out:
            Path(args.cam2_off_sections_out).write_text(json.dumps(cam2_off), encoding='utf-8')
            total_off_s = sum(e - s for s, e in cam2_off) / args.fps
            print(f"  CAM2 Off-Sektionen: {len(cam2_off)} Segmente ({total_off_s/60:.1f} min)")

    # ── 6b. Pause-Detection (optional) ──────────────────────────────────────
    # Nur erkennen und als JSON speichern — Anwendung erfolgt später in
    # run_from_bin.py auf die finalen cut_events (nach Cutaway-Einfügung),
    # damit tzvf in add_reactions_to_edl.py korrekt bleibt.
    if args.pause_trim:
        from pause_trim_edl import detect_pauses, save_pauses
        pauses = detect_pauses(
            events, _analysis1, _analysis2, sr1,
            args.wav_edl_frame, args.fps,
            silence_db=silence_db_cam1,
            silence_db2=silence_db_cam2,
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
        # Original-Audio: Das On-Mic wird vom Gate nicht gedämpft,
        # daher korrekte Pausenerkennung auf dem Originalsignal.
        _on_pauses = detect_on_speaker_pauses(
            audio_cam1, audio_cam2, sr1, segments,
            silence_db=pause_db_cam1,
            silence_db2=pause_db_cam2,
            min_pause_s=args.speaking_mask_min_pause,
            padding_s=args.speaking_mask_padding,
        )

        # Debug-Dump: nur im Dev-Modus, wie Decision Log und Console-Capture
        _sp_debug = None
        try:
            from shared.dev_mode import is_dev_mode
            if is_dev_mode():
                _sp_debug = []
        except ImportError:
            pass

        _det1 = _det2 = None
        if args.speaking_detect_mic_cam1 and args.speaking_detect_mic_cam2:
            _det1, _ds1 = combine_audios(args.speaking_detect_mic_cam1)
            _det2, _ds2 = combine_audios(args.speaking_detect_mic_cam2)
            assert _ds1 == sr1 and _ds2 == sr1, "Analysespur: andere Abtastrate"
            def _fit(a):
                a = a[:n]
                return np.pad(a, (0, n - len(a))) if len(a) < n else a
            _det1, _det2 = _fit(_det1), _fit(_det2)
            # Dieselbe Pegelangleichung wie bei den Originalen
            if abs(_offset_db) > 0.1:
                _det1 = (_det1 * _gain1).astype(_det1.dtype)
                _det2 = (_det2 * _gain2).astype(_det2.dtype)
            print(f"  Mischform: Kandidatensuche auf Analysespuren "
                  f"{[Path(p).name for p in args.speaking_detect_mic_cam1 + args.speaking_detect_mic_cam2]}")

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
            debug_sink=_sp_debug,
            post_freeze_refractory_s=args.speaking_post_freeze_refractory,
            freeze_hold_max_s=args.speaking_freeze_hold_max,
            freeze_release_margin_db=args.speaking_freeze_release_margin,
            fp_filter=args.speaking_fp_filter,
            fp_corr_max=args.speaking_fp_corr,
            fp_on_rise_db=args.speaking_fp_on_rise,
            fp_takeover_s=args.speaking_fp_takeover,
            det_audio1=_det1, det_audio2=_det2,
        )
        print(f"  CAM1 Reactions: {len(cam1_sr)}, CAM2 Reactions: {len(cam2_sr)}")

        if _sp_debug is not None:
            # Kompakt schreiben: indent=2 wuerde jede einzelne Zahl auf eine
            # eigene Zeile legen und die Datei vervielfachen.
            _dbg_path = Path(args.output).with_name('speaking_debug.json')
            _dbg_path.write_text(json.dumps({
                'schema':        1,
                'fps':           args.fps,
                'window_s':      args.analysis_window,
                'wav_edl_frame': args.wav_edl_frame,
                'params': {
                    'rise_db':               args.speaking_rise_db,
                    'attack_window_s':       args.speaking_attack_window,
                    'release_window_s':      args.speaking_release_window,
                    'warmup_s':              args.speaking_warmup,
                    'min_duration_s':        args.speaking_min_duration,
                    'max_duration_s':        args.speaking_max_duration,
                    'mode':                  args.speaking_mode,
                    'mask_min_pause_s':      args.speaking_mask_min_pause,
                    'mask_padding_s':        args.speaking_mask_padding,
                    # Nicht per CLI setzbar, aber fuer die Deutung noetig:
                    'lookback_s':            1.0,
                    'sustain_margin_db':     1.5,
                    'decay_hold_s':          3.0,
                    'no_burst_decay_factor': 3.0,
                },
                'thresholds': {
                    'pause_db_cam1':   pause_db_cam1,
                    'pause_db_cam2':   pause_db_cam2,
                    'silence_db_cam1': silence_db_cam1,
                    'silence_db_cam2': silence_db_cam2,
                    'kmeans_cam1': ({'noise_floor': _th1['noise_floor'],
                                     'quiet_speech': _th1['quiet_speech'],
                                     'confidence': _th1['confidence']}
                                    if _th1 else None),
                    'kmeans_cam2': ({'noise_floor': _th2['noise_floor'],
                                     'quiet_speech': _th2['quiet_speech'],
                                     'confidence': _th2['confidence']}
                                    if _th2 else None),
                },
                'segments': _sp_debug,
            }, ensure_ascii=False), encoding='utf-8')
            _n_skip = sum(1 for s in _sp_debug if s.get('skipped'))
            _mb = _dbg_path.stat().st_size / 1e6
            print(f"  🔬 Debug-Dump: {_dbg_path.name} "
                  f"({len(_sp_debug)} Segmente, davon {_n_skip} uebersprungen, {_mb:.1f} MB)")
        if args.speaking_reactions_cam1_out:
            Path(args.speaking_reactions_cam1_out).write_text(
                json.dumps({'fps': args.fps, 'reactions': cam1_sr}, indent=2),
                encoding='utf-8',
            )
        if args.speaking_reactions_cam2_out:
            Path(args.speaking_reactions_cam2_out).write_text(
                json.dumps({'fps': args.fps, 'reactions': cam2_sr}, indent=2),
                encoding='utf-8',
            )

    # ── 9. Pause-Cutaway-Kandidaten exportieren (optional) ─────────────────
    if args.pause_cutaway_json_out:
        print(f"\n🔇 Erkenne Stille-Pausen für Cutaways (min {args.pause_cutaway_min_pause}s)...")
        # Cutaway-Schwelle strenger als Pause-Trimming (-10 dB Offset),
        # damit nur echte Stille Cutaways auslöst, keine leise Sprache.
        _window_s = 0.02
        _db1 = compute_rms_db(_analysis1, sr1, _window_s)
        _db2 = compute_rms_db(_analysis2, sr1, _window_s)
        _n = min(len(_db1), len(_db2))
        _db1, _db2 = _db1[:_n], _db2[:_n]
        _both_silent = (_db1 < silence_db_cam1 - 10) & (_db2 < silence_db_cam2 - 10)

        # Zusammenhängende Stille-Regionen finden
        _min_wins = max(1, int(args.pause_cutaway_min_pause / _window_s))
        _mutual_pauses = []
        _in_pause = False
        _ps = 0
        for i in range(_n):
            if _both_silent[i] and not _in_pause:
                _ps = i
                _in_pause = True
            elif not _both_silent[i] and _in_pause:
                if i - _ps >= _min_wins:
                    _mutual_pauses.append((_ps * _window_s, i * _window_s))
                _in_pause = False
        if _in_pause and _n - _ps >= _min_wins:
            _mutual_pauses.append((_ps * _window_s, _n * _window_s))

        # Sprecher vor der Pause bestimmen (aus Diarization-Segmenten)
        pause_list = []
        for ps_s, pe_s in _mutual_pauses:
            # Welcher Sprecher war VOR der Pause aktiv?
            spk = None
            for seg in segments:
                if seg['end_s'] >= ps_s - 0.5 and seg['start_s'] < ps_s:
                    spk = seg['speaker']
            if spk not in ('CAM1', 'CAM2'):
                continue
            sf = round(ps_s * args.fps) + args.wav_edl_frame
            ef = round(pe_s * args.fps) + args.wav_edl_frame
            if ef > sf:
                pause_list.append({
                    'start_frame': sf,
                    'end_frame': ef,
                    'speaker': spk,
                })
        pause_list.sort(key=lambda p: p['start_frame'])
        Path(args.pause_cutaway_json_out).write_text(
            json.dumps({'fps': args.fps, 'pauses': pause_list}, indent=2),
            encoding='utf-8',
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
