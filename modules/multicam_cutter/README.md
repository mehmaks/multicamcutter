# Multicam Cutter — Anleitung

Dieses Tool analysiert eine Podcast-Aufnahme mit zwei Kameras und erstellt automatisch einen ersten Schnitt. Es erkennt, wer gerade spricht, schneidet zwischen den Kameras hin und her — und fügt kurze Reaktions-Cutaways ein, wenn die Off-Kamera nickt oder etwas sagt.

**Zwei Workflows stehen zur Wahl:**

| | Bin-Workflow | Ordner-Workflow |
|---|---|---|
| **Voraussetzung** | DaVinci Resolve geöffnet | Nur FFmpeg + Python |
| **Eingabe** | Resolve-Bin | Ordner mit Mediendateien |
| **Ausgabe** | Timeline direkt in Resolve | FCPXML + EDL (importierbar in Resolve, Premiere Pro, Final Cut Pro) |
| **NLE** | Resolve | Beliebig |

---

## Voraussetzungen

### Software (beide Workflows)
- **Python 3.12** mit den installierten Abhängigkeiten (`pip install -r requirements.txt`)
- **FFmpeg** muss systemweit verfügbar sein

### Zusätzlich für den Bin-Workflow
- **DaVinci Resolve 18 oder neuer** muss geöffnet sein und ein Projekt geladen haben

### Material (beide Workflows)
- Genau **2 Kamera-Clips** (MP4, MOV oder MXF) — alphabetisch sortiert nach Name, der erste wird als CAM1 behandelt, der zweite als CAM2
- **1 oder 2 Mikrofon-Spuren** als separate WAV- oder AIF-Dateien (z.B. vom Zoom-Recorder)
- Die Kameraclips müssen einen **eingebetteten Timecode** enthalten (Standard bei Sony, Canon, Blackmagic, etc.)
- Die Kameras **müssen nicht gleichzeitig gestartet** worden sein — das Tool synchronisiert automatisch per Waveform-Abgleich

---

## Bin-Workflow (mit DaVinci Resolve)

### Empfohlener Aufbau im Bin

```
Bin: "Podcast"
  ├── A001.MP4      ← CAM1 (alphabetisch zuerst)
  ├── B002.MP4      ← CAM2
  ├── MIC001.WAV    ← Mikrofon Gast / CAM2   → Index 0
  └── MIC002.WAV    ← Mikrofon Moderator / CAM1 → Index 1
```

> **Hinweis zur MIC-Zuordnung:** Die Mikrofone werden alphabetisch nummeriert (Index 0 = erstes WAV, Index 1 = zweites WAV). Welches Mic zu welcher Kamera gehört, stellst du im UI ein.

### Schritt-für-Schritt

#### 1. Bin in Resolve vorbereiten
Lege alle Clips der Folge in einen gemeinsamen Bin in DaVinci Resolve. Der Bin muss genau 2 Videoclips und mindestens 1 Audioclip enthalten.

#### 2. App starten und Tab öffnen
Öffne die Toolkit-App und wechsle in den Tab **Multicam Cutter → Bin-Workflow**.

#### 3. Bin und Timeline-Name wählen
- **Media Pool Bin:** Der aktuell in Resolve geöffnete Bin wird automatisch vorausgewählt
- **Cut-Timeline Name:** Der Name der fertigen Timeline in Resolve (z.B. `31 Katrin Final Cut`)

#### 4. MIC-Zuordnung prüfen
Wähle unter „MIC für CAM1" und „MIC für CAM2" das jeweils passende Mikrofon. Die Namen der erkannten Audiodateien werden direkt angezeigt.

#### 5. Einstellungen anpassen (optional)
Unter **Analyse-Einstellungen** findest du mehrere aufklappbare Gruppen. Jeder Wert hat ein **?-Symbol**, das beim Überfahren erklärt, was er tut. Die Standardwerte sind für einen typischen Podcast-Workflow kalibriert.

