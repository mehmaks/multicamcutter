"""Uebergangsregel: Schnitte fuehren ueber die kleinste gemeinsame Einstellung.

Ein Wechsel von Person A zu Person B fuehrt ueber die kleinste Kamera, die BEIDE
zeigt. Teilen sie eine Halbnahe, wird es die Halbnahe; sonst die Totale. Die
Sitzordnung muss dafuer nicht bekannt sein — sie steckt in den Zuordnungen.

Diese eine Formel deckt drei vom User beschriebene Regeln ab (R6/R7/R8 in
brain/Bildsprache.md); sie unterscheiden sich nur darin, welche Kameras es gibt.

ZWEI VORGAENGE, NICHT EINER:

    Sprecherwechsel   einseitig   A -> B          ein Uebergang
    Cutaway           Ausflug     A -> X -> A     ZWEI, unabhaengig voneinander

Der Unterschied ist inhaltlich: Zum Cutaway HIN ist die Zeit knapp — eine
Zwischeneinstellung verschleppt eine Reaktion und nimmt ihr die Wirkung. ZURUECK
gibt es keinen Zeitdruck, dort kann eine groessere Einstellung weich landen.
Deshalb ist jede Richtung einzeln schaltbar.

RUECKFALL: Gibt es keine Kamera, die beide Personen zeigt, wird geschnitten wie
bisher — unveraendert, ohne Ersatz. In Setups, in denen jede Kamera genau eine
Person zeigt, ist das der Normalfall und keine Auffaelligkeit.

Diese Datei entscheidet NUR, wo etwas eingefuegt gehoert. Das Einfuegen selbst
passiert an anderer Stelle, damit die Regel ohne Pipeline testbar bleibt.
"""

from typing import Dict, List, Optional

from shot_sizes import person_ids, smallest_containing

# Anlaesse, an denen die Regel greifen kann. Schluessel = wie sie in der EDL
# als `reason` auftauchen.
OCCASION_BY_REASON = {
    'reaction_nodding':           'nodding',
    'reaction_speaking_reaction': 'speaking_reaction',
    'max_time':                   'max_time',
    'reaction_pause':             'pause',
}

# Eigene Begruendung — nicht nur, damit PASS 3 die Bruecke nicht als Fragment
# wegraeumt, sondern auch fuer die Nachvollziehbarkeit: die AAF-Clipnamen tragen
# den Schnittgrund, und dort soll erkennbar sein, warum ein Bild steht.
TRANSITION_REASON = 'transition'

DEFAULT_SETTINGS = {
    'enabled': True,
    # Voreinstellung: nur der Sprecherwechsel. Fuer Setups, in denen jede Kamera
    # eine Person zeigt, aendert das nichts — dort gibt es nie ein gemeinsames
    # Bild, die Regel faellt immer zurueck.
    'occasions': {
        'speaker_change':    {'to': True,  'back': False},   # 'back' entfaellt
        'nodding':           {'to': False, 'back': False},
        'speaking_reaction': {'to': False, 'back': False},
        'max_time':          {'to': False, 'back': False},
        'pause':             {'to': False, 'back': False},
    },
}


def bridge_frames(config: dict, fps: float, rng=None) -> int:
    """Laenge der Zwischeneinstellung — abgeleitet, nicht frei gesetzt.

    Ein eigener Dauer-Parameter war ein Fehlgriff (0,8 s waeren fuer einen
    Schnitt Quatsch, User 21.07.): die Bruecke folgt der allgemeinen
    Mindest-Schnittlaenge und nutzt denselben EINSEITIGEN Zufallsfaktor wie die
    Cutaways (`1.0 + uniform(0, randomness)` — verlaengert nur, verkuerzt nie).
    So fuegt sie sich in den Rhythmus ein, statt einen eigenen zu setzen, und
    reagiert automatisch mit, wenn der Nutzer die Schnittfrequenz aendert.
    """
    import random as _random
    rng = rng or _random
    base_s = float(config.get('min_shot', 2.3))
    randomness = float(config.get('randomness', 0.0))
    factor = 1.0 + rng.uniform(0.0, randomness) if randomness > 0 else 1.0
    return max(1, int(round(base_s * factor * fps)))


