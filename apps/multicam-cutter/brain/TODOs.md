# TODOs & Roadmap — MultiCamCutter

> **Diese Datei = OFFENE Arbeit + 1.0-Roadmap.** Erledigte TODOs liegen im Archiv
> `brain/TODOs-Archiv.md` (Historie + Gotchas — nicht löschen, dort steckt oft die
> Begründung/der Fallstrick eines späteren Bugs).

## Weg zu 1.0

**Definition-of-Done 1.0:** „Ohne Fremdscham an einen fremden Cutter verkaufbar" —
kein bekannter Dead-End auf realem Material, Distribution sauber, der Kern (Ordner
rein → korrektes AAF für Resolve **und** Premiere) bulletproof. 1.0 fällt, wenn
A + B + die vorgezogenen Backlog-Themen stehen — **unabhängig vom restlichen
Backlog (C)**.

### 🔒 Feste Abarbeitungsreihenfolge (gelockt 25.07. — bis 1.0 NICHT mehr umsortieren)

Strikt Punkt für Punkt von oben nach unten. **Keine Neu-Sortierung bis 1.0** — Ausnahmen
nur: echte Bugs und kleine kosmetische Anpassungen. Neue Feature-Ideen gehen nach
Post-1.0 (C), nicht in diese Liste.

| # | Punkt | Bucket | Aufwand | Warum an dieser Stelle |
|---|---|---|---|---|
| 1 | **Sync-Graceful** — nicht abbrechen, Offset/Ausschluss pro Quelle (Baustein 1→2→3) | 🎯 A | mittel | Höchster Wert: einziger Punkt, an dem heute echte Arbeit verloren geht (1 Quelle killt den Lauf) |
| 2 | **FPS-Check zusammenführen** (Exit-Code 42) | 🎯 A | leicht–mittel | Klein; liegt im selben Pre-Analyse-Gate wie Sync, entfernt Doppel-Wahrheit + kryptischen Fehler |
| 3 | **Bundle-Größe im Frozen-Build verifizieren** | 🎯 A | leicht (Test) | Reiner Test (Excludes, CLIP an); billiger Distributions-De-Risk, evtl. DMG < 300 MB |
| 4 | **Mehrere Totalen Stufe 1** (`totale_mode`) | ✨ B | mittel | Neuer Param — **vor** dem Settings-Durchgang, damit der die finale Param-Menge sieht |
| 5 | **Dock-Balken gewichtet** (ehrlicher Fortschritt) | ✨ B | mittel | In sich abgeschlossene Politur; Protokoll (Arbeitsumfang je Schritt) + Swift |
| 6 | **Telemetrie** (Opt-in, Daten ab Tag 1) | 🌍 | mittel | Letzter neuer Datenfluss + Consent-Toggle — **vor** dem Settings-Durchgang |
| 7 | **Settings-Durchgang** (Benennung/Gruppierung) | ✨ B | mittel | **String-Freeze**: alle Labels final (inkl. Totalen-Param + Telemetrie-Toggle). Ab hier ändert sich kein deutscher UI-Text mehr |
| 8 | **Mehrsprachigkeit DE/EN** | 🌍 | mittel–schwer | **Capstone**: Freeze-then-Translate — Engine→Keys, Swift lokalisiert, ParamHelp ×30, Web-Schema-Sync über die eingefrorene Menge → **1.0** |

**Rückgrat der Ordnung (nicht willkürlich):** 6 → 7 → 8. Telemetrie bringt den letzten
neuen Toggle, der Settings-Durchgang friert danach *alle* deutschen UI-Texte ein, und
i18n übersetzt die eingefrorene Menge **einmal**. Punkt 4 (neuer Totalen-Param) liegt
bewusst vor 7. 1–3 (Blocker) zuerst, weil Wert/Risiko am höchsten.

Detail-Beschreibungen der Punkte unten (nach Bucket gruppiert).

## Offene TODOs

### 🎯 A — 1.0-Blocker

