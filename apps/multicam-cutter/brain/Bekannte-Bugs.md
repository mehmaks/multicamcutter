# Bekannte Bugs & Fixes

## OFFEN

### Split-Teil 2 linkt nicht in Resolve („timecode extents do not match") — GEFIXT (26.10., in Resolve bestätigt)
- **Symptom**: AAF von Folge 59 (Zoom H6essential, 29,97 DF): Teil 1 linkt, Teil 2
  jeder gesplitteten Spur bleibt rot (Offline).
- **Ursache (per Test-AAFs in Resolve eingegrenzt)**: Reel-TC aus BWF-`time_reference`
  wurde mit gerundetem `fps` 29,97 statt 30000/1001 und mit `round` gerechnet. Resolve
  gibt der Datei aber den ersten VOLLEN Frame (aufgerundet) als Start und nur volle
  Frames als Länge. Teil 2 wird ab Frame 0 bis zum Ende genutzt → Bereich ragte vorn
  bzw. (aufgerundete Teil-Länge) hinten 1 Frame über die Datei → kein Link. Teil 1 und
  Einzeldateien linkten trotzdem, lagen bei NTSC-Raten aber 1 Frame versetzt.
- **Fix**: `_bwf_start_frame` (exakt + aufgerundet), Teil-Länge = volle Frames bis
  Dateiende, Rest Filler. Details: `AAF-Struktur.md` → Gesplittete Aufnahmen.

### PyInstaller-Excludes brachen Nodding (+ CLIP) im Frozen-Build — GEFIXT (25.07.), Rebuild+Patch nötig
- **Symptom**: Auf dem **Release**-Build (Kollege) bricht die Analyse bei „Schritt 5/9:
  Nodding-Analyse" ab: `ERROR: No module named 'matplotlib'`. Im **Dev** (`swift run`,
  venv) tritt es NIE auf.
- **Ursache**: `multicam_engine.spec` schloss `matplotlib`/`pandas`/`pyarrow`/`sklearn`
  aus, begründet mit „per grep 0 direkte Imports im Engine-Pfad". Der grep sah aber nur
  DIREKTE Imports — diese Pakete kommen **transitiv**: **mediapipe → matplotlib** (der
  Nodding-Analyzer importiert `mediapipe.tasks`), **transformers → pandas/pyarrow/sklearn**
  (CLIP-Filter). **Nodding ist per Default AN** → 0.6.5–0.6.7 hatten im Release **kaputtes
  Nodding**; der Dev-Build kaschierte es (venv hat alles).
- **Fix**: die vier aus den Excludes entfernt (`llvmlite` 110 MB, `numba`, `plotly`
  bleiben — per `sys.modules`-Trace als ungenutzt bestätigt). Engine wächst ~159 MB.
  Braucht **Frozen-Rebuild + Patch-Release**.
- **Lehre**: Bundle-Excludes NIE per direktem grep verifizieren — immer per
  `sys.modules`-Trace über die echte Import-Oberfläche (cv2 + mediapipe + torch +
  transformers + scipy + soundfile + aaf2). Und Frozen-Only-Features (Nodding/CLIP)
  IM Frozen-Build testen, nicht im Dev.

