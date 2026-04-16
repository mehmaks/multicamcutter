# Multicam Cutter

## Generelle Schnittregeln

## Min. Shotlänge (s)

Verhindert, dass ein Cutaway direkt nach dem letzten Schnitt gesetzt wird. Wenn jemand gerade erst zu sehen war, soll nicht sofort wieder weggeschnitten werden — das würde unruhig und hektisch wirken. Erst wenn die Kamera die Mindestzeit durchgehalten hat, ist sie wieder bereit für einen Cutaway.

> **Standardwert 2,3 Sekunden bedeutet:** Nachdem auf eine Kamera geschnitten wurde, vergehen mindestens 2,3 Sekunden, bevor der nächste Cutaway gesetzt werden darf — auch wenn in dieser Zeit ein Nicken oder eine Reaktion erkannt wird.

## Max. Shotlänge (s)

Bleibt eine Kamera zu lange ohne Schnitt, wirkt das statisch. Sobald der Grenzwert erreicht ist, erzwingt der Workflow automatisch einen Cutaway — unabhängig davon, ob gerade ein erkanntes Ereignis (Nicken, Reaktion) vorliegt. Das hält den Schnittrhythmus lebendig.

> **Standardwert 11 Sekunden bedeutet:** Wird eine Kamera länger als 11 Sekunden am Stück gezeigt, setzt der Workflow automatisch einen Cutaway — selbst wenn kein Nicken oder keine Reaktion erkannt wurde.

## Cutaway-Länge (s)

Legt fest, wie lange eine Reaktionsaufnahme mindestens gezeigt wird. Der tatsächliche Cutaway kann durch den Zufallsfaktor länger werden. Zu kurze Cutaways (unter ~1 Sekunde) wirken wie ein Versehen, zu lange (über 3–4 Sekunden) ohne erkennbaren Anlass wirken unmotiviert. Ein guter Ausgangspunkt liegt je nach Gesprächstempo bei 1,5–2,5 Sekunden.

> **Standardwert 1,5 Sekunden bedeutet:** Jede Reaktionsaufnahme wird mindestens 1,5 Sekunden gezeigt. Mit dem Standardzufallsfaktor von 0,2 kann sie bis zu 1,8 Sekunden lang werden.

## Cutaway-Zufallsfaktor

Wenn alle Cutaways exakt gleich lang wären, entstünde ein mechanisch-gleichmäßiger Rhythmus, der im fertigen Schnitt auffällt. Der Zufallsfaktor fügt jedem Cutaway einen zufälligen Aufschlag hinzu. Das Ziel ist keine echte Zufälligkeit, sondern eine natürliche Variation, die den automatischen Schnitt weniger maschinell anfühlen lässt.

> **Standardwert 0,2 bedeutet:** Jeder Cutaway bekommt einen zufälligen Aufschlag von 0 bis 20 % auf die eingestellte Cutaway-Länge. Bei 1,5 Sekunden Basis liegt die tatsächliche Länge also zufällig zwischen 1,5 und 1,8 Sekunden.

## Cleanup-Mindestlänge (s)

Nach dem Zusammensetzen der Timeline können sehr kurze Schnitte übrig bleiben — z.B. wenn zwei Cutaways direkt aufeinanderfolgen und dazwischen nur eine halbe Sekunde der Hauptkamera liegt. Solche Mikroschnitte sind im Schnittbild meist störend.

Der Cleanup-Pass läuft nach der gesamten Montage ein letztes Mal durch die Timeline und entfernt alle Segmente kürzer als dieser Wert. Es ist kein inhaltlicher Eingriff, sondern ein technischer Qualitätsfilter kurz vor der Übergabe der Timeline.

> **Standardwert 1,5 Sekunden bedeutet:** Alle Segmente — egal ob Hauptkamera oder Cutaway — die nach dem Zusammenbau kürzer als 1,5 Sekunden sind, werden aus der Timeline entfernt.
