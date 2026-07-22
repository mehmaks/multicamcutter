# TODOs

## Offen

### ~~Fortschritt: aktuellen Pass im Cutaway-Schritt anzeigen~~ — UMGESETZT (21.07.)
Geloest wie unten skizziert: neuer Protokoll-Typ `step_detail` (setzt nur den
Text, **ohne** `stepNum` zu erhoehen), Pass-Banner werden in `protocol.py`
**vor** der `...`-Erkennung geprueft. Zuordnung wie in der Tabelle.

Der Schritt heisst pauschal „Cutaways einfügen" und laeuft je nach Material
minutenlang. Man sieht nicht, **welcher** Pass gerade rechnet — und damit nicht,
wo die Zeit haengen bleibt. Gewuenscht: der Text nennt die aktuelle Art,
benannt **wie der zugehoerige Schalter in den Einstellungen**, damit klar ist,
welcher Parameter die Laufzeit verursacht.

Vorgeschlagene Zuordnung (Banner in `add_reactions_to_edl.py` -> Anzeige):

| Pass | Banner | Anzeige |
|---|---|---|
| 1 | `PASS 1: Parse Resolve EDL` | Schnittliste einlesen |
| 2 | `PASS 2: Cutaways einfügen` | Kopfnicken-Cutaways einfügen |
| 2b | `PASS 2b: Pause-Cutaways` | Pausen-Cutaways einfügen |
| 3 | `PASS 3: Cleanup kurzer Events` | Kurze Einstellungen aufräumen |
| 4 | `PASS 4: Split zu lange Shots` | Lange Einstellungen teilen |
| 5 | `PASS 5: CLIP Ignore-Filter` | **Ungünstige Cutaways verschieben** |

Pass 5 ist der teuerste (CLIP) und der Anlass fuer den Wunsch.

**Zwei Fallstricke:**
1. Die Erkennung in `engine/protocol.py:78` greift nur bei Zeilen, die auf
   `...` enden. Die PASS-Banner tun das nicht und landen nur im Log — sie
   muessen zusaetzlich per `PASS <n>` erkannt werden.
2. `step_start_sub` **erhoeht den Schrittzaehler** (`EngineController.swift:1617`).
   Ein `step_start_sub` je Pass machte aus „Schritt 6 von 8" ein „Schritt 11 von 8".
   Daher braucht es eine Variante, die **nur den Text** setzt — etwa ein neuer
   Typ `step_detail` oder ein Feld `"advance": false`.

Aufwand: ~10 Zeilen `protocol.py` + ~5 Zeilen Swift + Eintrag in
`brain/Engine-Protokoll.md`. Braucht ein Neu-Einfrieren der Engine, geht also
fruehestens in 0.5.3.

