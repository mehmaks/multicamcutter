# Social Cutter — Pipeline-Dokumentation

Aus einem Single-Camera Talking-Head (9:16) und optionalem B-Roll-Material wird ein ~30s Social-Media-Rohschnitt generiert. Die Pipeline arbeitet schrittweise mit User-Review nach jedem Schritt.

---

## Schritt 0: Input

**Datei:** `ui/pages/social_cutter.py` → `_render_step_input()`

### Was passiert

- Prüft automatisch ob DaVinci Resolve geöffnet ist (`resolve_bridge/connection.py`)
- Bei Resolve-Verbindung: liest die aktive Timeline via `resolve_bridge/timeline_reader.py`, zeigt Projekt, Timeline-Name, FPS und V1-Clips an
- Der erste Clip auf V1 wird als Talking-Head vorgeschlagen
- Alternativ: manueller Dateipfad
- B-Roll-Kategorien: User gibt Ordnerpfade mit thematischem Namen an (z.B. "Injektion", "Beratung")

### Input → Output

| Input | Output |
|-------|--------|
| Resolve-Timeline oder Dateipfad | `soc_talking_head` (Pfad in session_state) |
| B-Roll-Ordner + Namen | `soc_broll_cats` (Liste von `{name, path}`) |

---

## Schritt 1: Silence Cut

**Datei:** `ui/pages/social_cutter.py` → `_render_step_silence()`
**Backend:** `resolve_bridge/silence_cutter.py` → `analyze_composite_silence()`

### Was passiert

1. Schema-Einstellungen rendern (Schwellwert, Mindestdauer, Pre/Post-Pad)
2. Optional: Schwellwert automatisch ermitteln (schnell via RMS-Analyse oder genauer via Whisper)
3. "Silence Cut ausführen": Erkennt Stille-Bereiche in der Audio-Spur
4. Invertiert Stille → Keep-Segmente (die Teile, die **nicht** still sind)
5. Speichert Keep-Segmente als `SilenceSegment(start_s, end_s)` im Pipeline-State

### Technische Details

- Nutzt `analyze_composite_silence()` mit einem Fake-Clip-Objekt (gleicher Pattern wie die Silence Cutter Page im Datei-Modus)
- RMS-basierte Erkennung bei 20ms Auflösung
- Pre/Post-Pad schützt Wortanfänge/-enden vor dem Abschneiden
- Ergebnis: Liste von Zeitbereichen, in denen gesprochen wird

### Parameter (aus Schema)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `silence_threshold_db` | -38 | Signale unter diesem Wert = Stille |
| `silence_min_s` | 0.5 | Kürzere Pausen werden ignoriert |
| `silence_pre_pad_ms` | 100 | Schutzabstand vor Sprachbeginn |
| `silence_post_pad_ms` | 100 | Schutzabstand nach Sprachende |

### Input → Output

| Input | Output |
|-------|--------|
| Talking-Head Dateipfad | `state.silence_segments: list[SilenceSegment]` |

---

## Schritt 2: Transkription

**Datei:** `ui/pages/social_cutter.py` → `_render_step_transcription()`
**Backend:** `modules/social_cutter/transcribe.py`

### Was passiert

1. Whisper-Modell laden (prüft erst ob es bereits im Cache `~/.cache/whisper/` liegt)
2. Word-level Transkription mit Timestamps und Konfidenzwerten
3. Volltext-Anzeige zur Kontrolle

### Technische Details

- Nutzt `openai-whisper` mit `word_timestamps=True`
- Modell "medium" empfohlen: gute Balance aus Geschwindigkeit und Qualität (Interpunktion, Fachbegriffe)
- Jedes Wort hat `start_s`, `end_s`, `confidence`
- Die Interpunktion (`.`, `,`, `?`, `!`) wird in Schritt 3 für Phrasengrenzen genutzt

### Parameter (aus Schema)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `whisper_model` | medium | Modellgröße (tiny/small/medium) |

### Input → Output

| Input | Output |
|-------|--------|
| Audio-Dateipfad | `state.transcript: TranscriptResult` (words, full_text, language) |

---

## Schritt 3: Phrasengrenzen

**Datei:** `ui/pages/social_cutter.py` → `_render_step_phrase_boundaries()`
**Backend:** `modules/social_cutter/phrase_boundaries.py`

### Was passiert

