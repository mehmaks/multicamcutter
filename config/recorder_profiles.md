# Rekorder-Profile (`recorder_profiles.json`)

Regeldatenbank fuer die Erkennung gesplitteter Aufnahmen (`shared/split_audio.py`).
Pro Rekorder steht hier, **woran er erkannt wird** und **wie seine Split-Teile
einander zugeordnet werden**. Neue Geraete = neues Profil, kein Code.

Gebuendelt in der App (`_internal/config/`). Ueberschreibbar per
`~/Library/Application Support/MulticamCutter/recorder_profiles.json` (ersetzt die
Datei komplett). Defekte Datei → eingebaute Standardregeln (Zeit + Signal + Namen).

## Immer zuerst (nicht konfigurierbar)

Teil B gehoert nur dann hinter Teil A, wenn B **samplegenau** dort beginnt, wo A
endet (BWF `time_reference`), und Audioformat + Rekorder (`originator`) gleich sind.
Die Profile entscheiden nur, **welcher** Kandidat es ist, wenn an einer Naht
mehrere Spuren gleichzeitig weiterlaufen (Mehrspur-Rekorder).

## Felder

| Feld | Bedeutung |
|------|-----------|
| `id`, `name` | Kennung + Anzeigename |
| `verified` | Wann/woran geprueft. Leer = Annahme |
| `match` | Erkennung. Alle angegebenen Regex muessen passen (`re.search`). Quellen siehe unten |
| `track_id` | Wo steht die Spur-/Eingangskennung? `{source, pattern}`, erste Regex-Gruppe = Kennung |
| `split_detection.steps` | Reihenfolge der Zuordnungsschritte (siehe unten) |
| `notes` | Freitext: Eigenheiten des Geraets |

**Quellen** (fuer `match` und `track_id.source`):
`originator` (bext, z. B. „ZOOM H6essential"), `coding_history` (bext, z. B.
„A=PCM,…,T=H6essential;VERSION=1.10;TRK=3;…"), `description` (bext, z. B.
„zTAKE=001…"), `ixml` (iXML-Chunk als Text — viele Profi-Rekorder schreiben dort
`TRACK_LIST`/`CHANNEL_INDEX` und `FILE_SET`/`FAMILY_UID`).

## Schritte (`steps`)

| Schritt | Was passiert |
|---------|--------------|
| `track` | Gleiche `track_id` = gleiche Spur. Greift nur, wenn ALLE Kandidaten eine eindeutige Kennung haben; sonst naechster Schritt. Ungleiche Kennung wird nie verbunden. Nahtsignal nur noch als Sicherung gegen klaren Sprung |
| `signal` | Nahtpruefung im Audio (LPC-Vorhersage ueber den Uebergang, nahtlos ≈ 1). Nur eindeutige Ergebnisse |
| `name` | Gemeinsames Dateinamen-Ende (`…_Tr1` ↔ `…_Tr1`). Nach `signal`: nur, wo das Signal nicht widerspricht. Ohne `signal` davor: allein |

Ohne `signal` und `name` werden bei mehreren Kandidaten nur `track`-Treffer
verbunden. Bei genau einem Kandidaten reicht die Zeitgleichheit (ausser
`signal` meldet einen klaren Sprung).

## Neues Geraet aufnehmen

1. Metadaten einer Datei ansehen:
   `venv/bin/python3 -c "from shared.split_audio import describe_recorder as d; print(d('pfad.wav'))"`
2. Profil mit `match` auf `originator` (oder `coding_history`) anlegen, **vor**
   allgemeineren Profilen (erstes passendes gewinnt).
3. An echtem Split-Material pruefen, `verified` ausfuellen.