### 🔴 Sync-Abbruch bei EINER Problemquelle blockiert alles (Fremd-Feedback, 22.07.)
- [ ] **Nicht hart abbrechen, wenn eine Quelle nicht syncbar ist.** Realfall vom
  Kollegen: 6 Quellen (3 Cams, 3 Mics), fünf perfekt synchron (MIC1↔MIC2 230×,
  Cams 100–400×), nur **MIC3** korreliert mit nichts (über MIC1 +62383 Frames,
  über MIC2 +19181 — 28 min auseinander, Confidence flach ~15× über die volle
  Datei). Die Kreuzprobe verweigert **korrekt** (kein echter Gipfel), aber der
  `SyncError` bricht den GESAMTEN Lauf ab. Der Cutter kommt gar nicht weiter.
  **Zu bauen — mehrstufig:**
  1. **Gegen ALLE Partner versuchen, nicht nur die Referenz.** Heute wird jede
     Quelle nur gegen das längste Mic korreliert (`sync_sources`). Eine
     Close-Mic teilt oft wenig Raumklang mit einem fernen Mic, aber viel mit der
     Kamera IHRER Person. Also: scheitert Quelle gegen die Referenz, gegen die
     anderen bereits sicheren Quellen (Kameras!) probieren, bestes Ergebnis über
     `TRUST_CONFIDENCE` nehmen. (Deckt sich mit „Sync-Referenz überdenken".)
  2. **Bleibt sie unsyncbar: nicht abbrechen, sondern melden.** `sync_sources`
     gibt die ermittelten Offsets zurück PLUS eine Liste „nicht syncbar". Die App
     bietet dann pro Problemquelle: **(a) manuellen Offset eingeben** (Feld in
     Frames/Sekunden), **(b) Quelle ausschließen**, **(c) abbrechen**. Die
     anderen fünf Quellen sind ja fertig.
  3. **Manueller Offset** ist damit endlich fällig (früher vertagt) — für Quellen,
     deren Ton aus ganz anderer Position kommt (Funk-Lav ohne Raumklang, separater
     Recorder mit Clock-Drift).
  **Sofort-Workaround (heute):** Die Problem-Mic im Personen/Mic-Schritt
  **abwählen** (`included=false`) — dann ist sie nicht im Sync und der Lauf
  läuft. Nachteil: die Person auf dieser Spur wird nicht diarisiert.

  **Diagnose GEKLÄRT (23.07.):** MIC3 ist **Track 3 desselben Mehrspur-Recorders**
  wie MIC1/MIC2 (Beweis: `MIC1↔MIC2 = +0 Frames @ 230×` = gemeinsame Clock; Namen
  `Track1/2/3`). Es ist **keine** Positions-/Drift-Sache — Person 3 spricht nur in
  den ersten 180 s kaum, und der Sync nimmt das Ziel-Chunk **immer ab Sekunde 0**
  (`_sync_pair`: `-t` ohne `-ss`, nur die REFERENZ wächst). Leeres Ziel-Chunk →
  flache ~15× über alle Fenster. Zusätzlich wird eine schwache Quelle nur gegen
  **die eine** beste Quelle gegengeprüft (hier MIC2, auch ein Lav) — **nie gegen
  eine Cam** (Baustein 1 unten bestätigt sinnvoll).

  **✅ TEIL-FIX geliefert (23.07., v-tbd): Recorder-Geschwister.** Wizard-Checkbox
  „Alle Tonspuren stammen aus einem Mehrspur-Recorder" (Screen 1, ab 2 Mics) →
  `sync_sources(..., mics_same_recorder=True)`: still aufgenommene Mic-Spuren erben
  den Referenz-Offset (0), statt den Lauf abzubrechen; gut korrelierte Mics behalten
  ihre Messung, weicht eine ab → Warnung. Deckt den Kollegen-Realfall komplett ab.
  Verkabelt: `waveform_sync.py`, `multicam_engine.py:~826`, `EngineController.swift`
  (PipelineParams `micsSameRecorder`), `WizardView.swift` (PersonsStep), `ParamHelp`.

  **✅ Fenster-Fix geliefert (23.07.):** `_sync_pair` nimmt das Ziel-Chunk jetzt
  bei schwachem Auftakt aus der ENERGIEREICHSTEN Region (`_loudest_window_start`)
  statt stur ab Sekunde 0, und rechnet die Verschiebung aus dem Versatz heraus.
  Der schnelle Normalfall (Auftakt lockt) bleibt unverändert. Deckt spät redende
  Träger ab. Getestet: später Sprechbeginn → +30s exakt bei 751×.

  **✅ Baustein 1 GELIEFERT (25.07.):** Rescue-Pass in `shared/waveform_sync.py`
  (direkt vor der CAM1-Normalisierung). Korreliert eine Quelle schwach gegen die
  Referenz (< `TRUST_CONFIDENCE` = 50×), wird sie gegen jede bereits sichere Quelle
  (≥ TRUST, **Kameras eingeschlossen**) gemessen, sicherste zuerst; ein echter Gipfel
  (≥ TRUST) ersetzt den Offset (`rel[partner] + Messung`, in die Referenz umgerechnet).
  Läuft NUR bei schwachen Quellen → Happy-Path (alle ≥ TRUST) Bit-für-Bit unverändert;
  nur ein Gipfel rettet, sonst bleibt die Quelle unangetastet und fällt in die
  Gegenprüfung (die HEUTE noch abbricht — das ist Baustein 2). Signatur/Rückgabe
  unverändert → keine Engine-/Swift-Änderung. Deterministische Tests:
  `shared/test_waveform_sync.py` (Rescue via Kamera · Happy-Path + Call-Log ·
  unsyncbar bricht weiterhin ab). Engine nutzt genau diese Datei (`ROOT`-Import).

  **✅ Baustein 2 — geteilte Fähigkeit GELIEFERT (25.07.):** `sync_sources(...,
  collect_unsyncable=True)` gibt `(offsets, [UnsyncableSource, …])` zurück, statt
  bei den beiden Kreuzvalidierungs-Abbrüchen (CAM1↔CAM2-Kreuzprobe · Zwei-Wege-
  Gegenprüfung) `SyncError` zu werfen. `offsets` enthält für JEDE Quelle einen
  Best-Effort-Wert (fürs manuelle Vorbelegen), die Liste nennt die unsicheren
  (label · filename · reason · best_confidence · candidate_offset_frames, per Label
  dedupliziert). Reine Eingabefehler (Datei zu kurz, Korrelation < MIN_CONFIDENCE)
  bleiben bewusst HARTE Fehler. **Ohne das Flag Bit-für-Bit unverändert** (raise +
  dict) → Web-Modul/CLI-Aufrufer nicht berührt. Tests: `shared/test_waveform_sync.py`
  (collect meldet statt raise · Happy-Path `[]` · Kreuzprobe flaggt CAM2). Neuer
  Datentyp `UnsyncableSource`.

  **✅ Baustein 2b + 3 GELIEFERT (25.07.) — Punkt 1 damit komplett (Test an echtem
  Material steht aus):**
  - **Engine:** `multicam_engine.py` ruft `sync_sources(collect_unsyncable=True,
    manual_offsets=…)`. Nicht-leere Liste → Message `sync_unresolved` (label · path ·
    filename · reason · best_confidence · candidate_offset_frames) + `SyncUnresolved`
    stoppt die Pipeline sauber (KEIN `error`, oben vor `except Exception` abgefangen).
    Neuer Arg `--manual-offset PFAD=FRAMES` (mehrfach) → `sync_sources`. `path` kommt
    mit, weil er über Re-Runs stabil ist.
  - **`sync_sources` (Baustein 3):** `manual_offsets={pfad: frames}` — diese Quellen
    werden nicht korreliert, aus Referenzwahl/Kreuzprobe/Gegenprüfung herausgehalten,
    Offset (rel. CAM1) direkt gesetzt. Test `test_manual_offset_bypasses_correlation`.
  - **App (Swift):** `EngineController` parst `sync_unresolved` → `state=.ready` +
    `showSyncResolution` (so zählt das folgende `session_end(success=false)` NICHT als
    Fehler). `SyncResolutionSheet.swift`: pro Quelle **manueller Offset** (Feld, mit
    `candidate_offset_frames` vorbelegt) ODER **Ausschließen**; „Erneut synchronisieren"
    → `resolveSyncAndRetry` (setzt `included=false` bzw. `manualSyncOffsets`, Re-Run)
    · „Abbrechen" → zurück zur Einrichtung. `--manual-offset` in `runEngine` angehängt.
    Swift-Build grün. Protokoll: `brain/Engine-Protokoll.md`.
  ⚠️ **Noch zu tun:** an echtem, nicht-syncbarem Material testen (Dev-App). Danach kann
  Punkt 1 komplett ins Archiv.

### 🔴 Bundle-Größe: 1,2 GB App → 500 MB DMG — blockiert den Upload
Aufwand: **mittel**, Nutzen hoch (Upload, Nutzer-Download, Update-Dauer).

**Anlass**: Cloudflare R2 nimmt weder über `wrangler` noch über das Web-Frontend
mehr als **300 MiB** an. Bei 500 MiB DMG bleibt nur die S3-API. Ein kleineres
Bundle löst das Problem an der Wurzel statt am Transportweg.

**Gemessen (0.5.0, `_internal/`):**

| Paket | Größe | Im Engine-Code importiert? |
|---|---|---|
| torch | **288 MB** | nur in CLIP-Pfaden (lazy `import torch` in Funktionen) |
| cv2 | 120 MB | ja (MediaPipe/Analyse) |
| **pyarrow** | **114 MB** | **nein — 0 Treffer** |
| **llvmlite** | **110 MB** | **nein — 0 Treffer** |
| mediapipe | 85 MB | ja |
| **onnxruntime** | **59 MB** | **nein** (evtl. von mediapipe zur Laufzeit) |
| transformers | 38 MB | nur CLIP |
| scipy | 38 MB | ja |
| mlx | 22 MB | 1 Treffer |
| **pandas** | **17 MB** | **nein** |
| **sklearn** | **16 MB** | **nein** |
| **matplotlib** | **12 MB** | nur `silence_cutter.py` + Sandbox, **nicht** im Multicam-Pfad |

**Schritt 1 — ✅ eingetragen (21.07.), Test steht aus.** `pandas`, `pyarrow`,
`sklearn`, `llvmlite`, `numba`, `matplotlib`, `plotly` stehen in
`multicam_engine.spec` unter `excludes` (~270 MB). `onnxruntime` bewusst NICHT —
mediapipe könnte es zur Laufzeit brauchen; erst nach erfolgreichem Test einzeln
nachziehen.

⚠️ **So wird getestet — die Reihenfolge ist wichtig:**
1. `bash scripts/release.sh <version>` (oder nur den PyInstaller-Build) — die
   Ausschlüsse wirken **nur im gefrorenen Bundle**. Ein Dev-Lauf über `swift run`
   beweist nichts, dort liegt das komplette venv vor.
2. Lauf aus der **gebündelten** `.app` heraus, **mit eingeschaltetem CLIP-Filter**
   („Ungünstige Cutaways verschieben"). Das ist der Pfad, der torch und
   transformers anfasst — und damit der einzige, auf dem die ausgeschlossenen
   Pakete überhaupt auftauchen könnten. Ohne CLIP prüft der Lauf die riskante
   Stelle gar nicht.
3. Zusätzlich den **Ordner-Scan** ansehen: die Personenerkennung fürs Thumbnail
   nutzt CLIP ebenfalls (`_find_person_frame`).
4. Erfolg = Lauf bis zur AAF ohne `ModuleNotFoundError`, plus Größenvergleich
   der `.app` (vorher 1,2 GB).

**Schritt 2 (größer)**: torch + transformers = **326 MB für ein optionales
Feature**. Der CLIP-Filter ist abschaltbar, und das *Modell* wird ohnehin schon
zur Laufzeit nachgeladen (`ClipDownloadSheet`). Nur die Runtime liegt fest im
Bundle. Eine Trennung („Basis-App" + optionales CLIP-Paket) würde das DMG etwa
halbieren — braucht aber ein Konzept, wie eine gefrorene App nachträglich eine
Python-Runtime dazubekommt.

- [ ] **FPS-Check zusammenführen (zwei parallele Mechanismen!)** — Aufwand: **leicht–mittel**.
  Es gibt **zwei** unabhängige FPS-Mismatch-Checks, voneinander nichts wissend:
  1. **Neu (App, heute gebaut)**: `EngineController.fpsMismatches` prüft vor dem Start,
     zeigt Banner + blockiert + bietet `--convert-fps` an. Quelle: `fps` aus dem Scan.
  2. **Alt (Engine)**: laut `modules/multicam_cutter/CLAUDE.md` prüft `run_from_bin.py`
     **vor `sync_sources()`** und bricht mit **Exit-Code 42** ab; die (Streamlit-)UI fängt
     das ab und bietet eine ffmpeg-Konvertierung an. Print-Hinweis: run_from_bin.py:906.
  **Problem**: Doppelte Wahrheit → driftet auseinander, und der App-Pfad kennt Code 42
  gar nicht (würde als generischer Fehler erscheinen). Auch die ffmpeg-Rezepte liegen
  jetzt doppelt (`convert_fps_files` in multicam_engine.py vs. `_run_ffmpeg_conversions`
  in ui/pages/multicam.py).
  **Ziel**: Ein Check, eine Konvertierung, beide UIs nutzen sie. Mindestens: App-Seite
  muss Exit-Code 42 kennen/abfangen. Beim Zusammenführen `modules/…/CLAUDE.md` (Gotchas)
  mitziehen.

### ✨ B — 1.0-Qualität

- [ ] **Mehrere Totalen sinnvoll nutzen** — Aufwand: **mittel**.
  **Ist-Zustand (Falle!)**: Taggt man 2+ Cams als Totale, sind alle ausser der ersten
  **totes Gewicht** — es wird nie auf sie geschnitten, ohne dass irgendwas es sagt:
  - `add_reactions_to_edl.py:266` → `off_cam = wide_cams[0]` (Multi-Person-Cutaway)
  - `add_reactions_to_edl.py:332` → `reset_cam = wide_cams[0]` (Reset nach max_shot)
  - `run_from_bin.py:658` → `next((i for i,t in … if t=='wide'), None)` → nur die erste
    wird `--totale-video` fuer die Base-EDL
  (Nur `build_aaf.py:394` kennt ALLE wide-Cams — fuer den Zoom, der jetzt aus ist.)

  **Stufe 1 (jetzt geplant)**: Parameter `totale_mode` — **zufällig** oder
  **abwechselnd** (Round-Robin: T1, T2, T3, T1, …). Greift an den drei Stellen oben;
  die Auswahl muss pro Cutaway erfolgen, nicht global. Expertenmodus-Parameter +
  (?)-Tooltip (Muster: `ParamHelp.swift`). Base-EDL-Pfad (`--totale-video`, singular)
  mitdenken — evtl. muss der mehrere annehmen.

  **Stufe 2 (später, Edge-Case)**: Totalen **Personen zuordnen**. Beispiel: 4 Personen
  mit je einer Close-Cam, dazu eine Totale P1+P2, eine P3+P4 und eine mit allen. Dann
  soll die Totale gewaehlt werden, die die **reagierenden** Personen zeigt (Fallback:
  die Totale mit allen).
  💡 **Das Datenmodell kann das schon**: Die App ordnet Mics bereits Cams zu. Fuer eine
  Totale muesste die Zuordnung nur andere **Semantik** bekommen — bei `.wide` heisst
  „Mics zugeordnet" nicht „spricht hier", sondern **„zeigt diese Personen"**. `analysisCams`
  laesst Totalen ohne Mic weiterhin zu, das passt also zusammen. UI muesste den
  Bedeutungswechsel nur klar machen (Drop-Ziel-Text auf einer Totale anders benennen).

- [ ] **Settings-Durchgang mit User**: alle Parameter durchgehen, Sortierung +
  Benennung in der UI überarbeiten (Labels, Gruppierung, Reihenfolge, welche
  Basis vs. Experte). Referenz für Namen/Reihenfolge: `config/schemas/multicam_params.json`.

- [ ] **Dock-Balken: pro Schritt zählen statt Gesamtfortschritt.** Aufwand: **mittel**.
  **Problem:** Der Balken hängt an `overallProgress`
  (`EngineController.swift:376`) = `(stepNum-1 + stepPercent/100) / totalSteps` —
  **alle Schritte gleich gewichtet**. Die Nodding-Analyse ist Schritt 6 von 8, dauert
  aber den Löwenanteil der Laufzeit. Der Balken steht also ~30 Minuten knapp unter
  „fertig", obwohl der Großteil der Arbeit noch kommt.
  **Gewünscht:** Der Dock-Balken zeigt den **aktuellen Schritt** 0–100 %, wie das
  Fenster (`ContentView.swift:446`). Nodding zählt dabei als **ein** Schritt über
  **alle** Kameras:
  ```
  fraktion = (cam_index + cam_percent/100) / cam_total
  # 2 Cams, erste Cam bei 50 %  ->  (0 + 0.5) / 2 = 25 %
  ```
  **Fehlendes Datum:** Heute wird je Kamera ein eigener `step_start_sub` gesendet
  (`engine/protocol.py:87-96`), der `stepNum` hochzählt und `stepPercent` auf 0
  zurücksetzt; der Cam-Index steckt nur im Label und wird per Regex geraten. Sauber
  wäre, `cam_index` und `cam_total` explizit mitzusenden, statt in Swift das Label
  erneut zu parsen.
  ✅ **Entschieden (User, 20.07.): gewichtete Dauer**, kein reiner Schritt-Balken —
  so bleibt der Balken ein Gesamtfortschritt, nur ein ehrlicher. Nodding bekäme
  den Löwenanteil statt 1/8.
  ⚠️ **Die Gewichte dürfen nicht statisch sein.** Welche Schritte überhaupt laufen und
  wie lange, hängt vom Lauf ab:
  - **CLIP-Filter ist optional** (PASS 5) und skaliert mit der Episodenlänge — kann
    also je nach Material ähnlich dominant werden wie Nodding oder ganz wegfallen.
  - Die Zahl der Kameras variiert (Nodding läuft je Kamera).
  - Kurze vs. lange Episode verschiebt das Verhältnis der langen zu den kurzen Schritten.
  Eine feste Tabelle (`nodding: 0.7, …`) wäre also schon beim nächsten Preset falsch.
  Besserer Ansatz: jeder lange Schritt meldet beim Start seinen **Arbeitsumfang**
  (z. B. zu analysierende Frames bzw. Segmente), der Balken normiert über die Summe
  der tatsächlich anstehenden Schritte. Dann stimmt es auch, wenn CLIP aus ist.
  🎨 **Kosmetisch, blockt nichts** — bewusst zurückgestellt.

### 🌍 1.0 — vorgezogen aus Backlog (User, 25.07.)

### Telemetrie (anonyme Nutzungsdaten) — Aufwand: **mittel**
- [ ] **Opt-in-Prompt beim ersten Start** + anonyme Nutzungsdaten senden.
  **Ziel (User)**: Wie umfangreich sind die Projekte da draußen? Eher 2-Cam-Setups
  oder komplexe Podcasts mit mehreren Cams/Gästen? Und als Benchmark: **wie lange
  dauert ein Durchlauf bei X Quellen à Y Länge?**

  **⚠️ Datenschutz — die drei Fallen (unbedingt beachten):**
  1. **NIEMALS `_device_id()` der Lizenz wiederverwenden!** Das würde Telemetrie mit
     Lizenz/E-Mail verknüpfbar machen → dann ist es *pseudonym*, nicht anonym.
     → Eigene, zufällige `analytics_id` (UUID), nur lokal erzeugt, ohne Bezug zur Lizenz.
     Noch besser: gar keine ID (dann aber keine Wiederkehrer-Analyse).
  2. **KEINE Namen/Pfade.** Episodenname („49 – Dr. Marion Runnebaum") und Pfade
     („/Volumes/Jardani/Projekte/2025 – Jena United/…") enthalten **Kundennamen** —
     das wäre ein DSGVO-Verstoß. Nur **Zahlen** senden, nie Strings aus dem Projekt.
  3. **Widerruf muss möglich sein** (DSGVO): Toggle in den Settings, nicht nur der
     Erst-Prompt. Plus Datenschutz-Hinweis auf der Website.

  **Payload-Vorschlag (nur Zahlen/Enums):**
  - Umfang: `n_cams`, `n_mics`, `source_durations_s` (Liste oder min/max/median),
    `total_source_s`
  - Benchmark: `elapsed_s` (liegt schon in den Stats!), idealerweise **pro Schritt**
    (die Engine sendet `step_start` — dann sieht man, ob MediaPipe alles dominiert)
  - **Kontext, sonst ist der Benchmark wertlos:**
    - `device_model` (z.B. „Mac14,14") + Chip/RAM — 20 Min auf M1 Air ≠ auf M3 Max
    - **Welche Features an waren** (`nodding_enabled`, `speaking_enabled`,
      `clip_filter_enabled`, `crossbleed_gate_enabled`) — CLIP/Nodding ändern die
      Laufzeit massiv; ohne das sind die Zahlen Rauschen
    - `app_version`
  - Ereignis: erst **nach erfolgreichem Lauf** senden (dann existieren die Daten),
    fire-and-forget — darf den Lauf **nie** blockieren oder scheitern lassen.

  **App-Seite**: `@AppStorage("analyticsConsent")` (ungefragt = nil → Prompt beim
  ersten Start), Settings-Toggle, POST via URLSession (Muster: `Feedback.swift`).
  Daten sind alle schon da: `resultStats["elapsed_s"]`, `cameraInfos`/`micInfos`
  (Dauern), `params` (Flags), `SystemInfo.deviceModel`.

  **Backend (Website-Session)**: `POST /api/telemetry` + Speicherung/Auswertung.
  Wie bei Lizenz/Feedback vorab eine **Contract-MD** schreiben (`brain/Telemetrie-API.md`).
  Alternative erwägen: fertiger Dienst (PostHog/Plausible) statt Eigenbau-Storage.

### Multilanguage (planen)
- [ ] **Mehrsprachigkeit konzipieren (DE/EN)**. Die Website ist bereits zweisprachig
  (next-intl, `src/messages/{de,en}.json`) — die App ist es **gar nicht**: alle
  Strings sind hart in Deutsch einkompiliert. Zu klären, bevor es teuer wird:
  1. **Swift-Strings**: String Catalog (`.xcstrings`) braucht Xcode-Tooling — wir
     bauen aber per SPM/`build_app.sh`. Alternative: `Localizable.strings` + `.lproj`
     in `Contents/Resources` von build_app.sh mitkopieren.
  2. **Engine-Ausgaben**: die Engine sendet deutsche Step-Labels/Fehlertexte über
     JSON-Lines. Sauber wäre: Engine sendet **Keys** (+ Parameter), Swift lokalisiert.
     → Protokoll-Änderung, siehe `brain/Engine-Protokoll.md`.
  3. **Parameter-Texte**: `ParamHelp.swift` (30 Texte) + alle Labels sind DE-only.
     Quelle `config/schemas/multicam_params.json` hat ebenfalls nur DE → Web-Modul
     müsste mitziehen, sonst driften die Sprachen auseinander.
  4. Reihenfolge/Umfang: erst EN, weil die Website EN schon anbietet und Tester/Käufer
     darüber kommen.

### 📦 Post-1.0 (geparkt)

- [ ] **Karenzzeit am Timeline-Anfang.** Beobachtung (ep04): Bei Timeline 7,6 s wird
  auf die andere Cam geschnitten, bevor der Zuschauer überhaupt jemanden gesehen hat.
  Die Erkennung war dabei **korrekt** — der Burst lag 8 s nach dem Timeline-Nullpunkt,
  ON-Mic bei −5,7 dB, conf 0,87. Es ist ein redaktionelles, kein technisches Problem.
  ⚠️ Eine Karenzzeit **existiert bereits**: PASS 2 setzt `last_cut_frame = section_start`
  und blockiert Cutaways innerhalb von `min_shot` (2,3 s). Nötig wäre nur ein größerer
  Mindestabstand für den **ersten** Schnitt — wofür es keinen belastbaren Richtwert gibt
  („der Einsatz nach Aufnahmebeginn ist immer unterschiedlich", User). Deshalb offen.
- [ ] **Reset der Analyse am Timeline-Nullpunkt.** Segmente vor Timeline-Frame 0
  überspringen, das eine überspannende vorne beschneiden. Gemessen an ep04: 20 von 370
  Segmenten liegen davor, 1 überspannt den Punkt; Ersparnis **1,5 %** der Laufzeit.
  Cutaways davor entstehen ohnehin nicht (`_to_reaction` verwirft negative Video-Frames).
  Konzeptionell sauber, praktisch marginal — und jede Frame-Arithmetik hängt daran, wo
  das WAV beginnt. Lohnt erst, wenn jemand mit stundenlangem Vorlauf auftaucht.
- [ ] Timeline-View: NLE-artige Darstellung der generierten Timeline.
  Farbkodierte Clips, Reason-Labels, scrollbar, zoombar.
  Spaeter: RMS-Wellenform, Decision-Log-Marker.
- [ ] **Mehrere Dateien einer Quelle nahtlos als eine behandeln.** User-Kontext: GoPro-Cams
  und DJI-Mic-Rekorder splitten lange Aufnahmen in mehrere Dateien (z. B. 2-h-Folge → 4
  nahtlos aneinander passende Teile). Die gehören zu EINER Person/Cam („Mic 2"), nicht zu
  vier verschiedenen. Heute sieht die App jede Datei als eigene Quelle.
  **Zu lösen:** Split-Gruppen erkennen (Namensschema / fortlaufender TC / Timestamps) oder
  manuell gruppieren lassen; die Teile für die Analyse virtuell konkatenieren (Sync + EDL
  + AAF müssen über die Segmentgrenzen stimmen). Betrifft Scan, Wizard-Zuordnung, Engine-Args.
- [ ] **AAF als Eingang statt Ordner.** Aufwand: **mittel–schwer**.
  ⚠️ **Rahmung korrigiert (21.07.):** Hier stand "ALTERNATIVE (evtl. schneller am
  Ziel)" und weiter unten, es ersetze den Sync-Umbau teilweise. Das ist FALSCH und
  hat die Priorisierung verzerrt. Es loest ein **anderes** Problem: GoPro-/DJI-Cams
  splitten lange Aufnahmen, und statt die Teile in der App zusammenzusetzen,
  bereitet der User sie im NLE vor und uebergibt eine AAF, in der jede Videospur
  EIN Clip ist. Eigene Baustelle — **kein Ersatz fuer Teil A**, das den echten
  Sync-Bug (Cams ab Nr. 3 bekommen still Offset 0) behebt.
  **Idee:** Der User sortiert und synchronisiert das Material in seinem NLE selbst und
  exportiert eine AAF, in der alle benötigten Spuren **bereits im Sync** liegen. Die App
  importiert diese AAF als Quelle — damit entfällt unser erster Workflow-Schritt
  (Waveform-Sync) komplett, und fragmentiertes GoPro-/DJI-Material ist erledigt, weil der
  User die Teile im NLE schon aneinandergelegt hat.
  **Datenmodell-Wahrheit, die daraus folgt:** Mehrere Clips auf **einer** Spur (z. B. 3
  Clips auf `V1`) sind für die Analyse **eine** Quelle. Ebenso muss mit **Lücken** in der
  Spur gerechnet werden (kein Material zu dieser Zeit).
  **Das ist der Knackpunkt:** Die gesamte Pipeline geht heute von *einer durchgehenden
  Datei je Quelle plus einem Offset* aus. Eine „Spur aus Segmenten mit Lücken" ist ein
  anderes Modell und betrifft die Frame-Rechnung überall (Source-TCs in der EDL,
  `build_aaf`, Nodding-Analyse je Clip, Diarisierung über Lückenzeiten).
  **Technisch:** AAF **lesen** können wir noch nicht (pyaaf2 kann es, wir schreiben bisher
  nur — Referenz: `brain/…` AAF-Export). Zu extrahieren: Spuren, Clips je Spur mit
  Timeline-Position + Source-Pfad + Source-In/Out. Spur → Kamera bzw. Mic mappen.
  **Reiz:** umgeht die Split-Erkennung, weil der User die Teile im NLE bereits
  aneinandergelegt hat.

### Performance: Nodding-Analyse parallelisieren — Aufwand: **mittel–schwer**
- [ ] **Kameras parallel analysieren statt nacheinander.**
  **Befund**: `run_from_bin.py` → `for i, cp in enumerate(cam_paths): run(...)` und
  `run()` macht `proc.wait()` → **strikt sequenziell**. Jede Cam ist ein eigener
  Python-Subprozess (`video_reaction_analyzer_v2.4.py`). MediaPipe läuft mit
  `BaseOptions(model_asset_path=…)` **ohne Delegate** (CPU-only) und
  `RunningMode.VIDEO` (Frame für Frame synchron). Auf einem M2 Ultra (16 P + 8 E)
  liegt damit der Großteil der Kerne brach.
  **Hebel**: bei 2 Cams fast Faktor 2, bei 3+ entsprechend mehr. Grösster verfügbarer
  Performance-Gewinn der App.
  **Kein Hebel** (geprüft): GPU-Delegate (MediaPipes Metal-Delegate ist iOS; macOS-
  Python-Wheels sind CPU-only) · `num_threads` (Tasks-API exponiert es nicht).
  **⚠️ Grad NICHT hart kodieren — und kein simpler An/Aus-Toggle.** Auf kleinen
  Maschinen kann Parallelität *schaden*:
  - **Oversubscription**: jeder Analyzer-Prozess spawnt intern schon TFLite/XNNPACK-
    Threads. N Prozesse × M Threads auf 8 Kernen → Context-Switching statt Speedup.
  - **RAM**: jeder Prozess lädt MediaPipe + Modell + Decode-Puffer erneut.
  - **Thermik**: MacBook Air (lüfterlos) drosselt unter Dauerlast — parallel kann dort
    langsamer sein als sequenziell.
  → **Auto-Grad** aus `ProcessInfo.activeProcessorCount` / P-Cores (sysctl
  `hw.perflevel0.logicalcpu`) + `physicalMemory`, optional `thermalState` beachten.
  Im **Expertenmodus** ein Override „Parallele Analyse: Auto / 1 / 2 / 4" (Grad, nicht
  Boolean — „an" ist ohne Grad bedeutungslos).
  **Vorher messen**: Wie viele Kerne zieht EIN Analyzer real? Das bestimmt den Grad.
  Die Telemetrie-Benchmarks (s.u.) liefern die Daten über echte Hardware.
  **Umbau-Kosten**: Der Fortschritt ist auf sequenzielle Steps gebaut (`Nodding×N`,
  `step_num`), das Live-Log würde zwischen Cams verschränken, und die Facemesh-
  Vorschau zeigt aktuell *eine* Cam — bei parallel muss man wählen (oder mehrere zeigen).

### CLIP-Pass: Kamera tauschen statt Cutaway verschieben (User, 22.07.)
- [ ] **Statt (nur) zeitlich zu verschieben, auf eine Kamera schalten, die die
  geflagte Person nicht zeigt.** Heute verschiebt `clip_filter_cutaways`
  (PASS 5) einen geflagten Cutaway alternierend um ±`shift_step_s`, bis das
  unerwünschte Bild (z. B. „trinkt") weg ist. Alternative ohne jede
  Zeitverschiebung: **dieselbe Zeit, andere Kamera** — eine, die die Person aus
  dem geflagten Clip NICHT enthält.
  **Passt in die Bildsprache-Mechanik:** das ist das Gegenstück zu
  `smallest_containing` — gesucht ist die (kleinste?) Kamera, deren
  Personenmenge die geflagte Person *ausschließt*. Ist es eine größere
  Einstellung, wird es zugleich ein Einsatz für Totalen/Medium.
  **Reihenfolge der Strategien** (zu entscheiden): erst Kamera-Tausch am selben
  Zeitpunkt versuchen, und nur wenn keine Kamera die Person ausschließt (oder
  keine verfügbar/gestartet ist), auf die Zeitverschiebung zurückfallen. Der
  Tausch ist der ruhigere Eingriff — er verändert den Schnittrhythmus nicht.
  ⚠️ Der neue Ziel-Clip muss selbst wieder gegen die Ignore-Liste geprüft werden
  (könnte ein anderes geflagtes Bild zeigen) — also derselbe `_clip_score`-Check
  wie heute, nur über Kamera-Kandidaten statt über Zeit-Offsets.
  ⚠️ **Ziel-Kamera ≠ Nachbarn** (User, 22.07.): Die Tausch-Kamera darf weder die
  davor noch die danach sein. Aus A-B-C darf weder A-A-C noch A-C-C werden — sonst
  entsteht ein Schnitt auf dieselbe Kamera (verschwindender bzw. sichtbarer
  Nicht-Schnitt). Dieselbe Invariante wie bei der Übergangsregel. Findet sich
  keine Kamera, die BEIDE Bedingungen erfüllt (Person ausschließen UND ≠ Nachbarn),
  → Rückfall auf die Zeitverschiebung.

- [ ] **Dock-Balken oszillieren lassen, wo die App es auch tut.** Aufwand: **mittel**.
  Regel im Fenster: `stepPercent > 0` → determinate, sonst oszillierend
  (`ContentView.swift:444-466`). Dieselbe Regel im Dock anwenden.
  ⚠️ **Haken:** `NSDockTile` animiert nicht von selbst — `DockProgressView` zeichnet
  nur, wenn `display()` gerufen wird. Ein oszillierender Balken braucht also einen
  Timer (~10–15 fps), der eine Phase weiterdreht und neu zeichnet. Der Timer **muss
  auf jedem Ausstiegspfad sterben** (fertig, Fehler, Abbruch), sonst zeichnet er nach
  dem Lauf weiter — dieselbe Fehlerklasse wie der Balken, der nach der Analyse stehen
  blieb (siehe `Bekannte-Bugs.md`).

### Metadaten-Ableitung (Recherche 25.07. — an echten Dateien geprueft)
- [ ] **Mehrspurige WAVs erkennen & je Kanal als eigene Quelle behandeln.** Aufwand:
  **mittel**. Manche Field-Recorder legen EINE WAV mit N Kanaelen an (je Kanal =
  ein Mikro). Kanalzahl lesen ist trivial (`ffprobe stream=channels`), Split in
  Mono geht per ffmpeg (`channelsplit`/`pan`) — beides verifiziert.
  ⚠️ **Blocker im aktuellen Code**: `load_audio` macht `-ac 1` (Downmix) → eine
  Mehrspur-WAV wuerde JETZT zu Mono-Matsch summiert. Noetig: >1 Kanal erkennen →
  im Wizard als N Personen-Quellen anbieten (statt 1 Datei = 1 Mic) → je Kanal
  einzeln ziehen. Kein konkreter Fall bisher → bauen, wenn echtes Material auftaucht.
- [ ] **Spurbenennung aus Recorder-Metadaten (iXML/bext) vorschlagen.** Aufwand:
  **mittel**. Field-Recorder schreiben Spurnamen in den **iXML**-Chunk
  (`<TRACK_LIST>`) bzw. eine Beschreibung in **bext**. ⚠️ `ffprobe` parst iXML
  NICHT, exiftool ist nicht gebuendelt. Leichtester Weg OHNE neue Dependency:
  kleiner RIFF-Chunk-Parser in Python (WAV oeffnen, `iXML`-Chunk finden, XML lesen)
  → Vorschlag fuer die Namen auf Seite 1 statt nur Dateiname. Haengt am Punkt darueber.
- [ ] **Kamera-Familie aus Datei-Metadaten ableiten.** Aufwand: **leicht** (Lesen),
  aber **unzuverlaessig**. Befund: DJI schreibt das Modell direkt in `format_tags:
  encoder` (echt getestet: „DJI Mini4 Pro"); GoPro/Sony/Canon legen es teils in
  eigene Atoms/Sidecar-XML (herstellerabhaengig). ⚠️ **Grosser Haken**: Dateien,
  die durch einen NLE/Export liefen, haben die Kamera-Metadaten VERLOREN (die
  FX3-Datei zeigt „DaVinci Resolve" statt Sony). Nur Kamera-**Originale** tragen es
  zuverlaessig → „erkannt/nicht erkannt" muss ehrlich kommuniziert werden.

- [ ] Einzeldateien importieren: Statt nur Ordner, auch einzelne Video-/Audio-Files
  per Drag & Drop oder Finder-Dialog hinzufügen. Für gemischte Quellpfade.
  .multicam müsste dann an zentralem Ort liegen (z.B. ~/Library/Application Support/)
  und bei AAF-Export nach Speicherort fragen.
- [ ] Workflow fortsetzen: Fortschritt in .multicam speichern.
  "Fortsetzen"-Toggle bei erneutem Laden. Dialog ob Dateien geaendert.
- [ ] Refresh-Trigger verfeinern: still im Hintergrund erneuern wenn Lease bald
  abläuft (aktuell erneuert jeder validate()-Call bei App-Start).
- [ ] **Personen-Modell — weitere Stufen.** Stufe 1 (abgeleitetes Modell + Wizard) ist LIVE. Offen: eigenständiger Personenname (heute = Mic-Name), Rollen an der Person, Zuordnung aus der Personen-Sicht, Totale↔Person, sowie die freigeschaltete Cutaway-Art „Bildgrößen-Wechsel am sprechenden Menschen". Volle Historie/Design-Entscheidungen im Archiv (`brain/TODOs-Archiv.md`).
