"""
Regressions- und Verhaltenstests fuer die RMS-Diarisierung.

Traegt den Umbau von binaer (2 Cams) auf N-fach (rms_diarize_n): Der wichtigste
Test beweist, dass der N=2-Shim `rms_diarize` byte-identisch zur FRUEHEREN
binaeren Logik bleibt. Dafuer liegt hier eine woertliche Kopie der alten
Implementierung (`_rms_diarize_old`) als Referenz — sie darf NICHT veraendert
werden, sie ist der eingefrorene Vergleichsstand.

Aufruf:  python3 modules/multicam_cutter/test_diarize.py
oder:    pytest modules/multicam_cutter/test_diarize.py
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from multicam_cutter.build_base_edl_from_audio import (  # noqa: E402
    compute_rms_db, rms_diarize, rms_diarize_n, build_base_edl_n,
)


# ── Eingefrorene Referenz: die alte binaere rms_diarize, WOERTLICH ──────────────
def _rms_diarize_old(audio1, audio2, sr, window_s, threshold_db,
                     change_delay_s, min_edit_s,
                     silence_gate_db=-55.0, silence_gate_db2=None):
    if silence_gate_db2 is None:
        silence_gate_db2 = silence_gate_db
    rms1 = compute_rms_db(audio1, sr, window_s)
    rms2 = compute_rms_db(audio2, sr, window_s)
    n = min(len(rms1), len(rms2))
    rms1, rms2 = rms1[:n], rms2[:n]

    diff = rms1 - rms2
    dominant = np.full(n, None, dtype=object)
    dominant[diff > threshold_db] = 'CAM1'
    dominant[diff < -threshold_db] = 'CAM2'
    both_quiet = (rms1 < silence_gate_db) & (rms2 < silence_gate_db2)
    dominant[both_quiet] = None

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

    segments, seg_start, seg_spk = [], 0, smoothed[0]
    for i in range(1, n):
        if smoothed[i] != seg_spk:
            segments.append({'speaker': seg_spk, 'start': seg_start, 'end': i})
            seg_start, seg_spk = i, smoothed[i]
    segments.append({'speaker': seg_spk, 'start': seg_start, 'end': n})

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

    for i, seg in enumerate(segments):
        if seg['speaker'] is None:
            seg['speaker'] = segments[i-1]['speaker'] if i > 0 else \
                             (segments[i+1]['speaker'] if i < len(segments)-1 else 'CAM1')

    final = []
    for seg in segments:
        s_s = seg['start'] * window_s
        e_s = seg['end'] * window_s
        if final and final[-1]['speaker'] == seg['speaker']:
            final[-1]['end_s'] = e_s
        else:
            final.append({'speaker': seg['speaker'], 'start_s': s_s, 'end_s': e_s})
    return final


# ── Signalgenerator: Rauschen, blockweise moduliert (erzeugt Wechsel + Stille) ──
def _gen(n_samples, sr, rng, seg_len_s=1.5,
         levels=(0.0, 0.002, 0.02, 0.1, 0.4, 1.0)):
    audio = rng.standard_normal(n_samples).astype(np.float32)
    seg = int(seg_len_s * sr)
    for start in range(0, n_samples, seg):
        audio[start:start + seg] *= float(rng.choice(levels))
    return audio


# ── Test 1: N=2-Shim byte-identisch zur eingefrorenen Referenz ─────────────────
def test_shim_matches_old_binary():
    sr = 8000
    mismatches = 0
    for seed in range(80):
        rng = np.random.default_rng(seed)
        dur = int(rng.integers(30, 90))            # 30–90 s
        a1 = _gen(dur * sr, sr, rng)
        a2 = _gen(dur * sr, sr, rng)
        window_s   = float(rng.choice([0.05, 0.1, 0.2]))
        threshold  = float(rng.choice([3.0, 6.0, 10.0]))
        change_del = float(rng.choice([0.0, 0.2, 0.5]))
        min_edit   = float(rng.choice([0.3, 0.8, 1.5]))
        g1 = float(rng.choice([-55.0, -50.0, -45.0]))
        g2 = None if rng.random() < 0.4 else float(rng.choice([-55.0, -50.0, -45.0]))

        old = _rms_diarize_old(a1, a2, sr, window_s, threshold, change_del, min_edit, g1, g2)
        new = rms_diarize(a1, a2, sr, window_s, threshold, change_del, min_edit, g1, g2)
        if old != new:
            mismatches += 1
            print(f"  ✗ seed {seed}: {len(old)} vs {len(new)} Segmente")
    assert mismatches == 0, f"{mismatches} Abweichungen zwischen alt und Shim"


# ── Test 2: N=3 — jeder Sprecher wird seiner Kamera zugeordnet ──────────────────
def test_three_speakers_each_attributed():
    sr = 8000
    win = 0.1
    n = 90 * sr
    silence = np.full(n, 0.001, dtype=np.float32)   # Grundrauschen unter Gate

    def loud(block_start_s, block_len_s):
        a = silence.copy()
        s = int(block_start_s * sr)
        e = int((block_start_s + block_len_s) * sr)
        a[s:e] = np.random.default_rng(0).standard_normal(e - s).astype(np.float32)
        return a

    # Person k spricht in Sekunde [k*20, k*20+15]
    a1 = loud(0, 15)
    a2 = loud(20, 15)
    a3 = loud(40, 15)
    segs = rms_diarize_n([a1, a2, a3], sr, win, threshold_db=6.0,
                         change_delay_s=0.3, min_edit_s=0.8,
                         labels=['CAM1', 'CAM2', 'CAM3'],
                         silence_gates_db=[-55.0, -55.0, -55.0])

    def speaker_at(t):
        for s in segs:
            if s['start_s'] <= t < s['end_s']:
                return s['speaker']
        return None

    assert speaker_at(7) == 'CAM1', f"bei 7s erwartet CAM1, bekam {speaker_at(7)}"
    assert speaker_at(27) == 'CAM2', f"bei 27s erwartet CAM2, bekam {speaker_at(27)}"
    assert speaker_at(47) == 'CAM3', f"bei 47s erwartet CAM3, bekam {speaker_at(47)}"
    labels_seen = {s['speaker'] for s in segs}
    assert 'CAM3' in labels_seen, "CAM3 kommt im Schnitt gar nicht vor — das war der Bug"


# ── Test 3: klarer Vorsprung entscheidet, knapper Gleichstand → kein Wechsel ────
def test_margin_gate_blocks_ambiguous():
    sr = 8000
    win = 0.1
    n = 40 * sr
    rng = np.random.default_rng(1)
    base = rng.standard_normal(n).astype(np.float32)
    # Zwei fast gleiche Pegel (Differenz < threshold) → keine klare Dominanz,
    # Default-Label bleibt (labels[0]); keine wilden Wechsel.
    a1 = base * 0.5
    a2 = base * 0.48
    segs = rms_diarize_n([a1, a2], sr, win, threshold_db=6.0,
                         change_delay_s=0.3, min_edit_s=0.8,
                         labels=['CAM1', 'CAM2'],
                         silence_gates_db=[-55.0, -55.0])
    assert all(s['speaker'] == 'CAM1' for s in segs), \
        "knapper Gleichstand haette nicht zu CAM2-Wechseln fuehren duerfen"


# ── Test 4: N-Basis-EDL routet jede Person auf ihre ENGSTE Kamera ──────────────
def test_n_base_edl_routes_to_tightest_camera():
    """Setup des Kollegen: Totale (3 Pers.), B-Cam (2 Pers.), C-Cam (1 Pers.).
    Person 3 ist nur auf der Totale → muss dort landen (heute waere sie stumm)."""
    sr = 8000
    p1, p2, p3 = 'mic1.wav', 'mic2.wav', 'mic3.wav'
    cameras = [
        {'name': 'A', 'clip': 'A', 'mics': [p1, p2, p3], 'edl_frame': 0, 'ref': 1000},  # Totale
        {'name': 'B', 'clip': 'B', 'mics': [p1, p2],      'edl_frame': 0, 'ref': 2000},
        {'name': 'C', 'clip': 'C', 'mics': [p1],          'edl_frame': 0, 'ref': 3000},
    ]

    dur = 45
    rng = np.random.default_rng(0)

    def track(loud_from, loud_to):
        a = np.full(dur * sr, 0.001, dtype=np.float32)   # Grundrauschen unter Gate
        s, e = loud_from * sr, loud_to * sr
        a[s:e] = rng.standard_normal(e - s).astype(np.float32)
        return a

    person_audios = {p1: track(0, 10), p2: track(15, 25), p3: track(30, 40)}
    gates = {p1: -55.0, p2: -55.0, p3: -55.0}

    events = build_base_edl_n(cameras, person_audios, sr, fps=25.0, wav_edl_frame=0,
                              window_s=0.1, threshold_db=6.0, change_delay_s=0.3,
                              min_edit_s=0.8, silence_gates_db=gates)

    clips = [e['clip_name'] for e in events]
    assert clips == ['C', 'B', 'A'], \
        f"erwartet [C, B, A] (Person1→C, Person2→B, Person3→Totale A), bekam {clips}"


# ── Test 5: Simultan-Sprechen → kleinste gemeinsame Kamera (P2) ────────────────
def test_n_simultaneous_speech_cuts_to_common_camera():
    from multicam_cutter.build_base_edl_from_audio import (
        detect_simultaneous_speech_n, insert_totale_events_n, timecode_to_frames,
    )
    sr = 8000
    p1, p2, p3 = 'mic1.wav', 'mic2.wav', 'mic3.wav'
    cameras = [
        {'name': 'A', 'clip': 'A', 'mics': [p1, p2, p3], 'edl_frame': 0, 'ref': 1000},
        {'name': 'B', 'clip': 'B', 'mics': [p1, p2],      'edl_frame': 0, 'ref': 2000},
        {'name': 'C', 'clip': 'C', 'mics': [p1],          'edl_frame': 0, 'ref': 3000},
    ]
    dur = 36
    rng = np.random.default_rng(2)
    a1 = np.full(dur * sr, 0.001, dtype=np.float32)
    a2 = np.full(dur * sr, 0.001, dtype=np.float32)
    a3 = np.full(dur * sr, 0.001, dtype=np.float32)
    a1[0:8 * sr] = rng.standard_normal(8 * sr).astype(np.float32)     # p1 solo
    sim = rng.standard_normal(8 * sr).astype(np.float32)             # p1+p2 gleich
    a1[12 * sr:20 * sr] = sim
    a2[12 * sr:20 * sr] = sim
    a3[26 * sr:32 * sr] = rng.standard_normal(6 * sr).astype(np.float32)  # p3 solo
    person_audio = {p1: a1, p2: a2, p3: a3}
    persons = [p1, p2, p3]

    simul = detect_simultaneous_speech_n(person_audio, persons, sr, 0.1, 6.0, 3.0)
    assert len(simul) == 1, f"erwartet 1 Simul-Region, bekam {len(simul)}"
    assert set(simul[0]['persons']) == {p1, p2}, \
        f"beteiligte Personen {simul[0]['persons']} (erwartet p1, p2)"

    base = build_base_edl_n(cameras, person_audio, sr, 25.0, 0, 0.1, 6.0, 0.3, 0.8,
                            {p1: -55.0, p2: -55.0, p3: -55.0})
    events = insert_totale_events_n(base, simul, cameras, 25.0, 0, cam_shift=0)

    def clip_at(t):
        f = round(t * 25)
        for e in events:
            if timecode_to_frames(e['record_in'], 25) <= f < timecode_to_frames(e['record_out'], 25):
                return e['clip_name']
        return None

    assert clip_at(16) == 'B', f"waehrend Simul p1+p2 erwartet B, bekam {clip_at(16)}"
    assert clip_at(4) == 'C',  f"p1 solo erwartet C, bekam {clip_at(4)}"
    assert clip_at(28) == 'A', f"p3 solo erwartet A (Totale), bekam {clip_at(28)}"


# ── Test 6: Reset-Kamera = breiteste (P3a, byte-identisch im 2er-Fall) ─────────
def test_pick_widest_reset_camera():
    from multicam_cutter.add_reactions_to_edl import _pick_widest
    # Totale (3 Personen) gewinnt als Reset, auch wenn sie nicht zuerst steht.
    cams = [
        {'name': 'C', 'mics': ['p1']},
        {'name': 'A', 'mics': ['p1', 'p2', 'p3']},
        {'name': 'B', 'mics': ['p1', 'p2']},
    ]
    assert _pick_widest(cams)['name'] == 'A', "breiteste Kamera muss gewinnen"
    # Gleichstand → erste (entspricht dem alten close_cams[0] im 2-Close-Fall).
    tie = [{'name': 'X', 'mics': ['p1']}, {'name': 'Y', 'mics': ['p2']}]
    assert _pick_widest(tie)['name'] == 'X', "Gleichstand → erste (byte-identisch)"
    assert _pick_widest([]) is None


# ── Test 7: Multi-Person-Reaktion → kleinste gemeinsame Kamera (P3b) ───────────
def test_multi_person_offcam_smallest_containing():
    from multicam_cutter.add_reactions_to_edl import _pick_multi_person_offcam
    A = {'name': 'A', 'mics': ['p1', 'p2', 'p3']}   # Totale
    B = {'name': 'B', 'mics': ['p1', 'p2']}
    C = {'name': 'C', 'mics': ['p1']}
    cutaway = [A, B, C]

    # p1 (auf C) und p2 (auf B) reagieren → kleinste Kamera mit beiden = B
    assert _pick_multi_person_offcam([C, B], cutaway, wide_cams=[])['name'] == 'B'
    # alle drei reagieren → Totale A
    assert _pick_multi_person_offcam([A, B, C], cutaway, wide_cams=[])['name'] == 'A'

    # Binaerer Fallback: keine gemeinsame Kamera, aber feste Totale (ohne Mics).
    close_only = [{'name': 'X', 'mics': ['p1']}, {'name': 'Y', 'mics': ['p2']}]
    totale = {'name': 'T', 'mics': []}
    assert _pick_multi_person_offcam(close_only, close_only,
                                     wide_cams=[totale])['name'] == 'T'
    # Keine gemeinsame Kamera, keine Totale → None (bleibt Einzel-Cutaway).
    assert _pick_multi_person_offcam(close_only, close_only, wide_cams=[]) is None


# ── Test 8: Off-Sektionen für N — Kamera off = nicht die On-Kamera (P3c) ───────
def test_off_sections_n():
    from multicam_cutter.build_base_edl_from_audio import (
        compute_off_sections_n, frames_to_timecode,
    )

    def ev(clip, s, e):
        return {'clip_name': clip,
                'record_in':  frames_to_timecode(s, 25),
                'record_out': frames_to_timecode(e, 25)}

    events = [ev('C', 0, 100), ev('B', 100, 200), ev('A', 200, 300)]
    cams = [{'clip': 'A', 'edl_frame': 0},
            {'clip': 'B', 'edl_frame': 0},
            {'clip': 'C', 'edl_frame': 0}]
    off = compute_off_sections_n(events, cams, cam_shift=0, fps=25)
    assert off['A'] == [[0, 100], [100, 200]], off['A']    # A off ausser bei sich
    assert off['B'] == [[0, 100], [200, 300]], off['B']
    assert off['C'] == [[100, 200], [200, 300]], off['C']

    # Mit edl_frame-Versatz: C startet 50 Frames spaeter → Video-Frames verschoben.
    cams2 = [{'clip': 'A', 'edl_frame': 0},
             {'clip': 'B', 'edl_frame': 0},
             {'clip': 'C', 'edl_frame': 50}]
    off2 = compute_off_sections_n(events, cams2, cam_shift=0, fps=25)
    assert off2['C'] == [[50, 150], [150, 250]], off2['C']


# ── Test 9: Bildsprache-Uebergang brueckt ueber die gemeinsame Kamera (P4) ─────
def test_n_transition_bridges_via_common_camera():
    from multicam_cutter.build_base_edl_from_audio import (
        insert_transition_events, frames_to_timecode,
    )
    from shot_sizes import smallest_containing
    cameras = [
        {'clip': 'T', 'mics': ['p1', 'p2'], 'edl_frame': 0, 'ref': 3000},  # Totale
        {'clip': 'X', 'mics': ['p1'],       'edl_frame': 0, 'ref': 1000},
        {'clip': 'Y', 'mics': ['p2'],       'edl_frame': 0, 'ref': 2000},
    ]
    persons_by_clip = {c['clip']: c['mics'] for c in cameras}
    ref_by_clip = {c['clip']: c['ref'] for c in cameras}
    tzv_by_clip = {c['clip']: -c['edl_frame'] for c in cameras}

    def resolve(fr, to):
        ppl = sorted(set(persons_by_clip.get(fr, [])) | set(persons_by_clip.get(to, [])))
        cam = smallest_containing(cameras, ppl) if ppl else None
        return (cam['clip'], ref_by_clip[cam['clip']], tzv_by_clip[cam['clip']]) if cam else None

    def ev(clip, s, e):
        return {'clip_name': clip,
                'source_in':  frames_to_timecode(s, 25),
                'source_out': frames_to_timecode(e, 25),
                'record_in':  frames_to_timecode(s, 25),
                'record_out': frames_to_timecode(e, 25)}

    # Sprecherwechsel X (p1) → Y (p2), Y lang genug fuer die Bruecke.
    events = [ev('X', 0, 200), ev('Y', 200, 500)]
    out = insert_transition_events(events, 25, resolve, lambda: 50, 50,
                                   return_min_factor=2.5)
    clips = [e['clip_name'] for e in out]
    assert clips == ['X', 'T', 'Y'], f"erwartet X→T→Y (Bruecke ueber Totale), bekam {clips}"


# ── Test 10: load_audio liest JEDE Bit-Tiefe korrekt (24-bit-Bug-Regression) ───
def test_load_audio_all_bit_depths():
    """Der alte wave+int16-Loader zerlegte 24-bit-WAVs zu Rauschen (1,5x Laenge).
    Der ffmpeg-Loader muss 16/24/32-bit PCM UND 32-bit-Float (DJI Mics) korrekt
    lesen: richtige Laenge, richtige Rate, Inhalt identisch zur Referenz."""
    import subprocess
    import tempfile
    from pathlib import Path as _P
    from multicam_cutter.build_base_edl_from_audio import load_audio

    sr = 48000
    rng = np.random.default_rng(7)
    ref = (rng.standard_normal(sr * 2) * 0.1).astype(np.float32)   # 2 s Rauschen

    with tempfile.TemporaryDirectory() as td:
        raw = _P(td) / "ref.f32"
        raw.write_bytes(ref.tobytes())
        for codec, name in [("pcm_s16le", "16-bit"), ("pcm_s24le", "24-bit"),
                            ("pcm_s32le", "32-bit int"), ("pcm_f32le", "32-bit float")]:
            wav = _P(td) / f"{codec}.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(sr),
                            "-ac", "1", "-i", str(raw), "-c:a", codec, str(wav)],
                           check=True)
            audio, got_sr = load_audio(str(wav))
            assert got_sr == sr, f"{name}: Sample-Rate {got_sr} statt {sr}"
            assert abs(len(audio) - len(ref)) <= 2, \
                f"{name}: {len(audio)} Samples statt {len(ref)} (Bit-Tiefe falsch gelesen!)"
            n = min(len(audio), len(ref))
            corr = float(np.corrcoef(audio[:n], ref[:n])[0, 1])
            assert corr > 0.999, f"{name}: Inhalt weicht ab (corr={corr:.4f})"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("\nAlle Diarisierungs-Tests bestanden.")
