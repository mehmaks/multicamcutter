# Multicam Cutter

## Sprecher-Erkennung

Die Audiodatei jedes Mikrofons wird in kurze Zeitfenster von 50 ms aufgeteilt und für jedes Fenster der durchschnittliche Lautstärkepegel berechnet. Wer in einem Fenster deutlich lauter ist als der andere, gilt als aktiver Sprecher. Das Ergebnis ist eine Abfolge von Segmenten — „CAM1 spricht", „CAM2 spricht" usw. — die das Grundgerüst der Timeline bilden. Alle Cutaway-Regeln werden erst danach darüber gelegt.

## Schwelle (dB)

In der Praxis sind Mikrofone nie vollständig voneinander isoliert. Der Sprecher von CAM1 ist auf dem Mikrofon von CAM2 immer noch leise hörbar — als sogenanntes Übersprechen. Ohne Schwellwert würde jedes kleine Geräusch als Sprecherwechsel gewertet.

Der Schwellwert legt fest, wie viel lauter jemand sein muss als der andere, damit ein Wechsel registriert wird. Je nach Aufnahmesituation:
- **Kleiner Raum, gute Isolation:** Schwellwert niedriger (z.B. 4 dB)
- **Viel Raumklang oder laute Umgebung:** Schwellwert höher (z.B. 8–10 dB), um fehlerhafte Wechsel zu vermeiden

> **Standardwert 6 dB bedeutet:** Sprecher A muss in einem 50-ms-Fenster rund doppelt so laut sein wie Sprecher B, damit auf ihn geschnitten wird. Liegt der Unterschied darunter, bleibt die aktive Kamera unverändert.

## Min. Segmentlänge (s)

Auch nach der Schwellwert-Filterung entstehen manchmal sehr kurze Abschnitte — z.B. wenn jemand kurz hustet oder räuspert — die den Schnittrhythmus stören würden. Segmente kürzer als dieser Wert werden mit dem jeweiligen Nachbarn zusammengefasst. Das verhindert nervöses Hin- und Herschneiden zwischen zwei Personen, die sich kurz überlappen oder nahezu gleichzeitig sprechen.

> **Standardwert 1,0 Sekunde bedeutet:** Jeder erkannte Sprechabschnitt, der kürzer als eine Sekunde ist, wird mit dem angrenzenden Abschnitt zusammengelegt und löst keinen eigenen Schnitt aus.

## Wechsel-Verzögerung (s)

Sprecherwechsel passieren selten hart. In der Übergangsphase können kurze Dominanzwechsel entstehen, die nicht als echter Wechsel gemeint sind. Dieser Wert stellt sicher, dass ein neuer Sprecher erst dann als aktiv gilt, wenn er für die eingestellte Dauer konstant lauter ist. Damit werden flüchtige Pegelspitzen — z.B. ein einzelner Laut am Satzende — nicht als Wechselsignal gewertet.

> **Standardwert 0,3 Sekunden bedeutet:** Ein neuer Sprecher muss mindestens 0,3 Sekunden lang konstant lauter sein, bevor der Wechsel registriert wird. Kürzere Dominanzmomente werden ignoriert.
