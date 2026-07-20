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

| Episode | Mic-Trennung | Grundkorrelation | FP-Rate |
|---|---|---|---|
| ep01 Mario Koch | 15,9 dB | 0,73 | 73 % |
| ep02 Sarah Jung | 11,0 dB | 0,71 | 21 % |
