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

**R9 — Kein gleicher Blick über einen Pause-Trim hinweg** (User, 22.07.)
> Vor und hinter einem Pause-Trim möglichst keine Kameras schneiden, die
> dieselben Personen zeigen, da man den Sprung sehen könnte durch das
> Wegschneiden von Material. Wenn vor Trim P1 in einer Cam ist, sollte nach
> Trim eine Cam genutzt werden, in der P1 nicht vorkommt. Muss für ALLE
> gezeigten Personen gelten: ist vor Trim P1 und P2 zusammen zu sehen, darf
> nach dem Trim keine der beiden gezeigt werden — AUSSER es gibt keine Lösung.


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
| Schnitt-Nachbarschaft | R9 | Kamerawahl beidseits eines Pause-Trims |
| Pflicht/Gedächtnis | R10 | Cooldown je Zusatzkamera (in Schnitten) |

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

### Die Brücke wird je Übergang bestimmt, nicht einmal

Naheliegende Abkürzung, die **falsch** wäre: „Bei binärer Diarisierung ist die
Brücke immer dieselbe Kamera." Das stimmt sogar — betrifft jeder Sprecherwechsel
dieselben zwei Personen, ist die kleinste gemeinsame Kamera fest. Aber es ist
eine Eigenschaft der **heutigen Einschränkung**, keine der Sache:

- Mit N-facher Diarisierung (Stufe 2) gibt es Wechsel wie P1→P3. Jedes Paar kann
  eine andere kleinste gemeinsame Kamera haben — genau das ist R8.
- Schon **heute** bricht die Annahme bei **zwei gleich weiten Kameras**: immer
  dieselbe zu wählen widerspräche R5 (Dynamik).

`insert_transition_events` fragt deshalb je Übergang einen `resolve_bridge`
-Aufruf. Ein Aufrufer, der nur eine Brücke kennt, gibt sie immer zurück — aber
die Schnittstelle nimmt die Einschränkung nicht in sich auf.

### Übergangsregel auf Cutaway-Ebene — dieselbe Art wie am Sprecherwechsel

**Max-Zeit ist ausgenommen (User, 22.07.):** Max-Zeit-Cutaways schneiden bereits
als Reset in die nächstgrößere Einstellung (die Totale) — sie SIND schon das
große Bild. Ein Übergang zurück braucht dort keine Zwischenstufe. Betroffen sind
also nur die Cutaways, die auf eine andere CLOSE-Kamera schneiden: Nicken,
Sprachreaktion, Pause. (Auch die `*_wide`-Varianten bei Mehrpersonen-Reaktionen
sind schon die Totale und damit ausgenommen.)

**Idee für später (User, 22.07.):** Ein eigener Parameter für Max-Zeit-Cutaways,
der die Ziel-Einstellung wählt — zufällig auf andere Kameras / immer die
nächstgrößere / immer die größte. Davon hinge dann ab, ob NACH einem Max-Zeit-Cut
ein Übergang gesetzt wird: landet Max-Zeit schon auf der größten Einstellung,
entfällt er; sonst könnte er greifen. Bewusst zurückgestellt, bis die
Cutaway-Rückwege für Nicken/Sprachreaktion/Pause stehen.


Bestätigung des Users (22.07.), nachdem der Sprecherwechsel-Fall im Schnitt
überzeugte: Die Regel lässt sich auf Cutaways übertragen, derselben Art nach.
Gemeint ist vor allem der Rückweg — nach einem Cutaway über eine andere Größe
zurück zum Sprecher (die zurück-Spalte der Matrix). Der Hinweg zum Cutaway
bleibt knapp (Reaktion sofort sichtbar), der Rückweg darf weich landen.

Dieselben Bedingungen wie am Sprecherwechsel gelten auch hier: der Folgepart
nach der Brücke muss return_factor × Mindest-Schnittlänge erfüllen (2,5×). Der
User ausdrücklich: zwar fängt der Cleanup-Pass Edge-Cases ab, aber schon vorab
zu prüfen erzeugt weniger unschöne Fragmente, als sie nachträglich
wegzuräumen. → Die insert_transition_events-Mechanik (inkl. der A-B-A-Einheit-
Logik) ist damit auch die Grundlage für die Cutaway-Rückwege; sie muss nur an
den Cutaway-Positionen statt an der Basis-EDL laufen (zweite Anwendung).

### R10 — Cooldown je Zusatzkamera (User, 22.07.)

> Verhindern, dass jeder 3. oder 4. Schnitt in dieselbe weitere Cam schneidet.
> „Frequenz" ist das falsche Wort — eher **Cooldown**, und der gilt PRO
> weiterer Kamera. Eine Kamera darf z. B. erst nach jedem 7. Schnitt wieder
> benutzt werden. Bei mehreren Zusatzkameras bekommt JEDE ihren eigenen
> Cooldown, damit nicht kategorisch für 7 Schnitte abgeschaltet wird, dass
> weitere Einstellungen genutzt werden können.

