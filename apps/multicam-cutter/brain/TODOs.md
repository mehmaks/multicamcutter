# TODOs & Roadmap — MultiCamCutter

> **Diese Datei = OFFENE Arbeit + 1.0-Roadmap.** Erledigte TODOs liegen im Archiv
> `brain/TODOs-Archiv.md` (Historie + Gotchas — nicht löschen, dort steckt oft die
> Begründung/der Fallstrick eines späteren Bugs).

## 🔥 Vorgezogen — höchste Priorität

- **Engine-Rebuild für den 29,97-Drop-Frame-Fix** (aufgenommen 15.08.). Der Fix
  (`build_aaf.py` Edit-Rate 30000/1001 + Drop-Frame-Reel-TC, `shared/frame_utils.py`
  nominale Zählung, Swift `deriveProjectFpsFromCameras`) wirkt im **Dev** sofort, muss
  aber für die ausgelieferte App ins **PyInstaller-Bundle** (Frozen-Rebuild). Details:
  `brain/Bekannte-Bugs.md` → „29,97-AAF: Drift + Kamera-Desync". Swift-Teil ist im
  Binary; nur die Python-Engine braucht den Rebuild.
  ✅ **Drop-Frame-Detektion erledigt (15.08.):** `build_aaf._detect_dropframe` liest das
  Flag aus Sonys NonRealTimeMeta (`<LtcChange value=…>` in der Top-Level-`meta`-Box,
  SMPTE-12M Bit 6 im Frames-Byte) — dieselbe Quelle, die Resolve anzeigt. fps-Annahme
  (`_is_dropframe`) ist nur noch Fallback. An C9540/C8575 verifiziert (beide DF=True).
  🔧 **Rest-Sliver (optional):** Kameras MIT `tmcd`-Track (nicht-Sony) → Flag aus dem
  tmcd-Sample-Entry lesen (Bit 0 der Flags); die fallen aktuell auf die fps-Annahme zurück.

## Weg zu 1.0

**Definition-of-Done 1.0:** „Ohne Fremdscham an einen fremden Cutter verkaufbar" —
kein bekannter Dead-End auf realem Material, Distribution sauber, der Kern (Ordner
rein → korrektes AAF für Resolve **und** Premiere) bulletproof. 1.0 fällt, wenn
A + B + die vorgezogenen Backlog-Themen stehen — **unabhängig vom restlichen
Backlog (C)**.

### 🔒 Feste Abarbeitungsreihenfolge (gelockt 25.07. — bis 1.0 NICHT mehr umsortieren)

Strikt Punkt für Punkt von oben nach unten. **Keine Neu-Sortierung bis 1.0** — Ausnahmen
nur: echte Bugs und kleine kosmetische Anpassungen. Neue Feature-Ideen gehen nach
Post-1.0 (C), nicht in diese Liste.

