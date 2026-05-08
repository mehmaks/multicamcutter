# Social Cutter — Planung

## Ziel

Aus Single-Camera-Rohmaterial (Talking Head + B-Roll) einen fast-paced, social-media-tauglichen Rohschnitt generieren, der zu ~95% fertig ist. Der Stil folgt einem konkreten, existierenden Muster — kein zufälliger Look, sondern programmatische Nachbildung eines definierten Schnittstils.

## Input

- **Talking-Head-Material** — Interview/Monolog, Single Camera, kein Skript. Thematisch vorgruppiert (ein Clip oder eine Auswahl = ein thematischer Block).
- **B-Roll-Material** — Sammlung thematisch passender Clips (Ordner oder Bin).

**Offene Frage:** Ist die thematische Vorsortierung des Talking-Head-Materials eine harte Voraussetzung (User liefert abgegrenzten Block) oder soll das Modul auch längeres Rohmaterial selbst in Themenblöcke segmentieren können?

## Output

- Timeline/AAF mit:
  - V1: Talking Head (silence-getrimmt, zoom-gestuft)
  - V2: B-Roll-Overlays an passenden Stellen
  - A1: Talking-Head-Audio (silence-getrimmt)

---

## Pipeline-Schritte

### 1. Silence Cut (bestehend)

Silence Cutter wiederverwenden: Pausen erkennen und entfernen. Ergebnis: Eine Abfolge von Sprach-Segmenten ohne Totpausen, die als Jump-Cut-Timeline aneinandergereiht werden.

**Status:** Kernlogik existiert in `modules/silence_cutter.py`. Muss als Library-Funktion aufrufbar sein (aktuell UI-gekoppelt?).

**TODO:**
- [ ] Silence-Cutter-Kernlogik als importierbare Funktion extrahieren
- [ ] Parameter-Defaults für Social-Cutter-Kontext festlegen (aggressivere Schwellen als Podcast-Schnitt?)

---

### 2. Satz-/Phrasenerkennung (Schnittmarken)

Nach dem Silence Cut liegen Jump-Cuts vor. Nicht jede Schnittstelle ist gleich gut — idealerweise liegen Schnitte an natürlichen Sprachgrenzen: Satzenden, Halbsatz-Pausen, abgeschlossene Gedanken.

**Ansätze:**

**Entscheidung:** Kombination Whisper + Pitch (all-in).

#### 2a. Whisper (Wort-Timestamps + Interpunktion)
- Whisper liefert Wort-für-Wort-Timestamps und setzt Satzzeichen
- Schnittmarken-Kandidaten an Punkten, Kommas, Gedankenstrichen → grobe Phrasengrenzen
- Vorteil: Bereits integriert (Take Selector)
- Schwäche: Interpunktion bei freier Rede unzuverlässig — Whisper setzt Punkte oft willkürlich

#### 2b. Intonationsanalyse (Pitch-Tracking)
- Fallende Grundfrequenz (F0) signalisiert Gedankenende
- Steigende F0 = offener Gedanke, Frage, Spannungsbogen
- Kandidaten: `crepe` (CNN-basiert, genau), `pyin` (librosa, schnell), `parselmouth` (Praat-Wrapper, bewährt)
- Bestätigt/verfeinert Whisper-Grenzen: Ein Whisper-Punkt mit fallender F0 ist eine starke Schnittmarke, ein Punkt mit steigender F0 eher nicht

#### 2c. Weitere Signale
- **RMS-Energie:** Energieabfall nach dem letzten Wort → natürliche Lücke
- **Wortabstand:** Zeitliche Lücke zwischen Whisper-Wörtern > X ms → Phrasenpause auch ohne Interpunktion
- **Sprechgeschwindigkeit:** Verlangsamung am Phrasenende ist ein bekanntes prosodisches Signal

#### 2d. Referenz-Analyse (Ground Truth aus manuellen Edits)

Aus 2-3 manuell geschnittenen Timelines ein statistisches Stilprofil extrahieren:

- **Segment-Längen-Verteilung** — Gleichmäßiger Takt oder variable Längen? Gibt es einen Rhythmus?
- **Prosodisches Muster am Schnittpunkt** — F0-Kontur in den letzten 500ms vor dem Cut: fallend, steigend, flach?
- **RMS/Energie am Schnittpunkt** — Cut in der Stille oder im Ausklingen?
- **Tail nach letztem Wort** — Wie viele ms nach dem letzten Whisper-Wort liegt der Cut? → natürlicher Tail-Wert
- **B-Roll-Timing** — Wo relativ zum Satz setzt B-Roll ein/aus?
- **Zoom-Wechsel-Muster** — Welche Zoom-Stufen nutzt der User, wie oft wird gewechselt?

