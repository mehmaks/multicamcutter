# Architektur-Entscheidungen

## SwiftUI statt Electron/Qt/Streamlit
- Native Mac-UX (Dock-Icon, Cmd+Tab, Keyboard-Fokus, Dark Mode)
- Kein Browser noetig
- Kleine Binary (~5 MB ohne Python-Bundle)
- Streamlit bleibt im Toolkit fuer die Web-UI, wird in der App nicht genutzt

## Python-Backend als Subprocess statt Embedded
- Kein PythonKit/version-Konflikt-Risiko
- Klare Trennung: Swift kennt kein Python, Python kennt kein Swift
- JSON-Lines-Protokoll: debugbar, testbar, erweiterbar
- Engine laeuft auch standalone fuer CLI-Nutzung

## PyInstaller statt py2app/Nuitka
- Beste Community-Erfahrung mit PyTorch + MediaPipe + OpenCV
- OneDir (nicht OneFile): schnellerer Start, einfacher zu debuggen

## Kein App Store
- Apple verbietet embedded Python-Runtimes
- Distribution als DMG ueber Website

## arm64-only
- Intel-Macs ab 2025/26 vernachlässigbar
- PyTorch MPS nur auf Apple Silicon
- mlx-whisper (spaeter) nur arm64

## CLIP im Bundle statt on-demand Download
- Wird fuer PASS 5 Ignore-Filter benoetigt (Cutaway verschieben bei "trinkt")
- ~350 MB Modell, aber PyTorch ist eh im Bundle
- Kein Netzwerk-Download beim User noetig

## Keine Auto-Zuordnung Mics->Cams
- User koennte denken die App hat es erkannt — taeuschend
- Mics starten immer als "nicht zugeordnet"
- User ordnet manuell per Drag & Drop

## Thumbnail: Scrubbing + Klick statt CLIP-Scan
- CLIP-Scan beim Ordner-Laden dauerte zu lange (15-20s)
- Scrubbing ist interaktiver und schneller
- Klick waehrend Scrubbing pinnt den Frame permanent

## Auto-Update: Sparkle Framework
- Industriestandard fuer Mac-Apps ausserhalb des App Stores
- Appcast-XML auf Server/GitHub Pages, Sparkle als Swift Package
- "Auf Update pruefen"-Button im About-Dialog
- Uebergangsweise: simpler GitHub-Release-Check (/releases/latest)

## Zwei GETRENNTE Keypairs (nicht verwechseln!)
Es gibt zwei unabhaengige Ed25519-Keypairs mit unterschiedlichem Zweck:

| | Sparkle-Update-Key | Lizenz-Key |
|---|---|---|
| Signiert | App-Updates (DMG/ZIP) | `license.json`-Dateien |
| Public Key | `Info.plist` → `SUPublicEDKey` | `licensing/license.py` → `_PUBLIC_KEY_B64` |
| Private Key | **beim Entwickler** (Keychain) | **auf dem Server/Backend** (Secret) |
| Tool | `sign_update` | `licensing/keysign.py` |

- Der Server braucht NUR den Lizenz-Private-Key (zum Lizenz-Signieren), NIE
  den Sparkle-Key. Beide Keys koennen die Aufgabe des anderen nicht erfuellen.
- Lizenz-Signaturformat: `_canonical()` in `license.py`/`keysign.py`
  (sortierte Keys, Listen als sortierter CSV, `k=v` mit `|` verkettet).

## Lizenzmodell: Abo via LemonSqueezy + signierte Lease (MODE=remote)
Entscheidung: Abo-Modell (monatlich/jaehrlich), NICHT das Offline-Datei-Modell
(`MODE=local`) — monatlich manuell eine license.json nachladen waere kein Abo-UX.

- **LemonSqueezy** = Zahlungsanbieter + Merchant of Record (EU-VAT erledigt) +
  eingebaute Lizenzschluessel-API. Key ist ans Abo gekoppelt (aktiv→`active`,
  gekuendigt→`expired`/`disabled`).