| # | Punkt | Bucket | Aufwand | Warum an dieser Stelle |
|---|---|---|---|---|
| ~~1~~ ✅ | ~~**Sync-Graceful**~~ — GELIEFERT (25.07.), Detail im Archiv (Vorbehalt: manueller-Offset-Re-Run an echtem Problemmaterial noch ungetestet) | 🎯 A | ✓ | erledigt — nächster offener Punkt: **2** |
| ~~2~~ ✅ | ~~**FPS-Check zusammenführen**~~ — GESCHLOSSEN (25.07.): native App schon kohärent (ein Check, ein Rezept, kein Exit-42); Doppelung nur zum abgelösten Resolve/Streamlit-Toolkit. Detail im Archiv | 🎯 A | ✓ | erledigt — nächster offener Punkt: **3** |
| 3 | **Bundle-Größe** — ⚠️ WIEDER OFFEN (25.07.): „verifiziert" war FALSCH. Excludes brachen im Release Nodding (mediapipe→matplotlib) + CLIP (transformers→pandas/pyarrow/sklearn). Spec gefixt; braucht **Frozen-Rebuild + Patch-Release + Nodding-Lauf am Release**. Sichere Excludes: nur llvmlite/numba/plotly | 🎯 A | leicht | Lehre: sys.modules-Trace statt grep |
| ~~4~~ ✅ | ~~**Mehrere Totalen Stufe 1**~~ — GELIEFERT (25.07.): `totale_mode` (round_robin/random/first), Reset + Multi-Person-Fallback rotieren, Experten-Picker + Schema. Rest-Sliver: Base-EDL-Totale (Binär-Simultan) noch first-only | ✨ B | ✓ | erledigt — nächster offener Punkt: **5** |
| ~~5~~ ✅ | ~~**Dock-Balken gewichtet**~~ — GELIEFERT (25.07.): Engine schickt `step_weights` (Nodding/CLIP dominieren, adaptiv zu Kamerazahl+CLIP), Swift normiert `overallProgress`, Fallback bei Mismatch | ✨ B | ✓ | erledigt — nächster offener Punkt: **6** |
| 6 | **Telemetrie** (Opt-in) — ✅ App-Seite KOMPLETT (26.07.: Consent-Prompt gebaut); Backend gebaut (Web-Session, lokal verifiziert); OFFEN: **Deploy** (Web-Repo) + E2E | 🌍 | mittel | App fertig (Toggle Default AUS + Erst-Start-Zustimmung, fire-and-forget); Rest extern |
| ~~7~~ ✅ | ~~**Settings-Durchgang**~~ — GELIEFERT (26.07.): User-Änderungsliste (CSV) eingepflegt — ParamHelp ×20 Hilfetexte + 3 Experten-Labels an Basis angeglichen (Min./Max. Schnittlänge, Pausen kürzen) + Web-Schema `help` synchron. **String-Freeze steht**, Build grün | ✨ B | ✓ | erledigt — nächster offener Punkt: **8** |
| 8 | **Mehrsprachigkeit DE/EN** — ⚡ EN-Übersetzung schon fertig auf Branch `en-screenshots` (~400 Strings), bleibt nur Infra+Verdrahtung+QA, **~2 Tage** system-folgend. Detail + Aufwandstabelle unten in „Multilanguage (planen)" | 🌍 | mittel–schwer | **Capstone**: Freeze-then-Translate — Engine→Keys, Swift lokalisiert, ParamHelp ×30, Web-Schema-Sync über die eingefrorene Menge → **1.0** |

**Rückgrat der Ordnung (nicht willkürlich):** 6 → 7 → 8. Telemetrie bringt den letzten
neuen Toggle, der Settings-Durchgang friert danach *alle* deutschen UI-Texte ein, und
i18n übersetzt die eingefrorene Menge **einmal**. Punkt 4 (neuer Totalen-Param) liegt
bewusst vor 7. 1–3 (Blocker) zuerst, weil Wert/Risiko am höchsten.

Detail-Beschreibungen der Punkte unten (nach Bucket gruppiert).

## Offene TODOs

### 🎯 A — 1.0-Blocker

### ✅ Sync-Graceful (Punkt 1) — ERLEDIGT (25.07.), ins Archiv verschoben
Rescue über sichere Partner · Referenz-Re-Anchor auf Kamera · melden-statt-abbrechen
(`sync_unresolved`) · manueller Offset / Ausschluss / Abbrechen. Volle Historie:
`TODOs-Archiv.md`. Commits u.a. `2b115fc` `137a35a` `4b117c9` `a1d92b9` `e306165` `4e732f9`.
- [ ] ⚠️ **Vorbehalt (offen):** manueller-Offset-Re-Run nur mit künstlich fremder Datei
  geprüft (kein sinnvoller Offset möglich) — an echtem Problemmaterial noch verifizieren.

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