**Input:** Resolve-Timeline mit Markern an Schnittpunkten + zugehörige Audio-Datei. Alternativ: EDL-Export.

**Output:** JSON-Stilprofil mit kalibrierten Schwellen und Verteilungen, das die Detection-Pipeline parametrisiert.

**Offene Fragen:**
- Wie gewichtet man Whisper vs. Pitch wenn sie sich widersprechen? (z.B. Whisper sagt Punkt, aber F0 steigt)
- Soll es einen "Aggressive"-Modus geben, der auch mitten in Halbsätzen schneidet (Social-Media-Stilmittel)?
- Soll der User Schnittmarken nachträglich verschieben/bestätigen können?

---

### 3. Zoom-Stufen + Reframing (Jump-Cut-Kaschierung)

**Format: 9:16 (vertikal).** Source-Material und Timeline sind beide 1080x1920. Zoom 1.0 = 1:1 (kein Crop, Person ist im vertikalen Frame bereits korrekt positioniert, Pan=0). Erst ab Zoom >1.0 wird Pan/Tilt nötig, um den Kopf im engeren Ausschnitt zu zentrieren.

Aufeinanderfolgende Talking-Head-Segmente bekommen wechselnde Zoom-Stufen, damit Jump-Cuts weniger auffallen. Der Zoom simuliert verschiedene Einstellungsgrößen einer Single-Camera-Aufnahme.

#### Erkenntnisse aus der Referenz-Timeline

Nicht 3, sondern **5 Zoom-Tiers** (Detail-Shots 2.0+ aus Automatisierung ausgeklammert):

| Tier | Zoom-Range | Anteil | Pan/Tilt |
|------|-----------|--------|----------|
| Wide | 1.0 | 43% | Zentriert (0/0) |
| Medium | 1.16–1.20 | 29% | Oft Pan≈-31 (leicht links) |
| Close | 1.25–1.35 | 12% | Individuelles Reframe |
| Tight | 1.37–1.55 | 12% | Immer mit Pan+Tilt Reframe |
| (Detail) | 2.0–2.5 | 4% | (Manuell, nicht automatisiert) |

**Zoom-Anchor = Kopf:** Bei 9:16 muss der Zoom auf den Kopf zentriert werden, nicht auf die Bildmitte. MediaPipe Face Detection liefert die Kopfposition pro Frame → daraus den Pan/Tilt-Offset pro Segment berechnen.

**Verifiziert aus Referenz-Timeline:** Die Pan-Werte bei Medium-Zoom-Clips (Pan≈-31 bei Zoom 1.2, Pan≈-59 bei Zoom 1.17) entsprechen manuellem Eyeballing der Kopfzentrierung. Der Wert variiert je nach Kopfposition im Source-Frame. → Automatisierung: MediaPipe Kopf-BBox pro Segment extrahieren, Pan/Tilt so berechnen, dass der Kopf horizontal mittig in der Safe Area liegt.

#### Safe Area

Gezoomte Segmente müssen einer vorgegebenen Safe Area folgen — wichtige Bildinhalte dürfen nicht an den Rändern abgeschnitten werden (z.B. durch Plattform-UI-Elemente, Beschriftungen, Profilbilder).

**Umsetzung — zwei Optionen:**

1. **PNG-Maske (Schwarz/Weiß):** Weiß = sicher, Schwarz = unsicher. Vorteil: Visuell intuitiv, der User sieht sofort was abgedeckt ist, kann die Maske in Photoshop anpassen. Nachteil: An Auflösung gebunden.

2. **Rect-Koordinaten (normalisiert, 0–1):** `{"safe_x": 0.05, "safe_y": 0.12, "safe_w": 0.90, "safe_h": 0.76}`. Vorteil: Auflösungsunabhängig, einfach zu verarbeiten. Nachteil: Nur Rechtecke, keine komplexen Formen.

**Empfehlung:** Rect-Koordinaten als Default (deckt 95% der Fälle ab — Plattform-UIs sind immer rechteckig), mit optionaler PNG-Maske als Override für Spezialfälle. Die Rect-Werte können als Preset pro Plattform mitgeliefert werden (Instagram Reels, TikTok, YouTube Shorts haben leicht unterschiedliche Safe Areas).

#### Splitscreens (aus Referenz-Analyse bestätigt)

