# Bildsprache

Regelwerk für die Frage: **welche Einstellung wird wann gewählt?**

Abgrenzung zur bestehenden Rubrik „Cutaway Regeln": die beantwortet *wann* und
*wie lange* geschnitten wird. Bildsprache beantwortet *welche Kamera*.

**Grundsatz (User, 21.07.):** Nichts davon wird fest verdrahtet. Jede Regel ist in
den Einstellungen an- und abwählbar und über eigene sowie geteilte Parameter
beeinflussbar. **Presets speichern den kompletten Regelsatz**, damit sich
Produktionen durch einen einzigen Preset-Wechsel umstellen lassen, ohne
zusätzlich etwas einzustellen.

---

## Die Stufenleiter (Voraussetzung für alles Weitere)

Regeln dürfen **keine Kameras und keine festen Größennamen** kennen. Statt
„nah / halbnah / total" gilt ein abgeleitetes Maß:

> **Einstellungsgröße = Anzahl der Personen, die eine Kamera zeigt.**
> Weniger Personen = engere Einstellung.

Vorteile: beliebig viele Stufen, ergibt sich allein aus den Zuordnungen des Users,
und funktioniert **auch beim heutigen Stand mit nur einer Größe** — dann hat jede
Kamera Stufe 1, alle Regeln greifen ins Leere und das Verhalten bleibt wie bisher.
Genau deshalb ist die Leiter der erste Umsetzungsschritt (User, 21.07.).

Zwei Größen fallen an, beide werden gebraucht:

| Maß | Bedeutung | Wofür |
|---|---|---|
| **Absolute Stufe** | wie viele Personen zeigt die Kamera | „eine Stufe weiter", Bias |
| **Relative Rolle** | Position in der Leiter EINER Person | „die engste Einstellung von P2" |

Dieselbe Kamera kann für eine Person die engste und für eine andere eine Totale
sein — die Wahrheit steckt im Kamera-Personen-Graphen, nicht in Etiketten.

**Ist-Zustand:** Die Information liegt bereits vor (`--cam-mics`, `cameras.json`
→ `mics`), wird aber in `camRoles()` auf `close`/`wide` **eingeebnet**. Der erste
Schritt ist daher nicht „Leiter einführen", sondern „Leiter nicht mehr einebnen".

---

## Regeln (Wortlaut des Users, 21.07.)

Unverändert übernommen. Meine Einordnung steht getrennt darunter.

**R1 — Bias auf Einstellungsgröße**
> Sobald es Totale und/oder Medium Shots gibt, sollte man über einen Multitoggle
> einen Bias einstellen können, welche Einstellungsgröße am häufigsten genutzt
> werden soll. Es kann bei Mehrpersonenpodcasts genauso gut sein, dass ein Cutter
> häufig mit Medium-Shots als Mainshots arbeitet und Nahe und Totale als
> Variationen nutzt.

**R2 — Position der Sprachreaktion im Sprechersegment**
> Ich weiß nicht genau, wie man das in Parametern ausdrücken kann, aber vielleicht
> macht es Sinn, Sprachreaktionen, die weiter vorne auf einem längeren
> Sprechersegment passieren anders umzuschneiden, als wenn sie weiter hinten oder
> im Mittelteil eines Sprechersegments passieren. Beispiel: P1 spricht 60s lang.
> P2 überspricht bei Sekunde 10 und wird als Close-up geschnitten. P2 überspricht
> bei 30s und wird als Totale geschnitten.

**R3 — Position bei Max-Zeit-Cutaways**
> Selbes Prinzip bei Max-Zeit: Position im übergeordneten Sprechersegment
> eventuell als Maßstab für Einstellungsgröße nutzbar machen.

**R4 — Sichtbarkeitspflicht je Person**
> Wenn eine Person für X Sekunden nicht mehr gezeigt wurde, muss sie in irgendeiner
> Art Cutaway erscheinen. Beispiel: P1 spricht, P2 wird ab und zu nickend close
> gezeigt, P3 ist 40 Sekunden lang nicht mehr durch einen Cutaway gezeigt worden,
> also muss der nächste Cutaway verpflichtend eine Einstellung wählen, die P3
> beinhaltet.

**R5 — Dynamik-Faktor**
> So oft wie möglich versuchen, unterschiedliche Einstellungen zu nutzen (evtl.
> durch einen Dynamik-Faktor, wenn das geht? Geringer Faktor: sehr gleichbleibende
> Cutaway-Muster, hoher Faktor: sehr viel Variation).

