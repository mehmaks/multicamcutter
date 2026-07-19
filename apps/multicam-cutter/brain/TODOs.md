# TODOs

## Offen

### UI / UX
- [x] Settings-Page (Cmd+,): Allgemein (Expertenmodus) + Lizenz (Status, Datei laden)
- [x] "Über MulticamCutter"-Dialog: Version 0.1.0, Copyright
- [x] Expertenmodus: Alle Parameter aus dem Web-UI Schema exposed
- [x] Progress-View: Live Facemesh-Frame aus laufender Nodding-Analyse
- [x] **Toggle „Kontrastkorrektur der Thumbnails"** (Settings → Allgemein). UMGESETZT:
  `@AppStorage("thumbnailAutoContrast")`, Toggle in `GeneralSettingsTab`,
  CoreImage-`autoAdjustmentFilters` beim Bild-Entstehen in `ScrubbableThumbnail`
  (Initial-Load off-main gecacht + Scrub-Frames), wirkt live. Rein kosmetisch.
  **Warum**: Log-Footage sieht als Thumbnail flach/tot aus. Bei aktiviertem Toggle
  eine einfache Auto-Kontrast-Korrektur auf die Thumbnails legen — **auch beim
  Scrubbing**.
  **Gute Nachricht — nur ein Eingriffspunkt**: In `ScrubbableThumbnail` laufen
  *beide* Bildquellen (Engine-JPG via `NSImage(contentsOfFile:)` **und** die
  Scrub-Frames aus `AVAssetImageGenerator`) durch `displayImage` → ein einziges
  `Image(nsImage:)`. Also:
  - **Engine bleibt unangetastet** (kein ffmpeg-Filter, kein `--flag`, kein Re-Scan).
  - Toggle wirkt **live** — Umschalten rendert sofort neu.
  - Rein kosmetisch: Analyse, CLIP-Prüfung und AAF-Export bleiben unberührt.
  **Umsetzung**:
  - `@AppStorage("thumbnailAutoContrast")` (Muster wie `expertMode`) + Toggle in
    `GeneralSettingsTab`; `ScrubbableThumbnail` liest denselben Key.
  - Filter via CoreImage: Start mit `CIImage.autoAdjustmentFilters(options:)`
    (Auto-Enhance: Tone-Curve/Vibrance, passt sich pro Bild an). Reicht das bei Log
    nicht, echtes Auto-Levels: `CIAreaMinMax` → `CIToneCurve`/`CIColorPolynomial`
    (Histogramm-Spreizung).
  ⚠️ **Performance**: NICHT in `displayImage` filtern — die computed property läuft
  bei **jedem** Render (liest das JPG jetzt schon jedes Mal neu von Platte). Den
  Filter dort anwenden, wo das `NSImage` **entsteht** (`extractFrame` + Laden des
  Initial-Thumbnails) und das Ergebnis cachen, sonst ruckelt das Scrubbing.
  Aufwand: **leicht–mittel**.
- [x] **Quelldateien-Panel rechts (`.inspector`) mit Include-Checkboxen**.
  Panel listet ALLE gescannten Quellen (Kameras + Mikrofone) mit Checkbox; Canvas
  zeigt nur die aktivierten Cams. Deaktivierte Quellen sind auch für die **Analyse**
  nicht vorhanden. Deaktiviertes Video gibt seine Mics zurück nach „Nicht zugeordnet",
  deaktiviertes Mic löst sich von seiner Kamera. `included` wird in `.multicam`
  persistiert (alte Sessions ohne das Feld → Default `true`).
  Toolbar-Button (`sidebar.right`) blendet das Panel ein/aus, Zustand via `@AppStorage`.
  **Ersetzt das destruktive Entf** (ausgebaut) und schließt die Lücke „Mics nicht
  entfernbar". Start-Gating erweitert: min. 2 aktive Cams + 1 aktives Mic.
  ⚠️ **Erforderte einen Engine-Contract-Umbau** — die Engine scannte den Ordner selbst
  und hätte deaktivierte Dateien wieder eingesammelt. Siehe `brain/Engine-Protokoll.md`
  → „Explizite Quelllisten". Merke: **nach Engine-Änderungen PyInstaller neu bauen**,
  build_app.sh kopiert nur das vorhandene `dist/multicam-engine`.
- [ ] Timeline-View: NLE-artige Darstellung der generierten Timeline.
  Farbkodierte Clips, Reason-Labels, scrollbar, zoombar.
  Spaeter: RMS-Wellenform, Decision-Log-Marker.
- [x] Bug-Report / Feedback (App-Seite): Formular-Sheet (`Feedback.swift`),
  erreichbar über Overlay-Button (immer sichtbar), Menü „Hilfe > Fehler melden"
  und Button im Fehler-Screen (vorbefüllt mit Fehlermeldung + Log). Hängt
  Analyse-Log (JSONL/stdout, Toggle) + System-Infos an. POST an `/api/feedback`
  (URL aus `LicenseConfig.apiBase`), Erfolg zeigt Issue-Link, Fehler → „Details
  kopieren"-Fallback. Kein Screenshot/keine .multicam (bewusst).
  **Backend LIVE** (Website-Session): `/api/feedback` legt GitHub Issues in
  `mehmaks/resolve-toolkit` an (Labels `bug`/`feedback` + `from-app`), Env-Vars
  gesetzt, verifiziert (leeres Payload → 400 Validierung statt 500). Große Logs
  gehen als Issue-Kommentare statt Gist (für die App identisch). `x-feedback-token`
  ist AUS → App sendet keinen Header, passt. Rate-Limit 8/10 min pro IP.
  → **Workflow ist damit end-to-end fertig**, ohne App-Rebuild (URL kommt zur
  Laufzeit aus `LicenseConfig.apiBase`). Details: `brain/Feedback-API.md`.
- [x] Log-View: Analysiere-Zeilen gefiltert (Progress-Bar zeigt Fortschritt)

