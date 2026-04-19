## Cutaway-Regeln

Cutaways sind Schnitte auf die zuhörende Person — Reaktionsaufnahmen, die dem Gespräch Tiefe geben und das Bild lebendig halten. Der Multicam Cutter erkennt zwei Arten von Ereignissen, die einen Cutaway auslösen: **Kopfnicken** und **Sprachreaktionen**. Die Einstellungen sind in drei Spalten organisiert: Generelle Regeln, Kopfnicken und Sprachreaktionen.

---

### Generell

Diese Einstellungen gelten für alle Cutaway-Typen — sowohl Kopfnicken als auch Sprachreaktionen.

#### Cutaway-Länge (s)

Legt fest, wie lange eine Reaktionsaufnahme mindestens gezeigt wird. Der tatsächliche Cutaway kann durch den Zufallsfaktor länger werden. Zu kurze Cutaways (unter ~1 Sekunde) wirken wie ein Versehen, zu lange (über 3–4 Sekunden) ohne erkennbaren Anlass wirken unmotiviert. Gilt für Kopfnicken und Max-Shotlänge-Cutaways — Sprachreaktionen bestimmen ihre Dauer organisch aus dem Audiosignal. Liegt der Wert unterhalb der Cleanup-Mindestlänge, werden die Cutaways im abschließenden Cleanup-Pass wieder entfernt.

> **Standardwert 1,5 Sekunden bedeutet:** Jede Reaktionsaufnahme wird mindestens 1,5 Sekunden gezeigt. Mit dem Standardzufallsfaktor von 0,2 kann sie bis zu 1,8 Sekunden lang werden.

#### Pre-Roll (Frames)

Reaktionen werden erkannt, wenn sie passieren — aber der passende Cutaway-Einstiegspunkt liegt oft etwas davor. Setzt man den Schnitt direkt auf den erkannten Frame, beginnt die Reaktion mitten in der Bewegung. Pre-Roll verschiebt den Cutaway-Start nach vorne in der Zeit, sodass man die Reaktion von Anfang an sieht. Gilt für alle Cutaway-Typen.

> **Standardwert 15 Frames bedeutet** bei 25 fps: Der Cutaway beginnt 0,6 Sekunden vor dem erkannten Ereignis, sodass die zuhörende Person schon zu sehen ist, bevor die Reaktion startet.

#### Zufallsfaktor

Wenn alle Cutaways exakt gleich lang wären, entstünde ein mechanisch-gleichmäßiger Rhythmus, der im fertigen Schnitt auffällt. Der Zufallsfaktor fügt jedem Cutaway einen zufälligen Aufschlag hinzu. Gilt für Kopfnicken und Max-Shotlänge-Cutaways.

> **Standardwert 0,2 bedeutet:** Jeder Cutaway bekommt einen zufälligen Aufschlag von 0 bis 20 % auf die eingestellte Cutaway-Länge. Bei 1,5 Sekunden Basis liegt die tatsächliche Länge also zufällig zwischen 1,5 und 1,8 Sekunden.

---

### Kopfnicken

Die Erkennung nutzt MediaPipe, eine Gesichtserkennungsbibliothek von Google, um 468 Gesichtspunkte pro Frame zu verfolgen. Für die Nickerkennung wird die vertikale Bewegung der Nasenspitze beobachtet: Bewegt sie sich innerhalb kurzer Zeit stark genug nach unten und wieder nach oben, gilt das als Nicken. Die Analyse läuft direkt auf den Videodateien.

#### Min. Konfidenz (%)

Die Konfidenz wird aus der Deutlichkeit der Nickbewegung selbst berechnet: Das Auf-Ab-Auf-Pattern wird in drei Segmente geteilt, und der schwächste Übergang (hin oder zurück) bestimmt den Wert. Je gleichmäßiger und kräftiger die Bewegung in beide Richtungen ist, desto höher die Konfidenz. Ein zaghaftes Nicken, bei dem der Kopf kaum zurückkehrt, erhält eine niedrige Konfidenz — ein deutliches Nicken mit klarer Rückkehr zur Ausgangsposition erreicht 100 %. Höhere Werte reduzieren Fehlschnitte, können aber dazu führen, dass subtilere Nicken ignoriert werden.

