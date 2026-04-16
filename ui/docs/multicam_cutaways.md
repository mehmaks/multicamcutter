# Cutaway-Regeln

Cutaways sind Schnitte auf die zuhörende Person — Reaktionsaufnahmen, die dem Gespräch Tiefe geben und das Bild lebendig halten. Der Multicam Cutter erkennt zwei Arten von Ereignissen, die einen Cutaway auslösen: **Kopfnicken** und **Sprachreaktionen**.

---

## Kopfnicken

Die Erkennung nutzt MediaPipe, eine Gesichtserkennungsbibliothek von Google, um 468 Gesichtspunkte pro Frame zu verfolgen. Für die Nickerkennung wird die vertikale Bewegung der Nasenspitze beobachtet: Bewegt sie sich innerhalb kurzer Zeit stark genug nach unten und wieder nach oben, gilt das als Nicken. Die Analyse läuft direkt auf den Videodateien.

### Min. Konfidenz (%)

MediaPipe liefert für jede Gesichtserkennung einen Konfidenzwert: Wie sicher ist das Modell, dass es wirklich ein Gesicht erkannt hat? Bei schlechter Beleuchtung, starker Bewegung oder ungünstigen Winkeln kann dieser Wert niedrig sein. Frames mit geringer Konfidenz werden ausgeschlossen, da die Bewegungsdaten dort unzuverlässig sind. Höhere Werte reduzieren Fehlschnitte, können aber dazu führen, dass echte Nicken ignoriert werden, wenn das Gesicht kurz schlecht sichtbar war.

> **Standardwert 88 % bedeutet:** Frames, bei denen MediaPipe das Gesicht mit weniger als 88 % Sicherheit erkannt hat, werden für die Nickanalyse übersprungen — z.B. wenn das Gesicht im Schatten liegt oder kurz verdeckt ist.

### Nod-Threshold (px)

Nicht jede Kopfbewegung ist ein bewusstes Nicken. Menschen bewegen den Kopf ständig leicht — beim Sprechen, beim Gestikulieren, beim Schlucken. Der Threshold filtert kleine Zufallsbewegungen heraus: Nur wenn die Nase sich um mindestens diesen Pixelwert vertikal bewegt, wird die Bewegung als potentielles Nicken registriert. Der Wert ist auf eine Framehöhe von 2160 Pixeln (4K) kalibriert.

> **Standardwert 80 px bedeutet:** Die Nasenspitze muss sich bei 4K-Material mindestens 80 Pixel vertikal bewegen — etwa 3,7 % der Bildhöhe — damit die Bewegung überhaupt als Nicken in Betracht kommt.

### Min. Nod-Dauer (s)

Fügt eine Zeitbedingung hinzu: Die Bewegung muss lang genug anhalten, um als echtes Nicken zu gelten. Zu kurze Bewegungen — z.B. ein kurzer Zuck beim Lachen — werden so herausgefiltert.

> **Standardwert 0,65 Sekunden bedeutet:** Eine Kopfbewegung muss mindestens 0,65 Sekunden andauern, um als gültiges Nicken zu zählen. Schnellere Bewegungen, die häufig beim Sprechen oder Lachen entstehen, werden ignoriert.

### Pre-Roll (Frames)

Nickbewegungen werden erkannt, wenn sie passieren — aber der passende Cutaway-Einstiegspunkt liegt oft etwas davor. Setzt man den Schnitt direkt auf den erkannten Frame, beginnt die Reaktion mitten in der Bewegung. Pre-Roll verschiebt den Cutaway-Start nach vorne in der Zeit, sodass man die Reaktion von Anfang an sieht.

> **Standardwert 15 Frames bedeutet** bei 25 fps: Der Cutaway beginnt 0,6 Sekunden vor dem erkannten Nicken, sodass die zuhörende Person schon zu sehen ist, bevor die Kopfbewegung startet.

### Auto Accuracy