**Wichtig — bezieht sich auf DIESELBE Kamera, nicht auf „weitere Einstellungen"
allgemein:** Im aktuellen Setup gibt es nur eine Totale, die immer wieder
verwendet wird; die soll gebremst werden. Sind mehrere da, bremst der Cooldown
jede einzeln, sodass ein Wechsel zwischen ihnen weiter erlaubt bleibt.

**Einordnung:** Gemessen in SCHNITTEN, nicht in Sekunden (der User denkt in
„jedem 7. Schnitt"). Damit ist es eine **Gedächtnis-Regel** wie R4/R5 — die
Auswahl muss je Kamera mitführen, wie viele Schnitte seit der letzten
Verwendung vergangen sind. Verwandt mit R5 (Dynamik-Faktor): R5 bestraft
Wiederholung graduell (weich), R10 sperrt sie für N Schnitte (hart). Denkbar
als zwei Stellungen derselben Idee — oder R10 als harte Kappung über dem
weichen R5.

**Greift an zwei Stellen:** bei der Wahl der Cutaway-/Reset-Kamera UND bei der
Brücken-Kamera der Übergangsregel — sonst umginge die weiche Landung den
Cooldown. Beide fragen letztlich `smallest_containing` bzw. die Kamerawahl; der
Cooldown wäre ein Filter davor.

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

## Für die Einstellungen exposen (wenn die Rubrik gebaut wird)

- **Hinweg-Schwelle `transition_return_factor`** (Default 2,5×). Engine-seitig bereits
  Parameter (`--transition-return-factor`, durchgereicht), nur ohne UI. User (22.07.):
  „Ich sehe hier und da Stellen, an denen ich mich frage, ob man den Faktor
  verkleinern könnte und immer noch eine schöne Schnittfrequenz bekommt." → als
  Regler in die Bildsprache-Rubrik, damit man ihn am Material justieren kann.

## Offene Fragen

- **R2/R3**: Wie wird „Position im Sprechersegment" auf eine Größe abgebildet —
  Schwellen (erstes Drittel / Mitte / letztes Drittel) oder stufenlos?
- **R4**: Zählt „gezeigt" nur als Cutaway, oder auch als Sprecher-Einstellung?
  Und zählt eine Totale, auf der die Person klein zu sehen ist, als „gezeigt"?
- **R5**: Bezieht sich Dynamik auf die Einstellungsgröße, auf die Kamera, oder
  auf beides?
- ~~R7: Nur bei Sprecherwechsel oder bei jedem Schnitt?~~ **Beantwortet (21.07.)**:
  Kästchen je Anlass UND je Richtung, Voreinstellung nur Sprecherwechsel.
- ~~Wie lang ist die Zwischeneinstellung?~~ **Beantwortet (21.07.)**: KEIN eigener
  Parameter. „0,8 s für einen Schnitt ist Quatsch" — die Brücke folgt der
  allgemeinen **Mindest-Schnittlänge** und nutzt zusätzlich den **Cutaway-
  Zufallsfaktor**. Bei `min_shot` 2,3 s und Zufall 0,20 ergibt das 2,32–2,72 s.
  Vorteil gegenüber einem eigenen Wert: die Brücke fügt sich in den Rhythmus ein,
  statt einen eigenen zu setzen, und zieht automatisch mit, wenn der Nutzer die
  Schnittfrequenz ändert.
- **Brücken bekommen eine eigene Begründung** (`transition`) — nicht nur zum
  Schutz vor PASS 3, sondern **für die Nachvollziehbarkeit**: die AAF-Clipnamen
  tragen den Schnittgrund, dort erscheint sie als „Übergang".
- ~~Was, wenn es keine gemeinsame Kamera gibt?~~ **Beantwortet (21.07.)**: dann
  wird geschnitten wie bisher — unangetasteter Cutaway nach den ursprünglichen
  Regeln. Kein Ersatz, keine Notlösung.
  **Wichtige Folge:** In Setups, in denen jede Kamera genau eine Person zeigt
  (alle bisherigen Zwei-Kamera-Folgen), gibt es **nie** ein gemeinsames Bild.
  Die Regel greift dort also nie und ändert nichts — sie kann deshalb
  **standardmäßig aktiv** sein, ohne bestehendes Material zu berühren.
  Für die Meldung heißt das: kein Warnton. Bei zwei Kameras ist der Rückfall der
  Normalfall, keine Auffälligkeit. Eine Zählung am Ende des Laufs genügt.
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
   teilt sich die Mechanik mit B3.

   **Einordnung in die Pipeline — ZWEI Anwendungen, nicht eine** (User, 21.07.):

   | Anlass | wann | warum |
   |---|---|---|
   | Sprecherwechsel | **vor** den Cutaways, auf der Basis-EDL | dort ist die Timeline noch ruhig, die Brücke hat Platz |
   | Cutaways | **nachdem** die Cutaway-Positionen feststehen | vorher ist gar nicht bekannt, wo Ausflüge liegen |

   Die frühe Anwendung ist strukturell dieselbe Operation wie
   `insert_totale_events` in `build_base_edl_from_audio.py` (Events schneiden,
   Segment einsetzen) — Mechanik und Ort sind also vorhanden.

   **Mindestlänge — Verlängern verworfen, Schwelle stattdessen musterabhängig**
   (User, 21.07., nach Zwischenstand):
   Die zuerst angedachte Verlängerung der Brücke über das ganze Event ist
   **raus**. Sie hätte den Sprecher unsichtbar gemacht — aus A-B-A würde A-T-A,
   B hätte gesprochen und wäre nie zu sehen. Außerdem entstand eine Unstetigkeit:
   B mit 2,2 s blieb sichtbar, B mit 2,4 s verschwand.
   Stattdessen entscheidet die Länge von B, **abhängig vom Muster**:

   | Muster | B braucht mindestens | bei min_shot 2,3 s |
   |---|---|---|
   | **A-B-A** (Rückkehr) | `return_factor` × Mindest-Schnittlänge (2,5) | 5,7 s |
   | **A-B-C** (Weitergang) | Brücke + Mindest-Schnittlänge | 4,6 s |

   Die Rückkehr verlangt mehr Raum: ein Ausflug, der gleich wieder zurückführt,
   wirkt sonst hektisch. Wird die Schwelle unterschritten, bleibt B
   **unangetastet** — kein Ersatz, keine Notlösung.
   **Aufgeklärt in zwei Schichten (22.07.), nachdem der User in der Timeline
   `C0002 → Totale (Übergang) → C0002` fand — eine Totale als Übergang zum SELBEN
   Sprecher:**

   1. **Korrektheit (PASS 3):** Der eigentliche Bug saß nicht in der Brückenlänge,
      sondern in `_is_diarization_switch`: der Schutz verlangte einen `speaker`-
      Nachbarn. Die Rückweg-Brücke (`transition`) neben B nahm B diesen Schutz,
      und PASS 3 löschte einen **echten** Sprecherwechsel → übrig blieb `A → T → A`.
      `_nearest_speaker` schaut jetzt durch Brücken hindurch; `A → B → T → A`
      bleibt geschützt. Das ist die robuste Ebene — sie trägt auch die kommenden
      Cutaway-Brücken.
   2. **Bildsprache (Hinweg vs. Rückweg):** Die 2,5×-Schwelle gehört NUR an den
      Hinweg — „ist B lang genug, um über die Totale HINEINzuschneiden?". Der
      Rückweg frisst A, nicht B, und ist eine weiche Landung; für ihn zählt nur,
      dass A noch `min_shot` übrig hat. Mein erster Fix legte die Schwelle
      fälschlich auch auf den Rückweg und sperrte damit genau die Landung, die
      gewollt ist.

   **Ergebnis je B-Länge:**

   | B | Muster |
   |---|---|
   | ≥ 2,5× min | `A → T → B → T → A` (beidseitig) |
   | < 2,5× min | `A → B → T → A` (B ungekürzt, nur Rückweg) |

   Kurzes B braucht keine Extra-Restriktion (User): der Hinweg kürzt es ohnehin
   nicht, und seine natürliche Länge stand schon vor der Übergangsregel in der
   Timeline.
   - **Cutaways:** Umgekehrt — passt der Rückweg nicht, wird **auf die Brücke
     verzichtet**. Eine Verlängerung würde hier die Rückkehr zum Sprecher
     verschlucken.
     *(User ausdrücklich als Vermutung markiert: möglicherweise zeigt sich im
     Schnitt, dass auch hier durchgezogen werden muss.)*

   ⚠️ **Offener Konflikt — PASS 3 löscht Brücken.** `_is_diarization_switch`
   (`add_reactions_to_edl.py:414`) schützt kurze Events nur im Muster
   **A → B → A** mit identischem Clip davor und danach. Eine Brücke beim
   Sprecherwechsel ist **A → T → B** — Vorgänger und Nachfolger sind
   verschieden, der Schutz greift nicht.
   Dazu kommt: `cleanup_min_duration` liegt bei **1,6 s**, der vorgeschlagene
   Standard für die Brücke bei **0,8 s**. Beides zusammen geht nicht.
   **Gelöst (21.07.): beides.** Die Brücke folgt der Mindest-Schnittlänge (liegt
   damit ohnehin über der Cleanup-Schwelle) UND bekommt die eigene Begründung
   `transition`, die PASS 3 überspringt. Der Schutz ist der eigentliche Punkt:
   PASS 3 soll versehentliche Fragmente entfernen, keine bewusst gesetzten
   Einstellungen — ein Aufräum-Parameter darf nicht über die Bildsprache
   entscheiden.
4. Rubrik „Bildsprache" in den Experteneinstellungen, sobald es mehr als einen
   Schalter gibt. Was davon in die einfachen Einstellungen wandert, entscheidet
   der User später.

**Keine Abwärtskompatibilität nötig** (User, 21.07.): Die App ist noch nicht
ausgeliefert und wird außer vom User von niemandem genutzt. Preset-Format darf
brechen.