### 🔴 N-Sprecher-Diarisierung (3+ Personen) — PRIORISIERT (Engine) — Aufwand: **mittel**
- [ ] **Basis-EDL von binär (2 Cams) auf N-fach umstellen.** User-Kontext: Podcast hat
  **häufig Host + 2 Gäste = 3 Personen**, also kein Edge-Case.
  **Ist-Zustand:** `build_base_edl_from_audio.py` (`rms_diarize`, ~:67-93) vergleicht nur
  `rms1` (Mics von `cam_paths[0]`) vs `rms2` (`cam_paths[1]`) → Label `CAM1`/`CAM2`.
  `run_from_bin.py:546-557` speist genau zwei Seiten. Personen auf Cams ab Index 2
  werden von der Basis-EDL **nie als Sprecher** gewählt (nur als Cutaway/Totale sichtbar).
  **Ziel:** pro Zeitfenster das **lauteste Mic** (bzw. dessen Person) bestimmen → deren
  engste Cam (via Personen-Modell / `shotLadder`) als Sprecher-Shot. Argmax über N Mics
  statt Differenz zweier Summen.
  **⚠️ Berührt den geteilten Kern** (`modules/multicam_cutter`, auch Web-Modul) → sorgfältig
  + testen. Das Personen-Modell (Person=Mic, Person→Cams) liefert die nötige Zuordnung frei Haus.
  **Reihenfolge:** NACH der Wizard-Validierung (erst End-to-End-Analyse bestätigen).
  **✅ Empirisch (18.07.):** 3 Personen werden KORREKT geschnitten, wenn 2 sich eine Cam
  teilen (Host-Cam + Gast-2-Shot) — dann effektiv binär (Host-Seite vs Gast-Seite). Die
  Grenze greift NUR bei **3+ Personen mit je EIGENER Cam**.

