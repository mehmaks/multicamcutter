# Plan: Umbau auf 3+ Kameras (Sync + Schnitt-Logik)

Designdokument für die große Multicam-Session. Aktuell blockiert ein Wächter
(`unsyncedCams`) den Start bei >2 Kameras — dieser Plan beschreibt, was nötig ist,
um ihn zu entfernen.

**Zwei Teile, klare Reihenfolge:** Ohne korrekten Sync (Teil A) ist jede Schnittlogik
wertlos. Teil B baut darauf auf.

---

# Stand & getroffene Entscheidungen (21.07.)

Der Plan wurde gegen den Code geprüft und ist inhaltlich weiter gültig. Umgesetzt ist
davon **nichts**; erledigt sind nur Vorarbeiten (Personen-Modell, Wizard, `camRoles()`,
`shotLadder()` — alle in Swift).

**Entschieden:**
- **B3 (Abdeckungsregel) gilt.** Der konkurrierende TODO-Entwurf `totale_mode`
  (Zufall/Round-Robin an den `wide_cams[0]`-Stellen) ist damit **verworfen** — er wäre
  Wegwerfarbeit und wählt die Totale ohne Bezug dazu, wer gerade spricht.
- **AAF-als-Eingang gehört NICHT in diesen Plan.** Im TODO stand es als Alternative,
  die den Sync-Umbau ersetzen könnte — das ist falsch gerahmt. Es löst ein anderes
  Problem: GoPro-/DJI-Kameras splitten lange Aufnahmen, und statt die Teile in der App
  zusammenzusetzen, bereitet der User sie im NLE vor und übergibt eine AAF, in der jede
  Videospur ein Clip ist. Eigene Baustelle, eigene Priorität.

**Beim Prüfen zusätzlich gefunden — drei Dinge, die der Plan nicht nennt:**

1. **Die Kern-Invariante lebt nur in Swift.** `camRoles()` (Totale-Regel) und
   `orderedAnalysisCams` (Closes zuerst, Totalen ans Ende) existieren ausschließlich in
   der App (`EngineController.swift:467-484`, `:524-541`). Python vertraut blind auf
   `cam_paths[0]`/`[1]`. Steht dort eine Totale, kippt die Diarisierung — lautlos. Wer
   `run_from_bin.py` direkt aufruft, hat keinerlei Schutz.
2. **Nodding läuft über ALLE Kameras, auch Totalen** (`run_from_bin.py:720-742`), aber
   PASS 2 verwirft deren Ergebnisse grundsätzlich (`add_reactions_to_edl.py:189`).
   Das sind ~30 min Rechenzeit pro Totale, vollständig umsonst.
3. **PASS 2b filtert nicht nach Typ.** Der Kommentar sagt „erste andere **Close**-Kamera",
   der Code prüft nur `cam['name'] != on_clip` (`add_reactions_to_edl.py:552-558`).
   Je nach Reihenfolge landet dort die Totale.

---

# Stufe 0 — Sofortmaßnahmen (unabhängig vom Umbau)

Klein, ohne Abhängigkeit zu Teil A/B, und sie machen stille Fehler laut. Vorziehen.

- [ ] **PASS 2b nach `type` filtern** — Kommentar und Code in Übereinstimmung bringen.
- [ ] **Nodding auf Totalen überspringen** — spart ~30 min je Totale und Lauf. Achtung:
      nur überspringen, wenn die Cam auch wirklich nirgends als Reaktionsquelle dient.
- [ ] **Python-seitiger Abbruch, wenn Position 1 oder 2 eine Totale ist.** Die Engine
      soll die Invariante selbst durchsetzen, statt sich auf den Aufrufer zu verlassen.
      Ein Abbruch mit klarer Meldung ist einer still gekippten Diarisierung vorzuziehen.

---

# Teil A — Sync für N Quellen (Voraussetzung)

## Ist-Zustand (Code-Fakten)

`shared/waveform_sync.py`:
- Signatur fest binär: `sync_sources(cam1, cam2, mic1, fps, additional_mics)`.
- Misst **nur** CAM1↔CAM2 und CAM1↔MIC1.
- Zusatz-Mics **erben** MIC1s Offset (Z. ~206) — ungemessen.
- **CAM1 = Referenz** (Offset 0), alles relativ dazu.
- `_sync_pair` erweitert das Analysefenster in 180-s-Schritten bis
  `MIN_CONFIDENCE = 5.0`, sonst `SyncError`.
- Extrahiert das Referenz-Audio **für jedes Paar neu** (ffmpeg je Paar).