### Sparkle-Update-Ablauf komplett Englisch — GEFIXT im Build-Script (26.07.), Verifikation braucht Release-Build
- **Symptom** (User, 26.07.): Der gesamte Update-Ablauf (Sparkles „Update verfügbar"-
  Dialog, Release-Notes-Rahmen, Download-Fortschritt, „Installieren & Neustarten") wird
  **englisch** angezeigt — obwohl die App sonst durchgehend deutsch ist. Unsere EIGENEN
  Update-Strings (About-Dialog, Einstellungen→Updates in `Updater.swift`) sind deutsch;
  nur Sparkles mitgelieferte Dialoge waren englisch.
- **Ursache**: Die App-`Info.plist` (aus `build_app.sh`) hatte **weder
  `CFBundleDevelopmentRegion` noch `CFBundleLocalizations`** und **keine app-eigene
  `.lproj`**. Damit gilt die App für macOS als „Englisch-only". macOS beschränkt die
  Sprache **geladener Frameworks auf die von der App unterstützten Sprachen** → Sparkle
  wird auf Englisch gezwungen, OBWOHL `Sparkle.framework` eine fertige `de.lproj`
  mitbringt. Es fehlten also keine Übersetzungen — die App hat Deutsch nie deklariert.
- **Fix** (`build_app.sh`): `CFBundleDevelopmentRegion=de` + `CFBundleLocalizations=[de]`
  in die Info.plist, plus eine physische `Contents/Resources/de.lproj/InfoPlist.strings`
  (zuverlässigstes Signal für `NSBundle.localizations`). Damit meldet die App Deutsch als
  verfügbare Sprache → Sparkle zieht automatisch seine de.lproj.
- **⚠️ Verifikation steht aus**: greift **nur im gebündelten `.app`** (Dev via `swift run`
  hat keine Info.plist/kein Sparkle-Feed). Prüfen im nächsten Release: Update-Dialog auf
  Deutsch? `plutil -p .../Contents/Info.plist | grep -i region` zeigt `de`, und
  `Contents/Resources/de.lproj/` existiert im signierten Bundle.
- **Lehre**: „Framework zeigt Englisch trotz vorhandener Lokalisierung" ist fast nie ein
  Übersetzungs-, sondern ein **Deklarations**problem der Host-App (Development Region /
  Localizations). Beim EN-Ausbau (Punkt 8) hier `en` ergänzen.

### Appcast: ältere Changelog-Einträge verloren ihr Deutsch — GEFIXT (26.07.), greift ab 0.6.9
- **Symptom** (User, 26.07.): Auf der Website steht nur der NEUESTE Changelog auf Deutsch;
  alle älteren Einträge erscheinen nur noch auf Englisch.
- **Ursache**: `release.sh` ruft `generate_appcast` (regeneriert den Appcast bei jedem
  Release) und danach `embed_release_notes.py <version>` — Letzteres bettete
  `<description xml:lang="de/en">` aber NUR ins Item der AKTUELLEN Version. Sparkle kennt
  kein `xml:lang` und behält beim Regenerieren höchstens EINE `<description>` je älterem
  Item → die zweisprachigen Beschreibungen der Vorgänger wurden bei jedem Release
  verstümmelt (DE fiel raus, EN blieb). Belegt am lokalen Appcast: 0.6.9 de+en, 0.6.8 nur
  en, 0.6.7/6.6/6.5 ganz leer.
- **Fix** (`embed_release_notes.py`): bettet jetzt ALLE Items ein (Version je Item aus der
  DMG-URL im Enclosure), nicht nur die aktuelle. Pro Item: bestehende (verstümmelte)
  `<description>` entfernen, DE(+EN) aus dem Changelog neu setzen. Der Release-Guard bleibt:
  die aktuelle Version braucht einen DE-Abschnitt, sonst Exit 2 → `release.sh` bricht ab.
  Verifiziert gegen eine Appcast-Kopie: alle 5 Items → de+en.
- **Greift ab dem nächsten Release** (0.6.9): der dann regenerierte Feed ist vollständig
  zweisprachig. Ältere Versionen ohne Changelog-Abschnitt würden übersprungen (hier n/a).

### Bekannter Ordner + neue Datei → Kamera↔Mic-Zuordnung verknüpft falsch — GEFIXT (25.07.)
- **Symptom**: Ordner mit gespeicherter `.multicam` erneut geöffnet, nachdem eine
  NEUE WAV hineinkopiert wurde. Die App stellt die alte Zuordnung wieder her, aber
  eine Kamera hängt am FALSCHEN Mic (neue „MIC2.WAV" statt „markt11.WAV"), und die
  eigentlich zugeordnete Datei steht auf „keine Kamera".
- **Ursache**: `loadSession()` restaurierte die Kamera↔Mic-Zuordnung als Mic-**Index**
  (`assigned_mics: [Int]`). Eine neue Datei verschiebt die Scan-Reihenfolge → derselbe
  Index zeigt danach auf eine andere Datei. Zusätzlich matchte der Restore per
  `id == id && filename ==` — der Index-Teil scheitert bei jeder Dateiänderung (die
  Zuordnung ging dann still verloren).
- **Fix** (`EngineController.loadSession`): Kameras UND Mics werden nur noch über den
  **Dateinamen** (im Ordner eindeutig, stabil) gematcht. Die gespeicherten
  `assigned_mics`-Indizes werden über die im `.multicam` mitgespeicherte Mic-Liste
  (Index→Dateiname zum Speicherzeitpunkt) auf die AKTUELLEN Indizes umgerechnet
  (`currentMicIndex`). Repariert auch BESTEHENDE Sessions, weil die nötige Information
  schon im `.multicam` steht. Inzwischen entfernte Mics fallen per `compactMap` weg.
- **Lehre**: Persistente Zuordnungen NIE an Scan-Indizes hängen — der Dateiname ist der
  stabile Schlüssel.

### 0.6.5 stuerzt beim Start ab, wenn die Icons nicht gefunden werden — GEFIXT (25.07.), Ursache eingegrenzt (transienter Update-Moment)
- **Symptom**: Nach dem Update 0.6.2 → 0.6.5 (per Sparkle, MacBook des Users)
  stuerzt die App SOFORT beim Start ab, noch vor dem ersten Fenster.
  `EXC_BREAKPOINT` in `LucideIcon.image(named:size:)` →
  `NSBundle.module` → `_assertionFailure`. Die App ist damit unbenutzbar und
  der Nutzer erreicht nicht einmal mehr die Update-Pruefung — Rettung nur per
  manuellem DMG-Download.
- **Ursache (Absturz)**: `Bundle.module` ist ein vom Compiler erzeugter Zugriff,
  der bei nicht auffindbarem SPM-Ressourcenbundle **`fatalError` aufruft**. Ein
  fehlendes Icon wurde so zum Totalausfall.
- **Fix**: `LucideIcon` benutzt kein `Bundle.module` mehr, sondern durchsucht
  mehrere Orte und liefert `nil` (Icon zeichnet einfach nicht). Zusaetzlich legt
  `build_app.sh` die SVGs DIREKT nach `Contents/Resources/Icons` — unabhaengig
  vom SPM-Bundle — und **bricht ab**, wenn keine Icons da sind.
  Belegt: App mit entfernter Icon-Quelle gestartet → laeuft (vorher: Absturz).
- **Ursache eingegrenzt: transienter Zustand direkt nach dem Sparkle-Update.**
  Auf dem betroffenen Geraet war das Bundle NACH dem Absturz **vorhanden**
  (User geprueft, 25.07.). Der Absturz betraf also genau den einen Start
  unmittelbar nach dem Update — Sparkle startet die App neu
  (`applicationOpenUntitledFile` → `showInitialWindows`), waehrend die frisch
  platzierten Ressourcen noch nicht sauber ladbar waren (Registrierung/
  Quarantaene/Signaturpruefung im Moment des Erststarts). AUSGESCHLOSSEN:
  (a) DMG/Release enthaelt das Bundle samt 38 Icons; (b) identisches Binary
  (UUID) startet auf dem Zweit-Mac sauber; (c) der Delta-Patch 202607221504 →
  202607231746 liefert lokal angewendet das Bundle vollstaendig, Signatur
  gueltig — der Delta-Pfad ist NICHT die Ursache. Der defensive Fix
  neutralisiert diese Fehlerklasse dauerhaft: selbst wenn die Ressourcen im
  Erststart-Moment nicht ladbar sind, laeuft die App (Icons zeichnen dann
  nicht, statt Absturz). Diagnose bei Wiederauftreten:
  `ls -la /Applications/MultiCamCutter.app/Contents/Resources/`
- **Lehre**: Ressourcen-Zugriffe, die eine App zum Absturz bringen koennen,
  gehoeren nicht in den Startpfad. `Bundle.module` NIE benutzen.

### Kamera-ENDE wird nicht geprueft — Standbild + Asynchronitaet
- **Symptom (Testordner, TC 00:18:45:00)**: C0352 friert ein, ab dem naechsten
  Schnitt laeuft alles asynchron. Bestaetigt: C0352 ist exakt **18:45,6** lang,
  die Timeline aber 67 min. Jeder Schnitt auf C0352 danach greift auf nicht
  vorhandene Quell-Frames zu → Resolve haelt das letzte Bild als Standbild, der
  Ton laeuft weiter.
- **Ursache**: Der EDL-Bau prueft `off_vi < 0` (Kamera schon GESTARTET?), aber
  nirgends, ob sie am Cut-Zeitpunkt noch LAEUFT. Stellen: `add_reactions_to_edl.py`
  :295, :402, :716, :783 — alle nur Start, kein Ende. Wieder ein stiller Fehler:
  keine Meldung, das Ergebnis sieht gebaut aus.
- **Realer Anlass (User)**: Gast geht vor Folgenende, seine Kamera wird schon
  abgeschaltet, der Host moderiert weiter. Kein Edge-Case, sondern Alltag.
- **Gewuenschte Loesung (User)**: Ab dem Frame, an dem eine Quelle endet, die
  Kamera in der Engine **deaktivieren** — als waere sie ab da nicht mehr als
  Objekt vorhanden und damit fuer keinen Schnitt mehr verfuegbar (weder Sprecher
  noch Cutaway noch Bruecke). Symmetrisch zur bestehenden Start-Pruefung, nur am
  anderen Ende.
- **Anknuepfpunkt**: Die Laenge liegt bereits vor (`_probe_duration` in
  `waveform_sync.py`, und `shot_sizes` kennt die Kameras). Zusammen mit dem
  Sync-Offset ergibt das je Kamera ein gueltiges Frame-Fenster
  `[start, start+laenge)`, gegen das jeder Kandidat geprueft werden kann.
  Beruehrt Diarisierung (Sprecher-Wahl), PASS 2/4 (Cutaway-Wahl) und die
  Uebergangsregel — also am besten EINE zentrale „ist Cam X bei Frame f
  verfuegbar?"-Funktion, die alle nutzen.

### ~~Kameras ab Nr. 3 und Zusatz-Mikrofone wurden nie gesynct~~ — BEHOBEN (21.07.)
- **Symptom**: keines. Der Lauf war erfolgreich, das Material asynchron.
- **Ursache**: `sync_sources` mass genau zwei Paare — CAM1↔CAM2 und CAM1↔MIC1.
  Kameras ab Nr. 3 tauchten im Offsets-Dict gar nicht auf und wurden in
  `build_aaf.py` still als 0 behandelt. Zusatz-Mikrofone bekamen **ungeprueft**
  MIC1s Offset ("assumed synchronous with MIC1").
- **Tragweite**: Im synthetischen Test mit bekannter Wahrheit lag MIC2 dadurch
  um **150 Frames = 6 s** daneben, CAM3 um 75 Frames.
- **Verdeckt** wurde es in der App durch den `unsyncedCams`-Waechter (>2 Kameras
  blockiert); ueber die CLI gab es keinerlei Schutz.
- **Fix**: `sync_sources(cam_paths, mic_paths, fps, reference=None)` misst **jede**
  Quelle einzeln. Referenz ist das **laengste Mikrofon** statt CAM1 (Mikrofone
  laufen durch, Kameras stoppen und splitten), am Ende wird auf CAM1 = 0
  normalisiert — EDL, AAF und `_cam_shift` rechnen unveraendert weiter.
  Zusaetzlich eine **Kreuzprobe**: CAM1↔CAM2 wird unabhaengig nachgemessen und
  gegen die ueber die Referenz abgeleitete Differenz geprueft (Toleranz 2 Frames).
- **Verifikation**: synthetische Quellen mit bekannten Versaetzen, alle fuenf
  Offsets exakt getroffen (`scratchpad/synctest`).
- **Nachtrag 21.07. — die Kreuzprobe hat sofort zugeschlagen** (Episode 38,
  2 Cams / 3 Mics): MIC1↔CAM1 lieferte bei nur **21,3x** Confidence einen um
  2895 Frames falschen Offset, waehrend MIC1↔CAM2 (642,8x) und CAM1↔CAM2 (237,5x)
  stimmten. **Ursache**: die Rekorder liefen ~100 s vor den Kameras, und das
  Analysefenster wird von JEDEM Dateianfang genommen — von 180 s ueberlappten
  also nur ~78 s. Zu wenig fuer ein eindeutiges Maximum, aber genug, um die
  Schwelle von 5,0x zu passieren (bekannter Gotcha in
  `modules/multicam_cutter/CLAUDE.md`).
  **Ohne die Kreuzprobe haette der alte Code MIC1 mit dem falschen Wert gesetzt
  und ihn an MIC2 und MIC3 vererbt** — drei um 100 s verschobene Tonspuren, ohne
  jede Warnung.
  **Reaktion**: bei uneiniger Kreuzprobe wird die schwaechste Messung mit
  vierfachem Fenster nachgemessen und nur bei besserer Confidence uebernommen;
  erst wenn auch das nicht aufloest, wird abgebrochen.

### 🟢 Pause-Trim entfernt Sprache — gefixt (Praxistest der Schranken offen)
- **Symptom**: Video UND Audio sind an einer Stelle geschnitten, an der beide
  Sprecher reden — ein Stück Gespräch fehlt. **Inhaltsverlust**, kein
  Schönheitsfehler. Selten (2 Audioschnitte in einer 100-min-Folge), dafür
  eindeutig hörbar. Gefunden 20.07. in „44 - Danny Müller" bei TL 00:17:49:22
  (roter Marker des Users).
- **Belegt**: Audioschnitt bei WAV-Sekunde 1077,80. Pegel dort MIC1 −33,6 dB
  (Schwelle −46), MIC2 −43,3 dB (Schwelle −52) — **beide über der Schwelle**,
  also keine Pause. Nächste echte Stille: 1073,58–1075,60 s, **2,20 s entfernt**.
  Entfernt wurden 8 Frames (0,32 s) mitten aus einem Sprachblock (Spitze −10,1 dB).
  K-Means-Schwellen waren plausibel (Konfidenz „hoch"), das Crossbleed-Gate
  dämpfte MIC1 dort nur um 0,4 dB — beide als Ursache ausgeschlossen.
- **Ursache**: `detect_pauses` sucht die Pause im Radius von **3 s**
  (`--pause-search-radius`, Default 3.0) um eine Schnittgrenze. Der Trim
  verschiebt die Grenze dann auf die Pause — laut Kommentar
  (`pause_trim_edl.py:311`) „bedingungslos". Greift dabei aber der Cap
  `max_trim = ev_dur - min_event_frames` (`:320-324`), wird der Trim **teilweise**
  ausgeführt: Die Grenze wandert nur ein Stück in Richtung Pause und bleibt
  irgendwo dazwischen stehen — hier 0,32 s statt der nötigen 2,2 s. Entfernt
  werden die Frames trotzdem, nur eben aus Sprache statt aus Stille.
  **Es gibt keine Prüfung, ob der tatsächlich entfernte Bereich still ist.**
- **Zweites Symptom, gleiche Ursache — WIEDERHOLTE FRAMES**: User beobachtet bei
  eingeschaltetem Kopfnicken gelegentlich Pause-Trims, nach denen sich die letzten
  10–15 Frames wiederholen. Grund: `trim`/`delta` haben nur eine **obere** Schranke
  (`if trim > max_trim`, `:323`/`:341`), **keine untere**. Liegt die Pause auf der
  falschen Seite der Grenze, wird `trim` negativ — dann *verlängert*
  `ev['source_out'] -= trim` das Event, während `ev['source_in'] += delta` das
  folgende zurückzieht. Beide decken dieselben Source-Frames ab. Bei gleicher
  Kamera sieht man die Wiederholung. Der Kommentar (`:311`) hält das Verlängern
  für gewollt („in Stillebereich hinein") — es ist aber ungeprüft, ob dort Stille ist.
- **Warum Kopfnicken den Symptomtyp umschaltet**: Mit Nicken gibt es viele
  Schnittgrenzen, eine verschobene `boundary_frame` findet also meist *irgendeine*
  Grenze in Toleranz → viele Trims (User: 6–16/Folge), an falscher Stelle, teils
  negativ → Wiederholungen. Ohne Nicken gibt es wenige Grenzen → die meisten Pausen
  werden verworfen → nur 2 Trims, dafür mit fehlendem Sprachinhalt.
- **Verdacht auf die gemeinsame Wurzel (noch zu belegen)**: `run_from_folder.py:194-199`
  **rechnet die Record-Positionen neu** (kumulativ aus Source-Dauern ab 0), statt sie
  aus der EDL zu übernehmen. `boundary_frame` in `audio_trims.json` stammt aber aus den
  echten Record-TCs der Base-EDL. Solange kein Event fehlt, ist das identisch — aber
  `build_aaf._parse_edl` **überspringt** Events (Clipname nicht zuordenbar bzw.
  `src_in < 0`, `:221`/`:227`), und jedes übersprungene Event verschiebt alle folgenden
  Record-Positionen. Der Code warnt dort selbst: „Audio/Video-Sync kann abweichen".
  ⚠️ **Erklärt auch, warum die Web-App (`run_from_bin`) unauffällig ist**: dort kommen
  die Record-Positionen aus `parse_edl()`, also aus der EDL selbst.
  Zu prüfen im nächsten Lauf: (1) erscheint die ÜBERSPRUNGEN-Warnung, (2) stimmen die
  neu berechneten Record-Positionen mit `final.edl` überein, (3) wie viele Pausen
  fallen unter `skipped_no_boundary`.
- **✅ WURZEL GEFUNDEN UND GEFIXT (20.07.)**: `run_from_folder.py` rechnete die
  Record-Positionen kumulativ **ab 0** neu. Die EDL beginnt aber bei Frame **134**
  (WAV-Vorlauf) — ein konstanter Versatz über die ganze Timeline, **26× größer als
  die `boundary_tolerance` von 5 Frames**. Folge: 153 von 160 Pausen fanden keine
  Grenze mehr (`skipped_no_boundary`), nur 2 kamen durch — und die an beliebiger
  Stelle. Belegt am Lauf vom 20.07.: gegen die echten Record-Positionen finden
  **160/160** Pausen eine Grenze, gegen die rekonstruierten nur **7/160**.
  ⚠️ Mein erster Verdacht (übersprungene Events in `_parse_edl`) war **falsch** —
  es wurde kein einziges Event übersprungen.
  **Fix**: `build_aaf._parse_edl` liefert `record_in`/`record_out` aus der EDL mit;
  die Rekonstruktion entfällt.
  ⚠️ **Die Rekonstruktion existierte ZWEIMAL.** Erster Anlauf reparierte nur
  `run_from_folder.py` — **das nutzt die Mac-App gar nicht** (kein einziger Import).
  Der wirksame Ort ist `apps/multicam-cutter/engine/multicam_engine.py:885`, eine
  wortgleiche Kopie im eigenen Pause-Trim-Block. Vor jedem „gefixt" prüfen, welche
  Datei der App-Pfad tatsächlich ausführt — `run_from_folder.py` ist nur der
  CLI-Einstieg. Damit arbeitet der
  Folder-Workflow wie der Bin-Workflow, der die Positionen schon immer aus
  `parse_edl()` bezog — deshalb war die Web-App nie betroffen.
  **Offline verifiziert**: 2 → 20 Trims (User erwartet 6–16), und 19 der 20
  entfernten Bereiche sind nachweislich still; einer ist grenzwertig
  (Spitze −34,7 dB bei Schwelle −46).
- **✅ BEIDE SCHRANKEN UMGESETZT (20.07., `pause_trim_edl.py`)**:
  1. **Grenze muss IN der erkannten Stille liegen** (`ps <= matched_cb <= pe`, nach
     Snap). Getrimmt wird immer *rund um* die Grenze — liegt sie außerhalb der Pause,
     ist der entfernte Bereich per Definition nicht still. Ersetzt die ursprünglich
     angedachte Audio-Prüfung: **geometrisch statt messend**, braucht keinen
     Audio-Zugriff in `apply_pauses_to_cut_events`.
  2. **Untere Schranke** für `trim`/`delta`: `max(0, min(…, matched_cb - ps))` bzw.
     `max(0, min(…, pe - matched_cb))`. Negative Werte hatten das Event *verlängert*,
     wodurch beide Nachbarn dieselben Source-Frames abdeckten — die wiederholten
     Frames. Zusätzlich bleibt der entfernte Bereich damit immer innerhalb `[ps, pe]`.
  Getestet mit drei Szenarien (Grenze neben der Pause → nichts entfernt; Pause hinter
  der Grenze → nichts entfernt, keine Überlappung; Grenze in der Pause → trimmt
  weiterhin korrekt). ⚠️ Praxistest an echtem Material steht aus — `/tmp` war beim
  Nachmessen bereits geleert.
  ⚠️ Audio-Keeps dabei weiterhin aus den getrimmten Video-Events ableiten
  (siehe `modules/multicam_cutter/CLAUDE.md`, Fixed Bugs) — nicht separat rechnen.

### Dev-Only-Artefakte entstehen aus der Mac-App NIE (`decision_log.json`, `speaking_debug.json`)
- **Symptom**: Nach einem vollständigen Lauf aus der App liegen im Work-Dir zwar
  `final.edl` und `final.colors.json`, aber **weder** `decision_log.json` **noch**
  `speaking_debug.json`. Auch im Dev-Build (`swift run`) nicht. Beobachtet 20.07.
  an `/tmp/resolve-toolkit/19bdb46b2e59/`.
- **Ursache**: Beide Artefakte hängen an `is_dev_mode()` (`licensing/license.py:473`),
  das nichts über Debugging aussagt, sondern **nur** `MODE == "dummy"` prüft.
  `MODE` kommt aus `TOOLKIT_LICENSE_MODE` und defaultet zwar auf `"dummy"` —
  die App überschreibt das aber für jeden Engine-Subprozess:
  `LicenseConfig.mode = "remote"` (`LicenseConfig.swift:8`) →
  `LicenseConfig.apply(to:)` (`:16`) → `engineEnvironment()`
  (`EngineController.swift:1758`). Damit ist `is_dev_mode()` in **jedem** aus der App
  gestarteten Lauf `False`.
  Verifiziert: `TOOLKIT_LICENSE_MODE` nicht gesetzt → `True`, `dummy` → `True`,
  `remote` → `False`.
- **Sofort-Workaround**: Dev-App mit gesetzter Variable starten — `apply(to:)`
  respektiert einen bereits vorhandenen Wert:
  ```
  TOOLKIT_LICENSE_MODE=dummy swift run --package-path apps/multicam-cutter/MulticamCutter
  ```
- **Richtiger Fix (offen, zu entscheiden)**: Debug-Artefakte vom **Lizenzmodus
  entkoppeln**. Der Lizenzmodus beschreibt, wie lizenziert wird, nicht ob geloggt
  werden soll — die Kopplung ist der eigentliche Fehler. Eigenes Signal, z. B.
  `MULTICAM_DEBUG=1` (von der App im Debug-Build gesetzt) oder ein verstecktes
  Setting. Betrifft `add_reactions_to_edl.py:1153`,
  `build_base_edl_from_audio.py` (speaking-Debug) und `run_from_bin.py:984`
  (Console-Capture — vermutlich aus demselben Grund ebenfalls wirkungslos, noch
  nicht gegengeprüft).

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

### Preset mit Built-in-Namen überschreiben tat scheinbar nichts — GEFIXT (15.08.)
- **Symptom:** Ein bestehendes Preset mit demselben Namen überschreiben (v.a. eines der
  drei Built-ins wie „Podcast 2-Cam") → gespeichert, aber nichts wurde sichtbar/geladen.
- **Ursache:** `PresetManager.listPresets` fügte Built-ins zuerst ein und **übersprang**
  dann eine User-Datei gleicher id; `loadPreset` prüfte Built-ins **zuerst**. Die
  `<slug>.json` des Users wurde also geschrieben, aber vom gleichnamigen Built-in verdeckt.
- **Fix (`EngineController.swift`):** **User-Datei hat jetzt Vorrang** — `listPresets`
  ersetzt ein Built-in gleicher id durch die User-Version (User-Name, `builtIn:false`),
  `loadPreset` liest die User-Datei zuerst und fällt nur sonst aufs Built-in zurück. Der
  Preset-Picker zeigt nach dem Speichern automatisch das Preset als ausgewählt (Rückmeldung).
- **Nebeneffekt (ok):** Ein über ein Built-in gespeichertes Preset verdeckt dieses (User
  gewinnt). Original zurück = die User-Datei in Application Support/MulticamCutter/presets löschen.

### Preset-Picker zeigte nach Auswahl das falsche (parameter-gleiche) Preset — GEFIXT (15.08.)
- **Symptom:** „JENA UNITED 3" auswählen → nach Schließen der Liste steht „JENA UNITED 2" da.
- **Ursache:** Die angezeigte Auswahl war KEIN gemerkter Zustand, sondern abgeleitet:
  `matchingPresetId = presets.first { loadPreset == engine.params }`. Bei zwei Presets mit
  IDENTISCHEN Parametern (2 vs. 3) liefert `.first` das ERSTE — also „2", egal was gewählt war.
- **Fix (`WizardView.swift` → `WizPresetDropdown`):** eigener `@State selectedId` als
  Anzeige-Wahrheit; der Picker bindet daran. Bei EXTERNEN Parameter-Änderungen (Slider/Toggle)
  gleicht `.onChange(of: engine.params)` ab: bleibt der Stand exakt auf dem gewählten Preset,
  bleibt die Auswahl (auch bei Duplikaten); sonst passendes Preset oder „Custom". Speichern
  setzt `selectedId` aufs frische Preset.

### 29,97-AAF: Drift + danach Kamera-Desync — Edit-Rate UND Drop-Frame-Reel-TC — GEFIXT (15.08., ⚠️ NLE-Gegentest offen)
- **Symptom (in zwei Wellen)**: Projekt mit zwei 29,97-Kameras (Sony, `rtmd`-Metadaten).
  (1) App monierte fälschlich FPS-Mismatch (Timeline fix 25) → Konvertierungs-Drang.
  (2) Nach 29,97-Timeline: AAF **driftete** (Standbild am Ende). (3) Nach Edit-Rate-Fix:
  **ab Timeline-Start komplett asynchron** — und die **Kameras untereinander** desynchron
  (eine am Ende schon aus, während die andere noch läuft, ~56 s Versatz).
- **Ursachen (vier, nacheinander gefunden)**:
  1. **App leitete Projekt-FPS nie aus dem Scan ab** (`@Published var fps = 25.0` hart).
     → Fix (Swift): `EngineController.deriveProjectFpsFromCameras()` — gleiche FPS aller
     aktiven Kameras (±0,01) wird Timeline-FPS. Uneinheitlich → unverändert (Warnung greift).
  2. **Edit-Rate `int(round(fps))` = 30/1** statt 29,97 → 30er-Timeline auf 29,97-Material →
     Speed-Adaption → **Drift/Standbild**. → Fix (`build_aaf._edit_rate`): krumme NTSC-Raten
     als **exakter Bruch** `AAFRational(30000,1001)`; Ganzzahl-fps bleiben plain int (25er byte-identisch).
  3. **EDL-TC-Round-Trip driftete ±1 Frame** bei krummer fps (fraktionale Rechnung).
     → Fix (`shared/frame_utils`): Zählung über **nominale Ganzzahl-Rate** `round(fps)`
     (Non-Drop) → Round-Trip exakt für ALLE fps, byte-identisch für Ganzzahl-fps.
  4. **⚠️ DER Kamera-Desync-Killer: Reel-TC muss DROP-FRAME sein.** Das Sony-Material ist
     Drop-Frame (29,97). Der ALTE Code rechnete `* 29.97` (fraktional) ≈ Drop-Frame-Zählung
     und traf den Reel-TC damit **zufällig ~richtig**. Mein Non-Drop-Fix (Ursache 3) machte
     den Reel-TC Non-Drop → beim Resolve-Reel+TC-Link verschob sich JEDE Kamera um ihren
     **akkumulierten Drop-Frame-Versatz** (108 F/Std). Weil die Kameras verschiedene
     Tageszeit-TCs haben (C9540 23:58 → Δ86 s, C8575 08:27 → Δ30 s), war der **relative**
     Versatz **56 s** — exakt das Symptom. → Fix (`build_aaf`): `_is_dropframe(fps)`
     (29,97/59,94 = Drop-Frame) + `_dropframe_count()`; Reel-TC (Tape) + Timeline-TC werden
     **Drop-Frame** (`Drop=True`, Start = Drop-Frame-Zählung), `create_tape_slots(drop_frame=…)`.
     **Wichtig:** die relative Position (`source_in`) bleibt NOMINAL — die Subtraktions-Ref
     in `_parse_edl` ruft `_probe_embedded_tc_frames` OHNE `dropframe` → nur der ABSOLUTE
     Reel-/Timeline-TC ist Drop-Frame, die Schnitte bleiben frame-exakt.
- **Detektion Drop-Frame (`_detect_dropframe`, aus der Datei — wie Resolve)**: Sony `rtmd`
  hat KEINEN `tmcd`-Track, und ffprobe/ffmpeg normalisieren den TC-String auf ':'. ABER das
  Flag steht in Sonys **NonRealTimeMeta-XML** in der Top-Level-`meta`-Box:
  `<LtcChange frameCount="0" value="HHHHHHHH">` = SMPTE-12M-gepackter Start-TC als Hex; im
  **Frames-Byte (höchstes Byte) ist Bit 6 (0x40) das Drop-Frame-Flag**. `0x60375823` →
  23:58:37:20, DF=1. An C9540/C8575 verifiziert (beide DF=True, deckt sich mit Resolve-Anzeige).
  Nur Metadaten gelesen (schnell auch bei 100 GB). **fps-Annahme `_is_dropframe` nur Fallback**,
  wenn kein Sony-Meta da ist (z.B. tmcd-Kameras → Rest-Sliver im TODO).
- **Dateien**: `EngineController.swift`; `build_aaf.py` (`_edit_rate`, `_NTSC_RATIONALS`,
  `_is_dropframe`, `_dropframe_count`, `_probe_embedded_tc_frames(dropframe=…)`, `_make_timecode_slot(drop=…)`);
  `shared/frame_utils.py`.
- **Validierung ohne NLE**: synthetisch + **echtes Material** → Readback: Edit-Raten `30000/1001`;
  Reel-TC C8575=913212 / C9540=2586940 (beide `Drop=True`, = Drop-Frame-Zählung der echten
  embedded TCs); Locator 4, MasterMobs 4; Sync sauber (Conf 123–194×). 25er byte-identisch,
  Diarize/Totale grün. **Test-AAF im Projektordner: `49_DROPFRAME_TEST.aaf`.**
- ⚠️ **NLE-Gegentest offen (nur User)**: `49_DROPFRAME_TEST.aaf` in **Resolve UND Premiere** —
  Kameras untereinander synchron, A/V ab Start synchron, kein Standbild, Medien online.
  **Fürs Release: Engine-Rebuild.**
- **Merke**: (a) Krumme fps NIE als `int(round())` in die Edit-Rate — nur der exakte Bruch.
  (b) Bei Drop-Frame-Material MUSS der Reel-/Timeline-TC Drop-Frame sein, sonst desynchronisieren
  Kameras mit unterschiedlichem Tageszeit-TC über den akkumulierten DF-Versatz. (c) Interne
  Frame-Zählung bleibt nominal/Non-Drop (exakter Round-Trip); NUR der absolute TC ist Drop-Frame.

### Schnitt-Begruendung ging zweimal auf dem Weg verloren
- **Symptom**: Uebergangs-Einstellungen hiessen im AAF „Sprecher" statt
  „Uebergang". Sichtbar war der Schnitt korrekt — nur nicht zuzuordnen.
- **Zwei getrennte Verlustpunkte**, nacheinander gefunden:
  1. **`write_edl`** schrieb nur Timecodes und Clipnamen. Beim Wiedereinlesen
     setzte `parse_resolve_edl` pauschal `speaker`.
     → Fix: `* CUT REASON`-Kommentar schreiben und lesen. Der Parser sammelt
     jetzt ALLE Kommentarzeilen nach einem Event ein; bei festem Blick auf `i+1`
     haette je nach Reihenfolge Clipname oder Begruendung gefehlt.
  2. **PASS 2 baut die Events NEU.** Die geparsten Events dienen nur als
     Section-Grenzen; die neuen bekamen den Standardwert.
     → Fix: Sections tragen `reason` mit, `build_events_with_cutaways` nimmt sie
     als `base_reason`.
- **Die entscheidende Stelle war die unscheinbarste**: der Zweig in `main()`
  „keine OFF-Kamera → Sections direkt uebernehmen". Genau dort landen die
  Bruecken, denn die Bruecke ist die Totale und fuer sie gibt es keine
  Cutaway-Quellen. Ohne diese eine Stelle haette der Fix ueberall gegriffen
  **ausser dort, wo er gebraucht wird**.
- **Nebenwirkung, die niemand bemerkt haette**: Solange die Begruendung fehlte,
  war der Schutz in PASS 3 (`reason == 'transition'`) **toter Code**. Dass die
  Bruecken ueberlebten, lag allein an ihrer Laenge — bei einem kuerzeren Wert
  waeren sie stillschweigend verschwunden.
- **Merke**: Eine Eigenschaft, die eine Datei-Serialisierung passieren muss,
  ueberlebt sie nur, wenn beide Seiten sie kennen. Und ein Schutz, der auf einer
  solchen Eigenschaft beruht, ist ohne Beweis nur eine Vermutung.

### Schwache Korrelationen wurden ungeprueft uebernommen (Confidence-Schwelle)
- **Befund (3-Cam-Test, 21.07.)**: Eine Totale (Actioncam, `VID_…`) lieferte bei
  JEDEM Analysefenster eine Confidence um 12x — und dabei voellig verschiedene
  Offsets: −478 (180 s), +95 (600 s), −460 (1500 s). Ueber CAM1 gemessen −472,
  ueber CAM2 −374. **Es gibt bei dieser Quelle keinen echten Korrelationsgipfel**;
  die Korrelation findet Rauschen und liefert je Fenster eine andere Zufallszahl.
- **Erkennungsmerkmal**: gleichbleibend niedrige Confidence bei WACHSENDEM Fenster.
  Bei echtem Signal steigt sie mit mehr Material.
- **Warum es durchging**: `MIN_CONFIDENCE = 5.0` ist die Schwelle zum
  Weitersuchen, nicht zum Vertrauen. 12x passiert sie muehelos. Die Kreuzprobe
  deckte nur CAM1↔CAM2 ab — jede andere Quelle blieb ungeprueft.
- **Fix (21.07.)**: Neue Schwelle `TRUST_CONFIDENCE = 50.0`. Jede Quelle darunter
  wird ueber einen ZWEITEN Weg gegengeprueft (sicherste andere Quelle als Pruefer);
  weichen beide Wege um mehr als 2 Frames ab, bricht der Sync ab und nennt Quelle,
  beide Ergebnisse und die Confidence.
- **Wirkung**: Der 3-Cam-Ordner bricht jetzt mit klarer Diagnose ab statt mit
  einem um bis zu 4 s falschen Offset weiterzurechnen. Beide bekannt guten
  2-Cam-Episoden laufen unveraendert durch (Confidences dort 100–470x).
- **KORREKTUR (21.07., wenige Stunden spaeter)**: Die Schlussfolgerung „Totale
  per Waveform nicht syncbar" war **falsch**. Die flache Confidence war echt,
  ihre Ursache aber eine andere: der wahre Versatz (30 min) lag ausserhalb des
  durchsuchbaren Bereichs. `correlate(mode="full")` findet nur Lags bis zur
  Laenge der REFERENZ — mit 180 s Referenz sind 30 min prinzipiell unauffindbar,
  und man sieht ausschliesslich Rauschen. Auch der Gegentest mit 1500 s reichte
  nicht, weil der gesuchte Versatz bei 1808 s liegt.
  **Merkregel**: flache Confidence bei WACHSENDEM Fenster heisst nicht „kein
  Signal", sondern zuerst „Suchraum zu klein".
  Mit asymmetrischen Fenstern (Ziel 180 s, Referenz waechst bis zur vollen Laenge)
  synct dieselbe Totale mit **177x** statt 12x.

### Unvollstaendige Quelldatei wird beim Scan unbesehen uebernommen
- **Symptom (Episode 38, 21.07.)**: Waveform-Sync bricht mit „Kreuzprobe
  fehlgeschlagen" ab. Sieht nach einem Korrelationsproblem aus, ist aber keines.
- **Wahre Ursache**: `C7451_25fps.MP4` war ein **94-Sekunden-Fragment** einer
  abgebrochenen FPS-Konvertierung (Original `C7451.MP4`: 99 min). Die App nahm
  es beim Scan als vollwertige Kamera an — 1,6 min Video gegen 100 min Ton.
- **Warum die Nachmessung nicht half**: `_sync_pair` kappt beide Seiten per
  `min_len` auf die kuerzere Datei. Ein groesseres Fenster anzufordern aendert
  nichts, wenn nur 94 s existieren — Confidence und Offset kamen deshalb auf die
  Nachkommastelle identisch zurueck. Genau das war der Hinweis.
- **Der Konverter war nicht schuld**: Er prueft seine Ausgabe seit dem 18.07.
  (`out_dur < dur * 0.98` → Datei loeschen + Fehler). Das Fragment stammt vom
  17.07., ist also einen Tag aelter als der Schutz.
- **Luecke**: Der Schutz griff nur beim KONVERTIEREN. Eine unvollstaendige Datei
  kann auch anders entstehen — abgebrochener Kopiervorgang, halb geladene
  Cloud-Datei, Altbestand.
- **Fix (21.07.), zweiter Anlauf**: Der erste Versuch — Abbruch bei Quellen unter
  3 min — behandelte das Symptom. Der User wandte zu Recht ein, dass 95 s
  gemeinsames Material fuer eine Korrelation reichlich sind. Die wahre Ursache
  lag in `_sync_pair`:
  ```python
  min_len = min(len(ref_audio), len(target_audio))
  ref_audio = ref_audio[:min_len]     # kappt die REFERENZ auf 94 s
  ```
  Die Referenz wurde auf die Laenge des kuerzeren Partners gestutzt, **gerechnet
  ab ihrem eigenen Anfang**. MIC1 blieben so nur die ersten 94 s — reiner
  Vorlauf, null Ueberlappung mit CAM1 (beginnt bei Sekunde 102). Zugleich sinkt
  damit der groesste auffindbare Versatz auf ebendiese Laenge: 102 s waren
  **prinzipiell unauffindbar**.
  Die Kuerzung war ueberfluessig — `correlate(mode="full")` kommt mit
  unterschiedlich langen Signalen zurecht. Sie ist entfernt; der harte Abbruch
  gilt nur noch unter `MIN_SOURCE_SECONDS` (10 s), darunter ist es Rauschen.
  Quellen unter 50 % der laengsten erzeugen weiter einen Hinweis (kann legitim
  sein, wenn eine Kamera nur zeitweise lief).
- **Verifiziert**: 95-s-Fragment bei 102 s Vorlauf synct jetzt exakt; beide
  frueheren Szenarien (5 Quellen, 100-s-Vorlauf) unveraendert korrekt.
- **Merke**: Die Kreuzprobe hat hier korruptes EINGANGSMATERIAL aufgedeckt, nicht
  einen Rechenfehler. Ohne sie waere daraus klaglos ein Schnitt entstanden.

### Deltas wurden nie hochgeladen — jedes Update lud die volle DMG
- **Symptom**: keines. Updates funktionierten, nur langsam.
- **Ursache**: `publish.sh` lud genau **eine** Datei hoch (`$OBJECT_KEY`, die
  versionierte DMG). Die von `generate_appcast` erzeugten `.delta`-Dateien blieben
  liegen, obwohl der Appcast sie bewirbt. Ebenso pruefte Schritt [2/4] nur die
  erste Enclosure-URL.
- **Warum es niemandem auffiel**: Sparkle versucht das Delta und faellt bei einem
  Fehler **still** auf die volle DMG zurueck. Das Update gelingt also — es
  uebertraegt nur **346 MB statt 832 KB** (Faktor ~400). Kein Fehler, keine Meldung.
- **Nachgewiesen (21.07.)**: Im Bucket lagen nur `0.5.0.dmg` und `0.5.2.dmg`.
  Der Feed bewarb zusaetzlich `0.5.1.dmg` und **drei** Deltas — alle 404.
- **Fix (21.07.)**: `publish.sh` laedt jetzt **alles hoch, was der Appcast
  referenziert** und lokal in `release/updates/` liegt, und die Pruefung geht
  ueber **jede** Enclosure-URL statt nur die erste. Bei einer nicht abrufbaren
  Datei wird der Appcast nicht veroeffentlicht.
- **Grundregel**: Der Appcast definiert, was im Bucket liegen muss. Was dort nicht
  mehr referenziert wird, darf geloescht werden — und nur das.

### notarize.sh direkt aufgerufen -> unsigniertes DMG
- **Symptom**: `⚠ SIGN_IDENTITY nicht gesetzt — DMG bleibt unsigniert`, danach
  laeuft die Einreichung bei Apple trotzdem weiter.
- **Ursache**: Die Identitaet wird in `release.sh:39` aus dem Schluesselbund
  ermittelt und an `notarize.sh` durchgereicht. Wird `notarize.sh` **direkt**
  gestartet (z.B. um nach einem Abbruch nur die Notarisierung zu wiederholen),
  ist die Variable leer — `make_dmg.sh` hat dann nur gewarnt und weitergebaut.
- **Tragweite**: Apple notarisiert das unsignierte DMG anstandslos, aber
  Gatekeeper lehnt es beim Oeffnen mit `no usable signature` ab. Der Defekt
  faellt also erst nach Upload, Notarisierung und Download auf.
- **Fix (21.07.)**: `notarize.sh` ermittelt die Identitaet notfalls selbst aus
  der **App-Signatur** (`codesign -dv` -> erste `Authority=`-Zeile) — damit wird
  das DMG zwingend mit derselben Identitaet signiert wie sein Inhalt — und
  bricht ab, wenn keine ermittelbar ist. `make_dmg.sh` bricht bei `NOTARIZED=1`
  ohne Identitaet hart ab statt nur zu warnen.
- **Dateien**: `scripts/notarize.sh`, `scripts/make_dmg.sh`

### DMG-Bau: geratener Mountpunkt gestaltet das falsche Volume
- **Symptom**: `hdiutil: convert failed - Die Ressource ist zeitweilig nicht
  verfuegbar` beim Komprimieren. Alternativ — je nach Timing — ein fertiges,
  aber **ungestaltetes** DMG **ohne Fehlermeldung**.
- **Ursache**: `make_dmg.sh` setzte `MOUNT_DIR="/Volumes/$VOL"` als Annahme,
  statt den Mountpunkt aus der `hdiutil attach`-Ausgabe zu lesen. Existiert
  bereits ein Volume dieses Namens (abgebrochener Vorlauf, Testimage), haengt
  macOS das neue still als `/Volumes/<Name> 1` ein. Folge: der Finder gestaltete
  das ALTE Volume, `detach` warf das ALTE aus, die "wirklich weg?"-Pruefung war
  damit zufrieden — und `convert` lief, waehrend das NEUE Volume noch hing.
- **Fix (21.07.)**: Mountpunkt wird aus der `attach`-Ausgabe gelesen; der Finder
  wird ueber `basename "$MOUNT_DIR"` angesprochen statt ueber `$VOL`; verwaiste
  Volumes gleichen Namens werden vor dem Einhaengen ausgeworfen; die
  Auswurf-Pruefung befragt zusaetzlich `hdiutil info` nach dem Image, weil ein
  verschwundenes `/Volumes/...` nicht beweist, dass das Image freigegeben ist.
- **Datei**: `scripts/make_dmg.sh`

### 🔴 0.5.0 wurde mit einer zwei Tage alten Engine ausgeliefert
- **Symptom**: Analyse aus 0.5.1 bricht ab mit
  `unrecognized arguments: --cam-person-names`. Die App sendet das Argument, die
  gebündelte Engine kennt es nicht.
- **Ursache**: `build_app.sh` friert die Engine **nicht** ein, es **kopiert** nur
  `dist/multicam-engine` ins Bundle (`:78`). PyInstaller muss vorher von Hand
  laufen. Am 21.07. war `dist/` vom **19.07. 20:06**, die Quellen vom 20.07. —
  der Build meldete trotzdem Erfolg.
- **Tragweite**: In **0.5.0, das live ist**, fehlt jede Python-Änderung seit dem
  19.07.: Pause-Trim-Fix (Inhaltsverlust!), AAF-Clipnamen, FP-Filter Regel A,
  Kopfnicken-Schalter, speaking_debug. Die Swift-Seite war aktuell — deshalb sah
  die App neu aus, verhielt sich aber wie vorher.
- **Warum es niemandem auffiel**: Die Versionsnummer stammt aus der Info.plist
  (Swift-Seite), nicht aus der Engine. Ein Bundle mit neuer Version und alter
  Engine ist von außen nicht unterscheidbar.
- **Abgesichert (21.07.)**: `build_app.sh` vergleicht jetzt die mtime der
  eingefrorenen Engine gegen alle `.py` unter `modules/`, `shared/`,
  `licensing/`, `engine/` und **bricht ab**, wenn Quellen neuer sind. Bewusst
  kein Auto-Rebuild — PyInstaller läuft mehrere Minuten und soll eine
  Entscheidung bleiben. `SKIP_ENGINE_CHECK=1` übergeht die Prüfung.
- **Zu tun**: `cd apps/multicam-cutter && pyinstaller scripts/multicam_engine.spec`,
  dann Release neu bauen und **0.5.2 nachschieben** — die Nutzer von 0.5.0 haben
  den Pause-Trim-Bug weiterhin.
- **Nachtrag (23.07.):** Das „0.5.2 nachschieben" ist durch die 0.6.x-Releases ueberholt — alle Nutzer sind laengst auf neueren Versionen.

### Kameras ab Nr. 3 werden nicht gesynct → stillschweigend Offset 0
- **Symptom**: Bei **3+ Kameras** läuft die dritte (und jede weitere) zeitlich
  versetzt zum Rest — ohne Fehlermeldung. Bei 2 Cams (bisheriger Normalfall)
  tritt es NICHT auf.
- **Ursache**: `sync_sources()` (`shared/waveform_sync.py`) hat eine feste Signatur
  `(cam1, cam2, mic1, additional_mics)` und misst nur **CAM1↔CAM2** und **CAM1↔MIC1**.
  Beide Aufrufer (`apps/multicam-cutter/engine/multicam_engine.py:825`,
  `modules/multicam_cutter/run_from_bin.py:932`) reichen nur `cam_paths[0]` und
  `cam_paths[1]` durch. CAM3 landet nie im Offsets-Dict; `build_aaf.py:258`
  (`offsets.get(f'CAM{i+1}', 0)`) macht daraus **stumm eine 0**.
- **Nebenbefund**: Zusatz-Mics werden ebenfalls nicht gemessen, sie **erben** MIC1s
  Offset (`waveform_sync.py:206`). Unkritisch, solange alle Mics von einem Recorder
  kommen (bisheriger Fall), falsch bei getrennten Recordern.
- **Status**: **abgesichert** (nicht behoben). Ein Wächter in der App verhindert, dass
  der Fall still eintritt: `EngineController.unsyncedCams` (alles ab Position 3 in
  `orderedAnalysisCams`) → `UnsyncedCamsBanner` auf Screen 2 + `startBlockedReason`
  sperrt den Analyse-Start. Lieber laut blockieren als stumm falsch schneiden.
  Der eigentliche Fix (N-Cam-Sync) folgt in der Multicam-Session.
- ⚠️ **NICHT die Ursache des Gast-Async-Bugs vom 18.07.** Der Lauf hatte 3 Mics, aber
  nur **2 Cams**; dort war allein der abgeschnittene CAM1-Clip schuld (s. „Gefixt").
- **Fix bewusst aufgeschoben**: gehört in die große Multicam/Close-Totale-Session, weil
  die Sync-Referenzlogik davon abhängt, wie Close/Totale künftig modelliert wird.
  Richtung (siehe TODO „Sync-Robustheit"): alle Quellen **einzeln** gegen eine
  **Mic-Referenz** messen, Ausgabe so normalisieren dass CAM1 = 0 bleibt.
- **Nachtrag (23.07.):** GEFIXT durch den N-Sync (Teil A, 0.6.0): jede Quelle wird einzeln gegen die Referenz (laengstes Mikrofon) gemessen; der App-Waechter ist seit 0.6.3 ganz aufgehoben.

### Automatische Update-Pruefung meldete sich nie (Toggle war an)
- **Symptom (User, 23.07.)**: Trotz aktiviertem „Automatisch nach Updates
  suchen" kam beim App-Oeffnen ueber mehrere Releases hinweg nie eine
  Benachrichtigung.
- **Ursache**: KEIN Verkabelungsfehler — Updater startet korrekt beim App-Start
  (`MulticamCutterApp:7`), Toggle greift. Aber Sparkles Default-Intervall ist
  **24 h**, und JEDER manuelle Check sowie jede Update-Installation setzen
  `SULastCheckTime` zurueck. Bei mehreren Releases pro Tag (und staendigem
  manuellem Pruefen) wurde die automatische Pruefung schlicht nie faellig.
  Belegt per `defaults read com.jenaunited.multicam-cutter SULastCheckTime`.
- **Fix**: `SUScheduledCheckInterval = 3600` (Sparkles Minimum) in der
  Info.plist (build_app.sh). Die App meldet sich beim Oeffnen, sobald der
  letzte Check ueber eine Stunde her ist. Greift ab dem naechsten Build.
- **Merke**: Wer haeufiger als das Intervall manuell prueft, sieht per
  Konstruktion nie eine automatische Meldung — das ist Sparkle-Verhalten,
  kein Bug.

### Dock-Fortschrittsbalken bleibt nach Analyse-Ende stehen
- **Symptom**: Analyse fertig, aber das Dock-Icon zeigt weiter den Balken.
- **Ursache**: `DockProgress.hide()` setzte `NSApp.dockTile.contentView = nil` und rief
  danach `display()`. Ohne contentView hat `display()` aber nichts zu zeichnen — die
  **zuletzt gerenderte Kachel (mit Balken) bleibt stehen**. Der Aufruf kam korrekt
  (`.running` → `.done`), er wirkte nur nicht.
- **Fix**: `MacIntegrations.swift` — vor dem Abhängen den Balken wegzeichnen:
  `DockProgressView.fraction = -1` (Sentinel: „nur Icon zeichnen") + `display()`,
  **dann** `contentView = nil` + `display()`.

### Fenster bleibt schmal bei Rückkehr zum Projekt (nach Analyse)
- **Symptom**: Nach fertiger Analyse zurück ins Projekt → Fenster bleibt auf der
  schmalen Analyse-Breite (760 pt).
- **Ursache**: `animateWindowWidth` verwarf `frameBeforeRun` bereits beim **ersten**
  Verlassen von `.running`, also schon bei `.done`. Der Weg zurück ins Projekt ist aber
  ein **zweiter** Wechsel (`.done` → `.ready`), bei dem SwiftUI die Fensterbreite erneut
  an den Content anpasst — da war die gemerkte Geometrie längst weg.
- **Fix**: `ContentView.animateWindowWidth` restauriert bei **jedem** Nicht-Running-
  Zustand und gibt `frameBeforeRun` erst bei `.ready`/`.idle` frei.
- **Merke**: Ein Analyse-Lauf durchläuft mehrere Zustandswechsel — Aufräumlogik darf
  ihren Zustand nicht schon beim ersten davon verwerfen.

### Gespeichertes Preset taucht nicht in der Preset-Liste auf
- **Symptom**: „Preset speichern …" im Wizard-Footer legt das Preset an, aber das
  Dropdown zeigt es nicht — weder als Auswahl noch beim Aufklappen.
- **Nicht** die Ursache: Das Speichern selbst funktionierte einwandfrei (Datei lag
  korrekt in `~/Library/Application Support/MulticamCutter/presets/`).
- **Ursache**: Reines SwiftUI-Datenfluss-Problem. `WizPresetDropdown` rief
  `PresetManager.shared.listPresets()` **direkt im Body** auf. `PresetManager` ist ein
  einfacher `Sendable`-Singleton ohne Observability, und die Methode liest bei jedem
  Aufruf frisch vom Dateisystem — SwiftUI hat darauf **keine Abhängigkeit** und baut
  das Menü folglich nicht neu.
- **Fix**: Preset-Liste als echter `@State` (`presets`), nach Speichern/Import per
  `reloadPresets()` neu einlesen, zusätzlich `.onAppear`. Auswahl-Logik über
  `matchingPresetId` statt mehrfacher Inline-Aufrufe.
- **Nebeneffekt**: deutlich weniger I/O — vorher wurde pro Render mehrfach das
  Verzeichnis gelistet UND je Preset die JSON geladen (für den Params-Vergleich).
- **Merke**: Sobald eine View Daten aus einem nicht-observablen Singleton/Dateisystem
  zeigt, muss der Zustand in `@State`/`@Published` gespiegelt werden — sonst
  aktualisiert SwiftUI nicht.

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
