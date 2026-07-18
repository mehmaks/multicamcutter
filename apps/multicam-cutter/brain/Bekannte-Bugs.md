# Bekannte Bugs & Fixes

## OFFEN

### ffmpeg nicht gefunden in PASS 5 (CLIP-Filter) — Issue #3
- **Symptom**: Durchlauf bricht ab mit `[Errno 2] No such file or directory: 'ffmpeg'`.
  Log (Issue #3, `mehmaks/resolve-toolkit`): Sync + Nodding liefen bis **96,9 %** durch,
  Fehler erst danach. Trat auf, seit „Talk (entspannt)" = Jena-United-Preset ist —
  das hat **`clip_filter_enabled: true`**, ein Codepfad der vorher nie lief.
- **Verdächtiger**: `add_reactions_to_edl.py` **PASS 5** (CLIP-Ignore-Filter) →
  `_extract_frame()` (Zeile ~820) ruft `subprocess.run(['ffmpeg', …])`.
- **⚠️ WIDERSPRUCH — hier nicht raten:** Im Frozen-Bundle laufen die Scripts
  **in-process via `runpy`** (run_from_bin.py:565-574), teilen sich also `os.environ`.
  Der Analyzer ruft ffmpeg im **selben** Prozess auf (ein ffmpeg pro Off-Sektion, 76×
  erfolgreich) → der PATH war nachweislich korrekt. Dass derselbe Prozess ffmpeg kurz
  darauf nicht findet, ergibt so keinen Sinn. Ausgeschlossen: Thread-/Prozess-Pools,
  `env=`-Übergaben, `os.environ`-Manipulation (alles gegrept, nichts gefunden).
- **Stand (umgesetzt, wartet auf Reproduktion)**:
  1. ✅ **Diagnose im Fehlerpfad**: `_ffmpeg_diagnostics()` haengt bei jedem
     ffmpeg/ffprobe-Fehler `PATH`, `which(ffmpeg)`, `which(ffprobe)`, `frozen`,
     `executable` an die Meldung → landet automatisch im Bug-Report.
  2. ✅ **Selbstheilung**: `_ensure_ffmpeg_on_path()` laeuft beim Engine-Start; ist
     ffmpeg nicht im PATH, wird es neben dem eigenen Binary gesucht (im Bundle:
     `Contents/Resources/`, eine Ebene ueber `multicam-engine/`) und nachgetragen.
     ⚠️ **Fixt diesen Bug vermutlich NICHT** — der PATH war laut Log ja korrekt
     (76 erfolgreiche ffmpeg-Aufrufe). Ist Robustheit fuer andere Hosts/Terminal.
- **Wie der naechste Report zu lesen ist**: Zeigt `which(ffmpeg)` einen gueltigen
  Pfad, obwohl der Aufruf mit ENOENT scheitert, ist es **nicht** der PATH → dann
  Richtung „Datei zwischenzeitlich verschwunden" (DMG ausgeworfen?) oder
  Ressourcen-Limit (viele Popen pro Off-Sektion) weitersuchen.
- **Workaround**: Expertenmodus → „Ungünstige Cutaways verschieben (CLIP)" AUS.

## Gefixt

### Abgebrochene FPS-Konvertierung → abgeschnittene Datei → kaputte AAF + Sync-Versatz
- **Symptom** (18.07.): In Resolve „The clip C7451_25fps failed to link because the timecode
  extents do not match any clip in the Media Pool" (viele Zeilen), UND die Gast-Cam läuft
  async zum Gast-Mic (Mics untereinander aber synchron). Schnitte gingen korrekt zur Cam.
- **Ursache**: Der User hatte die FPS-Konvertierung einmal **abgebrochen** — die Abbruch-
  Bereinigung (löscht Teildateien) kam erst DANACH in die Engine. Die abgeschnittene
  `C7451_25fps.MP4` (94,6 s statt 99 min, TC korrekt erhalten) blieb liegen und wurde beim
  nächsten Scan als gültige 25fps-Cam benutzt. Zwei Folgen: (1) die AAF verweist auf
  Source-TC bis 99 min, die Datei hat aber nur 94,6 s → Link-Fehler. (2) Der Sync macht
  `cam_paths[0]` (= diese Host-Cam) zur ALLEINIGEN Referenz (`waveform_sync.py:183`) →
  die Gast-Cam wird gegen nur 94,6 s Referenz korreliert → falscher Offset → async.
  MIC2/3 erben MIC1s Offset (by design) → bleiben untereinander synchron. **Nicht** die
  Diarisierung (die entscheidet nur, WOHIN geschnitten wird — lief korrekt).
- **Fix**: (1) Engine `convert_fps_files` prüft jetzt die **Ausgabe-Dauer ≈ Quelle**;
  abgeschnittene Ausgabe wird gelöscht + Fehler. (2) App-Warnbanner `ShortCamBanner`
  (`suspiciouslyShortCams`, < 50 % der längsten Quelle) fängt bereits liegende Teildateien
  vor der Analyse ab.
- **Dateien**: engine/multicam_engine.py (convert_fps_files), EngineController.swift
  (suspiciouslyShortCams), WizardView.swift (ShortCamBanner).
- **Backlog**: Sync-Anker gegen Mics statt CAM1 (s. TODOs) — die eigentliche Fragilität.

### Thumbnail laeuft ueber Mic-Pills, sobald eine Karte hoeher wird
- **Symptom**: Ordnet man einer Cam ein zweites Mic zu (Karte waechst), laeuft das
  Video-Thumbnail nach unten ueber die Mic-Pills; die Karten einer Reihe wirken
  unterschiedlich hoch/versetzt.
- **Ursache**: `ScrubbableThumbnail` hatte die Ratio direkt auf dem Bild mit
  `.aspectRatio(16/9, contentMode: .fill)`. `.fill` ist vertikal **gierig** — bekommt
  die Karte mehr Hoehe (2 Pills, Totale-Hinweis), dehnt sich das Bild mit und
  ueberlappt die darunterliegenden Views.
- **Fix**: 16:9-Box **aus der Breite** ableiten: `Color.clear.overlay { Bild }`
  + `.aspectRatio(16/9, contentMode: .fit)` + `.clipped()`. Das Bild fuellt die Box
  (`scaledToFill`), kann aber nicht mehr vertikal wuchern.
- **Datei**: ScrubbableThumbnail.swift (`body`)

### Totale-Pill im Thumbnail zu „Tota" gestaucht
- **Symptom**: Markiert man eine Cam als Totale, wird die orange „Totale"-Pill oben
  rechts im Thumbnail abgeschnitten dargestellt („Tota…"). Trat **nur** bei „Totale"
  auf, nicht bei den kürzeren (alten) Tags „Host"/„Gast" → klarer Hinweis auf reine
  Breiten-Stauchung, kein Farb-/Z-Order-Problem.
- **Ursache**: Das `Label` im Overlay bekam eine zu enge Breite vorgeschlagen und
  hat den Text (6 Zeichen) trunkiert; „Host"/„Gast" (4 Zeichen) passten zufällig.
- **Fix**: `.lineLimit(1).fixedSize()` auf dem Label → es nimmt seine natürliche
  Breite, die Pille skaliert mit.
- **Datei**: ContentView.swift (CameraCard, `.overlay(alignment: .topTrailing)`)

### Facemesh-Vorschau zeigt Bild aus einem VORIGEN Projekt
- **Symptom**: Zu Beginn des MediaPipe-Steps erscheint sofort ein Still — teils aus
  einem ganz anderen, vorher analysierten Projekt.
- **Ursache**: Zwei Dinge zusammen. (1) Der Analyzer schreibt die Vorschau auf einen
  **festen** Pfad `/tmp/multicam_preview_cam{i}.jpg` (run_from_bin.py) — **nicht pro
  Projekt**, die Datei überlebt also Projektwechsel. (2) `startPreviewPolling` zeigte
  die Datei, **sobald sie existiert**; `facemeshImage` wurde nur am Lauf-*Ende* geleert.
- **Fix**: `startPreviewPolling` merkt sich `previewStartedAt` und akzeptiert nur
  Stills mit `mtime >= Poll-Start`; `facemeshImage` wird beim Start sofort geleert.
  Damit ist es unabhängig vom Pfad-Problem robust.
- **Datei**: EngineController.swift (startPreviewPolling/stopPreviewPolling)

### Card-Auswahl-Outline geht nicht weg (mehrere Karten + blauer Ring)
- **Symptom**: Klick auf den grauen Teil einer Video-Card → Akzent-Outline bleibt
  dauerhaft; mehrere Karten gleichzeitig „ausgewählt"; teils zusätzlich ein blauer
  Ring (nicht Lime).
- **Ursache**: CameraCard nutzte lokalen `@State isSelected`, wurde beim Tap auf
  `true` gesetzt aber **nie zurück** (pro Karte eigener State, `engine.selectedCamId`
  lag ungenutzt). Der blaue Ring war der macOS-Fokusring von `.focusable`.
- **Fix**: Auswahl zentral über `engine.selectedCamId` (computed `isSelected`,
  exklusiv). Tap setzt `selectedCamId`, Klick ins Leere (SetupView-Container) setzt
  `nil`. `.focusEffectDisabled()` unterdrückt den System-Fokusring → nur die
  Lime-Outline bleibt. Delete-zum-Entfernen funktioniert weiter.
- **Datei**: ContentView.swift (CameraCard, SetupView)

### Videolänge 0:00 + keine Thumbnails (nur im gebauten .app, per Doppelklick)
- **Symptom**: Nach Ordner-Scan zeigen alle Cams „0:00 min" und leere Thumbnails
  (video.slash). Nur in der verteilten .app per Finder/Dock-Start — aus dem
  Terminal / im Dev-Modus lief es.
- **Ursache**: Die Engine ruft `ffmpeg`/`ffprobe` als **bloße Namen** auf
  (`subprocess.run(["ffprobe", …])`) → PATH-abhängig. Eine per Finder/Dock
  gestartete App erbt einen **minimalen PATH** (`/usr/bin:/bin:…`) OHNE
  `/opt/homebrew/bin` und ohne die gebündelten Binaries. Alle ffprobe/ffmpeg-
  Aufrufe scheitern, werden abgefangen → `duration_s = 0`, Thumbnail leer.
  (Empirisch verifiziert: minimaler PATH → duration 0.0; ffmpeg-Ordner im PATH →
  duration 5.0.)
- **Fix**: `EngineController.engineEnvironment()` stellt `ffmpegDirectory` (Bundle:
  `Resources/`, Dev: `scripts/`) an den **Anfang des PATH** jedes Engine-Subprozesses.
  Deckt ALLE bare-name-Aufrufe ab, ohne die Engine anzufassen.
- **Dateien**: EngineController.swift (engineEnvironment, ffmpegDirectory)

### Sofort-Crash SIGBUS aus gemounteter DMG (KEIN App-Bug!)
- **Symptom**: App stürzt beim/kurz nach Start ab. Crash-Report: `EXC_BAD_ACCESS
  (SIGBUS)`, Stack in `NSHostingView`/SwiftUI-Layout, Kernel Triage:
  **„Object has no pager because the backing vnode was force unmounted"**,
  `procPath: /Volumes/*/…app`.
- **Ursache**: App wurde **direkt aus der gemounteten DMG** gestartet und die DMG
  wurde ausgehängt (ausgeworfen ODER die .dmg-Datei am selben Pfad ersetzt/neu
  gebaut → Zwangs-Unmount). macOS kann dann Code aus dem App-Binary nicht mehr
  nachladen. Der SwiftUI-Stack ist nur der Auffall-Zeitpunkt, nicht die Ursache.
- **Fix / Regel**: App IMMER erst nach `/Programme` ziehen und von dort starten,
  nie aus der DMG. Und: **die Test-DMG NIE neu bauen/ersetzen, solange ein Tester
  aus ihr läuft.** Anleitung in der DMG (make_dmg.sh) warnt jetzt prominent davor.

### Keyboard-Fokus bei swift run
- **Symptom**: Tastatureingaben landen im Terminal statt in der App
- **Ursache**: Plain executable (kein .app Bundle) bekommt keinen Keyboard-Fokus
- **Fix**: `NSApplication.shared.setActivationPolicy(.regular)` + `activate(ignoringOtherApps: true)`
- **Datei**: MulticamCutterApp.swift

### Progress-Bar bleibt bei 0%
- **Symptom**: Nodding-Analyse laeuft, aber Bar zeigt 0%
- **Ursache**: `__PROGRESS__`-Zeilen gingen am JsonLineWriter vorbei weil
  `run_from_bin.py` den hasattr-Check `_log` nutzt, aber JsonLineWriter nur
  `_log_file` hatte
- **Fix**: `_log = log_file` Attribut in JsonLineWriter.__init__
- **Datei**: engine/protocol.py

### Engine/Python nicht gefunden
- **Symptom**: "Engine oder Python nicht gefunden" beim Ordner-Drop
- **Ursache**: `#filePath`-basierte Pfadaufloesung funktioniert nicht bei swift run
  (Binary liegt in .build/ Cache, nicht neben Sources/)
- **Fix**: Fallback auf bekannten Dev-Pfad in toolkitRoot
- **Datei**: EngineController.swift

### Mic verschwindet beim Drop auf CameraCard
- **Symptom**: Mic-Pill wird unsichtbar nach Drag & Drop
- **Ursache**: CameraCard bekam `let camera: CameraInfo` als Struct-Kopie,
  Aenderungen am @Published Array wurden nicht reflektiert
- **Fix**: CameraCard liest direkt `engine.cameraInfos[camIndex]`
- **Datei**: ContentView.swift

### Scan haengt bei Fehler
- **Symptom**: "Ordner wird gescannt..." bleibt stehen
- **Ursache**: Scan-Error kam als JSON aber wurde nicht als Fehler erkannt
- **Fix**: Alle Zeilen auf type=error pruefen bevor scan_complete gesucht wird
- **Datei**: EngineController.swift (runScan)

### Remote-Lizenz: cryptography/requests fehlten im Bundle
- **Symptom**: Im gebündelten App würde jede Lizenz als ungültig gelten
  (Signaturprüfung schlägt still fehl), obwohl die CLI/Dev-Version funktioniert
- **Ursache**: Build-venv hatte kein `cryptography`; `requests` + `cryptography`
  standen nicht in den `hidden_imports`. Im alten Dummy-Modus nie aufgefallen,
  weil `_verify_signature` nie aufgerufen wurde
- **Fix**: `cryptography` ins Build-venv (`venv/bin/pip install cryptography`);
  `requests` + `cryptography`(+ed25519/openssl-Submodule) in spec hidden_imports
- **Datei**: scripts/multicam_engine.spec, Build-venv
- **Merke**: `_verify_signature` fängt ImportError → gibt einfach False zurück.
  Fehlende Krypto-Deps zeigen sich NICHT als Crash, nur als „Lizenz ungültig".

### SICHERHEIT: Lizenz-Private-Key im ausgelieferten Bundle
- **Symptom**: `license_private.key` lag in `MulticamCutter.app/.../licensing/` —
  jeder haette damit beliebige Lizenzen faelschen koennen
- **Ursache**: PyInstaller-Spec bundelte den ganzen `licensing/`-Ordner
  (`(ROOT/'licensing', 'licensing')`) inkl. Private Key, keygen.py, keysign.py,
  licenses/
- **Fix**: Spec kopiert nur noch `license.py` (Public Key) + `__init__.py`.
  Bestehende Bundles (dist/, release/) manuell bereinigt.
- **Nicht geleakt**: App war noch nicht verteilt (nur lokale Testbuilds).
- **Datei**: scripts/multicam_engine.spec. Siehe Entscheidungen.md → "Zwei Keypairs"

### Fertig-Screen: versehentlicher Klick setzt Projekt zurueck
- **Symptom**: Ein Klick ins Fenster nach dem finalen Screen wirft das ganze
  Projekt aus dem Speicher (zurueck zum Ordner-Drop)
- **Ursache**: ResultView hatte nur "Neuen Ordner waehlen" (ruft `reset()` →
  `.idle`, loescht folderURL/Cams/Mics) als einzige Aktion — zu leicht zu treffen
- **Fix**: Neue nicht-destruktive `backToSetup()` (nur `state = .ready`, Ordner +
  Zuordnungen bleiben). ResultView: "Zurueck zum Projekt" (.bordered) als
  Hauptweg, "Neuen Ordner waehlen" nur noch als unauffaelliger `.link`.
- **Kein Datenverlust**: AAF liegt bereits auf Platte, `.multicam` haelt Setup —
  Re-Drop stellt via `loadSession()` alles wieder her
- **Dateien**: EngineController.swift (backToSetup), ContentView.swift (ResultView)

## Pipeline-Bugs (im Toolkit gefixt)

Siehe `modules/multicam_cutter/CLAUDE.md` -> "Fixed Bugs" Sektion fuer:
- Pause-Trim Audio/Video Desync
- Same-Speaker-Cut nach Event-Eliminierung
- Flacker-Schnitte durch zu kurz getrimmte Events
- Speaker-Switch-Heuristik unterdrueckt alle Single-Splits
- audio_trims.json Dual-Use Crash
