## Sprecher-Erkennung

Die Audiodatei jedes Mikrofons wird in kurze Zeitfenster von 50 ms aufgeteilt und für jedes Fenster der durchschnittliche Lautstärkepegel berechnet. Wer in einem Fenster deutlich lauter ist als der andere, gilt als aktiver Sprecher. Das Ergebnis ist eine Abfolge von Segmenten — „CAM1 spricht", „CAM2 spricht" usw. — die das Grundgerüst der Timeline bilden. Alle Cutaway-Regeln werden erst danach darüber gelegt.

### Schwelle (dB)

In der Praxis sind Mikrofone nie vollständig voneinander isoliert. Der Sprecher von CAM1 ist auf dem Mikrofon von CAM2 immer noch leise hörbar — als sogenanntes Übersprechen. Ohne Schwellwert würde jedes kleine Geräusch als Sprecherwechsel gewertet.

Der Schwellwert legt fest, wie viel lauter jemand sein muss als der andere, damit ein Wechsel registriert wird. Je nach Aufnahmesituation:
- **Kleiner Raum, gute Isolation:** Schwellwert niedriger (z.B. 4 dB)
- **Viel Raumklang oder laute Umgebung:** Schwellwert höher (z.B. 8–10 dB), um fehlerhafte Wechsel zu vermeiden

> **Standardwert 6 dB bedeutet:** Sprecher A muss in einem 50-ms-Fenster rund doppelt so laut sein wie Sprecher B, damit auf ihn geschnitten wird. Liegt der Unterschied darunter, bleibt die aktive Kamera unverändert.

### Min. Segmentlänge (s)

Auch nach der Schwellwert-Filterung entstehen manchmal sehr kurze Abschnitte — z.B. wenn jemand kurz hustet oder räuspert — die den Schnittrhythmus stören würden. Segmente kürzer als dieser Wert werden mit dem jeweiligen Nachbarn zusammengefasst. Das verhindert nervöses Hin- und Herschneiden zwischen zwei Personen, die sich kurz überlappen oder nahezu gleichzeitig sprechen.

> **Standardwert 1,0 Sekunde bedeutet:** Jeder erkannte Sprechabschnitt, der kürzer als eine Sekunde ist, wird mit dem angrenzenden Abschnitt zusammengelegt und löst keinen eigenen Schnitt aus.

### Wechsel-Verzögerung (s)

Sprecherwechsel passieren selten hart. In der Übergangsphase können kurze Dominanzwechsel entstehen, die nicht als echter Wechsel gemeint sind. Dieser Wert stellt sicher, dass ein neuer Sprecher erst dann als aktiv gilt, wenn er für die eingestellte Dauer konstant lauter ist. Damit werden flüchtige Pegelspitzen — z.B. ein einzelner Laut am Satzende — nicht als Wechselsignal gewertet.

> **Standardwert 0,3 Sekunden bedeutet:** Ein neuer Sprecher muss mindestens 0,3 Sekunden lang konstant lauter sein, bevor der Wechsel registriert wird. Kürzere Dominanzmomente werden ignoriert.

---

## Pausen-Trimming

Bei Sprecherwechseln entstehen oft lange Pausen — der eine Sprecher hat aufgehört, der andere setzt erst nach einer Sekunde ein. In einer manuell geschnittenen Timeline würde man diese Pausen kürzen. Das Pausen-Trimming macht das automatisch: Es erkennt Stille an Sprecherwechseln und kürzt sie auf eine einstellbare Maximallänge.

### Pausen trimmen (Toggle)

Aktiviert oder deaktiviert das automatische Kürzen von Sprechpausen. Standardmäßig deaktiviert.

### Schnittmodus

Bestimmt, wo der Videocut innerhalb der gekürzten Pause liegt. Der Audio-Cut ist immer symmetrisch (Middle).

- **Middle:** Video- und Audio-Cut liegen beide symmetrisch in der Pausenmitte
- **L-Cut:** Das Video schneidet am Pausenanfang auf den neuen Sprecher, der Ton des alten Sprechers läuft noch kurz weiter
- **J-Cut:** Der Ton des neuen Sprechers setzt vor dem Bildwechsel ein — man hört die nächste Person, bevor man sie sieht
- **Zufall:** Wählt bei jedem Schnitt zufällig zwischen den drei Modi

