# Take Selector

## Inhaltlicher Vergleich

Der **Inhalt vergleichen**-Dialog zeigt auf einen Blick, wie sich die Takes einer Sektion inhaltlich voneinander unterscheiden — nicht nur wann sie beginnen und enden, sondern was genau gesagt wurde und wo es abweicht.

## Funktionsweise

Als Referenz dient automatisch der längste Take der Sektion. Alle anderen Takes werden Wort für Wort mit dieser Referenz verglichen:

- **Normaler Text** — Wörter, die identisch mit der Referenz sind
- ~~Durchgestrichen grau~~ — Wörter aus der Referenz, die in diesem Take fehlen oder übersprungen wurden
- **Farbig markiert** — Wörter, die in diesem Take anders formuliert sind oder zusätzlich vorkommen

Jeder Take bekommt eine eigene Farbe, erkennbar an der farbigen linken Kante des Blocks.

## Fragment-Filter

Kleine Abweichungen entstehen oft nicht durch bewusste Umformulierung, sondern durch Versprecher, Füllwörter oder Erkennungsungenauigkeiten von Whisper. Der Fragment-Filter blendet solche kurzen Unterschiede aus.

> **Beispiel:** Bei einem Filter von 2 Wörtern wird ein einzelnes falsch erkanntes Wort nicht als Abweichung angezeigt — erst ab zwei aufeinanderfolgenden abweichenden Wörtern erscheint eine Markierung.

Der Filter lässt sich direkt im geöffneten Dialog verschieben — die Ansicht aktualisiert sich sofort, ohne dass die Analyse neu gestartet werden muss.

## Wann ist das nützlich?

- Du willst wissen, ob ein Take inhaltlich vollständig ist oder ob der Sprecher einen Satz ausgelassen hat
- Du vergleichst zwei scheinbar ähnliche Takes und suchst die genaue Stelle, an der sie voneinander abweichen
- Du prüfst, ob eine Umformulierung im letzten Take trotzdem die gleiche Information enthält