def _people_of(clip_name: str, by_name: Dict[str, dict]) -> List[str]:
    cam = by_name.get(clip_name)
    return person_ids(cam) if cam else []


def _wants(settings: dict, occasion: str, direction: str) -> bool:
    return bool(settings.get('occasions', {}).get(occasion, {}).get(direction))


def plan_transitions(events: List[dict], cameras: List[dict],
                     settings: Optional[dict] = None) -> List[dict]:
    """Ermittelt, wo Zwischeneinstellungen eingefuegt gehoeren.

    events: Liste mit mindestens `clip_name` und `reason`, in Timeline-Reihenfolge.
    Rueckgabe: Liste von {'before': index, 'clip_name', 'occasion', 'direction'} —
    einzufuegen VOR dem Event mit diesem Index. Absteigend sortiert, damit
    Einfuegen von hinten die noch offenen Indizes nicht verschiebt.
    """
    s = settings or DEFAULT_SETTINGS
    if not s.get('enabled', True):
        return []

    by_name = {c['name']: c for c in cameras}
    plan: List[dict] = []

    for i in range(len(events) - 1):
        cur, nxt = events[i], events[i + 1]
        if cur.get('clip_name') == nxt.get('clip_name'):
            continue                      # kein Bildwechsel, nichts zu ueberbruecken

        cur_reason = cur.get('reason', 'speaker')
        nxt_reason = nxt.get('reason', 'speaker')

        # Richtung und Anlass bestimmen. Ein Cutaway ist ein Ausflug: der Hinweg
        # geht vom Sprecher zum Cutaway, der Rueckweg zurueck zum Sprecher.
        if nxt_reason in OCCASION_BY_REASON:
            occasion, direction = OCCASION_BY_REASON[nxt_reason], 'to'
        elif cur_reason in OCCASION_BY_REASON:
            occasion, direction = OCCASION_BY_REASON[cur_reason], 'back'
        else:
            occasion, direction = 'speaker_change', 'to'

        if not _wants(s, occasion, direction):
            continue

        people = set(_people_of(cur['clip_name'], by_name)) | \
                 set(_people_of(nxt['clip_name'], by_name))
        if not people:
            continue

        bridge = smallest_containing(cameras, list(people))
        # Kein gemeinsames Bild -> unveraendert schneiden. Kein Ersatz.
        if bridge is None:
            continue
        # Die Bruecke waere dasselbe Bild wie eine der beiden Seiten -> nichts
        # gewonnen, nur ein Schnitt auf sich selbst.
        if bridge['name'] in (cur['clip_name'], nxt['clip_name']):
            continue

        plan.append({
            'before':    i + 1,
            'clip_name': bridge['name'],
            'occasion':  occasion,
            'direction': direction,
            'reason':    TRANSITION_REASON,
        })

    plan.sort(key=lambda p: p['before'], reverse=True)
    return plan


def summarize(plan: List[dict], events: List[dict]) -> str:
    """Einzeiler fuers Log — kein Warnton, nur eine Zaehlung."""
    if not plan:
        return "Uebergangsregel: keine Zwischeneinstellung eingefuegt"
    by_occ: Dict[str, int] = {}
    for p in plan:
        key = f"{p['occasion']}/{p['direction']}"
        by_occ[key] = by_occ.get(key, 0) + 1
    detail = ", ".join(f"{k}: {v}" for k, v in sorted(by_occ.items()))
    return (f"Uebergangsregel: {len(plan)} Zwischeneinstellung(en) "
            f"({len(events)} → {len(events) + len(plan)} Events) — {detail}")
