## Wie der Voice Leveler arbeitet

Der Voice Leveler normalisiert Sprach-Aufnahmen in vier aufeinander aufbauenden Stufen:

`INPUT` → `Gate` → `Upward Compressor` → `Leveler (AGC)` → `Limiter` → `OUTPUT`

Jede Stufe löst ein spezifisches Problem: Das Gate entfernt Grundrauschen zwischen den Sätzen, der Upward Compressor hebt leise Passagen an ohne laute zu berühren, der AGC-Leveler bringt alles auf eine konsistente Ziellautstärke, und der Limiter stellt sicher dass der Output-Pegel nie übersteuert.

Das Ergebnis ist eine Spur, die im Schnitt ohne weitere Lautstärkeautomation funktioniert — laut und leise Sprecher klingen gleichmäßig, Atempausen und Rauschen verschwinden im Hintergrund.

---

## Gate Threshold

Das Gate schließt, sobald der Eingangspegel unter diesen Wert fällt. Passagen unterhalb des Schwellwerts — Atemgeräusche, Raumrauschen, kurze Pausen — werden stummgeschaltet und fließen nicht in die nachfolgenden Stufen ein.

- **Zu niedrig:** Rauschen und Atmer passieren das Gate und werden vom Compressor hochgezogen
- **Zu hoch:** Leise Konsonanten oder Silben am Satzanfang werden abgeschnitten

> **Standardwert −39.1 dB:** Entspricht dem Wavs MaxxVolume-Preset. Passt für Nahbesprechung mit moderatem Grundrauschen.

---

## Leveler Target

Ziel-Lautheit des AGC-Levelers in LUFS. Der Leveler analysiert die Dynamik der gesamten Datei und passt den Pegel so an, dass die integrierte Lautheit diesen Zielwert trifft.

- **Höher (z.B. −16 LUFS):** Lauter, näher an Broadcast-Standards — sinnvoll für Podcast oder YouTube
- **Niedriger (z.B. −23 LUFS):** Leiser, mehr Headroom — sinnvoll wenn der Mix danach noch weiter bearbeitet wird

> **Standardwert −20.7 LUFS:** Entspricht dem MaxxVolume-Preset. Guter Kompromiss zwischen Lautheit und Spielraum für den weiteren Mix.

---

## Output Ceiling

Maximaler True-Peak-Pegel am Ausgang. Sowohl der Loudness-Normalisierer als auch der abschließende Brickwall-Limiter respektieren diesen Wert — kein Sample überschreitet ihn.

- **Näher an 0 dBFS:** Lauter, weniger Headroom für z.B. Musik im Mix
- **Tiefer (z.B. −3 dBFS):** Mehr Sicherheitsabstand, empfehlenswert wenn die Spur noch in einem größeren Mix landet

> **Standardwert −1.5 dBFS:** Verhindert Inter-Sample-Clipping bei der Konvertierung, ohne hörbar Lautstärke zu verschenken.

---

## Erweiterte Parameter

### Low Level Gain (Upward Compressor)

Maximale Anhebung leiser Passagen durch den Upward Compressor. Nur Signale die knapp über dem Gate-Threshold liegen werden angehoben — laute Passagen bleiben unberührt. Das erzeugt eine natürlichere Dynamik als ein klassischer Abwärts-Kompressor.

> **Standardwert +17.0 dB:** Hebt sehr leise Passagen spürbar an. Bei Aufnahmen mit gleichmäßiger Eingangsaussteuerung kann ein niedrigerer Wert (z.B. +10 dB) natürlicher klingen.

### High Level Gain (Peak Limiter)

Maximale Absenkung lauter Peaks durch den Brickwall-Limiter. Wirkt als harter Ceiling-Begrenzer bevor das Signal den Output verlässt.

> **Standardwert −4.5 dB:** Lässt moderate Peaks passieren und begrenzt nur echte Ausreißer. In Kombination mit dem Output Ceiling entsteht ein zuverlässiges Lautstärke-Band.