- **Flow**: App → unser Backend (Key + device_id) → Backend prueft LS
  (`/v1/licenses/activate` bei Erststart, `/v1/licenses/validate` danach) →
  bei aktivem Abo signiert Backend eine **kurze Lease** (Ed25519, unser Key,
  `expires = min(LS-Ablauf, now + ~7-14 Tage)`) → App cached + verifiziert offline.
- **Refresh**: bei jedem Start; Lease laeuft offline ~7-14 Tage weiter (Grace).
  Kuendigung wirkt automatisch (Server stellt keine neue Lease aus).
- **LS activate/validate brauchen KEINEN LS-Secret** (Client-Endpoints). Einziger
  kritischer Backend-Secret: unser Lizenz-Private-Key.
- **Reuse**: `_validate_remote` (key-file, POST, cache, 7-Tage-Grace) + Signatur-
  Infra sind schon da. Zu ergaenzen: Server signiert Antwort, App verifiziert sie,
  Refresh-Trigger, Free-Tier-Gate (kein Key = 30-Min-Limit statt Fehler).
- **Lease-Laenge = Trade-off**: kurz → nach Kuendigung schnell dicht, aber wenig
  Offline-Toleranz. ~7-14 Tage gewaehlt (Tool wird meist online genutzt).

## license_private.key NIEMALS ins Bundle
- Der PyInstaller-Spec bundelte frueher den ganzen `licensing/`-Ordner inkl.
  `license_private.key` → Schluessel lag in JEDER App, Lizenzen faelschbar.
- Fix: Spec kopiert nur `license.py` + `__init__.py` (Public Key).
- Guardrail in CLAUDE.md ergaenzt.

## Totale: explizit markieren, NICHT aus fehlendem Mic raten (überholt die alte Regel)
- **Alt (verworfen)**: Cam ohne Mic → automatisch „wide". Nebenwirkung: jede mic-lose
  Cam wurde still zur Totale erklärt **und um 150 % gezoomt** (`wide_zoom`) — unerwünscht.
- **Neu**: Totale ist ein explizites `isWide: Bool` pro Cam (Rechtsklick-Toggle).
  Cam ohne Mic UND ohne Totale = geht gar nicht in die Analyse (Card sagt es offen).
- **Zoom gestrichen**: `wide_zoom`-Default überall auf 1.0 (die Cams sind ordentlich
  eingerichtet). War in den Aufrufern noch `1.5` → mitgezogen.
- Host/Gast (früher `CamTag`) taten nachweislich nichts → entfernt. Rollen kämen
  künftig an der **Person**.

## Person = abgeleitete Sicht, kein gespeichertes Erstklassen-Objekt (Stufe 1)
- Eine Person wird NICHT persistiert, sondern zur Laufzeit aus dem Cam↔Mic-Graphen
  abgeleitet: `persons` = eine je aktivem Mic, Kameras = Cams mit diesem Mic in
  `assignedMics`, Name = Mic-Anzeigename.
- **Warum**: hält den Engine-Kontrakt (`--cam-mics`/`--cam-types`) unangetastet →
  die Personen-Sicht + der neue Inspector-Reiter tragen **null Pipeline-Risiko**.
  Erst wenn Personen eigene Namen/Rollen/Totale-Zuordnung bekommen, wird gespeichert.
- Bewusst zuerst gebaut, weil dieselbe Grundlage drei spätere Features trägt
  (Totale↔Person, Mehr-Totalen-Auswahl, Bildgrößen-Wechsel) — „sonst baut man dreimal um".

## Audio-Preview: RMS-Dominanz statt feste Sekunde
- Pauschal Sekunde 30 zeigte oft die falsche Person
- RMS-Analyse (2 Min, 1s-Fenster) findet wo Mic dominant ist
- Laeuft in <2s, deutlich bessere Trefferquote

## FPS-Konvertierung: quellabhaengige Hardware-Encoder (VideoToolbox)
- **Problem**: Die Umwandlung lief mit libx264 (Software, 4:2:2 10-bit, crf14) —
  bei 4K/50p ~36 s fuer 27 s Material, CPU 100 %. Wunsch: schneller + gradebare,
  quellgetreue Kopie.
