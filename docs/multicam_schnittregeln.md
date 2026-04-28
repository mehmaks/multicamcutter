## Generelle Schnittregeln

### Min. Shotlänge (s)

Verhindert, dass ein Cutaway direkt nach dem letzten Schnitt gesetzt wird. Wenn jemand gerade erst zu sehen war, soll nicht sofort wieder weggeschnitten werden — das würde unruhig und hektisch wirken. Erst wenn die Kamera die Mindestzeit durchgehalten hat, ist sie wieder bereit für einen Cutaway.

> **Standardwert 3,0 Sekunden bedeutet:** Nachdem auf eine Kamera geschnitten wurde, vergehen mindestens 3,0 Sekunden, bevor der nächste Cutaway gesetzt werden darf — auch wenn in dieser Zeit ein Nicken oder eine Reaktion erkannt wird.

### Max. Shotlänge (s)

Bleibt eine Kamera zu lange ohne Schnitt, wirkt das statisch. Sobald der Grenzwert erreicht ist, erzwingt der Workflow automatisch einen Cutaway — unabhängig davon, ob gerade ein erkanntes Ereignis (Nicken, Reaktion) vorliegt. Das hält den Schnittrhythmus lebendig.

> **Standardwert 14 Sekunden bedeutet:** Wird eine Kamera länger als 14 Sekunden am Stück gezeigt, setzt der Workflow automatisch einen Cutaway — selbst wenn kein Nicken oder keine Reaktion erkannt wurde.

### Cleanup-Mindestlänge (s)

Nach dem Zusammensetzen der Timeline können sehr kurze Schnitte übrig bleiben — z.B. wenn zwei Cutaways direkt aufeinanderfolgen und dazwischen nur eine halbe Sekunde der Hauptkamera liegt. Solche Mikroschnitte sind im Schnittbild meist störend.

Der Cleanup-Pass läuft nach der gesamten Montage ein letztes Mal durch die Timeline und entfernt alle Segmente kürzer als dieser Wert. Es ist kein inhaltlicher Eingriff, sondern ein technischer Qualitätsfilter kurz vor der Übergabe der Timeline.

> **Standardwert 1,8 Sekunden bedeutet:** Alle Segmente — egal ob Hauptkamera oder Cutaway — die nach dem Zusammenbau kürzer als 1,8 Sekunden sind, werden aus der Timeline entfernt.
