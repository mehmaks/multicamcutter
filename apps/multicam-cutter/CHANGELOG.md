# Changelog — MultiCamCutter

Nutzersichtbare Änderungen je Version. Ein Text pro Version beantwortet die Frage:
*Was ändert sich für mich?* — einfach formuliert, ohne technische Interna.
Aus diesem Abschnitt werden später die Update-Notizen (Sparkle) und die
Website-Seite erzeugt.

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