**Schritt 1 — ⚠️ KORRIGIERT (25.07.): frühere „verifiziert"-Behauptung war FALSCH.**
Die Excludes brachen im Frozen-Build **Nodding** (mediapipe → matplotlib, Default AN!)
und **CLIP** (transformers → pandas/pyarrow/sklearn) — transitive Deps, die der grep-nach-
direkten-Imports nicht sah. Mein „alle Pakete fehlen, Releases liefen" war kein Beweis:
im Dev (venv) lief alles, 0.6.5–0.6.7 hatten im RELEASE **kaputtes Nodding**.
**Fix (Spec):** `matplotlib`, `pandas`, `pyarrow`, `sklearn` wieder drin; nur `llvmlite`
(110 MB), `numba`, `plotly` bleiben ausgeschlossen (per `sys.modules`-Trace als ungenutzt
bestätigt). Engine +~159 MB. Braucht **Frozen-Rebuild + Patch-Release + Nodding-Lauf am
echten Release**. Details: `brain/Bekannte-Bugs.md`. `onnxruntime` (59 MB) weiter drin.

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

### ✨ B — 1.0-Qualität

- [x] **Mehrere Totalen — Stufe 1 GELIEFERT (25.07.)** (Stufe 2 = Personen-Zuordnung bleibt Edge-Case, s.u.). Aufwand war: **mittel**.
  **Ist-Zustand (Falle!)**: Taggt man 2+ Cams als Totale, sind alle ausser der ersten
  **totes Gewicht** — es wird nie auf sie geschnitten, ohne dass irgendwas es sagt:
  - `add_reactions_to_edl.py:266` → `off_cam = wide_cams[0]` (Multi-Person-Cutaway)
  - `add_reactions_to_edl.py:332` → `reset_cam = wide_cams[0]` (Reset nach max_shot)
  - `run_from_bin.py:658` → `next((i for i,t in … if t=='wide'), None)` → nur die erste
    wird `--totale-video` fuer die Base-EDL
  (Nur `build_aaf.py:394` kennt ALLE wide-Cams — fuer den Zoom, der jetzt aus ist.)

  **✅ Stufe 1 GELIEFERT (25.07., Punkt 4):** Parameter `totale_mode` (round_robin
  [Default] / random [fester Seed, reproduzierbar] / first [altes Verhalten]). Auswahl
  **pro Cutaway** via `_pick_totale` (State im settings-Dict, rotiert global über
  Sections). Angewandt am **Max-Shot-Reset** und am **Multi-Person-Totale-Fallback**;
  bei 0/1 Totale byte-identisch. Experten-Picker „Mehrere Totalen" (Cutaway-Regeln) +
  Schema + `ParamHelp.totaleMode`. Tests: `test_totale_mode.py`, Diarisierungs-Suite grün.
  ⚠️ **Rest-Sliver (offen):** die Base-EDL-Totale (`--totale-video`, binärer
  Simultan-Sprech-Pfad, `run_from_bin.py`) rotiert noch NICHT — nutzt weiter die erste.
  Im N-Pfad irrelevant (Simultan → kleinste gemeinsame Kamera). Kleiner Nachzug.
  ⚠️ **Changelog fürs nächste Release:** Multi-Totale-Setups schneiden ab jetzt anders (rotieren).

  **Stufe 2 (später, Edge-Case)**: Totalen **Personen zuordnen**. Beispiel: 4 Personen
  mit je einer Close-Cam, dazu eine Totale P1+P2, eine P3+P4 und eine mit allen. Dann
  soll die Totale gewaehlt werden, die die **reagierenden** Personen zeigt (Fallback:
  die Totale mit allen).
  💡 **Das Datenmodell kann das schon**: Die App ordnet Mics bereits Cams zu. Fuer eine
  Totale muesste die Zuordnung nur andere **Semantik** bekommen — bei `.wide` heisst
  „Mics zugeordnet" nicht „spricht hier", sondern **„zeigt diese Personen"**. `analysisCams`
  laesst Totalen ohne Mic weiterhin zu, das passt also zusammen. UI muesste den
  Bedeutungswechsel nur klar machen (Drop-Ziel-Text auf einer Totale anders benennen).

