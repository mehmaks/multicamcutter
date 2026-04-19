## Einfachmodus

Der Einfachmodus reduziert die Einstellungen auf drei Entscheidungen, die für die meisten Aufnahmen ausreichen.

### Leveler Target

Wie laut soll die fertige Datei sein? Der Wert wird in LUFS gemessen — je höher (näher an 0), desto lauter.

| Einsatzzweck | Empfohlener Wert |
|---|---|
| Podcast / YouTube | −16 LUFS |
| Broadcast (TV, Radio) | −23 LUFS |
| Mix-Vorbereitung (Musik unterlegen etc.) | −20 LUFS |

> **Standard: −20.7 LUFS** — ein guter Kompromiss, der für die meisten Formate funktioniert.

---

### Output Ceiling

Maximaler Pegel, den die fertige Datei erreichen darf. Kein Sample wird lauter als dieser Wert — ein Sicherheitsnetz gegen Übersteuerung.

| Einsatzzweck | Empfohlener Wert |
|---|---|
| Direkte Auslieferung (Podcast, Upload) | −1.5 dBFS |
| Weiterverarbeitung im Mix | −3.0 dBFS |

> **Standard: −1.5 dBFS** — verhindert Verzerrungen bei MP3/AAC-Konvertierung.

---

### Aufnahmesituation

Wählt automatisch die passenden Rauschunterdrückungs-Einstellungen für dein Setup:

- **Studio:** Nahbesprechung mit Großmembran- oder Tauchspulenmikrofon in ruhiger Umgebung. Leises Rauschen wird abgesenkt, Sprache bleibt unberührt.
- **Lavalier:** Ansteck-Mikrofon mit etwas mehr Umgebungsgeräuschen. Das Gate ist empfindlicher eingestellt, um auch bei höherem Rauschpegel sauber zu arbeiten.
- **Kameramikro:** Eingebautes oder weit entferntes Mikrofon. Das Gate ist deaktiviert, da der Rauschpegel zu hoch und zu nah an der Sprache liegt — hier würde ein Gate mehr schaden als helfen.
