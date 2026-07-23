# Design-System

## Allgemein

- Dark Mode als Default (macOS System-Appearance wird respektiert)
- Native macOS-Controls wo möglich (kein Custom-UI wo SwiftUI reicht)
- Lucide-Icons (fest im Bundle, s. u.) — SF Symbols nur in System-Bereichen
- **Echte Umlaute** in allen UI-Strings (ä, ö, ü, ß) — kein ae/oe/ue

## Farben

**Marken-Akzent: Lime `#C6F24E`** — identisch mit der Website (siehe
`multicamcutter-web/design.md`). Definiert **einmalig** in `Sources/Theme.swift`
als `Color.brandAccent` (auf `ShapeStyle where Self == Color`, damit Leading-Dot
`.brandAccent` in `.foregroundStyle`/`.tint` funktioniert wie SwiftUIs `.blue`).
App-weit gesetzt via `.tint(.brandAccent)` auf den Fenster-Wurzeln (ContentView,
Über-Dialog, Acknowledgements) → treibt `.borderedProminent`-Buttons, Links,
Progress-Bars. Bei Akzent-Änderung: nur Theme.swift + Website angleichen.

**Zweite Akzentfarbe: Flieder/Lila `#CBA6F7`** (`Color.brandSecondary`, ebenfalls
in Theme.swift). **Komplementaerkontrast zu Lime** — loeste das fruehere Orange ab.
Deckt bewusst BEIDE Rollen ab: Akzent (Totale-Marker, Personen) UND Warnzustaende
(FPS-Mismatch-Banner, „wird ignoriert", Lizenz-Grace). Hell genug fuer schwarzen
Text auf Pills und als Textfarbe auf dunklem Grund. (User-Entscheidung: kein
separates Warn-Amber, alles Orange → Lila.)

- `.brandAccent` (Lime) fuer primaere Aktionen, Drop-Highlight, Selection, Pills
- `.brandSecondary` (Lila) fuer Totale-Marker, Personen-Hinweise UND Warnungen
- `.secondary` / `.tertiary` fuer dezenteren Text
- `.green` fuer Erfolg (Checkmark im Result-Screen)
- `.red` fuer Fehler (Error-Screen)
- `.brandAccent.opacity(0.15)` fuer Mic-Pills und Selection-Highlight

## App-Icon

Offizielles Icon (grüner Glow-Orb mit Multicam-Frames + Waveform, „magic core").
Quelle: `multicamcutter-web/assets/AppIcon.icns` (Build-Pipeline dort:
`assets/build-icon.js`, sharp). Ins Toolkit kopiert als `scripts/AppIcon.icns`,
von build_app.sh eingebettet. **Ersetzt** den früheren blauen Pillow-Entwurf
(`scripts/make_icon.py`, obsolet). Bei Icon-Änderung: neue `.icns` aus dem
Web-Repo kopieren.

## Typografie

Noch keine Custom-Fonts. Aktuell System-Defaults:
- `.title2.fontWeight(.medium)` fuer Step-Labels in Progress
- `.title2.fontWeight(.semibold)` fuer Section-Ueberschriften
- `.headline` fuer Cam-Namen in Cards
- `.caption` / `.caption2` fuer Mic-Pills, Dauer-Anzeigen
- `.system(.body, design: .monospaced)` fuer Prozent, ETA, Timecodes
- `.subheadline` fuer "Schritt X von Y"

## Spacing / Layout

- Sidebar: ideal 220px (min 180, max 300)
- Camera-Cards: LazyVGrid adaptive 220-300px, 16px spacing
- Card-Innenabstand: 10px
- Card-Eckenradius: 10px
- Section-Abstaende: 24px vertikal
- Horizontal-Padding: `.padding(.horizontal)` (16px default)

### Fenster-Verhalten (24.07., User-Entscheid)
Das Hauptfenster ist **nicht vom Nutzer skalierbar** — Groesse folgt dem Inhalt:
- **Inhaltsbreite: 1080 pt** fuer ALLE Wizard-Seiten (`WizardLayout.contentWidth`,
  WizardView.swift) — der Standard ist die fruehere Screen-3-Breite (revidiert
  24.07.: bei 720 brachen die Uebersichts-Spalten der Seite 3 um). Auch die
  Audio-Cards auf Seite 1 folgen dem Standard.
  Fensterbreite = 1080 + 2×28 Rand = **1136 pt** (`wizardWindowWidth`, ContentView).
- **Hoehe: automatisch je Seite** (Content-Fitting): Wizard meldet Inhalts- und
  Viewport-Hoehe per PreferenceKey, die Differenz wird animiert ausgeglichen
  (Oberkante fix). Reagiert auch auf Aenderungen innerhalb einer Seite
  (Experteneinstellungen, Banner-Auto-Dismiss, viele Audio-Cards).
- **Max-Hoehe: min(1100 pt, Bildschirm-visibleFrame − 24)** — darueber wird der
  Inhalt scrollbar (z. B. Seite 1 mit sehr vielen Audioclips).
- **Min-Hoehe: 520 pt.**
- **Analyse-Fenster: fix 760×552** (eigene Sperre, unveraendert).
- Stabilitaets-Sicherungen (Endlos-Pump-Lehre 24.07.): kein Fit waehrend der
  Animation (ein Korrekturlauf nach Settle), Flip-Flop-Detektor, inLiveResize-
  Guard. Mechanik: `fitWindowToWizardContent`/`enforceWizardWindowChrome`
  (ContentView.swift).

## Komponenten-Stile

### Fluechtige Informationen (UI-Regel, 24.07.)
Info-Banner, die nur informieren und keine Entscheidung blockieren, blenden
sich nach **~7,5 s automatisch aus** — via `.autoDismiss { … }`
(`AutoDismiss.swift`). Verhalten: Hover pausiert das Ausblenden (wer liest,
wird nicht ueberrascht), das X schliesst sofort, Ausblenden mit
`.transition(.opacity)` + easeOut 0,4 s.
- **Anwenden auf:** reine Status-/Bestaetigungs-Infos (z. B. „Ordner bekannt —
  Zuordnungen geladen"; dass dabei der Reset-Link mit verschwindet, ist ok —
  User-Entscheid).
- **NICHT anwenden auf:** Warnungen, die eine Handlung erfordern oder einen
  Zustand beschreiben, der bestehen bleibt (FPS-Mismatch-Badge, Fehler,
  Blocker, Material-Warnungen).

### Buttons
- Primaer: `.buttonStyle(.borderedProminent).controlSize(.large)` (Start-Button)
- Sekundaer: `.buttonStyle(.bordered)` (Abbrechen)
- Destruktiv: `.buttonStyle(.bordered)` + `role: .destructive` (Abbrechen waehrend Run)
- Inline: `.buttonStyle(.plain)` (Play/Pause in Pills, Pencil-Icon)

### Cards (CameraCard)
- Background: `Color(.controlBackgroundColor)`
- Border: `Color(.separatorColor)` 0.5px, blau 2px bei Drop-Target
- Drop-Highlight: `Color.blue.opacity(0.15)` Background

### Parameter-Hilfe ((?)-Tooltips)
- Hinter **jedem** Parameternamen ein (?) — `questionmark.circle`, `.caption`,
  `.secondary` — Erklärung als Tooltip via `.help(...)` beim Hovern.
- Bausteine in `ParamHelp.swift`: `HelpBadge` (nur das (?)), `HelpLabel`
  (Titel + Badge, für Picker/eigene Zeilen), `HelpToggle` (Toggle mit Badge).
  `ParameterRow` hat einen optionalen `help:`-Parameter.
- ⚠️ **Gotcha**: SwiftUIs `.help(...)` allein zeigte in den Form-Zeilen **keinen**
  Tooltip (macOS 26, weder Hover noch Klick). Deshalb liegt in `HelpBadge` ein
  transparenter AppKit-`NSView` mit `toolTip` als `.overlay` darüber
  (`AppKitToolTip`) — der wirkt zuverlässig. `.help(...)` bleibt zusätzlich für
  VoiceOver/Fallback. Bei neuen Tooltips **immer `HelpBadge` nutzen**, nicht `.help` pur.
- **Texte verbatim aus `config/schemas/multicam_params.json`** (Feld `help`), damit
  App und Web-UI Parameter identisch erklären. Bei Änderung: **beide** Orte nachziehen.
  Ausnahme `fps` (app-spezifisch, im Web-Schema nicht vorhanden).

### Pills (MicPill)
- Background: **voller `.brandAccent`** (Lime, keine Opacity)
- Vordergrund: **schwarz** — auf dem Lime-Akzent muss alles Dunkle sein (wie die
  Website: `--primary-foreground` = near-black). Text + mic-Icon `.black`,
  Sekundär-Icons (Entfernen/Play) `.black.opacity(0.55)`, Play-aktiv `.black`.
- Shape: `Capsule()`
- Padding: 8px horizontal, 4px vertikal

### Progress
- Bar: `.progressViewStyle(.linear)`, 400px breit
- Log: `DisclosureGroup`, 500px breit, 180px hoch

## Icons (Lucide)

Icon-Set der Website (lucide.dev, ISC). SVGs FEST im App-Bundle: exakt aus
lucide-react 1.24.0 des Website-Repos extrahiert (`scripts/extract_lucide.py`),
stroke-width **2.5** statt Lucide-Default 2 (User-Entscheid 24.07.: kräftiger).
Rendering: `LucideIcon("name", size: N)` bzw. `LucideLabel("Text", icon:size:)`
als Drop-in für `Label(_:systemImage:)` — Template-NSImage, tintbar via
`.foregroundStyle`. Neues Icon: `python3 scripts/extract_lucide.py <name>`
(Achtung: manche Namen sind Aliase, z. B. circle-help → circle-question-mark).

| Kontext | Lucide-Icon |
|---------|-------------|
| Ordner | folder, folder-plus |
| Kamera fehlt | video-off |
| Play/Pause (Mic-Vorschau) | circle-play, circle-pause |
| Entfernen | x, circle-x, trash-2 |
| Bearbeiten | pencil |
| Erfolg | check, circle-check |
| Warnung/Fehler | triangle-alert, octagon-x |
| Analyse starten | play |
| Hilfe-Badge (?) | circle-question-mark |
| Session/Verlauf | history |
| Zurücksetzen/Konvertieren | undo-2, refresh-cw |
| Lizenz gültig/ungültig | badge-check, badge-x |
| CLIP/Magie | sparkles |
| Totale-Badge | columns-2 |
| Info | info |
| Feedback | message-square-warning |
| Erste Schritte | list-checks, audio-waveform, speech, refresh-cw |
| Log/Lizenzen | copy, file-text, file-search, external-link |
| Mehr-Menü | circle-ellipsis |
| Chevrons | chevron-up, chevron-down |
| Download/Schutz | circle-arrow-down, shield-check |

**Ausnahmen (bleiben SF Symbols):** Settings-Tab-Icons (gearshape, sparkles,
chevron.up.chevron.down, key) und Menüeinträge — dort rendert das System die
Icons selbst, eigene Bilder skalieren unzuverlässig.
