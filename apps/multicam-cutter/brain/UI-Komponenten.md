# UI-Komponenten

## Layout (Hush-Style)

Kein NavigationSplitView mehr. Stattdessen HSplitView:
- **Links**: Settings (Episode, Parameter, Presets) — scrollbar
- **Rechts**: Content (Folder-Drop, Kamera-Cards, Mic-Pills) — scrollbar
- **Unten fixiert**: Analyse-Button (über gesamte Breite)
- **Rename**: Doppelklick auf Namen in Cards/Pills/Episodenname

## App-States

| State | View | Beschreibung |
|-------|------|-------------|
| `.idle` | FolderDropView | Drag & Drop oder Finder-Dialog |
| `.scanning` | Progressbar | Engine --scan laeuft |
| `.ready` | SetupView | Cam/Mic-Zuordnung + Parameter |
| `.running` | ProgressView_ | Pipeline laeuft, Fortschrittsanzeige |
| `.done` | ResultView | AAF-Pfad, Statistik, "Im Finder zeigen" |
| `.error` | ErrorView | Fehlermeldung, "Erneut versuchen" / "Zurueck" |

## Sidebar (SidebarView)

- Episode-Name (editierbar, Finder-Stil: Klick selektiert, 2. Klick editiert)
- Kameras-Section (editierbare Labels, Rename gesperrt waehrend `.running`)
- Mikrofone-Section (editierbar, draggable auf CameraCards im `.ready` State)
- Feste Breite: ideal 220px (min 180, max 300)

## Setup-Bereich (SetupView)

- **Kamera-Zuordnung**: LazyVGrid mit CameraCards (adaptive 220-300px)
- **Nicht zugeordnete Mics**: Unterhalb der Cards als draggable Pills
- **Schnitt-Parameter**: Form mit Sections (Allgemein, Schnitt, Pause-Trim)
- **Preset-Picker**: Menu neben "Schnitt-Parameter" Ueberschrift
- **Quelldateien-Panel**: rechts als `.inspector` (s.u.), Toolbar-Button `sidebar.right`
- **Start-Button**: `startBlockedReason` liefert Hinweistext + disabled. Blockiert bei:
  < 2 aktive Cams, kein aktives Mic, oder nicht alle aktiven Mics zugeordnet.

## InspectorPanel (rechtes Panel, zwei Reiter)

- `.inspector(isPresented:)` (macOS 14+) am NavigationSplitView → collapsible,
  resizable, Breite persistent. Sichtbarkeit via `@AppStorage("showSourcesInspector")`.
- Segmented Picker oben: **„Quellen | Personen"** → `SourcesInspector` bzw.
  `PersonsInspector`.

### SourcesInspector (Datei-Sicht)
- Listet **alle** gescannten Quellen (Sections „Kameras" / „Mikrofone") mit
  `Toggle(.checkbox)` → `engine.setCamIncluded` / `setMicIncluded`.
- Umbenennen NUR hier (Stift-Symbol), nicht auf dem Canvas.
- Deaktiviert = existiert weder auf dem Canvas noch fuer die Analyse.
  Deaktiviertes Video gibt seine Mics frei; deaktiviertes Mic loest sich von der Cam.
- FPS-Detail pro Cam („30 fps ≠ 25" orange bei Mismatch).

### PersonsInspector (Personen-Sicht)
- Gruppiert denselben Cam↔Mic-Graphen nach **Person** (`engine.persons`, abgeleitet:
  eine je aktivem Mic, Name = Mic-Anzeigename). Pro Person: Mic-Datei + zugeordnete
  Cams (Totale-Cams orange markiert), oder „Keine Kamera zugeordnet".
- Sections „Geteilte Totalen" (`sharedWideCams` = Totale ohne Mic) und „Ohne Person"
  (`ignoredCams` = kein Mic, keine Totale → nicht analysiert).
- **Rein lesend** — Zuordnung passiert weiter per Drag&Drop auf dem Canvas.
  Grundlage fuer spaetere Personen-Features (Rollen, Bildgroessen-Wechsel).

## CameraCard

- ScrubbableThumbnail (Hover scrubt, Klick pinnt Frame als Thumbnail)
- Display-Name + Dauer
- Zugeordnete Mics als MicPills (removable, Play/Pause)
- Drop-Target fuer Mic-Pills (aus Sidebar oder aus "Nicht zugeordnet")
- Mic-zu-Cam Umziehen: Drag von einer Card auf andere funktioniert
- Klick waehlt aus (Lime-Outline, `engine.selectedCamId`), Klick ins Leere waehlt ab.
  **Kein Entf/Backspace mehr** — Quellen werden im Panel per Checkbox deaktiviert.
- **Rechtsklick → Toggle „Als Totale markieren"** (`engine.setCamWide`, Feld `isWide`).
  Orange „Totale"-Pill oben rechts IM Thumbnail. (Host/Gast gab es frueher als
  `CamTag`, taten aber nichts → entfernt. Rollen kaemen kuenftig an der Person.)
