# Pipeline-Referenz — wie die Analyse wirklich arbeitet

Detaillierte Referenz aller Analyse-Stufen: Logik, Parameter, Schwachstellen.
Gedacht als Grundstein, um einzelne Pässe gezielt zu verbessern.

**Entstehung:** aus dem Code erhoben (Stand 20.07.2026), alle ~4.500 Zeilen der fünf
Module gelesen. Zeilennummern als Beleg. Wo etwas aus dem Code nicht entscheidbar war,
steht ausdrücklich **unklar** — lieber eine ehrliche Lücke als eine plausible Erfindung.

`Pipeline-Schritte.md` bleibt die knappe Landkarte; hier steht die Tiefe.

---

## Signalfluss

```
1. waveform_sync.sync_sources        → offsets {label: frames}
2. build_base_edl_from_audio         → base.edl (+ speaking-reactions, pauses, cutaway-json)
3. video_reaction_analyzer_v2.4      → <cam>_reactions.json   (je Kamera)
4. add_reactions_to_edl  PASS 1–5    → final.edl (+ .colors.json)
5. pause_trim_edl.apply_pauses…      → getrimmte Events + audio_keeps
6. build_aaf / build_cut_timeline    → AAF bzw. Resolve-Timeline
```

---

## Stufe 1 — Waveform-Sync (`shared/waveform_sync.py`)

**Logik:** ffmpeg extrahiert Mono @ 8 kHz (`:33-43`). Beide Signale werden nur auf
Einheitsvarianz skaliert (`:66-68`), dann FFT-Kreuzkorrelation (`:70`).
`offset_samples = peak_idx - (len(target)-1)` (`:77`), positiv = target startet später.

**Confidence:** `peak / median(|corr|)` (`:73`). Schwelle `MIN_CONFIDENCE = 5.0` (`:23`).
Bei Unterschreitung wächst das Fenster in 180-s-Schritten (`:21-22, :158`), bis die
Materiallänge überschritten ist → `SyncError`.

**Konstanten:** `SAMPLE_RATE 8000`, `CHUNK_SECONDS/STEP 180`, `MIN_CONFIDENCE 5.0` (`:20-23`).

### Schwachstellen
- **Rohe Wellenform statt Hüllkurve** (`:70`). Kamera-Onboardmikro vs. Lavalier sind sich
  im Rohsignal kaum ähnlich, selbst bei perfektem Sync. **Größter Hebel:** spektrale
  Hüllkurve / Onset-Envelope korrelieren statt PCM.
- **Kein DC-Abzug** (`:67-68`): nur `/std`, kein `-mean`. Ein DC-Offset erzeugt einen
  Dreiecksverlauf mit Maximum bei Lag 0 → zieht das Ergebnis Richtung 0.
- **Confidence ist nicht fenstergrößen-invariant** (unnormierte Korrelation). Ein größeres
  Fenster kann die Confidence *verschlechtern* — die Erweiterungsstrategie ist damit nicht
  garantiert zielführend. Besser: normierte Korrelation + Peak-zu-Zweitpeak statt Peak-zu-Median.
