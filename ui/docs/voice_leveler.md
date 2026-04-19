## Wie der Voice Leveler arbeitet

Intern arbeitet er in zwei aufeinander aufbauenden Schritten:

**Schritt 1 — Leveler (AGC):** Der Leveler analysiert die integrierte Lautheit der gesamten Datei und normalisiert sie auf den eingestellten Zielwert. Das schafft eine konsistente Ausgangsbasis, auf der der nächste Schritt arbeiten kann.

**Schritt 2 — Dynamikformung (Compand):** Gate, Upward Compressor und High Level Compressor sind keine drei getrennten Filter — sie sind drei Zonen einer einzigen statischen Transferkurve. Diese Kurve beschreibt für jeden Eingangspegel den gewünschten Ausgangspegel:

- **Unterhalb Gate Threshold:** Sanfte Downward Expansion (2:1) — sehr leise Signale wie Rauschen und Atemgeräusche werden weiter abgesenkt
- **Gate bis LLT:** Der Boost des Upward Compressors steigt sanft an
- **Bei LLT:** Maximaler Boost (Low Level Gain) aktiv — leise Sprache wird auf diesen Pegel angehoben
- **LLT bis HLT:** Passthrough — kein Eingriff, dieser Bereich ist die „Komfortzone" für normale Sprachpegel
- **Oberhalb HLT:** Downward Compression — laute Spitzen werden kontrolliert, maximaler Output-Pegel ist High Level Gain bei 0 dBFS

**Schritt 3 — Brickwall-Limiter:** Fängt alle Samples ab, die den Output Ceiling überschreiten würden. Kein Sample verlässt den Prozessor über diesem Wert.

Das Ergebnis ist eine Spur, die im Schnitt ohne weitere Lautstärkeautomation funktioniert — leise und laute Sprecher klingen gleichmäßig, Rauschfahnen und Atempausen verschwinden im Hintergrund.

---

## Presets

Presets speichern alle Parametereinstellungen inklusive der On/Off-Zustände der einzelnen Stufen. Beim Auswählen eines Presets aus der Liste werden alle Werte sofort geladen.

Mit den Raute-markierten (◆) Presets werden fertig kalibrierte Vorlagen mitgeliefert — sie können nicht überschrieben oder gelöscht werden. Eigene Presets lassen sich über den Expander „Preset speichern" ablegen.

---

## Gate

Das Gate sorgt dafür, dass sehr leise Signale — Rauschen, Atemgeräusche, Raumton in Sprechpausen — nicht vom Upward Compressor hochgezogen werden.

Technisch arbeitet es als sanfte Downward Expansion (2:1-Ratio): Signale unterhalb des Threshold werden progressiv abgesenkt, nicht hart abgeschnitten. Der Übergang ist fließend.

Die Wirkung des Gates ist in der Transferkurve nicht als eigener Kurvenpunkt sichtbar, sondern beeinflusst, wie stark der Boden der Kurve (−90 dBFS-Ankerpunkt) abgesenkt wird. Genau genommen wirkt das Gate auf den Pegel, den der Upward Compressor für das allerleiseste Signal erzeugen würde — ist dieser nach der LL-Kompression noch unterhalb des Gate Threshold, wird er mit 2:1 weiter abgesenkt.

### Gate Threshold

Pegel, unterhalb dem die Downward Expansion einsetzt.

- **Zu niedrig:** Rauschen und Atmer passieren das Gate unverändert und werden vom Upward Compressor angehoben
- **Zu hoch:** Leise Konsonanten oder Silbenanfänge werden abgedämpft, der Einstieg in Sätze klingt abgeschnitten

> **Standardwert −39.1 dB:** Abgestimmt auf Nahbesprechungs-Aufnahmen mit moderatem Grundrauschen (entspricht dem Waves MaxxVolume-Preset).

---

## Upward Compressor

