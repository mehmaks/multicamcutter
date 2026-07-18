# UI-Komponenten

## Grundlayout

Kein NavigationSplitView, kein linker Sidebar, kein rechter Inspector mehr. Der
`.ready`-State ist ein geführter **Zuordnungs-Wizard** (3 Schritte) über die
gesamte Fensterbreite. Datei: `WizardView.swift`. Der Wizard ist eine reine
**Präsentationsschicht** über demselben Modell wie zuvor (Cam↔Mic-Graph); er
setzt/liest nur `engine.persons`, `engine.camRoles()` etc. — keine eigene
Persistenz.

## App-States

| State | View | Beschreibung |
|-------|------|-------------|
| `.idle` | `FolderDropView` | Drag & Drop oder Finder-Dialog |
| `.scanning` | Linearer Balken | Engine `--scan` laeuft (`scanLabel`/`scanPercent`) |
| `.ready` | **`WizardView`** | 3-Schritt-Wizard: Personen · Kameras · Uebersicht |
| `.running` | `ProgressView_` | Pipeline laeuft, Fortschrittsanzeige |
| `.done` | `ResultView` | AAF-Pfad, Statistik, „Im Finder zeigen" |
| `.error` | `ErrorView` | Fehlermeldung, „Erneut versuchen" / „Zurueck" |

Alle States leben in `ContentView.stateContent` (switch über `engine.state`).

## WizardView (Container)

`VStack(spacing: 0)`: Header · Trennlinie · `ScrollView` mit dem aktiven Step ·
Trennlinie · `WizardFooter`. Hintergrund `wizBackground` (Verlauf `wizBg2→wizBg`
plus dezente Lime/Flieder-Radials — bewusst kein flaches Schwarz), Textfarbe
`wizText`. Haengt zwei Sheets/Alerts an: `FpsConversionSheet` (`isConverting`)
und den Konvertierungs-Fehler-Alert (`convertError`).

