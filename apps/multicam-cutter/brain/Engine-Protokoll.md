# Engine-Protokoll (Swift <-> Python)

## Aufruf

```
multicam-engine --folder /path --fps 25 --params '{...}' --output /path/final.aaf
multicam-engine --folder /path --scan   # Nur Thumbnails + Audio-Previews
```

## Lizenz-Modi (einzeiliges JSON auf stdout, kein Streaming)

| Flag | Beschreibung |
|------|-------------|
| --check-license | Aktuellen Lizenzstatus prüfen |
| --set-key KEY | Schlüssel hinterlegen + aktivieren (Abo) |
| --clear-license | Lizenz deaktivieren (lokal löschen + best-effort Server-Slot frei) |
| --install-license PFAD | Legacy: signierte license.json-Datei installieren |

JSON-Ausgabe: `{valid, email, expires, modules, grace, sub_status, renews_at,
ends_at, error}`. `expires` = Lease-Fenster (NICHT Abo-Ende). Abo-Datum via
`renews_at`/`ends_at` (nur wenn Backend `subscription`-Block liefert).
Voraussetzung Remote: `TOOLKIT_LICENSE_MODE=remote` (setzt LicenseConfig.swift).

## Free-Tier

Ohne gültige Lizenz bricht `run_pipeline` vor dem Sync ab, wenn die längste
Quelldatei > 30 Min ist (`_enforce_free_tier`) → als `error`-Message an die UI.

## Explizite Quelllisten (--cams / --mics) — WICHTIG

| Flag | Typ | Beschreibung |
|------|-----|-------------|
| --cams | Pfade | Nur die im Panel **aktivierten** Kameras |
| --mics | Pfade | Nur die im Panel **aktivierten** Mikrofone |

Sind sie gesetzt, scannt `run_pipeline` den Ordner **nicht** selbst, sondern nutzt
genau diese Listen. Ohne sie bleibt der Selbst-Scan (Rückwärtskompatibilität).

**Warum das existiert:** Vorher rief `run_pipeline` immer `scan_folder(folder)` —
die Engine hätte im Panel deaktivierte Dateien wieder eingesammelt. Ausserdem sind
`--cam-mics`/`--cam-types`/`--display-names` **positionsbasiert** und verliessen sich
darauf, dass Swifts Reihenfolge zufaellig der Scan-Reihenfolge entspricht. Mit
expliziten Listen stimmen die Positionen **per Konstruktion**.

⚠️ **Zwei Fallstricke:**
1. `--cam-mics`-Werte sind Positionen in **`--mics`**, nicht die Mic-IDs der App.
   `EngineController.camMicsArgs` rechnet die IDs auf `activeMics`-Positionen um —
   sonst landen Mics bei den falschen Kameras (still, ohne Fehler!).
2. Alle positionalen Args muessen ueber `activeCams`/`activeMics` gebaut werden,
   nie ueber die vollen Listen.

## Zusaetzliche Flags

| Flag | Typ | Beschreibung |
|------|-----|-------------|
| --cam-mics | "1" "0" | Mic-Zuordnung pro Cam (Positionen in --mics, s.o.) |
| --cam-types | "close" "wide" | Kamera-Typ pro Cam |
| --cam-nodding | "true" "false" | Nodding on/off pro Cam |
| --skip-analysis | flag | Nodding-JSONs wiederverwenden |
| --skip-base-edl | flag | base.edl wiederverwenden |
| --display-names | JSON-Array | Display-Namen fuer Progress-Labels |
| --speaking-mode | rms/peak | Ueberschreibt speaking_mode |
| --lut | Pfad | LUT-Datei fuer MediaPipe (App hebt es nicht, s. UI-Komponenten.md) |
| --clip-name-pattern | Muster | AAF-Clipnamen. Tokens `%S` Quelle · `%R` Grund · `%P` Person · `%L` smartes Label. Logik: `build_aaf._name_for`. **KEIN Flag = ein MasterMob pro Kamera** (Name = Dateiname). Mit Flag: grund-benannte MasterMobs (mehrere pro Kamera) — Resolve zeigt sie am Timeline-Clip, Premiere legt je Grund einen zusaetzlichen KORREKT verknuepften Clip an (beide online, s. brain/AAF-Struktur.md). App sendet es bei Toggle „Schnittgruende in Clipnamen" (Default **AN**, Key `clipNameReasons`) |
| --manual-offset | PFAD=FRAMES | Manueller Sync-Offset je Quelle (mehrfach). Quelle wird NICHT korreliert, Wert (Frames rel. CAM1) direkt uebernommen. **Pfad-basiert** (interne Labels verrutschen bei Ausschluss). App sendet es beim „Erneut synchronisieren" aus dem `SyncResolutionSheet` (Baustein 3). Anwendung: `waveform_sync.sync_sources(manual_offsets={pfad: frames})` |