- **Confidence wird verworfen** (`:173`): `sync_sources` gibt nur `{label: frames}` zurück.
  Niemand erfährt, ob 5,1× oder 200×. Genau der dokumentierte Gotcha („5–50× werden
  akzeptiert, sind aber unsicher").
- **Kein Drift-Modell**: ein Offset aus den ersten 180 s gilt für die ganze Aufnahme.
  Bei 50 ppm Clock-Drift sind das nach 1 h ≈ 4,5 Frames.
- **Zusatz-Mics ungeprüft** (`:203-207`): erben MIC1s Offset.
- Jede Iteration dekodiert **von vorne neu** (`:119-120`); CAM1 wird zweimal dekodiert.

> Ausführlicher Umbauplan inkl. N-Kamera-Problem: `Plan-Multicam-3plus.md`.

---

## Stufe 2 — Base-EDL (`build_base_edl_from_audio.py`)

### ⚠️ Zwei Audio-Arrays — Grundlage für das Verständnis der ganzen Stufe

| Array | Entsteht durch | Benutzt von |
|---|---|---|
| `audio_cam1/2` | Stage-A-Norm (`:905-906`) | K-Means-Schwellen (`:936-937`), On-Speaker-Pausen, Speaking-Reactions |
| `_analysis1/2` | Stage A + Gate + Stage-B-Norm (`:993-994`) | Diarisierung, Simultan, Pausen, Pause-Cutaways |

### 2a. RMS-Diarisierung (`rms_diarize`, `:67-165`)
`diff = rms1 - rms2`; `> threshold_db` → CAM1, `< -threshold_db` → CAM2, dazwischen `None`
(`:85-88`). Bei Default 6.0 ist die **Totzone 12 dB breit**. Silence-Gate ist **UND**-verknüpft
(`:92-93`) — greift nur, wenn *beide* Mics leise sind.

**Change-Delay-Glättung** (`:99-116`): Ein Wechsel braucht `delay_wins` (Default 6 = 300 ms)
**lückenlos** eindeutige Fenster. `raw is None` **setzt den Zähler zurück** (`:103-104`).
Der bestätigte Wechsel wird **rückwirkend** auf den Streak-Beginn datiert (`:114-115`) —
der Schnitt liegt also am echten Sprech-Onset, nicht 300 ms später. Das ist korrekt.

**Min-Edit-Merge** (`:127-147`) iterativ; `None`-Segmente werden nie gemergt und erst in
`:150-153` aufgelöst — nach hinten propagierend, d. h. **Stille fällt dem vorherigen
Sprecher zu**.

**Parameter:** `--min-edit-duration 1.0` (`:758`), `--change-delay 0.3` (`:759`),
`--threshold-db 6.0` (`:760`), `--analysis-window 0.05` (`:761`).
Silence-Gates kommen aus K-Means minus hartkodierte **15 dB** (`:1026-1027`).

### 2b. Crossbleed-Gate (`rms_gate`, `:168-262`)
Zustandsautomat MIC1/MIC2/BOTH (`:200-221`), 50 % Overlap (`:182`), Gain-Glättung über
`alpha = 1 - exp(-2.2/n)` (`:231-232`), lineare Interpolation aufs Sample-Raster (`:248-251`).
Im BOTH-Zustand wird **nicht** gedämpft.

**Parameter:** `--gate-window 80`, `--gate-attack 15`, `--gate-release 80`,
`--gate-floor -25`, `--gate-hysteresis 2.0`, `--gate-both-threshold 3.0` (`:766-777`).

### 2c. Pegel-Normalisierung — zwei kumulative Stufen
- **Stage A** (`:893-922`): gleicht den **Median** beider Kanäle symmetrisch an.
- **Stage B** (`:969-998`): gleicht den Energie-Mittelwert der „aktiven" Fenster an.

### 2d. Sprach-Cutaways (`_bursts_rolling`, `:358-496`)
Detektiert **nicht** Pegel-über-Baseline, sondern die **Anstiegsrate der Baseline**
(`rise[k] = baseline[k] - baseline[k-lookback]`, `:432-433`). Burst startet bei
`rise >= rise_db`, endet bei Abfall unter `peak - sustain_margin` oder `max_duration`.

**Parameter:** `--speaking-rise-db 6.0`, `--speaking-min-duration 0.20`,
`--speaking-max-duration 2.5`, `--speaking-attack-window 0.2`,
`--speaking-release-window 20.0`, `--speaking-warmup 3.0`, `--speaking-mode peak` (`:790-797`).
Fensterbreite ist `--analysis-window` = **0,05 s** (`run_from_bin` überschreibt es nicht).
Analysiert wird das **un-gegatete** `audio_cam1/2` (`:1247`) — bewusst, das Gate würde
genau dieses Signal zerstören. Kreuzweise: CAM1 spricht → Bursts auf MIC2 = CAM2-Reaktionen.
Baseline wird **pro Diarization-Segment** zurückgesetzt (`:546`).

**Der Crossbleed-Rückkehr-FP (empirisch belegt, 2026-07-20).** Macht der aktive Sprecher
eine Pause, bricht das Crossbleed auf dem Off-Mic weg, die Baseline sackt ab; beim
Weitersprechen kehrt der Pegel zurück und erzeugt einen Rise **ohne jede Reaktion**.
Simulation mit Produktions-Defaults (Crossbleed −25 dBFS):

| Pause | Rise | Baseline-Sag | Falscher Burst? |
|---|---|---|---|
| 1,0 s | 4,2 dB | 2,9 dB | nein |
| **2,0 s** | **7,8 dB** | 5,6 dB | **JA** |
| 3,0 s | 10,9 dB | 8,0 dB | JA |
| 8,0 s | 20,9 dB | 15,5 dB | JA |

`no_burst_decay_factor = 3.0` verschärft das: die Baseline fällt dreimal schneller,
solange kein Burst läuft — also genau während der Pause.

**Der Freeze funktioniert** (`:409-412`): mit korrekt gesetzter Maske 0 Bursts bei
jeder getesteten Pausenlänge. Er ist aber **binär** (verlangt `< quiet_speech + 3 dB`
auf dem On-Mic, min 0,3 s zusammenhängend), während das Phänomen stufenlos ist.
Gemessene Blindzone — Teilabfälle, die keinen Freeze auslösen, aber trotzdem kippen:

| Abfall | 3 s | 5 s | 8 s |
|---|---|---|---|
| 9 dB | – | – | **FP** |
| 12 dB | – | **FP** | **FP** |
| 20 dB | **FP** | **FP** | **FP** |

**Hebel:** Recovery-Detektor statt Stille-Erkennung — ist die Baseline zuvor um
etwa denselben Betrag gefallen wie sie jetzt steigt, ist es Rückkehr, keine Reaktion.
Symmetrisch, braucht das andere Mikrofon nicht, greift auch in der Blindzone.

**Weitere Eigenheiten:**
- Segmente **kürzer als `warmup_s` (3 s) werden komplett übersprungen** (`:567`) —
  schneller Schlagabtausch erzeugt gar keine Reaktionen.
- Baseline startet auf dem **75. Perzentil der ersten 3 s** des Segments; Reaktionen
  ganz am Segmentanfang sind darin schon eingerechnet und erzeugen keinen Rise mehr.
- **Kein Konfidenz-Filter:** `add_reactions_to_edl.py:197` nimmt `speaking_reaction`
  explizit vom `min_confidence`-Check aus. `conf` wirkt nur als Sortier-Tiebreak.
- **`dur_s` wird nie gelesen.** Die Cutaway-Länge kommt aus `reaction_duration`
  (`add_reactions_to_edl.py:304-313`), nicht aus der Burst-Dauer. Der UI-Slider
  „Max. Cutaway-Dauer" setzt `--speaking-max-duration`, also die maximale **Burst**-Länge.
  Falsch beschriftet.

**Diagnose:** Im Dev-Modus schreibt der Lauf `speaking_debug.json` mit Pegel-, Baseline-,
Rise- und Freeze-Verlauf pro Segment → siehe `Dateiformate.md`.

### 2e. Simultan-Erkennung + Totale (`:612-642`, `:660-715`)
```
both_active  = (rms1 > -50) & (rms2 > -50)      # :627, NOISE_FLOOR hartkodiert
simultaneous = both_active & (|rms1-rms2| < threshold_db)   # :628
```
Zusammenhängende Runs `>= totale_simul_min_duration` (Default 3.0 s) werden zur Totale.

> ⚠️ **Dieser Pfad ist aus der Mac-App heraus scharf**, auch wenn er nie bewusst
> gebaut/getestet wurde. Kette: `EngineController:1516` (`--cam-types`) →
> `multicam_engine:838` (`_parse_cam_list`) → `run_from_bin:659`
> (`totale_idx = erste Cam mit type == 'wide'`) → `--totale-video`/`--totale-clip` →
> `build_base_edl_from_audio:1140` (`if args.totale_clip and args.totale_video:`).
> Sobald `camRoles()` eine Kamera als `wide` einstuft, laufen Simultan-Erkennung und
> `insert_totale_events` mit. Dass in der Praxis nie Totale-Schnitte auftauchen, ist
> vermutlich **kein** fehlendes Feature, sondern die 60-Fenster-Strenge unten.

### 2f. EDL-Erzeugung (`:1036-1121`)
```
edl_frame       = round(seg_s * fps) + wav_edl_frame
video_frame     = timeline_zero_video + edl_frame
source_tc_frame = reference_frame + video_frame        # absoluter Tageszeit-TC
```
`_cam_shift = max(0, -min(cam1_edl_frame, cam2_edl_frame))` (`:855`) schiebt die früheste
Kamera auf 0 — **ohne** die Totale zu berücksichtigen.

### Schwachstellen Stufe 2
- **🔴 Schwellen-Drift** (`:936-937` vs. `:1026, :1216, :1284`): K-Means-Schwellen werden auf
  `audio_cam1/2` berechnet, aber auf `_analysis1/2` angewendet — dazwischen verschiebt Stage B
  den Pegel. Je größer die Korrektur, desto falscher werden Silence-Gate, Pausenerkennung und
  Pause-Cutaway-Schwellen. **Betrifft alles Nachgelagerte.**
- **🔴 Stage A normalisiert vermutlich das Falsche**: Der Median über die Gesamtaufnahme liegt
  bei zwei Sprechern im **Rausch-/Übersprechbereich**, nicht im Sprachbereich — entgegen der
  im Kommentar (`:894`) erklärten Absicht. Hebel: Perzentil der lauten Fenster statt Median.
- **🔴 Simultan-Erkennung ohne jede Glättung** (`:631-640`): Bei Default müssen **60 lückenlose
  50-ms-Fenster** erfüllt sein; ein Verschlusslaut bricht den Run. Sehr plausible Erklärung
  für selten ausgelöste Totale-Schnitte. Hebel: morphologisches Closing + Merge benachbarter
  Segmente. Zudem ist `threshold_db` **derselbe** wie in der Diarisierung — Simultansprechen
  ist per Definition deren Totzone, beides nicht unabhängig tunebar.
- **Timeline-Loch bei nicht gestarteter Totale** (`:700-710`): `cursor = simul_end` läuft auch,
  wenn kein Totale-Event eingefügt wurde.
- **Fallback-Verkettung CAM1↔CAM2** (`:1044-1085`): Beide Blöcke laufen in derselben Iteration;
  ein Segment kann hin- und zurückkippen, ohne dass `edl_start` mitgeführt wird → Loch.
- **Einheiten-Mismatch** (`:977`): `gate_floor + 5` vergleicht eine **relative Dämpfung** mit
  **absoluten dBFS**. Wer `--gate-floor` verstellt, verschiebt unbeabsichtigt die
  Aktivitätsschwelle der Normalisierung.
- **Change-Delay-Streak bricht bei `None`** (`:103-104`) — bei Crossbleed schwer erreichbar.
- **Gate-Hysterese deckelt Both-Threshold** (`:206-215`): `hysteresis 2.0 < both 3.0` macht
  den Bereich 2–3 dB für BOTH unerreichbar. Ob beabsichtigt: **unklar**.
- **`warmup_s` blendet kurze Segmente aus** (`:567-568`): Segmente < 3 s bekommen **keine**
  Speaking-Reactions — bei schnellem Dialog der Großteil.

---

## Stufe 3 — Nodding-Detektor (`video_reaction_analyzer_v2.4.py`)

**Frames:** ffmpeg-Pipe, `-vf` = optional `lut3d` + optional `scale` auf `analysis_width`
(Default 1280), rawvideo bgr24 (`:795-811`). **Jeder** dekodierte Frame wird analysiert.
`stderr=DEVNULL` (`:924, :981`) — ffmpeg-Fehler sind unsichtbar.

**MediaPipe:** FaceLandmarker, `num_faces` Default 1, alle drei Confidences hartkodiert 0.5
(`:98-105`).

### Das Nick-Signal ist die rohe y-Pixelkoordinate der Nasenspitze
`nose_y = landmarks[1].y * height` (`:443`). **Kein Pitch**, keine Rotationsmatrix — obwohl
das Tasks-Modell `facial_transformation_matrixes` liefern könnte.

**Aber: Tilt und Yaw sind sehr wohl berücksichtigt** — im X-Drift-Check (`:231-252`), mit
explizit dokumentierter Geometrie:
```python
# 1) Tilt: Kopf seitlich geneigt → Nicken hat X-Anteil = y * |tan(tilt)|
# 2) Yaw:  Kopf zur Seite gedreht (Halbprofil) → Nicken erzeugt
#    Bogen-Projektion mit X-Anteil proportional zur Drehung
expected_x_total = y_range * |tan(median_tilt)| + y_range * yaw_dev * 1.2
corrected_x      = max(0, x_range - expected_x_total)
FAIL wenn corrected_x >= x_drift_ratio * y_range**0.7
```
`head_tilt` (`:451-455`) ist Roll, `head_yaw` (`:457-467`) die Kopfdrehung; beide gehen
ausschließlich hier ein.

⚠️ **Die entscheidende Feinheit:** Diese Korrektur wirkt auf den **Verwerfungsfilter** — sie
*toleriert* die geometrisch erwartete X-Bewegung. Sie korrigiert **nicht das Signal selbst**.
Die Amplitude wird weiterhin als rohes `y_range` gemessen. Bei starker Schrägstellung oder
Halbprofil wandert ein Teil der Nickbewegung in die X-Achse und fehlt in `y_range` → das
Amplituden-Gate (`osc_y_range < effective_thr`, `:347`) wird **schwerer** passierbar, obwohl
genickt wurde. **Hebel:** die Bewegung auf die erwartete Nickachse projizieren (um `tilt`
rotieren) statt die rohe y-Komponente zu nehmen — dann profitiert auch die Amplitudenmessung
von der bereits vorhandenen Geometrie.

Davon abgesehen ist das Signal nicht translations- oder distanzinvariant. Kompensiert
wird das ausschließlich über die Schwelle:
```
thr = nod_threshold * (height / calibration_height) * clamp(face_h / auto_accuracy_ref, 0.3, 2.0)
```
(`:485-490`, dupliziert in `:519-524`.)

**Pattern-Prüfung** (`_check_nod_pattern`, `:210-405`): Fenster → X-Drift-Check → Glättung →
Reversals zählen → Frequenz-, Damping-, Amplitudenverhältnis-, Korrelationsfilter →
Amplituden-Gate. Danach **Delayed-Fire-State-Machine** mit `settle_s` (`:430-560`).

**Globals** (`config/nodding_patterns.json`): `nod_threshold 45`, `cooldown_s 3.0`,
`settle_s 3.0`, `auto_accuracy_ref 0.31`, `analysis_width 1280`, `smooth_kernel 3`,
`calibration_height 2160`.

**Confidence** = gewichtete Summe aus `reversals, frequency, damping, correlation, amplitude`,
mal `multiplier`, gekappt auf `max` (`:379-398`).

### Schwachstellen Stufe 3
- **🔴 Crash: alle Muster deaktiviert** (`:127`): `max()` auf leerer Sequenz → `ValueError`
  beim Detektor-Init. **Mit den Pattern-Toggles pro Preset ist das drei Klicks entfernt.**
- **🔴 `amplitude_factor` wirkungslos bei 2 von 3 Mustern** (`:337-345`): Zeile 345 rechnet mit
  `thr` statt `effective_thr` und überschreibt damit Zeile 338. Nur `strong_oscillation`
  (ohne `dynamic_threshold`) nutzt seinen Faktor.
- **🔴 `dynamic_threshold` ist faktisch statisch** (`:342-345`): `pattern_revs` hat
  konstruktionsbedingt **immer genau `min_reversals`** Elemente (`:276`) → der „adaptive"
  Term ist eine Konstante. Übrig bleibt ein fester Multiplikator um 0,8.
- **`min_damping` ist bei `min_reversals=2` ein Binärschalter** (`:315-327`): `damping_ratio`
  kann nur 0.0 oder 1.0 sein. Jeder Wert in (0,1] verhält sich identisch.
- **Der Korrelationsfilter ist nahezu degeneriert** (`:279-289`): Er korreliert Nasenspitze
  (LM 1) gegen Nasenrücken (LM 6) — **zwei Punkte auf derselben starren Nase**, vom selben
  Face-Transform getrieben. Korreliert auch bei Kamerawackeln oder Vorlehnen ≈ 1.0. Filtert
  praktisch nur MediaPipe-Aussetzer, **nicht** Nicken vs. Translation.
- **Nur horizontaler Global-Motion-Filter** (`:239-252`): Reine Vertikalbewegung (Kamera-Tilt,
  Hinsetzen, federnder Stuhl) besteht den Check trivial.
- **Detektion auf Bruchteil-Fenstern** (`:469`): Nach jedem Buffer-Clear reichen 15 Frames, um
  ein 50–62-Frame-Muster zu bewerten. Zwei Rauschumkehrpunkte genügen dann.
- **`settle_s` (3,0 s) > längstes `window_s` (2,5 s)**: Der Buffer (62 Frames) enthält nach
  ~62 Settle-Frames **kein Sample des ursprünglichen Nickens** mehr — die „stärkere Detection
  gewinnt"-Logik bewertet dann eine andere Bewegung.
- **Effektiver Mindestabstand ≠ `cooldown_s`**: real ~6 s statt 3 s (Fire-Zeitpunkt +
  Buffer-Clear + Fensteraufbau).
- **Tote Filter**: `max_reversals`, `return_to_baseline`, `max_v_duration_s` sind in allen
  Mustern `null`; der `return_to_baseline`-Score steht in keinem `weights`-Dict.
- **`head_shake`** (`:562-580`) hat weder Cooldown noch Oszillationsprüfung — reine
  horizontale Verschiebung über 30 Frames. Wird per Default nicht geschnitten.

---

## Stufe 4 — `add_reactions_to_edl.py` (PASS 1–5)

**Zentrale Invariante:** `source_tc_frame = ref + (tzvf + timeline_frame)` (`:107-151`).

### PASS 1 — Parsen + Referenzframes (`:74-151`)
Regex nur auf `V`/`C`-Zeilen; `* FROM CLIP NAME:` **muss** in Zeile i+1 stehen (`:87`), sonst
wird das Event **stillschweigend verworfen**.

### PASS 2 — Reaction-Cutaways (`:154-410`)
Reaktionen nur von **Close-Cams** (`:188`), gefiltert über `cutaway_enabled`, `min_confidence`,
Section-Grenzen. Cluster rückwärts suchen (`:240-247`), Cutaway bei
`cluster_start - pre_roll`. Ziel-Cam: bei Multi-Person `wide_cams[0]`, sonst die
Reaktions-Cam (`:265-270`).

**Parameter:** `min_shot 2.0`, `reaction_dur 3.0`, `max_shot 30.0`, `min_conf 0.86`,
`cluster_max_gap_frames 75`, `pre_roll 0`, `randomness 0.0` (`:1111-1119`).

### PASS 2b — Pause-Cutaways (`:479-644`)
Ersetzt ein Host-Event durch drei (ON / OFF / ON). **Speaker→Clip ist hart auf die ersten
zwei Kameras verdrahtet** (`:501-506`) — bricht die N-Kamera-Architektur.

### PASS 3 — Cleanup kurzer Events (`:435-476`)
Events unter `cleanup_dur` werden entfernt und der **Vorgänger verlängert** (`:452-457`).
Geschützt sind Sprecherwechsel-Sandwiches (`_is_diarization_switch`, `:413-432`).

### PASS 4 — Split zu langer Shots (`:647-796`)
Schwelle `max_shot + 3.0 s` (`:660`). Multi-Split:
`n = max(1, ceil((duration - threshold) / (threshold + cutaway)))` (`:713`).
Skip-Heuristik bei Sprecherwechsel, wenn `duration <= threshold * 1.2` (`:722`).

### PASS 5 — CLIP-Ignore-Filter (`:866-1082`)
Score = **Softmax-Wahrscheinlichkeitsmasse auf den Ignore-Prompts**, maximiert über zwei
Sample-Frames (`:851-863`). Bei `score >= threshold` wird in der Sequenz
**+2s, −2s, +4s, −4s, +6s** verschoben (`:986-988`).

**Parameter:** `clip_ignore_threshold 0.5`, `clip_shift_step_s 2.0`, `clip_max_attempts 5`
(`:1132-1134`).

### Schwachstellen Stufe 4
- **🔴 Timeline-Loch in PASS 2** (`:385-397`): Scheitert der Max-Time-Cutaway an einer noch
  nicht gestarteten Off-Cam, wird `current_pos` weitergesetzt, **ohne** Speaker-Event für den
  Rest. Betrifft genau den Timeline-Anfang.
- **🔴 PASS 5 kann Nachbarn auf 1 Frame stauchen** (`:995, :1002`): Die Grenzen sind `±1`
  Frame, kein `min_shot`-Guard — und PASS 3 ist längst gelaufen. Wahrscheinlichster Weg zu
  Flackerschnitten. **Nach PASS 5 läuft kein Cleanup mehr.**
- **🔴 `cleanup_dur` steuert zwei unabhängige Dinge**: die PASS-3-Löschschwelle (`:439`) **und**
  die Länge **aller** PASS-4-Cutaways (`:1279`).
- **`speaking_min_confidence` ist wirkungslos** (`:177` gelesen, nie angewendet);
  `speaking_reaction` umgeht jede Confidence-Prüfung (`:197`).
- **PASS 4 gibt bei fehlender Wide-Referenz komplett auf** (`:704-707`) statt auf eine
  Close-Cam zurückzufallen.
- **Cluster-Walk ignoriert die Kamera** (`:241-247`) → Cutaway-Zeitpunkt kann von einer
  anderen Cam stammen als die Ziel-Cam.
- **`random` nie geseedet** (`:310-312`); Randomness verlängert nur, verkürzt nie.
- **Zwei Max-Time-Mechanismen** mit verschiedenen Schwellen *und* Cutaway-Längen
  (PASS 2 intern vs. PASS 4).
- **`write_edl` ohne `encoding='utf-8'`** (`:808`), Reel immer `AX`, keine Ausgabe-Validierung.
- **PASS 3 → PASS 4**: verlängerte Vorgänger können die Split-Schwelle überschreiten.
- **PASS 2 → PASS 3**: auf `section_end` geklemmte Cutaways werden von PASS 3 sofort gelöscht.

---

## Stufe 5 — Pause-Trim (`pause_trim_edl.py`)

**Zwei Phasen:** Detection läuft in Stufe 2 (`detect_pauses`, `:117-186`, nur an
Sprecherwechseln), Application danach (`apply_pauses_to_cut_events`, `:202-423`).

### Die vier Schnittmodi (`:286-300`)
Pause `[ps,pe]`, `M = max_pause_frames`. Entfernt wird `[p1_end, p2_start]`:

| Modus | p1_end | p2_start | Der Zuschauer sieht |
|---|---|---|---|
| `middle` | `ps + M//2` | `pe - (M - M//2)` | Stille je zur Hälfte vor/nach dem Cut |
| `l-cut` | `ps` | `pe - M` | Cut am Pausen**anfang** — man sieht den neuen Sprecher schweigen |
| `j-cut` | `ps + M` | `pe` | Cut am Pausen**ende** — man bleibt auf dem alten Sprecher |
| `random` | — | — | pro Pause zufällig, **ohne Seed** (`:290`) |

**Wo ist das Audio?** Exakt an denselben Frames wie das Video — es gibt keine separate
Audio-Schnittposition. Die entfernte Region liegt in allen Modi vollständig in der Stille und
hat dieselbe Länge; nur ihre *Position* wandert. Deshalb klingt es identisch, nur das Bild
wechselt anderswo.

> ⚠️ **Doku-Widerspruch:** `config/schemas/multicam_params.json:108` behauptet „Audio ist immer
> Middle-Cut." Das tut der Code **nicht**. Ob der Text veraltet ist oder eine unerfüllte
> Absicht beschreibt: **unklar**.

### Audio-Keeps — wie der dokumentierte Bugfix funktioniert (`:373-387`)
Drei Bausteine, die die Sync-Garantie tragen:
1. **Keine unabhängige Berechnung** — `orig_in/out` kommen 1:1 aus den bereits getrimmten
   Video-Events. Egal wie stark die Caps den Trim beschnitten haben, das Audio erbt das Ergebnis.
2. **Derselbe Cursor** wie die spätere Kompaktierung (`:387` vs. `:390-395`).
3. **Reihenfolge**: Der Block steht **vor** der Kompaktierung — danach wären die
   Original-Koordinaten verloren.

Da Trims immer paarweise auf `source_*` **und** `record_*` wirken (`:325-326, :342-343`),
bleibt `record_dur == source_dur` erhalten.

**Parameter:** `max_pause_s 1.0`, `cut_mode 'middle'`, `min_event_s 0.0` (`:203-205`);
Detection: `silence_db -40.0`, `search_radius_s 3.0`, `min_pause_s 0.3`, `window_s 0.02`.

### Schwachstellen Stufe 5
- **Überlappende Audio-Keeps sind erreichbar** — und der SYNC-CHECK ist dafür blind: Er
  vergleicht nur **Summen** (`:410-413`), bei Überlappung ist `Diff = 0`. Ob der Pfad in realen
  Daten auftritt: **unklar**, aus dem Code aber erreichbar.
- **Negative Trims sind nicht gecappt** (`:325, :342`): können `source_out` über die Cliplänge
  und `source_in` unter 0 treiben → das dokumentierte „Standbild + leere Audiospur"-Schadensbild.
- **`min_event_s` Default `0.0`** (`:205`) — fail-open. Der Sequencer-Pfad reicht ihn nicht
  durch, dort ist der Flacker-Fix wirkungslos.
- **Cutaway-Schutz kann still ausfallen**: Stimmt die Anzahl in `.colors.json` nicht, wird sie
  verworfen → `cutaway_spans` leer → Pause-Trims schneiden ungebremst durch Cutaways.
- **`find_boundary` nimmt die erste, nicht die nächste Grenze** (`:243-247`, Set-Iteration).
- **Pausen-Auswahl über Mittelpunktsdistanz** (`:89-98`) statt Enthaltensein: Eine lange Pause,
  die die Grenze enthält, kann gegen eine kürzere danebenliegende verlieren.
- **Identitätsvergleich `is`** (`:240, :361`) als undokumentierter API-Vertrag.

---

## Querschnitt: Parameter, die nicht tun, was sie versprechen

| Parameter | Status | Fundstelle |
|---|---|---|
| `speaking_min_confidence` | gelesen, nie angewendet | `add_reactions:177` |
| `--speaking-hold` | durchgereicht, nie gelesen | `base_edl:796, :364` |
| `--max-pause`, `--pause-cut-mode` | an base_edl übergeben, dort ungenutzt | `base_edl:819, :827` |
| `amplitude_factor` | bei 2 von 3 Mustern überschrieben | `varz:337-345` |
| `dynamic_threshold` | faktisch konstanter Faktor | `varz:342-345` |
| `max_reversals`, `return_to_baseline`, `max_v_duration_s` | in allen Mustern `null` | `nodding_patterns.json` |
| `--analysis-window` | von keinem Aufrufer gesetzt (immer 0.05) | `base_edl:761` |
| `sensitivity` | beeinflusst nur noch `laughing` | `varz:131-139` |
| `min_damping` | Binärschalter bei `min_reversals=2` | `varz:315-327` |

## Querschnitt: Stellen, an denen Löcher in der Timeline entstehen

1. `base_edl:700-710` — Totale noch nicht gestartet
2. `base_edl:1044-1085` — Fallback-Verkettung CAM1↔CAM2
3. `base_edl:1090, :1110` — Skips ohne Verdichtung
4. `add_reactions:385-397` — Max-Time-Cutaway scheitert an Off-Cam

## Priorisierte Hebel

**Sofort (Crash/Korrektheit, klein):**
1. Guard gegen leere Pattern-Liste (`varz:127`) — sonst crasht die Analyse
2. `effective_thr` statt `thr` (`varz:345`) — macht `amplitude_factor` überhaupt erst nutzbar
3. Timeline-Löcher schließen (die vier Stellen oben)
4. PASS-5-Grenzen von `±1` auf `min_shot`/`cleanup` heben

**Mittelfristig (Qualität, größerer Hebel):**
5. Schwellen-Drift beheben (Schwellen nach Stage B neu berechnen)
6. Simultan-Erkennung glätten → Totale wird überhaupt erst zuverlässig ausgelöst
7. Stage A auf Perzentil der lauten Fenster statt Median
8. Mindest-Fensterfüllung im Nodding-Detektor (`varz:469`)
9. Sync: Hüllkurven-Korrelation + Confidence durchreichen und anzeigen

**Strukturell (größter Hebel, größter Aufwand):**
10. Echtes Pitch-Signal statt y-Pixel (`facial_transformation_matrixes`) — der einzige Weg,
    Nicken strukturell von Translation/Kamerabewegung zu trennen
11. N-Kamera-Fähigkeit (siehe `Plan-Multicam-3plus.md`)

---

## Offene Fragen (aus dem Code nicht entscheidbar)

- Sind `nod_threshold: 45` und `auto_accuracy_ref: 0.31` empirisch kalibriert oder Startwerte?
  (`debug_nodding_gt.py` existiert und könnte Messungen enthalten.)
- Ist die Gate-Attack/Release-Semantik bewusst invertiert (`base_edl:229-245`)?
- Ist die Hysterese-vor-Both-Prüfreihenfolge Absicht (`base_edl:206-215`)?
- Warum `+3.0 s` Zuschlag auf die PASS-4-Schwelle (`add_reactions:660`)?
- Sind die modularen Neufassungen unter `sequencer/modules/` (`rms_diarize.py`,
  `crossbleed_gate.py`, `simultaneous_speech.py` …) der Zielzustand oder ein paralleler Zweig?
  **Vor größeren Umbauten hier abgleichen.**