- **Entscheidung (25.07.)**: Encoder richtet sich nach dem QUELLFORMAT
  (`_video_encode_args`), hardware-beschleunigt (Apple Silicon):
  - **4:2:0** (Action-Cams/Drohnen/Exporte, der Normalfall) -> `hevc_videotoolbox`
    10-bit, `-q:v 72`. Kein Chroma-Verlust (die Quelle IST 4:2:0; das alte libx264
    rechnete unnoetig auf 4:2:2 hoch). q72 an echtem 4K-10bit kalibriert = exakt die
    Bildtreue von libx264-crf14 (PSNR 48,8 / SSIM 0,995 in beiden).
  - **4:2:2 / 4:4:4** (Profikameras) -> `prores_videotoolbox` (hq bzw. 4444).
    Apples HW-HEVC kann KEIN 4:2:2 (rechnet still auf 4:2:0 runter, gemessen) —
    ProRes erhaelt die Chroma. `.mov`-Container.
- **Hardware-DECODE ist der eigentliche Hebel**: `-hwaccel videotoolbox` beim Input.
  Ohne ihn bremst der Software-Decode von 4K/50p alles aus (30 s statt 9 s). Nur beim
  HW-Versuch; der Software-Rueckfall (libx264, greift wenn HW scheitert) laeuft ohne.
- **Messung (echtes 4K-10bit, 27 s, 50->25p)**: alt libx264 36 s / 433 MB · neu
  HEVC q72 **10 s / 522 MB**. ~3,6x schneller, ~1,2x groesser (HW-Encoder sind
  weniger effizient), gleiche Qualitaet, CPU frei.
- **Exponiert** in den Settings ("Bildraten-Umwandlung"): HEVC-Qualitaet (Slider
  50-95, Default 72) + ProRes-Profil (standard/hq). Engine-CLI: `--hevc-quality`,
  `--prores-profile`. App reicht sie per UserDefaults durch.
- **TC erhalten** in allen Zweigen verifiziert (tmcd-Datenspur wandert mit).

## i18n: Englisch als Quell-/Key-Sprache, Deutsch via de.lproj (system-folgend)
- **Problem (15.08.)**: App komplett zweisprachig DE/EN machen (Punkt 8). Ausgangslage:
  Arbeitsbaum hatte bereits die englischen Screenshot-Strings + den frischen 29,97-
  Dropframe-Fix uncommittet vermischt.
- **Entscheidung**: **Englisch = Key-Sprache** (Quelltext bleibt Englisch), Deutsch als
  Übersetzung in `Localization/de.lproj/Localizable.strings`. NICHT „Deutsch als Key"
  (der dokumentierte Ur-Plan) — das hätte ein Zurücksetzen der Swift-Quellen auf Deutsch
  verlangt und den im selben Baum liegenden Dropframe-Fix gefährdet. Sprachwahl folgt der
  macOS-Systemsprache (`CFBundleDevelopmentRegion=en`, `CFBundleLocalizations=(en,de)`);
  kein In-App-Umschalter (nachrüstbar).
- **Mechanik**: Bare `Text("literal")` lokalisiert SwiftUI automatisch (Key=Literal).
  Für `String`-Parameter durch Views der `loc()`-Wrapper (`NSLocalizedString`); Custom-
  Komponenten `loc()`-en intern. Interpolationen: einzeilige `Text` nativ (`%@`/`%lld`),
  Plurale via Count-Branch + `String(localized:)`. Engine emittiert Englisch (Keys), App
  lokalisiert per `loc()`/`locStepLabel()`. Voll dokumentiert: `brain/TODOs.md` → „Multilanguage".
- **Preis**: `swift run` (Dev) zeigt Englisch (kein `.lproj` in Bundle.main) — Deutsch nur
  im gebauten `.app`. Web-Schema bleibt vorerst DE-only (App ist ab jetzt die Text-Wahrheit).
