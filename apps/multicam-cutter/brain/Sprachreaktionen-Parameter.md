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

## Gemessene Baseline (Vergleichsmaßstab)

Episode „45 - Mario Koch", 82,7 min, 2 Kameras.

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