> **Standardwert 88 % bedeutet:** Nur Nickbewegungen, bei denen beide Übergänge — nach unten und zurück — mindestens 88 % der erwarteten Stärke erreichen, werden als Cutaway verwendet.

#### Nod-Threshold (px)

Nicht jede Kopfbewegung ist ein bewusstes Nicken. Menschen bewegen den Kopf ständig leicht — beim Sprechen, beim Gestikulieren, beim Schlucken. Der Threshold filtert kleine Zufallsbewegungen heraus: Nur wenn die Nase sich um mindestens diesen Pixelwert vertikal bewegt, wird die Bewegung als potentielles Nicken registriert. Der Wert ist auf eine Framehöhe von 2160 Pixeln (4K) kalibriert.

> **Standardwert 80 px bedeutet:** Die Nasenspitze muss sich bei 4K-Material mindestens 80 Pixel vertikal bewegen — etwa 3,7 % der Bildhöhe — damit die Bewegung überhaupt als Nicken in Betracht kommt.

#### Min. Nod-Dauer (s)

Fügt eine Zeitbedingung hinzu: Die Bewegung muss lang genug anhalten, um als echtes Nicken zu gelten. Zu kurze Bewegungen — z.B. ein kurzer Zuck beim Lachen — werden so herausgefiltert.

> **Standardwert 0,65 Sekunden bedeutet:** Eine Kopfbewegung muss mindestens 0,65 Sekunden andauern, um als gültiges Nicken zu zählen. Schnellere Bewegungen, die häufig beim Sprechen oder Lachen entstehen, werden ignoriert.

#### Auto Accuracy

Wenn sich eine Person sehr nah an der Kamera befindet, nimmt das Gesicht einen großen Teil des Bildes ein und Bewegungen in Pixeln sind entsprechend groß. Sitzt jemand weiter entfernt, fällt die gleiche Kopfbewegung in Pixeln viel kleiner aus. Auto Accuracy gleicht diesen Unterschied automatisch aus, indem der Threshold dynamisch an die erkannte Gesichtsgröße angepasst wird. Besonders nützlich bei Totalen, auf denen mehrere Personen gleichzeitig sichtbar sind.

---

### Sprachreaktionen

Sprachreaktionen sind kurze Laute der zuhörenden Person während der andere spricht: ein „Genau", „Mhm", Lachen, ein zustimmendes Geräusch. Diese Momente sind wertvolle Schnittanlässe, weil sie emotional aufgeladen sind — aber oft zu kurz und zu spontan für die Nickenerkennung.

Die Erkennung arbeitet mit einer gleitenden Audio-Baseline — einem geglätteten Durchschnittspegel der letzten Sekunden. Statt den absoluten Pegel mit der Baseline zu vergleichen, misst der Algorithmus die **Anstiegsrate der Baseline** selbst: Steigt sie innerhalb eines kurzen Zeitfensters sprunghaft an, wird ein Cutaway ausgelöst. Die Dauer ergibt sich organisch aus dem Audiosignal — der Cutaway hält, solange die Baseline nahe ihrem Peak bleibt, und endet, wenn sie wieder abfällt. Eine S-Kurven-Glättung des Baseline-Decays sorgt dafür, dass Cutaways natürlich ausklingen statt abrupt abzubrechen.

#### Rise (dB)

Legt fest, wie stark die Baseline innerhalb des Messfensters ansteigen muss, um einen Cutaway auszulösen. Höhere Werte reagieren nur auf klare Einwürfe wie „Genau!" oder Lachen, niedrigere Werte fangen auch leisere Reaktionen ein.

> **Standardwert 6 dB bedeutet:** Die Baseline muss um mindestens 6 dB ansteigen — etwa eine Verdopplung der wahrgenommenen Lautstärke — damit der Moment als Reaktion erkannt wird.

#### Max. Cutaway-Dauer (s)

Sicherheitsbegrenzung für die maximale Dauer eines Sprach-Cutaways. Im Normalfall endet der Cutaway organisch, wenn die Baseline wieder abfällt. Dieser Parameter greift nur als Obergrenze, falls die Baseline ungewöhnlich lange erhöht bleibt.

> **Standardwert 2,5 Sekunden bedeutet:** Selbst wenn die Baseline erhöht bleibt, wird der Cutaway nach spätestens 2,5 Sekunden beendet.
