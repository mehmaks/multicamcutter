"""
Pause Trimming für EDL-Events.

Zwei Phasen:
1. detect_pauses() — Erkennt Sprechpausen an Diarization-Grenzen (braucht Audio).
   Wird in build_base_edl_from_audio.py aufgerufen, Ergebnis als JSON gespeichert.
2. apply_pauses_to_cut_events() — Kürzt Pausen in frame-basierten cut_events.
   Wird in run_from_bin.py nach parse_edl aufgerufen (nach Cutaway-Einfügung).
"""

import json
import random
import numpy as np
from pathlib import Path

try:
    from .build_base_edl_from_audio import compute_rms_db, timecode_to_frames, frames_to_timecode
except ImportError:
    from build_base_edl_from_audio import compute_rms_db, timecode_to_frames, frames_to_timecode


def detect_pause_at_boundary(audio1: np.ndarray, audio2: np.ndarray, sr: int,
                              boundary_s: float,
                              search_radius_s: float = 3.0,
                              silence_db: float = -40.0,
                              window_s: float = 0.02,
                              min_pause_s: float = 0.3):
    """
    Sucht eine Sprechpause rund um eine Diarization-Grenze.

    Analysiert beide MIC-Signale: Pause = beide unter silence_db.

    Returns:
        dict {pause_start_s, pause_end_s, pause_dur_s, boundary_s}
        oder None
    """
    search_start_s = max(0, boundary_s - search_radius_s)
    search_end_s = boundary_s + search_radius_s

    s1 = max(0, int(search_start_s * sr))
    e1 = min(len(audio1), int(search_end_s * sr))
    s2 = max(0, int(search_start_s * sr))
    e2 = min(len(audio2), int(search_end_s * sr))

    if e1 - s1 < sr * window_s or e2 - s2 < sr * window_s:
        return None

    db1 = compute_rms_db(audio1[s1:e1], sr, window_s)
    db2 = compute_rms_db(audio2[s2:e2], sr, window_s)

    n = min(len(db1), len(db2))
    if n == 0:
        return None
    db1, db2 = db1[:n], db2[:n]

    both_silent = (db1 < silence_db) & (db2 < silence_db)

    pauses = []
    in_pause = False
    pause_start = 0

    for i in range(n):
        if both_silent[i] and not in_pause:
            pause_start = i
            in_pause = True
        elif not both_silent[i] and in_pause:
            dur = (i - pause_start) * window_s
            if dur >= min_pause_s:
                pauses.append((pause_start, i, dur))
            in_pause = False

    if in_pause:
        dur = (n - pause_start) * window_s
        if dur >= min_pause_s:
            pauses.append((pause_start, n, dur))

    if not pauses:
        return None

    boundary_window = int((boundary_s - search_start_s) / window_s)
    best = None
    best_dist = float('inf')

    for p_start, p_end, dur in pauses:
        p_center = (p_start + p_end) / 2
        dist = abs(p_center - boundary_window)
        if dist < best_dist:
            best_dist = dist
            best = (p_start, p_end, dur)

    if best is None:
        return None

    p_start, p_end, dur = best
    pause_start_s = search_start_s + p_start * window_s
    pause_end_s = search_start_s + p_end * window_s

    return {
        'pause_start_s': pause_start_s,
        'pause_end_s': pause_end_s,
        'pause_dur_s': dur,
        'boundary_s': boundary_s,
    }


# ── Phase 1: Detection ──────────────────────────────────────────────────────

def detect_pauses(events: list, audio1: np.ndarray, audio2: np.ndarray,
                  sr: int, wav_edl_frame: int, fps: float,
                  silence_db: float = -40.0,
                  search_radius_s: float = 3.0,
                  min_pause_s: float = 0.3) -> list:
    """
    Erkennt Sprechpausen an Diarization-Grenzen.

    Args:
        events: EDL-Event-Dicts (clip_name, record_out als TC)
        audio1, audio2: MIC-Audio-Arrays
        sr: Sample-Rate
        wav_edl_frame: EDL-Frame bei dem Audio Frame 0 liegt
        fps: Timeline-Framerate
        silence_db: dB-Schwelle für Stille
        search_radius_s: Suchradius um jede Grenze
        min_pause_s: Mindest-Pausendauer für Erkennung

    Returns:
        Liste von Pause-Dicts:
        [{'pause_start_frame': int, 'pause_end_frame': int,
          'boundary_frame': int, 'pause_dur_s': float}]
    """
    if len(events) < 2:
        return []

    pauses = []
    for i in range(len(events) - 1):
        ev_a = events[i]
        ev_b = events[i + 1]
        if ev_a['clip_name'] != ev_b['clip_name']:
            boundary_frame = timecode_to_frames(ev_a['record_out'], fps)
            boundary_audio_s = (boundary_frame - wav_edl_frame) / fps
            if boundary_audio_s > 0:
                pause = detect_pause_at_boundary(
                    audio1, audio2, sr, boundary_audio_s,
                    search_radius_s=search_radius_s,
                    silence_db=silence_db,
                    min_pause_s=min_pause_s,
                )
                if pause:
                    pause_start_frame = round(pause['pause_start_s'] * fps) + wav_edl_frame
                    pause_end_frame = round(pause['pause_end_s'] * fps) + wav_edl_frame
                    pauses.append({
                        'pause_start_frame': pause_start_frame,
                        'pause_end_frame': pause_end_frame,
                        'boundary_frame': boundary_frame,
                        'pause_dur_s': pause['pause_dur_s'],
                    })

    # Überlappende Pausen deduplizieren
    if len(pauses) > 1:
        deduped = [pauses[0]]
        for p in pauses[1:]:
            if p['pause_start_frame'] < deduped[-1]['pause_end_frame']:
                continue
            deduped.append(p)
        pauses = deduped

    if pauses:
        print(f"\n🔍 Pause-Detection: {len(pauses)} Pausen gefunden")
        for p in pauses:
            print(f"    Boundary {p['boundary_frame']}: "
                  f"{p['pause_start_frame']}–{p['pause_end_frame']} "
                  f"({p['pause_dur_s']:.2f}s)")

    return pauses


