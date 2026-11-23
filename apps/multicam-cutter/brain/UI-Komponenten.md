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
lauter Stelle) · Link-Menue (gesplittete Aufnahmen: „Gehört zu …" → `joinMic`,
„In Einzeldateien trennen" → `splitMic`; beide speichern und scannen neu, Badge
„N Teile" mit Teil-Liste im Tooltip) · Trash (`deletePerson` — Spur ist kein Sprecher).
- Name-Commit bei `.onSubmit`, Fokusverlust (`onChange(of: focused)`) **und**
  `.onDisappear` (Sicherheitsnetz gegen verlorene Umbenennung bei „Weiter").
- `liveName` liest aus `engine.micInfos` (reagiert auf Rename von außen).

Ausgeblendete Spuren erscheinen unten als `WizRestoreChips` (Wiederherstellen).

## Screen 2 — CamerasStep

„Wer ist auf welcher Kamera zu sehen?" Zwei Spalten:
- **Rail links** (200px): `PersonToken` je `engine.persons`, **nur per Drag&Drop**
  auf eine Kamera ziehbar (kein Tap-to-assign mehr — kollidierte mit dem
  Thumbnail-Klick und war überflüssig). Unplatzierte Person zeigt „· frei"
  (Flieder). Mehrfachzuordnung erlaubt.
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
- **Drop-Target** (`addPersonToCam`), `targeted` = Lime-Outline. Der Klick auf das
  Thumbnail pinnt einen Frame (ScrubbableThumbnail) — die Karte hat keinen eigenen
  Tap mehr.

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
- **Experteneinstellungen** (`expertList`): Benennung nach Schema
  (`config/schemas/multicam_params.json`), scrollbar (`maxHeight 300`). Rubriken:
  **Generelle Schnittregeln · Sprecher-Erkennung · Pausen-Trimming** (inkl.
  `WizSegmented` „Schnittmodus") **· Crossbleed-Filter · Cutaway Regeln · Kopfnicken ·
  Sprachreaktionen · Stille**.
  Rubrik-Titel via `group(_:first:_)`, Sub-Titel via `subLabel(_:)`. `group` zeichnet
  über **jeder** Rubrik eine Trennlinie (`wizBorder`, wie unter „Einstellungen") —
  außer der ersten (`first: true`), die schon unter der Einstellungen-Linie sitzt.

  **Cutaway-Rubriken bewusst aufgeteilt** (Abweichung vom flachen Web-Block): „Cutaway
  Regeln" enthält nur die **typ-übergreifenden** Parameter (Cutaway-Länge, Pre-Roll,
  Zufallsfaktor, Ungünstige Cutaways verschieben). Jeder Cutaway-Typ bekommt eine
  eigene Rubrik mit „Aktiv"-Toggle + NUR seinen Parametern:
  **Kopfnicken** (Min. Konfidenz + Muster-Toggles) · **Sprachreaktionen** (Rise, Max.
  Cutaway-Dauer) · **Stille** (Min. Pausenlänge). Vorher lagen alle in einem Block und
  die Zuordnung Toggle→Parameter war nicht erkennbar.

  ⚠️ **`pauseCutMode`-Werte**: `middle` | `l-cut` | `j-cut` | `random` (aus
  `pause_trim_edl.py` / Schema-Transform) — **nicht** none/end.

  **Bewusst NICHT exponiert:**
  - **LUT** — vorerst nicht in die App gehoben (25.07.). ⚠️ Der „bringt nichts"-
    Befund ist NICHT allgemeingueltig: getestet nur an EINER Kamera mit EINEM
    Log-Profil — ob MediaPipe bei ARRI Log-C, RED Log o. flacheren Kurven doch
    profitiert, ist offen. Das `--lut`-Flag + `lut3d`-Zweig bleiben daher bewusst
    in der Engine (ungenutzt, aber sofort reaktivierbar, falls ein Log-Problemfall
    auftaucht). Nicht als „erledigt/verworfen" behandeln.
  - **Gate-Audio in Timeline** (`gateUseFiltered`) — reine Debug-Option: exportiert nur
    `*_gated.wav` und importiert sie **nur im Resolve/Bin-Workflow** in den Media Pool.
    Im Ordner/AAF-Workflow ohne Wirkung (die AAF referenziert Original-Audio). Param
    bleibt in `PipelineParams`, nur ohne UI.
  - **Totale-Cam Schnittlogik** (`totaleSimulDur`) — Rubrik entfernt, das Thema wird in
    einer eigenen Session neu konzipiert. Param bleibt (Default 3.0).

**Nicken-Muster (pro Preset):** In der Rubrik „Kopfnicken" folgen unter dem Sub-Titel
„Muster" **dynamische Toggles** je Pattern (Oscillation/Slow/Strong, Namen +
Defaults aus `getNoddingPatterns()` → `noddingPatternDefs`). Sie schreiben in
`engine.params.noddingPatterns` (`[name: Bool]`) → **pro Preset** gespeichert, an die
Engine als `nodding_patterns`. Default je Pattern = `enabled` aus der JSON. (Die
globalen Schwellen bleiben im Settings→Nodding-Tab, siehe dort.)

Beide Ansichten schreiben in dasselbe `engine.params`.

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

`Zurück` (WizSecondary, im Personen-Schritt disabled) · **`FeedbackButton`** (Bug/
Feedback melden — sitzt hier statt global oben rechts; ErrorView + Menü haben eigene
Einstiege) · Spacer · rechts je nach Schritt: **Weiter** (WizPrimary) oder — auf
Übersicht — `WizPresetDropdown` + **Analyse starten** (`engine.start()`).
Hintergrund `wizBg` (dunkler Footer).

`startBlockedReason` liefert Hinweistext (Flieder) + `disabled`. Blockiert bei:
< 2 aktive Cams · keine Person · < 2 Cams mit Person (`analysisCams`) ·
FPS-Mismatch · **> 2 Kameras** (`unsyncedCams`, Sync deckt nur zwei ab) ·
nicht jede Person hat eine Kamera (`unassignedMics`).

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
- **`UnsyncedCamsBanner`**: warnt bei `unsyncedCams` (alles ab Position 3 in
  `orderedAnalysisCams`). Der Waveform-Sync misst nur die ersten beiden Cams; weitere
  bekämen stumm Offset 0. **Sperrt zusätzlich den Start** (`startBlockedReason`) —
  bewusst laut blockieren statt still falsch schneiden. Temporärer Wächter, bis der
  N-Cam-Sync in der Multicam-Session gebaut ist (siehe Bekannte-Bugs).

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

## Dock-Fortschritt & System-Notifications (`MacIntegrations.swift`)

An den Analyse-Lebenszyklus gekoppelt über `ContentView` (`handleMacIntegrations`
in `.onChange(of: engine.state)`, plus `.onChange(of: stepNum/stepPercent)`).
- **`DockProgress`**: zeichnet einen `NSProgressIndicator`-Balken unten auf das
  Dock-Icon (`NSApp.dockTile.contentView` = App-Icon + Balken), `show(fraction)` /
  `hide()`. Fortschritt = `engine.overallProgress` (0…1 über alle Schritte). So sieht
  man den Fortschritt auch bei minimierter App. Balken bei `.running` an, beim
  Verlassen weg.
- **`AnalysisNotifier`** (`UserNotifications`): postet beim Übergang **aus** `.running`
  einen Banner — `.done` „Analyse abgeschlossen", `.error` „…fehlgeschlagen"
  (+ `errorMessage`), `.ready` (= `cancel()`) „…abgebrochen". macOS zeigt den Banner
  standardmäßig nur, wenn die App **nicht** im Vordergrund ist. ⚠️ Braucht ein echtes
  App-Bundle (Bundle-ID) → im Dev-Lauf via `swift run` still übersprungen (kein Crash),
  funktioniert im gebauten `.app`.

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

Erreichbar über Cmd+, (SwiftUI Settings Scene), `.tint(.brandAccent)` auf dem
`TabView` (sonst blaue System-Tabs). Der frühere Expertenmodus-Toggle ist
**entfernt** (Experteneinstellungen liegen jetzt im Wizard, `WizardSettings`).
- **Allgemein** (`GeneralSettingsTab`): Toggle „Kontrast der Vorschaubilder
  anheben" (`@AppStorage("thumbnailAutoContrast")`) — hebt flaches Log-Material in
  den Kamera-Vorschauen an; denselben Key liest `ScrubbableThumbnail`, wirkt live,
  rein kosmetisch.
- **CLIP** (`ClipSettingsTab`): Modell-Status („geladen/nicht geladen" + Download
  via `downloadClipModel()`, Inline-Progress) + Prompt-Editor (zwei Text-Editoren
  Ignorieren/Neutral, ein Prompt je Zeile). Lädt via Engine `--get-clip-prompts`,
  speichert nach `~/Library/Application Support/MulticamCutter/clip_prompts.json`
  (Engine bevorzugt sie), „Auf Standard zurücksetzen" löscht sie. Immer sichtbar.
- **Nodding** (`NoddingSettingsTab`): **roher JSON-Editor** nur der **globalen**
  Schwellen/Filter der `nodding_patterns.json` (Globals + Filter/Confidence — Expert).
  Lädt via `--get-nodding-patterns`, speichert **validiert** (JSON + `global`/`patterns`)
  nach `~/Library/Application Support/MulticamCutter/nodding_patterns.json`, „Auf
  Standard zurücksetzen" löscht sie; Engine bevorzugt die User-Datei, Fallback auf
  Defaults bei defekt. **Das AN/AUS einzelner Muster liegt NICHT hier**, sondern pro
  Preset im Wizard (Experteneinstellungen → Cutaway Regeln → Nicken-Muster).
- ~~Lizenz~~-Tab: seit 1.0.1 entfernt (App kostenlos). Alte `lic.*`-UserDefaults
  bei Bestandsnutzern bleiben liegen, werden aber nicht mehr gelesen.

⚠️ Die Settings-Scene muss `.environmentObject(engine)` bekommen (in
`MulticamCutterApp.swift`) — der CLIP-Tab liest `@EnvironmentObject engine`.

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


### Updates (Einstellungen → Allgemein)
`UpdateSettingsSection` (in `Updater.swift`, bewusst neben `AboutView` — beide
hängen am selben `SPUUpdater`). Zeigt die installierte Version, den Schalter
„Automatisch nach Updates suchen" und einen Prüfen-Button.

- **„Beta-Versionen erhalten"** (`@AppStorage("updates.betaChannel")`, Standard aus).
  Hier IST ein eigener Schlüssel richtig: Sparkle speichert keine Kanalwahl, sondern
  fragt sie über `UpdaterChannelDelegate.allowedChannels` ab. Abschalten während eine
  Beta läuft (`UpdateChannel.isBetaBuild`, erkannt an „beta" in der Anzeige-Version)
  → Rückfrage, ob die neueste stabile Version geladen werden soll (`StableRelease`
  liest dazu den Appcast, Delta-Enclosures ausgenommen; Download öffnet im Browser).
  Sparkle selbst installiert nie eine ältere Version.
- **Kein eigener `@AppStorage`-Schlüssel** (für die Auto-Prüfung). Sparkle persistiert den Schalter
  selbst unter `SUEnableAutomaticChecks`; ein zweiter Speicher liefe auseinander.
  Der `UpdaterViewModel` reicht nur durch.
- **Default an**: `SUEnableAutomaticChecks` steht in der Info.plist auf `true`
  (`build_app.sh`). Das ist nur der Startwert — legt der Nutzer den Schalter um,
  gewinnt seine Wahl. `true` unterdrückt zugleich Sparkles Rückfrage beim ersten
  Start.
- **Dev-Build**: ohne `SUFeedURL` startet der Updater nicht
  (`UpdaterController.isActive`). Dann erscheint statt der Bedienelemente ein
  Hinweis — sonst gäbe es einen Button, der ins Leere greift.
- Der automatische Lauf **meldet** nur; installiert wird nach Bestätigung.

## Parameter-Hilfetexte (Tooltips)

Jeder feste Regler/Toggle im Wizard zeigt ein (?) neben dem Label
(`WizHelpBadge`), das den Hilfetext als nativen macOS-Tooltip beim Überfahren
zeigt. `WizSlider`/`WizToggle`/`WizSegmented` haben dafür einen optionalen
`help:`-Parameter. Texte kommen aus `ParamHelp.swift` (verbatim aus dem
Web-Schema). Rubriken mit einem `group(..., description:)` zeigen zusätzlich
einen Einleitungssatz unter der Überschrift (z.B. „Bildsprache"). Textstil:
siehe Memory feedback_ui_texte — einfach, menschlich, kein Fachjargon.

## Einstellungen: Kacheln mit eingeblendeten Expertenwerten (21.11.)

Keine eigene Expertenliste mehr. „Einstellungen" ist eine Abschnitts-Überschrift (wie
„Bildgrößen je Person"), die Kacheln stehen ohne Container im Fenster. „Experteneinstellungen"
blendet in jeder Kachel unter den Stufen-Schaltern die Einzelwerte ein (`ExpertenInhalt`,
`Sources/ExpertenKacheln.swift`), dazu die Kachel „Weitere" (Sprecherschwelle, Wechsel-
verzögerung, Vorlauf, Cutaway-Filter, Analyse-Einblendungen). Zeilen in Kacheln laufen im
kompakten Modus (`\.wizKompakt`: Name + Wert oben, Regler volle Breite darunter).
Verstellte Werte → „angepasst" an der Stufe (wie bisher).

**Kachel „Eyeline“ (23.11.):** eigene Stufen-Kategorie ohne Stufen-Schalter, nur An/Aus
(`eyeline_enabled`, Piktogramm `piktogramm-augenlinie`). Im Expertenmodus darin
„Max. Vergrößerung“ (`eyeline_max_scale`, 100–140 %). Ist sie an, zeigt die Übersicht unter
„Kameras“ je Kamera eine Pille „Eyeline“ (Auge/Auge durchgestrichen) zum Abwählen
(`CameraInfo.eyeline`, in der `.multicam`). Die Ergebnis-Seite listet je Kamera „meist X %,
höchstens Y %“.

**„angepasst" — Bezug je Modus (21.11.):** Einfache Ansicht = Abweichung von der gewählten
Stufe. Experteneinstellungen mit geladenem Preset = Abweichung vom Preset
(`engine.presetReferenz`, gesetzt beim Laden/Importieren/Speichern eines Presets, beim
Öffnen einer anderen Folge zurückgesetzt). Ohne Preset auch im Expertenmodus gegen die
Stufen bzw. den App-Standard. Gilt für den Hinweis an den Stufen und für Flieder-Werte.

**Zurücksetzen (21.11.):** Doppelklick auf den Namen eines Flieder-Werts setzt ihn auf seinen
Vergleichswert zurück (Preset bzw. Stufe/App-Standard, wie bei „angepasst“). Tooltip „Doppelklick setzt zurück“.