1. **Praat Pitch-Tracking** (`parselmouth`): F0-Kontur bei 5ms Auflösung
2. **Whisper-Interpunktion auswerten**: Punkt/Fragezeichen = Satzende, Komma = Halbsatz
3. **Wortlücken erkennen**: Pausen zwischen Wörtern ab `min_gap_ms` = Phrasengrenze
4. **Pitch-Trend klassifizieren**: 600ms-Fenster vor der Grenze analysieren
   - Fallend (F0 sinkt) → natürliches Satzende
   - Steigend (F0 steigt) → Fortsetzung/Frage
   - Flat → keine klare Richtung
5. **Konfidenz berechnen**: Kombination aus Interpunktion (50%), Pitch-Trend (30%), Wortlücke (20%)
6. **Filtern**: Nur Grenzen innerhalb von Keep-Segmenten (aus Schritt 1) behalten

### Algorithmus (Konfidenz)

```
Konfidenz = Interpunktion + Pitch + Gap

Interpunktion:  . ! ? → 0.5    , → 0.3    nichts → 0.0
Pitch:          falling → 0.3 (prefer_falls=true) / 0.15
                rising  → 0.15 (prefer_falls=true) / 0.3
                flat    → 0.1
Gap:            > 0.5s → 0.2   > 0.3s → 0.1
```

### Parameter (aus Schema)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `prefer_falls` | true | Fallende Intonation bevorzugen (natürlicher Schnitt) |
| `min_gap_ms` | 300 | Wortlücken ab dieser Dauer = Phrasengrenze |
| `phrase_min_confidence` | 0.5 | Grenzen unter diesem Wert ignorieren |

### Input → Output

| Input | Output |
|-------|--------|
| `state.transcript`, Audio-Pfad, `state.silence_segments` | `state.phrase_boundaries: list[PhraseBoundary]` |

---

## Schritt 4: Redundanz-Erkennung

**Datei:** `ui/pages/social_cutter.py` → `_render_step_redundancy()`
**Backend:** `modules/social_cutter/redundancy.py`

### Was passiert