Die **Cutaway Regeln** sind in drei Spalten organisiert:
- **Generell** — Cutaway-Länge, Pre-Roll und Zufallsfaktor (gilt für alle Cutaway-Typen)
- **Kopfnicken** — Toggle, Konfidenz, Nod-Threshold und -Dauer
- **Sprachreaktionen** — Toggle, Rise (dB) und maximale Burst-Dauer

Einstellungen lassen sich als **Preset** speichern und für andere Folgen oder Formate wieder laden.

#### 6. Workflow starten
Klicke auf **▶ Bin-Workflow starten**. Die Progressbar zeigt den aktuellen Schritt und eine ETA in Echtzeit.

**Typische Laufzeiten** (60-min-Folge, MacBook Pro M2):

| Schritt | Dauer |
|---|---|
| Waveform-Sync | ~30 Sekunden |
| Basis-Schnitt aus Audio | ~1 Minute |
| Gesichtsanalyse (KI, CAM1 + CAM2) | 5–15 Minuten |
| Cutaway-Einbau + Timeline | ~1 Minute |

#### 7. Ergebnis in Resolve kontrollieren
Nach Abschluss erscheinen in Resolve zwei neue Timelines:

- **`<Name> Sync`** — alle Quellen übereinander, zum Kontrollieren der Synchronisation
- **`<Name>`** — die fertige Schnitt-Timeline

Die Clips sind farblich markiert, damit du sofort siehst, warum ein Schnitt gesetzt wurde:

| Farbe | Bedeutung |
|---|---|
| 🔵 Blau | CAM1 spricht (Hauptsprecher) |
| 🩵 Türkis | CAM2 spricht (Hauptsprecher) |
| 🟣 Lila | Nodding-Cutaway (Nicken erkannt) |
| 🟢 Grün | Speaking-Cutaway (Einwurf erkannt) |
| 🟠 Orange | Erzwungener Schnitt (Shot zu lang) |

---

## Ordner-Workflow (ohne DaVinci Resolve)

Dieser Workflow läuft vollständig ohne Resolve. Eingabe ist ein Ordner mit den Mediendateien, Ausgabe ist eine **AAF-Datei** mit Video- und synchronisierten Mikrofon-Audiospuren — importierbar in DaVinci Resolve, Premiere Pro und Avid.

Alle Analyse-Zwischendateien landen in einem `analyse/`-Unterordner, getrennt von den Quelldateien.

### Empfohlener Ordneraufbau

```
/Episoden/31-Katrin/
  ├── A001.MP4      ← CAM1 (alphabetisch zuerst)
  ├── B002.MP4      ← CAM2
  ├── MIC001.WAV    ← Mikrofon (Index 0)
  └── MIC002.WAV    ← Mikrofon (Index 1)
```

### Schritt-für-Schritt

#### 1. App starten und Tab öffnen
Öffne die Toolkit-App und wechsle in den Tab **Multicam Cutter → Ordner-Workflow**.

#### 2. Ordner wählen
Trage den vollständigen Pfad zum Episoden-Ordner ein. Die App zeigt sofort die erkannten CAM- und MIC-Dateien an.

#### 3. MIC-Zuordnung prüfen
Wähle unter „MIC für CAM1" und „MIC für CAM2" das jeweils passende Mikrofon aus den Dropdowns.

#### 4. Einstellungen anpassen (optional)
Gleiche Einstellungen wie im Bin-Workflow, ebenfalls mit Preset-System.

#### 5. Workflow starten
Klicke auf **▶ Ordner-Workflow starten**. Die Progressbar zeigt den aktuellen Schritt und ETA.

**Typische Laufzeiten** entsprechen dem Bin-Workflow. Der Waveform-Sync und die Gesichtsanalyse dauern gleich lang; der Resolve-Schritt entfällt dafür vollständig.

#### 6. Ausgabedateien importieren

Nach Abschluss findest du im `analyse/`-Unterordner:

- **`final.aaf`** — Timeline mit Video + synchronisierten MIC-Audiospuren
- **`final.edl`** — Nur Video, ohne separate MIC-Spuren (Fallback)

**Import in DaVinci Resolve:**
`Datei → Import → Timeline → final.aaf auswählen`
Die Mediendateien werden automatisch mit bereits importierten Clips im Media Pool verknüpft.

**Import in Premiere Pro:**
`Datei → Importieren → final.aaf`

**Import in Avid Media Composer:**
`File → Import → final.aaf`

> **Tipp:** Die AAF enthält Video auf V1, MIC1 auf A1 und MIC2 auf A2, jeweils synchron zum Schnitt. Das Kamera-internaudio ist nicht enthalten.

---

## Was das Tool intern macht

1. **Waveform-Sync** — vergleicht das Audiosignal aller Quellen miteinander und berechnet, wie viele Frames sie gegeneinander verschoben sind
2. **Sprecher-Erkennung** — analysiert beide Mikrofon-Spuren und entscheidet per Lautstärke-Vergleich, wer gerade spricht
3. **Gesichtsanalyse & Sprachreaktionen** — analysiert mit KI (MediaPipe) nur die Frames, in denen eine Kamera *nicht* der aktive Sprecher ist — sucht nach Nicken. Parallel erkennt eine Baseline-Rise-Analyse kurze Einwürfe der Off-Kamera anhand des Anstiegsverhaltens der Audio-Baseline
4. **Cutaway-Einbau** — fügt erkannte Reaktionen als Cutaways in die Timeline ein, bereinigt zu kurze Clips und erzwingt Schnitte bei zu langen Einstellungen
5. **Timeline-Aufbau** — entweder direkt in Resolve (Bin-Workflow) oder als FCPXML/EDL (Ordner-Workflow)

---

## Aktuelle Limitierungen

### Anzahl Quellen
- **Genau 2 Kameras** — mehr oder weniger werden nicht unterstützt
- **1 oder 2 Mikrofon-Spuren** — bei mehr als 2 WAV-Dateien werden nur die ersten beiden verwendet

### Keine Multi-Gäste-Unterstützung
Das Tool ist für das **1 Moderator + 1 Gast**-Format ausgelegt. Formate mit 3 oder mehr Gesprächspartnern werden aktuell nicht unterstützt — die Sprecher-Erkennung arbeitet mit genau zwei Kanälen.

### Schnitt beginnt beim ersten Sprecheinsatz
Die fertige Timeline beginnt dort, wo laut Mikrofonanalyse der Podcast startet. Material davor (Vorbereitung, stilles Warten) fehlt im Schnitt — das ist gewollt.

### Nodding-Erkennung benötigt frontale Kamera
Die KI-Gesichtsanalyse arbeitet am zuverlässigsten wenn das Gesicht **frontal oder leicht seitlich** in die Kamera schaut. Stark seitliche Aufnahmen (Profil-Perspektive) reduzieren die Erkennungsrate deutlich.

### Der erste Schnitt ist ein Vorschlag
Das Ergebnis ist ein KI-gestützter Ersteditschnitt — kein Fertigschnitt. Gleichzeitiges Reden beider Personen, schlechte Reaktions-Cutaways oder zu ähnliche Mikrofonpegel können zu Fehlschnitten führen. Die Farbmarkierung hilft, schnell zu erkennen warum ein Schnitt gesetzt wurde.

### Keine Farbkorrektur oder Tonbearbeitung
Das Tool legt nur den Schnitt an. Farbkorrektur, Tonpegel und alle weitere Postproduktion erfolgen wie gewohnt im NLE.

---

## Häufige Probleme

**„Resolve nicht verbunden"** (Bin-Workflow)
Resolve muss geöffnet sein und ein Projekt geladen haben, *bevor* die Toolkit-App gestartet wird. Nach dem Starten von Resolve die App neu laden.

