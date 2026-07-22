#!/usr/bin/env python3
"""Extrahiert den Abschnitt einer Version aus CHANGELOG.md und gibt ein
HTML-Fragment aus — genau die Form, die generate_appcast als CDATA-<description>
pro <item> einbettet (kein DOCTYPE/body). Die Website rendert dieselbe
<description> automatisch (Contract der Web-Session, 22.07.).

    python3 changelog_to_html.py 0.6.1  >  release/updates/MultiCamCutter-0.6.1.html

Exit 2, wenn CHANGELOG.md keinen Abschnitt fuer die Version hat — release.sh
bricht dann ab, statt stillschweigend ein Release ohne Notizen auszuliefern.

Bewusst KEIN Markdown-Paket (keine neue Dependency): der Changelog nutzt nur
eine kleine, feste Teilmenge (## Version, **fett**, - Liste, Absaetze).
"""

import html
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def _extract(version: str, text: str) -> str:
    """Zeilen des Abschnitts '## <version>' bis zur naechsten '## '-Zeile."""
    lines = text.splitlines()
    out, capturing = [], False
    for ln in lines:
        if ln.startswith("## "):
            if capturing:
                break
            capturing = ln[3:].strip() == version
            continue          # die Versions-Ueberschrift selbst nicht mituebernehmen
        if capturing:
            out.append(ln)
    return "\n".join(out).strip()


def _inline(s: str) -> str:
    """Text escapen, dann **fett** zu <strong>."""
    s = html.escape(s, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def _is_heading(s: str) -> bool:
    return bool(re.fullmatch(r"\*\*.+\*\*", s))


def _logical_lines(section: str) -> list:
    """Umbrochene Zeilen zu je einer logischen Zeile zusammenfuegen.

    Fortsetzungszeilen (weder leer, noch '- ', noch **Titel**) haengen an die
    vorherige — ABER nicht an eine Ueberschrift: nach '**Titel**' beginnt ein
    neuer Absatz. Sonst wuerden umbrochene Listenpunkte/Absaetze zerrissen bzw.
    Ueberschrift und Folgeabsatz verschmelzen.
    """
    out: list = []
    for raw in section.splitlines():
        s = raw.strip()
        if not s or s.startswith("- ") or _is_heading(s):
            out.append(s)
        else:
            prev = out[-1] if out else ""
            if prev and not _is_heading(prev):
                out[-1] = prev + " " + s        # Absatz- oder Listen-Umbruch
            else:
                out.append(s)                    # nach Titel/Leerzeile → neuer Absatz
    return out


def _to_html(section: str) -> str:
    parts, in_list = [], False

    def close_list():
        nonlocal in_list
        if in_list:
            parts.append("</ul>")
            in_list = False

    for ln in _logical_lines(section):
        if not ln:
            close_list()
        elif ln.startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append("<li>" + _inline(ln[2:].strip()) + "</li>")
        elif _is_heading(ln):
            close_list()
            parts.append("<h4>" + _inline(ln.strip("*").strip()) + "</h4>")
        else:
            close_list()
            parts.append("<p>" + _inline(ln) + "</p>")
    close_list()
    return "\n".join(parts)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: changelog_to_html.py <version>", file=sys.stderr)
        return 1
    version = sys.argv[1]
    if not CHANGELOG.exists():
        print(f"CHANGELOG.md nicht gefunden: {CHANGELOG}", file=sys.stderr)
        return 2
    section = _extract(version, CHANGELOG.read_text(encoding="utf-8"))
    if not section:
        print(f"Kein Changelog-Abschnitt fuer Version {version} in CHANGELOG.md.\n"
              f"Bitte '## {version}' mit Nutzernotizen ergaenzen.", file=sys.stderr)
        return 2
    sys.stdout.write(_to_html(section) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
