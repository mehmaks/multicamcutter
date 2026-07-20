# Dateiformate

## .multicam (Session-Datei)

Versteckte JSON-Datei im Episoden-Ordner. Wird automatisch gespeichert bei
jeder Aenderung (Rename, Zuordnung, Parameter, Aktivierung). Beim erneuten Laden
des Ordners werden Labels, Zuordnungen, Parameter und Aktivierung wiederhergestellt.

`included` (Cams + Mics): Steuerung ueber das Quelldateien-Panel. `false` =
existiert weder auf dem Canvas noch fuer die Analyse (wird der Engine nicht
uebergeben). **Fehlt das Feld** (aeltere Sessions), gilt `true`.

`is_wide` (nur Cams, Bool): Cam ist als **Totale** markiert → `--cam-types wide`
(Simultan-Reaktionen via `totale_simul_dur`). Fehlt das Feld, gilt `false`. Cam
ohne Mic UND ohne `is_wide` wird der Engine gar nicht uebergeben.
**Migration**: Alte Sessions hatten `tag` (`none`/`host`/`guest`/`wide`) — nur
`wide` hatte je Funktion; `loadSession()` liest `tag == "wide"` als `is_wide = true`.
Host/Gast (waren reine Kategorisierung, taten nichts) sind entfallen; Rollen
kaemen kuenftig an der **Person**, nicht an der Cam.

```json
{
  "episode_name": "49 - Dr. Marion Runnebaum",
  "fps": 25.0,
  "cameras": [
    {"id": 0, "filename": "C9732.MP4", "display_name": "Cam Gast", "assigned_mics": [1], "included": true, "is_wide": false},
    {"id": 1, "filename": "jena_0003.MP4", "display_name": "Cam Seb", "assigned_mics": [0], "included": true, "is_wide": false},
    {"id": 2, "filename": "wide.MP4", "display_name": "Totale", "assigned_mics": [], "included": true, "is_wide": true}
  ],
  "mics": [
    {"id": 0, "filename": "MIC1.WAV", "display_name": "Mic Seb", "included": true},
    {"id": 1, "filename": "MIC2.WAV", "display_name": "Mic Gast", "included": false}
  ],
  "params": {
    "max_shot": 14.0, "cleanup_dur": 1.6, "reaction_dur": 1.7,
    "pause_trim_enabled": true, "max_pause": 1.0, ...
  }
}
```

Matching: Dateien werden ueber `id` + `filename` zugeordnet. Wenn sich
Dateien im Ordner aendern, werden nur passende Eintraege geladen.

## Preset-Dateien (.json)

Gespeichert in `~/Library/Application Support/MulticamCutter/presets/`.
Exportierbar/importierbar ueber Finder-Dialoge.

```json
{
  "name": "Podcast 2-Cam",
  "params": {
    "max_shot": 14.0, "cleanup_dur": 1.6, "reaction_dur": 1.7, ...
  }
}
```

Built-in Presets (hardcoded): Podcast 2-Cam, Interview (schnell), Talk (entspannt).

## clip_prompts.json (user-editierte CLIP-Prompts)

`~/Library/Application Support/MulticamCutter/clip_prompts.json` — vom Settings-Tab
„CLIP" geschrieben. Existiert sie, bevorzugt die Engine sie vor der gebündelten
`config/clip_ignore_prompts.json` (`shared.paths.effective_clip_prompts_path()`).
„Auf Standard zurücksetzen" löscht sie. Gleiches Schema wie die gebündelte Datei:

```json
{ "ignore": ["a person drinking water"], "neutral": ["a person talking"] }
```

`ignore` = Frames, die als Cutaway vermieden werden; `neutral` = ausdrücklich ok.
Prompts englisch (CLIP-Erwartung).

## nodding_patterns.json (user-editierte Nodding-Muster)