- **Header** (zweizeilig): Zeile 1 = editierbarer Episodenname (`EditableLabel`
  mit `film.stack`-Icon + Stift). Zeile 2 = `WizardStepBar`. Der App-Titel
  („MultiCamCutter") steht in der Titelleiste selbst, nicht im Header.
- **Step-Auswahl** via `engine.wizardStep` (`WizardStep`-Enum: `.persons` /
  `.cameras` / `.overview`). Jeder Step setzt seine eigene `maxWidth` und wird
  horizontal zentriert.

### Wizard-Reentry (Phase 5)
Beim erneuten Öffnen eines Ordners mit bereits gespeicherten Zuordnungen springt
der Wizard direkt auf **Übersicht** statt auf Personen. Entscheidung faellt in
`EngineController.runScan(decideWizardStep:)` nach `loadSession`:
`cameraInfos.contains { !$0.assignedMics.isEmpty } ? .overview : .persons`.
Der Re-Scan nach FPS-Konvertierung ruft mit `decideWizardStep: false` auf (Schritt
bleibt, wo der User war).

### WizardStepBar
Klickbare 1-2-3-Leiste (`Personen / Kameras / Übersicht`). Aktiver Schritt =
gefüllter Lime-Kreis mit Nummer; erledigte (kleinerer rawValue) = Lime-Häkchen;
kommende = graue `wizSurface`-Kreise. Jeder Schritt ist direkt anwählbar
(`engine.wizardStep = step`).

## Screen 1 — PersonsStep

„Benenne deine Sprecher:innen." Für **jede aktive Tonspur** (`engine.activeMics`)
eine `PersonRow`. Grundregel der App: **1 Person = 1 Mic**.

**PersonRow**: Avatar (Initialen auf Identitätsfarbe) · editierbares `TextField`
(Name) + Dateiname (monospaced) · Play/Pause (`toggleMicPreview`, ab erster
lauter Stelle) · Trash (`deletePerson` — Spur ist kein Sprecher).
- Name-Commit bei `.onSubmit`, Fokusverlust (`onChange(of: focused)`) **und**
  `.onDisappear` (Sicherheitsnetz gegen verlorene Umbenennung bei „Weiter").
- `liveName` liest aus `engine.micInfos` (reagiert auf Rename von außen).

Ausgeblendete Spuren erscheinen unten als `WizRestoreChips` (Wiederherstellen).

## Screen 2 — CamerasStep

„Wer ist auf welcher Kamera zu sehen?" Zwei Spalten:
- **Rail links** (200px): `PersonToken` je `engine.persons`. Antippen selektiert
  (dann Kamera klicken); alternativ per Drag&Drop. Unplatzierte Person zeigt
  „· frei" (Flieder). Mehrfachzuordnung erlaubt.
- **Grid rechts**: `WizardCamCard` je `engine.activeCams` (adaptiv 210–260px).

Oben ggf. `FpsMismatchBanner` (bei `fpsMismatches`) und `ShortCamBanner` (bei
`suspiciouslyShortCams`). Ausgeblendete Kameras unten als `WizRestoreChips`.

**WizardCamCard**:
- `ScrubbableThumbnail` mit Rollen-Pill oben rechts (`camRoles()[cam.id]`):
  **Totale** (Flieder, `brandSecondary`) / **Nah** (Lime-Tint) / nichts.
- `assigned` wird **LIVE** aus `engine.cameraInfos` gelesen, nicht aus dem
  `cam`-Snapshot — `CameraInfo`-`==` ist id-only, sonst erschienen die Pills
  erst nach Screen-Wechsel (siehe Bekannte-Bugs).
- Zugeordnete Personen als removable Chips (`removePersonFromCam`).
- Trash (`setCamIncluded(false)` — Kamera gehört nicht zum Projekt).
- „zeigt alle" (gestrichelt, `setCamShowsAllPersons`) — ordnet alle Personen zu.
- Drop-Target + Tap-to-assign (`addPersonToCam`); `targeted` = Lime-Outline.

Die Nah/Totale-Zuordnung ist **abgeleitet, nicht gesetzt**: „Close gewinnt" —
eine Kamera bleibt Nah, solange sie für mindestens eine ihrer Personen die engste
Einstellung ist; erst wenn für alle woanders enger gefilmt wird, wird sie Totale.

## Screen 3 — OverviewStep

„Passt alles?" Zwei Spalten + abgeleiteter Hinweis + Einstellungen.
- **Bildgrößen je Person**: `LadderRow` — Avatar + `shotLadder(for:)` als Chips
  von „engste" → „weiteste" (Totale-Chips Flieder, Nah-Chips Lime).
- **Kameras**: `CamSummaryRow` je Cam — Name · zugeordnete Personen · Rollen-Pill
  (Totale / Nah / ungenutzt).
- **derivedNote** (Flieder-Box): „Automatisch erkannt: N Sprecher:innen, N
  Kameras, N Totalen …" inkl. Erklärung der Close-gewinnt-Regel.
- **`WizardSettings`** (s.u.).

## WizardSettings (Variante C)

Kein Experten-Toggle als globale Einstellung mehr. Innerhalb der Box tauscht ein
**Textlink** den gesamten Inhalt:
- **Einfache Ansicht** (`simpleList`): kuratierte 8 Essentials, 2-spaltiges
  `LazyVGrid`.
- **Experteneinstellungen** (`expertList`): volle Parameterliste in Rubriken
  (Schnittregeln, Sprecher-Erkennung, Pausen, Reaktionen & Cutaways,
  Crossbleed-Gate, Totale), scrollbar (`maxHeight 300`).

Beide schreiben in dasselbe `engine.params`. Rubrik-Titel via `@ViewBuilder
group(_:_)`.

## Custom-Controls (Dummy-Look)

Native macOS-Controls ließen sich nicht auf den schlanken Dummy-Look bringen —
daher eigene:
- **`WizSlider`** (Label · `WizSliderControl` · Wert) + **`WizSliderControl`**:
  GeometryReader + `DragGesture`, dünne Spur (`wizSurface2`), Lime-Füllung +
  kleiner Lime-Knopf. Werte mit **Komma** formatiert (`.` → `,`), optional
  `suffix`/`format`. Bindings können skalieren (z. B. Konfidenz ×100 %).
- **`WizToggle`** + **`WizSwitch`**: Capsule + Knopf, Lime an / graue Spur aus.
- **`WizPrimaryButton`** (Lime, schwarze Schrift) / **`WizSecondaryButton`**
  (`wizSurface` + `wizBorder2`-Outline) — beides `ButtonStyle`.

## WizardFooter

`Zurück` (WizSecondary, im Personen-Schritt disabled) · Spacer · rechts je nach
Schritt: **Weiter** (WizPrimary) oder — auf Übersicht — `WizPresetDropdown` +
**Analyse starten** (`engine.start()`). Hintergrund `wizBg` (dunkler Footer).

`startBlockedReason` liefert Hinweistext (Flieder) + `disabled`. Blockiert bei:
< 2 aktive Cams · keine Person · < 2 Cams mit Person (`analysisCams`) ·
FPS-Mismatch · nicht jede Person hat eine Kamera (`unassignedMics`).

## WizPresetDropdown

„Preset [aktueller Name ▾]" — natives `Picker(.menu)` (dunkle Box, aktueller
Preset-Name oder „Angepasst") + „…"-Overflow-`Menu` (Speichern/Import/Export).
Speichern via Sheet mit Namensfeld. Preset-Match durch Vergleich
`loadPreset(...) == engine.params`.

## WizRestoreChips

Wiederherstellen-Chips für ausgeblendete (getrashte) Quellen — ohne sie käme man
an eine getrashte Kamera/Person nur noch übers Löschen der `.multicam` heran
(`included=false` ist persistent). Nutzt `excludedCams`/`excludedMics`.

## Personen-Identitätsfarben

`personPalette` (6 gedämpfte Farben, konkurrieren nicht mit Lime/Flieder), Index
= Position in `engine.activeMics`. `avatar(id, name, size, engine)` = Kreis in
Identitätsfarbe + Initialen (schwarz). Genutzt in PersonRow, PersonToken,
Chips, LadderRow.

## Banner

- **`FpsMismatchBanner`** (eigenständig, auch außerhalb des Wizards nutzbar):
  Flieder-Warnbox, listet Cams ≠ Timeline-FPS, Button `convertMismatchedFps()`.
- **`ShortCamBanner`**: warnt bei `suspiciouslyShortCams` (< 50 % der längsten
  Quelle) — typisch eine abgebrochene Konvertierung, deren Teildatei liegen
  blieb → Video-Sync-Versatz + AAF verlinkt in Resolve nicht. Bitte Datei löschen
  und neu konvertieren (siehe Bekannte-Bugs: truncated conversion).

## Verbliebene Views (ContentView.swift)

- **`FolderDropView`**: Drag & Drop / Finder-Dialog (`.idle`).
- **`FpsConversionSheet`**: siehe Fortschritts-Sheets unten.
- **`EditableLabel`**: Text + Stift-Icon zum Umbenennen. Im Header an
  `engine.episodeName` gebunden (bestimmt den AAF-Dateinamen), `.help(...)`.
- **`FlowLayout`**: umbrechendes Layout für Chips/Pills.
- **`ProgressView_`** (`.running`): großer Step-Name, Balken 0–100 % pro Step,
  Prozent + ETA, „Schritt X von Y", Abbrechen (`cancel()`). **Kein Log-Expander
  mehr** — der Roh-Log liegt im Fenster-Menü (Window).
- **`ResultView`** (`.done`): AAF-Pfad, Statistik, „Im Finder zeigen".
- **`ErrorView`** (`.error`): Fehlermeldung, „Erneut versuchen" / „Zurück".
- **`WindowAccessor`**: reicht das `NSWindow` an `ContentView` (Chrome + Resize).

## ScrubbableThumbnail

- Initial: JPEG vom Engine-Scan (Frame bei ~10 s).
- Hover: `AVAssetImageGenerator` extrahiert Frame nach Mausposition (linker Rand
  = Frame 0, rechter Rand = letzter Frame). Timecode-Label + weiße Positionslinie.
- Debounced (50 ms), ±1 s Toleranz. Klick pinnt Frame als Thumbnail (JPEG).

## Fenster-Chrome & Resize (ContentView)

- **`configureWindowChrome`**: `titlebarAppearsTransparent = true`,
  `titleVisibility = .visible`, Titel „MultiCamCutter", **kein**
  `fullSizeContentView` (App-Titel steht sauber allein oben, Episode im Header
  darunter), `backgroundColor = wizBg` (#0e100c).
- **`growWindowForOverview`**: wächst auf Screen 3 (Übersicht + Einstellungen)
  bei Bedarf auf 940px Höhe (Oberkante fix, nach unten).
- **`animateWindowWidth`**: bei `.running` einmalig auf 760px schmälern, danach
  exakt die vorherige Geometrie wiederherstellen (`frameBeforeRun`).

## Fortschritts-Sheets (einheitlicher Aufbau)

`ClipDownloadSheet` (CLIP-Modell) und `FpsConversionSheet` (FPS-Konvertierung)
teilen dasselbe Layout: Icon links (`.brandAccent`), Titel, linearer Balken,
darunter „X von Y (Z %)" (`.monospacedDigit`), Breite 460.
- **FpsConversionSheet**: `film`-Icon, Titel = Dateiname + `(n/m)` bei mehreren.
  Balken aus `convertDone`/`convertTotal` (Sekunden, aus `convert_progress`).
  „Wird vorbereitet …" solange `convertTotal == 0`. Roher ffmpeg-Log NICHT live —
  nur im Fehlerfall haengt der Schwanz (12 Zeilen) an `convertError`
  (`convertDiagnosticsTail()`).
  **ETA** (`convertEtaSeconds`): „· noch ~4 min" aus Wall-Clock-Durchschnitt
  über alle offenen Dateien (`convertTargetDurations`).
  **Abbrechen** (X, `cancelConversion`): SIGTERM an die Engine. Deren
  `_on_term`-Handler beendet ffmpeg und **loescht die halbfertige `_NNfps.mp4`**.
  Swift setzt `convertCanceled` → kein Fehler, kein Re-Scan, Zustand unveraendert.
  **Nach Erfolg** (`rescanAndDeselectOriginals`): Ordner neu einlesen (neue
  `_NNfps`-Dateien erscheinen) und die konvertierten Originale automatisch
  abwaehlen (`included=false`, Mic-Zuordnung geloest, gespeichert). Der
  FPS-Mismatch-Banner verschwindet damit von selbst.
- **ClipDownloadSheet**: `sparkles`-Icon, Bytes statt Zeit, mit Abbrechen.

## Menue

- Projekt > Neu (Cmd+N) → `reset()`
- Projekt > Ordner oeffnen … (Cmd+O) → NSOpenPanel
- Window-Menü: Roh-Log der laufenden/letzten Analyse.
- MulticamCutter > Einstellungen … (Cmd+,) → Settings Scene
- MulticamCutter > Ueber MulticamCutter → About-Dialog (TODO)

## Settings-Page

Erreichbar über Cmd+, (SwiftUI Settings Scene). Der frühere Expertenmodus-Toggle
ist **entfernt** (Experteneinstellungen liegen jetzt im Wizard, `WizardSettings`)
→ `GeneralSettingsTab` ist ein Platzhalter („Hier erscheinen künftig
App-Einstellungen."). Geplant: Lizenz-Status, weitere App-Optionen.

## About-Dialog (TODO)

App-Icon, Name, Versionsnummer (aus Bundle), Copyright, Website-Link.

## Entfernte Views (historisch)

Mit dem Wizard + Phase-4-Cleanup entfernt: `SetupView` (+ Extension),
`SidebarView`, `InspectorPanel`, `SourcesInspector`, `PersonsInspector`,
`CameraCard`, `MicPill`, `PresetPicker`, `ParameterForm`/`ParameterRow`. Ihre
Funktionen leben jetzt im Wizard: Cam↔Mic-Zuordnung → Screen 2, Quellen
aus-/einblenden → Trash auf den Cards + `WizRestoreChips`, Parameter →
`WizardSettings`, Presets → `WizPresetDropdown`. Auch die alten Kamera-Tags
(Host/Gast als `CamTag`, `isWide`/`setCamWide`, `sharedWideCams`/`ignoredCams`)
sind weg — Rollen werden aus dem Personen-Graphen **abgeleitet** (`camRoles()`).
