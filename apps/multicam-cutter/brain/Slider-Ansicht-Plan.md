# Slider-Ansicht — Plan (Entwurf, noch nicht gebaut)

> Stand 19.11.2026. Erst verfeinern, dann bauen. Entscheidungen des Users sind mit
> **(entschieden)** markiert, alles andere ist Vorschlag.

## Ziel

Statt vieler mechanischer Regler bekommt jede Kategorie **einen, höchstens zwei Slider**,
die intern mehrere Parameter sinnvoll — auch nichtlinear — mitbewegen. Der bisherige
Stand mit allen Einzelparametern bleibt als **Expertenmodus**.

## Entscheidungen

- **(entschieden)** Die Slider-Ansicht **ersetzt die heutige „Einfache Ansicht"** (8
  Essentials). Es gibt danach nur noch: Slider-Ansicht ↔ Expertenmodus.
- **(entschieden)** Zwei Achsen, ehrlich benannt:
  - **Wie oft** — Schnittdichte (Abstände, Cooldowns, Mindestlängen zwischen Schnitten).
  - **Wie sicher** — nur eindeutige Momente ↔ auch Grenzfälle (Schwellen, Konfidenz).
  Begründung: Ein Regler kann die Erkennung nicht *besser* machen, nur strenger oder
  großzügiger. Echte Qualität kommt aus besserer Erkennung (Analysespur, später
  Stimm-Prüfung) und ist immer an. „Wie sicher" ganz rechts = wenige, todsichere Cutaways.
  Beleg aus der Sichtung 61/62: eine Mindestlänge als Filter (≙ „strenger") hätte bei
  0,2 s 170 echte Einwürfe gekostet und nur 24 Geräusche entfernt.

- **(erledigt 20.11.)** Sprachreaktionen ohne Regler „Treffsicherheit": Sichtung Folge 62 —
  was nur „großzügig" (4,5/9 dB) dazubringt, war zu 72 % daneben (meist leichte Atmer);
  was „streng" (8/15 dB) streicht, war zu ~64 % echt. Fest 6/12 dB (`fest` der Kategorie).
  Kachel behält nur „Wie oft" (Cooldown 12/4/0 s; „oft" = jeder Einwurf). Neuer
  Expertenschalter `speaking_ignore_min_shot` („Einwürfe dürfen Einstellungen verkürzen"):
  Abstand zum letzten Schnitt nur cleanup_dur statt min_shot → Folge 62 „oft": 294 → 337.
- **(erledigt 20.11.)** Alte Einwurf-Erkennung A (Grundlinie, `rise_db`, Regel A,
  CLI-Versuche), Mischform, `speaking_min_confidence` und der Beta-Schalter
  `speaking_analysespur_enabled` entfernt — B ist die einzige Erkennung. Hinweis im Log
  nur, wenn B nicht laufen kann.
- **(erledigt 20.11.)** Crossbleed-Filter entfernt (Engine, Schema, App; `rms_gate` lebt im
  Sequencer-Modul weiter). Eingebaute Presets entfernt — die Stufen sind die neue
  „Preset-Liste", Presets nur noch eigene. Telemetrie `preset` = Stufen-Stellung.
- **(entschieden)** Alle Kandidaten zum Entfernen (🗑) fliegen raus: Crossbleed-Filter
  (8 Parameter, Code + UI), Erkennung A samt Regel A sobald B Standard ist, Mischform,
  toter Schlüssel `speaking_min_confidence`, CLI-Altversuche.
- **(entschieden)** Neuer **Schnittabstand je Cutaway-Typ** (Cooldown: „nach einem
  Nick-/Einwurf-/Pausen-Cutaway frühestens nach X s der nächste dieses Typs") — die
  eigentliche Stellschraube für „Wie oft".

## Prinzipien (Vorschlag)

1. **Kennlinie je Slider:** Jede Stufe ist eine Tabelle „Parameter → Wert". Zwischen den
   Stufen darf es nichtlinear sein (ein Parameter kippt früh, ein anderer spät).
2. **5 benannte Stufen** (evtl. 7) statt 0–100, z. B. *kaum · wenig · ausgewogen · viel ·
   sehr viel*. Jede Stufe muss an echten Folgen geprüft sein (Analyse-Player, Folgen
   61/62 + weitere) — 100 Stufen kann niemand prüfen; Feinarbeit = Expertenmodus.
3. **Datengetrieben:** Kennlinien in einer Konfigurationsdatei (z. B.
   `config/slider_kennlinien.json`), nicht im Code → anpassbar ohne neuen Build.
4. **Slider schreibt Expertenparameter:** Der Expertenmodus zeigt immer, was gilt. Ändert
   man dort einen gesteuerten Parameter, zeigt der Slider „angepasst" (gleiche Logik wie
   heute `PresetManager.matchingBuiltIn` → „Angepasst").
5. **Presets speichern weiterhin Parameter**, nicht Slider-Stellungen — die Stellung wird
   beim Laden aus den Werten zurückgerechnet (oder „angepasst").
6. **Nicht jede Kategorie braucht einen Slider.** Wo die App automatisch misst und gut
   trifft (Sprechererkennung 99 %), würde ein Regler mehr verstellen als helfen.

## Parameter-Inventar (alle, inkl. interner)

Legende Status: 🎚 Slider-Kandidat · 🔧 nur Expertenmodus · 🔒 intern fest (nicht im UI) ·
🧩 Setup/Material (kein Kreativregler) · 🗑 Kandidat zum Entfernen · ⏸ abgeschaltet.
Werte = App-Standard (die Engine hat für CLI-Läufe teils andere Rückfallwerte).

### Allgemeine Schnittregeln

| Parameter (Schlüssel) | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Min. Einstellungslänge (`min_shot`) | einfach + Experte | 3,0 s | kürzeste Einstellung; Mindestabstand zwischen zwei Schnitten | 🎚 Tempo |
| Max. Einstellungslänge (`max_shot`) | einfach + Experte | 14 s | längere Sprecher-Einstellungen bekommen „Max.-Time"-Cutaways | 🎚 Tempo |
| Min. Aufräumlänge (`cleanup_dur`) | Experte | 1,8 s | PASS 3/6 entfernen kürzere Reststücke | 🎚 Tempo (mitgeführt) |
| Cutaway-Länge (`reaction_dur`) | einfach + Experte | 1,8 s | Mindestdauer jedes Reaktions-Cutaways | 🎚 Tempo |
| Pre-Roll (`pre_roll`) | Experte | 15 Bilder | Cutaway beginnt so viel vor der Reaktion | 🔧 |
| Zufallsfaktor (`randomness`) | Experte | 0,2 | Cutaway-Länge zufällig bis +20 % (ohne festen Startwert → jeder Lauf leicht anders) | 🎚 Tempo |
| Cluster-Abstand (`cluster_max_gap_frames`) | — | 75 Bilder | Reaktionen < 2,5 s Abstand = eine Gruppe, Schnitt rückt an den Gruppenanfang | 🔒 |
| Vorrang Einwürfe vor Nicken (`speaking_priority`) | Experte | aus | Nicken weicht, wenn es einen Einwurf blockieren würde | 🎚 Kopfnicken/Einwürfe (Wie oft) |

### Sprechererkennung

| Parameter | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Schwelle (`threshold_db`) | einfach + Experte | 6 dB (Scan schlägt Wert je Folge vor) | Vorsprung, ab dem ein Mikro als Sprecher gilt | 🔧 (automatisch) |
| Min. Segmentlänge (`min_edit`) | Experte | 1,0 s | kürzere Sprecherwechsel werden geglättet | 🔧 |
| Wechselverzögerung (`change_delay`) | Experte | 0,3 s | Wechsel zählt erst nach so viel stabiler Dominanz | 🔧 |
| Analysefenster (`--analysis-window`) | — | 0,05 s | Fenster der Pegelmessung | 🔒 |
| Pegelausgleich der Mikros | — | automatisch | Median-/RMS-Angleich vor dem Vergleich | 🔒 |
| Stille-Gate | — | automatisch (K-Means − 15 dB) | „niemand spricht" | 🔒 |
| Gleichzeitig-Schwelle (`NOISE_FLOOR_DB`) | — | −50 dB | ab hier gilt ein Mikro als aktiv (→ Totale) | 🔒 |

### Crossbleed-Filter (alt)

| Parameter | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Aktiv (`crossbleed_gate_enabled`) | Experte | aus | „Lauter gewinnt": dämpft je 80-ms-Fenster das leisere Mikro um `gate_floor`, bevor Sprechererkennung UND Einwurf-Erkennung laufen | 🗑 |
| `gate_floor` / `gate_window` / `gate_attack` / `gate_release` / `gate_hysteresis` / `gate_both_threshold` | Experte | −25 dB / 80 / 15 / 80 ms / 2 dB / 3 dB | Feineinstellung des Gates | 🗑 |
| Gefilterte Spuren nutzen (`gate_use_filtered`) | Experte | aus | Debug: schreibt `*_gated.wav` NEBEN die Original-Mikros und importiert sie (nur Resolve-Bin-Workflow) | 🗑 |

**Warum entfernen:** Das Gate ist ein grober Vorgänger der Analysespur. Es drückt gerade
die leise, zuhörende Person weg — also genau die kurzen Einwürfe, die wir finden wollen,
sobald sie sich mit dem Sprecher überlappen. Die Analysespur entfernt Übersprechen je
Frequenz (+9–12 dB Trennung) ohne die eigene Stimme zu opfern. Die Sprechererkennung
braucht das Gate nicht (99 % ohne). Standard war ohnehin aus. Achtung: `gate_use_filtered`
legt Dateien in den Medienordner des Nutzers — auch das spricht fürs Entfernen.

### Sprachreaktionen (Einwürfe)

| Parameter | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Aktiv (`speaking_enabled`) | einfach + Experte | an | Einwürfe überhaupt schneiden | 🎚 (Stufe „aus") |
| Aus der Analysespur (`speaking_analysespur_enabled`) | Experte (Beta) | aus | Erkennung B statt A | später Standard → kein Schalter mehr |
| Max. Cutaway-Dauer (`speaking_max_dur`) | Experte | 2,5 s | längere Laute sind keine Einwürfe | 🔧 |
| **Erkennung B (Analysespur), intern** | | | | |
| Umgebung (`umgebung_s/pctl/db`) | — | 6 s / 80. Pz. / +6 dB | Hügel muss über der lokalen Umgebung liegen | 🎚 Wie sicher |
| Erwartetes Übersprechen (`uebersprechen_db`, `hall_s`) | — | +12 dB / 0,4 s | Hügel muss über dem liegen, was der Sprecher erklären würde | 🎚 Wie sicher |
| Nicht zu leise (`leise_db`) | — | −12 dB unter eigener Sprache | sehr leise Laute ignorieren | 🎚 Wie sicher |
| Lücke / Mindestlänge / Zusammenfassen (`luecke_s/min_s/zusammen_s`) | — | 0,2 / 0,1 / 0,5 s | Form eines Einwurfs | 🔒 (Länge trennt nicht, s. o.) |
| Deadband (`deadband_s`) | — | ±1 s | um Sprecherwechsel nicht suchen | 🎚 Wie oft (oder 🔒) |
| Analysespur (Bandpass, β=2, α=3, STFT 1024/256) | — | fest | Übersprechen/Rauschen entfernen | 🔒 |
| **Erkennung A (bisher), nur ohne Analysespur** | | | | |
| Anstieg (`rise_db`) | Experte | 6 dB | Anstieg über die wandernde Grundlinie | 🗑 sobald B Standard |
| `speaking_min_duration` / `attack_window` / `release_window` / `warmup` / `hold` / `mask_min_pause` / `mask_padding` | — | 0,2 / 0,2 / 20 / 3 / 0 / 0,3 / 0,15 s | Grundlinie, Einfrieren in Pausen | 🗑 sobald B Standard |
| Regel A (`speaking_fp_filter`, `speaking_fp_corr`) | — | an / 0,75 | Gleichtakt = Übersprechen → verwerfen | 🗑 sobald B Standard |
| CLI-only: `fp_on_rise`, `fp_takeover`, `freeze_hold_max`, `freeze_release_margin`, `post_freeze_refractory` | — | aus | alte Versuche | 🗑 |
| Mischform (`speaking_detect_mic_cam1/2`) | — | — | Versuch vom 19.11., verworfen | 🗑 |
| `speaking_min_confidence` | — | = `min_conf` | wird für Einwürfe gar nicht ausgewertet | 🗑 (toter Schlüssel) |
| **Mund + Mikro** (`mouth_reactions_enabled`, `mouth_deadband_s`, `mouth_window_s`, `mouth_listen_pctl`) | ausgeblendet | aus / 1,0 / 0,33 / 93 | Einwürfe über Mundbewegung | ⏸ |

### Kopfnicken

| Parameter | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Aktiv (`nodding_enabled`) | einfach + Experte | an | Nick-Cutaways | 🎚 (Stufe „aus") |
| Min. Konfidenz (`min_conf`) | Experte | 0,60 | nur sicherere Nicker | 🎚 Wie sicher |
| Muster an/aus je Preset (`nodding_patterns`: oscillation, slow_oscillation, strong_oscillation) | Experte | alle an | welche Nick-Formen zählen | 🎚 Wie sicher (z. B. ganz rechts nur „strong") |
| `nod_threshold` | Datei (Nicken-Tab) | 45 | Bewegungsschwelle | 🔧 (global) |
| `cooldown_s` | Datei | 3,0 s | Mindestabstand zweier ERKANNTER Nicker desselben Gesichts (kein Schnittabstand!) | 🔒 |
| `settle_s`, `auto_accuracy_ref`, `analysis_width`, `smooth_kernel`, `calibration_height` | Datei | 3,0 / 0,31 / 1280 / 3 / 2160 | Analyse-Technik | 🔒 |
| Muster-Feinwerte (Fenster, Umkehrungen, Dämpfung, Korrelation, Gewichte …) | Datei | je Muster | Form-Erkennung | 🔒 |
| Kopfschütteln / Augenbrauen / Lachen (`headshake/eyebrow/laughing_cutaway`) | — | aus | erkannt, aber nie geschnitten | 🔒 (später ggf. 🎚) |

### Stille / Pausen

| Parameter | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Pausen kürzen (`pause_trim_enabled`) | einfach + Experte | aus | lange Pausen im Schnitt kürzen | 🎚 Pausen |
| Max. Pause (`max_pause`) | Experte | 1,0 s | Pausen werden auf so viel gekürzt | 🎚 Pausen |
| Schnittmodus (`pause_cut_mode`) | Experte | Mitte | wo im Pausenrest geschnitten wird | 🔧 |
| Stilleschwelle (`pause_silence_db`) | Experte | −40 dB (bzw. automatisch) | was als Stille gilt | 🔧 (später Analysespur?) |
| `pause_search_radius` / `pause_min_duration` | — | 3,0 / 0,3 s | Suche an Sprecherwechseln | 🔒 |
| Pausen-Cutaways (`pause_cutaway_enabled`) | einfach + Experte | aus | Cutaway in langen Sprecherpausen | 🎚 Pausen |
| Min. Pausenlänge (`pause_cutaway_min_pause`) | Experte | 2,0 s | ab welcher Pause | 🎚 Pausen |

### Totale / Bildsprache (nur mit Totale/Halbtotale)

| Parameter | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Simultansprechen (`totale_simul_dur`) | Experte | 3,0 s | ab so langem Durcheinander → Totale | 🎚 Totale |
| Mehrere Totalen (`totale_mode`) | Experte | reihum | welche Totale | 🔧 |
| Übergang bei Sprecherwechsel (`transition_speaker_change`) | Experte | an | Wechsel über die gemeinsame Einstellung | 🎚 Totale |
| Rückweg-Faktor (`transition_return_factor`) | Experte | 2,5 | wann es zurück auf die Nahe geht | 🔒/🔧 |
| Cutaway-Rückwege (`transition_cutaway_back`: Nicken/Einwürfe/Pausen) | Experte | aus | nach Cutaway über die Totale zurück | 🎚 Totale |
| Rückweg-Cooldown (`transition_cutaway_cooldown`, `_cooldown_s`) | Experte | 6 / 8 s | Mindestabstand solcher Rückwege | 🎚 Totale (Wie oft) |
| Wide-Zoom im AAF (`wide_zoom`) | — | 1,0 | Skalierung der Totale | 🔒 |

### CLIP-Filter (Bildinhalt, z. B. „trinkt")

| Parameter | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Aktiv (`clip_filter_enabled`) | Experte | aus | ungünstige Cutaways verschieben | 🔧 |
| `clip_ignore_threshold` / `clip_shift_step_s` / `clip_max_attempts` | — | 0,65 / 2 s / 5 | Schwelle, Verschiebeschritt, Versuche | 🔒 |
| `clip_nodding_mode` / `clip_nodding_threshold` | — | aus / 0,6 | Nick-Cutaways bei „trinkt" verwerfen | 🔒 (Schwelle unbestätigt) |

### Setup / Material

| Parameter | UI | Standard | Wirkung | Status |
|---|---|---|---|---|
| Ein Mehrspur-Recorder (`mics_same_recorder`) | Experte | aus | gemeinsamer Takt aller Mikros beim Sync | 🧩 |
| Sync (`MIN_CONFIDENCE` 5, `TRUST_CONFIDENCE` 50, Fenster 180 s …) | — | fest | Wellenform-Sync | 🔒 |
| Split-Aufnahmen (`recorder_profiles.json`) | — | je Gerät | Teil-Dateien verbinden | 🔒 |

## Slider-Entwurf je Kategorie (zum Verfeinern)

| Kategorie | Slider | steuert (Entwurf) |
|---|---|---|
| **Tempo** | ruhig ↔ lebendig | `min_shot`, `max_shot`, `reaction_dur`, `cleanup_dur`, `randomness` |
| **Kopfnicken** | Wie oft (aus … viel) | Schnittabstand für Nicken*, `speaking_priority` |
| | Wie sicher | `min_conf`, aktive Muster |
| **Sprachreaktionen** | Wie oft (aus … viel) | Schnittabstand für Einwürfe*, Deadband |
| | Wie sicher | `umgebung_db`, `uebersprechen_db`, `leise_db` (später Stimm-Prüfung) |
| **Pausen** | aus · leicht · stark | `pause_trim_enabled`, `max_pause`, Pausen-Cutaways + Mindestpause |
| **Totale** (nur mit Totale) | selten ↔ oft | `totale_simul_dur`, Übergänge, Rückwege + Cooldown |
| **Sprechererkennung** | kein Slider | automatisch (Expertenmodus bleibt) |

\* Schnittabstand je Cutaway-Typ — gibt es heute nicht (nur globales `min_shot`), wird
neu eingeführt (entschieden, s. o.).

## Anordnung (User-Skizze 19.11.)

Raster aus Kacheln, je Kategorie: **großes Piktogramm** oben, darunter die Slider
(höchstens zwei), jeder mit Überschrift und (?)-Tooltip. Vorschlag: Klick aufs
Piktogramm schaltet die Kategorie an/aus (aus = Piktogramm abgedunkelt, Slider
ausgegraut) — so brauchen die Slider keine Stufe „aus".

## Stufen (entschieden 19.11.: 3 Stufen, als Segment-Schalter)

**(entschieden)** Statt Slidern **Segment-Schalter** mit drei ausgeschriebenen Stufen —
wie „Schnittmodus" bei Pausen-Trimming (`WizSegmented`, Lime-Hintergrund für die aktive
Stufe). Text steht direkt im Schalter, ein Klick genügt.

**Engine-Bausteine dafür (gebaut, Standard aus, Schnitt ohne sie byte-identisch):**
`nodding_cooldown_s` / `speaking_cooldown_s` (Schnittabstand je Typ und Person, PASS 2,
decision_log `type_cooldown`) · `nodding_pattern_min_conf` ({muster: schwelle}, > 1 =
Muster aus) · `speaking_umgebung_db` / `speaking_uebersprechen_db` / `speaking_deadband_s`
(Strenge der Einwurf-Erkennung B).


**3 Stufen** je Slider; Wording je Kategorie, Mitte immer „ausgewogen":

| Kategorie | Slider | links · Mitte · rechts |
|---|---|---|
| Tempo | Tempo | ruhig · ausgewogen · lebendig |
| Kopfnicken | Wie oft | selten · ausgewogen · oft |
| | Treffsicherheit | großzügig · ausgewogen · streng |
| Sprachreaktionen | Wie oft | selten · ausgewogen · oft |
| | Treffsicherheit | großzügig · ausgewogen · streng |
| Pausen | Pausen straffen | sanft · ausgewogen · straff |
| | Cutaways in Pausen | selten · ausgewogen · oft |
| Totale (nur mit Totale) | Wie oft | selten · ausgewogen · oft |

Kopfnicken „Treffsicherheit" aus der Sichtung: streng = nur oscillation · ausgewogen =
+ slow ab 0,7 · großzügig = + slow ab 0,6 + strong.

## Kennlinien (entschieden 19.11., Werte zum Nachjustieren)

Mitte „ausgewogen" = User-Einstellungen bzw. gesichtete Werte.

**Tempo** (ruhig · ausgewogen · lebendig): min_shot 4,0 / 3,0 / 1,2 s · max_shot 20 / 14 /
6,5 s · reaction_dur 2,2 / 1,8 / 1,2 s · cleanup_dur 1,8 / 1,5 / 1,0 s (nie über
reaction_dur) · randomness 0,2 / 0,3 / 0,3. „lebendig" bewusst für Social Clips.

**Kopfnicken** Wie oft (selten · ausgewogen · oft): nodding_cooldown_s 14 / 8 / 0.
Treffsicherheit (großzügig · ausgewogen · streng): alle Muster ab 0,6 / slow ab 0,7 +
strong aus / nur oscillation.

**Sprachreaktionen** Wie oft: speaking_cooldown_s 12 / 4 / 0. Treffsicherheit:
übersprechen/umgebung +9/+4,5 · +12/+6 (gesichtet) · +15/+8 dB. Vorrang vor Nicken immer an.

**Totale** Wie oft: totale_simul_dur 5 / 3 / 2 s · Rückweg über Totale: nie / nach
Einwürfen / nach allen.

**Pausen** (Piktogramm schaltet die Kategorie): Pausen kürzen = verbleibende Pausenlänge
1,5 / 1,0 / 0,6 s (sanft · ausgewogen · straff); Cutaways in Pausen: keine / lange Pausen
(ab 3 s) / oft (ab 1,5 s).

## Piktogramme (Higgsfield)

- Modell: **GPT Image 2.6 mit SVG-Ausgabe** (echte Vektoren, transparenter Hintergrund,
  skaliert scharf, Farbe in der App nachträglich anpassbar). ~1,5 Credits je Bild in
  hoher Qualität. Alternative: Recraft V4.1 `vector` mit fester Palette (2,5 Credits).
- Stil: Referenz-Maskottchen (runder Kopf, Punktaugen, Strich-Lächeln, Ohr, Haarschopf),
  einfarbig **Lime #C6F24E**, in der App auf **#191C15** (wizSurface).
- **(entschieden)** Kategorien heißen **Kopfnicken · Sprachreaktionen · Pausen · Totale ·
  Tempo**. Finale SVGs in `apps/multicam-cutter/design/piktogramme/` (kopfnicken,
  sprachreaktionen, pausen, totale, rhythmus). Motive: Nicken + Auf-ab-Pfeil · offener
  Mund + Schallbögen · zurückgelehnt, Hand hinterm Kopf, „…" · zwei Figuren im
  Bildrahmen · Filmstreifen mit einer Unterteilung, Schere schneidet, Köpfe links/rechts.
  Einfarbig #C6F24E, transparent → Farbe/Abdunkeln in der App per Code.

## Offene Fragen

1. Kategorien und Zuordnung oben — passt das, fehlt etwas, ist etwas zu viel?
2. Cooldown je Typ: Wirkt er nur innerhalb des Typs (Nicken→Nicken) oder auch
   typübergreifend (Nicken→Einwurf)? Mit „Vorrang vor Nicken" zusammen denken.
3. Anzahl Stufen: 5 oder 7? Stufennamen?
4. Wie prüfen wir Kennlinien? Vorschlag: je Stufe ein Lauf auf Folge 61/62, im Player
   die Unterschiede zur Nachbarstufe sichten.

## Belegt: Nick-Muster (Sichtung 19.11., Folge 61 + 62, 253 Nicker)

| Muster | nickt | trinkt | sonstiges | erkannt (61+62) |
|---|---|---|---|---|
| oscillation | 98 % | 0 | 2 | 338 |
| slow_oscillation | 54 % | 0 | 46 | 640 |
| strong_oscillation | 45 % | 6 (alle Trinken-Fälle) | 23 | 53 |

- Trinken kommt NUR von `strong_oscillation`; Konfidenz trennt dort nicht (fast alles > 0,7).
- `slow_oscillation` = größte Fehlerquelle der Menge nach (Lachen, Sitzposition,
  Erstaunen, Ansetzen zum Reden). Konfidenz trennt gut: ≥0,6 → 68 % nickt, ≥0,7 → 80 %
  (49 % bleiben), ≥0,8 → 100 % (11 % bleiben).
- Hochrechnung bei min_conf 0,6: alle Muster ~870 Nick-Cutaways, 78 % echt; `strong` aus +
  `slow` ab 0,7: ~650, 89 % echt (−170 Fehlalarme, −100 schwache echte).
- Kennlinien-Vorschlag „Wie sicher" (Kopfnicken): ganz sicher = nur oscillation · sicher =
  + slow ≥0,8 · ausgewogen = + slow ≥0,7 · mehr = + slow ≥0,6 · alles = + strong.
  Braucht eine Konfidenzschwelle JE MUSTER (heute nur global `min_conf`).
- Idee: Fehlalarm „beginnt zu reden" per Analysespur abfangen (eigene Spur kurz danach aktiv).
- Daten: `<Folge>/_Aktivitaet-Test/player_nicken/labels.json`.

## Noch zu belegen (Testläufe)

- **Nick-Muster: welches liefert die meisten Fehlalarme (Trinken statt Nicken)?**
  (User, 19.11.) Voraussetzung für „Wie sicher" bei Kopfnicken — welche Muster bei
  strengeren Stufen wegfallen, hängt davon ab. Machbar ohne Umbau: Jeder erkannte Nicker
  trägt in `<cam>_reactions.json` sein Muster (`pattern`: oscillation /
  slow_oscillation / strong_oscillation). Ablauf: Nick-Analyse mit ALLEN Mustern an
  (Folge 61/62, Schnittregeln aus), je Nicker ein Prüf-Marker im Analyse-Player mit dem
  Muster im Namen; bewerten als trifft / Trinken / sonstiges. Auswertung je Muster:
  Anteil Treffer vs. Trinken. Gleich mit prüfen: ob `min_conf` Trinken von Nicken trennt
  (Konfidenz je Marker mitschreiben). Dauer: Gesichtsanalyse ~45 min je Kamera.

## Umsetzung (später, nach Freigabe)

1. Kennlinien-Datei + Lade-/Rückrechnungslogik (Engine-unabhängig, nur App).
2. Erste Kategorie: Sprachreaktionen (meiste Daten), Kennlinie an 61/62 prüfen.
3. Slider-Ansicht ersetzt `simpleList` in `WizardSettings`; Expertenmodus unverändert.
4. Übrige Kategorien nacheinander, jeweils mit Prüflauf.
