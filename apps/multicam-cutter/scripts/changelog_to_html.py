#!/usr/bin/env python3
"""Extrahiert den Abschnitt einer Version aus dem Changelog und gibt ein
HTML-Fragment aus — die Form, die als CDATA-<description> pro <item> in den
Appcast eingebettet wird (kein DOCTYPE/body). Die Website rendert dieselbe
<description> und waehlt bei mehreren per xml:lang nach Locale (Contract 22.07.,
brain/Appcast-Hosting.md → GEKLÄRT).

    python3 changelog_to_html.py 0.7.0            # Deutsch (CHANGELOG.md)
    python3 changelog_to_html.py 0.7.0 en         # Englisch (CHANGELOG.en.md)

Sprachen:
  de  CHANGELOG.md      — Autorensprache, PFLICHT (Exit 2, wenn Abschnitt fehlt)
  en  CHANGELOG.en.md   — optional (Exit 3, wenn Datei/Abschnitt fehlt → Fallback
                          auf DE uebernimmt die Website)

Bewusst KEIN Markdown-Paket (keine neue Dependency): der Changelog nutzt nur
eine kleine feste Teilmenge (## Version, **fett**, - Liste, umbrochene Absaetze).
"""

import html
import re
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
CHANGELOG = {"de": _DIR / "CHANGELOG.md", "en": _DIR / "CHANGELOG.en.md"}


def _extract(version: str, text: str) -> str:
    lines, out, capturing = text.splitlines(), [], False
    for ln in lines:
        if ln.startswith("## "):
            if capturing:
                break
            capturing = ln[3:].strip() == version
            continue
        if capturing:
            out.append(ln)
    return "\n".join(out).strip()


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def _is_heading(s: str) -> bool:
    return bool(re.fullmatch(r"\*\*.+\*\*", s))


def _logical_lines(section: str) -> list:
    """Umbrochene Zeilen zu je einer logischen Zeile zusammenfuegen — aber nicht
    ueber eine Ueberschrift hinweg (nach '**Titel**' beginnt ein neuer Absatz)."""
    out: list = []
    for raw in section.splitlines():
        s = raw.strip()
        if not s or s.startswith("- ") or _is_heading(s):
            out.append(s)
        else:
            prev = out[-1] if out else ""
            if prev and not _is_heading(prev):
                out[-1] = prev + " " + s
            else:
                out.append(s)
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


def render(version: str, lang: str = "de") -> str | None:
    """HTML-Fragment fuer Version+Sprache, oder None wenn nicht vorhanden.
    Importierbar von embed_release_notes.py."""
    path = CHANGELOG.get(lang)
    if not path or not path.exists():
        return None
    section = _extract(version, path.read_text(encoding="utf-8"))
    if not section:
        return None
    return _to_html(section)


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("Usage: changelog_to_html.py <version> [de|en]", file=sys.stderr)
        return 1
    version = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) == 3 else "de"
    if lang not in CHANGELOG:
        print(f"Unbekannte Sprache: {lang} (erlaubt: de, en)", file=sys.stderr)
        return 1
    frag = render(version, lang)
    if frag is None:
        code = 2 if lang == "de" else 3
        where = CHANGELOG[lang].name
        print(f"Kein Changelog-Abschnitt fuer {version} ({lang}) in {where}.",
              file=sys.stderr)
        return code
    sys.stdout.write(frag + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