Konsumenten:
- `build_base_edl_from_audio`: `--cam1-edl-frame`, `--cam2-edl-frame`,
  `--wav-edl-frame`, `--totale-edl-frame`.
- `build_aaf.py:258`: `offsets.get(f'CAM{i+1}', 0)` → **stumme 0** für fehlende Cams.

Aufrufer: `multicam_engine.py:825`, `run_from_bin.py:932`, `run_from_folder.py:109`.

## Ziel-Design

1. **Neue Signatur**
   `sync_sources(cam_paths: list[str], mic_paths: list[str], fps, reference=None) -> dict[str,int]`
2. **Jede Quelle einzeln messen** — keine Vererbung mehr (behebt auch getrennte Recorder).
3. **Referenz = Mic-Spur.** Mics sind in der Regel vollständig, sauber und ohne
   Kamera-Ton-Probleme. Kandidatenreihenfolge: längstes Mic zuerst, bei Misserfolg
   nächstes; letzter Fallback eine Cam.
4. **Ausgabe-Kontrakt erhalten:** am Ende alles so normalisieren, dass **CAM1 = 0**
   bleibt (alle Offsets minus dem gemessenen CAM1-Offset). Damit ändert sich für
   EDL/AAF/`_cam_shift` **nichts** — minimales Regressionsrisiko.
5. **Performance:** Audio je Quelle **einmal** extrahieren und wiederverwenden.
   Heute wird die Referenz pro Paar neu dekodiert; bei N+M Quellen wäre das teuer.

## Robustheit (neu)

- **Plausibilitätsgrenze:** |offset| muss kleiner als die kürzere Quelldauer sein.
- **Kreuzprobe:** zusätzlich CAM1↔CAM2 direkt messen und mit der über die Referenz
  abgeleiteten Differenz vergleichen. Weichen sie mehr als eine Toleranz ab →
  Warnung/Abbruch. Fängt eine schlechte Referenz.
- **Confidence ins Protokoll:** pro Quelle als JSON-Lines emittieren, damit die App
  grenzwertige Werte anzeigen kann (heute nur stdout-Text).
- **Fehler benennen:** `SyncError` sagt, **welche** Quelle unsicher war.

## Bewusste Verhaltensänderung

Bisher „liefen" 3-Cam-Setups durch, weil Cam 3 still auf 0 gesetzt wurde. Künftig wird
gemessen — bei unsicherer Korrelation **bricht der Lauf ab**. Das ist richtig (stumm
falsch schneiden ist schlimmer), muss aber kommuniziert werden.

## Verifikation — auch ohne echtes Material möglich

1. **Synthetik-Test:** zwei Signale mit bekanntem Versatz erzeugen (numpy → wav),
   `sync_sources` drauf; Offset muss auf ±1 Frame stimmen. Deckt Vorzeichen,
   Sample→Frame-Skalierung und die CAM1-Normalisierung ab.
2. **Regression:** alt vs. neu auf einem echten 2-Cam-Set → Offsets müssen **identisch**
   sein.
3. Echtes 3-Cam-Material erst danach.

---

# Teil B — Schnitt-Logik: wann Close, wann Totale

## Ist-Zustand

**Diarisierung ist cam-basiert binär**, nicht personenbasiert:
- `rms_diarize(audio_cam1, audio_cam2)` vergleicht die RMS zweier Gruppen.
- `--mic-cam1/--mic-cam2` sind `nargs='+'` → alle Mics einer Cam werden per
  `combine_audios()` **gemischt**. **Deshalb funktionieren 3 Personen auf 2 Cams.**
- Dominanz: `diff > threshold_db` → CAM1, `< -threshold_db` → CAM2, beide leise → None,
  danach Change-Delay-Glättung.

**Die Totale entsteht an drei Stellen:**
1. `detect_simultaneous_speech()` + `insert_totale_events()` — beide Gruppen aktiv,
   Differenz < Schwelle → Totale (`totale_simul_dur`, Default 3 s).
2. Reaktionen: `_is_multi_person(frame) and wide_cams` → Totale statt Close
   (`add_reactions_to_edl.py:265`).
3. PASS 4 Reset bei zu langem Shot: `reset_cam = wide_cams[0]` (:332).

**Es gibt nur EINE Totale:** `totale_idx = next(i for i,t in enumerate(cam_types) if t=='wide')`
(`run_from_bin.py:659`) — schlicht die erste `wide`-Cam.

Rollen kommen als `--cam-types` (close/wide); die App leitet sie über „Close gewinnt" ab.

## Kernproblem

Binär auf **allen** Ebenen: Diarisierung (2 Gruppen), Simultan-Erkennung (2 Gruppen),
Totale (genau eine).

