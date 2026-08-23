# AAF-Struktur (build_aaf.py) — hart erarbeitetes Interop-Wissen

⚠️ **Diese Datei NICHT verlieren und NICHT leichtfertig umbauen.** Die
AAF↔NLE-Kompatibilität (besonders Premiere) ist aus wochenlangem Reverse-
Engineering entstanden (April 2026, Take-Selector-Modul; Premiere-Ursachen
bestätigt 25.07.2026). Jede Änderung an `modules/multicam_cutter/build_aaf.py`
gegen die Invarianten unten muss in **Resolve UND Premiere** gegengetestet werden.

Kurzreferenz für die Test-Methodik: isolierter pyaaf2-Readback (unten) prüft die
Struktur **ohne NLE**; die echte Auto-Link-Probe braucht eine laufende NLE.

---

## Warum Bugs hier so lange verborgen bleiben — ZWEI Link-Mechanismen

AAF referenziert Medien nicht per Datei, sondern über eine Mob-Kette. Wie eine
NLE die reale Datei findet (Auto-Linking), ist je NLE **unterschiedlich**:

| NLE | linkt über | Konsequenz |
|---|---|---|
| **DaVinci Resolve** | **Reel-Name + Timecode** der TapeMob | Findet Medien auch OHNE Datei-URL. Verzeiht viel. |
| **Adobe Premiere Pro** | **Datei-URL** im `NetworkLocator` des FileDescriptors | Ohne gültige URL: kann NICHT linken → **erfindet Namen** `<stem>_V01_<zähler>` / `<stem>_A01_<zähler>` und zeigt die Medien **offline**. |

**Merke:** „In Resolve funktioniert's" beweist NICHTS für Premiere. Ein
AAF-Bug, der die URL betrifft, ist in Resolve komplett unsichtbar. Genau so
blieb der Locator-Bug (unten) lange verborgen.

---

## Kritische Invarianten (Fass-das-nicht-an-Liste)

### 1. NetworkLocator: `desc['Locator'].value = [loc]` — NIEMALS `.append`
```python
loc = f.create.NetworkLocator()
loc['URLString'].value = Path(src).resolve().as_uri()
desc['Locator'].value = [loc]     # ✅ RICHTIG — Locator wird gespeichert
# desc.locator.append(loc)        # ❌ FALSCH — pyaaf2 gibt eine List-KOPIE
                                   #    zurück, der Locator landet NIE in der Datei
```
**Empirisch belegt** (isolierter pyaaf2-Readback, 25.07.): `.append` → Locator-
Count **0**; `['Locator'].value = [loc]` → Count **1** mit korrekter URL. Der
`.append`-Weg produzierte AAFs komplett OHNE Datei-URL → Premiere offline. Das
war die Wurzel des `_V01_`-Offline-Problems. Gilt für Video- UND Audio-Descriptor.

### 2. Mehrere MasterMobs pro Quelle sind OK — solange der FileMob linkbar ist
Premiere macht aus **jedem** MasterMob einen eigenen Master-Clip im Projekt.
Mehrere MasterMobs pro Kamera (z. B. einer je Schnittgrund) → **mehrere Clips im
Projekt, ALLE online** (sie zeigen auf denselben, korrekt linkbaren FileMob).
Resolve zeigt die Namen am Timeline-Clip; Premiere legt die Extra-Clips im Bin an.
- ⚠️ **Frueher falsch dokumentiert:** „mehrere MasterMobs → Premiere offline". Das
  war in Wahrheit der Locator-/Descriptor-Bug (Invariante 1 + 3): der FileMob hatte
  gar keine linkbare URL, deshalb ging ALLES offline — auch der einzelne Basis-Clip.
  Nach dem CDCIDescriptor+Locator-Fix (25.07.) linken **beide** Modi in Premiere.
