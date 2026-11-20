# Datensatz: Sprachreaktions-FPs

Ground Truth zur Bewertung der FP-Filterregeln (siehe
`apps/multicam-cutter/brain/Sprachreaktionen-Parameter.md`).

## Dateien

- `ep*-marker.json` — die Marker aus der Resolve-Timeline, roh.
  **Nur dort existierten sie ursprünglich** — Resolve-Projekte sind kein Archiv.
- `features.json` — pro Marker die gemessenen Merkmale. Das ist die
  Arbeitsdatei; Regeln werden hiergegen bewertet, ohne die Dumps zu brauchen.
- `dumps/` — die rohen `speaking_debug.json` je Episode. **Nicht im Git**
  (`.gitignore`), ~3 MB pro Episode. Nur nötig, um `features.json` neu zu bauen
  oder neue Merkmale zu berechnen.

## Markier-Protokoll

Erste ~30 Minuten, **100 %** der Sprachreaktions-Cutaways markieren:

| Farbe | Bedeutung |
|---|---|
| Grün | TP — dort war eine echte Reaktion |
| Blau | FP — dort war keine |
| Gelb | unsicher |

⚠️ **Gelb bitte nur für „ich kann die Reaktion nicht beurteilen"**, nicht für
„Reaktion war da, aber der Schnitt sitzt schlecht". Das sind zwei verschiedene
Fragen, und die Schnittposition ist ein eigenes, separat lösbares Problem
(Einstiegspunkt ist deterministisch: `cluster_start − pre_roll`, kein Zufall).
Vermischt verwässern sie die Ground Truth.

## Metadaten je Episode

`mic_separation_db` (Median On-minus-Off während Sprechpassagen) und
`base_corr` gehören zur Episode, nicht zum einzelnen Marker — beide erklären,
warum eine Regel in der einen Aufnahme funktioniert und in der anderen nicht.

| Episode | Kopfnicken | Sprachreaktions-Cutaways | markiert | FP-Rate |
|---|---|---|---|---|
| ep01 (Folge 45) | **AN** | 70 | 22 | **73 %** |
| ep02 (Folge 47) | aus | — | 29 | 21 % |
| ep03 (Folge 44) | aus | 105 | 21 | 10 % |

⚠️ **Konfigurations-Confound, nicht übersehen.** ep01 lief mit **eingeschaltetem**
Kopfnicken, ep02 und ep03 ohne. Das ist kein Detail: Ohne Nicken-Cutaways
konkurrieren weniger Kandidaten um den `min_shot`-Abstand in PASS 2, es
überleben also **mehr** Sprachreaktionen in den Schnitt (ep03: 105 gegenüber
ep01: 70). Die überlebende Teilmenge ist damit eine andere.

Die stark schwankende FP-Rate (73 % → 21 % → 10 %) darf deshalb **nicht** ohne
Weiteres dem Material zugeschrieben werden — sie kann ebenso gut an der
Konfiguration liegen. Wer das auflösen will, braucht entweder eine Episode in
beiden Varianten oder alle weiteren mit derselben Einstellung.

⚠️ Die früher hier geführte `mic_separation_db` ist als Erklärgröße verworfen
(nach Stufe A gemessen, siehe `brain/Sprachreaktionen-Parameter.md`).