## Ziel-Design

### B1 — N-way Diarisierung
`rms_diarize_n(audios: list[np.ndarray], ...)`:
- RMS je Cam-Gruppe (Mischung pro Cam bleibt wie heute).
- **Dominant = argmax, aber nur wenn der Abstand zum Zweitplatzierten > `threshold_db`**
  — sonst „keine klare Dominanz".
- Silence-Gate: alle Gruppen unter Schwelle → None.
- Change-Delay/`min_edit`-Glättung arbeitet auf einer Label-Sequenz → für N Labels
  unverändert nutzbar.
- ⚠️ **Rückwärtskompatibilität:** bei N=2 muss das Ergebnis **identisch** zur heutigen
  Funktion sein (Regressionstest).

### B2 — Simultan-Erkennung generalisieren
- Heute: beide aktiv **und** Differenz < Schwelle.
- N: **≥2 Gruppen aktiv** und Abstand Platz 1 → Platz 2 < Schwelle.
- Zusätzlich merken, **welche** Sprecher beteiligt sind (Input für die Totale-Wahl).

### B3 — Der eigentliche Hebel: Auswahl über Personen-Abdeckung statt close/wide-Flag

Die App weiß, welche Personen jede Cam zeigt; die Engine bekommt es implizit über
`--cam-mics`. Damit lässt sich **jede** Auswahl einheitlich formulieren:

> **Regel:** Für eine gewünschte Personenmenge P wähle die Cam mit der **kleinsten**
> Personenmenge, die P vollständig enthält. Existiert keine, nimm die Cam mit der
> größten Überdeckung von P.

Alles Bisherige fällt als Spezialfall heraus:
- **Ein dominanter Sprecher** → kleinste Cam, die ihn zeigt = seine Close.
  („Close gewinnt" ergibt sich automatisch.)
- **Mehrere gleichzeitig** → kleinste Cam, die alle zeigt = die passende Totale.
  Bei mehreren Totalen wird die **engste passende** gewählt statt „die erste wide".
- **Reaktion mehrerer Personen** → dito.
- **Reset-Schnitt (PASS 4)** → Cam mit größter Abdeckung, oder bewusst eine andere
  Close als Abwechslung.

`close`/`wide` wird damit ein **abgeleitetes Anzeige-Label**, kein Steuerparameter mehr.

### B4 — Mehrere Totalen  ✅ Entwurf entschieden (21.07.): fällt aus B3 ab,
`totale_mode` aus der TODO-Liste ist verworfen
Fällt mit B3 automatisch ab: `totale_idx` entfällt; `insert_totale_events` bekommt pro
Simultan-Segment die passende Cam statt einer global fixen.

## Was das an Schnittstellen kostet

- `build_base_edl_from_audio.py` — **invasivster Teil**: `--mic-cam1/--mic-cam2` →
  N Gruppen (z. B. `--cam-mics` als JSON), `--cam1/2-video/clip/edl-frame` → Listen.
  `--totale-*` entfällt zugunsten der Abdeckungsregel.
- `add_reactions_to_edl.py`: `wide_cams[0]` → Abdeckungs-Auswahl.
  ⚠️ **PASS-Reihenfolge NICHT ändern** (Guardrail in `modules/multicam_cutter/CLAUDE.md`).
- App: `--cam-types` kann als Anzeige bleiben; die Auswahl-Logik wandert in die Engine.

## Reihenfolge

1. **Teil A (Sync)** — Voraussetzung.
2. **B1/B2 (N-way Diarisierung)** mit Regressionstest N=2.
3. **B3/B4 (Abdeckungs-Auswahl)**.
4. Wächter `unsyncedCams` + `UnsyncedCamsBanner` entfernen.

## Verifikation

- **Synthetik:** 3 Signale mit bekannten Sprech-Abschnitten erzeugen →
  `rms_diarize_n` muss die richtigen Labels liefern. Ohne echtes Material machbar.
- **Regression N=2:** alte vs. neue Diarisierung auf realem 2-Cam-Set → identische
  Base-EDL.
- Echtes 3-Cam-Material zum Schluss.

## Offene Produktfragen (in der Session zu klären)

- Soll die Totale auch **ohne** Simultan-Sprechen als Rhythmus-Mittel dienen?
- Cooldown: wie oft darf hintereinander auf dieselbe Totale geschnitten werden?
- Mehrere gleichwertige Cams: feste Priorität oder Abwechslung?
- Darf eine Person **mehrere** Close-Cams haben (zwei Winkel)? Dann braucht die
  Abdeckungsregel ein Tie-Break-Kriterium.
