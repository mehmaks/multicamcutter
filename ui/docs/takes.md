# Take Selector

## Whisper-Modell

Der Take Selector nutzt [OpenAI Whisper](https://github.com/openai/whisper) zur Spracherkennung. Whisper transkribiert den Clip und liefert für jedes erkannte Wort einen genauen Zeitstempel — auf dieser Basis funktioniert die gesamte Take- und Sektionserkennung.

Whisper gibt es in verschiedenen Größen. Kleinere Modelle arbeiten schneller, größere erkennen Text genauer — besonders bei Fachjargon, Eigennamen oder undeutlicher Aussprache.

| Modell | Größe | Geschwindigkeit | Empfehlung |
|--------|-------|-----------------|------------|
| tiny | ~39 MB | sehr schnell | Schnelltest, einfache Sprache |
| base | ~74 MB | schnell | — |
| **small** | **~461 MB** | **mittel** | **Standard — gutes Gleichgewicht** |
| medium | ~1,5 GB | langsam | Schwierige Aufnahmen, Fachsprache |
| large | ~3 GB | sehr langsam | Maximale Genauigkeit |

> **Warum small als Standard?** Bei geskripteten Aufnahmen kommt es besonders auf genaue Wortgrenzen an — ein falsch erkanntes Wort kann dazu führen, dass zwei Takes nicht als Wiederholung erkannt werden. Small ist der kleinste Schritt, bei dem das zuverlässig funktioniert.

Das Modell wird beim ersten Einsatz automatisch heruntergeladen und lokal zwischengespeichert (`~/.cache/whisper/`). Bei der Erstinstallation des Toolkits wird es vorab geladen, sodass die erste Analyse ohne Wartezeit startet.

---

# Take Selector

Der Take Selector analysiert geskriptete Aufnahmen — Clips, in denen ein Text mehrfach aufgenommen wurde — und wählt automatisch den besten Take pro Abschnitt aus.

Er erkennt, wo neue Versuche beginnen, gruppiert zusammengehörige Takes und schlägt jeweils den letzten vollständigen Take vor. Die Auswahl kann manuell überschrieben werden.

---

## Erkennungs-Parameter

### Pause-Schwelle (s)

Der Sprecher hält inne — entweder um neu anzusetzen oder weil ein Abschnitt zu Ende ist. Ab welcher Länge eine Pause als Trennung gilt, legt dieser Wert fest. Kurze Atempausen innerhalb eines Takes bleiben so zusammen, längere Unterbrechungen trennen die Aufnahme in einzelne Segmente.

> **Standardwert 1,5 Sekunden bedeutet:** Pausen kürzer als 1,5 Sekunden gelten als normale Sprechpausen innerhalb eines Takes. Erst ab 1,5 Sekunden Stille beginnt ein neues Segment.

### Ähnlichkeits-Schwelle

Wenn ein neues Segment beginnt, vergleicht das Tool dessen erste Wörter mit dem Anfang des aktuellen Abschnitts. Klingen sie ähnlich, ist es ein neuer Versuch des gleichen Textes — also ein neuer Take. Klingen sie anders, beginnt ein neuer Abschnitt.

> **Standardwert 0,5 bedeutet:** Ein Segment muss zu mindestens 50 % mit dem Anfang des aktuellen Abschnitts übereinstimmen, um als neuer Take zu zählen. Niedrigere Werte fassen mehr Varianten zusammen, höhere Werte trennen strenger.

### Min. Take-Vollständigkeit

Nicht jeder Take ist vollständig — manchmal bricht der Sprecher mittendrin ab. Dieser Wert legt fest, wie viel von einem Take vorhanden sein muss, damit er als gültiger Kandidat gilt. Unvollständige Takes werden übersprungen, der letzte vollständige Take wird ausgewählt.

> **Standardwert 0,7 bedeutet:** Ein Take muss mindestens 70 % der Wörter des längsten Takes in diesem Abschnitt enthalten, um als vollständig zu gelten. Kürzere Takes — z.B. weil der Sprecher abgebrochen hat — werden ignoriert.

### Min. Sektion-Länge (%)

Zwischen echten Takes passiert immer etwas: ein Mikrofontest am Anfang, ein kurzes „Warte" während der Sprecher sich neu einliest, ein „Noch eins?" an den Kameramann. All das wird zwar erkannt, soll aber nicht als eigener Abschnitt behandelt werden.

Stell dir vor, du schaust alle erkannten Abschnitte nebeneinander an und suchst den mit den längsten Takes — das ist mit hoher Wahrscheinlichkeit das eigentliche Skript. Alles, was im Vergleich dazu winzig ist, wird ignoriert.

> **Standardwert 30 % bedeutet:** Hat der längste Take eines Abschnitts weniger als 30 % der Wörter des längsten Takes überhaupt, wird der Abschnitt herausgefiltert. Ein „Warte" mit 1 Wort verschwindet genauso wie ein Mikrofontest mit 8 Wörtern, wenn das eigentliche Skript 80 Wörter hat.