## CLIP-Modi (Bilderkennung)

| Flag | Ausgabe |
|------|---------|
| --check-clip-model | einzeiliges JSON `{"installed": bool, "download_bytes": int}` |
| --download-clip-model | streamt `clip_download_start`/`clip_progress`/`clip_download_complete` |
| --get-clip-prompts | einzeiliges JSON `{"ignore":[…],"neutral":[…],"source":"user"\|"default","user_path","default_path"}` |
| --get-nodding-patterns | einzeiliges JSON `{"content": "<rohe nodding_patterns.json>","source":"user"\|"default","user_path"}` |

`--get-clip-prompts` liest die aktiven Cutaway-Filter-Prompts: die user-editierte
`~/Library/Application Support/MulticamCutter/clip_prompts.json` wird bevorzugt
(`shared.paths.effective_clip_prompts_path()`), sonst die gebündelte
`config/clip_ignore_prompts.json`. Der Settings-Tab „CLIP" schreibt/löscht die
User-Datei direkt (Swift), die Engine liest sie beim Analyse-Lauf über
`run_from_bin.py` → `add_reactions_to_edl.py --clip-filter-config`.

`--get-nodding-patterns` liefert den **rohen** Inhalt der aktiven
`nodding_patterns.json` (user-editierte in Application Support bevorzugt, sonst
gebündelt — `shared.paths.effective_nodding_patterns_path()`). Der Settings-Tab
„Nodding" zeigt/bearbeitet ihn als Text; Swift schreibt die validierte User-Datei,
die Engine liest sie beim Analyse-Lauf über `_load_nod_patterns()` (Fallback auf
Defaults bei defekter Datei).

## JSON-Lines Message Types