**R6 — „von groß nach klein nach groß"**
> Verbietet den Schnitt von einer Closen direkt auf eine Totale (wenn es auch
> mittelnahe gibt) und umgekehrt.

**R7 — „immer über Totale"**
> Um von einer Person auf eine andere zu schneiden, muss immer über eine Totale
> (oder Halbnahe) geschnitten werden — das würde vorrangig Sprecherwechsel
> betreffen und dort eine ganz neue Art Cutaway etablieren. Was vorher Schnitt von
> Close P1 auf Close P2 wegen Sprecherwechsel war, wird dann zu Close P1 auf
> Totale auf Close P2 und umgekehrt.

**R8 — Schnitt nach „Entfernung" der Personen**
> 4 Personen im Podcast, jede hat eine Close für sich selbst, es gibt 2 Kameras,
> die jeweils 2 Personen zeigen und es gibt eine Totale auf der alle 4 zu sehen
> sind: Sprecherwechsel von P1 zu P2 wird von Close auf Halbnahe auf Close
> geschnitten, Sprecherwechsel von P1 zu P4 wird von Close auf Totale auf Close
> geschnitten — der Fall setzt voraus, dass P4 am weitesten von P1 wegsitzt. Ohne
> den Raum zu kennen, abstrahiert sich diese Regel natürlich darauf, welche
> Kameras welche Personen zeigen, und wenn P1 und P4 sich keine Halbnahe teilen,
> eben über die Totale geschnitten wird, weil dort sowohl P1 als auch P4 enthalten
> sind.

---

## Einordnung (meine, zur Diskussion)

### Vier Sorten, nicht acht gleichartige Regeln

| Sorte | Regeln | Wirkung |
|---|---|---|
| Gewicht (immer aktiv) | R1, R5 | färben jede Entscheidung |
| Kontext → Zielgröße | R2, R3 | wählen die Größe situationsabhängig |
| Pflicht mit Gedächtnis | R4 | sammelt „Schuld" über Zeit an |
| Übergangsregel | R6, R7, R8 | betreffen das PAAR aus Vorher und Nachher |

Daraus folgt die Aufteilung in den Einstellungen: **R1 und R5 sind
Grundeinstellungen**, die übrigen einzeln zuschaltbare Regeln.

### R6, R7 und R8 sind eine Regel

Nicht weil sie dasselbe wollen, sondern weil sie **dieselbe Formel in
verschiedenen Konstellationen** sind:

> Ein Wechsel von A nach B führt über die **kleinste Einstellung, die beide
> enthält**.

- A und B teilen eine Halbnahe → über die Halbnahe (= R6)
- Sie teilen nur die Totale → über die Totale (= R7)
- Sie sitzen weit auseinander → teilen naturgemäß keine engere Kamera → Totale (= R8)

Die Sitzordnung muss nicht bekannt sein; sie steckt bereits im
Kamera-Personen-Graphen. Das ist zugleich die **Abdeckungsregel B3** aus
`Plan-Multicam-3plus.md`, angewandt auf *Übergänge* statt auf *Sprecher* —
beide Vorhaben teilen sich also eine Mechanik.

### Die Übergangsregel ist nicht ein Schalter, sondern eine Matrix

Präzisierung des Users (21.07.): Die Regel muss **je Anlass** ein- und
ausschaltbar sein — und bei Cutaways zusätzlich **je Richtung**.

Der Grund ist eine Ungleichheit, die vorher untergegangen war:

| Vorgang | Form | Übergänge |
|---|---|---|
| **Sprecherwechsel** | einseitig, A → B | **einer** |
| **Cutaway** | Ausflug, A → X → A | **zwei**, unabhängig voneinander |

> „Sicher gibt es auch Schnittstile, die zwar nicht zu einem Nicken hin über die
> nächst größere Einstellung schneiden (weil wir Reaktionen ja instant wahrnehmen
> wollen) aber von einem Nicken über die nächstgrößere Einstellung zurück zum
> aktiven Sprecher."

Zum Cutaway **hin** ist die Zeit knapp: eine Zwischeneinstellung verschleppt die
Reaktion und nimmt ihr die Wirkung. **Zurück** gibt es keinen Zeitdruck — dort
kann eine größere Einstellung weich landen und den Raum wieder herstellen.

Vorgeschlagene Oberfläche — Kästchen je Zelle, **Voreinstellung: nur
Sprecherwechsel**:

|  | hin | zurück |
|---|---|---|
| Sprecherwechsel | **✓ Standard** | — (entfällt) |
| Nicken | ☐ | ☐ |
| Sprachreaktion | ☐ | ☐ |
| Max-Zeit | ☐ | ☐ |
| Pause | ☐ | ☐ |

