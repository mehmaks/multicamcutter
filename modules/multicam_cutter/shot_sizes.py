"""Einstellungsgroessen als STUFENLEITER statt als zwei Klassen.

Bis hierher kannte die Pipeline nur `close` und `wide`. Das reicht fuer zwei
Kameras und bricht bei jeder weiteren Groesse: „eine Stufe weiter" laesst sich
damit nicht ausdruecken, und Regeln muessten feste Namen wie „halbnah" kennen.

Grundlage ist stattdessen ein abgeleitetes Mass:

    Einstellungsgroesse = Anzahl der Personen, die eine Kamera zeigt.
    Weniger Personen = engere Einstellung.

Das ergibt beliebig viele Stufen, folgt allein den Zuordnungen des Users und
funktioniert auch dann, wenn es nur eine Groesse gibt — dann hat jede Kamera
Stufe 1 und alles verhaelt sich wie bisher.

Siehe brain/Bildsprache.md.
"""

from typing import Dict, List


def shot_level(cam: dict) -> int:
    """Absolute Stufe: Anzahl gezeigter Personen. Kleiner = enger."""
    return max(1, len(cam.get('mics') or []))


def person_ids(cam: dict) -> List[str]:
    """Wen zeigt diese Kamera? Mic-Pfade dienen als Personen-Identitaet
    (eine Person = ein Mikrofon, siehe EngineController.Person)."""
    return list(cam.get('mics') or [])


def camera_roles(cameras: List[dict]) -> Dict[str, str]:
    """Rolle je Kamera: 'close' oder 'wide' — aus dem Personen-Graphen abgeleitet.

    Regel (identisch zu EngineController.camRoles): Fuer jede Person ist ihre
    engste Kamera die mit den WENIGSTEN Personen. Eine Kamera ist TOTALE, wenn
    JEDE Person darauf woanders enger zu sehen ist; ist sie fuer mindestens eine
    Person die engste, ist sie ein CLOSE („Close gewinnt").

    Bewusst hier nachgebildet, obwohl die App dasselbe berechnet und als
    `--cam-types` schickt: die Engine soll ihre eigene Wahrheit haben statt dem
    Aufrufer zu vertrauen. Weichen beide ab, ist das ein Fehler, den man sehen
    will — nicht einer, den man erbt.
    """
    min_count: Dict[str, int] = {}
    for cam in cameras:
        ppl = person_ids(cam)
        if not ppl:
            continue
        n = len(ppl)
        for pid in ppl:
            min_count[pid] = min(min_count.get(pid, n), n)

    roles: Dict[str, str] = {}
    for cam in cameras:
        ppl = person_ids(cam)
        if not ppl:
            roles[cam['name']] = 'unused'
            continue
        n = len(ppl)
        roles[cam['name']] = 'close' if any(min_count[p] == n for p in ppl) else 'wide'
    return roles


def ladder_for_person(cameras: List[dict], person: str) -> List[dict]:
    """Kameras, die diese Person zeigen — engste zuerst.

    Die RELATIVE Rolle einer Kamera haengt von der Person ab: dasselbe Bild kann
    fuer den Gast die engste Einstellung und fuer den Host eine Totale sein.
    """
    return sorted((c for c in cameras if person in person_ids(c)), key=shot_level)


def smallest_containing(cameras: List[dict], people: List[str]) -> dict:
    """Kleinste Kamera, die ALLE genannten Personen zeigt — sonst None.

    Das ist der Kern der geplanten Uebergangsregel (R6/R7/R8 in
    brain/Bildsprache.md): ein Wechsel von A nach B fuehrt ueber die kleinste
    Einstellung, die beide enthaelt. Teilen sie eine Halbnahe, wird es die
    Halbnahe; sonst die Totale. Die Sitzordnung muss dafuer nicht bekannt sein —
    sie steckt bereits in den Zuordnungen.
    """
    need = set(people)
    fits = [c for c in cameras if need.issubset(set(person_ids(c)))]
    return min(fits, key=shot_level) if fits else None