`~/Library/Application Support/MulticamCutter/nodding_patterns.json` — vom
Settings-Tab „Nodding" geschrieben (roher JSON-Editor, ganze Datei). Existiert sie,
bevorzugt die Engine sie vor der gebündelten `config/nodding_patterns.json`
(`shared.paths.effective_nodding_patterns_path()` bzw. `_load_nod_patterns()`).
Struktur: `{ "global": {…7 Werte…}, "patterns": [ {name, enabled, window_s, filters,
confidence}, … ] }`. Swift validiert vor dem Speichern (gültiges JSON +
`global`/`patterns`); die Engine fällt bei defekter Datei auf die Defaults zurück.

## JSONL Log

`~/Library/Logs/MulticamCutter/{timestamp}_{name}.jsonl`

Jede Zeile ein JSON-Objekt mit `type` und `ts` (ISO 8601).
Enthaelt: session_start (mit System-Info), alle step_progress,
warnings, errors, log-Zeilen, result, session_end.

## Previews (temporaer)

`/tmp/multicam-cutter-previews/`
- `cam{i}_{stem}.jpg` — Thumbnails (320px breit)
- `mic{i}_{stem}.wav` — Audio-Previews (5s, 22050 Hz, mono)

## Pipeline-Output

`/tmp/resolve-toolkit/{md5-hash}/`
- base.edl, final.edl, final.colors.json
- *_reactions.json, *_speaking.json, *_off_sections.json
- cameras.json, params.json
- audio_trims.json (Pause-Daten), audio_keeps.json (Audio-Keeps)
- decision_log.json (Dev-Only)
- speaking_debug.json (Dev-Only, siehe unten)

## speaking_debug.json (Dev-Only)

Kurvenverlauf der Sprachreaktions-Erkennung, um FPs nachvollziehbar zu machen
(Crossbleed-Rückkehr, Freeze-Aussetzer). Nur wenn `is_dev_mode()` — beim Kunden
entsteht die Datei nicht. Geschrieben neben der EDL.

```json
{
  "schema": 1, "fps": 25.0, "window_s": 0.05, "wav_edl_frame": 0,
  "params":     { "rise_db": 6.0, "attack_window_s": 0.2, ... },
  "thresholds": { "pause_db_cam1": -31.0, "kmeans_cam1": {
                    "noise_floor": -52.0, "quiet_speech": -34.0,
                    "confidence": "hoch" }, ... },
  "segments": [
    { "speaker": "CAM1", "reaction_cam": "CAM2", "off_mic": "MIC2",
      "start_s": 132.4, "end_s": 148.95, "start_edl_frame": 3310,
      "db": [...], "baseline": [...], "rise": [...], "freeze": [0,0,1,1,0,...],
      "bursts":   [{ "start_s": 6.15, "tl_frame": 3464, "conf": 0.83,
                     "emitted": true }],
      "rejected": [{ "start_s": 2.1, "reason": "kuerzer_als_min_duration" }] },

    { "speaker": "CAM2", "start_s": 149.0, "end_s": 151.2,
      "skipped": "segment_kuerzer_als_warmup" }
  ]
}
```

- **Pro Segment, nicht durchgehend** — die Baseline wird pro Sprecher-Turn
  zurückgesetzt. Die Sprünge an den Grenzen sind echt und sollen sichtbar bleiben.
- Alle vier Arrays sind gleich lang; Zeitbezug `start_s + i · window_s`,
  Timeline-Frame `start_edl_frame + round(i · window_s · fps)`.
- `freeze` ist der einzige Wert, der sonst nirgends beobachtbar ist — er wird in
  `detect_speaking_reactions` gebaut und war bisher nur lokal.
- Kompaktes JSON (kein `indent`), ~1,7 MB pro Stunde Material.
- Datenquelle für die geplante Timeline-/Kurvenansicht in der App.

## AAF-Output

Im Episoden-Ordner: `{Episodenname}.aaf`
Dateiname leitet sich vom editierbaren Episodennamen ab.
