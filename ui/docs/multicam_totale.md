# Totale-Cam Schnittlogik

Die normale Sprecher-Erkennung funktioniert nach dem Prinzip der Dominanz: Wer lauter ist, bekommt den Schnitt. Das funktioniert gut, solange sich die Sprecher abwechseln. Wenn aber beide gleichzeitig sprechen — in einer lebhaften Diskussion, beim gemeinsamen Lachen oder bei einer Überlappung — ist kein klarer Dominanzunterschied messbar. In solchen Momenten ist die beste Wahl oft die Totale: Sie zeigt beide Personen gleichzeitig und gibt dem Zuschauer Orientierung.

Das System analysiert dieselben 50-ms-Fenster wie die Sprecher-Erkennung, prüft aber eine andere Bedingung: Sind beide Mikrofone gleichzeitig aktiv und ist der Lautstärkeunterschied kleiner als der eingestellte Schwellwert, gilt das Fenster als simultan. Aufeinanderfolgende simultane Fenster werden zu Segmenten zusammengefasst.

## Min. Simultandauer (s)

Kurze Überlappungen beim Sprecherwechsel kommen immer vor und sollen keinen Totalen-Schnitt auslösen. Nur wenn ein simultanes Segment länger als dieser Wert andauert, wird tatsächlich auf die Totale geschnitten. Die Logik greift außerdem nur, wenn mindestens eine Kamera im Workflow als **Totale** markiert ist.

> **Standardwert 3,0 Sekunden bedeutet:** Erst wenn beide Mikrofone für mindestens 3 zusammenhängende Sekunden gleichzeitig aktiv sind und kein klarer Lautstärkeunterschied zwischen ihnen besteht, wird auf die Totale geschnitten. Kürzere Überlappungen — z.B. beim Satzende oder bei kurzen Einwürfen — lösen keinen Totalen-Schnitt aus.