- **Toggle (0.6.7):** Settings „Schnittgründe in Clipnamen" (`clipNameReasons`,
  **Default AN**). An → grund-benannte MasterMobs (Muster `clip_name_pattern`).
  Aus → EIN MasterMob pro Kamera (Puristen, die genau einen Clip pro Kamera wollen).
  Mechanik: `build_aaf._master_for` liefert ohne `clip_name_pattern` immer den
  Basis-`cam_masters[cam_idx]`; die App sendet `--clip-name-pattern` nur bei aktivem
  Toggle. Muster-Details: `brain/Engine-Protokoll.md`.

### 3. URL: voller `/Volumes/`-Pfad, KEIN Stripping
`Path(src).resolve().as_uri()` → `file:///Volumes/Jardani/…`.
Premieres eigene Exporte nutzen `file:///Jardani/…` (ohne `/Volumes/`), aber das
linkt nur über die **MobID** (die Premiere bei EIGENEM Export speichert), nicht
über die URL. Für URL-Auto-Linking (unser Fall, wie DaVinci-Export) MUSS
`/Volumes/` drin sein.

### 4. KEIN MultipleDescriptor
MultipleDescriptor triggert in Premiere denselben Namensgenerator
(`_V1A2_XXXX`-Suffix) → Auto-Linking scheitert immer. Stattdessen **getrennte**
Video- und Audio-Descriptor-Mobs.

### 5. Timecode gehört in die TapeDescriptor-Mob
Der echte Quell-TC in die TapeMob (Reel-Name = `stem`), NICHT als direkter
Offset in den FileDescriptor. Die FileDescriptor-Slots referenzieren die
TapeMob. (Das ist zugleich, worüber Resolve linkt.)

### 6. Krumme fps (29,97 …) → EXAKTER rationaler Edit-Rate, NICHT `int(round())`
Alle Slot-Edit-Rates + die Video-`SampleRate` kommen aus `_edit_rate(fps)`:
- **Ganzzahl-fps** (25/30/50/60) → plain int (byte-identisch zum alten `fps_int`).
- **Krumme NTSC-fps** → exakter Bruch: `AAFRational(30000, 1001)` für 29,97,
  `(24000, 1001)` für 23,976, `(60000, 1001)` für 59,94 (`_NTSC_RATIONALS`).