### 🟠 Datei-Splits als EINE logische Quelle — Aufwand: **mittel**
- [ ] **Mehrere Dateien einer Quelle nahtlos als eine behandeln.** User-Kontext: GoPro-Cams
  und DJI-Mic-Rekorder splitten lange Aufnahmen in mehrere Dateien (z. B. 2-h-Folge → 4
  nahtlos aneinander passende Teile). Die gehören zu EINER Person/Cam („Mic 2"), nicht zu
  vier verschiedenen. Heute sieht die App jede Datei als eigene Quelle.
  **Zu lösen:** Split-Gruppen erkennen (Namensschema / fortlaufender TC / Timestamps) oder
  manuell gruppieren lassen; die Teile für die Analyse virtuell konkatenieren (Sync + EDL
  + AAF müssen über die Segmentgrenzen stimmen). Betrifft Scan, Wizard-Zuordnung, Engine-Args.

### 🟡 Sync-Robustheit: gegen Mics statt gegen CAM1 — Aufwand: **mittel**
- [ ] **Sync-Referenz überdenken.** Heute ist `cam_paths[0]` (erste Cam) der EINZIGE
  Sync-Anker (`shared/waveform_sync.py:183` „CAM1 is always 0"); alles hängt an Qualität/
  Länge dieser einen Cam-Tonspur. Fragil — siehe abgeschnittener-Host-Bug (18.07., beide
  Symptome, AAF-Link + Gast-Sync, hatten diese eine Wurzel). Robuster: gegen die sauberen,
  vollen **Mic-Spuren** synchronisieren. Der Swift-Ordnungs-Fix (Close-Cams zuerst) entschärft.

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

### Versionierung
- [x] **Echte Versionierung** (`build_app.sh`): `MARKETING_VERSION` per Hand,
  `CFBundleVersion` = UTC-Zeitstempel (monoton **und** pro Build eindeutig),
  neuer `GitCommit`-Key (Kurz-SHA + `-dirty`). Über-Dialog + Bug-Reports zeigen
  `Version 0.2.0 (202607170939) · 95130e5-dirty`. Details: `brain/Distribution-Setup.md`.
  ⚠️ Deckte auf: mit dem alten harten `CFBundleVersion 1` hätte **Sparkle nie ein
  Update ausgeliefert** — es vergleicht genau dieses Feld.

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

### CLIP-Einstellungen
- [x] **Settings-Tab „CLIP"** — UMGESETZT (immer sichtbar als 3. Tab; der frühere
  „nur im Expertenmodus"-Plan ist obsolet, seit der globale Expertenmodus weg ist).
  1. **Prompt-Editor**: zwei Editoren (Ignorieren/Neutral, ein Prompt je Zeile).
     Speichert nach `~/Library/Application Support/MulticamCutter/clip_prompts.json`;
     Engine bevorzugt diese Datei via `shared.paths.effective_clip_prompts_path()`
     (in `run_from_bin.py`), sonst gebündelte `config/clip_ignore_prompts.json`.
     „Auf Standard zurücksetzen" löscht die User-Datei.
  2. **Modell-Status + Download**: „geladen/nicht geladen" + Button, Inline-Progress.
     Nutzt `--check-clip-model` / `--download-clip-model` (neue `downloadClipModel()`
     ohne Analyse-Start).
  Neues Engine-Kommando `--get-clip-prompts` (JSON: ignore/neutral/source/user_path).
  ⚠️ **Braucht PyInstaller-Rebuild**, bevor es im ausgelieferten App-Bundle wirkt
  (Dev via `swift run` nutzt den Python-Quellcode → funktioniert sofort).
- [x] **Settings-Fenster ist noch blau**: GELÖST — `.tint(.brandAccent)` auf dem
  `TabView` in `SettingsView`. Tab-Icons/Labels nutzen jetzt Lime statt System-Blau.

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

### Parameter / Settings
- [ ] **Settings-Durchgang mit User**: alle Parameter durchgehen, Sortierung +
  Benennung in der UI überarbeiten (Labels, Gruppierung, Reihenfolge, welche
  Basis vs. Experte). Referenz für Namen/Reihenfolge: `config/schemas/multicam_params.json`.
- [x] `gate_use_filtered` nachgerüstet (Toggle „Gate-Audio in Timeline" im
  Crossbleed-Filter, Debug-Option). War der einzige Web-Parameter, den die App
  nicht kannte. In `toJSON()` (Engine!), `toDict()`, `apply()` + UI verdrahtet.
- [x] (?)-Tooltips an allen 30 Parametern (`ParamHelp.swift`), Texte verbatim aus
  `config/schemas/multicam_params.json`. Gotcha: `.help()` allein zeigt nichts →
  AppKit-`NSView.toolTip`-Overlay. Verzögerung via `NSInitialToolTipDelay` = 200 ms.

### Workflow
- [x] **FPS-Mismatch: Fehler anzeigen + Analyse blockieren + Inline-Konvertierung**
  UMGESETZT: Scan liefert `fps` pro Cam (ffprobe `r_frame_rate`, 0 = unlesbar),
  `EngineController.fpsMismatches`, Warnbanner mit betroffenen Cams, Start blockiert,
  Konvertier-Button → Engine `--convert-fps` mit Live-Log-Sheet, danach Re-Scan.
  FPS steht auch im Quelldateien-Panel („30 fps ≠ 25" orange).
  **TC-Erhalt verifiziert**: 30→25 fps behält den Timecode auf Video- UND tmcd-Spur.
  ⚠️ Noch offen: Zusammenführung mit dem alten Engine-Check (Exit-Code 42) — s.u.
- [ ] ~~ALT~~ (Doppel-Eintrag, s.o.)
  (Port aus dem Web-Modul: `ui/pages/multicam.py` ~1003–1140 + `_run_ffmpeg_conversions`).
  **Warum**: Weichen Source-FPS von der Timeline-FPS ab, rechnet die EDL/AAF-Pipeline
  mit falschen Source-Frames → Audio/Video-Drift + Standbild am Timeline-Ende
  (im Web dokumentiert als „Resolve-Auto-Speed-Adaption-Bug").
  **Verhalten (wie im Web):**
  1. Erkennung pro Cam: `abs(cam_fps - timeline_fps) > 0.01` → Mismatch; nicht
     lesbare FPS (0) zählt ebenfalls als Mismatch.
  2. Fehler mit Liste der betroffenen Cams (Name + FPS); **„Analyse starten"
     deaktiviert**, solange Mismatches bestehen.
  3. Button „Datei(en) auf Timeline-FPS konvertieren" → ffmpeg im Hintergrund mit
     Live-Log (dauert: ~10er-Minuten pro GB), danach **Re-Scan** für frische FPS.
  **ffmpeg-Rezept (aus dem Web übernehmen):**
  `-vf fps=<target>` · `-c:v libx264 -pix_fmt yuv422p10le -profile:v high422
  -crf 14 -preset medium` (praktisch verlustfrei, behält die Pro-Color-Reserve) ·
  `-c:a aac -b:a 192k` · Ziel `<stem>_<fps>fps.<ext>` neben dem Original.
  ⚠️ **Kritisch**: Embedded TC des Originals per ffprobe lesen und via
  `-metadata timecode=…` **+** `-metadata:s:v:0 timecode=…` erhalten — sonst bricht
  die Source-Frame-Berechnung (bekannter Bug „Cam-Cutaways verschoben bei fehlendem
  embedded TC", siehe modules/multicam_cutter/CLAUDE.md → Gotchas).
  **App-seitig nötig:**
  - Engine-Scan muss **FPS pro Cam** liefern (aktuell nur `duration_s`/`thumbnail`;
    ffprobe `r_frame_rate` ergänzen) → neues Feld `CameraInfo.fps` in Swift.
  - Gebündeltes ffmpeg kann encoden (`--enable-gpl --enable-libx264`) ✓ → die
    Konvertierung läuft auch in der verteilten App.
- [~] **„Personen" als erstklassiges Konzept** (UI-Modell-Umbau) — Aufwand: **schwer**.
  **🟢 Stufe 1 begonnen (17.07.):** `Person` ist als **abgeleitetes** Modell da
  (`EngineController.persons` — eine Person je aktivem Mic, Name = Mic-Anzeigename,
  Kameras = aktive Cams mit diesem Mic in `assignedMics`). Rein lesende Sicht auf
  denselben Cam↔Mic-Graphen → **Engine-Kontrakt unangetastet** (weiter `--cam-mics`
  + `--cam-types`), Null Pipeline-Risiko. Der rechte Inspector hat jetzt zwei Reiter
  **„Quellen | Personen"** (`InspectorPanel`); `PersonsInspector` gruppiert nach
  Person und zeigt „Geteilte Totalen" + „Ohne Person". `sharedWideCams` = Totale
  ohne Mic. Zuordnen läuft weiter per Drag&Drop auf dem Canvas.
  **Noch offen (nächste Stufen):** eigenständiger Personenname (heute = Mic-Name) ·
  Zuordnung aus der Personen-Sicht heraus · Rollen an der Person · Totale↔Person
  (schaltet Bildgrößen-Wechsel + Mehr-Totalen-Auswahl frei, s. u.).

  **✅ WIZARD GEBAUT & LIVE (17.07., Phase 2+3):** `WizardView.swift` ersetzt im
  `.ready`-Zustand den alten Canvas/Inspector/Sidebar (`SetupView` wird nur noch
  umgangen, NICHT entfernt = Phase 4). Drei Screens im Dummy-Look: Personen (Avatar-
  Farben, Name editierbar, Play/RMS-Vorschau, Trash = Mic ausschließen) · Kameras
  (Drag&Drop + Klick, MEHRFACH pro Person, live abgeleitete Nah/Totale-Pill via
  `camRoles()`, „zeigt alle", Cam-Trash) · Übersicht (Bildgrößen-Leiter je Person,
  Kamera-Zusammenfassung, „Automatisch erkannt"-Box, Einstellungen).
  Modell-Ergänzungen: `addPersonToCam`/`removePersonFromCam`/`setCamShowsAllPersons`
  (Multi-Cam!), `wizardStep`, `camRoles()`/`shotLadder()`/`deletePerson()`. Engine:
  `--cam-types` kommt jetzt aus `camRoles()`. Einstellungen (Variante C): 2-spaltige
  Slider/Toggles + „Experteneinstellungen"-Swap auf die volle gruppierte Liste (kein
  Expert-Toggle mehr). Eigene Palette in Theme.swift (`wizBg…wizText`, grün-getönt),
  custom Slider/Toggle/Buttons, natives Preset-Dropdown, transparente dunkle Titelleiste
  (App-Titel oben, Episode im Header + Stift), Fenster wächst auf Screen 3 (940px).
  **✅ Engine-Verifikation ERLEDIGT (Phase 4, per Recherche-Agent):** Mehrfach-
  Zuordnung (ein Mic auf mehreren Cams) ist SICHER — keine globale `mic→cam`-Map;
  `--cam-mics` = unabhängige Liste pro Cam; `max_faces` = Mics-pro-Cam (Totale
  korrekt); Cutaway-Pass nutzt Mics gar nicht. **ABER:** die Basis-EDL diarisiert
  BINÄR die ERSTEN ZWEI `--cams` (RMS CAM1 vs CAM2 — run_from_bin.py:546-557 →
  build_base_edl_from_audio.py:67-93). Die zwei müssen disjunkte Mic-Sets sein und
  dürfen NICHT die Totale sein (summiert alle Mics → Diarisierung kippt).
  **Fix umgesetzt (Swift, keine Engine-Änderung):** `orderedAnalysisCams` sortiert
  Close-Cams zuerst, Totalen ans Ende → Diarisierungs-Paar = garantiert zwei Closes;
  ALLE positionalen Args nutzen diese Ordnung (verändert nur die AAF-Track-Reihenfolge).
  **Bekannte Engine-Grenze (vorbestehend, nicht neu):** Basis-EDL ist 2-Sprecher-binär;
  3+ Personen bzw. 2-Shot-ohne-Solo-Cam haben inhärente Grenzen → späteres Engine-Thema.
  **✅ Phase 4 ERLEDIGT (18.07.):** Alter toter Code entfernt (~850 Zeilen) — SetupView,
  InspectorPanel/PersonsInspector/SourcesInspector, CameraCard, MicPill, ParameterForm/
  ParameterRow, PresetPicker (ContentView 1403→555 Zeilen), sowie `isWide`/`setCamWide`/
  `sharedWideCams`/`ignoredCams` + is_wide-Persistenz aus EngineController. Build grün.
  Commits: `95ecfed` (Wizard) + `64be61b` (Cleanup).
  ⚠️ **Doku-Schuld:** `brain/UI-Komponenten.md` beschreibt noch die entfernten Views
  (SetupView, Inspector, CameraCard, MicPill) → müsste auf den Wizard umgeschrieben werden.
  **Phase 5 OFFEN:** Wizard bei vorhandener `.multicam`-Zuordnung überspringen → Übersicht.

  **🔒 GELOCKTE DESIGN-ENTSCHEIDUNG (17.07., mit User) — Zuordnungs-Wizard (KISS):**
  Der rohe Personen-Reiter ist Erst-Usern zu undurchsichtig → ersetzt durch einen
  geführten **Wizard mit 2 echten Schritten + Übersicht** (reine Präsentationsschicht
  über demselben Graphen, KEINE Engine-/Modell-Änderung):
  1. **Personen benennen** — 1 Person = **genau 1 Mic** (starr, kein „schätzen", kein
     „+"). Nicht-Sprecher-Mic (Raum/Ambience) per Trashbin **wegwerfbar** → fällt aus
     der Analyse. Kopftext 2-3 Sätze („Benenne deine Sprecher:innen").
  2. **Personen auf Kameras ziehen** — Person auf jede Cam, die sie zeigt (Graph =
     `cam.assignedMics`). Mehrfach-Zuordnung erlaubt. Für die Raum-Cam eine „zeigt
     alle"-Abkürzung (sonst N Einzel-Drags).
  3. **Übersicht & Start** — zeigt die ABGELEITETE Klassifizierung sichtbar (kein
     Black-Box), bleibt editierbar, trägt den „Analyse starten"-Button.
  **Kein manueller Totale-Toggle mehr** (der von vorgestern **entfällt**) — Bildgröße
  wird **programmatisch** aus dem Graphen abgeleitet:
  - Für jede Person P: ihre Kameras nach Personen-Anzahl aufsteigend sortiert =
    Bildgrößen-Leiter (engste zuerst). Die engste = P's Close/Primärbild — auch die
    korrekte Quell-Cam für den Sprecher-Schnitt, wenn P keine Solo-Cam hat.
  - **Totale-Regel (präzise):** Eine Cam ist Totale, wenn JEDE Person darauf woanders
    eine engere Cam hat. Ist sie für ≥1 Person die engste, ist sie ein **Close**
    („Close gewinnt"). Reine Totale = für NIEMANDEN die engste (Raum-/Alle-Cam).
    → Gegenbeispiel {P2,P3} ohne andere Cam = Close (nicht Totale), weil engste für beide.
  - Nuance: dieselbe Cam kann für P3 Close und für P1/P2 Totale sein (Gast nur im
    Gruppenbild). Binäres Engine-Flag = „Close gewinnt"; die personen-relative
    Wahrheit steckt im Graphen (fürs spätere Bildgrößen-Feature). Übersicht macht's sichtbar.
  - **Heute (binäre Engine):** `isWide(C) = alle Personen auf C sind woanders enger`
    → speist `--cam-types`. Totale-**Pill** auf der Card wird daraus **abgeleitet + live**
    aktualisiert (kein Toggle).
  **Layout-Entscheidungen (17.07., aus Dummy-Feedback — 🔒 Variante C):**
  - **Rechter Inspector (Quellen/Personen) entfällt** — der Wizard ersetzt ihn.
  - **Linke Parameter-Sidebar entfällt KOMPLETT** (nicht nur eingeklappt).
  - **Expertenmodus-Toggle entfällt** — keine versteckte globale Modus-Umschaltung mehr.
  - **Einstellungen leben auf dem Übersichts-Screen (3):** eine kurze, kuratierte
    **Einfach-Liste** (~8 Parameter) ist immer sichtbar. Textlink **„Experteneinstellungen"**
    **TAUSCHT den ganzen Panel-Inhalt** (View-Swap, KEIN Anhängen!) gegen die **volle
    Liste in ihren echten Rubriken** (Schnittregeln, Sprecher-Erkennung, Pausen,
    Reaktionen & Cutaways, Crossbleed-Gate, Totale) — dieselben Parameter, andere
    Position/Gruppe (z. B. Reaktionslänge in Einfach an 2., in Experte unter
    „Schnittregeln"). Experten-Liste scrollbar. Zurück per „Einfache Ansicht".
    ⚠️ Wichtig: Einfach- und Experten-Ansicht müssen an **denselben Parameter-State**
    schreiben — es sind zwei Darstellungen desselben Modells, keine zwei Wertesätze.
  - **Preset-Dropdown** sitzt im Footer **links neben „Analyse starten"** (fühlt sich
    als Teil der Start-Aktion richtiger an als im Einstellungs-Kopf).
  - **Parameter 2-spaltig** — Label und Wert liegen nah beieinander, nutzt die App-Breite
    (statt schmaler Liste mit weiten Lücken). Auf schmalen Fenstern → 1 Spalte.
  - **Re-Edit** über die Wizard-Schritte (Stepper), nicht über einen Inspector.
    Bei vorhandener `.multicam`-Zuordnung Wizard überspringen → direkt Übersicht.
  - Screen 1 behält die **Audio-Vorschau** je Person (Play, ab erster lauter Stelle,
    nur eine Spur gleichzeitig — wie bisher `toggleMicPreview` / RMS-Dominanz).
  - Klick-Dummy (Referenz-Layout): claude.ai/code/artifact/14554cb8-e137-4fcd-8134-8ecb743e3b96
  **⚠️ Offene Enden durch den Wegfall von Expertenmodus + Sidebar:**
  - Der geplante **CLIP-Prompt-Editor** war „nur im Expertenmodus" gedacht — braucht
    jetzt eine neue Heimat (hinter „Experteneinstellungen" oder im Settings-Fenster Cmd+,).
  - **Preset-Verwaltung** (eigene speichern/exportieren) lag konzeptuell in der Sidebar
    → braucht einen Platz neben dem Preset-Dropdown (z. B. „Preset speichern …").

  **Idee (User)**: Beim Import legt die App pro Mikrofon automatisch eine **Person** an
  (Pill/Circle-Icon). Statt Mics auf Videos zu ziehen, zieht man **Personen** auf Mics
  **und** auf Videos → visuell: wer ist **wo zu sehen** und **wo zu hören**.
  **Warum das besser ist**: Wir modellieren aktuell *Dateien* (Mic gehoert zu Cam).
  Die Domaene sind aber **Personen** — Cams zeigen sie, Mics hoeren sie.
  💡 **Die Pipeline denkt insgeheim schon so**: `max_faces` pro Cam wird aus der
  **Mic-Anzahl** der Cam abgeleitet (Commit „max_faces pro Cam aus MIC-Zuordnung
  ableiten") — „Mics auf einer Cam" heisst dort also laengst „Personen auf dieser Cam".
  Das Personen-Modell macht das nur explizit.
  **Loest den Totale-Bedeutungskonflikt elegant**: Eine Totale ist dann einfach eine Cam
  mit **mehreren** Personen — kein Semantik-Bruch mehr noetig (siehe Stufe 2 unten).
  **Engine bleibt unangetastet (Stufe 1)**: `--cam-mics` ist weiter Mic-Positionen pro
  Cam → Ableitung: Cam → Personen → deren Mics. Gleiches Format, nur andere Herkunft.
  **Zu klaeren**: Migration bestehender `.multicam` (Personen aus vorhandenen
  Mic→Cam-Zuordnungen ableiten) · Person ohne Mic / Mic ohne Person · Benennung
  (Personenname wird die natuerliche Beschriftung statt „Cam Gast"/„Mic Gast" getrennt).

  **🔓 Schaltet eine neue Cutaway-Art frei (User-Idee): Bildgroessen-Wechsel am
  sprechenden Menschen.** Bisher heisst Cutaway immer „weg vom Sprecher, hin zum
  Zuhoerer". Neu waere: **beim Sprecher bleiben, aber die Bildgroesse wechseln** —
  P1s Redebeitrag wird dynamisch geteilt in „P1 spricht, close" und „P1 spricht,
  totaler". Macht den Schnitt lebendig, ohne die Aufmerksamkeit vom Redner zu nehmen.
  **Warum das Personen braucht**: Die Pipeline muss wissen, **welche Cams P1 zeigen**
  (Close *und* Totale). Heute weiss eine Totale gar nichts ueber Personen — man koennte
  nicht mal pruefen, ob sie den aktuellen Sprecher im Bild hat. Mit Personen ist es ein
  Lookup: Person → alle Cams, die sie zeigen.
  **Umsetzung**: neuer Event-Typ (neben `speaker`/`reaction_nodding`/`max_time`) im
  Cutaway-Pass, NICHT in der Base-EDL (die kommt aus der Sprechererkennung; hier wird
  ein bestehendes Sprecher-Segment nur unterteilt). Parameter noetig: Haeufigkeit,
  Mindestdauer je Bildgroesse. ⚠️ Beruehrt `add_reactions_to_edl.py` → Guardrail
  beachten: **Pass-Reihenfolge nicht aendern**.

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

- [ ] Einzeldateien importieren: Statt nur Ordner, auch einzelne Video-/Audio-Files
  per Drag & Drop oder Finder-Dialog hinzufügen. Für gemischte Quellpfade.
  .multicam müsste dann an zentralem Ort liegen (z.B. ~/Library/Application Support/)
  und bei AAF-Export nach Speicherort fragen.
- [x] ~~Dateien aus Projekt entfernen: Selektiertes Item in **Sidebar** per Entf~~
  → **hinfällig**: beschrieb eine alte UI, in der Dateien in der Sidebar standen.
  Die Sidebar enthält heute nur Episode + Parameter; die Absicht ist durch
  „Entf/Backspace auf selektierter Card" bereits erfüllt.
  (Verbleibende Lücke, falls je gewünscht: **Mic-Dateien** lassen sich nur
  *zuordnen/lösen*, nicht ganz aus dem Projekt entfernen.)
- [ ] Workflow fortsetzen: Fortschritt in .multicam speichern.
  "Fortsetzen"-Toggle bei erneutem Laden. Dialog ob Dateien geaendert.
- [x] AAF-Metadaten: Autor, Beschreibung, Version, Datum in comp.comments
- [x] Dateien aus Projekt entfernen (Entf/Backspace auf selektierter Card)
- [x] **Kamera-Totale-Markierung** (`isWide`): Rechtsklick auf der Card →
  Toggle „Als Totale markieren", orange Pill oben rechts. Persistiert als
  `is_wide` in `.multicam`. **Auto-Totale entfernt**: `--cam-types` kommt aus der
  Markierung statt aus `assignedMics.isEmpty ? "wide" : "close"`. Vorher wurde jede
  Cam ohne Mic still zur Totale erklärt.
  `analysisCams` = aktiviert UND (Mic ODER Totale) → Cams ohne beides werden der
  Engine gar nicht übergeben. Die Card sagt das offen („Wird ignoriert — kein Mic,
  keine Totale"). Start-Gating: min. 2 `analysisCams`.
  **Nachtrag (17.07.):** Host/Gast waren nur Deko und taten nachweislich nichts
  (an der einzigen Engine-Stelle wurde alles ≠ wide zu `close` eingedampft) →
  **entfernt**. `CamTag`-Enum weg, `tag: CamTag` → `isWide: Bool`. Der 150 %-Zoom
  war zudem noch aktiv (Aufrufer-Default `wide_zoom=1.5` in `multicam_engine.py`
  + `run_from_folder.py`) → **auf 1.0 gesetzt**, damit die Zoom-Streichung wirklich greift.
- [x] Totale-Hinweis-Pill auf Cams ohne Mic (wenn alle Mics zugeordnet) — wird ersetzt durch Tag-System

### Lizenz / Abo (LemonSqueezy + signierte Lease, MODE=remote)
Siehe brain/Entscheidungen.md → "Lizenzmodell: Abo via LemonSqueezy".
- [x] API-Contract-Spec für Backend (brain/Lizenz-API.md) — inkl. Test-Vektor
- [x] `license.py`: signierte Lease verifizieren (Signatur + Gerätebindung +
  Ablauf), cachen, Offline-Grace bis Lease-Ablauf. activate/validate-Flow mit
  activation_id. `set_license_key()`. 15/15 Core-Tests grün.
- [x] Engine-CLI `--set-key` (ruft `set_license_key`) + JSON-Ausgabe mit grace
- [x] Swift Key-Eingabe-UI im Lizenz-Tab (Aktivieren, Status inkl. grace/offline)
- [x] LicenseConfig.swift: setzt `TOOLKIT_LICENSE_MODE=remote` + `TOOLKIT_LICENSE_API`
  auf allen Engine-Launches (Dev-Override respektiert). Plumbing smoke-getestet.
- [x] Backend-URL `https://multicamcutter.pantake.com` + Pfade `/api/license/*`
  in `LicenseConfig.swift` + `license.py`
- [x] E2E verifiziert: Testkauf → Key → activate → signierte Lease → validate +
  Offline-Grace. Gerät aktiviert (Lease bis 2026-07-30).
- [x] Bundle-Rebuild (PyInstaller + build_app.sh): neue license.py + --set-key +
  cryptography/requests im Bundle. Frozen Engine verifiziert Signaturen (online
  + offline-grace). Kein Private-Key im Bundle. Frischer .app-Build startet.
- [x] Abo-Datumsanzeige forward-compatible (renews_at/ends_at/sub_status).
  Zeigt sobald Backend den `subscription`-Block liefert (Spec in Lizenz-API.md).
- [x] Free-Tier-Gate: ohne gültige Lizenz längste Quelldatei > 30 Min → Pipeline
  bricht mit Upgrade-Hinweis ab (`_enforce_free_tier` in run_pipeline, vor Sync).
  Grenze `>` (genau 30 Min erlaubt). 4/4 Logiktests grün.
- [x] Deaktivieren: license.py `clear_license()` (lokal löschen + best-effort
  Server-Deactivate/Self-Leave), Engine `--clear-license`, Swift-UI (Button in
  der aktiven Card; Key-Eingabe erscheint wieder). Backend-Endpoint deployt.
- [x] Produkt-Brief (brain/Produkt-Brief.md) für Website-Texte
- [x] Geräte-Umzug ("Auf dieses Gerät umziehen"): bei `activation_limit`
  erscheint der Umzugs-Button → `migrate_license_key` (Takeover via device_id +
  reaktivieren). Engine `--migrate-key`, LicenseInfo.status durchgereicht.
- [x] Abo-Datum LIVE: Backend liefert `subscription`-Block (renews_at etc.) —
  App zeigt „Verlängert sich am …" (verifiziert: renews_at 2027-07-16).
- [x] Deaktivieren: Bestätigungsdialog (`confirmationDialog`, destruktiv) — erklärt,
  dass der Server-Slot frei wird und die Lizenz jederzeit neu aktivierbar ist.
- [ ] Refresh-Trigger verfeinern: still im Hintergrund erneuern wenn Lease bald
  abläuft (aktuell erneuert jeder validate()-Call bei App-Start).

### Website / Lizenz-Shop
**Alles hier liegt bei der Website-Session** (Repo `multicamcutter-web`), nicht bei uns.
- [x] Stack/Anbieter entschieden: **LemonSqueezy** (Merchant of Record) — live, E2E verifiziert
- [~] Landing Page + Lizenz-Shop: laut `multicamcutter-web/design.md` gebaut
  (Home/Pricing/Download/FAQ, DE/EN) — Stand dort erfragen
- [x] **`/api/feedback` → GitHub Issue** — LIVE, Env-Vars gesetzt, verifiziert.
  Issues landen in `mehmaks/resolve-toolkit`. Kein App-Rebuild nötig war.
- [ ] **`appcast.xml` hosten** (Contract: `brain/Appcast-Hosting.md`) — blockiert Auto-Update

### Design
- [x] **Log-Fenster** (`LogWindow.swift`): eigene `Window`-Scene, **Cmd+L**, landet
  automatisch im „Fenster"-Menü. Zeigt den laufenden Engine-Output, bleibt offen —
  auch nach Fehler und nach Analyse-Ende (vorher war das Log im ErrorView schlicht weg,
  obwohl es dann am wichtigsten ist). Buttons: „Kopieren" + **„Log-Ordner öffnen"**.
  **Historie kommt aus Dateien, nicht aus dem Speicher**: Die Engine schrieb schon
  immer pro Lauf ein JSONL nach `~/Library/Logs/MulticamCutter/` (macOS-Standardort,
  Console.app sieht ihn) — es fehlte nur der Zugang aus der App.
  `EngineController.logDirectory` muss mit `log_dir` in multicam_engine.py übereinstimmen.
- [ ] **Log-Retention**: `~/Library/Logs/MulticamCutter/` wächst unbegrenzt (nach
  wenigen Tagen schon 32 Dateien / 9 MB, ein einzelner Lauf 1,8 MB). Bei Testern über
  Monate problematisch. Vorschlag: die letzten N Läufe (z.B. 20) behalten, ältere beim
  Engine-Start aufräumen. Aufwand: **leicht**.
- [x] Fenster-Resize-Animation: bei `.running` schmälert sich das Fenster animiert
  zur Mitte (760 pt), danach wird die **exakte** vorherige Geometrie
  wiederhergestellt. `WindowAccessor` (NSViewRepresentable) reicht das NSWindow
  hoch, `NSWindow.setFrame(_:display:animate:)` animiert. Schmälert nur, wenn das
  Fenster breiter als 760 ist.
- [x] App-Icon: **offizielles Icon** (grüner Glow-Orb, „magic core") aus
  `multicamcutter-web/assets/AppIcon.icns` → `scripts/AppIcon.icns`, von
  build_app.sh eingebettet. Ersetzt den blauen Pillow-Entwurf (make_icon.py obsolet).
- [x] Marken-Akzent Lime `#C6F24E` app-weit: `Color.brandAccent` in Theme.swift,
  `.tint(.brandAccent)` auf Fenster-Wurzeln, alle `.blue` in ContentView ersetzt.
  Deckungsgleich mit Website (multicamcutter-web/design.md).
- [x] Open-Source-Lizenzen: Acknowledgements-View (Master-Detail, scrollbare
  Lizenztexte), Button „Open-Source-Lizenzen" im Über-Dialog → eigenes Fenster.
  Texte kommen aus `scripts/collect_licenses.py`: sammelt die dist-info-LICENSE
  des Frozen-Bundles (42 Komponenten, verbatim) + `scripts/extra_licenses/`
  (ffmpeg/GPLv2, Sparkle, Python, requests, pyaaf2, mediapipe, opencv, soundfile).
  build_app.sh generiert + bettet `acknowledgements.json` ein. FFmpeg (GPL-2.0+,
  Quell-Link) steht oben. Erfüllt die GPL-Pflicht vor Verteilung.

### Bundling / Distribution
- [x] PyInstaller-Build testen (OneDir) — läuft E2E aus der UI durch
- [x] ffmpeg/ffprobe static builds (arm64, osxexperts.net v8.1) — self-contained,
  keine Homebrew-dylibs, ad-hoc signiert. In scripts/ (gitignored, 51 MB je).
  build_app.sh bevorzugt sie vor der Homebrew-Kopie. GPL → Acknowledgements-Pflicht.
- [x] **CLIP-Modell: Download auf Anfrage** (GELÖST — nicht gebündelt, bewusst).
  Prompt beim ersten CLIP-Lauf („Einmalig 581 MB"), Download mit Fortschritt
  (`ClipModelSheets.swift`, Vorlage `look examples/download.png`), danach startet die
  Analyse automatisch. Ablehnen → `clip_filter_enabled` dauerhaft aus, Rest läuft normal.
  **Alle Built-ins haben CLIP jetzt auf `false`** — niemand wird ungefragt konfrontiert.
  Engine: `--check-clip-model` / `--download-clip-model`, `ignore_patterns` laden nur
  PyTorch (581 statt 1,7 GB — das Repo führt das Modell 3× in PyTorch/TF/Flax).
  Cache: `~/.cache/huggingface/hub` → überlebt App-Updates und Neuinstallation.
  Vom User E2E bestätigt (Prompt, Download, Auto-Start); Fortschritt von mir im
  Frozen-Build verifiziert (0 → 573 MB).
  **Gelernte Fallstricke** (stehen so im Code): `model.safetensors` existiert im Repo
  NICHT (Whitelist hätte 0 Gewichte geladen) · `HF_HUB_OFFLINE` wird beim IMPORT zur
  Konstante (Sperre muss NACH den CLIP-Kommandos stehen) · Cache-Pfad nie hartkodieren
  (`HF_HUB_CACHE` nutzen) · `emit()` statt `print("__PROGRESS__")` — der Übersetzer
  läuft erst im Pipeline-Pfad.
- [ ] ~~ALT: CLIP-Modell nicht im Bundle~~ (erledigt, s.o.) — Details:
  `find dist/ -name "*.safetensors"` findet nichts; die Spec bündelt nur
  `transformers.models.clip` = Code + `clip_ignore_prompts.json`).
  Das Modell liegt nur in **Max' HF-Cache**: `~/.cache/huggingface/hub/models--openai--
  clip-vit-base-patch32` (**1,1 GB**). Code lädt mit `local_files_only=True`.
  **→ Bei jedem Tester schlägt der CLIP-Filter fehl** — und CLIP ist im Built-in
  „Talk (entspannt)" **standardmäßig AN**. Blocker vor Verteilung.
  **Optionen (User-Entscheidung, Größen-Tradeoff):**
  1. **Modell bündeln** → DMG wächst von ~500 MB auf ~1,1 GB. Ggf. reicht ein Teil
     des Caches (safetensors statt zusätzlich .bin/TF/Flax) → vorher messen.
  2. **Nachladen bei Bedarf** (erster CLIP-Lauf) → widerspricht „100 % lokal & offline"
     auf der Website und braucht Netz.
  3. **CLIP im Preset default AUS** → Feature bleibt für Profis, Tester laufen nicht rein.
  Kurzfristig sinnvoll: **3**, damit die Testrunde nicht blockiert.
- [x] Sparkle als Swift Package + Framework-Einbettung in build_app.sh
- [x] "Auf Update prüfen"-Button im Über-Dialog (KVO-gesteuert)
- [ ] Sparkle scharf schalten (wartet auf Website/Domain):
  - EdDSA-Keypair via `generate_keys` — Public Key `kcPVT…` ist bereits in
    `SUPublicEDKey`. ⚠ Private Key liegt im Login-Keychain → VOR Tester-Verteilung
    per `generate_keys -x` exportieren + im Passwort-Manager sichern (Verlust =
    nie wieder Auto-Updates für bestehende Installs).
  - SUFeedURL steht auf `https://multicamcutter.pantake.com/appcast.xml`
    → Website-Session muss dort `appcast.xml` hosten (Details/Signier-Flow in
    `brain/Distribution-Setup.md`). Update-DMGs NICHT in Git — Objekt-Storage.
  - `SUEnableAutomaticChecks` auf `true`
  - Releases mit `sign_update` signieren
- [x] Apple Developer Program Enrollment — **erledigt**. Team-ID `6F5UGR7V25`
  (Individual, „Maximilian Menge"). Zertifikat „Developer ID Application" im
  Schlüsselbund, Notary-Profil `MulticamNotary` via `store-credentials` hinterlegt.
- [x] Codesigning + Notarization **verdrahtet** (nicht getestet-am-Ende): 
  `SIGN_IDENTITY=… build_app.sh` signiert inside-out mit Hardened Runtime +
  `scripts/MulticamCutter.entitlements`; `scripts/notarize.sh` macht DMG → submit
  → staple → verify. Details: `brain/Distribution-Setup.md`.
  ⚠️ Offen: **erster echter End-to-End-Lauf** muss der User im eigenen Terminal
  starten (codesign braucht einmal „Immer erlauben" am Schlüsselbund-Dialog —
  headless/Agent hängt daran). Danach ggf. Entitlements nachjustieren, falls die
  notarisierte App unter Hardened Runtime beim Start crasht.
- [x] DMG-Installer (Test-Verteilung): `scripts/make_dmg.sh` baut `MultiCamCutter.dmg`
  aus release/-App + „Programme"-Verknüpfung + Erste-Start-Anleitung (Gatekeeper-
  Umgehung für ad-hoc/unnotarisierten Build). Finale signierte DMG nach Notarization.
- [ ] DMG grafisch gestalten (Drag-to-Install-Look): Hintergrundbild im Marken-Stil
  (dunkel + Lime, passend zum Orb-Icon) mit Pfeil App → „Programme", feste Icon-
  Positionen, größere Icons, ausgeblendete Toolbar. Umsetzung via `create-dmg`
  (Homebrew, simpel) oder `dmgbuild` (Python, headless/reproduzierbar). Gatekeeper-
  Hinweis dezent ins Hintergrundbild statt separater LIESMICH-Datei.
  **Deprio: erst rund um Signierung/Notarization sinnvoll**, vorher unwichtig.

## Erledigt

- [x] Ordner-Scan mit Thumbnails + Audio-Previews
- [x] Cam/Mic-Zuordnung per Drag & Drop
- [x] Editierbare Labels (Sidebar, Finder-Stil)
- [x] Audio-Preview: intelligente Stelle per RMS-Dominanz
- [x] Video-Thumb Scrubbing (AVAssetImageGenerator)
- [x] Thumbnail per Klick pinnen
- [x] Parameter-Presets (Built-in + User, Export/Import)
- [x] Progress-View mit Per-Step-Bar, ETA, Step X von Y
- [x] Abbrechen-Button -> zurueck zu .ready
- [x] .multicam Session-Persistenz (Labels, Zuordnungen, Parameter)
- [x] Episodenname editierbar, AAF-Dateiname davon abgeleitet
- [x] Play/Pause Audio (nur eine Wiedergabe gleichzeitig)
- [x] Projekt-Menue (Neu, Ordner oeffnen)
- [x] Sidebar Drag auf CameraCards
- [x] Camera-Cards als adaptives Grid (LazyVGrid)