1. **Sätze bilden**: Transkript an Phrasengrenzen (ab `phrase_min_confidence`) splitten → `list[Sentence]`
2. **Embeddings berechnen**: sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`) erstellt Vektoren pro Satz
3. **Pairwise Cosine Similarity**: Matrix aller Satzpaare berechnen
4. **Gruppen bilden**: Union-Find-ähnlich — Sätze mit Similarity >= Schwelle werden gruppiert
5. **User-Auswahl**: Jede Gruppe wird als Radio-Button-Gruppe angezeigt, User wählt welche Version behalten wird (Default: erste)

### Technische Details

- Nur Gruppen mit 2+ Sätzen werden angezeigt (Einzelsätze = nicht redundant)
- Durchschnittliche Similarity innerhalb jeder Gruppe wird berechnet
- Modell ist multilingual — funktioniert mit deutschen Texten

### Parameter (aus Schema)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `similarity_threshold` | 0.75 | Ab welcher Cosine-Similarity = Wiederholung |

### Input → Output

| Input | Output |
|-------|--------|
| `state.sentences` (aus Phrasengrenzen) | `state.redundancy_groups: list[RedundancyGroup]` |

---

## Schritt 5: Segment-Montage

**Datei:** `ui/pages/social_cutter.py` → `_render_step_assembly()`
**Backend:** `modules/social_cutter/segment_assembly.py`

### Was passiert

1. **Redundanz-Auswahl anwenden**: Entfernt abgewählte Sätze aus der Satzliste
2. **Segmente assemblieren**: Jeder behaltene Satz wird ein `FinalSegment` mit Source-Timecodes
3. **Tail anhängen**: Nach dem letzten Wort jedes Segments wird `tail_ms` angefügt (natürlicher Auslauf)
4. **Dauer-Check**: Gesamtdauer vs. Zieldauer anzeigen, Warnung bei >10% Überschreitung
5. **Manuelle Nachbearbeitung**: User kann einzelne Segmente entfernen

### Technische Details

- `assemble_segments()` schneidet Segmente an Silence-Grenzen zu (kein Segment ragt in einen Stille-Bereich)
- `estimate_duration()` summiert die Einzeldauern

### Parameter (aus Schema)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `target_duration_s` | 30.0 | Gewünschte Zieldauer |
| `tail_ms` | 100 | Auslauf nach dem letzten Wort pro Segment |

### Input → Output

| Input | Output |
|-------|--------|
| `state.sentences`, `state.redundancy_groups`, `state.silence_segments` | `state.final_segments: list[FinalSegment]` |

---

## Schritt 6: Zoom / Reframing

**Datei:** `ui/pages/social_cutter.py` → `_render_step_zoom()`
**Backend:** `modules/social_cutter/zoom_assignment.py`

### Was passiert

1. **Audio-Prosodie analysieren** (`analyze_audio_prosody`):
   - RMS-Peak pro Segment (Lautstärke)
   - Sprechtempo (Wörter/Sekunde)
   - Anrede-Keywords erkennen ("du", "ihr", "euch", ... → direkte Ansprache)
   - Energie-Rank normalisieren (0–1): 50% RMS + 30% Tempo + 20% Keywords

2. **Face Detection** (`detect_face_positions`):
   - Pro Segment ein Frame am Mittelpunkt extrahieren (ffmpeg)
   - MediaPipe FaceLandmarker (IMAGE-Modus, gleicher Modellpfad wie `video_reaction_analyzer_v2.4.py`)
   - Nasenspitze (Landmark 1) = Kopfzentrum, Stirn-Kinn-Abstand = Gesichtshöhe
   - Fallback bei nicht erkanntem Gesicht: center_x=0.5, center_y=0.35

3. **Zoom-Tier zuweisen** (`assign_zoom_tiers`):
   - Segmente nach Energie-Rank in Quartile einteilen
   - Top-Quartil → TIGHT, nächstes → CLOSE, dann MEDIUM, Rest → WIDE
   - Keine zwei aufeinanderfolgenden Segmente mit gleichem Tier (visueller Rhythmus)

4. **Pan/Tilt berechnen** (`calculate_pan_tilt`):
   - Kopf auf Safe-Area-Zentrum zentrieren
   - Vertikal leicht über der Mitte (Regel der Drittel)
   - Max-Pan/Tilt begrenzt durch sichtbaren Ausschnitt bei gegebenem Zoom

### Zoom-Tiers

| Tier | Default Scale | Wann |
|------|--------------|------|
| WIDE | 1.00x | Ruhige Passagen, niedriger Energie-Rank |
| MEDIUM | 1.18x | Mittlere Energie |
| CLOSE | 1.30x | Hohe Energie, betontes Sprechen |
| TIGHT | 1.45x | Höchste Energie, direkte Ansprache |

### Parameter (aus Schema)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `zoom_wide/medium/close/tight` | 1.0/1.18/1.30/1.45 | Scale-Faktor pro Tier |
| `safe_x/y/w/h` | 0.05/0.12/0.90/0.76 | Safe Area (normalisiert, für UI-Elemente der Plattform) |

### Input → Output

| Input | Output |
|-------|--------|
| `state.final_segments`, Video-Pfad, `state.transcript` | `seg.zoom: ZoomParams` (tier, scale, pan, tilt) pro Segment |

---

## Schritt 7: B-Roll

**Datei:** `ui/pages/social_cutter.py` → `_render_step_broll()`
**Backend:** `modules/social_cutter/broll_matching.py`

### Was passiert

1. **Kategorie-Embeddings** (`embed_categories`): sentence-transformers encodiert die Kategorie-Namen
2. **Segment → Kategorie** (`match_segments_to_categories`): Cosine-Similarity zwischen Segment-Text und Kategorie-Embeddings → Top-K Matches
3. **CLIP-Ranking** (`rank_clips_in_category`): Innerhalb der besten Kategorie wird jeder Clip visuell gegen den Segment-Text gerankt
   - Ein Thumbnail pro Clip (Mittelpunkt, 224x224)
   - `openai/clip-vit-base-patch32` berechnet Text-Image-Similarity
   - Device: MPS (Apple Silicon) > CUDA > CPU
4. **Density-Budget**: Maximal `max_broll_density` der Timeline-Dauer darf B-Roll sein
5. **Splitscreen-Option**: Bei langen Segmenten (> `splitscreen_threshold_s`) wird Splitscreen vorgeschlagen statt Fullscreen-B-Roll
6. **User-Review**: Vorschläge mit Kategorie, Clip-Name und Score — Reject-Button pro Vorschlag

### Parameter (aus Schema)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `max_broll_density` | 0.4 | Max. 40% der Timeline mit B-Roll bedeckt |
| `enable_splitscreen` | false | Splitscreen bei langen B-Roll-Segmenten |
| `min_broll_segment_s` | 2.0 | Kürzere Segmente bekommen kein B-Roll |
| `splitscreen_threshold_s` | 3.0 | Ab dieser Dauer → Splitscreen statt Fullscreen |

### Input → Output

| Input | Output |
|-------|--------|
| `state.final_segments`, B-Roll-Kategorien | `seg.broll: BRollPlacement` (clip_path, source_in/out, score, is_splitscreen) |

---

## Schritt 8: Voice Leveler

**Datei:** `ui/pages/social_cutter.py` → `_render_step_voice_leveler()`
**Backend:** `modules/voice_leveler.py` (bestehend)

### Was passiert

- Toggle: Voice Leveler an/aus
- Preset-Auswahl: loud / natural / broadcast
- Nutzt den bestehenden Voice Leveler aus `modules/voice_leveler.py` — keine Kopie

### Parameter (aus Schema)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `run_voice_leveler` | true | Voice Leveler aktivieren |
| `leveler_preset` | loud | Preset (loud/natural/broadcast) |

---

## Schritt 9: Anwenden

**Datei:** `ui/pages/social_cutter.py` → `_render_step_apply()`
**Backend:** `resolve_bridge/social_cutter.py`

### Was passiert

1. **Zusammenfassung**: Segment-Anzahl, Gesamtdauer, Zoom-Count, B-Roll-Count
2. **Auf Timeline anwenden** (async Worker):
   - `apply_zoom_params()`: Setzt ZoomX, ZoomY, Pan, Tilt pro Clip auf V1
   - `place_broll()`: Platziert B-Roll-Clips auf V2 (Track wird erstellt falls nötig)
   - Voice Leveler: Aktuell Hinweis auf manuellen Export (Audio-Export → Leveler → Re-Import)

### Resolve-API-Operationen

| Funktion | Was sie tut |
|----------|-------------|
| `apply_zoom_params()` | `item.SetProperty("ZoomX/ZoomY/Pan/Tilt", ...)` pro V1-Clip |
| `place_broll()` | `media_pool.AppendToTimeline()` auf V2, Track anlegen wenn nötig |
| `set_markers_at_boundaries()` | Farbkodierte Marker (Grün=Satzende, Gelb=Halbsatz, Blau=Pause) |
| `remove_segments_from_timeline()` | Clips rückwärts löschen (Frame-Positionen bleiben stabil) |

---

## Datenfluss

```
Input (Datei/Resolve)
  │
  ▼