⚠️ **`int(round(29.97)) = 30` ist der Bug**: eine als 30/1 gestempelte Timeline
mit 29,97-Material löst in Resolve/Premiere Speed-Adaption aus → A/V-Drift +
Standbild am Ende (Realmaterial 15.08.: „funktioniert nicht mit 30fps"). Nur der
exakte Bruch verhindert das.

### 7. Drop-Frame-Reel-TC bei 29,97/59,94 — sonst desynchronisieren die Kameras
29,97/59,94-Material ist per NTSC-Norm **Drop-Frame**. Der Reel-TC (TapeMob) UND der
Timeline-TC müssen dann Drop-Frame sein (`_is_dropframe(fps)` → `create_tape_slots(
drop_frame=True)`, `_make_timecode_slot(drop=True)`, Start = `_dropframe_count(tc)`).

⚠️ **Warum kritisch**: Resolve linkt über Reel + TC. Ist der Reel-TC Non-Drop, aber das
Medium Drop-Frame, verschiebt sich jede Kamera um ihren **akkumulierten DF-Versatz**
(108 F/Std bei 29,97). Kameras mit unterschiedlichem Tageszeit-TC driften dadurch
**relativ zueinander** (Realfall: 23:58 vs 08:27 → 56 s → „eine Cam am Ende aus, andere
läuft noch"). Der frühere fraktionale Code (`* 29.97`) traf DF **zufällig** (Echtzeit ≈
Drop-Frame); die nominale Umstellung brach das → deshalb explizit Drop-Frame.
- **Detektion (`_detect_dropframe`, aus der Datei — wie Resolve)**: Sony `rtmd` hat keinen
  `tmcd`-Track, ffprobe/ffmpeg normalisieren den TC-String auf ':'. Das Flag steht aber in
  Sonys **NonRealTimeMeta-XML** (Top-Level-`meta`-Box): `<LtcChange value="HHHHHHHH">` =
  SMPTE-12M-Hex, **Bit 6 (0x40) im Frames-Byte = Drop-Frame**. fps-Annahme `_is_dropframe`
  nur noch **Fallback** (tmcd-Kameras: Flag aus tmcd-Sample-Entry lesen — Rest-Sliver).
- **Nur der ABSOLUTE TC ist Drop-Frame.** Interne/relative Positionen (`source_in`, Record,
  Dauern) bleiben nominal/Non-Drop: `shared/frame_utils` zählt über `round(fps)` (Round-Trip
  exakt, byte-identisch für Ganzzahl-fps), und die Subtraktions-Ref in `_parse_edl` ruft
  `_probe_embedded_tc_frames` OHNE `dropframe` → Schnitte bleiben frame-exakt.

Isolierter Readback nach einem Umbau hier: **alle** Edit-Rates `30000/1001`, Tape-TC-Starts
= Drop-Frame-Zählung der embedded TCs mit `Drop=True` (bei 29,97/59,94).

---

## Aktuelle Struktur in build_aaf.py (Stand 0.6.7)

Kette je Quelle: `TapeMob (TC/Reel) → FileMob (Descriptor + NetworkLocator) → MasterMob (Bin-Clip) → CompositionMob`.

- **Video** (`build_aaf.py`): TapeMob (`create_tape_slots`, TC-Start = embedded TC)
  → FileMob mit **`CDCIDescriptor`** (StoredWidth/Height via `_probe_video_info`,
  ImageAspectRatio, FrameLayout, HorizontalSubsampling=2, ComponentWidth=8,
  VideoLineMap=[0,1], SampleRate=fps) + NetworkLocator → MasterMob (`name = stem`,
  in `cam_masters`).
- **Audio**: TapeMob → SourceMob mit **`PCMDescriptor`** (Length in **Samples**,
  SampleRate = Audiorate) + NetworkLocator → MasterMob.
- **Grund-Namen**: `reason_masters` — pro (Kamera, Grund) ein ZUSÄTZLICHER
  MasterMob (`_name_for`). Nur wenn `clip_name_pattern` gesetzt (Toggle an).

**Warum CDCIDescriptor (nicht ImportDescriptor):** Mit `ImportDescriptor` blieb
das Video in Premiere offline, OBWOHL der Locator korrekt gesetzt war — Premiere
erkennt einen ImportDescriptor nicht als linkbare Datei (Video-Clips im „Medien
verknüpfen"-Dialog hatten leeren Dateiname/-pfad, nur Bandname+TC). Das
funktionierende Audio nutzt `PCMDescriptor` (echter File-Descriptor) → linkte
sofort. Fix: Video auf `CDCIDescriptor` (echter File-Descriptor mit Maßen).
Bestätigt: Audio online nach Locator-Fix (25.07.); Video-Fix danach. ⚠️ Nach
diesem Umbau BEIDE gegentesten — Resolve (nutzt DaVinci-Style CDCIDescriptor
selbst) UND Premiere.

---

## Getestet-funktionierende Referenz-Struktur (DaVinci-Style, Premiere 25.6.4)

7 Mobs pro Quelle, mit **`CDCIDescriptor`** (Video) + **`PCMDescriptor`** (Audio),
getrennt (kein MultipleDescriptor). TC-Träger sind eigene TapeDescriptor-Mobs.

```
TapeDescriptor (Video-TC)   ←── CDCIDescriptor SourceMob (Video)  ←──┐
TapeDescriptor (Audio-Ch1)  ←──┐                                     ├── MasterMob ← CompositionMob
TapeDescriptor (Audio-Ch2)  ←── PCMDescriptor SourceMob (Audio) ←──┘
```

**CDCIDescriptor (Video) — Pflichtfelder:**
```python
mob_vid = f.create.SourceMob(); mob_vid.name = src.stem   # ohne Endung
cdci = f.create.CDCIDescriptor()
cdci["StoredWidth"].value = vid_w;  cdci["StoredHeight"].value = vid_h
cdci["ImageAspectRatio"].value = aspect        # Fraction, z.B. 16/9
cdci["FrameLayout"].value = "FullFrame"
cdci["HorizontalSubsampling"].value = 2;  cdci["ComponentWidth"].value = 8
cdci["VideoLineMap"].value = [0, 1]
cdci["SampleRate"].value = Fraction(fps_int, 1);  cdci["Length"].value = dur_vid
loc = f.create.NetworkLocator(); loc["URLString"].value = src.resolve().as_uri()
cdci["Locator"].value = [loc]                  # NICHT .append
mob_vid.descriptor = cdci
```

**PCMDescriptor (Audio) — Pflichtfelder:**
```python
pcm = f.create.PCMDescriptor()
pcm["AudioSamplingRate"].value = Fraction(48000, 1); pcm["Channels"].value = n_ch
pcm["QuantizationBits"].value = 16; pcm["BlockAlign"].value = 2
pcm["AverageBPS"].value = 48000 * 2
pcm["SampleRate"].value = Fraction(48000, 1)
pcm["Length"].value = dur_aud                  # in SAMPLES, nicht Frames!
pcm["Locator"].value = [loc]                   # gleiche URL wie Video
```
- Audio-Slot Edit-Rate = **fps** (`create_sound_slot(edit_rate=fps_int)`),
  Slot-LÄNGEN in Frames. Descriptor-`Length` dagegen in Samples.
- `mob.name` immer `src.stem` (ohne Endung), bei CDCI-, PCM- UND MasterMob.

Das VOLLSTÄNDIGE, getestete Code-Beispiel (inkl. TapeMob-Helper `_make_tape`,
CompositionMob) liegt zusätzlich in der Auto-Memory `reference_aaf_premiere.md`.
Bei einem CDCIDescriptor-Umbau von dort übernehmen und 1:1 gegen Resolve +
Premiere testen.

---

## Irrwege (was NICHT funktioniert — nicht nochmal probieren)

- **`desc.locator.append(loc)`** → Locator wird nicht gespeichert (pyaaf2-Bug).
- **`MultipleDescriptor`** → Premiere-Namensgenerator `_V1A2_XXXX` → offline.
- **`file:///Jardani/…` ohne `/Volumes/`** → linkt nur MobID-basiert (Premieres
  eigene Exporte), nicht URL-basiert.
- **TC als Offset im FileDescriptor** (statt in der TapeMob) → Frame-Out-of-Range.
- **WAV-Extraktion für Audio** → funktioniert, aber unerwünschte Extra-Datei.

---

## AAF-Änderungen testen (Reihenfolge)

1. **Isolierter pyaaf2-Readback (ohne NLE):** AAF schreiben, wieder öffnen, prüfen:
   ist `descriptor['Locator'].value` gefüllt, stimmt die URL, wie viele MasterMobs
   pro Quelle? Findet Struktur-Fehler sofort.
2. **DaVinci Resolve:** importieren, Medien online? Timeline korrekt? TC stimmt?
3. **Premiere Pro:** importieren — **keine** `_V01_`/`_A01_`-Namen, Medien
   **online**, ein Clip pro Kamera. Nur eine laufende Premiere-Installation kann
   das validieren (⚠️ ohne Premiere ist AAF-Premiere-Arbeit Blindflug).

---

## Zukunft: direkte NLE-Anbindung (löst das grundsätzlich)

Langfristplan (kein 1.0.0-Feature): die App direkt mit Resolve UND Premiere
verbinden (wie es die Web-App/`run_from_bin.py` mit Resolve schon tut), Bins als
Quelle nutzen und Timelines DIREKT in der NLE anlegen statt AAF zu exportieren.
Dann ist AAF nur noch die Fallback-Brücke für „andere NLEs / Avid" — die
Invarianten oben bleiben aber für diesen Fallback gültig.
