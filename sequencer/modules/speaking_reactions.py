"""Speaking-Reactions-Modul — Erkennt Sprech-Reaktionen auf dem Off-Mic."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.types import ReactionData

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules" / "multicam_cutter"))
from build_base_edl_from_audio import detect_on_speaker_pauses, compute_rms_db, combine_audios  # noqa: F401


# Aus build_base_edl_from_audio.py hierher verschoben (20.11.): der MultiCamCutter
# erkennt Einwürfe nur noch auf der Analysespur (einwurf_analysespur.py). Die alte
# Erkennung (wandernde Grundlinie + Regel A) nutzt nur noch der Sequencer.
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



class SpeakingReactionsModule(Module):
    name = "speaking_reactions"
    description = "Sprech-Reaktionen erkennen (Off-Mic Burst-Detection)"
    category = "analysis"

    inputs = ["audio.data", "diarization.segments", "frame_mapping"]
    outputs = ["reactions.speaking"]
    optional_inputs = ["audio.gated"]

    schema = {
        "expanders": [{
            "key": "speaking_reactions",
            "label": "Sprech-Reaktionen",
            "rows": [
                {
                    "columns": 1,
                    "params": [
                        {"name": "enabled", "widget": "toggle", "default": True,
                         "label": "Aktiviert", "column": 0},
                    ],
                },
                {
                    "columns": 3,
                    "params": [
                        {"name": "rise_db", "widget": "number_input", "default": 6.0,
                         "label": "Anstieg (dB)", "expert": True, "column": 0},
                        {"name": "min_duration", "widget": "number_input", "default": 0.20,
                         "label": "Min. Dauer (s)", "expert": True, "column": 1},
                        {"name": "max_duration", "widget": "number_input", "default": 2.5,
                         "label": "Max. Dauer (s)", "expert": True, "column": 2},
                    ],
                },
                {
                    "columns": 3,
                    "params": [
                        {"name": "attack_window", "widget": "number_input", "default": 0.2,
                         "label": "Attack (s)", "expert": True, "column": 0},
                        {"name": "release_window", "widget": "number_input", "default": 20.0,
                         "label": "Release (s)", "expert": True, "column": 1},
                        {"name": "warmup", "widget": "number_input", "default": 3.0,
                         "label": "Warmup (s)", "expert": True, "column": 2},
                    ],
                },
            ],
        }],
    }

    def skip_condition(self, ctx: PipelineContext, params: Dict[str, Any]) -> bool:
        return not params.get("enabled", True)

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        # Original-Audio fuer Baseline-Freeze-Pausen
        audio_data = ctx.get("audio.data")
        diarization = ctx.get("diarization.segments")
        frame_mapping = ctx.get("frame_mapping")

        cam_names = list(audio_data.audio.keys())
        if len(cam_names) > 2:
            raise NotImplementedError(
                f"Speaking-Reactions unterstuetzt aktuell nur 2 Quellen, "
                f"erhalten: {cam_names}. N-Kanal-Analyse ist geplant."
            )
        audio1 = audio_data.audio[cam_names[0]]
        audio2 = audio_data.audio[cam_names[1]]
        sr = audio_data.sr
        fps = frame_mapping.fps

        segments = diarization.segments

        # Analyse-Audio (gated wenn vorhanden, sonst Original)
        if ctx.has("audio.gated"):
            analysis = ctx.get("audio.gated")
            a1_analysis = analysis.audio[cam_names[0]]
            a2_analysis = analysis.audio[cam_names[1]]
        else:
            a1_analysis = audio1
            a2_analysis = audio2

        # Pausen erkennen (fuer Baseline-Freeze)
        on_pauses = detect_on_speaker_pauses(
            audio1, audio2, sr, segments,
        )

        # Timeline-Koordinaten
        tzvf = frame_mapping.timeline_zero_video_frames
        cam1_tzvf = tzvf.get(cam_names[0], 0)
        cam2_tzvf = tzvf.get(cam_names[1], 0)

        # wav_edl_frame: Offset des Audio-Starts im EDL-Koordinatensystem
        # Im aktuellen Code aus dem CLI-Argument, hier aus dem Sync-Offset ableitbar
        wav_edl_frame = params.get("wav_edl_frame", 0)

        cam1_reactions, cam2_reactions = detect_speaking_reactions(
            a1_analysis, a2_analysis, sr, segments,
            fps=fps,
            wav_edl_frame=wav_edl_frame,
            cam1_timeline_zero_video=cam1_tzvf,
            cam2_timeline_zero_video=cam2_tzvf,
            window_s=params.get("analysis_window", 0.05),
            rise_db=params.get("rise_db", 6.0),
            min_duration_s=params.get("min_duration", 0.20),
            max_duration_s=params.get("max_duration", 2.5),
            attack_window_s=params.get("attack_window", 0.2),
            release_window_s=params.get("release_window", 20.0),
            warmup_s=params.get("warmup", 3.0),
            on_pauses=on_pauses,
        )

        print(f"  {cam_names[0]}: {len(cam1_reactions)} Reaktionen")
        print(f"  {cam_names[1]}: {len(cam2_reactions)} Reaktionen")

        ctx.set("reactions.speaking", {
            cam_names[0]: ReactionData(
                cam_name=cam_names[0], reactions=cam1_reactions, fps=fps,
            ),
            cam_names[1]: ReactionData(
                cam_name=cam_names[1], reactions=cam2_reactions, fps=fps,
            ),
        })