### Sprachreaktionen — dokumentiert, bewusst nicht umgesetzt
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
- [ ] **Mic-Trennung anzeigen statt warnen.** Die Trennung je Richtung ist ohne Labels
  messbar und korreliert mit der FP-Rate (r = −0,65, n=6). Eine Warnschwelle bei 12 dB
  würde aber bei **2 von 3** Folgen feuern und damit weggeklickt. Besser: den Wert im
  Ergebnis nennen („Cam A 10,8 dB, Cam B 25,2 dB"), damit über Folgen hinweg sichtbar
  wird, was normal ist. ⚠️ Nicht als Gate missbrauchen: 10,5 dB → 28 % FP, 15,0 dB →
  75 % FP. Zu wackelig, um Verhalten daran zu hängen.
- [x] **Voice Leveler als Pre-Process — GEMESSEN, bringt nichts.** Idee: `voice_leveler.py`
  vor der Analyse laufen lassen, um Pegel anzugleichen. Test an ep04 (3 min, beide Mics,
  Gate −45 dB, Low-Level-Boost +8, Ziel −16 LUFS):
  Trennung roh **22,8 / 7,9 dB**, gelevelt **22,2 / 8,1 dB** — unverändert.
  **Warum es prinzipiell nicht gehen kann:** Ein Prozessor pro Spur sieht immer nur
  *eine* Spur. Um die Trennung zu verbessern, müsste er Übersprechen dämpfen — aber
  Übersprechen ist auf einer einzelnen Spur nicht von einer leisen Reaktion zu
  unterscheiden. Genau daran scheitert auch das vorhandene Crossbleed-Gate, weshalb die
  Sprachreaktions-Erkennung es bewusst NICHT benutzt. Die nötige Information ist die
  **Beziehung zwischen den Spuren** — und genau die nutzt Regel A.
  → Als **Ausgabe**-Bearbeitung des fertigen Tons bleibt der Leveler sinnvoll; das ist,
  wofür er gebaut wurde, und es berührt die Erkennung nicht.

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

### UI / UX
- [ ] **Waveform je Audiospur + Klick-zum-Abspielen** (Fremd-Feedback, 22.07.) —
  Aufwand: **mittel**.
  **User-Story:** Cutter bekommen teils UNBEKANNTES Material und müssen schnell
  rausfinden, wer auf welcher Spur spricht. Der heutige Ansatz — Play-Button
  spielt die getrimmte Vorschau ab der ersten lauten Stelle (`previewPath`) — ist
  dafür **zu unzuverlässig**: man hört einen Ausschnitt, kann aber nicht gezielt
  an eine Stelle springen.
  **Gewünscht:** Jede Audiospur (im Personen/Mic-Schritt, `MicRow` in
  WizardView) zeigt eine **visualisierte Waveform**. **Klick auf eine Position**
  → Wiedergabe genau dort. So hört man in Sekunden rein, an mehreren Stellen,
  und ordnet die Spur einer Person zu.
  **Technik:**
  - Wiedergabe ab Position: `AVAudioPlayer.currentTime` setzen (statt neu vom
    Anfang) — der Player-Umbau in `toggleMicPreview`/`playingMicId`
    (`EngineController`) ist überschaubar. Play/Pause + Fortschritts-Cursor.
  - Waveform-Daten: heruntergerechnete Peak-Werte je Pixel. Entweder in Swift
    (`AVAudioFile` → Samples lesen → Min/Max je Bucket) oder die Engine liefert
    beim Scan ein Peak-Array je Datei (JSON). Swift-seitig hält die Daten aus
    dem Prozess raus; Engine-seitig ist es zentral und cachebar. **Entscheiden.**
  - Über die volle Datei, nicht nur die Vorschau — sonst bleibt die
    Navigations-Lücke. `previewPath` wird damit für diesen Zweck obsolet.
  **Verwandt:** die früher gewünschte NLE-artige Timeline-Darstellung des
  fertigen Schnitts nutzt dieselbe Waveform-Rendering-Basis — beim Bau
  zusammendenken.

- [x] **Changelog mehrsprachig (DE/EN)** — UMGESETZT (22.07.), Format mit Web-Session abgestimmt.
  Die Website bietet DE/EN, das Changelog sollte das auch. Sparkle unterstuetzt
  `xml:lang` auf `<description>` (mehrere pro `<item>`, Auswahl nach Systemsprache).
  Drei Bausteine:
  1. **Englischer Changelog**: entweder EN-Abschnitte in `CHANGELOG.md` oder ein
     separates `CHANGELOG.en.md`. (Entscheidung: eine Datei mit beiden vs. zwei.)
  2. **`generate_appcast` kann kein `xml:lang`** — es bettet nur EINE `<description>`
     ein. Also: nach `generate_appcast` den Appcast nachbearbeiten und je Item eine
     zweite `<description xml:lang="en">` (CDATA) einfuegen, ODER die Items selbst
     bauen. `changelog_to_html.py` bekommt einen Sprach-Parameter.
  3. **⚠️ Website-Contract abstimmen** (mit der Web-Session): wie liest die Website
     die Sprache? Ueber `xml:lang` auf `<description>` (naheliegend) oder ueber
     `sparkle:releaseNotesLink` je Sprache? Beide Seiten muessen dasselbe Format
     erwarten. NICHT einseitig festlegen.
  Nicht fuer 0.6.1 (geht deutsch-only raus). Fuer die naechste inhaltliche Version.

- [x] **Materialhinweis: Punkt „Sprecherwechsel zwischen zwei Nahaufnahmen" gestrichen**
  (22.07., doch noch in 0.6.1 gezogen). Ersatzlos raus, contentRevision 2→3. Er passt nicht zur Überschrift
  „Was dein Material mitbringen muss": die anderen drei Punkte sind echte Anforderungen
  (Tonspur je Kamera, Mikro je Person, zeitliche Überlappung), dieser beschreibt
  App-Verhalten (binäre Diarisierung, Totalen als Cutaway) und ist zudem zu komplex
  formuliert. Ersatzlos entfernen. `FirstRunSheet.swift`, das `person.2`-Requirement.
  Danach `contentRevision` erhöhen, damit bestehende Tester die kürzere Fassung sehen.

- [x] ⚠️ **TEST-DEFAULT entfernt (22.07.):** ~~`run_from_bin.py` belegt
  `transition_cutaway_back` mit `['nodding']` vor, damit die Dev-App die
  Cutaway-Rückwege ohne UI zeigt. Der Matrix-Default ist AUS. Sobald die
  Bildsprache-Rubrik existiert…~~ Erledigt: Werte kommen jetzt aus den
  Experteneinstellungen (Bildsprache-Gruppe), `run_from_bin` hat keine
  transition-setdefaults mehr.

- [ ] **Clipnamen im AAF: Schnittgrund vor Quellname.** Aufwand: **leicht** (Stufe 1).
  Heute `{stem} - {label}` (`build_aaf.py:483`), z.B.
  `VID_20250710_101101_00_002_004_25… - Übergang`. Bei langen Quellnamen (GoPro/DJI,
  Totale) wird der Name vom Resolve-Clipfeld abgeschnitten und der **Grund ist nicht
  mehr sichtbar** — beobachtet am 21.07. Der Grund ist beim Sichten aber die
  wichtigere Information.
  - **Stufe 1:** Reihenfolge umdrehen → `Übergang - C0352` bzw. mit Person
    `Übergang - Andreas`. Steht der Grund vorn, überlebt er das Abschneiden.
  - **Stufe 2:** Als **Toggle** in den Einstellungen (Grund-zuerst / Quelle-zuerst),
    Default noch zu entscheiden.
  - **Stufe 3 (später, wenn sinnvoll):** freies Muster per Wildcards, z.B.
    `{reason} · {person} ({source})`. Erst bauen, wenn ein konkreter Bedarf über
    die zwei festen Varianten hinausgeht — sonst ist es Konfiguration ohne Nachfrage.

- [x] **Changelog: in der App sichtbar UND auf der Website.** UMGESETZT (22.07.):
  Nutzer sollen sehen, was ein Update bringt — heute steht im Update-Dialog nur
  eine Versionsnummer.

  **Sparkle kann das bereits, wir nutzen es nur nicht.** Der Appcast enthaelt
  aktuell weder `<description>` noch `<sparkle:releaseNotesLink>` (geprueft
  21.07.: nur title, version, enclosure, pubDate, minimumSystemVersion,
  hardwareRequirements, deltas). `generate_appcast` bietet dafuer fertige
  Schalter: `--embed-release-notes` (Notizen direkt ins Item) bzw.
  `--release-notes-url-prefix` / `--full-release-notes-url` (Verlinkung auf die
  Website). Damit erscheinen die Notizen **ohne eigene UI** im Sparkle-Dialog.

  **NICHT direkt aus Git generieren.** Die Commit-Botschaften hier sind bewusst
  entwicklungsnah (Ursachen, Dateinamen, Zeilennummern) — als Nutzertext waeren
  sie unbrauchbar bis verunsichernd. Besser: eine gepflegte `CHANGELOG.md` im
  Repo (gibt es noch nicht) als EINE Quelle, aus der beim Release erzeugt wird:
  1. Abschnitt der Version → `release/updates/<version>.html` fuer Sparkle
  2. derselbe Abschnitt → Seite auf der Website (Appcast verlinkt dorthin)
  3. optional ein „Was ist neu"-Fenster in der App nach einem Update — der
     `firstRunInfoSeenRevision`-Mechanismus aus `FirstRunSheet` ist dafuer das
     passende Muster (Stand merken, bei Aenderung einmalig zeigen).

  **Reihenfolge:** erst CHANGELOG.md + Sparkle-Verlinkung (klein, sofort
  sichtbar im Update-Dialog), das eigene Fenster in der App danach.
  ⚠️ `release.sh` muesste beim Fehlen eines Abschnitts fuer die Version
  **abbrechen** — sonst geht stillschweigend ein Release ohne Notizen raus,
  und das faellt wieder erst beim Nutzer auf.

- [ ] **Dock-Fortschritt auch bei der FPS-Konvertierung.** Aufwand: **leicht**.
  🎨 Kosmetisch, blockt nichts — aber die Konvertierung dauert laenger als vieles
  andere (Faustregel im UI-Text: ~10 min pro GB; im Test 67 min Material →
  ~15 min geschaetzt). Genau dann legt man die App in den Hintergrund und will
  am Dock-Icon sehen, wie weit sie ist.
  **Ist-Zustand:** Der Dock-Balken haengt ausschliesslich am Analyse-Lebenszyklus
  (`ContentView.handleMacIntegrations`, `updateDockProgress` → `guard engine.state
  == .running`). Waehrend `isConverting` passiert am Dock nichts.
  **Zu tun:** Auf `isConverting` genauso reagieren wie auf `.running` — beim Start
  `DockProgress.shared.show(0)`, beim Ende `hide()`.
  **Fortschritt ist schon da** (`EngineController`): `convertFileIndex` /
  `convertFileCount` (Datei n von m) plus `convertDone` / `convertTotal`
  (Sekunden innerhalb der Datei). Sinnvolle Gesamtfraktion:
  `(convertFileIndex - 1 + convertDone / max(convertTotal, 1)) / convertFileCount`.
  ⚠️ **Achtung bei `convertTotal == 0`** — laut `brain/Engine-Protokoll.md` heisst
  das „wird vorbereitet", nicht „fertig". Sonst springt der Balken auf 100 %.
  ⚠️ Analyse und Konvertierung schliessen sich aus, aber der Abbruch-Pfad
  (SIGTERM) muss den Balken ebenfalls ausblenden, sonst bleibt er stehen.

- [x] **CLIP-Schritt: „ETA: 199/382" ist keine ETA.** UMGESETZT (21.07.):
  Der CLIP-Pass rechnet seine ETA jetzt selbst (`add_reactions_to_edl.py`,
  `clip_start_time` + Hochrechnung wie bei Nodding) und sendet
  `__PROGRESS__ <pct> <M:SS> <done>/<total>`. `protocol.py` unterscheidet die
  Zusatzfelder nach **Form** statt nach Position (`\d+:\d\d` vs. `\d+/\d+`) —
  damit wandert der Fehler nicht nur weiter — und liefert `eta` **und**
  `counter`. Anzeige: „88%  341 von 384  ETA: 4:12".
  Alte Beschreibung zur Nachvollziehbarkeit:
  **Ursache:** Zwei Formate auf demselben Kanal. Nodding sendet
  `__PROGRESS__ <pct> <M:SS>` (echte ETA aus `elapsed/done`,
  `video_reaction_analyzer_v2.4.py:900-911`), CLIP sendet
  `__PROGRESS__ <pct> <checked>/<total>` (`add_reactions_to_edl.py:955`).
  `engine/protocol.py:109` nimmt blind `parts[1]` als `eta`, `ContentView.swift:456`
  schreibt „ETA:" davor → „ETA: 199/382".
  **Zu tun:** CLIP rechnet seine ETA selbst, genau wie Nodding es schon tut — die
  Schleife hat `checked`, `total_cutaways` und kann die Startzeit mitführen. Dann
  liefern beide Schritte dasselbe Format und der Zähler kann **zusätzlich** angezeigt
  werden („199 von 382 · ETA 4:12") statt als ETA missbraucht.
  Alternative (ohne Engine-Änderung): Swift misst die Abstände zwischen
  `step_progress`-Nachrichten und extrapoliert. Funktioniert für **jeden** Schritt,
  der X/Y meldet — dafür neuer Zustand in `EngineController`. Engine-seitig ist
  konsistenter, weil der Mechanismus schon existiert.
  ⚠️ Beim Umbau `parts[1]` nicht weiter blind interpretieren: unterscheidbar über
  `\d+:\d\d` (Zeit) vs. `\d+/\d+` (Zähler), sonst wandert der Fehler nur weiter.
- [x] **Analyse-Modus: feste Fenstergröße statt nur schmaler.** UMGESETZT (21.07.):
  `runHeight = 552` (am laufenden Fenster ausgemessen), `WindowConstraints` merkt
  min/max/Stil vor dem Lauf, `applyRunWindowLock()` sperrt Breite **und** Höhe für
  die Dauer der Analyse und gibt sie danach wieder frei. Idempotent und zusätzlich
  als Heartbeat aus `updateDockProgress()` aufgerufen, weil SwiftUI die Constraints
  nach Layout-Wechseln sonst wieder aufweicht.
  Beim Start der Analyse verschmälert sich das Fenster bereits (`ContentView.animateWindowWidth`),
  aber es ist **auch zu hoch** — im Analyse-Zustand steht kaum Inhalt drin.
  Gewünscht: feste Breite **und** Höhe für die Dauer des Laufs, und in dieser Zeit
  **nicht vom User skalierbar** (Resize-Sperre), danach zurück auf den vorherigen Frame.
  Anknüpfpunkt: dort wo heute `frameBeforeRun` gemerkt und bei `.ready`/`.idle`
  freigegeben wird — die Logik existiert, es fehlt die Höhe und das Sperren.
  Konkrete Zielwerte noch festzulegen (am laufenden Analysefenster ausmessen).
- [x] **Hinweis-Fenster beim ersten Start: technische Voraussetzungen.** UMGESETZT (21.07.):
  `FirstRunSheet.swift`, `@AppStorage("hasSeenFirstRunInfo")`, per Sheet aus
  `ContentView.onAppear` (0,4 s verzoegert, sonst sitzt es ohne Elternfenster).
  Ueber Einstellungen -> Hinweise zuruecksetzbar.
  **Beim Schreiben zwei Annahmen korrigiert:** Bildraten muessen NICHT
  uebereinstimmen (die App erkennt Abweichungen ueber `fpsMismatches` und bietet
  `--convert-fps` an) — steht jetzt als Entwarnung drin. Und die Grenze sind zwei
  **Kameras**, nicht zwei Sprecher: `rms_diarize` vergleicht zwei Seiten, aber jede
  Seite nimmt eine LISTE von Mics (`combine_audios` → elementweises **Maximum**).
  Mehrere Personen pro Kamera funktionieren deshalb vollständig.
  (Diese Zeile stand zwischenzeitlich falsch herum — korrigiert 21.07.)
  Alte Beschreibung:
  Erst-Start-Sheet (einmalig, `@AppStorage`-Flag), das die Anforderungen ans Material
  erklärt — bevor der User in einen unnötigen Fehlversuch läuft. Mindestens:
  - **Jede Videospur braucht einen eigenen Referenzton.** Der Waveform-Sync korreliert
    den Kamera-Ton; eine Cam ohne (brauchbare) Tonspur lässt sich nicht synchronisieren.
  - Eine eigene Mic-/Tonspur je Sprecher:in (1 Person = 1 Mic).
  - Alle Quellen müssen dieselbe Timeline-FPS haben (sonst greift der FPS-Konverter).
  - Aufnahmen sollten sich zeitlich überlappen (sonst findet die Korrelation nichts).
  Später ggf. mit den Grenzen aus `Bekannte-Bugs.md` abgleichen (z. B. aktuell max. 2 Cams).
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

  **NOCH OFFEN — für ECHT getrennte Quellen** (separater Recorder mit Clock-Drift,
  Funk-Lav ohne Raumklang): „nicht syncbar"-Liste zurückgeben statt abbrechen +
  manueller Offset/Ausschluss pro Quelle in der App (Baustein 2+3). Baustein 1
  (gegen ALLE Partner inkl. Cams gegenprüfen) — siehe unten, wird als Nächstes
  gebaut.

### 🔴 N-Sprecher-Diarisierung (3 Personen auf 3 EIGENEN Cams) — HOCHPRIORISIERT (22.07.) — Aufwand: **mittel**
*(Vom User am 22.07. wieder nach oben gesetzt: Das ist die letzte Beschraenkung, die
echte Mehr-Kamera-Setups blockiert — der Waechter sperrt >2 Nahaufnahmen NUR wegen
der binaeren Diarisierung. `rms_diarize` vergleicht zwei Seiten (CAM1/CAM2); eine
dritte Nahaufnahme kann nie als Sprecher gewaehlt werden. Loesung: argmax ueber N
Mics statt Differenz zweier Seiten — Teil B in Plan-Multicam-3plus.md. Der Sync
(Teil A) ist bereits N-faehig, es fehlt nur noch die Diarisierung.)*

**✅ KERN GEBAUT (23.07.) — B1:** `rms_diarize_n(audios, ..., labels, silence_gates_db)`
in `build_base_edl_from_audio.py`: pro Fenster gewinnt die lauteste Gruppe, aber nur
mit Vorsprung > threshold; Stille nur wenn JEDE Gruppe unter ihrem Gate. `rms_diarize`
ist jetzt ein byte-identischer N=2-Shim darauf. Sicherheitsnetz: `test_diarize.py`
(80 Zufallslaeufe alt==Shim + N=3-Attribution + Margin-Gate). **NOCH offen (invasiv):**
`build_base_edl_from_audio.main` (`--mic-cam1/2` → N Gruppen, Label→Clip ueber Liste,
Vor-Start-Swap, `detect_*`/`insert_totale_events` verallgemeinern), `run_analysis`
(`cam_paths[0/1]`-Bindung, `_wide_at_front`, `totale_idx`), B3 (`smallest_containing`),
und die 3 Waechter entfernen (Swift `unsupportedCloseCams`, `_wide_at_front`, sequencer
`NotImplementedError`).
- [ ] **Basis-EDL von binär (2 Cams) auf N-fach umstellen.** User-Kontext: Podcast hat
  **häufig Host + 2 Gäste = 3 Personen**, also kein Edge-Case.
  ⚠️ **Weniger dringend als hier lange behauptet** (geklärt 21.07.): Die Grenze sind
  zwei **Kameras**, nicht zwei **Personen**. Jede Seite nimmt eine LISTE von Mikrofonen
  (`load_and_combine`, Maximum), und die App kann sie auch senden (`camMicsArgs` → `"0,1"`).
  Host + 2 Gäste läuft daher **vollständig**, solange sich die Gäste eine Kamera teilen —
  vom User so getestet. Offen ist nur der Fall **drei Personen auf drei eigenen Kameras**,
  jede einzeln angeschnitten.
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
- [x] **Warnung „Auffällig kurze Kamera" entschärft (22.07.):** Der Text behauptete
  „meist eine abgebrochene Konvertierung" und riet „Datei löschen und neu
  konvertieren" — bei legitim kurzen Kameras (Gast früher weg, GoPro/DJI-Fragment)
  irreführend. Neu: beschreibt das Symptom (Standbild ab dem Kamera-Ende) und
  nennt BEIDE Fälle (ungewollt → Datei ersetzen; wirklich kürzer aktiv →
  fortfahren, Standbild beachten). Das eigentliche Unterdrücken bei erkannten
  Split-Fragmenten bleibt für die Split-Logik offen.
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

### 🟡 Sync-Robustheit: gegen Mics statt gegen CAM1 — Aufwand: **mittel**
> 📋 **Detaillierter Umbauplan: `brain/Plan-Multicam-3plus.md`** (Sync + Schnitt-Logik,
> Reihenfolge, Verifikation, offene Produktfragen).
- [ ] **⚠️ Enthält einen echten Bug: Cams ab Nr. 3 werden gar nicht gesynct** (bekommen
  stumm Offset 0) — Details in `brain/Bekannte-Bugs.md` → OFFEN. Bewusst **zusammen mit
  der Multicam/Close-Totale-Session** angehen, weil die Referenzlogik davon abhängt.
  Bei 2 Cams (bisheriger Normalfall) tritt es nicht auf.
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

### Nodding-Einstellungen
- [x] **Settings-Tab „Nodding"** — UMGESETZT (4. Tab). Roher JSON-Editor der
  `nodding_patterns.json` (ganze Datei inkl. Globals + Pattern-Filter/Confidence).
  Speichert **validiert** nach `~/Library/Application Support/MulticamCutter/
  nodding_patterns.json`; Engine bevorzugt sie (`effective_nodding_patterns_path()`,
  `_load_nod_patterns()`), fällt bei defekter Datei auf Defaults zurück (Analyse bricht
  nie). Neues Engine-Kommando `--get-nodding-patterns`. „Auf Standard zurücksetzen"
  löscht die User-Datei. Bewusste Erweiterung der alten „UI nur enabled-Flags"-Regel
  (die galt gegen Preset/config.ini-Duplikate — die bleiben unberührt).
  ⚠️ **Braucht PyInstaller-Rebuild** fürs ausgelieferte Bundle (Dev via `swift run` sofort).

### macOS-Integration
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
- [ ] **Dock-Balken oszillieren lassen, wo die App es auch tut.** Aufwand: **mittel**.
  Regel im Fenster: `stepPercent > 0` → determinate, sonst oszillierend
  (`ContentView.swift:444-466`). Dieselbe Regel im Dock anwenden.
  ⚠️ **Haken:** `NSDockTile` animiert nicht von selbst — `DockProgressView` zeichnet
  nur, wenn `display()` gerufen wird. Ein oszillierender Balken braucht also einen
  Timer (~10–15 fps), der eine Phase weiterdreht und neu zeichnet. Der Timer **muss
  auf jedem Ausstiegspfad sterben** (fertig, Fehler, Abbruch), sonst zeichnet er nach
  dem Lauf weiter — dieselbe Fehlerklasse wie der Balken, der nach der Analyse stehen
  blieb (siehe `Bekannte-Bugs.md`).
- [x] **Dock-Fortschrittsbalken während der Analyse** — `DockProgress`
  (`MacIntegrations.swift`), gekoppelt in `ContentView` an `engine.overallProgress`.
  Sichtbar auch bei minimierter App.
- [x] **System-Notification bei Analyse-Ende** — `AnalysisNotifier`
  (`UserNotifications`): abgeschlossen / fehlgeschlagen / abgebrochen. Banner nur wenn
  App nicht im Vordergrund. ⚠️ Nur im gebauten `.app` (Bundle-ID), im Dev übersprungen.
- [x] **Nodding-Pattern-Toggles PRO PRESET** (korrigiert von „global"): Toggles im
  Wizard (Experteneinstellungen → Cutaway Regeln → Nicken-Muster), gespeichert in
  `PipelineParams.noddingPatterns` → Preset/.multicam. Engine wendet sie via
  `_load_nod_patterns(enabled_overrides=params['nodding_patterns'])` an. Der
  Settings→Nodding-Tab editiert nur noch die globalen Schwellen.
- [x] **Wizard-Experteneinstellungen 1:1 zur Web-UI/Schema** (Benennung + Reihenfolge):
  Generelle Schnittregeln · Sprecher-Erkennung · Pausen-Trimming (+ Schnittmodus-Picker)
  · Crossbleed-Filter · Cutaway Regeln · Totale-Cam Schnittlogik. Neuer `WizPicker`.
  LUT bewusst weggelassen (auf Halde).

### Analyse-Input: LUT / Kontrast (auf Halde, niedrige Prio)
- [ ] **LUT-Picker für die MediaPipe-Analyse in der Mac-App exponieren.** Aufwand:
  **leicht** (Backend fertig). Das `--lut`-Flag (.cube) ist bereits end-to-end
  durchgereicht: `run_from_bin.py --lut` → `video_reaction_analyzer_v2.4.py`
  (`lut3d` in der ffmpeg-`-vf`-Kette, wo die Analyseframes für MediaPipe entstehen).
  Es fehlt nur ein Datei-Picker in den Settings + Durchreichen an die Engine.
  Zweck: Log-Material vor MediaPipe nach Rec.709 wandeln. **War im Web-UI schon da.**
  ⚠️ **Auf Halde**: User hat in eigenen Analysen **keinen qualitativen Unterschied**
  bemerkt, ob MediaPipe mit oder ohne LUT lief → geringer Nutzen. Erst umsetzen, wenn
  ein konkreter Log-Problemfall auftaucht (dann mit Vergleichs-Durchlauf: Nodding-
  Events mit/ohne LUT).
  Alternative ohne LUT: generischer Auto-Kontrast-Filter (`eq`/`normalize`/`curves`)
  in dieselbe `-vf`-Kette, per Toggle — analog zum kosmetischen Thumbnail-Toggle, aber
  Engine-seitig. Ebenfalls nur bei Bedarf. (Beides braucht PyInstaller-Rebuild fürs Release.)
- [ ] **Log-Footage automatisch erkennen und LUT-Hinweis einblenden.** Aufwand: **leicht**.
  ⚠️ **Hängt am LUT-Punkt darüber** — ergibt erst Sinn, sobald der LUT-Parameter wieder
  exponiert ist. Vorher hätte der Hinweis keine Handlungsoption.
  **Idee:** Das beim Scan ohnehin erzeugte Thumbnail je Videodatei aufs **Kontrastprofil**
  messen. Ist der Kontrast auffällig gering (typisch für Log-Material), einen dezenten
  Hinweis einblenden, dass ein LUT sinnvoll wäre.
  **Technisch:** Das JPEG liegt bereits vor (`CameraInfo.thumbnailPath`), die Messung ist
  billig — z. B. Histogramm-Spreizung über CoreImage (`CIAreaMinMax` / `CIAreaHistogram`)
  oder schlicht Standardabweichung + Perzentil-Abstand (P5→P95) der Luma. Auswertung in
  Swift beim Scan, kein Engine-Eingriff nötig.
  ⚠️ **Falsch-Positive bedenken:** Auch eine dunkle, neblige oder flaue Szene ist
  kontrastarm. Der Hinweis darf deshalb nur **weich** formuliert sein („könnte Log-Material
  sein") und niemals blockieren. Ggf. über mehrere Scrub-Positionen mitteln statt nur den
  einen Initial-Frame zu messen.

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

### AAF: Clipnamen als Schnitt-Begründung nutzen
- [x] **UMGESETZT 20.07.** (`build_aaf.py`, Commit `c225289`). Eine MasterMob je
  (Kamera × Grund), Namen wie `CAM_B - Sprachreaktion`. Quelle ist **nicht** eine neue
  EDL-Kommentarzeile, sondern das bereits existierende Sidecar `final.colors.json`
  (`add_reactions_to_edl.py:1295`) — das „fehlende Glied" unten war also schon da.
  Angehängt als `cut_reason`, bewusst **nicht** als `reason`: `pause_trim_edl` verzweigt
  darauf (`:256`, `:363`) und echte Gründe dort würden den Schnitt ändern. Längen-Guard:
  passt der Sidecar nicht zur EDL, wird die Benennung abgeschaltet statt falsch zugeordnet.
  Details in `Dateiformate.md`. Funktionierender Vorzustand als Tag `aaf-struktur-funktioniert`.
  - [ ] **Offen: Import-Gegenprobe.** Struktur ist per Test belegt, das Rendering in
    Resolve/Premiere noch nicht. Beim nächsten echten Import prüfen.
- [ ] ~~**Timeline-Clips im AAF nach Schnittgrund benennen**~~ (Pendant zu den Resolve-
  Farbcodes aus der Web-Version — nachvollziehbares Kategorisieren der Schnitte).
  Aufwand: **leicht–mittel**.
  **BELEGT (Test, 20.07.):** Clipnamen sind **frei wählbar** und komplett vom
  Quelldateinamen entkoppelt. Was die NLE im Timeline-Segment anzeigt, ist der Name des
  **MasterMob**, den der SourceClip referenziert. Test: drei MasterMobs
  (`CAM1__Sprecher`, `CAM1__Kopfnicken`, `CAM1__Totale-Reset`) auf **einen** FileMob →
  Timeline zeigt pro Segment den jeweiligen Namen. Zurückgelesen und bestätigt.
  **Warum es heute so aussieht:** `build_aaf.py:309` setzt `master.name = Path(cp).stem`
  — EIN MasterMob je Kamera, benannt mit dem Dateinamen **ohne Endung**. Daher „nicht
  direkt der Dateiname", und Umbenennen in Resolve ändert nichts (Name ist eingebacken).
  **Die Daten existieren schon:** `add_reactions_to_edl.py` führt je Event ein `reason`
  (`speaker`, `reaction_<typ>`, `reaction_<typ>_wide`, `max_time`).
  ⚠️ **Fehlendes Glied:** `write_edl()` (Z. 799) schreibt nur die Edit-Zeile +
  `* FROM CLIP NAME:` — der Grund geht verloren; `build_aaf._parse_edl` liest ihn folglich
  nicht. Zu tun: `reason` mitgeben (zusätzliche `*`-Kommentarzeile **nach** `FROM CLIP
  NAME`, damit bestehende Parser nicht brechen — `run_from_bin.parse_edl` erwartet sie in
  `lines[i+1]` — oder als Sidecar-JSON) und in `build_aaf` je (Kamera × Grund) einen
  MasterMob anlegen.
  ⚠️ **Trade-off:** Jeder MasterMob = ein eigener Clip im Resolve-Bin. Ein MasterMob pro
  **Segment** würde den Bin mit hunderten Einträgen fluten → deshalb einen pro
  **Kamera × Kategorie** (realistisch 3–5 je Kamera).
  ⚠️ **Noch offen:** Der Test belegt die AAF-**Struktur**, nicht das Rendering in Resolve.
  Vor Umsetzung einmal echt importieren und prüfen, ob Resolve die MasterMob-Namen wie
  erwartet im Timeline-Segment anzeigt.

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
  Person und zeigt „Geteilte Totalen" + „Ohne Person". `sharedWideCams` (18.07.
  ENTFERNT, s.u.) = Totale
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
  dürfen NICHT die Totale sein (`combine_audios` nimmt das **Maximum** über
  alle Mics der Cam → die Totale waere fast immer die lauteste Seite und die
  Diarisierung kippt. Nicht "summiert", wie hier lange stand.)
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
- [x] **Log-Retention**: UMGESETZT — beim Anlegen des Lauf-Logs (`multicam_engine.py`,
  Logging-Setup) werden nur die neuesten **20** `*.jsonl` in
  `~/Library/Logs/MulticamCutter/` behalten, ältere gelöscht. Best-effort (bricht den
  Lauf nie). Nicht-Log-Dateien unangetastet. ⚠️ PyInstaller-Rebuild fürs Release.
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
  - [x] EdDSA-Keypair via `generate_keys` — Public Key `kcPVT…` steckt in
    `SUPublicEDKey` (verifiziert: stimmt mit dem Keychain-Key überein). **Private Key
    ist gesichert** (per `generate_keys -x` exportiert, im Passwort-Manager abgelegt,
    Export-Datei gelöscht). Damit ist das Risiko „Verlust = nie wieder Auto-Updates"
    entschärft.
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