Der Upward Compressor hebt leise Sprachpassagen an, ohne laute zu berühren. Anders als ein klassischer Abwärts-Kompressor — der laute Stellen dämpft — arbeitet er von unten: leise Signale werden in Richtung einer Zielzone geschoben, ohne dass der Gesamtcharakter der Aufnahme verdichtet wirkt.

**Wie die Kurve funktioniert:** Die Verstärkung ist nicht konstant, sondern pegelsensitiv. An der Rauschgrenze (−90 dBFS) wird der maximale Boost (Low Level Gain) angewendet. Je lauter das Eingangssignal wird, desto weniger Boost wird zugegeben — bis bei LLT die Verstärkung auf Null (Unity) zurückgefallen ist. Oberhalb von LLT greift der Upward Compressor nicht mehr ein.

### Low Level Threshold (LLT)

Der Pegel, bei dem der Upward Compressor aufhört zu arbeiten — sein Unity-Punkt. Unterhalb des LLT steigt der Boost sanft an, bei LLT selbst ist kein Gain-Eingriff mehr vorhanden.

- **Niedriger (z.B. −40 dB):** Nur sehr leise Passagen werden angehoben, normaler Sprachpegel bleibt unberührt — schonender, aber weniger ausgleichend
- **Höher (z.B. −20 dB):** Auch mittellaut gesprochene Passagen werden noch angehoben — gleichmäßiger, aber der Kompressor greift stärker ein

> **Standardwert −31.5 dB:** Abgestimmt auf typische Sprachpegel bei Nahbesprechung (entspricht dem Waves MaxxVolume-Preset).

### Low Level Gain

Die maximale Anhebung, die an der Rauschgrenze (−90 dBFS) angewendet wird. Dieser Wert tappert bis zum LLT auf Null ab.

- **Höher (z.B. +30 dB):** Auch sehr leise oder weit entfernte Signale werden kräftig angehoben — sinnvoll bei schwacher Eingangsaussteuerung (Kamera-Audio, Lavalier mit großem Abstand)
- **Niedriger (z.B. +8 dB):** Nur moderat leise Passagen werden angehoben — sinnvoll bei gleichmäßig gut ausgesteuertem Quellmaterial

> **Standardwert +17.0 dB:** Hebt schwache Passagen spürbar an. Für Kamera-Audio mit sehr leisen Pegeln (unter −50 dBFS) können Werte bis +40 dB sinnvoll sein.

> **Hinweis:** Wenn Low Level Gain größer ist als der Abstand von LLT zu 0 dBFS (also `ll_gain > |LLT|`), können Signale knapp unterhalb LLT nach der Anhebung kurzzeitig 0 dBFS überschreiten. Der Brickwall-Limiter am Ende fängt das auf.

---

## Leveler (AGC)

Der Leveler funktioniert wie ein sehr langsamer Kompressor mit langen Zeitkonstanten — er reagiert auf die Dynamik über lange Abschnitte, nicht auf einzelne Transienten. Im Gegensatz zum Upward Compressor, der auf Pegelunterschiede innerhalb einer Aufnahme reagiert, bringt der Leveler die *gesamte* Datei auf eine konsistente Ziellautstärke.

Technisch verwendet er EBU R128 Integrated Loudness Normalisation (Two-Pass) — das Ergebnis ist eine Datei, die den eingestellten LUFS-Wert als integrierte Lautheit trifft.

**Wichtig:** Der Leveler läuft als erster Schritt der Verarbeitungskette, bevor Gate, Upward Compressor und High Level Compressor eingreifen. Das stellt sicher, dass alle nachfolgenden Stufen auf einem konsistenten Pegelniveau arbeiten.

### Leveler Target

Ziel-Integrated-Loudness in LUFS (Loudness Units Full Scale, gemessen nach EBU R128).

