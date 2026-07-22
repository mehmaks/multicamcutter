# Changelog — MultiCamCutter

Nutzersichtbare Änderungen je Version. Ein Text pro Version beantwortet die Frage:
*Was ändert sich für mich?* — einfach formuliert, ohne technische Interna.
Aus diesem Abschnitt werden später die Update-Notizen (Sparkle) und die
Website-Seite erzeugt.

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