- Cam ohne Mic **und** ohne Totale zeigt „Wird ignoriert" (orange) — sie geht
  nicht in die Analyse. Frueher wurde sie STILL zur Totale erklaert (inkl. 150% Zoom).
- Totale-Cam zeigt „Totale — kein Mic nötig" statt der Mic-Drop-Aufforderung.

## Fortschritts-Sheets (einheitlicher Aufbau)

`ClipDownloadSheet` (CLIP-Modell) und `FpsConversionSheet` (FPS-Konvertierung)
teilen dasselbe Layout: Icon links (`.brandAccent`), Titel, linearer Balken,
darunter „X von Y (Z %)" (`.monospacedDigit`), Breite 460.
- **FpsConversionSheet**: `film`-Icon, Titel = Dateiname + `(n/m)` bei mehreren.
  Balken aus `convertDone`/`convertTotal` (Sekunden, aus `convert_progress`).
  „Wird vorbereitet …" solange `convertTotal == 0`. Der rohe ffmpeg-Log wird NICHT
  mehr live gezeigt — nur im Fehlerfall haengt der Schwanz (12 Zeilen) an
  `convertError` (`convertDiagnosticsTail()`).
  **ETA** (`convertEtaSeconds`): „· noch ~4 min" in der Detailzeile. Aus dem
  Wall-Clock-Durchschnitt (Video-Sek pro Real-Sek), inkl. der noch offenen Dateien
  (`convertTargetDurations`) — ruhiger als ffmpegs Momentan-`speed`.
  **Abbrechen** (X-Button, `cancelConversion`): schickt der Engine SIGTERM. Deren
  `_on_term`-Handler beendet das laufende ffmpeg (kein verwaister Child) und **loescht
  die halbfertige `_NNfps.mp4`**. Swift merkt sich `convertCanceled` → kein Fehler,
  kein Re-Scan, der Zustand bleibt unveraendert.
  **Nach Erfolg** (`rescanAndDeselectOriginals`): Ordner wird neu eingelesen (die
  neuen `_NNfps`-Dateien erscheinen) und die **konvertierten Originale automatisch
  abgewaehlt** (`included=false`, Mic-Zuordnung geloest, gespeichert). So verschwindet
  der FPS-Mismatch-Banner von selbst und die Analyse nutzt nur die korrigierte Fassung.
- **ClipDownloadSheet**: `sparkles`-Icon, Bytes statt Zeit, mit Abbrechen-Button.

## MicPill

- Mic-Icon + Live-Name (liest aus engine.micInfos, reagiert auf Rename)
- Optional: X-Button zum Entfernen (removable)
- Play/Pause-Button (AVAudioPlayer, nur eine Wiedergabe gleichzeitig)
- Draggable (NSItemProvider mit Mic-ID als String)

## ScrubbableThumbnail

- Initial: JPEG von Engine-Scan (Frame bei ~10s)
- Hover: AVAssetImageGenerator extrahiert Frame basierend auf Mausposition
- Linker Rand = Frame 0, rechter Rand = letzter Frame
- Timecode-Label unten links, weisse Positions-Linie
- Debounced (50ms), 480px Breite, ±1s Toleranz
- Klick waehrend Hover: pinnt Frame als permanentes Thumbnail (JPEG gespeichert)

## PresetPicker

- Menu mit Built-in Presets + User-Presets
- "Speichern..." -> Sheet mit Namensfeld
- "Importieren..." / "Exportieren..." -> Finder-Dialoge
- Presets in ~/Library/Application Support/MulticamCutter/presets/

## Progress-View

- Step-Name gross (z.B. "Nodding-Analyse CAM1 (Cam Host)")
- Progress-Bar 0-100% pro Step (resettet bei neuem Step)
- Prozent + ETA
- "Schritt X von Y" dezent darunter
- Abbrechen-Button -> cancel() -> zurueck zu .ready
- Log als DisclosureGroup (aufklappbar, Text selektierbar)

## Menue

- Projekt > Neu (Cmd+N) -> reset()
- Projekt > Ordner oeffnen... (Cmd+O) -> NSOpenPanel
- MulticamCutter > Einstellungen... (Cmd+,) -> Settings Scene (TODO)
- MulticamCutter > Ueber MulticamCutter -> About-Dialog mit Version (TODO)

## Settings-Page (TODO)

- Lizenz: Datei auswaehlen, Status anzeigen (gueltig/abgelaufen/fehlend)
- Expertenmodus: Toggle der erweiterte Parameter in der Setup-View einblendet
- Erreichbar ueber Cmd+, (SwiftUI Settings Scene)

## About-Dialog (TODO)

- App-Icon, Name, Versionsnummer (aus Bundle oder hardcoded)
- Copyright, Website-Link
