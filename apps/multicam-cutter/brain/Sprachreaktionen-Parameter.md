# Sprachreaktionen — Parameter-Baseline

Momentaufnahme **vor** den ersten Änderungen an der FP-Problematik.
Zweck: jederzeit exakt zurückkönnen, auch wenn der Ist-Zustand nicht gut ist.

**Stand: 2026-07-20.** Rollback-Punkt: Git-Tag `sprachreaktion-baseline`.

```
git checkout sprachreaktion-baseline -- modules/multicam_cutter/build_base_edl_from_audio.py
```

Alle Werte unten sind die **effektiv wirksamen** (per `inspect` aus dem Code
gelesen, nicht abgeschrieben) für einen Lauf aus der Mac-App.

## Ebene 1 — in der App einstellbar

| Parameter | Wert | UI |
|---|---|---|
| `speaking_enabled` | `true` | Experten → Sprachreaktionen → Aktiv |
| `rise_db` | `6.0` | „Rise" |
| `speaking_max_dur` | `2.5` | „Max. Cutaway-Dauer" (⚠️ falsch beschriftet, begrenzt die **Burst**-Länge) |

## Ebene 2 — als params-Key durchgereicht, aber nirgends in der UI

Immer Default; **ohne Codeänderung** über `params.json` änderbar
(`run_from_bin.py:643-656`).

| Parameter | Wert | Bedeutung |
|---|---|---|
| `speaking_min_duration` | `0.20` s | kürzere Bursts werden verworfen |
| `speaking_attack_window` | `0.2` s | Baseline steigt schnell (α = 0,25) |
| `speaking_release_window` | `20.0` s | Baseline fällt langsam (α = 0,0025) |
| `speaking_warmup` | `3.0` s | Startwert = 75. Perzentil; Segmente **kürzer als das werden komplett übersprungen** |
| `speaking_hold` | `0.0` s | — |
| `speaking_mask_min_pause` | `0.3` s | ab wann eine On-Mic-Pause den Freeze auslöst |
| **`speaking_mask_padding`** | **`0.15` s** | **Freeze-Rand, aktuell symmetrisch vorn wie hinten** |

⭐ `speaking_mask_padding` ist der Hebel für den gemessenen Hauptfehler
(siehe unten) — und er ist ohne Codeänderung testbar. Für **asymmetrisches**
Padding (vorn 0,15 / hinten ~1,0) braucht es allerdings einen neuen Parameter,
weil `detect_on_speaker_pauses` denselben Wert für beide Ränder nutzt.

## Ebene 3 — hartkodiert, kein CLI-Flag, kein params-Key

| Parameter | Wert | Ort |
|---|---|---|
| `decay_hold_s` | `3.0` s | `_bursts_rolling` Signatur |
| `lookback_s` | `1.0` s | dito — Fenster, über das der Rise gemessen wird |
| `sustain_margin_db` | `1.5` dB | dito — Burst endet bei `baseline < peak − 1,5` |
| `no_burst_decay_factor` | `3.0` | dito — Baseline fällt 3× schneller ohne Burst |
| `mode` | `'peak'` | von `run_from_bin.py:654` fest gesetzt |
| `window_s` (Analyse) | `0.05` s | `--analysis-window` existiert, wird aber **nie übergeben** |
| `window_s` (Pausen) | `0.02` s | `detect_on_speaker_pauses` Signatur |
| Freeze-Schwelle | `quiet_speech + 3` dB | `build_base_edl_from_audio.py:1013-1014` |

## Welches Audio die Erkennung überhaupt sieht

Wichtig für jede Regel, die Pegel vergleicht — die Kette in
`build_base_edl_from_audio.py`:

```
combine_audios()        alle Mics EINER Cam summiert          → audio_cam1/2
Stufe A Normalisierung  Median-Ausgleich, IN PLACE  (:1098)   → audio_cam1/2
Crossbleed-Gate         rms_gate() → NEUE Variablen (:1161)   → _analysis1/2
Stufe B Post-Gate-Norm  nur auf _analysis1/2        (:1197)
```

| Verbraucher | Signal |
|---|---|
| **Sprachreaktionen** (`:1459`) | **`audio_cam1/2` — un-gegatet, nur Stufe A** |
| **Freeze-Maske** (`:1442`) | **`audio_cam1/2`** |
| Diarisierung (`:1227`), Totale (`:1351`), Pause-Trim (`:1420`), Stille-Cutaways (`:1547`) | `_analysis1/2` (gegatet + Stufe B) |

