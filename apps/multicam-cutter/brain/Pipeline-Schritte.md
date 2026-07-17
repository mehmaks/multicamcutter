# Pipeline-Schritte

## Uebersicht

| # | Step-ID | Beschreibung | Dauer |
|---|---------|-------------|-------|
| 1 | scan | Ordner scannen, Cams/Mics erkennen | <1s |
| 2 | sync | Waveform-Sync (Cross-Correlation) | 5-15s |
| 3 | base_edl | RMS-Diarization + Base-EDL bauen | 10-30s |
| 4-N | nodding_camX | Nodding-Analyse pro Kamera | 5-15 min/Cam |
| N+1 | cutaways | PASS 2-5 (Cutaway-Einfuegung, CLIP-Filter) | 30-120s |
| N+2 | pause_trim | Pause-Trimming | <1s |
| N+3 | aaf_export | AAF-Generierung | 1-3s |

Nodding ist ~80% der Gesamtzeit. Bei 2 Cams a 90 Min: ~20 Min total.

## Pipeline-Code

Engine: `multicam_engine.py:run_pipeline()` orchestriert.
Intern: `run_from_bin.py:run_analysis()` startet Subprocesses:
- `build_base_edl_from_audio.py` (Schritt 3)
- `video_reaction_analyzer_v2.4.py` (Schritt 4-N, pro Cam)
- `add_reactions_to_edl.py` (Schritt N+1)

Pause-Trim und AAF-Export laufen inline in der Engine.

## PASS-Reihenfolge in add_reactions_to_edl.py

1. PASS 1 — Base-EDL parsen
2. PASS 2 — Reaction-Cutaways einfuegen (nodding, speaking)
3. PASS 2b — Pause-Cutaways (Stille-basiert)
4. PASS 3 — Cleanup kurze Events (< cleanup_dur)
5. PASS 4 — Split lange Shots (> max_shot + 3s)
6. PASS 5 — CLIP Ignore-Filter (optional)

Reihenfolge NICHT aendern — Paesse greifen ineinander.

## Pause-Trim (nach Pipeline)

Laeuft in run_from_bin.py / multicam_engine.py NACH add_reactions_to_edl.
Audio-Keeps werden direkt aus Video-Events abgeleitet (Sync garantiert).
Separate Dateien: audio_trims.json (Pause-Daten), audio_keeps.json (Output).

## Skip-Optionen

- `--skip-analysis`: Nodding-JSONs wiederverwenden (wenn vorhanden)
- `--skip-base-edl`: base.edl wiederverwenden (wenn vorhanden)
- Beide nutzbar wenn sich Quelldateien nicht geaendert haben