Wenn sich eine Person sehr nah an der Kamera befindet, nimmt das Gesicht einen großen Teil des Bildes ein und Bewegungen in Pixeln sind entsprechend groß. Sitzt jemand weiter entfernt, fällt die gleiche Kopfbewegung in Pixeln viel kleiner aus. Auto Accuracy gleicht diesen Unterschied automatisch aus, indem der Threshold dynamisch an die erkannte Gesichtsgröße angepasst wird. Besonders nützlich bei Totalen, auf denen mehrere Personen gleichzeitig sichtbar sind.

---

## Sprachreaktionen

Sprachreaktionen sind kurze Laute der zuhörenden Person während der andere spricht: ein „Genau", „Mhm", Lachen, ein zustimmendes Geräusch. Diese Momente sind wertvolle Schnittanlässe, weil sie emotional aufgeladen sind — aber oft zu kurz und zu spontan für die Nickenerkennung.

Es wird eine gleitende Baseline berechnet — ein Durchschnittspegel der letzten Sekunden, der den normalen Ruhepegel der Off-Kamera-Person repräsentiert. Eine Reaktion wird erkannt, wenn der aktuelle Pegel sprunghaft über diese Baseline steigt.

### Rise (dB über Baseline)

Legt fest, wie stark dieser Pegelanstieg sein muss. Höhere Werte reagieren nur auf klare Einwürfe wie „Genau!" oder Lachen.

> **Standardwert 10 dB bedeutet:** Die Off-Kamera-Person muss kurz um den Faktor ~3 lauter werden als ihr gleitender Ruhepegel, damit der Moment als Reaktion zählt. Ein leises Räuspern oder Atemgeräusch reicht dafür in der Regel nicht aus.

### Min. Burst-Dauer (s)

Zu kurze Ausschläge werden ignoriert — das könnten Atemgeräusche, Stühlerücken oder kurze Rauschspitzen sein.

> **Standardwert 0,2 Sekunden bedeutet:** Ein Lautstärkeausschlag muss mindestens 200 Millisekunden andauern, um als Reaktion erkannt zu werden. Kürzere Spitzen werden herausgefiltert.

### Max. Burst-Dauer (s)

Zu lange Ausschläge werden ebenfalls ignoriert — dann spricht die Person selbst, und die Sprecher-Erkennung übernimmt die Steuerung.

> **Standardwert 1,5 Sekunden bedeutet:** Alles, was länger als 1,5 Sekunden laut ist, wird nicht als Reaktion gewertet — der Einwurf ist dann lang genug, um als eigenständiger Sprechbeitrag zu gelten, und wird ignoriert.

### Min. Konfidenz (%)

Wie sicher die Erkennung sein muss, bevor ein Einwurf als Schnitt verwendet wird. Die Konfidenz wird direkt aus dem durchschnittlichen Pegelanstieg des Bursts berechnet: Bei einem Anstieg von 10 dB über Baseline liegt sie bei 100 %, bei 5 dB bei 75 %. Der Parameter wirkt daher vor allem als Qualitätsfilter, wenn der Rise-Wert niedrig eingestellt ist — bei hohem Rise-Wert erreichen erkannte Bursts ohnehin fast immer die maximale Konfidenz.

> **Standardwert 90 % bedeutet:** Nur Erkennungen, bei denen das System zu mindestens 90 % sicher ist, dass es sich um eine echte Reaktion handelt, werden als Schnittanlass verwendet.

### Peak-Detektion

Standardmäßig wird der Durchschnittspegel jedes Zeitfensters ausgewertet. Bei sehr kurzen, impulsartigen Geräuschen — ein kurzes „Ha!", ein Schnalzlaut — kann der Durchschnitt so niedrig bleiben, dass die Reaktion nicht erkannt wird, obwohl der lauteste Moment deutlich über der Baseline liegt. Peak-Detektion wechselt auf den maximalen Momentanpegel pro Fenster. Das macht die Erkennung sensibler für solche kurzen Spitzen, auf Kosten einer leicht erhöhten Anfälligkeit für einzelne Rauschspitzen.
