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