- **Höher (z.B. −16 LUFS):** Lauter, näher an typischen Streaming- und Broadcast-Standards — geeignet für Podcast, YouTube, Social Content
- **Niedriger (z.B. −23 LUFS):** Leiser, mehr Headroom — empfehlenswert wenn die Spur danach noch in einem größeren Mix mit Musik landet

> **Standardwert −20.7 LUFS:** Entspricht dem Waves MaxxVolume-Preset. Guter Kompromiss zwischen wahrnehmbarer Lautheit und ausreichend Spielraum für die weitere Bearbeitung.

### Loud / Soft

Steuert die Release-Zeit des Compand-Filters (Gate + Upward Compressor + High Level Compressor):

- **Soft (Standard):** Längere Release-Zeit (0,8 s) — der Filter reagiert langsamer auf Pegeländerungen, Übergänge klingen transparenter und natürlicher
- **Loud:** Kürzere Release-Zeit (0,15 s) — der Filter reagiert schneller, Anhebungen und Absenkungen setzen aggressiver ein, das Ergebnis klingt komprimierter und lauter

---

## High Level Compressor

Der High Level Compressor begrenzt laute Spitzen oberhalb des HLT — Passagen die auch nach dem Leveler noch zu laut sind. Zwischen LLT und HLT gibt es keine Bearbeitung (Passthrough); erst oberhalb von HLT setzt sanfte Downward Compression ein.

### High Level Threshold (HLT)

Pegel, oberhalb dem der High Level Compressor aktiv wird. Zwischen LLT und HLT findet kein Gain-Eingriff statt — das ist die Zielzone für normalen Sprachpegel.

- **Niedriger (z.B. −25 dB):** Die Kompression setzt früher ein, mehr Signale werden limitiert — engere Dynamik
- **Höher (z.B. −10 dB):** Nur echte Ausreißer werden begrenzt, normale Laustärkevariation bleibt erhalten

> **Standardwert −20.0 dB:** Ergänzt sich mit dem LLT bei −31.5 dB — zwischen diesen Werten liegt die Passthrough-Zone für normalen Sprachpegel.

> **Hinweis:** HLT muss kleiner sein als High Level Gain (z.B. HLT −20 dB, HL Gain −4.5 dB — also −4.5 ≥ −20), sonst invertiert die Kompressionskurve. Eine Warnung erscheint wenn diese Bedingung verletzt wird.

### High Level Gain

Maximaler Output-Pegel des High Level Compressors, wirksam bei 0 dBFS Eingangspegel. Definiert zusammen mit dem HLT implizit die Kompressionscharakteristik: je größer der Abstand zwischen HLT und High Level Gain, desto stärker die Kompression.

- **Näher an 0 dB (z.B. −1 dB):** Sehr sanfte Kompression, fast kein Eingriff an Peaks
- **Tiefer (z.B. −12 dB):** Starke Begrenzung lauter Stellen, dichter klingender Output

> **Standardwert −4.5 dB:** Begrenzt echte Ausreißer spürbar, ohne die Dynamik hörbar zu verdichten.

---

## Output Ceiling

Maximaler True-Peak-Pegel am Ausgang. Sowohl der Leveler (TP-Parameter der Lautheits-Normalisierung) als auch der abschließende Brickwall-Limiter respektieren diesen Wert — kein Sample überschreitet ihn, unabhängig von allen anderen Einstellungen.

- **Näher an 0 dBFS (z.B. −0.5 dBFS):** Lauteres Ergebnis, weniger Headroom — geeignet wenn die Datei direkt ausgeliefert wird
- **Tiefer (z.B. −3 dBFS):** Mehr Sicherheitsabstand vor Inter-Sample-Clipping bei Konvertierungen — empfehlenswert wenn die Spur noch in einem größeren Mix landet

> **Standardwert −1.5 dBFS:** Verhindert Inter-Sample-Clipping bei lossy-Konvertierungen (z.B. AAC, MP3), ohne hörbar Lautstärke zu verschenken.
