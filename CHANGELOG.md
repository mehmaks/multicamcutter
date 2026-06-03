# Changelog

## v0.7.0  (2026-06-03)

### Neu
- **Sync-Timeline-Modus im Bin-Workflow** — Toggle „Sync aus aktiver Resolve-Timeline" im Optionen-Expander. Statt Waveform-Cross-Correlation werden die Clip-Positionen einer manuell in Resolve aufgebauten Sync-Timeline als Offsets übernommen. Praktischer Rettungsanker bei niedriger Waveform-Confidence, die zuvor zu vollständig asynchronen Cuts geführt hat.
- **Multi-MIC pro Kamera im Bin-Workflow** — UI übernimmt das Folder-Workflow-Pattern: pro Mic eine Selectbox „Zuordnung zu Cam X", mehrere Mics dürfen dieselbe Cam wählen. Use-Case: 2 Gäste auf einer Kamera mit je eigenem Lavalier. CLI wechselt von Single-Index auf `--cam-mics`-Listen.
- **`max_faces` pro Cam automatisch aus MIC-Zuordnung abgeleitet** — Cams mit mehreren zugewiesenen Mics bekommen entsprechend mehr gleichzeitige Gesichts-Tracks bei MediaPipe. Endlich Nodding/Reaction-Erkennung für jeden Gast einzeln, auch wenn mehrere im selben Bild sitzen.
- **FPS-Konsistenz-Check + Inline-Konvertierung** — Beim Bin-Scan prüft die UI, ob alle Kameras die Timeline-FPS haben. Bei Mismatch: roter Banner mit Liste der betroffenen Files, gesperrter Start-Button, und ein „Konvertieren"-Button startet ffmpeg im Background-Thread mit Live-Log. Ziel-Codec H.264 4:2:2 10-bit (praktisch verlustfrei), embedded Timecode wird erhalten. Verhindert die Klasse von Bugs, die sich aus FPS-Mismatch + Resolve-Auto-Speed-Adaption ergibt.
- **CLI-Flag `--skip-clip-filter`** — Überspringt den CLIP-Bilderkennungs-Pass (Cutaway-Filter für „trinkt aus Glas" o.ä.) für diesen Lauf. Spart ~30 min bei Test-Läufen, ohne das persistente Schema-Setting zu ändern. UI-Toggle im Optionen-Expander.

### Fixes
- **Cam-Cutaways auf einer Cam systematisch um den Sync-Offset verschoben (~250 Frames)** — `calculate_reference_frames()` vertauschte im Fallback (Cam-Datei ohne embedded TC) `reference_frame` und `timeline_zero_video`. Effekt: Cutaways auf der betroffenen Cam landeten konstant um den Sync-Offset versetzt — das Nick-Pattern lag dann außerhalb des Cutaway-Fensters. In der Praxis sichtbar als „Cutaway auf Host, aber Host bewegt sich nicht". Tritt nur auf, wenn eine Cam keinen embedded TC hat (z.B. nach fps-Konvertierung).
- **ffprobe-TC-Read mit Diagnose & Resolve-Fallback** — `get_embedded_timecode()` schluckte Fehler stillschweigend und lieferte `None`. Jetzt explizite Fehlermeldungen auf stderr (FileNotFoundError, returncode, JSON-Parse). Zusätzlich Resolve-Fallback über `item.GetClipProperty('Start TC')` falls ffprobe transient ausfällt.

### Sonstiges
- **PASS 4 Split-Logik überarbeitet** — Statt eines einzelnen Mittelschnitts werden jetzt N Cutaways gleichmäßig verteilt, sodass jedes Speaker-Stück unter dem Threshold bleibt. Bei threshold=17s, cutaway=1.7s: 30s-Event → 1 Cutaway, 90s-Event → 4 Cutaways (vorher 1), 180s-Event → 9. Off-Cam-Check pro einzelnem Cutaway-Slot.
- Lokale `CLAUDE.md`-Brain-Files via `.gitignore` ausgeschlossen.

---

## v0.6.5  (2026-05-18)

### Fixes
- **UnicodeEncodeError beim Schreiben von `cameras.json`** — Multicam-Läufe brachen nach erfolgreicher Reaction-Analyse ab, wenn Pfade Umlaute enthielten (z.B. "Stützer"). `Path.write_text()` fiel ohne explizites `encoding=` auf System-Locale zurück. Alle `write_text(json.dumps(...))`-Aufrufe im Multicam-Produktivpfad und in den UI-Preset-Speicherungen verwenden jetzt explizit `encoding='utf-8'`.

---

## v0.6.4  (2026-05-08)

### Neu
- **Auphonic — Timeline-Modus** — Audio direkt zwischen In/Out-Markern aus einer Resolve-Audiospur extrahieren, an Auphonic schicken und das Ergebnis automatisch in den Quell-Bin importieren. Optional: Originalspur ersetzen statt neue Spur anzulegen.
- **Auphonic — Live-Fortschritt** — Modaler Dialog zeigt während der Cloud-Verarbeitung Status und Ergebnis-Track-Index. Auphonic-Parameter sind in einen Expander gewandert.

### Fixes
- **MediaPipe `analysis_width`** — Wert aus `nodding_patterns.json` wurde nicht gelesen, sodass MediaPipe Videos in Originalauflösung (4K) statt 1280px analysierte. Detail u.a. sichtbar an winzigen Landmarks im Live-Preview.
- **Auphonic-Dialog blockierte UI** — Sidebar-Queue-Consumer in `app.py` las parallel aus derselben Queue wie der Dialog, filterte Steuer-Messages nicht und blockierte das Page-Rendering. Dialog läuft jetzt in `@st.fragment(run_every=2s)`.
- **`DeleteClips` Replace-Track** — Erwartete eine Liste statt einzelner Items.

### Sonstiges
- `auto_accuracy`-Flag (CLI + Code-Pfade) als OBSOLET markiert — Face-Size-Adaption ist ohnehin immer aktiv.
- Social-Cutter-Modul-Skelett (BETA_BLOCKED, im Repo).
- `.gitignore`: `venv_py39_backup/`, `face_landmarker.task`, `memory/`.

---

## v0.6.3  (2026-04-29)

### Fixes
- **Voice Leveler — Expertenmodus** — Modul-eigener "Expertenmodus"-Button entfernt; Anzeige ist jetzt an den globalen Sidebar-Toggle gekoppelt.

---

## v0.6.2  (2026-04-29)

### Fixes
- **Beta-blocked Module in Sidebar** — Im Dev-Modus wieder sichtbar (mit 🔴-Indikator).
- **Doppelter Expertenmodus-Toggle** — Im Social Cutter wurde der Expert-Toggle doppelt angezeigt; modul-interner Toggle entfernt.

---

## v0.6.1  (2026-04-28)

### Fixes
- **Update-Check** — Zeigte fälschlich ältere Versionen als Update an (z.B. v0.5.0 obwohl v0.6.0 installiert). Prüft jetzt nur noch den neuesten Tag der Hauptversion.
- **licensing/ im Repo** — Das Lizenz-Modul fehlte nach `git pull` auf Client-Rechnern (war komplett in .gitignore).

---

## v0.6.0 — Architektur-Refactoring & neue Features  (2026-04-28)

### Architektur
- **config.ini → JSON-Params** — Modul-Parameter werden nicht mehr über config.ini übergeben, sondern als temporäre JSON-Dateien via `--params`. config.ini hält nur noch UI-State (Feedback, UI, Auphonic, Debug).
- **Projekt-Restrukturierung** — Backend-Extraktion, Pfad-Zentralisierung, Cleanup. Config- und Doc-Dateien aus Untermodulen in zentrale Ordner verschoben.

### Neu
- **Expert-Mode** — Einfach/Experten-Aufteilung der UI-Parameter. Im Einfachmodus werden nur die wichtigsten Einstellungen angezeigt, per Toggle umschaltbar.
- **Schema-basierter UI-Renderer** — Parameter-Widgets werden aus `multicam_params.json` generiert statt hardcoded.
- **Crossbleed-Filter** — Intelligentes Noise Gate unterdrückt Übersprechen zwischen Mikrofonen vor der Sprechererkennung. Konfigurierbar mit Dämpfung, Hysterese, Attack/Release.
- **Pause-Cutaways** — Schneidet während Sprechpausen automatisch auf die zuhörende Person.
- **CLIP Ignore-Filter** — Prüft per Bilderkennung (OpenAI CLIP), ob ein Cutaway eine unerwünschte Szene zeigt, und verschiebt ihn automatisch.
- **Pausen-Trimming** — Kürzt überlange Sprechpausen an Wechselpunkten automatisch. Unterstützt Middle, L-Cut, J-Cut und Zufalls-Modus.
- **RMS-Gate & Diarization-Stille-Gate** — Zusätzliche Audio-Gates für sauberere Sprechererkennung.
- **Beta-Disclaimer** — Einmaliger Hinweis beim Session-Start mit "nicht mehr anzeigen"-Option.
- **Lizenz-Versionsbindung** — Lizenzen sind an die Hauptversion gebunden (v0, v1, ...). Update-Benachrichtigungen nur innerhalb der lizenzierten Version.
- **Nodding-Detection: Tilt+Yaw-Korrektur** — Kompensiert Kopfneigung und -drehung für genauere Nickerkennung.
- **Slow Oscillation Pattern** — Neues Nodding-Pattern für langsames, bedächtiges Nicken.
- **Sequencer** — Modulares Pipeline-System mit 22 Modulen (experimentell, noch nicht für Beta freigegeben).

### Fixes
- **max_time Cutaways** — Werden jetzt in der Segmentmitte platziert statt am Rand.
- **Diarization-Cleanup-Schutz** — Verhindert, dass der Cleanup-Pass Diarization-Segmente entfernt.
- **Pause-Trim-Sync** — Audio und Video trimmen exakt synchron.

### Docs
- Dokumentation an aktuelle Standardwerte angepasst (min_shot 3.0, max_shot 14.0, cleanup_dur 1.8, reaction_dur 1.8).
- Neue Dokumentation für Pausen-Trimming, Crossbleed-Filter, Stille-Cutaways und CLIP-Filter.
- Whisper-Modellgröße in Silence Cutter Docs korrigiert (75 MB → 39 MB).

---

## v0.5.0 — Pattern-basierte Nodding-Detection  (2026-04-23)

### Neu
- **Oszillations-lokale Amplitudenmessung** — Amplitude, Dämpfung und Halbschwingungen werden nur über den Pattern-relevanten Bereich berechnet, nicht über das gesamte 2s-Fenster. Verhindert False Positives durch große Kopfbewegungen vor dem eigentlichen Nicken.
- **Pattern-Offset** — Cutaways beginnen am Anfang der sichtbaren Nickbewegung statt am Detection-Frame. Berechnet aus dem ersten Reversal des erkannten Musters.
- **Dynamische Cutaway-Dauer** — Die Cutaway-Länge passt sich an die tatsächliche Pattern-Länge an. Kurze Nicker bekommen die Mindestdauer, längere Bewegungen werden vollständig gezeigt.
- **Tail-Berechnung** — Ausklingzeit nach dem letzten Richtungswechsel wird datengestützt aus dem Median-Abstand der Reversals geschätzt (typical_gap). Cutaways enden nicht mehr mitten im Ausschwingen.
- **Strong Oscillation Pattern** — Neues Pattern für kräftiges Nicken (min. 3 Richtungswechsel, hohe Amplitude).
- **Timeline-Manifest** — `timeline_manifest.json` wird nach Timeline-Erstellung geschrieben (idx, Record-TC, Clip, Reason, Color pro Event).
- **Farb-Diagnostik** — Count-Mismatch-Warning und Color-Statistik nach dem Einfärben.
- **Changelog-Tab** — Release Notes sind jetzt in der App unter Roadmap & Changelog einsehbar.

### Entfernt
- **Single-Nod Pattern** — Zu viele False Positives (Lachen, Nasekratzen, Runtergucken). Nur noch Oscillation und Strong Oscillation aktiv.
- **Alte UI-Parameter** — Nod-Threshold, Min. Nod-Dauer und Auto Accuracy sind nicht mehr im UI exposed (werden über die Pattern-JSON konfiguriert).

### Docs
- Cutaway-Regeln-Dokumentation komplett überarbeitet: beschreibt jetzt die pattern-basierte Erkennung, Confidence-Gewichtung und dynamische Cutaway-Dauer.

### Testergebnis
Oscillation + Strong Oscillation über 15.000 Frames (Ronny Pietsch): **Nur True Positives, keine False Positives.**

---

## v0.4.9  (2026-04-20)

## Config-Migration & UI-Polish

### Neu
- **Automatische Config-Migration** — Beim App-Start werden fehlende Sections/Keys aus dem Template ergänzt und obsolete Keys entfernt. Bestehende Werte werden nie überschrieben.
- **Schnittmodus "Zufall"** — Wählt bei jedem Pause-Schnitt zufällig zwischen Middle, L-Cut und J-Cut.

### Fixes
- **Config-Template vervollständigt** — `[PauseTrim]`, `[TotaleLogic]`, `[Debug]`, `[Nodding] threshold` fehlten im Template.
- **Obsolete Nodding-Keys** — `threshold_low`, `threshold_medium`, `threshold_high` werden automatisch entfernt (nur `threshold` wird verwendet).
- **Analyse-Dialog** — Taucht nicht mehr erneut auf nach Schließen per X-Button.
- **Unicode in Presets** — Umlaute in Preset-JSON-Dateien führen nicht mehr zum Crash.
- **Default-Preset** — Obsolete Speaking-Detection-Parameter entfernt, aktuelle Werte übernommen.

### UI
- Schnittmodus-Labels mit Großbuchstaben (Middle, L-Cut, J-Cut) für bessere Lesbarkeit.
- Built-in-Preset-Caption entfernt.

---

## v0.4.8  (2026-04-20)

## PauseTrim Production-Release

### Neu
- **PauseTrim in Production-Pipeline** — Sandbox-Logik 1:1 übernommen: Events an Sprecherwechsel-Grenzen bedingungslos auf Pausenmitte verschieben. Exakter Audio/Video-Sync (Diff=0).
- **Schnittmodus "Zufall"** — Wählt bei jedem Pause-Schnitt zufällig zwischen Middle, L-Cut und J-Cut.

### Fixes
- **Audio-Sync** — Video und Audio trimmen jetzt exakt gleich viele Frames (vorher bis zu 218 Frames Drift).
- **Videoschnitt-Position** — Schnitt liegt jetzt immer in der Pausenmitte (Middle-Mode), nicht mehr asymmetrisch verschoben.
- **Analyse-Dialog** — Taucht nicht mehr erneut auf, wenn per X-Button geschlossen.
- **Unicode in Presets** — `read_text(encoding='utf-8')` verhindert Crash bei Umlauten.
- **Marker-Offset** — Timeline-Startframe wird korrekt abgezogen.

### Aktualisiert
- Default-Preset: Obsolete Speaking-Detection-Parameter entfernt, aktuelle Werte + PauseTrim-Felder eingefügt.
- Schnittmodus-Labels in Großbuchstaben (Middle, L-Cut, J-Cut) für bessere Lesbarkeit.
- Pitch-Dokument und Roadmap überarbeitet.

---

## v0.4.7  (2026-04-19)

## v0.4.7

- **Voice Leveler Doku:** Einfachmodus und Expertenmodus als getrennte Expander
- Einfachmodus erklärt Leveler Target, Output Ceiling und Aufnahmesituation

---

## v0.4.6  (2026-04-19)

## v0.4.6

- **Dokumentation überarbeitet:** Alle Module haben jetzt Einleitungstexte und Workflow-Diagramme
- Doc-Grafiken aktualisiert
- Multicam Anleitung: Mikrofonspur-Beschreibung korrigiert

---

## v0.4.5  (2026-04-18)

## v0.4.5

- **Fix:** `start.command` beendet jetzt automatisch alte Prozesse vor dem Neustart — verhindert veralteten Code nach Updates

---

## v0.4.4  (2026-04-18)

## v0.4.4

- Fix: BETA_BLOCKED vollständig in allen Dateien enthalten (behebt AttributeError aus v0.4.3)
- Auphonic aus der Beta ausgeblendet
- Resolve Bridge aus Modul-Liste entfernt

---

## v0.4.3  (2026-04-18)

## v0.4.3

- **BETA_BLOCKED**: Module lassen sich jetzt app-seitig aus dem Betatest ausschließen, ohne Lizenzen neu signieren zu müssen
- Auphonic vorerst aus der Beta ausgeblendet
- Resolve Bridge aus Modul-Liste entfernt (license, UI)

---

## v0.3.1  (2026-04-17)

## Neu

- **Persistentes Error-Log** — Fehler werden in `~/.resolve-toolkit/app.log` gespeichert und können beim Bug-Report automatisch mitgeschickt werden
- **Feedback-Dialog** — Bugs & Feedback öffnet sich jetzt als großer zentrierter Dialog statt als Popover
- **Silence Cutter: Ergebnis-Dialog** — nach der Analyse erscheint ein Dialog mit Anzahl der gefundenen Pausen und direktem "Stille löschen"-Button (startet den Cut-Workflow)
- **Take Selector** — Bin- und Clip-Listen sind jetzt alphabetisch sortiert
- **Audio Enhance** — Datei-/Ordner-Browser statt Drag & Drop; Video-Dateien werden ebenfalls unterstützt

## Fixes & Verbesserungen

- Voice Leveler: "Aktive Timeline" Modus entfernt — der Modus hat alle Spuren in einen Mix gerendert, was für Sprachverarbeitung nicht sinnvoll ist
- Silence Cutter: Quelle heißt jetzt "Aktive Timeline" statt "Resolve Timeline"
- Silence Cutter: Slider-Werte bleiben beim Seitenwechsel erhalten
- Silence Cutter: Unnötige Hinweiskästen zu Kamera-Audiodaten entfernt
- Silence Cutter: Bestätigungs-Checkbox vor dem Cut-Button entfernt
- Audio Enhance: "MaxxVolume" → "Voice Leveler" umbenannt
- Config-Page: Nur lizenzierte Module werden in der Sortier-Liste angezeigt
- Resolve Bridge Seite entfernt

## Update

```bash
bash ~/resolve-toolkit/start.command
```

---

## v0.3.0 — v0.3.0 — UI Overhaul  (2026-04-16)

## Was ist neu

### Design & Theme
- Neues Anthropic-inspiriertes Light Theme (SpaceGrotesk + SpaceMono Fonts)
- Alle Emojis durch Material Icons ersetzt (Sidebar, Buttons, Seitentitel)
- Versionsnummer als Badge in der Sidebar

### Config
- Drag & Drop Reihenfolge der Module in der Config-Page (streamlit-sortables)
- Modul-Aktivierung per Drag in 'Aktiviert' / 'Deaktiviert' Container

### Voice Leveler (ehem. MaxxVolume)
- Umbenennung zu Voice Leveler
- Einzeldatei- und Ordner-Modus als separate Quellen
- Resolve-Quellen werden ausgeblendet wenn Resolve nicht verbunden ist

### Silence Cutter
- Datei-Pfad-Modus mit AAF-Export

### Take Selector
- Bugfix: Compare-Dialog öffnet sich nicht mehr ungewollt beim Take-Auswählen
- Bugfix: X-Button schließt Dialog korrekt

### Dokumentation
- Neue Docs: Silence Cutter, Voice Leveler
- Screenshots eingebunden (Take Selector, Silence Cutter, Voice Leveler)
- Alle Überschriften um eine Ebene erhöht

### Sonstiges
- openai-whisper in requirements.txt
- ffmpeg-Check und Auto-Install in setup.sh
- Config-Migration beim Start (fehlende Keys werden ergänzt)

---

## v0.2.1  (2026-04-16)

## Bugfixes
- Fix: License-Page importierte sich selbst statt Root-`license.py` — Lizenz-Installer per Dateidialog funktioniert jetzt korrekt
- `openai-whisper` zu `requirements.txt` hinzugefügt (Take Selector)

---

## v0.2.0  (2026-04-16)

## Take Selector
- AAF-Export komplett neu gebaut (DaVinci-Style Mob-Struktur: CDCIDescriptor + PCMDescriptor + TapeDescriptor) — Premiere Auto-Linking funktioniert, korrekte Dateinamen, Audio und Timecode
- Zwei Export-Modi: **Best Takes** (V1) und **Alle Takes** mit Best Takes auf V2
- Resolve-Export ebenfalls mit V1/V2-Modus (trackIndex + recordFrame)
- Fix: bei Datei-Pfad-Quelle wurde fälschlich Resolve-Export angeboten wenn Resolve offen war

## Lizenz
- Lizenzdatei per Dateidialog auswählen und automatisch installieren
- Validierung vor dem Kopieren — ungültige/abgelaufene Dateien werden nie geschrieben

## App / UI
- Sidebar-Navigation mit **TOOLS** / **SETTINGS** Sections
- Config-Migration beim Start: neue Template-Keys werden automatisch in bestehende config.ini übernommen
- Bugreport: Log-Checkbox entfernt (Log war unvollständig und nicht persistent)

---

## v0.1.6  (2026-04-16)

## Neu in v0.1.6

### Dokumentation
- Neue Docs-Page mit vollständiger Parametererklärung für den Multicam Cutter
- Screenshots und Blockquote-Standardwerte für alle Einstellungen

### Multicam Cutter UI
- Expander umbenannt und neu strukturiert
- Nodding-Erkennung und Sprachreaktionen zu „Cutaway Regeln" zusammengeführt
- Auto Accuracy standardmäßig aktiviert
- Preset-Panel restrukturiert: Dropdown oben, Speichern/Löschen im eigenen Expander

### Allgemein
- Update-Check als modaler Dialog
- Feedback-Button umbenannt zu „Bugs & Feedback", E-Mail-Feld ergänzt

### Start-Verhalten
- `start.command` startet Streamlit jetzt im Hintergrund — Terminal kann nach dem Start geschlossen werden
- Bei erneutem Doppelklick wird nur der Browser geöffnet, kein zweiter Prozess gestartet

---

## v0.1.5 — v0.1.5 — Auto Accuracy, Timeline-Fix, UI-Overhaul  (2026-04-15)

## Änderungen

### Fix: Timeline-Startpunkt
- Der Workflow nutzt jetzt immer die frühest startende Kamera als Timeline-Ursprung
- Verhindert abgeschnittene Anfangsmoderation wenn eine Kamera später eingeschaltet wird als die andere

### Nodding-Analyse
- **Auto Accuracy**: Nodding-Threshold skaliert automatisch auf die erkannte Gesichtsgröße — nützlich bei Totalen mit mehreren Personen im Bild
- Nod-Threshold vereinfacht: ein Wert statt drei Sensitivitätsstufen (low/medium/high)
- **Debug-Limit**: `limit_frames` + `max_analysis_frames` in `[Debug]`-Config-Sektion für schnelle Testruns

### UI
- Alle Checkboxen als Toggle-Schalter
- Auto Accuracy im Nodding-Erkennung-Expander
- Speaking Peak-Detection in Speaking-Reactions-Expander
- Nod-Threshold direkt editierbar (px) im UI
- Min. Konfidenz als Prozentwert (0–100)
- LUT-Datei-Selector mit nativem macOS-Picker + Thumbnail-Refresh bei LUT-Wechsel
- FPS wird automatisch aus den Videodateien ausgelesen (ffprobe)
- MediaPipe Preview-Frequenz auf 5 Sekunden reduziert

---

## v0.1.4 — v0.1.4 — Kompakte Sidebar-Leiste  (2026-04-14)

## Was ist neu

- **Kompakte Bottom-Bar in der Sidebar**: Feedback-Button, Update-Button und Lizenz-Status sind jetzt immer sichtbar — kein Scrollen mehr nötig
- **Feedback als Popover**: Der 💬 Feedback-Button öffnet ein Overlay direkt in der Sidebar, ohne die Seite zu verlassen
- **Update-Button direkt daneben**: ↻ Updates und ⬆ Tag-Update-Button im gleichen Bereich wie Feedback
- **Lizenz-Dot**: 🟢 / 🟡 / 🔴 zeigt den Lizenzstatus auf einen Blick, mit Tooltip-Details
- **Version + Lizenz-Label**: Eine einzige Zeile am unteren Rand zeigt Version und Lizenz-Modus

## Verbesserungen

- Separate „Lizenz"- und „Update"-Sektionen in der Sidebar entfernt — weniger Scrollen
- Feedback-Form nur sichtbar, wenn GitHub-Token und Repo in config.ini konfiguriert sind

---

## v0.1.3 — v0.1.3 — Test-Release  (2026-04-14)

## Test-Release

Kein inhaltlicher Stand — dient ausschließlich zum Testen der Update-Check-Funktion.

---

## v0.1.2 — v0.1.2 — Update-Check Fix  (2026-04-14)

## Bugfix: Update-Check

### Fix
- Update-Check funktioniert jetzt zuverlässig: Versionsprüfung läuft jetzt über `git fetch --tags` statt über die GitHub Releases API. Die API-Variante schlug auf privaten Repos still fehl, sodass der Button keine Reaktion zeigte. Release Notes werden weiterhin optional über die API geladen.

---

## v0.1.1 — v0.1.1 — Bugfixes & Installation  (2026-04-14)

## Bugfixes & Installationsverbesserungen

### Fixes
- Update-Check: NameError beim Start behoben (`configparser` wird jetzt lokal in der Update-Funktion importiert)
- Streamlit Deploy-Button ausgeblendet

### Installation
- `requirements.txt` auf direkte Abhängigkeiten mit losen Versions-Pins umgestellt — behebt Konflikte bei frischer Python-3.12-Installation
- DeepFilterNet und deepspeed aus Requirements entfernt (werden im Multicam Cutter nicht verwendet, erfordern Rust-Toolchain)
- mediapipe auf 0.10.33 aktualisiert (0.10.5 hat keine Python-3.12-Wheels)
- `setup.sh` bevorzugt jetzt explizit Python 3.12
- `install.md`: Terminal-basierte Installation via Homebrew, Python 3.12 explizit angegeben

---

## v0.1.0 — v0.1.0 — Beta  (2026-04-14)

## Multicam Cutter — erster Beta-Release

Automatischer Ersteditschnitt für Podcast- und Interviewproduktionen.

### Was enthalten ist

**Kern-Workflow**
- Automatische Synchronisation aller Kamera- und Mikrofonspuren per Waveform-Korrelation (keine Klappe nötig)
- RMS-basierte Sprechererkennung mit Rolling-Baseline-Algorithmus
- Reaktions-Cutaways via MediaPipe Face Landmarker: Nicken, Lachen, Kopfschütteln
- Unterstützung für N Kameras und M Mikrofone in beliebiger Zuordnung
- Kamera-Rollen: Close-Up und Wide-Shot mit konfigurierbarer Schnittlogik
- Digitaler Zoom auf Wide-Shot-Clips direkt im AAF (kein Pre-Render)

**AAF-Export**
- Kompatibel mit DaVinci Resolve und Adobe Premiere Pro (getestet)
- Video-Timeline mit Sprecherwechseln und Reaktions-Cutaways
- Separate Lavalier-Audiospur pro Mikrofon, synchron zur Video-Timeline

**Zwei Workflow-Modi**
- Bin-Workflow: Clips direkt aus einem offenen DaVinci Resolve Projekt
- Folder-Workflow: Clips aus einem Ordner, unabhängig von Resolve

**UI**
- Streamlit-basierte Oberfläche mit Live-Fortschrittsanzeige
- In-App Feedback und Bug-Meldung via GitHub Issues
- Modulbasiertes Lizenzsystem (Multicam Cutter separat lizenzierbar)
- Automatischer Update-Check via GitHub Releases

### Systemvoraussetzungen
- macOS 13 oder neuer (Apple Silicon empfohlen)
- Python 3.12
- DaVinci Resolve (für Bin-Workflow) oder eigenständig (Folder-Workflow)

### Installation
Siehe [install.md](install.md) im Repository.

---

