## Andere Einstellungen

### FPS

Die Framerate des Projekts muss hier eingestellt werden, damit alle zeitbasierten Berechnungen korrekt in Frames umgerechnet werden. Falsche FPS führen zu verschobenen Schnittpunkten in der Timeline. Der Wert wird automatisch aus dem ersten erkannten Videoclip vorausgefüllt, kann aber überschrieben werden.

### Nodding-Analyse überspringen / Base-EDL überspringen

Wurde die Nodding-Analyse bereits für diese Dateien durchgeführt, liegen die Ergebnisse als JSON-Dateien im `analyse/`-Unterordner. Mit diesem Toggle wird die rechenintensive Videoanalyse übersprungen und direkt auf die vorhandenen JSONs zurückgegriffen — sinnvoll, wenn nur Schnittparameter angepasst und die Timeline neu generiert werden soll, ohne die Analyse zu wiederholen.

Gleiches gilt für den Base-EDL-Toggle: Liegt die aus dem Audio generierte Rohschnittliste bereits vor, kann auch dieser Schritt übersprungen werden.

### LUT (.cube)

Eine optionale Farbtabelle für Footage, das in einem Log-Farbraum aufgenommen wurde (z.B. S-Log2, C-Log). Die LUT wird auf die extrahierten Frames angewendet, bevor MediaPipe die Gesichtserkennung durchführt — Log-Footage wirkt ohne Konvertierung flach und kontrastarm, was die Erkennungsqualität deutlich verschlechtert. Außerdem werden die Thumbnails in der Dateiübersicht damit korrekt dargestellt. Die LUT ändert nichts am eigentlichen Export.