V1 mit Tilt=-597 bis -805 bei Zoom 1.0 + gleichzeitiges V2 = **Splitscreen**. V1 wird nach oben/unten verschoben, V2 füllt die andere Hälfte.

- Splitscreens treten in Clustern auf (3-6 aufeinanderfolgende Clips)
- Immer mit B-Roll als zweite Hälfte
- Scheinen an thematischen Höhepunkten/Zusammenfassungen zu stehen

**Für Automatisierung:** Splitscreen als eigener Effekt-Typ, der bei hoher B-Roll-Dichte oder an Themen-Übergängen getriggert werden kann. Genaue Trigger-Logik erst nach Pitch-/Whisper-Analyse klärbar.

**Ausgeklammert aus Automatisierung:**
- Detail-Shots (Zoom 2.0+) → manueller Feinschnitt

---

### 4. B-Roll-Zuordnung und Platzierung

B-Roll-Clips werden thematisch passend über das Talking-Head-Material gelegt. Die Platzierung soll an natürlichen Sprachgrenzen erfolgen (siehe Schritt 2), nicht mitten im Satz.

#### 4a. Thematische Zuordnung
**Ansätze:**
- **CLIP-basiert:** Talking-Head-Segment (Audio-Transkription) als Text-Prompt, B-Roll-Frames als Bild → Cosine Similarity. CLIP ist bereits im Projekt (Cutaway-Filter).
- **Keyword-Matching:** Whisper-Transkript → Keywords extrahieren → mit B-Roll-Dateinamen oder Tags matchen (simpler, aber fragil).
- **LLM-basiert:** Transkript + B-Roll-Beschreibungen an ein LLM, das die Zuordnung vorschlägt (mächtig, aber externe Dependency).

#### 4b. Platzierung
- B-Roll startet/endet an Satz- oder Phrasengrenzen (aus Schritt 2)
- B-Roll-Dauer: Mindestens X Sekunden, maximal bis zur nächsten Satzgrenze
- Nicht zu häufig — Rhythmus aus Talking-Head und B-Roll soll natürlich wirken
- B-Roll darf nicht auf wichtigen Momenten liegen (emotionale Peaks im Talking Head?)

**Offene Fragen:**
- Wie beschreibt der User sein B-Roll? Dateinamen, Ordnerstruktur, manuelle Tags, oder rein visuell (CLIP)?
- Soll B-Roll mit Crossfade oder hartem Cut ein-/ausgeblendet werden?
- Gibt es eine maximale B-Roll-Dichte (z.B. max 40% der Gesamtlänge)?
- Soll B-Roll auch als Reaktion auf bestimmte Wörter/Themen getriggert werden können?

---

### 5. Effekte (optional, spätere Phase?)

- **Splitscreens** — Wann und warum? Zwei B-Roll-Clips gleichzeitig? Talking Head + B-Roll nebeneinander?
- **Texteinblendungen** — Untertitel/Captions automatisch aus Whisper-Transkript?
- **Transitions** — Welche Übergänge zwischen Segmenten?
- **Farbkorrektur** — LUT-Anwendung wie im Multicam Cutter?

---

## Abhängigkeiten / Vorarbeiten

| Thema | Status | Notiz |
|-------|--------|-------|
| Silence Cutter als Library | Nötig | Kernlogik aus UI-Flow extrahieren |
| Whisper-Integration | Vorhanden | Take Selector nutzt es bereits |
| CLIP-Integration | Vorhanden | Multicam Cutter Ignore-Filter |
| MediaPipe Face Detection | Vorhanden | Für Zoom-Reframing nutzbar |
| Pitch-Tracking | Neu | `crepe`, `pyin`, oder `parselmouth` evaluieren |
| AAF-Export mit Zoom/Crop | Teilweise | Multicam hat Wide-Shot-Zoom, muss erweitert werden |
| Multi-Track AAF (V1+V2) | Teilweise | Multicam hat Audio-Tracks, Video-V2 muss ergänzt werden |

---

## Offene Grundsatzfragen

1. **Workflow-Modus:** Nur Folder-Workflow (Dateipfade) oder auch Resolve-Bin-Workflow?
2. **Deliverable-Format:** AAF für Premiere/Resolve? Oder auch direkter MP4-Export?
3. **Iterativer Workflow:** Soll der User nach jedem Schritt Ergebnisse sehen und justieren können, oder läuft die Pipeline komplett durch?
4. **Stil-Presets:** Soll es verschiedene Schnitt-Stile geben (z.B. "Interview ruhig" vs. "Social aggressiv")?
5. **Audio-Finishing:** Voice Leveler automatisch auf das Talking-Head-Audio anwenden?