Das Gate bleibt bewusst draußen: Es dämpft das nicht-dominante Mic um bis zu
25 dB und würde genau das Signal zerstören, das hier ausgewertet wird.

**Der Crossbleed-Filter wirkt trotzdem — indirekt.** Er formt die Diarisierung,
also die Segmentgrenzen, und die Erkennung läuft segmentweise mit
Baseline-Reset. Ändert man ihn, verschieben sich die Bursts.

### Warum die Regeln gegen Stufe A immun sind
Stufe A ist ein **konstanter Gain je Kanal**. Korrelation ist skaleninvariant
(Regel A), und ein dB-*Anstieg innerhalb eines Kanals* ändert sich durch
konstanten Gain ebenfalls nicht (Regel B). Beide messen also robust.
Wäre das Gate eingeflossen, hätte es die Kanäle künstlich dekorreliert und
Regel A wäre von vornherein wertlos gewesen.

⚠️ **Verworfene Kennzahl: `mic_separation_db`.** Der kanalübergreifende Abstand
(On − Off) wurde anfangs als Erklärgröße benutzt (ep01 15,9 / ep02 11,0 dB). Er
taugt nicht: Stufe A hebt einen Kanal um x und senkt den anderen, wodurch sich
der Abstand je Sprecher um ±2x verschiebt — das kürzt sich nur bei ausgeglichenen
Redeanteilen (ep01: 42/58 %). Und er misst ohnehin nicht das, woran B hängt.
Ersetzt durch die kanalinterne Kennzahl unten (Abschnitt „Warum B kippt").

## Gemessene Baseline (Vergleichsmaßstab)

Folge 45 (ep01), 82,7 min, 2 Kameras.

- **145 Detektionen** gesamt (CAM1 70 / CAM2 75); daraus wurden im echten Lauf
  **70 Cutaways** (`reaction_speaking_reaction` in `final.colors.json`).
- **Ground Truth (User-Marker, erste 31 min, 100 % der Sprachreaktions-Cutaways
  markiert):** 22 Cutaways → **16 FP / 6 TP**, also **73 % FP**.
- **Trennendes Merkmal:** Abstand zwischen Freeze-Ende und Burst-Start.
  FP 0,10–1,40 s · TP 1,00–6,30 s. Eine Schwelle bei 1,0 s entfernt
  **13 von 14 FP** und verliert **0 von 6 TP**. Pegel, Rise, Dauer und
  Confidence überlappen dagegen alle.
- **Mechanismus:** Der Freeze wird gelöst, sobald das On-Mic nicht mehr still
  ist. Das Crossbleed auf dem Off-Mic braucht länger zurück; in dieser Lücke
  fällt die Baseline mit `no_burst_decay_factor` dreifach schnell, und das
  zurückkehrende Crossbleed erzeugt den falschen Anstieg. Der Freeze versagt
  also nicht — **er endet zu früh**.

⚠️ Verworfene Hypothese, damit sie nicht wiederkehrt: „Baseline sackt während
der Pause ab und kehrt zurück" ist **nicht** die Ursache. Die echten FPs zeigen
Einbrüche von nur 0,0–3,7 dB. Ein darauf gebauter Klassifikator schätzte 9 % FP,
die Marker sagen 73 %.

## Versuche — was NICHT funktioniert hat

Beide gegen die 22 Marker geprüft. Nicht wiederholen.

### ❌ Versuch 1: `speaking_mask_padding` 0,15 → 1,0 s
145 → 95 Detektionen. **7 von 16 FP entfernt, aber 2 von 6 TP verloren.**
**Warum:** Es gibt 426 (CAM1) bzw. **1118 (CAM2)** On-Speaker-Pausen. Mit ±1 s
Rand wachsen die Freeze-Bereiche zusammen und decken große Teile der Segmente ab.
Eine eingefrorene Baseline unterdrückt dann auch echte Reaktionen — ein
verlorener TP lag 3,65 s nach seinem Freeze-Ende. Pauschales Einfrieren ist ein
zu grobes Werkzeug.

### ❌ Versuch 2: Sperrfrist nach dem Freeze (`post_freeze_refractory_s` 0,95 s)
Idee: nicht die Baseline anhalten, sondern nur das Auslösen kurz sperren.
145 → 131 Detektionen. **Nur 1 von 16 FP entfernt**, dafür alle 6 TP erhalten.
**Warum:** Es unterdrückt nicht, es **verzögert**. Nachgemessen: 32 Bursts nur
nach hinten verschoben, Median 0,60 s, max 1,15 s. Der Rise liegt nach Ablauf
der Sperre immer noch über der Schwelle, der Burst feuert also einfach später.

Der Parameter existiert im Code (`--speaking-post-freeze-refractory`,
Default `0.0` = aus, von `run_from_bin` **nicht** übergeben) und ist damit
wirkungslos, solange ihn niemand setzt.

### ❌ Versuch 3: Adaptiver Freeze (`freeze_hold_max_s` 2,0 s, Marge 3 dB)
Über die Maske hinaus halten, solange `db` noch unter dem eingefrorenen Wert liegt.
145 → 124 Detektionen. **5 von 16 FP entfernt, wieder 2 von 6 TP verloren.**
**Warum:** Bei 3 dB Toleranz bleibt die Haltebedingung in leisen Passagen lange
wahr, der Freeze läuft also regelmäßig bis zum 2-s-Deckel und deckt damit wieder
zu viel ab — dieselbe Falle wie Versuch 1, nur später.

### Was alle drei zeigen
Das Problem ist **nicht der Zeitpunkt des Auslösens**, sondern dass die Baseline
in einem Fenster abfällt, in dem das Signal nicht repräsentativ ist (Crossbleed
noch nicht zurück). Pauschales Einfrieren behebt den Abfall, deckt aber zu viel
ab; die Sperrfrist deckt das Richtige ab, behebt den Abfall aber nicht.

Alle drei drehen an **derselben Stellschraube** (dem Freeze) und scheitern
daran, dass der Detektor **nur das Off-Mic sieht**. Dort ist „Crossbleed kehrt
zurück" und „Person sagt mhm" beides schlicht ein Pegelanstieg — kein
Freeze-Timing der Welt kann das trennen, weil die unterscheidende Information
gar nicht im Signal steckt, das er auswertet.

## ✅✅ Bester Befund: Hüllkurven-Korrelation der Spuren

Aus einer Beobachtung des Users an der Waveform: Bei den FPs hört der aktive
Sprecher auf und setzt wieder ein — **alle** Spuren zeigen denselben Abfall,
dieselbe Pause, denselben Anstieg. Bei reinem Crossbleed ist das Off-Mic eben
eine leisere Kopie des On-Mics; bei einer echten Reaktion kommt dort eigener
Inhalt hinzu und die Kurven laufen auseinander.

Gemessen als Pearson-Korrelation der beiden dB-Hüllkurven über **3 s vor bis
2 s nach** dem Burst-Start:

| | FP | TP |
|---|---|---|
| Median | **0,81** | **0,46** |
| Spanne | 0,33 … 0,97 | 0,25 … **0,67** |

Zwischen **0,67 und 0,76** liegt eine echte Lücke in den Daten. Eine Schwelle
darin entfernt **11 von 15 FP ohne TP-Verlust**. Empfehlung **0,75** statt des
rechnerischen Optimums 0,68 — gleiche Trefferzahl, aber Abstand zum obersten TP.

Die Steigung der Regression (wie stark das Off-Mic dem On-Mic folgt) ist
schwächer: 9 von 15 bei Schwelle 0,58.

⚠️ Nicht erfasst bleiben 4 FPs mit Korrelation 0,33–0,65. Dort laufen die Spuren
tatsächlich auseinander — andere Ursache, weiter offen.

## ✅✅✅ Drei Ursachen, drei Regeln (Stand der Analyse)

Es gibt **nicht eine** FP-Ursache. Drei unabhängig begründete Regeln, jede
gegen die 22 Marker gemessen:

| Regel | Mechanismus | FP entfernt | TP verloren |
|---|---|---|---|
| **A** Hüllkurven-Korrelation ≥ 0,75 | Crossbleed ist eine leisere Kopie des On-Mics → Spuren laufen im Gleichtakt | 11/15 | 0 |
| **B** On-Mic steigt ≥ 5 dB | Der Sprecher redet weiter → es ist Übersprechen, keine Reaktion | 7/15 | 0 |
| **C** Wortübernahme: ≤ 2,5 s vor Segmentende **und** danach ist diese Cam Sprecher | Kein „Mhm", sondern der **Beginn des eigenen Redebeitrags** | 2/15 | 0 |
| **A oder B oder C** | | **14/15** | **0** |

A und B überschneiden sich stark (beide zielen auf Crossbleed), C ist
unabhängig — und C erklärt zugleich die **überlangen Clips**: Ein Cutaway,
direkt gefolgt von Sprechermaterial derselben Kamera mit lückenlosem Source,
wird in `pause_trim_edl.py:356-368` zu **einem** Clip verschmolzen. Deshalb
gibt es „Sprachreaktionen" von 14,9 s / 8,6 s / 5,6 s (Median sonst 1,8 s) und
Nicken-Clips bis 19,3 s. Der Schnitt selbst ist dabei nicht falsch — es ist
durchgehendes Material einer Kamera —, aber er sitzt ~2 s zu früh, nämlich auf
der vermeintlichen Reaktion statt auf dem Sprecherwechsel.

**Nicht erfasst:** ein FP (00:03:36) mit Korrelation 0,54, fallendem On-Mic und
56 s Abstand zum Segmentende. Passt in kein Muster — Ursache offen.

⚠️ **Überanpassungs-Risiko ernst nehmen.** Drei Regeln mit je einer gefitteten
Schwelle auf **21 Datenpunkten**, aus **einem** 31-Minuten-Ausschnitt **einer**
Episode mit **zwei** Kameras. Die Trennungen sind sauber und jede Regel hat eine
eigenständige physikalische Begründung — aber vor dem Scharfschalten braucht es
einen zweiten markierten Ausschnitt, am besten aus einer anderen Episode.

## 🔬 Validierung an Episode 2 (Folge 47) — Regel B ist durchgefallen

Zweite Episode, gleicher Raum, anderer Gast: **4,9 dB weniger Mic-Trennung**
(11,0 statt 15,9 dB). 29 markierte Cutaways: 6 FP, 20 TP, 3 unsicher.
Bemerkenswert: die FP-Rate ist hier **21 %** statt 73 % in Episode 1.

| Regel | Episode 1 | Episode 2 | Gesamt |
|---|---|---|---|
| **A** Korrelation ≥ 0,75 | 11/15 FP, 0 TP weg | 4/6 FP, **0 TP weg** | **15/21 FP, 0 TP weg** |
| **B** On-Mic ≥ 5 dB | 7/15 FP, 0 TP weg | **0/6 FP, 5 TP weg** | 7/21 FP, 5 TP weg |
| **C** Wortübernahme | 2/15 FP, 0 TP weg | 1/6 FP, 1 TP weg | 3/21 FP, 1 TP weg |

- **Nur A:** 15/21 FP (71 %) entfernt, **0 von 26 TP verloren**.
- **A+B+C:** 17/21 FP (81 %), aber **6 von 26 TP verloren (23 %)** — untragbar.

### Warum B kippt
Prämisse war: „das On-Mic steigt → der Sprecher redet weiter → Übersprechen".
Das gilt nur, wenn die Stimme des *Reagierenden* **nicht** hörbar auf das Mikro
des Sprechers durchschlägt. Genau das unterscheidet die beiden Episoden:

| | echte Reaktionen, die das andere Mic um ≥ 5 dB heben |
|---|---|
| ep01 (Folge 45) | **0 von 6 (0 %)** |
| ep02 (Folge 47) | **5 von 20 (25 %)** |

In ep01 kann B jeden On-Mic-Anstieg gefahrlos als Übersprechen werten. In ep02
trifft sie damit jede vierte echte Reaktion. Noch deutlicher: Dort haben die
**FPs** einen medianen On-Mic-Anstieg von **−5,2 dB** — das Mikro wird leiser.
Bs Prämisse ist in dieser Aufnahme also nicht bloß nutzlos, sondern umgekehrt.

⚠️ **Nicht als „Artefakt" abtun** (frühere Formulierung hier war zu stark, vom
User zu Recht bemängelt). Mit n=2 lässt sich nicht sagen, welche Episode typisch
ist. Belegt ist: **B ist nicht robust und hängt am Durchschlagen des
Reagierenden.** Denkbar bleibt eine bedingte Regel („B nur, wenn dieser Anteil
unter X liegt") — X ist mit zwei Punkten nur nicht bestimmbar.

⚠️ **Diese Kennzahl braucht Labels** und taugt deshalb **nicht** als
Laufzeit-Schalter. Für ein bedingtes B bräuchte es eine Größe, die sich ohne
Markierung aus dem Audio ableiten lässt. Offene Frage an den größeren Datensatz.

### Was gilt jetzt
**A ist der Filter.** Über beide Episoden, über 4,9 dB Trennungsunterschied
hinweg, 15/21 FP ohne einen einzigen Verlust. Defaults entsprechend gesetzt:
`fp_on_rise_db = 999` (B aus), `fp_takeover_s = 0` (C aus).

C bleibt als Idee brauchbar — sie erwischt die überlangen Merge-Clips, die A
verfehlt —, aber 3 FP gegen 1 TP ist ein zu magerer Tausch. Bräuchte ein
engeres Fenster als 2,5 s.

⚠️ **Die Schwelle von A ist knapp.** Höchster TP über beide Episoden: 0,72.
Bei 0,75 bleiben nur 0,03 Abstand, und im Bereich 0,72–0,76 liegen sowohl TPs
als auch FPs. Mehr Material würde helfen; alternativ die Schwelle relativ zur
Grundkorrelation der Aufnahme setzen (Episode 1: 0,73, Episode 2: 0,71 — die
liegen erfreulich nah beieinander, was für eine feste Schwelle spricht).

## Umsetzung (Stand 2026-07-20)

Nachfilter in `detect_speaking_reactions` (`_fp_reject`), `_bursts_rolling`
unangetastet. **Default aus**, per `--speaking-fp-filter` einschaltbar:

| Flag | Default | Regel aus bei |
|---|---|---|
| `--speaking-fp-corr` | 0,75 | > 1,0 |
| `--speaking-fp-on-rise` | 5,0 dB | 999 |
| `--speaking-fp-takeover` | 2,5 s | 0 |

**Von `run_from_bin` bewusst NICHT übergeben** — die App verhält sich also
unverändert, bis der Filter validiert ist.

Verifiziert am Material: Filter aus → exakt 145 Detektionen wie die Baseline.
Filter an → 74. Gegen die 22 Marker: **14/15 FP entfernt, 0/6 TP verloren**
(die Implementierung reproduziert die Offline-Rechnung exakt). Verworfen wurden
71 Detektionen: 34× `on_mic_steigt`, 20× `gleichtakt`, 17× `wortuebernahme`.
Die Gründe stehen je Segment als `fp_dropped` im Debug-Dump.

⚠️ **Ein Warnsignal:** Der Filter entfernt 49 % aller Detektionen. Aus der
markierten Strecke (73 % FP, davon 93 % erfasst) wären ~68 % zu erwarten. Also
ist entweder der markierte Ausschnitt FP-reicher als der Rest, oder die Regeln
greifen außerhalb schlechter. Das ist ohne einen zweiten markierten Ausschnitt
nicht zu entscheiden.

## Zweitbester Befund: das ON-Mic mitbewerten

Kehrt das Crossbleed zurück, weil der Sprecher wieder einsetzt, steigt sein
**eigenes** Mikrofon mit. Bei einer echten Reaktion steigt nur das Off-Mic.

Gemessen an den 22 Markern (Pegel während des Bursts gegen die Sekunde davor,
jeweils Median):

| | FP (Median) | TP (Median) | TP-Maximum |
|---|---|---|---|
| Off-Mic steigt | −0,2 dB | +1,8 dB | — |
| **On-Mic steigt** | **+4,7 dB** | **−0,7 dB** | **+4,2 dB** |

**Regel „On-Mic steigt ≥ 5 dB → verwerfen": entfernt 7 von 15 FP und kostet
0 von 6 TP.** Der erste Eingriff ohne Kollateralschaden. Sieben FPs zeigen
On-Mic-Anstiege von +16 bis +28 dB — dort redet der Sprecher schlicht weiter.

⚠️ **Deckt nur die Hälfte ab.** Die übrigen FPs sind ein **anderes Phänomen**:
bei acht von ihnen **fällt** der Off-Mic-Pegel während des Bursts sogar
(−2 bis −8 dB). Dort feuert die Erkennung auf einer Baseline, die einem früheren
Anstieg noch hinterherläuft, während aktuell gar nichts lauter wird. Das ist
getrennt zu untersuchen.

**Umsetzung wäre günstig:** `detect_speaking_reactions` hat beide Audio-Arrays
bereits zur Hand. Ein Nachfilter über die fertigen Bursts genügt —
`_bursts_rolling` muss nicht angefasst werden.

## Reproduzierbare Prüfschleife

Kein 30-Minuten-Lauf nötig — nur der Base-EDL-Schritt (~1 min):

1. `build_base_edl_from_audio.py` direkt aufrufen (Mics, Cams, `--speaking-*`),
   mit **nicht gesetztem** `TOOLKIT_LICENSE_MODE` → schreibt `speaking_debug.json`
   (siehe `Dateiformate.md`; sonst greift der Dev-Guard nicht, siehe
   `Bekannte-Bugs.md`).
2. Marker aus der aktiven Resolve-Timeline lesen (`resolve_bridge.connection`),
   Clip unter dem Marker → `GetSourceStartFrame()`.
3. Quellframe → WAV-Zeit über den Versatz zwischen eigenem Lauf und
   `*_speaking.json` des echten Laufs (Listen von hinten ausrichten).
4. Merkmale an der Stelle aus der Kurve ziehen und FP gegen TP vergleichen.

## 🔑 Die FP-Rate hängt an der Mic-Trennung — pro RICHTUNG

Beobachtung des Users an ep04 („MIC2 viel leiser geregelt"): Sprachreaktionen sind
in die eine Richtung überwiegend TP, in die andere überwiegend FP. Nachgemessen —
bestätigt, und zwar deutlich:

| ep04, Reaktions-Cam | Sprecher-Pegel | Übersprechen | Trennung | FP-Rate |
|---|---|---|---|---|
| C7816 (MIC1) | −25,9 dB | −36,9 dB | **10,8 dB** | **75 %** (9/12) |
| C9322 (MIC2) | −14,4 dB | −37,8 dB | **25,2 dB** | **20 %** (2/10) |

Das Übersprechen ist in beiden Richtungen fast gleich laut. Der Unterschied kommt
vom **Sprecher**: kommt er nur mit −25,9 dB an, hebt er sich kaum vom Übersprechen
ab — und der Rise-Detektor liest jede Pegelschwankung als Reaktion.

Über alle vier Episoden (6 Richtungspaare): **r = −0,65**. Klarer Trend, aber
Ausreißer in beide Richtungen (ep02/C9730: 10,5 dB → nur 28 % FP; ep01/C7814:
15 dB → 75 %). **Starker Faktor, nicht die ganze Erklärung.** Der Vergleich
*innerhalb* einer Folge ist am belastbarsten, weil Material und Gast konstant sind.

⚠️ **Das ist der label-freie Indikator, der Regel B retten könnte.** Die Trennung
je Richtung ist vor der Analyse aus dem Audio berechenbar — anders als der Anteil
durchschlagender Reaktionen, der Marker braucht. Damit ließe sich der Filter je
Richtung unterschiedlich scharf stellen, statt global.

**Praktischer Hebel jenseits jeder Filterregel:** Die Aussteuerung beim Aufnehmen.
Ein Gast, der 11 dB leiser ankommt als der Host, produziert dreimal so viele
Fehlschnitte auf seiner Kamera.

## ❌ Verworfene Idee: Absolut-Pegel-Gate (Silence-Cutter quiet_speech) — 2026-07-27

Ausgelöst durch einen realen FP (C7816, 00:03:32): „auf der Spur ist gar kein
Ausschlag, das sollte keinen Burst auslösen". Idee: den pro Spur adaptiven
`quiet_speech`-Floor aus `shared/audio_analysis.suggest_threshold_kmeans` (Silence
Cutter) als **absoluten Boden** nehmen und Bursts verwerfen, deren Off-Mic-Pegel
den Floor nicht überschreitet.

**Gemessen an ep04 (22 gelabelte Cuts, 11 FP / 11 TP; Off-Mic-Spitze je Burst aus
`speaking_debug.json`, Floor per kmeans auf denselben `db`-Fenstern):**

| | FP | TP |
|---|---|---|
| Spitze − quiet_speech | Median **+17,6 dB** (10,7 … 22,4) | Median **+23,5 dB** (11,2 … 32,1) |
| Spitze − noise_floor | Median +23,4 dB (16,5 … 28,0) | Median +29,3 dB (16,8 … 37,9) |

**Verteilungen überlappen komplett.** Der eine FP, den Regel A verpasst (corr<0,75),
liegt bei **+22,4 dB** — mitten unter den lautesten TPs. Ein Gate bei
`quiet_speech + margin` entfernt bis margin +9 dB **0 FP**, bei +12 dB **1 FP gegen
1 TP**. Nutzlos.

**Warum die flache Waveform täuscht:** Am Burst gibt es sehr wohl einen
Übersprech-Ausschlag von +17 dB über dem Floor — nur beim Rauszoomen unsichtbar.
Der Pegel ist da; er unterscheidet bloß FP nicht von TP. Deckt sich mit dem
früheren Befund oben („Pegel, Rise, Dauer und Confidence überlappen alle") und mit
der Verwerfung von `mic_separation_db` als Per-Marker-Kennzahl. **Nicht erneut
vorschlagen.** MIC1-Floor in ep04: quiet_speech −41,6 / noise_floor −47,4 → nur
5,8 dB Rausch-zu-Sprache-Spanne, die ein 6-dB-Rise mühelos überspringt — das ist
der Mechanismus, nicht ein fehlender Absolut-Boden.

**Was bleibt:** Regel A (Korrelation) ist und bleibt der Filter (24/30 FP gesamt,
10/11 in ep04, aktiv auch im Folder-Pfad via `run_analysis`). Die ~1/11, die A
verpasst, sind der oben offene Sub-Typ (Spuren dekorrelieren, corr~0,58,
Off-Mic flach/fallend während der Burst auf nachlaufender Baseline feuert) — von
keiner getesteten Off-Mic-Kennzahl sauber trennbar.

## Datensatz und wie es weitergeht

Ground Truth liegt in **`datasets/speaking-fp/`** (eigenes README mit
Markier-Protokoll). Die Labels existierten vorher nur im Resolve-Projekt, die
Dumps nur in `/tmp` — beides flüchtig, deshalb gesichert.

- `ep*-marker.json` — Marker roh
- `features.json` — je Marker die Merkmale (Korrelation, On-Mic-Anstieg,
  Abstand zum Segmentende, Wortübernahme, Clip-Länge). **Arbeitsdatei**;
  Regeln lassen sich hiergegen bewerten, ohne die 3-MB-Dumps zu laden
- `dumps/` — Rohdaten, per `.gitignore` außen vor

### Was die gelben Marker ergaben
Gelb = „unsicher" (3 Stück in ep02). Sie liegen **exakt in der TP-Verteilung**
(Median-Korrelation 0,47 gegen 0,51 bei TP, 0,81 bei FP) und werden von Regel A
alle behalten. Erkenntnis: Die Unsicherheit kam **nicht aus dem Signal** — die
Erkennung war dort eindeutig, unklar war die *Schnittposition*.

→ Deshalb im Protokoll geschärft: **Gelb nur für „Reaktion nicht beurteilbar"**,
nicht für „Reaktion da, aber Schnitt sitzt schlecht". Zwei verschiedene Achsen;
vermischt verwässern sie ausgerechnet die Grenzfälle, die über die Schwelle
entscheiden. Die Schnittposition ist ein eigenes Thema und **deterministisch**
(`cutaway_frame = cluster_start − pre_roll`, 5 Frames fest). Der Zufallsfaktor
wirkt ausschließlich auf die **Länge** und verlängert nur — er kann einen
Einstieg nie verschieben.

### Offene Fragen an den größeren Datensatz (5–8 weitere Episoden geplant)
1. **Hält Regel A?** Bisher 15/21 FP bei 0/26 TP-Verlust. Der Abstand zum
   höchsten TP (0,72) ist mit 0,03 knapp — mehr Material entscheidet, ob 0,75
   trägt oder die Schwelle relativ zur Grundkorrelation gesetzt werden muss.
2. **Lässt sich B retten?** Braucht einen **label-freien** Indikator dafür, wie
   stark der Reagierende auf das andere Mic durchschlägt.
3. **Lohnt C?** 3 FP gegen 1 TP über beide Episoden. Erwischt als einzige die
   überlangen Merge-Clips. Bräuchte ein engeres Fenster als 2,5 s.
4. **Warum schwankt die FP-Rate so stark?** 73 % (ep01) gegen 21 % (ep02).
   Wenn sich das an einer Materialeigenschaft festmachen lässt, ist das
   wertvoller als jede Filterregel.
