# Multicam Cutter — Kurzanleitung

## Was du brauchst

- **Mindestens 2 Kamera-Clips** (MP4, MOV oder MXF) mit eingebettetem Timecode — optional eine zusätzliche Totale
- **Pro Person eine eigene Mikrofonspur** (WAV oder AIF, z.B. vom Zoom-Recorder)
- Die Kameras müssen **nicht gleichzeitig gestartet** worden sein — die Synchronisation passiert automatisch

---

## Welcher Workflow passt zu dir?

| | Bin-Workflow | Ordner-Workflow |
|---|---|---|
| **Wann nutzen?** | Du arbeitest direkt in DaVinci Resolve | Du nutzt Premiere, Avid, Final Cut — oder willst ohne Resolve arbeiten |
| **Eingabe** | Ein Bin in Resolve mit deinen Clips | Ein Ordner auf deiner Festplatte |
| **Ergebnis** | Fertige Timeline erscheint direkt in Resolve | AAF-Datei zum Importieren in dein Schnittprogramm |

---

## Bin-Workflow (mit DaVinci Resolve)

### Vorbereitung in Resolve

Lege alle Dateien einer Folge in **einen gemeinsamen Bin**:

```
Bin: "Folge 31"
  ├── A001.MP4      ← Kamera 1
  ├── B002.MP4      ← Kamera 2
  ├── MIC_Gast.WAV  ← Mikrofon 1
  └── MIC_Mod.WAV   ← Mikrofon 2
```

> Die Clips werden alphabetisch sortiert — der erste Videoclip ist Kamera 1, der zweite Kamera 2. Gleiches gilt für die Mikrofone.

### Los geht's

1. **Resolve muss geöffnet** sein und ein Projekt geladen haben
2. Öffne das Toolkit und wechsle zu **Multicam Cutter → Bin-Workflow**
3. Wähle deinen **Bin** aus dem Dropdown
4. Vergib einen **Namen** für die Schnitt-Timeline (z.B. „Folge 31 Rohschnitt")
5. Prüfe die **Mikrofon-Zuordnung** — welches Mikrofon gehört zu welcher Kamera?
6. Klicke auf **Starten**

### Was passiert?

Die Analyse dauert je nach Länge 5–15 Minuten. Du siehst den Fortschritt live mit Vorschaubildern und ETA.

### Ergebnis

In Resolve erscheinen zwei neue Timelines:

- **„… Sync"** — alle Quellen übereinander gelegt, damit du die Synchronisation kontrollieren kannst
- **„…"** — dein fertiger Rohschnitt

Die Clips sind farbig markiert, damit du den Grund für jeden Schnitt sofort erkennst:

| Farbe | Bedeutung |
|---|---|
| Blau | Kamera 1 spricht |
| Türkis | Kamera 2 spricht |
| Lila | Reaktions-Cutaway: Nicken erkannt |
| Grün | Reaktions-Cutaway: Einwurf erkannt |
| Orange | Pflichtschnitt (Einstellung war zu lang) |

---

## Ordner-Workflow (ohne Resolve)

### Vorbereitung

Lege alle Dateien einer Folge in **einen gemeinsamen Ordner**:

```
/Podcast/Folge 31/
  ├── A001.MP4
  ├── B002.MP4
  ├── MIC_Gast.WAV
  └── MIC_Mod.WAV
```

### Los geht's

1. Öffne das Toolkit und wechsle zu **Multicam Cutter → Ordner-Workflow**
2. Gib den **Ordnerpfad** ein — die App zeigt dir sofort die erkannten Dateien
3. Weise die **Kamera-Rollen** zu (Kamera 1, Kamera 2, ggf. Totale)
4. Weise die **Mikrofone** den Kameras zu
5. Klicke auf **Starten**

### Ergebnis

Im Unterordner `analyse/` findest du:

- **`final.aaf`** — deine Schnitt-Timeline mit Video und synchronisierten Mikrofonspuren

**Importieren:**
- DaVinci Resolve: *Datei → Import → Timeline → final.aaf*
- Premiere Pro: *Datei → Importieren → final.aaf*
- Avid: *File → Import → final.aaf*

> Die AAF verknüpft sich automatisch mit den Originaldateien, solange diese noch am selben Ort liegen oder bereits im Projekt importiert sind.

---

## Tipps

- **Mikrofon-Zuordnung vertauscht?** Wenn der falsche Sprecher auf der falschen Kamera landet, tausche einfach die MIC-Zuordnung im UI und starte erneut.
- **Zu wenige Cutaways?** Unter *Analyse-Einstellungen → Cutaway Regeln* kannst du die Empfindlichkeit erhöhen.
- **Erneuter Durchlauf geht schneller:** Aktiviere „Gesichtsanalyse überspringen" wenn du nur die Schnittparameter anpassen willst — die KI-Analyse vom letzten Lauf wird wiederverwendet.

---

## Grenzen

- Mindestens **2 Kameras** und **1–2 Mikrofone** erforderlich
- Die Gesichtserkennung funktioniert am besten bei **frontaler bis leicht seitlicher** Kameraperspektive
- Keine Farbkorrektur, kein Sounddesign — nur der Schnitt
