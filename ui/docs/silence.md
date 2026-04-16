## Wie der Silence Cutter arbeitet

Der Silence Cutter analysiert Audio frame-für-frame und berechnet für jedes Zeitfenster den RMS-Pegel — ein Maß für die durchschnittliche Lautstärke. Frames, die unter dem eingestellten Schwellwert liegen, gelten als Stille. Aufeinanderfolgende stille Frames werden zu Bereichen zusammengefasst. Alles, was übrig bleibt, wird als Keep-Segment in die neue Timeline übernommen.

Im **Resolve-Modus** können mehrere Audio-Spuren gleichzeitig analysiert werden. Ein Frame gilt dabei nur dann als Stille, wenn *alle* ausgewählten Spuren gleichzeitig unter dem Schwellwert liegen — das verhindert, dass ein Schnitt gesetzt wird, während auf einer anderen Spur noch gesprochen wird.

Im **Datei-Pfad-Modus** wird eine einzelne Datei analysiert. Die Logik ist identisch, es gibt nur eine Spur.

### Schwellwert (dB)

Legt fest, ab welchem Pegel ein Audiobereich als Stille gilt. Alles unterhalb dieses Werts wird als nicht-sprachlich eingestuft.

Je nach Aufnahmesituation:
- **Ruhige Umgebung, gutes Mikrofon:** Schwellwert niedriger (z.B. −50 dB)
- **Raumgeräusche, Grundrauschen:** Schwellwert höher (z.B. −35 bis −30 dB), um Rauschen als Stille zu erkennen und nicht fälschlich als Sprache

> **Standardwert −40 dB bedeutet:** Frames mit einem RMS-Pegel unterhalb von −40 dB gelten als Stille. Ein leises Grundrauschen liegt typischerweise darunter, normale Sprache deutlich darüber.

### Mindestdauer Stille (s)

Kurze Unterbrechungen innerhalb eines Satzes — ein Luftholen, eine kurze Sprechpause — sollen nicht herausgeschnitten werden. Erst wenn eine Stille die eingestellte Mindestdauer überschreitet, wird sie als zu schneidende Pause erkannt.

> **Standardwert 0,8 Sekunden bedeutet:** Pausen kürzer als 0,8 Sekunden werden ignoriert und bleiben im Schnitt erhalten. Erst längere Lücken werden als echte Stille behandelt.

### Pre-Pad (ms)

Stille beginnt selten exakt mit dem letzten Wort. Zwischen dem Ende eines Satzes und dem Einsetzen der Stille liegt oft noch ein kleiner Nachhall oder das Ausklingen der Stimme. Der Pre-Pad lässt diesen Übergang stehen — er schützt den Anfang jeder erkannten Stille vor dem Schnitt.

> **Standardwert 150 ms bedeutet:** Die ersten 150 ms jeder erkannten Stille bleiben erhalten. Der Schnitt beginnt erst danach.

### Post-Pad (ms)

Symmetrisch zum Pre-Pad: Auch am Ende einer Stille — kurz bevor jemand wieder zu sprechen anfängt — gibt es einen kurzen Übergangsmoment. Ohne Puffer würde der Schnitt direkt auf den ersten Laut fallen, was abrupt klingt. Der Post-Pad hält diesen Moment zurück.

> **Standardwert 150 ms bedeutet:** Die letzten 150 ms jeder erkannten Stille bleiben erhalten. Der Schnitt endet entsprechend früher.

### Lücken = Stille (nur Resolve-Modus)

Im Resolve-Modus kann eine Audio-Spur Lücken zwischen Clips haben — Bereiche, auf denen kein Clip liegt. Mit dieser Option gelten diese Lücken automatisch als Stille, ohne dass Audio analysiert werden muss.

Wenn deaktiviert, fließen nur tatsächlich analysierte Audiobereiche in die Composite-Detection ein. Lücken werden dann weder als Stille noch als Sprache gewertet — die anderen Spuren entscheiden allein.