| Type | Felder | Wann |
|------|--------|------|
| `session_start` | version, folder, fps, params, system, log_file | Einmalig am Start |
| `scan_progress` | percent, step, total_steps, label | Waehrend --scan |
| `scan_complete` | cameras[], mics[], default_mapping | Ende von --scan. Je Mic: index, filename, path, preview, `preview_offset_s`, `duration_s`, `separation_db` (Trennung in dB, Median-Pegelabstand wenn diese Person spricht; **null** wenn nicht messbar), `parts` (Originalteile einer gesplitteten Aufnahme in Aufnahmereihenfolge; dann ist `path` die temporaere Gesamt-WAV, s. Dateiformate.md; **leer** = Einzeldatei). `parts_manual` (true = per „Gehört zu …" verbunden). Top-Level `join_warnings[]`: manuelle Verbindungen, die nicht gingen (z. B. anderes Audioformat) — App zeigt sie als Alert. Scan-Args `--join-groups` (JSON-Liste von Dateinamen-Listen) / `--keep-separate` (JSON-Liste), s. Dateiformate.md. Scan-Fortschritt hat dafuer je Gruppe einen Schritt `Joining split recording: …` |
| `step_start` | step_num, total_steps, label | Neuer Pipeline-Schritt (von Engine) |
| `step_start_sub` | label | Subprocess-Schritt (von JsonLineWriter erkannt) |
| `step_detail` | label | Verfeinert den Text des LAUFENDEN Schritts (welcher Pass rechnet). Erhoeht `stepNum` **nicht** — anders als `step_start_sub` |
| `step_progress` | percent, eta, counter? | Fortschritt innerhalb eines Schritts. `eta` = Restzeit `M:SS`, `counter` = `done/total` (optional) |
| `scan_result` | cameras[], mics[] | Nach Ordner-Scan im Pipeline-Modus |
| `step_weights` | weights[] | Einmal nach dem Scan: relatives Gewicht je Schritt (Reihenfolge wie `total_steps`: Scan, Sync, Base-EDL, Nodding×N, Cutaways, Pause-Trim, AAF) fuer den **gewichteten Dock-Balken** (Punkt 5). Nodding (je Kamera) + CLIP-Cutaway-Pass dominieren. Swift nutzt es in `overallProgress`; Laenge != `total_steps` → Fallback Gleichgewichtung. |
| `sync_result` | offsets{} | Nach Waveform-Sync (alle Quellen einordbar) |
| `sync_unresolved` | sources[] | Sync fand nicht automatisch einordbare Quellen (Baustein 2). Je Quelle: `label`, `path`, `filename`, `reason`, `best_confidence`, `candidate_offset_frames`. Danach stoppt die Pipeline **sauber** (`SyncUnresolved`, KEIN `error`); die App zeigt `SyncResolutionSheet` (ausschliessen / manueller Offset / abbrechen) und startet neu. Nur bei `sync_sources(collect_unsyncable=True)` — harte Eingabefehler (Datei zu kurz, Korrelation < MIN) bleiben `error`. |
| `warning` | message | Nicht-fatale Warnung |
| `error` | message | Fataler Fehler |
| `result` | aaf, edl, events_total, events_by_type, elapsed_s | Erfolg |
| `log` | message | Regulaere Print-Ausgabe (gewrappt) |
| `convert_progress` | file_index, file_count, label, done, total | FPS-Konvertierung: `done`/`total` in **Sekunden** (aus ffmpeg `time=`), Fraktion = done/total. `total=0` = „wird vorbereitet". Abbruch: App schickt **SIGTERM** → Engine (`_on_term`) killt ffmpeg + loescht Teildatei + `os._exit(0)`. |
| `convert_complete` | outputs[] | Ende von `--convert-fps`. Codec quellabhaengig (HEVC 10-bit fuer 4:2:0, ProRes fuer 4:2:2/4:4:4 — s. brain/Entscheidungen.md). Tuning per `--hevc-quality` (Default 72) + `--prores-profile` (standard\|hq, Default hq); die App reicht die Settings-Werte (`convertHevcQuality`/`convertProResProfile`) durch. |
| `clip_progress` | done, total | CLIP-Download: Bytes |
| `session_end` | success, elapsed_s | Ende der Session |

## JsonLineWriter (protocol.py)

Ersetzt sys.stdout. Konvertiert alle Ausgaben:
- JSON-Zeilen (starten mit `{`) -> durchreichen
- `__PROGRESS__ <pct> [<M:SS>] [<done>/<total>]` -> `step_progress` (auch bei `\r`-Separator).
  Die Zusatzfelder werden nach **Form** erkannt (`\d+:\d\d` = Zeit, `\d+/\d+` = Zaehler),
  nicht nach Position: frueher wurde `parts[1]` blind als ETA uebernommen, wodurch der
  Zaehler des CLIP-Passes als `ETA: 341/384` in der UI stand.
- `… PASS <n>: …` -> `step_detail` mit dem Namen des zugehoerigen Einstellungs-Schalters
  (`_PASS_LABELS` in `protocol.py`). Die Banner enden nicht auf `...` und werden
  deshalb **vor** der Punkt-Erkennung geprueft.
- `__REACTIONS__` -> gefiltert (nicht anzeigen)
- `  Beschreibung...` -> `step_start_sub` wenn bekannter Step
- Alles andere -> `{"type": "log"}`

Display-Namen: `_display_names` Dict (filename -> label) ersetzt Dateinamen
in Step-Labels (z.B. "Nodding-Analyse CAM1 (Cam Host)" statt Dateiname).

Kompatibilitaet: `_log` Attribut muss existieren damit `run_from_bin.py`
Subprocesses durch den Writer pipt (hasattr-Check).

## Logging

JSONL-Logdatei: `~/Library/Logs/MulticamCutter/{timestamp}_{name}.jsonl`
Enthaelt ALLE Messages + Timestamps. Wird vom JsonLineWriter parallel geschrieben.