def save_pauses(pauses: list, output_path: str):
    """Speichert Pause-Daten als JSON."""
    Path(output_path).write_text(json.dumps(pauses, indent=2))
    print(f"  Pause-Daten: {output_path}")


def load_pauses(path: str) -> list:
    """Lädt Pause-Daten aus JSON."""
    return json.loads(Path(path).read_text())


# ── Phase 2: Application ────────────────────────────────────────────────────

def apply_pauses_to_cut_events(cut_events: list, pauses: list, fps: float,
                                max_pause_s: float = 1.0,
                                cut_mode: str = 'middle'):
    """
    Kürzt überlange Pausen in frame-basierten cut_events.

    Ansatz (wie Sandbox): Für jede Pause wird das Event VOR der Grenze
    am Ende gekürzt und das Event NACH der Grenze am Anfang gekürzt.
    Der Sprecherwechsel-Schnitt wird dadurch VERSCHOBEN, nicht dupliziert.

    Args:
        cut_events: Liste von Dicts mit clip, source_in, source_out,
                    record_in, record_out, reason
        pauses: Liste aus detect_pauses / load_pauses
        fps: Framerate
        max_pause_s: Max. erlaubte Pausendauer
        cut_mode: Video-Schnittmodus (l-cut, middle, j-cut)

    Returns:
        (modified_cut_events, audio_keeps)
        audio_keeps: Liste von (orig_start_frame, orig_end_frame, new_record_frame)
                     für segmentierte MIC-Platzierung
    """
    if not pauses or not cut_events:
        return cut_events, None

    max_pause_frames = int(max_pause_s * fps)
    snap_frames = int(0.2 * fps)

    # Clip-Grenzen in den finalen cut_events ermitteln.
    # boundary_frame muss einer echten Clip-Grenze entsprechen (± Toleranz).
    boundary_tolerance = snap_frames
    clip_boundaries = set()
    for i in range(len(cut_events) - 1):
        ev_a = cut_events[i]
        ev_b = cut_events[i + 1]
        if ev_a.get('clip') is not ev_b.get('clip'):
            clip_boundaries.add(ev_a['record_out'])

    def find_boundary(boundary_frame):
        for cb in clip_boundaries:
            if abs(boundary_frame - cb) <= boundary_tolerance:
                return cb
        return None

    # Original-Span merken für Audio-Keeps
    orig_start = cut_events[0]['record_in']
    orig_end = cut_events[-1]['record_out']

    # Cutaway-Spans sammeln (alles außer 'speaker')
    cutaway_spans = [(ev['record_in'], ev['record_out'])
                     for ev in cut_events
                     if ev.get('reason', 'speaker') != 'speaker']

    # ── Pausen verarbeiten (Sandbox-Ansatz) ─────────────────────────────
    audio_trims = []
    trimmed_count = 0
    total_saved_frames = 0
    skipped_no_boundary = 0
    skipped_cutaway = 0

    for p in pauses:
        ps = p['pause_start_frame']
        pe = p['pause_end_frame']
        boundary = p['boundary_frame']

        # 1. Grenze muss noch existieren
        matched_cb = find_boundary(boundary)
        if matched_cb is None:
            skipped_no_boundary += 1
            continue

        # Snap: Pause bis zur Grenze erweitern wenn knapp daneben
        if matched_cb > pe and (matched_cb - pe) <= snap_frames:
            pe = matched_cb
        if matched_cb < ps and (ps - matched_cb) <= snap_frames:
            ps = matched_cb

        dur = pe - ps
        excess = dur - max_pause_frames
        if excess <= 0:
            continue

        # 2. Neue Schnittpositionen berechnen (wie Sandbox)
        half = max_pause_frames // 2
        half2 = max_pause_frames - half

        mode = random.choice(['middle', 'l-cut', 'j-cut']) if cut_mode == 'random' else cut_mode

        if mode == 'l-cut':
            p1_end = ps                       # Clip 1 endet am Pausenanfang
            p2_start = pe - max_pause_frames  # Clip 2 startet so dass max_pause bleibt
        elif mode == 'j-cut':
            p1_end = ps + max_pause_frames    # Clip 1 behält max_pause Stille
            p2_start = pe                     # Clip 2 startet am Pausenende
        else:  # middle
            p1_end = ps + half                # Symmetrisch um Pausenmitte
            p2_start = pe - half2

        # 3. Cutaway-Schutz: Trim-Region = p1_end bis p2_start
        overlaps_cutaway = any(
            cs < p2_start and ce > p1_end for cs, ce in cutaway_spans
        )
        if overlaps_cutaway:
            skipped_cutaway += 1
            continue

        # 4. Event VOR der Grenze kürzen (Ende → p1_end)
        #    Wie Sandbox: bedingungslos verschieben. Wenn Grenze vor p1_end,
        #    wird das Event verlängert (in Stillebereich hinein). Netto-Trim
        #    beider Seiten = excess, garantiert Audio-Sync.
        actual_trim_before = 0
        for ev in cut_events:
            if abs(ev['record_out'] - matched_cb) <= boundary_tolerance:
                trim = ev['record_out'] - p1_end
                # Cap: Event darf nicht negativ werden
                max_trim = ev['source_out'] - ev['source_in']
                if trim > max_trim:
                    trim = max_trim
                ev['source_out'] -= trim
                ev['record_out'] -= trim
                actual_trim_before = trim
                break

        # 5. Event NACH der Grenze kürzen (Anfang → p2_start)
        actual_trim_after = 0
        for ev in cut_events:
            if abs(ev['record_in'] - matched_cb) <= boundary_tolerance:
                delta = p2_start - ev['record_in']
                # Cap: Event darf nicht negativ werden
                max_delta = ev['source_out'] - ev['source_in']
                if delta > max_delta:
                    delta = max_delta
                ev['source_in'] += delta
                ev['record_in'] += delta
                actual_trim_after = delta
                break

        # Audio-Trim = tatsächlich entfernte Frames (symmetrisch um Pausenmitte)
        actual_total = actual_trim_before + actual_trim_after
        if actual_total > 0:
            at_half = actual_total // 2
            at_half2 = actual_total - at_half
            pause_center = (ps + pe) // 2
            at_start = pause_center - at_half2
            at_end = pause_center + at_half
            audio_trims.append((at_start, at_end))

        if actual_total > 0:
            trimmed_count += 1
            total_saved_frames += actual_total

    # Leere Events entfernen
    cut_events = [ev for ev in cut_events if ev['source_out'] > ev['source_in']]

    # Record-Positionen kompaktieren (lückenlos)
    cursor = 0
    for ev in cut_events:
        dur = ev['source_out'] - ev['source_in']
        ev['record_in'] = cursor
        ev['record_out'] = cursor + dur
        cursor += dur

    # Audio-Keeps berechnen (aus Audio-Trim-Regionen)
    audio_keeps = []
    if audio_trims:
        pos = orig_start
        rec_cursor = 0
        for at_start, at_end in sorted(audio_trims):
            if pos < at_start:
                audio_keeps.append((pos, at_start, rec_cursor))
                rec_cursor += at_start - pos
            pos = at_end
        if pos < orig_end:
            audio_keeps.append((pos, orig_end, rec_cursor))

    # Statistik
    if skipped_no_boundary:
        print(f"  ⏭️  {skipped_no_boundary} Pausen übersprungen "
              f"(Grenze nicht mehr in finaler EDL)")
    if skipped_cutaway:
        print(f"  ⚠️  {skipped_cutaway} Pausen übersprungen (Cutaway im Bereich)")

    if trimmed_count:
        print(f"\n✂️  Pause-Trim ({cut_mode}):")
        print(f"  {trimmed_count} Pausen getrimmt, "
              f"{total_saved_frames / fps:.1f}s eingespart")

    # Sync-Verifikation
    video_total = sum(ev['source_out'] - ev['source_in'] for ev in cut_events)
    audio_total = sum(ke - ks for ks, ke, _ in audio_keeps) if audio_keeps else 0
    print(f"\n  SYNC-CHECK: Video={video_total} Frames, Audio={audio_total} Frames, "
          f"Diff={video_total - audio_total}")
    if audio_keeps:
        print(f"    Audio-Keeps: {len(audio_keeps)} Segmente")
        for i, (ks, ke, rec) in enumerate(audio_keeps[:5]):
            print(f"      [{i}] orig {ks}-{ke} ({ke-ks}fr) → rec {rec}")
        if len(audio_keeps) > 5:
            print(f"      ... ({len(audio_keeps) - 5} weitere)")

    if not audio_keeps:
        return cut_events, None
    return cut_events, audio_keeps