Die Formel bleibt in allen Zellen dieselbe: **kleinste Einstellung, die beide
beteiligten Personen enthält** (`smallest_containing` in `shot_sizes.py`). Beim
Hinweg sind das Sprecher und Ziel, beim Rückweg Ziel und Sprecher — dieselbe
Menge, dieselbe Kamera. Nur *ob* geschnitten wird, unterscheidet sich.

Ist nur „zurück" aktiv, entsteht das Muster **A → X → T → A**.

### Zwei Regeln brauchen Gedächtnis

R4 (wer war wie lange nicht zu sehen) und R5 (was lief zuletzt) sind die einzigen,
die Zustand über die Timeline mitführen. Alle anderen sind lokale Entscheidungen.
Architektonisch ist das der größte Unterschied zu heute.

### Was noch fehlt

R2 und R3 setzen voraus, dass beim Einfügen eines Cutaways bekannt ist, **wo im
Sprechersegment** man sich befindet. Diese Größe gibt es in der Pipeline noch
nicht; sie muss vorher berechnet werden und würde beiden Regeln zugleich dienen.

### Vorgeschlagene Auswertung

```
Kandidaten (alle Kameras)
  → harte Filter   (Regeln mit Strenge = Pflicht)
  → Bewertung      (Grundeinstellungen + Regeln mit Strenge = Präferenz)
  → beste wählen
```

Damit sind die Regeln **kombinierbar statt gegenseitig ausschließend**, weil sie
an verschiedenen Stufen ansetzen.

### Strenge als Parameter

Jede Regel bekommt **Pflicht** oder **Präferenz**. Als Pflicht schließt sie
Kandidaten aus, als Präferenz gewichtet sie nur. Damit löst sich die Frage
„was gewinnt, wenn R4 und R6 sich widersprechen" **im Preset** statt im Code —
und dieselbe Regel deckt „nie direkt von Nah auf Totale" und „möglichst nicht"
in zwei Stellungen ab.

---

## Offene Fragen

- **R2/R3**: Wie wird „Position im Sprechersegment" auf eine Größe abgebildet —
  Schwellen (erstes Drittel / Mitte / letztes Drittel) oder stufenlos?
- **R4**: Zählt „gezeigt" nur als Cutaway, oder auch als Sprecher-Einstellung?
  Und zählt eine Totale, auf der die Person klein zu sehen ist, als „gezeigt"?
- **R5**: Bezieht sich Dynamik auf die Einstellungsgröße, auf die Kamera, oder
  auf beides?
- ~~R7: Nur bei Sprecherwechsel oder bei jedem Schnitt?~~ **Beantwortet (21.07.)**:
  Kästchen je Anlass UND je Richtung, Voreinstellung nur Sprecherwechsel.
- **Wie lang ist die Zwischeneinstellung?** Eigener Parameter oder an
  `min_shot_duration` gekoppelt? Zu kurz wirkt sie wie ein Fehler, zu lang
  bremst sie den Wechsel aus.
- **Was, wenn es keine gemeinsame Kamera gibt?** Übergang auslassen (harter
  Schnitt wie heute) oder die größte verfügbare nehmen?
- Welche Regeln sind im Standard-Preset aktiv? Voreinstellung sollte sich wie
  der heutige Stand verhalten.

## Umsetzungsreihenfolge (verabredet 21.07.)

1. ~~Dieses Dokument~~
2. ~~**Stufenleiter durchreichen statt einebnen**~~ — ERLEDIGT (21.07.):
   `modules/multicam_cutter/shot_sizes.py` mit `shot_level`, `camera_roles`,
   `ladder_for_person`, `smallest_containing`. `cameras.json` traegt jetzt
   `shot_level`. Die Engine berechnet die Rollen **selbst** aus den Zuordnungen
   und gleicht sie gegen `--cam-types` ab (Warnung bei Abweichung) — eine
   Invariante, die nur im Aufrufer lebt, ist keine. Verhalten unveraendert:
   es kommen nur Felder und eine Warnung hinzu, kein Konsument liest das Neue.
3. Erste Regel: die Übergangsregel (R6/R7/R8) — größter sichtbarer Effekt und
   teilt sich die Mechanik mit B3
4. Rubrik „Bildsprache" in den Experteneinstellungen, sobald es mehr als einen
   Schalter gibt. Was davon in die einfachen Einstellungen wandert, entscheidet
   der User später.

**Keine Abwärtskompatibilität nötig** (User, 21.07.): Die App ist noch nicht
ausgeliefert und wird außer vom User von niemandem genutzt. Preset-Format darf
brechen.
