# Nodding Patterns — Parameter-Referenz

## Global

| Parameter | Einfluss |
|-----------|----------|
| `nod_threshold` | Mindest-Amplitude (in Pixel bei `calibration_height`) damit eine Kopfbewegung als Nicken zählt. Niedriger = empfindlicher, fängt auch schwache Nods, aber mehr FP-Risiko. |
| `cooldown_s` | Wartezeit nach einem erkannten Nicken, bevor das nächste erkannt werden kann. Verhindert Doppel-Detektionen desselben Nickens. |
| `settle_s` | Beobachtungsfenster nach der ersten Detection. Innerhalb dieser Zeit wird weiter geprüft, ob eine stärkere Confidence erreicht wird — erst danach wird das Event gefeuert. |
| `auto_accuracy_ref` | Referenzwert für die Gesichtsgröße (Stirn-Kinn-Abstand als Anteil der Bildhöhe). Gesichter, die größer oder kleiner sind als dieser Wert, bekommen einen proportional angepassten Threshold. |
| `analysis_width` | Breite in Pixel, auf die das Video vor der Analyse skaliert wird. Geringere Werte beschleunigen die Analyse, reduzieren aber die Landmark-Genauigkeit. |
| `smooth_kernel` | Größe des Glättungsfensters für die Nose-Y-Kurve. Höhere Werte filtern Rauschen, können aber schnelle Bewegungen verschlucken. |
| `calibration_height` | Referenz-Auflösung für den `nod_threshold`. Der Threshold wird proportional skaliert, wenn das analysierte Video eine andere Höhe hat. |

## Pattern-Parameter

### Allgemein

| Parameter | Einfluss |
|-----------|----------|
| `name` | Interner Name des Patterns, wird in die Reaction-JSON geschrieben. |
| `description` | Beschreibung, nur zur Dokumentation. |
| `enabled` | Pattern an/aus. Deaktivierte Patterns werden bei der Analyse komplett übersprungen. |
| `window_s` | Zeitfenster in Sekunden, das für die Pattern-Erkennung betrachtet wird. Längere Fenster erlauben langsamere Nods, brauchen aber auch mehr Frames mit konsistenter Bewegung. |

### Filters

| Parameter | Einfluss |
|-----------|----------|
| `min_reversals` | Mindestanzahl Richtungswechsel (runter-rauf oder rauf-runter). Ein typisches Nicken hat 2-3 Reversals. Höhere Werte erfordern deutlicheres/längeres Nicken. |
| `max_reversals` | Obergrenze für Richtungswechsel. Begrenzt z.B. hektisches Kopfwackeln. `null` = keine Obergrenze. |
| `max_reversal_gap` | Maximaler Abstand (in Frames) zwischen zwei aufeinanderfolgenden Richtungswechseln. Kleinere Werte fordern schnelleres Nicken, größere Werte erlauben langsamere/emphatische Bewegungen. |
| `min_damping` | Mindest-Dämpfungsfaktor: Wie stark muss die zweite Bewegung gegenüber der ersten abnehmen? Wert 0.3 = die zweite Bewegung muss mindestens 30% kleiner sein. `null` = kein Dämpfungszwang, erlaubt auch emphatisches Nicken wo die Folgebewegung gleich groß oder größer ist. |
| `min_amplitude_ratio` | Verhältnis der kleinsten zur größten Teilbewegung. Stellt sicher, dass alle Bewegungen des Nickens ähnlich groß sind und nicht nur eine stark und der Rest minimal. `null` = keine Einschränkung. |
| `min_correlation` | Mindest-Korrelation der Nose-Y-Kurve mit einer idealen Sinuswelle. Hohe Werte (0.85+) fordern ein sauberes, gleichmäßiges Auf-und-Ab. Niedrigere Werte erlauben unregelmäßigere Bewegungen. |
| `x_drift_ratio` | Wie viel horizontale Bewegung (X) relativ zur vertikalen (Y) toleriert wird. Höhere Werte sind strenger — reines Nicken hat wenig X-Drift. Zusätzlich wird Tilt (Kopfneigung) und Yaw (Halbprofil) automatisch korrigiert, bevor dieser Wert geprüft wird. |
| `amplitude_factor` | Multiplikator auf den globalen `nod_threshold` für dieses Pattern. Werte < 1.0 senken die Schwelle (empfindlicher), Werte > 1.0 fordern stärkere Bewegungen. |
| `dynamic_threshold` | Erlaubt eine Absenkung des Thresholds, wenn das Bewegungsmuster ansonsten sehr überzeugend ist (viele Reversals, hohe Korrelation). `max_reduction` bestimmt, wie weit der Threshold maximal gesenkt werden darf (0.4 = bis zu 40%). `null` = keine dynamische Anpassung. |
| `return_to_baseline` | Prüft, ob der Kopf nach dem Nicken in die Ausgangsposition zurückkehrt. `null` = deaktiviert (aktuell bei allen Patterns). |
| `max_v_duration_s` | Maximale Dauer einer einzelnen V-förmigen Bewegung (runter-rauf). Begrenzt sehr langsame Kopfbewegungen, die kein Nicken sind. `null` = keine Begrenzung. |

### Confidence

| Parameter | Einfluss |
|-----------|----------|
| `weights` | Gewichtung der einzelnen Faktoren für die Confidence-Berechnung. Die Summe sollte 1.0 ergeben. Bestimmt, welche Eigenschaften des Nickens stärker in die Bewertung einfließen. |
| `weights.reversals` | Einfluss der Anzahl Richtungswechsel. Mehr Reversals = höhere Confidence. |
| `weights.frequency` | Einfluss der Nick-Frequenz. Typische Nickfrequenz (2-4 Hz) gibt die beste Bewertung. |
| `weights.damping` | Einfluss der Dämpfung. Gut gedämpfte Schwingungen (natürliches Abklingen) werden höher bewertet. |
| `weights.correlation` | Einfluss der Sinuswellen-Korrelation. Gleichmäßigere Bewegungen bekommen mehr Punkte. |
| `weights.amplitude` | Einfluss der Bewegungsgröße. Größere, deutlichere Kopfbewegungen werden höher bewertet. |
| `multiplier` | Skaliert die berechnete Confidence des gesamten Patterns. Werte < 1.0 (z.B. 0.9 bei `slow_oscillation`) drücken die Confidence generell etwas, weil das Pattern von Natur aus unsicherer ist. |
| `max` | Obere Grenze der Confidence für dieses Pattern. Verhindert, dass ein Pattern trotz perfekter Werte eine höhere Confidence erreicht als gewünscht — z.B. soll `slow_oscillation` nie über 0.9 kommen. |
