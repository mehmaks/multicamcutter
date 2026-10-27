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

## Gesamt-WAVs gesplitteter Aufnahmen (temporaer)

Rekorder wie der Zoom H6essential splitten lange Aufnahmen (neue Datei nach 1 GB).
Der Scan (`shared/split_audio.py`) erkennt die Teile OHNE Dateinamen: BWF-
`time_reference` (Teil B beginnt exakt am Ende von A, gleiches Format/Rekorder) +
bei Mehrspur-Rekordern die Nahtpruefung im Signal (LPC-Vorhersage ueber den
Uebergang, nahtlos ≈ 1, falsche Spur ≥ 3). Nur bei digitaler Stille entscheidet
die Namensaehnlichkeit.

- Ort: `$TMPDIR/MultiCamCutter-joined/<hash der Teile>/<Name von Teil 1>`
  (`MCC_JOIN_DIR`, von der App gesetzt). Die App loescht den Ordner beim Beenden
  und beim Start; der naechste Scan erzeugt die Dateien neu.
- Inhalt: Header (inkl. bext) von Teil 1, Audiodaten aller Teile bytegleich
  hintereinander (> 4 GB → RF64).
- Manifest daneben: `<gesamt>.parts.json` → `{"parts": [{"path", "start_sample",
  "n_samples", "sample_rate"}], "sample_rate"}`. **Vertrag:** Analyse/Sync laufen
  auf der Gesamt-WAV; `build_aaf` liest das Manifest und verweist NUR auf die
  Originalteile (die Gesamt-WAV kommt nie ins Schnittprojekt).
- `.multicam` speichert wie gehabt den Dateinamen — der ist bei der Gesamt-WAV der
  von Teil 1, Zuordnungen bleiben also stabil.
- **Manuelle Korrekturen** (seit 27.10.) in `.multicam`, per Dateiname:
  `"audio_joins": [["a.wav", "b.wav"], …]` (vom Nutzer verbunden, „Gehört zu …" —
  geht der Erkennung vor, ohne Zeit-/Nahtpruefung; nur gleiches Audioformat) und
  `"audio_keep_separate": ["c.wav", …]` (nie automatisch verbinden, „In Einzeldateien
  trennen"). Die App liest beides VOR dem Scan und reicht es als `--join-groups` /
  `--keep-separate` an die Engine. Reihenfolge der Teile: bext-Zeitstempel, wenn alle
  einen haben, sonst wie gewaehlt (Ziel-Spur zuerst).

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

### ⚠️ Mob-Struktur — vor Umbauten sichern

`TapeMob → FileMob → MasterMob → CompositionMob` plus TC-Slot und
`PhysicalTrackNumber` auf den Audio-Slots. Diese Struktur war hart erarbeitet
(Resolve **und** Premiere). Der verifiziert funktionierende Stand liegt als
Git-Tag:

```
git show aaf-struktur-funktioniert:modules/multicam_cutter/build_aaf.py > /tmp/build_aaf_ok.py
git checkout aaf-struktur-funktioniert -- modules/multicam_cutter/build_aaf.py
```

### Clip-Benennung nach Schnittgrund

Ersatz für die Clip-Farben aus dem Resolve-Workflow, die es im AAF nicht gibt.
Der Segmentname in der Timeline ist der **MasterMob-Name**, deshalb:
eine MasterMob je **(Kamera × Schnittgrund)** — nicht je Schnitt, sonst
entstünden hunderte Bin-Clips. Bei 2 Kameras sind es max. ~10.

| reason | Label | Resolve-Farbe (Referenz) |
|---|---|---|
| `speaker` | **Name der sprechenden Person** (Fallback: „Sprecher") | Blue / Teal |
| `reaction_speaking_reaction` | Sprachreaktion | Green |
| `reaction_nodding` | Nicken | Purple |
| `pause_cutaway` | Stille | Violet |
| `max_time` | Max-Zeit | Orange |

Ergebnis in der Timeline: `C7814 - Seb`, `C9320 - Sprachreaktion`, `C9320 - Max-Zeit`, …

**Warum bei `speaker` die Person statt des Grundes:** „Sprecher" steht sonst auf
jedem zweiten Clip (555 von 937 Events in einem realen Lauf) und sagt nichts, was
der Schnitt nicht schon zeigt. Bei Cutaways bleibt der Grund stehen — dort **ist**
er die Information.

**Woher der Name kommt:** Der Personenname existiert nur in der App
(`MicInfo.displayName`; die Engine kennt von den Mics sonst nur Pfade wie
`MIC1.WAV`). Deshalb neuer Weg: `EngineController` leitet je Kamera aus
`assignedMics` den Namen ab → `--cam-person-names` (JSON, **positionsgleich zu
`--cams`**) → `multicam_engine.run_pipeline` → `build_aaf(cam_person_names=…)`.
**Nur bei genau einer zugeordneten Person.** Bei mehreren (Totale) ist aus der
Kamera nicht ableitbar, *wer* spricht — eine Namensliste wäre dort die falsche
Information. Dann bleibt „Sprecher". In der Praxis bekommen Totalen ohnehin nie
`reason == 'speaker'`: das setzt `add_reactions_to_edl.py` nur für die Sprecher-
Kamera, Totalen erhalten `max_time` oder `reaction_*_wide`.

**Wide-Varianten:** `reaction_*_wide` entsteht **ausschließlich**, wenn mehrere
Personen gleichzeitig reagiert haben (`_is_multi_person`, `:266`). Der Clipname
soll sagen, *weswegen* umgeschnitten wurde, nicht wer im Bild ist — daher Suffix:
`Nicken (mehrere)`, `Sprachreaktion (mehrere)`. Das Suffix wird generisch über die
Endung `_wide` gebildet, neue Reaktionstypen brauchen keinen Eintrag.
Die unbenannten Kamera-Mobs (`CAM_A`, `CAM_B`) bleiben zusätzlich im Bin —
sie sind der Zugriff auf den ungeschnittenen Clip.

**Quelle:** `final.colors.json` (`[{"reason": ...}]`, index-parallel zu den
EDL-Events, von `add_reactions_to_edl.py:1295` immer geschrieben).
`_parse_edl` lädt den Sidecar automatisch und hängt ihn als **`cut_reason`** an.

Zwei bewusste Entscheidungen:
- **`cut_reason`, nicht `reason`.** `pause_trim_edl.py` verzweigt auf `reason`
  (`:256` Cutaway-Schutz, `:363` Merge-Sperre). Im Folder-Workflow steht dort
  überall `'speaker'` (`run_from_folder.py:192`), die Logik läuft also leer.
  Echte Gründe dort einzusetzen **würde den Schnitt ändern** — das ist eine
  eigene Entscheidung, kein Nebeneffekt der Benennung. Offener Hebel.
- **Längen-Guard.** Passt `final.colors.json` nicht zur Event-Zahl der EDL,
  wird die Benennung komplett abgeschaltet statt verschoben zuzuordnen.
  Ein falsches Label im Schnitt ist schlimmer als keines.
