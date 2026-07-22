#!/usr/bin/env python3
"""Bettet die Changelog-Notizen einer Version zweisprachig in den Appcast ein.

generate_appcast kann kein xml:lang (es bettet nur EINE <description> ein).
Deshalb wird der Appcast NACH generate_appcast hier nachbearbeitet: ins <item>
der aktuellen Version kommen `<description xml:lang="de">` (Pflicht) und, falls
CHANGELOG.en.md den Abschnitt hat, `<description xml:lang="en">`. Die Website
waehlt per Locale, mit Fallback auf DE (Contract, brain/Appcast-Hosting.md).

    python3 embed_release_notes.py <version> [appcast.xml]

Exit 2, wenn der deutsche Abschnitt fehlt → release.sh bricht ab (kein Release
ohne Notizen). Fehlendes Englisch ist ok: dann nur DE, die Website faellt zurueck.

Bewusst String-Bearbeitung statt ElementTree: letzteres kann kein CDATA sauber
schreiben, und der Appcast ist von generate_appcast praezise formatiert.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from changelog_to_html import render  # noqa: E402

_DIR = Path(__file__).resolve().parent.parent
DEFAULT_APPCAST = _DIR / "release" / "updates" / "appcast.xml"


def _cdata(html_fragment: str) -> str:
    # CDATA endet an "]]>" — im Fragment kommt das nicht vor (einfache HTML-Tags),
    # aber sicher ist sicher: aufsplitten, falls doch.
    safe = html_fragment.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def _description_block(version: str, indent: str) -> str | None:
    de = render(version, "de")
    if de is None:
        return None
    lines = [f'{indent}<description xml:lang="de">{_cdata(de)}</description>']
    en = render(version, "en")
    if en is not None:
        lines.append(f'{indent}<description xml:lang="en">{_cdata(en)}</description>')
    return "\n".join(lines)


def embed(version: str, appcast_path: Path) -> int:
    if not appcast_path.exists():
        print(f"Appcast nicht gefunden: {appcast_path}", file=sys.stderr)
        return 1
    text = appcast_path.read_text(encoding="utf-8")

    # Das <item> der Version finden — ueber seine DMG-URL, nicht ueber die
    # Versionszeile allein (robuster gegen aehnliche Versionsstrings).
    dmg = f"MultiCamCutter-{version}.dmg"
    items = list(re.finditer(r"<item>.*?</item>", text, re.S))
    target = next((m for m in items if dmg in m.group()), None)
    if target is None:
        print(f"Kein <item> mit {dmg} im Appcast.", file=sys.stderr)
        return 1

    item = target.group()

    # Einrueckung an der <enclosure>-Zeile ablesen und uebernehmen.
    enc = re.search(r"^([ \t]*)<enclosure\b", item, re.M)
    if enc is None:
        print("Kein <enclosure> im Ziel-Item.", file=sys.stderr)
        return 1
    indent = enc.group(1)

    block = _description_block(version, indent)
    if block is None:
        print(f"Kein deutscher Changelog-Abschnitt fuer {version} in CHANGELOG.md.\n"
              f"Bitte '## {version}' ergaenzen.", file=sys.stderr)
        return 2

    # Etwaige bestehende <description>(n) im Item entfernen (idempotent bei
    # Wiederholungslauf), dann den Block vor <enclosure> einsetzen.
    item_clean = re.sub(r"[ \t]*<description\b.*?</description>\n?", "", item, flags=re.S)
    new_item = re.sub(r"(^[ \t]*<enclosure\b)", block + "\n" + r"\1",
                      item_clean, count=1, flags=re.M)

    text = text[:target.start()] + new_item + text[target.end():]
    appcast_path.write_text(text, encoding="utf-8")

    langs = "de+en" if render(version, "en") is not None else "nur de"
    print(f"  ✓ Release-Notes eingebettet ({langs}) in {dmg}")
    return 0


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("Usage: embed_release_notes.py <version> [appcast.xml]", file=sys.stderr)
        return 1
    version = sys.argv[1]
    appcast = Path(sys.argv[2]) if len(sys.argv) == 3 else DEFAULT_APPCAST
    return embed(version, appcast)


if __name__ == "__main__":
    raise SystemExit(main())
