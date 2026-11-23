"""Clipnamen nach dem Muster aus den App-Einstellungen („AAF-Clipnamen").

1:1 dieselbe Logik wie in build_aaf.build_aaf (`_label`, `_reason_word`, `_tidy`,
`_name_for`) — dort steht sie als Closure und bleibt bewusst unangetastet (AAF-Struktur
ist Fass-das-nicht-an). Genutzt vom XML-Export (build_xml.py). Ändert sich die Benennung
in build_aaf, muss sie hier mitgezogen werden.

Tokens: %S Quellname · %R Grund-Wort · %P Person auf der Kamera · %L „smartes" Label
(Person bei Sprecher-Schnitten, sonst Grund). Ohne Muster (Schalter aus): nur die Quelle,
wie in der AAF (ein MasterMob je Kamera).
"""
from __future__ import annotations

import re
from pathlib import Path

_REASON_LABEL = {
    'speaker':                    'Sprecher',
    'reaction_nodding':           'Nicken',
    'reaction_speaking_reaction': 'Sprachreaktion',
    'pause_cutaway':              'Stille',
    'max_time':                   'Max-Zeit',
    'transition':                 'Übergang',
}
_SEP = r'[-–—·|/•:]'
_TOKEN_RE = re.compile(r'%([SRPL])')


def _tidy(s: str) -> str:
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(rf'({_SEP})\s*(?:{_SEP}\s*)+', r'\1 ', s)
    s = re.sub(rf'^\s*{_SEP}\s*', '', s)
    s = re.sub(rf'\s*{_SEP}\s*$', '', s)
    return s.strip()


class ClipNamen:
    def __init__(self, cam_paths, cam_person_names=None, muster=None):
        self.cam_paths = cam_paths
        self.personen = cam_person_names or []
        self.muster = muster

    def person(self, cam_idx: int) -> str:
        if cam_idx < len(self.personen):
            return (self.personen[cam_idx] or '').strip()
        return ''

    def label(self, cam_idx: int, reason) -> str:
        if reason == 'speaker':
            p = self.person(cam_idx)
            if p:
                return p
        if reason and reason.endswith('_wide'):
            base = reason[:-len('_wide')]
            return f"{_REASON_LABEL.get(base, base)} (mehrere)"
        return _REASON_LABEL.get(reason, reason or '')

    @staticmethod
    def grund_wort(reason) -> str:
        if reason and reason.endswith('_wide'):
            base = reason[:-len('_wide')]
            return f"{_REASON_LABEL.get(base, base)} (mehrere)"
        return _REASON_LABEL.get(reason, reason or '')

    def name(self, cam_idx: int, reason) -> str:
        src = Path(self.cam_paths[cam_idx]).stem
        if not self.muster:
            return src          # Schalter „Schnittgründe in Clipnamen" aus: wie AAF nur die Quelle
        werte = {'S': src, 'R': self.grund_wort(reason), 'P': self.person(cam_idx),
                 'L': self.label(cam_idx, reason)}
        return _tidy(_TOKEN_RE.sub(lambda m: werte[m.group(1)], self.muster)) or src
