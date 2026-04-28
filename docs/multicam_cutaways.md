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

Die Erkennung nutzt MediaPipe, eine Gesichtserkennungsbibliothek von Google, um Gesichtspunkte pro Frame zu verfolgen. Für die Nickerkennung werden zwei Punkte beobachtet: Nasenspitze und Nasenrücken. Über ein gleitendes Zeitfenster (2 Sekunden) wird das Bewegungsmuster analysiert — der Detektor sucht nach mehrfachen Richtungswechseln (Oszillation), die typisch für echtes Kopfnicken sind. Die Analyse läuft direkt auf den Videodateien.

Verschiedene Nickmuster sind als **Patterns** definiert, die unabhängig aktiviert und deaktiviert werden können. Aktuell gibt es zwei Patterns: **Oscillation** erkennt typisches Nicken mit mindestens zwei Richtungswechseln, **Strong Oscillation** erkennt kräftigeres Nicken mit mindestens drei Richtungswechseln und höherer Amplitude. Beide Patterns prüfen zusätzlich, ob die Geschwindigkeitskurven von Nasenspitze und Nasenrücken synchron verlaufen — bei echtem Kopfnicken ist diese Korrelation extrem hoch, bei zufälligem Rauschen oder Artefakten nicht. Außerdem wird geprüft, ob die Schwingung gedämpft ist (wie eine Feder, die ausschwingt) und ob die Bewegung nicht zu stark seitlich verläuft (Kopfschütteln-Filter).

Das Pattern mit der höchsten Konfidenz gewinnt. Der Cutaway beginnt automatisch am Anfang der sichtbaren Nickbewegung, nicht erst am Ende der Erkennung. Die Cutaway-Dauer passt sich dynamisch an die tatsächliche Länge der Bewegung an — kurze Nicker bekommen die eingestellte Mindestdauer, längere Bewegungen werden vollständig gezeigt.

#### Min. Konfidenz (%)

Die Konfidenz wird aus mehreren Faktoren berechnet: Anzahl der Richtungswechsel, Frequenz der Schwingung, Stärke der Dämpfung, Korrelation zwischen Nasenspitze und Nasenrücken sowie Amplitude der Bewegung. Je nach Pattern werden diese Faktoren unterschiedlich gewichtet. Ein schwaches Nicken mit wenigen Richtungswechseln erhält eine niedrigere Konfidenz als ein deutliches, kräftiges Nicken. Höhere Werte reduzieren Fehlschnitte, können aber dazu führen, dass subtilere Nicker ignoriert werden.

> **Standardwert 60 % bedeutet:** Nur Nickbewegungen, deren gewichtete Bewertung mindestens 60 % erreicht, werden als Cutaway verwendet.

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
