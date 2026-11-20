# Pipeline-Schritte

> 📖 **Diese Datei ist die Landkarte.** Die detaillierte Referenz — Logik jedes Passes,
> alle Parameter mit Defaults, Schwachstellen und Verbesserungs-Hebel — steht in
> **`Pipeline-Referenz.md`**.

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

**Analysespur (Schritt 2a; nur binärer Pfad, genau ein Mikro je Kamera; läuft, sobald
Sprachreaktionen, Pausen kürzen ODER Pausen-Cutaways an sind):** Nach der Basis-EDL (vor `cutaways`) rechnet
`einwurf_analysespur.add_analysespur_reactions` je Mikro die Analysespur (Übersprechen +
Rauschen entfernt, in 60-s-Stücken, nur Pegel je Bild; ~50 s für 97 min) und ERSETZT die
Einwürfe in `<cam>_speaking.json` (`source: "analysespur"`) — seit 20.11. die EINZIGE
Einwurf-Erkennung (die alte auf der wandernden Grundlinie + Regel A ist entfernt und lebt
nur im Sequencer-Modul `speaking_reactions.py` weiter). Erkennung lokal wie das Auge:
über Umgebung (ohne eigene Sprache) + über erwartetem Übersprechen, Deadband ±1 s um
Sprecherwechsel. Alte `*_speaking.json` werden vorher gelöscht. Geht die Analysespur
nicht (Mikro-Zuordnung, Fehler) → Lauf ohne Sprachreaktionen, mit Hinweis im Log (nur
dann — über eine Funktion, die nicht angeboten wird, redet die App nicht).

**Vorrang Einwürfe vor Nicken (`speaking_priority`):** in PASS 2 vor der chronologischen
Auswahl — Nicken fällt weg, wenn sein Cutaway weniger als min_shot vor dem Cutaway eines
späteren Einwurfs endet (Decision-Log `speaking_priority`). Pass-Reihenfolge unverändert.

**Pausen auf der Analysespur (20.11.):** Läuft die Analysespur, erkennt der Schritt 2a
die Pausen neu (`pausen_aus_analysespur`): Stille = beide Spuren unter „eigene Sprache −
12 dB". Überschreibt `audio_trims.json` und `pause_cutaways.json`, die Originalton-Listen
bleiben als `*_original.json`. Grund (Sichtung Folge 62, „straff"): im Original lag leise
Sprache — v. a. des leiseren Mikros — unter der Stilleschwelle (−60 dB) und wurde an
Sprecherwechseln weggeschnitten (bis 1,8 s). Ohne Analysespur (z. B. ein Mikro für beide)
bleibt die alte Erkennung im Originalton.

**Sprecherwechsel in die Stille (20.11.):** Vor der Pausenerkennung rückt Schritt 2a
Sprecherwechsel der Basis-EDL in die nächste Stille (±3 s), wenn die Person, die im
übersprungenen Stück noch im Bild war, dort laut Analysespur ≥ 90 % still ist
(`wechsel_in_stille`). Quelle + Aufnahme verschieben sich gleich → synchron. Original
bleibt als `base_original.edl`. Abschaltbar über `speaker_change_into_silence: false`.
Grund: Kürzen geht nur AM Wechsel, und vorher lag er bei ~80 % der Pausen außerhalb.
Sicherheitsabstand der Stille: 0,08 s nach Satzende, 0,22 s vor Satzanfang (Sichtung v3: +2 Frames für sauberen Einstieg).

**Pausen in Redebeiträgen kürzen (User-Idee 19.11.):** Nur wenn Pausen kürzen UND
„Cutaways in Pausen" an sind. `pause_trim_edl.innere_pausen` macht aus jedem Pausen-Cutaway,
der nach allen Pässen noch genau auf seiner Stille aus `pause_cutaways.json` liegt (CLIP
kann ihn verschieben → dann nicht), eine Pause mit `innen: true`; gekürzt wird immer am
Schnitt Sprecher → Zuhörende (l-cut: der Cutaway beginnt später), der Zeitsprung liegt im
Kamerawechsel. Der Cutaway bleibt ≥ Cleanup-Mindestlänge (bestehender Trim-Cap). Im
AAF-Weg steht der Grund in `cut_reason`, nicht `reason` (bewusst, siehe build_aaf).

**„Mund + Mikro" (Beta, `mouth_reactions_enabled`, nur binärer Pfad; seit 19.11.
abgeschaltet über `MOUTH_REACTIONS_AVAILABLE` / `FeatureFlags.mouthReactions`):** Die Nodding-
Analyse schreibt zusätzlich `<cam>_mouth.npz` (Lippenabstand je Bild der Off-Sektionen,
`--mouth-out`). Ist Nicken für eine Kamera aus, läuft die Analyse trotzdem — dann mit
`params_mouth_only.json` (nodding_enabled=false), also nur für die Mund-Daten.
Danach (vor `cutaways`) trägt `mouth_reactions.add_mouth_reactions` Einwürfe in die
`<cam>_speaking.json` ein (`source: "mund"`) bzw. markiert bestätigte Audio-Erkennungen
(`mund_bestaetigt`). PASS 2 bleibt unverändert. Fehler darin brechen den Lauf nie ab.

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
6. PASS 5 — CLIP Ignore-Filter (optional): max_time/Pausen → Shift;
   Nodding → DROP (Trinkbewegung verworfen, `clip_nodding_mode`, max-Scoring);
   Sprachreaktionen unangetastet
7. PASS 6 — finaler Cleanup kurzer Events (nach Split/CLIP)

Reihenfolge NICHT aendern — Paesse greifen ineinander.

## Pause-Trim (nach Pipeline)

Laeuft in run_from_bin.py / multicam_engine.py NACH add_reactions_to_edl.
Audio-Keeps werden direkt aus Video-Events abgeleitet (Sync garantiert).
Separate Dateien: audio_trims.json (Pause-Daten), audio_keeps.json (Output).

## Skip-Optionen

- `--skip-analysis`: Nodding-JSONs wiederverwenden (wenn vorhanden)
- `--skip-base-edl`: base.edl wiederverwenden (wenn vorhanden)
- Beide nutzbar wenn sich Quelldateien nicht geaendert haben