- [x] **Settings-Durchgang mit User — ERLEDIGT (26.07.).** User ist alle Settings selbst
  durchgegangen und hat eine Änderungsliste (CSV) übergeben. Eingepflegt: **20 Hilfetexte**
  in `ParamHelp.swift` (Kürzungen + Präzisierungen, z.B. „einer nicht aktiv sprechenden
  Person", Crossbleed/Gate-Texte, Bildsprache-Cooldowns mit Querverweis), **3 Experten-Labels**
  an die Basis-Liste angeglichen (`Min./Max. Shotlänge`→`Schnittlänge`, `Pausen trimmen`→
  `Pausen kürzen`), und dieselben `help`-Felder im **Web-Schema** (`multicam_params.json`)
  synchronisiert (Labels dort bewusst NICHT angefasst — anderes Namensschema mit „(s)"-Suffix).
  Build grün, JSON valide. **Damit ist der deutsche String-Freeze erreicht** → Basis für Punkt 8.
  - [ ] ⚠️ **2 vereinheitlichte Divergenzen** (User gab für dieselbe Konstante in Basis vs.
    Experte unterschiedlichen Text — es gibt aber nur EINE Konstante pro Key): `noddingEnabled`
    → „einer zuhörenden Person" (statt Experten-Variante „der zuhörenden Personen"),
    `pauseCutawayEnabled` → knappe Basis-Formulierung. Kann der User bei Bedarf einzeilig ändern.

### 🌍 1.0 — vorgezogen aus Backlog (User, 25.07.)

### Telemetrie (anonyme Nutzungsdaten) — Aufwand: **mittel**

**✅ Contract + App-Seite geliefert (25.07.):** `brain/Telemetrie-API.md` (Payload nur
Zahlen/Enums; die 3 DSGVO-Regeln). `Telemetry.swift` (anonyme `analytics_id`, fire-and-
forget POST an `/api/telemetry`, nur bei Zustimmung). `EngineController.sendTelemetryIfEnabled`
baut den Payload (n_cams/n_mics/n_speakers, Dauern, elapsed_s, komplettes Settings-Abbild
via `params.toDict()`, Built-in-Preset via `PresetManager.matchingBuiltIn` sonst „custom",
Gerät) und feuert im `result`-Dispatch. Settings → Datenschutz: Opt-in-Toggle (**Default AUS**,
Key `analyticsConsent`: 0 ungefragt/1 an/2 aus). Alles **inert**, bis Backend steht.

**✅ Erst-Start-Consent-Prompt GEBAUT (26.07.):** `TelemetryConsentSheet.swift` — einmalige
Opt-in-Frage, DSGVO-konform (freiwillig, transparent, Datenschutz-Link `/de/privacy`,
Escape/„Nein danke" = datensparsame Wahl, Enter löst KEINE Zustimmung aus). In
`ContentView` **nach** dem Material-Hinweis sequenziert (`onDismiss` → nie gestapelt),
erscheint nur bei `analyticsConsent == 0`. Setzt 1/2 im geteilten @AppStorage-Key.
Damit ist die App-Seite von Punkt 6 komplett.

**⚠️ NOCH OFFEN (extern / abhängig):**
- **Deploy (Web-Session):** Backend ist gebaut (Neon-Postgres Frankfurt, `POST /api/telemetry`,
  204, PII-Backstop serverseitig, Rate-Limit, Privacy-Seite DE/EN — lokal E2E verifiziert),
  aber **noch nicht deployed**. Details/Stand: `brain/Telemetrie-API.md`. Erst nach Deploy
  landet echte Telemetrie in der DB.
- **✅ Contract-Abgleich erledigt (26.07., Web-Session bestätigt):** Payload Feld-für-Feld
  geprüft. `app_version`→kurz gefixt; `device.chip`/`os` werden wortgetreu gespeichert
  (Token-Filter nur auf `settings.*`); Privacy-Link `/de/privacy` korrekt (next-intl
  Always-Prefix); verschachtelte `settings` ok; alle `settings`-Enums sind Whitespace-freie
  Tokens < 32 Z. → nichts wird gedroppt. Feld-Regeln jetzt im Contract (`Telemetrie-API.md`).
- **✅ `runtime.per_step_s` implementiert (26.07.):** Engine (`multicam_engine.py`/`protocol.py`)
  sendet je Schritt einen stabilen, PII-freien Key (`scan`/`sync`/`base_edl`/`nodding`/`cutaways`/
  `pause_trim`/`aaf`) statt der deutschen Labels (mit Kameranamen). App misst die Wall-Clock-Dauer
  je Key (Nodding×N summiert automatisch), sendet unter `runtime.per_step_s`. ⚠️ **Engine geändert
  → für 0.6.9 Frozen-Rebuild nötig** (Dev greift sofort).
- **E2E-Test** (Backend ist live, 405-Probe): Zustimmung → echter Lauf → Event bereinigt in der DB.
  Erster Prod-Run belegt (26.07.): device/settings wortgetreu, PII-frei; `app_version`-null war
  Stale-Build (gefixt), `per_step_s` fehlte (jetzt gebaut) — Re-Test bestätigt beides.
- **Reihenfolge:** ausliefern erst mit einem Release NACH dem Deploy (sonst fragt die App
  Zustimmung für einen noch toten Endpoint). Trifft sich mit 0.6.9 (Freeze ist eh unpubliziert).

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

### Multilanguage (planen)
- [ ] **Mehrsprachigkeit konzipieren (DE/EN)**. Die Website ist bereits zweisprachig
  (next-intl, `src/messages/{de,en}.json`) — die App ist es **gar nicht**: alle
  Strings sind hart in Deutsch einkompiliert. Zu klären, bevor es teuer wird:
  1. **Swift-Strings**: String Catalog (`.xcstrings`) braucht Xcode-Tooling — wir
     bauen aber per SPM/`build_app.sh`. Alternative: `Localizable.strings` + `.lproj`
     in `Contents/Resources` von build_app.sh mitkopieren.
     **✅ Vorarbeit (26.07.):** `build_app.sh` deklariert die App jetzt als deutsch
     (`CFBundleDevelopmentRegion=de` + `CFBundleLocalizations` + physische
     `Contents/Resources/de.lproj/InfoPlist.strings`). Der `.lproj`-Weg ist damit schon
     angelegt — für EN nur `en` in `CFBundleLocalizations` ergänzen + `en.lproj` befüllen.
     Nebeneffekt: Sparkles Update-UI ist dadurch jetzt deutsch (`brain/Bekannte-Bugs.md`).
  2. **Engine-Ausgaben**: die Engine sendet deutsche Step-Labels/Fehlertexte über
     JSON-Lines. Sauber wäre: Engine sendet **Keys** (+ Parameter), Swift lokalisiert.
     → Protokoll-Änderung, siehe `brain/Engine-Protokoll.md`.
  3. **Parameter-Texte**: `ParamHelp.swift` (30 Texte) + alle Labels sind DE-only.
     Quelle `config/schemas/multicam_params.json` hat ebenfalls nur DE → Web-Modul
     müsste mitziehen, sonst driften die Sprachen auseinander.
  4. Reihenfolge/Umfang: erst EN, weil die Website EN schon anbietet und Tester/Käufer
     darüber kommen.

  **✅ Ist-Stand nach EN-Screenshot-Build (12.08.):** Auf Branch `en-screenshots` sind
  **alle ~400 sichtbaren Strings** bereits von DE→EN übersetzt (15 Swift-Dateien +
  `engine/multicam_engine.py` + `engine/protocol.py`, ~940 Diff-Zeilen). ⚠️ Das ist noch
  **KEINE i18n** — die deutschen Literale wurden 1:1 durch Englisch *ersetzt*, kein
  Umschalten. **ABER:** Der Branch-Diff (`git diff main..en-screenshots`) liefert alle
  DE→EN-Paare fertig — **die eigentliche Übersetzungsarbeit ist erledigt**, es bleibt
  Infrastruktur + Verdrahtung + QA. Package.swift hat noch kein `defaultLocalization`,
  0 `NSLocalizedString`/`String(localized:)` im Code.
  **Umfang-Messung:** ~527 Literale, davon ~102 `Text()` (SwiftUI lokalisiert automatisch,
  Literal = Key), ~93 `Button/Label/Toggle/Picker/Section/Menu`, ~35 Alert-Texte,
  ~19 mit String-Interpolation, ~16 Engine-Step-Labels (Python).

  **Restaufwand bis „final zweisprachig" (~2 Arbeitstage, System-folgend):**
  - **Infrastruktur (~½ Tag):** `defaultLocalization: "de"` + `en`/`de` in
    `CFBundleLocalizations` (build_app.sh legt de.lproj schon an, s.o. Punkt 1) +
    `Localizable.strings` je `.lproj`. Für SPM-Build den `.strings`/`.lproj`-Weg
    nehmen (NICHT `.xcstrings` — braucht Xcode-Toolchain, wir bauen per build_app.sh).
    SwiftUI `Text("Deutsch")` sucht dann „Deutsch" als Key in der Tabelle → für DE
    Fallback auf Key, für EN Mapping `"Deutsch" = "English";`.
  - **Katalog befüllen (~½ Tag):** `en.lproj/Localizable.strings` automatisch aus dem
    Branch-Diff extrahieren (DE=Key, EN=Wert), Sonderfälle prüfen (Interpolationen,
    mehrzeilig, gleiche DE-Strings mit unterschiedlichem Kontext).
  - **Nicht-`Text`-Strings kapseln (~1 Tag):** `String(localized:)` für Alerts,
    `.help()`, `ParamHelp`-Werte (×30), Menü-/Accessibility-Labels, interpolierte Formate.
  - **Engine (~¼ Tag):** Sprache per Env/Arg an die Engine reichen + DE/EN-Dict für die
    ~16 Step-Labels (`multicam_engine.py`/`protocol.py`). Sauberer Weg lt. Punkt 2:
    Engine sendet **Keys**, Swift lokalisiert.
  - **QA beide Sprachen (~½ Tag):** DE Umlaute/Truncation, EN Textlängen/Layout.

  **⚖️ Eine offene Entscheidung, die den Aufwand treibt — Sprachwahl:**
  - **System-Sprache folgen** (macOS entscheidet) → im Aufwand oben drin, praktisch gratis.
  - **Eigener DE/EN-Umschalter in den Settings** → **+½–1 Tag** (Bundle-Swapping in
    SwiftUI/SPM ohne Neustart ist fummelig).
  → **Empfehlung:** erst System-folgend finalisieren (schnell, robust), In-App-Umschalter
  nur nachrüsten, wenn LemonSqueezy-Käufer ihn verlangen.

### ⏳ Zuletzt (ans Ende gestellt 15.08. — nach den 1.0-Blockern)

- [ ] **CLIP-Nodding-DROP finalisieren + Prompt-Schwelle kalibrieren** (aufgenommen 27.07.,
  ans Ende gestellt 15.08.). Code steht bereits: DROP-Modus statt Shift für Nodding-Cutaways,
  `max`-Scoring, handlungsspezifische Prompts (`config/clip_ignore_prompts.json`,
  `add_reactions_to_edl.py` PASS 5 + `_clip_score_for_event(score_mode='max')`).
  **OFFEN:** (1) Schwelle `clip_nodding_threshold` 0,6 an echten Trink-Nick-Timecodes
  bestätigen — **User liefert TCs**; (2) Dev-Lauf/echter Lauf zur Sicht-Kontrolle;
  (3) Engine-Rebuild fürs Release. Hintergrund/Validierung:
  `modules/multicam_cutter/CLAUDE.md` → Fixed Bugs → „Nachtrag (27.07.)".

### 📦 Post-1.0 (geparkt)

- [ ] **Multitrack-AAF: eine Videospur je Kamera, Umschnitte per Clip-Aktivierung.**
  (Externes Feedback, 26.07. — im Workflow des Users nie relevant, für andere Cutter
  aber wichtig; stand bisher NICHT im TODO.) Statt alle Umschnitte auf EINE Videospur zu
  schneiden, bekommt jede Kameraquelle eine eigene Spur; der Umschnitt entsteht durch
  AKTIVIEREN/DEAKTIVIEREN von Clips: zu jedem Zeitpunkt ist genau eine Kamera aktiv, an
  jedem Schnittpunkt bekommen ALLE Spuren einen Cut (C1→C3→C1: auf der C1-Spur der mittlere
  Clip deaktiviert, auf C3 nur der mittlere aktiv). Nutzen: der Cutter kann einzelne
  Umschnitte im NLE durch Re-Aktivieren einer anderen Spur bequem ändern.
  ⚠️ **Recherche-Ergebnis (26.07.): so wörtlich NICHT sauber machbar.** AAF hat KEIN
  „disabled/muted"-Clip-Flag (pyaaf2-Metadict vollständig geprüft; nur Avid-Extension
  `Parameter.IsEnabled` für Effekt-Parameter, nicht für Clips). Einziger spec-nativer
  Verwandter: der **`Selector`** (`Selected` + `Alternates`; pyaaf2 kann ihn schreiben,
  Write/Readback getestet) — aber das ist „EINE Spur, ein aktiver Clip + Alternativen".
  Premiere UND Resolve **verwerfen die Alternates beim Import** (Premiere lässt deaktivierte
  Clips beim AAF-Export sogar ganz weg; Multicam überlebt den AAF-Austausch generell nicht).
  Ein „vorhanden-aber-deaktiviert, per Klick reaktivierbar"-Clip ist reines NLE-UI, kein
  transportierbares AAF-Konzept.
  ✅ **Interoperable Alternative (empfohlen): eine Spur pro Kamera, aktiv = SourceClip,
  inaktiv = Lücke (Filler).** An jedem Schnitt bekommt jede Spur einen Cut; die aktive
  Kamera trägt den Clip, die anderen eine Lücke. Im Repo bereits bewiesen
  (`modules/take_selector.py:95-124` best_set + Filler in `build_aaf.py:621,644`); die
  Interop-Invarianten (Locator/CDCIDescriptor/TapeMob-TC aus `AAF-Struktur.md`) bleiben 1:1,
  nur das Layout wird „N parallele Slots V1…Vn mit Clip/Lücke" statt „1 Sequence auf V1".
  ⚠️ Preis: „inaktiv" ist eine echte Lücke, KEIN Toggle — der Cutter sieht nur, *wann* eine
  Kamera live ist, kann aber nicht per Häkchen umschalten. Echtes Angle-Switching gibt nur
  die native NLE-Multicam her → nicht aus AAF, sondern über die in `AAF-Struktur.md`
  skizzierte direkte NLE-Anbindung. **Vor Bau: 3-Cam-Test-AAF (Spur-pro-Kamera + Lücken) in
  Resolve UND Premiere gegenprüfen — framegenaue Cuts, Lücken korrekt, Medien online.**

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
- [ ] Timeline-View: NLE-artige Darstellung der generierten Timeline.
  Farbkodierte Clips, Reason-Labels, scrollbar, zoombar.
  Spaeter: RMS-Wellenform, Decision-Log-Marker.
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

- [ ] **Dock-Balken oszillieren lassen, wo die App es auch tut.** Aufwand: **mittel**.
  Regel im Fenster: `stepPercent > 0` → determinate, sonst oszillierend
  (`ContentView.swift:444-466`). Dieselbe Regel im Dock anwenden.
  ⚠️ **Haken:** `NSDockTile` animiert nicht von selbst — `DockProgressView` zeichnet
  nur, wenn `display()` gerufen wird. Ein oszillierender Balken braucht also einen
  Timer (~10–15 fps), der eine Phase weiterdreht und neu zeichnet. Der Timer **muss
  auf jedem Ausstiegspfad sterben** (fertig, Fehler, Abbruch), sonst zeichnet er nach
  dem Lauf weiter — dieselbe Fehlerklasse wie der Balken, der nach der Analyse stehen
  blieb (siehe `Bekannte-Bugs.md`).

### Metadaten-Ableitung (Recherche 25.07. — an echten Dateien geprueft)
- [ ] **Mehrspurige WAVs erkennen & je Kanal als eigene Quelle behandeln.** Aufwand:
  **mittel**. Manche Field-Recorder legen EINE WAV mit N Kanaelen an (je Kanal =
  ein Mikro). Kanalzahl lesen ist trivial (`ffprobe stream=channels`), Split in
  Mono geht per ffmpeg (`channelsplit`/`pan`) — beides verifiziert.
  ⚠️ **Blocker im aktuellen Code**: `load_audio` macht `-ac 1` (Downmix) → eine
  Mehrspur-WAV wuerde JETZT zu Mono-Matsch summiert. Noetig: >1 Kanal erkennen →
  im Wizard als N Personen-Quellen anbieten (statt 1 Datei = 1 Mic) → je Kanal
  einzeln ziehen. Kein konkreter Fall bisher → bauen, wenn echtes Material auftaucht.
- [ ] **Spurbenennung aus Recorder-Metadaten (iXML/bext) vorschlagen.** Aufwand:
  **mittel**. Field-Recorder schreiben Spurnamen in den **iXML**-Chunk
  (`<TRACK_LIST>`) bzw. eine Beschreibung in **bext**. ⚠️ `ffprobe` parst iXML
  NICHT, exiftool ist nicht gebuendelt. Leichtester Weg OHNE neue Dependency:
  kleiner RIFF-Chunk-Parser in Python (WAV oeffnen, `iXML`-Chunk finden, XML lesen)
  → Vorschlag fuer die Namen auf Seite 1 statt nur Dateiname. Haengt am Punkt darueber.
- [ ] **Kamera-Familie aus Datei-Metadaten ableiten.** Aufwand: **leicht** (Lesen),
  aber **unzuverlaessig**. Befund: DJI schreibt das Modell direkt in `format_tags:
  encoder` (echt getestet: „DJI Mini4 Pro"); GoPro/Sony/Canon legen es teils in
  eigene Atoms/Sidecar-XML (herstellerabhaengig). ⚠️ **Grosser Haken**: Dateien,
  die durch einen NLE/Export liefen, haben die Kamera-Metadaten VERLOREN (die
  FX3-Datei zeigt „DaVinci Resolve" statt Sony). Nur Kamera-**Originale** tragen es
  zuverlaessig → „erkannt/nicht erkannt" muss ehrlich kommuniziert werden.

- [ ] Einzeldateien importieren: Statt nur Ordner, auch einzelne Video-/Audio-Files
  per Drag & Drop oder Finder-Dialog hinzufügen. Für gemischte Quellpfade.
  .multicam müsste dann an zentralem Ort liegen (z.B. ~/Library/Application Support/)
  und bei AAF-Export nach Speicherort fragen.
- [ ] Workflow fortsetzen: Fortschritt in .multicam speichern.
  "Fortsetzen"-Toggle bei erneutem Laden. Dialog ob Dateien geaendert.
- [ ] Refresh-Trigger verfeinern: still im Hintergrund erneuern wenn Lease bald
  abläuft (aktuell erneuert jeder validate()-Call bei App-Start).
- [ ] **Personen-Modell — weitere Stufen.** Stufe 1 (abgeleitetes Modell + Wizard) ist LIVE. Offen: eigenständiger Personenname (heute = Mic-Name), Rollen an der Person, Zuordnung aus der Personen-Sicht, Totale↔Person, sowie die freigeschaltete Cutaway-Art „Bildgrößen-Wechsel am sprechenden Menschen". Volle Historie/Design-Entscheidungen im Archiv (`brain/TODOs-Archiv.md`).
