# Changelog — MultiCamCutter

Nutzersichtbare Änderungen je Version. Ein Text pro Version beantwortet die Frage:
*Was ändert sich für mich?* — einfach formuliert, ohne technische Interna.
Aus diesem Abschnitt werden später die Update-Notizen (Sparkle) und die
Website-Seite erzeugt.

## 1.1.0-beta.1

**Neu: Beta-Versionen**

In den Einstellungen unter „Updates“ kannst du jetzt „Beta-Versionen erhalten“ einschalten. Dann
bekommst du neue Funktionen schon vor dem offiziellen Release. Schaltest du es wieder aus, bietet
dir die App an, zur aktuellen stabilen Version zurückzukehren.

**Neu (Beta): Einwürfe über die Mundbewegung erkennen**

Bisher hat die App kurze Einwürfe der zuhörenden Person nur am Ton erkannt und dabei viele
übersehen. Mit „Mundbewegung (Beta)“ unter Experteneinstellungen → Einwürfe achtet sie zusätzlich
darauf, ob sich der Mund der Person bewegt. Ein Schnitt kommt nur dazu, wenn sich der Mund bewegt
und gleichzeitig das eigene Mikro Ton aufnimmt. So findet die App deutlich mehr echte Einwürfe wie
„Ja“, „Krass“ oder ein kurzes Lachen. Direkt an Sprecherwechseln wird die Mundbewegung ignoriert.
Die Funktion ist standardmäßig aus und braucht etwas mehr Rechenzeit, wenn die Nicken-Erkennung
ausgeschaltet ist.

## 1.0.2

**Behoben: Gesplittete Aufnahmen wurden manchmal nicht zusammengefügt**

Hat der Rekorder eine lange Aufnahme mit mehreren Spuren in Teile aufgeteilt, erkannte die App die
Zusammengehörigkeit in manchen Fällen nicht, besonders wenn an der Übergangsstelle gerade niemand
sprach. Die Teile erschienen dann als einzelne Spuren. Das ist behoben. Bei Zoom-Rekordern ordnet die
App die Teile jetzt anhand des Rekorder-Eingangs zu, der in jeder Datei gespeichert ist. Das ist
deutlich zuverlässiger als bisher. Deine bisherigen Schnittprojekte sind nicht betroffen.

## 1.0.1

**MultiCamCutter ist jetzt kostenlos**

Du brauchst keine Lizenz und kein Abo mehr. Die Grenze von 30 Minuten pro Aufnahme fällt weg, du
kannst also beliebig lange Folgen schneiden. Den Lizenz-Bereich in den Einstellungen gibt es nicht
mehr.

## 1.0.0

**Neu: MultiCamCutter spricht Englisch**

Die App folgt jetzt der Systemsprache deines Macs: Auf einem englischen System erscheint sie auf
Englisch, sonst wie gewohnt auf Deutsch.

**Neu: Gesplittete Aufnahmen werden automatisch zusammengefügt**

Viele Rekorder, etwa der Zoom H6essential, teilen lange Aufnahmen in mehrere Dateien auf. Die App
erkennt solche Teile jetzt selbst und behandelt sie als eine durchgehende Spur. In der
Personen-Übersicht steht dann z. B. „2 Teile“. Im fertigen Schnittprojekt liegen weiterhin deine
Originaldateien, nahtlos hintereinander. Wird eine Aufnahme nicht erkannt, kannst du sie über das
Ketten-Symbol mit „Gehört zu …“ von Hand zuordnen. Eine falsche Zuordnung trennst du dort auch wieder.

**Behoben: 29,97-fps-Projekte liefen auseinander**

Bei Kameras mit 29,97 Bildern pro Sekunde (z. B. Sony, Drop-Frame) liefen die Kameras im
Schnittprojekt mit der Zeit auseinander, und Bild und Ton konnten schon ab dem Start versetzt sein.
Externe Tonaufnahmen von Rekordern lagen in solchen Projekten außerdem um ein Bild daneben. Beides
ist behoben. **Wenn du 29,97-fps-Material mit einer früheren Version geschnitten hast, exportiere
diese Projekte bitte neu.**