Silence Cut ──→ SilenceSegment[]     (Keep-Bereiche)
  │
  ▼
Whisper ──────→ TranscriptResult     (Wörter + Timestamps)
  │
  ▼
Phrasengrenzen → PhraseBoundary[]    (Schnittmarken-Kandidaten)
  │
  ▼
  ├─→ Sentences   (Transkript an Grenzen gesplittet)
  │
  ▼
Redundanz ────→ RedundancyGroup[]    (Ähnliche Sätze gruppiert)
  │
  ▼
Montage ──────→ FinalSegment[]       (Source-Timecodes, Transkript)
  │
  ├─→ Zoom ───→ FinalSegment[].zoom  (Tier, Scale, Pan, Tilt)
  │
  ├─→ B-Roll ─→ FinalSegment[].broll (Clip, Timecodes, Score)
  │
  ▼
Anwenden ─────→ Resolve Timeline     (V1 Zoom + V2 B-Roll)
```

---

## Dateien

| Datei | Funktion |
|-------|----------|
| `modules/social_cutter/types.py` | Alle Dataclasses (13) + Enums (3) |
| `modules/social_cutter/transcribe.py` | Whisper word-level Transkription |
| `modules/social_cutter/phrase_boundaries.py` | Praat-Pitch + Whisper-Interpunktion |
| `modules/social_cutter/redundancy.py` | sentence-transformers Similarity |
| `modules/social_cutter/segment_assembly.py` | Segment-Montage + Dauer |
| `modules/social_cutter/zoom_assignment.py` | Prosodie + MediaPipe + Zoom-Tiers |
| `modules/social_cutter/broll_matching.py` | Kategorie-Match + CLIP-Ranking |
| `resolve_bridge/social_cutter.py` | Resolve-API Operationen |
| `ui/pages/social_cutter.py` | Streamlit Wizard (10 Steps) |
| `config/schemas/social_cutter_params.json` | 25 Parameter in 7 Gruppen |

---

## Abhängigkeiten

| Paket | Genutzt in | Zweck |
|-------|-----------|-------|
| `openai-whisper` | transcribe.py | Word-level Transkription |
| `praat-parselmouth` | phrase_boundaries.py | F0 Pitch-Tracking |
| `sentence-transformers` | redundancy.py, broll_matching.py | Text-Embeddings |
| `transformers` + `torch` | broll_matching.py | CLIP Text-Image-Similarity |
| `mediapipe` | zoom_assignment.py | FaceLandmarker |
| `numpy` | Überall | Numerik |