**Kein Bin in der Liste** (Bin-Workflow)
Prüfen ob der Bin in Resolve sichtbar ist und mindestens 2 Videoclips sowie 1 Audioclip enthält. Untergeordnete Sub-Bins werden ebenfalls aufgelistet.

**MIC-Zuordnung falsch (falscher Sprecher landet auf falscher Kamera)**
MIC-Index für CAM1 und CAM2 im UI tauschen. Beim nächsten Start kann „Base-EDL überspringen" aktiviert werden — dann läuft nur die Sprecher-Erkennung neu, ohne erneute Gesichtsanalyse.

**Keine oder sehr wenige Cutaways**
- Nodding: `Min. Konfidenz` etwas absenken oder `Min. Nod-Dauer` verkürzen
- Speaking: `Rise (dB)` absenken

**Zu viele falsche Cutaways**
- Nodding: `Min. Konfidenz` erhöhen
- Speaking: `Rise (dB)` erhöhen oder Speaking Reactions deaktivieren

**Sync-Timeline sieht verschoben aus**
Der Waveform-Abgleich funktioniert am besten wenn auf beiden Kameras dasselbe Umgebungsaudio zu hören ist. Stark gedämpfte Studios oder Richtmikrofone mit sehr wenig Übersprechen können den Abgleich erschweren.

**AAF-Import: Clips offline / nicht verknüpft**
Die AAF referenziert die Mediendateien über ihren absoluten Pfad und eingebetteten Timecode. Die Clips müssen im Media Pool bereits importiert sein (oder noch am selben Ort liegen wie beim Workflow-Durchlauf), damit Resolve sie automatisch verknüpft.

---

## Technische Referenz (`config.ini`)

Die vollständige Konfiguration liegt in `config.ini` im gleichen Ordner. Alle relevanten Werte sind über das UI editierbar — direkte Änderungen in der Datei sind nur für fortgeschrittene Anpassungen nötig.

| Sektion | Parameter | UI-Bereich | Beschreibung |
|---|---|---|---|
| `[General]` | `min_shot_duration` | Generelle Schnittregeln | Minimum Shotlänge vor einem Cutaway |
| | `max_shot_duration` | Generelle Schnittregeln | Maximale Shotlänge vor Pflicht-Cutaway |
| | `cleanup_min_duration` | Generelle Schnittregeln | Clips kürzer als dieser Wert werden entfernt |
| | `reaction_min_duration` | Cutaway Regeln → Generell | Basislänge eines Reaction-Cutaways (Nodding + Max-Shot) |
| | `cutaway_randomness` | Cutaway Regeln → Generell | Zufälliger Aufschlag auf Cutaway-Länge (0–0.5) |
| `[CutawayTiming]` | `pre_roll_frames` | Cutaway Regeln → Generell | Frames Vorlauf vor dem Cutaway-Start |
| | `cluster_max_gap_frames` | — | Max. Abstand um Reaktionen zu gruppieren |
| `[RMSDiarization]` | `threshold_db` | Sprecher-Erkennung | dB-Unterschied für Sprecherwechsel |
| | `min_edit_duration` | Sprecher-Erkennung | Mindestlänge eines Sprechabschnitts |
| | `change_delay` | Sprecher-Erkennung | Verzögerung vor Sprecherwechsel |
| `[Detection]` | `min_confidence` | Cutaway Regeln → Kopfnicken | Mindest-Konfidenz für Nodding-Cutaways |
| | `analysis_width` | — | Breite für KI-Analyse (0 = Originalauflösung) |
| `[Nodding]` | `min_nod_duration` | Cutaway Regeln → Kopfnicken | Mindestdauer der Kopfbewegung |
| | `cooldown_frames` | — | Frames Pause nach erkanntem Nod |
| `[SpeakingReaction]` | `rise_db` | Cutaway Regeln → Sprachreaktionen | dB-Anstieg der Baseline für Burst-Erkennung |
| | `max_duration` | Cutaway Regeln → Sprachreaktionen | Maximale Burst-Dauer in Sekunden |