**Behoben: Presets**

Hast du ein Preset unter dem Namen eines mitgelieferten Presets gespeichert, schien das Speichern
wirkungslos. Außerdem zeigte die Auswahl bei zwei Presets mit gleichen Einstellungen manchmal das
falsche an. Beides funktioniert jetzt. Zum Speichern gibt es zusätzlich einen sichtbaren Button
„Preset speichern“.

## 0.6.10

**Behoben: Reaktions-Schnitte (Kopfnicken, Einwürfe) sitzen wieder genau auf der Reaktion**

In manchen Aufnahmen wurde ein Teil der Reaktions-Schnitte — besonders auf Kopfnicken — erst
gesetzt, als die Reaktion schon vorbei war, sodass der Schnitt auf eine regungslose Person fiel.
Ursache war der Bilderkennungs-Filter („Ungünstige Cutaways verschieben"), der solche Momente in
seltenen Fällen fälschlich verschob. Reaktions-Schnitte werden davon jetzt nicht mehr verschoben —
sie bleiben exakt am erkannten Moment. Für Kamera-Umschnitte in langen Passagen bleibt der Filter
aktiv und greift insgesamt etwas zurückhaltender.

**Behoben: vereinzelte Ein-Bild-Fragmente in der Timeline**

An wenigen Stellen konnten winzige Bruchstücke zwischen zwei Umschnitten stehen bleiben — ein
kurzes Aufblitzen der Basiskamera. Diese werden jetzt zuverlässig entfernt.

## 0.6.9

**Neu: anonyme Nutzungsstatistik — freiwillig**

Beim ersten Start nach diesem Update fragt die App einmal, ob sie anonyme
Nutzungszahlen senden darf: wie viele Kameras, Mikrofone und Personen ein Projekt hat,
wie lange die Aufnahmen und ein Durchlauf dauern und auf welchem Mac. Das hilft, die App
gezielt zu verbessern — etwa zu erkennen, welche Schritte am meisten Zeit kosten.
Übertragen werden ausschließlich Zahlen, niemals Namen, Dateien oder Pfade, und alles
bleibt anonym. Die Abfrage ist freiwillig und lässt sich jederzeit in den Einstellungen
unter „Datenschutz" wieder abschalten.

**Behoben: der Update-Ablauf erscheint jetzt auf Deutsch**

Die Dialoge beim Suchen und Installieren von Updates wurden bisher auf Englisch
angezeigt, obwohl die App sonst durchgehend deutsch ist. Sie erscheinen jetzt ebenfalls
auf Deutsch.

**Verbessert: klarere Beschriftungen und Hilfetexte**

Zahlreiche Bezeichnungen und Erklärungen in den Einstellungen wurden überarbeitet und
vereinheitlicht — einige Regler heißen jetzt eindeutiger (etwa „Min./Max. Schnittlänge"
und „Pausen kürzen"). An der Funktion ändert sich nichts.

## 0.6.8

**Behoben: Kopfnicken-Erkennung ließ die Analyse abbrechen**

In den letzten Versionen brach die Analyse ab, sobald die Kopfnicken-Erkennung an der
Reihe war — eine interne Komponente fehlte im ausgelieferten Programm. Reaktions-Schnitte
auf Kopfnicken funktionierten dadurch nicht. Das ist behoben; die Erkennung läuft wieder
vollständig durch.

**Neu: Quellen, die sich nicht automatisch synchronisieren lassen, stoppen nicht mehr den ganzen Lauf**

Ließ sich eine Ton- oder Videospur nicht automatisch mit den anderen synchronisieren,
brach bisher der komplette Durchlauf ab. Jetzt zeigt die App die betroffene Quelle, und du
entscheidest pro Quelle: einen Zeitversatz von Hand eingeben (mit Vorschlag) oder die
Quelle vom Schnitt ausschließen. Die übrigen Quellen laufen normal weiter.

**Behoben: falsche Zuordnung nach einer neuen Datei im bekannten Ordner**

Hattest du einen Ordner schon einmal geöffnet und danach eine neue Tonspur
hineinkopiert, konnte die App eine Kamera der falschen Person zuordnen. Die Zuordnung
wird jetzt anhand der Dateinamen wiederhergestellt und bleibt korrekt.

**Verbessert: mehrere Totalen werden jetzt genutzt**

Markierst du mehr als eine Kamera als Totale, wechselt der Schnitt jetzt zwischen ihnen —
der Reihe nach oder zufällig, einstellbar in den Experteneinstellungen — statt immer nur
die erste zu verwenden.

**Weitere Verbesserungen**

Der Fortschrittsbalken im Dock zeigt den Fortschritt ehrlicher: die lange
Kopfnicken-Analyse dominiert ihn jetzt, statt dass er kurz vor „fertig" lange hängt. Und
das Fenster bleibt während der Analyse fest — es lässt sich in dieser Zeit nicht mehr
versehentlich verziehen.

## 0.6.7

**Behoben: AAF-Export importiert jetzt fehlerfrei in Premiere Pro**

Bisher zeigte Premiere Pro die Medien eines importierten AAF als offline an und
suchte nach falsch benannten Dateien — vor allem beim Video. Der Export ist jetzt
so aufgebaut, dass Premiere alle Clips automatisch mit dem richtigen Material
verknüpft. In DaVinci Resolve klappte der Import schon vorher; beide Programme
sind damit voll unterstützt.

**Verbessert: Umwandlung abweichender Bildraten deutlich schneller**

Müssen Videodateien auf die Timeline-Bildrate umgewandelt werden, nutzt die App
jetzt die Hardware-Beschleunigung deines Macs. Das ist je nach Material rund drei-
bis viermal schneller (aus einer halben Stunde werden wenige Minuten), und der
Prozessor bleibt dabei frei. Die App wählt automatisch das passende Format, damit
die Kopie qualitativ dem Original entspricht und weiter gradebar bleibt. Die
Qualität lässt sich in den Einstellungen feinjustieren.

**Neu: Schnitte im AAF nach ihrem Grund benannt**

Jeder Schnitt im exportierten AAF trägt jetzt einen sprechenden Namen — bei
Sprecherschnitten die Person, sonst den Grund (z. B. „Übergang"). So sieht man
beim Sichten sofort, warum an einer Stelle geschnitten wurde. Das Namensmuster
lässt sich in den Einstellungen frei anpassen; wer lieber genau einen Clip pro
Kamera möchte, schaltet die Funktion dort ab.

**Behoben: Tonvorschau lief beim Seitenwechsel weiter**

Spielte man auf der ersten Seite eine Tonspur ab und wechselte die Seite, lief
der Ton unsichtbar weiter. Er stoppt jetzt beim Seitenwechsel.

**Weitere Verbesserungen**

Die Filter-Prompts der Bilderkennung (CLIP) erscheinen in den Einstellungen nur
noch, wenn das Modell installiert ist. Kurzlebige Hinweis-Karten zeigen mit einem
kleinen ablaufenden Ring, wann sie sich von selbst schließen.

## 0.6.6

**Behoben: möglicher Absturz beim ersten Start nach einem Update**

In seltenen Fällen konnte die App direkt nach einem Update beim Neustart
abstürzen. Ursache war ein Icon, das im Moment des Erststarts noch nicht bereit
war. Das kann jetzt nicht mehr passieren — fehlt eine Grafik kurz, bleibt sie
einfach leer, statt die App zu beenden.

**Neu: Trennung jeder Tonspur sichtbar**

Auf jeder Audiokarte steht jetzt, wie gut die Spur getrennt ist — also um wie
viel lauter sie ist als die anderen, wenn diese Person spricht (in dB). So
erkennst du auf einen Blick, welche Spuren sauber sind und welche viel
Übersprechen haben, und bekommst über mehrere Folgen ein Gefühl dafür, was
normal ist. Der Wert ist rein informativ und beeinflusst den Schnitt nicht.

**Verbessert: Fortschritt der Bildraten-Umwandlung am Dock-Symbol**

Wandelt die App Videodateien auf die Timeline-Bildrate um, zeigt jetzt auch das
Dock-Symbol den Fortschritt. Das dauert je nach Material einige Minuten — so
siehst du auch mit der App im Hintergrund, wie weit sie ist.

## 0.6.5

**Neu: Wellenform für jede Tonspur — mit Anhören per Klick**

Jede Audiokarte zeigt jetzt die Wellenform ihrer Spur, und ein Klick spielt sie
direkt ab. So prüfst du in Sekunden, ob die Zuordnung stimmt und ob jede Person
auf ihrer eigenen Spur am deutlichsten zu hören ist. Die Wellenformen werden
einmal berechnet (mit Fortschrittsanzeige) und gespeichert — beim nächsten
Öffnen des Ordners erscheinen sie sofort.

**Bekannte Ordner öffnen sich deutlich schneller**

Vorschaubilder, Tonanalyse und Hörproben werden beim ersten Scan gespeichert
und danach wiederverwendet, statt jedes Mal neu berechnet zu werden.

**Fenster & Oberfläche**

Das Fenster passt seine Höhe auf jeder Seite automatisch dem Inhalt an — kein
Leerraum mehr unter der Übersicht, kein manuelles Ziehen nötig (die Breite ist
jetzt fest). Ab zwei Tonspuren erscheinen die Audiokarten zweispaltig,
kurzlebige Hinweise blenden sich nach ein paar Sekunden selbst aus, und die
App nutzt jetzt dasselbe Icon-Set wie die Website.

**Warnung bei abweichender Bildrate direkt an der Kamera**

Passt die Bildrate einer Videodatei nicht zum Projekt, steht die Warnung jetzt
direkt auf der betroffenen Kamera-Karte — man muss nicht mehr suchen, welche
Datei gemeint ist.

**Mehrplatz-Lizenzen: belegte Arbeitsplätze sichtbar**

Bei Lizenzen mit mehreren Arbeitsplätzen zeigen die Einstellungen jetzt an, wie
viele Plätze gerade belegt sind (z. B. „2 von 3 belegt").

**Updates werden schneller gefunden**

Die App prüft jetzt stündlich auf neue Versionen statt einmal täglich — Updates
kommen damit spürbar früher an.

## 0.6.4

**Behoben: 24-bit-Tonspuren wurden falsch gelesen**

Tonspuren in 24 bit — der Standard vieler Field-Recorder — wurden intern als
Rauschen fehlinterpretiert. Die Sprechererkennung fand dann keine Unterschiede
zwischen den Spuren, und der Lauf brach mit einem technischen Fehler ab. Jetzt
werden alle Bit-Tiefen korrekt dekodiert. Die Tonsynchronisierung war von dem
Fehler nie betroffen.

**Verständliche Meldung statt Absturz**

Findet die Sprechererkennung keine Unterschiede zwischen den Tonspuren, erklärt
die App jetzt die wahrscheinlichen Ursachen (z. B. Mix statt Einzelspuren) und
empfiehlt, die Spuren einzeln anzuhören — statt mit einer Fehlermeldung ohne
Zusammenhang abzubrechen.

**Neu: Hinweis bei bekannten Ordnern**

Öffnest du einen Ordner erneut, springt die App wie gewohnt direkt zur
Übersicht — sagt dir jetzt aber auch, dass deine früheren Zuordnungen geladen
wurden. Über „Zuordnung zurücksetzen" im Hinweis startest du bei Bedarf sauber
von vorn.

## 0.6.3

**Neu: Mehr als zwei Nahaufnahmen — Setups mit drei und mehr Personen**

Bisher konnte der Schnitt nur zwischen zwei Nahaufnahmen wählen; eine dritte
Person auf einer eigenen Kamera blieb im Schnitt stumm. Jetzt erkennt die App
beliebig viele Sprecher und schneidet jede Person auf die Kamera, die sie am
engsten zeigt — eine dritte Person, die nur auf der Totale zu sehen ist, landet
also auf der Totale. Sprechen mehrere gleichzeitig, wird auf die kleinste
Einstellung geschnitten, die alle Beteiligten zeigt, und auch die
Bildsprache-Übergänge funktionieren über mehrere Personen. Setups mit genau zwei
Personen verhalten sich unverändert.

**Neu: Mehrspur-Recorder**

Kommen alle Tonspuren aus einem Mehrspur-Recorder, kannst du das jetzt im Schritt
„Personen" bestätigen. Dann wird eine Spur, auf der gerade niemand spricht, nicht
mehr fälschlich als „nicht synchronisierbar" abgelehnt — sie übernimmt den
gemeinsamen Versatz der übrigen Spuren.

**Zuverlässigere Tonsynchronisierung**

Fängt eine Person erst spät an zu sprechen, wurde ihre Spur bisher manchmal nicht
eingemessen. Die Synchronisierung sucht jetzt die sprechreichste Stelle einer
Spur, statt stur den Anfang — auch spät einsetzende Sprecher werden zuverlässig
gefunden.

## 0.6.2

Klarere Meldungen bei der Tonsynchronisierung:

- Lässt sich eine Tonspur nicht sicher einordnen, nennt die Meldung jetzt den
  Dateinamen statt einer internen Bezeichnung (etwa „MIC3"). So ist sofort
  erkennbar, welche deiner Dateien betroffen ist.
- Das Protokoll zeigt am Anfang, welche Datei zu welcher Spur gehört.

## 0.6.1

Kleine Korrekturen an der Oberfläche:

- Der Hinweis beim ersten Start ist schlanker: ein Punkt, der eher die Funktionsweise
  als eine Anforderung ans Material beschrieb, ist entfallen.
- In der Übersicht ragte ein sehr langer Kameraname aus seiner Markierung heraus. Er
  wird jetzt sauber gekürzt und passt sich der Fensterbreite an.

## 0.6.0

**Neu: Bildsprache — sanftere Übergänge bei mehreren Einstellungsgrößen**

Wenn dein Material mehr als eine Einstellungsgröße hat — zum Beispiel eine Totale,
auf der mehrere Personen zu sehen sind — führt der Schnitt Wechsel jetzt über die
größere Einstellung, statt hart von einer Nahaufnahme zur nächsten zu springen.
Das wirkt organischer und ruhiger.

Steuerbar in den Experteneinstellungen unter „Bildsprache": beim Sprecherwechsel
standardmäßig aktiv, für Reaktionen (Nicken, Einwürfe, Pausen) einzeln zuschaltbar.
Ein Cooldown verhindert, dass dieselbe Totale zu oft hintereinander kommt. Bei
Setups mit nur einer Einstellungsgröße ändert sich nichts — die Gruppe erscheint
dann gar nicht erst.

**Mehr als zwei Kameras**

Setups mit mehreren Kameras sind jetzt möglich, solange sich der Sprecherwechsel
zwischen zwei Nahaufnahmen abspielt. Zusätzliche Totalen sind erlaubt und werden
für Cutaways und Übergänge genutzt.

**Zuverlässigere Synchronisierung**

Zusätzliche Mikrofone und weitere Kameras wurden bisher nicht immer korrekt
eingemessen. Das ist behoben: jede Quelle wird einzeln vermessen und gegengeprüft.
Unsichere oder unmögliche Synchronisierungen — etwa durch eine unvollständige Datei
oder einen zu langen Vorlauf — werden jetzt erkannt und mit einer klaren Meldung
abgebrochen, statt still verschoben im Schnitt zu landen.

**Hilfetexte zurück**

Neben jedem Parameter in den Einstellungen steht wieder ein (?) mit einer kurzen,
verständlichen Erklärung.