> **Standard: Middle** — neutralste Variante, die in den meisten Gesprächssituationen funktioniert.

### Max. Pause (s)

Maximale Pausenlänge, die nach dem Trimming bestehen bleibt. Längere Pausen werden auf diesen Wert gekürzt.

> **Standardwert 1,0 Sekunde bedeutet:** Alle Sprechpausen an Wechselpunkten, die länger als 1 Sekunde sind, werden auf 1 Sekunde gekürzt. Kürzere Pausen bleiben unverändert.

### Stille-Schwelle (dB)

dB-Schwelle, unter der beide Mikrofone als still gelten. Nur Bereiche, in denen beide Mikrofone gleichzeitig unter diesem Wert liegen, werden als trimmbare Pause erkannt.

> **Standardwert −40 dB bedeutet:** Beide Mikrofone müssen gleichzeitig leiser als −40 dB sein, damit ein Bereich als Pause gilt und für das Trimming in Frage kommt.

---

## Crossbleed-Filter

Wenn beide Mikrofone im selben Raum stehen, ist der aktive Sprecher immer auch auf dem anderen Mikrofon hörbar — als sogenanntes Übersprechen (Crossbleed). Das kann die RMS-basierte Sprechererkennung verfälschen, weil der Pegelunterschied zwischen den Mikrofonen kleiner wird als er tatsächlich ist.

Der Crossbleed-Filter arbeitet als intelligentes Noise Gate: Er vergleicht die Pegel beider Mikrofone in Echtzeit und dämpft das jeweils leisere Mikrofon. Das verstärkt den Kontrast zwischen den Kanälen, bevor die Sprechererkennung ansetzt.

### Crossbleed-Gate (Toggle)

Aktiviert oder deaktiviert den Crossbleed-Filter. Standardmäßig deaktiviert — nur nötig wenn Übersprechen die Sprechererkennung merklich verschlechtert.

### Dämpfung (dB)

Wie stark das inaktive Mikrofon gedämpft wird.

- **Stärker (z.B. −40 dB):** Aggressivere Unterdrückung, fast vollständige Stille auf dem inaktiven Kanal
- **Sanfter (z.B. −10 dB):** Leichtes Absenken, Raumakustik bleibt teilweise erhalten

> **Standardwert −25 dB bedeutet:** Das inaktive Mikrofon wird um 25 dB gedämpft — Crossbleed wird stark unterdrückt, minimale Raumakustik bleibt erhalten.

### Hysterese (dB)

Verhindert schnelles Hin- und Herschalten (Flattern) an Pegelgrenzen. Ein Wechsel findet erst statt, wenn das andere Mikrofon um diesen Betrag lauter wird als das aktuell aktive.

> **Standardwert 2,0 dB bedeutet:** Das andere Mikrofon muss mindestens 2 dB lauter werden als das aktuell dominante, bevor das Gate wechselt.

### Fenster (ms)

Analysefenster für den Pegelvergleich zwischen den Mikrofonen. Groß genug, um Raumhall auszugleichen, klein genug für schnelle Sprecherwechsel.

> **Standardwert 80 ms.**

### Attack (ms)

Wie schnell das Gate öffnet, wenn ein Mikrofon als aktiv erkannt wird. Kurz genug, damit Silbenanfänge nicht verloren gehen.

> **Standardwert 15 ms.**

### Release (ms)

Wie langsam das Gate schließt, wenn ein Mikrofon inaktiv wird. Längere Werte verhindern Pumping-Effekte bei schnellen Pegelwechseln.

> **Standardwert 80 ms.**

### Gleichzeitig-Schwelle (dB)

Wenn der Pegelunterschied zwischen beiden Mikrofonen kleiner als dieser Wert ist, werden beide durchgelassen — das System erkennt gleichzeitiges Sprechen und dämpft keinen Kanal.

> **Standardwert 3,0 dB bedeutet:** Liegen beide Mikrofone innerhalb von 3 dB Unterschied, werden beide ungedämpft durchgelassen.

### Gate-Audio in Timeline (Toggle)

Debug-Option: Verwendet die gefilterten (gegate-ten) WAVs statt der Originale in der finalen Timeline. Nur zu Testzwecken — damit kann man hören, wie das Gate klingt, bevor man es produktiv einsetzt. Standardmäßig deaktiviert.
