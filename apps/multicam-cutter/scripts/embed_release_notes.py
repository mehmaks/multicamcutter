#!/usr/bin/env python3
"""Bettet die Changelog-Notizen zweisprachig in den Appcast ein — fuer ALLE Items.

generate_appcast kann kein xml:lang (es behaelt hoechstens EINE <description>) und
verstuemmelt bei jedem Lauf die zweisprachigen Beschreibungen der AELTEREN Items.
Deshalb wird der Appcast NACH generate_appcast hier nachbearbeitet: in JEDES <item>
(Version aus der DMG-URL) kommen `<description xml:lang="de">` und, falls
CHANGELOG.en.md den Abschnitt hat, `<description xml:lang="en">`. Nur so bleiben auch
aeltere Eintraege deutsch — sonst zeigt die Website die aelteren nur noch englisch.
Die Website waehlt per Locale, mit Fallback auf DE (Contract, brain/Appcast-Hosting.md).

    python3 embed_release_notes.py <version> [appcast.xml]

<version> = die AKTUELLE Version: fuer SIE ist der deutsche Abschnitt Pflicht — Exit 2,
wenn er fehlt → release.sh bricht ab. Aeltere Versionen ohne Changelog-Abschnitt werden
uebersprungen. Fehlendes Englisch ist ok (die Website faellt auf DE zurueck).

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


def _strip_descriptions(item: str) -> str:
    # Bestehende <description>(n) entfernen — idempotent bei Wiederholung und raeumt
    # die von generate_appcast verstuemmelten Ein-Sprach-Reste weg.
    return re.sub(r"[ \t]*<description\b.*?</description>\n?", "", item, flags=re.S)


def _embed_one(item: str, version: str):
    """Setzt DE(+EN)-Notizen in EIN <item>. None, wenn kein deutscher
    Changelog-Abschnitt fuer diese Version existiert (dann keine Aenderung)."""
    item_clean = _strip_descriptions(item)
    enc = re.search(r"^([ \t]*)<enclosure\b", item_clean, re.M)
    if enc is None:
        return None
    block = _description_block(version, enc.group(1))
    if block is None:
        return None
    # Lambda statt r"\1"-String: der Block enthaelt CDATA-HTML, das re.sub in der
    # Ersetzungszeichenkette sonst als Backreference fehldeuten koennte.
    return re.sub(r"(^[ \t]*<enclosure\b)", lambda m: block + "\n" + m.group(1),
                  item_clean, count=1, flags=re.M)


def embed(version: str, appcast_path: Path) -> int:
    if not appcast_path.exists():
        print(f"Appcast nicht gefunden: {appcast_path}", file=sys.stderr)
        return 1
    text = appcast_path.read_text(encoding="utf-8")

    # ALLE Items zweisprachig befuellen — nicht nur die aktuelle Version.
    # generate_appcast regeneriert den Appcast bei jedem Release und verstuemmelt
    # dabei die xml:lang-Beschreibungen der aelteren Items (Sparkle kann kein
    # xml:lang, behaelt hoechstens EINE <description>). Wuerde hier nur die aktuelle
    # Version behandelt, verloeren die aelteren Eintraege ihr Deutsch — genau der
    # Website-Bug: neuester Eintrag DE, aeltere nur noch EN.
    state = {"current_found": False, "current_de": False}
    embedded: list = []
    skipped: list = []

    def process(m):
        item = m.group()
        vm = re.search(r"MultiCamCutter-([0-9][0-9.]*)\.dmg", item)
        if vm is None:
            return item  # Version nicht ableitbar → unangetastet
        ver = vm.group(1)
        is_current = ver == version
        if is_current:
            state["current_found"] = True
        new_item = _embed_one(item, ver)
        if new_item is None:
            # Kein DE-Abschnitt fuer diese Version: bestehende (evtl. falsch-
            # sprachige) Beschreibung entfernen, damit nichts Falsches stehen bleibt.
            skipped.append(ver)
            return _strip_descriptions(item)
        if is_current:
            state["current_de"] = True
        embedded.append(ver)
        return new_item

    new_text = re.sub(r"<item>.*?</item>", process, text, flags=re.S)

    # Release-Guard: die AKTUELLE Version muss existieren und einen DE-Abschnitt haben.
    if not state["current_found"]:
        print(f"Kein <item> mit MultiCamCutter-{version}.dmg im Appcast.", file=sys.stderr)
        return 1
    if not state["current_de"]:
        print(f"Kein deutscher Changelog-Abschnitt fuer {version} in CHANGELOG.md.\n"
              f"Bitte '## {version}' ergaenzen.", file=sys.stderr)
        return 2

    appcast_path.write_text(new_text, encoding="utf-8")

    for ver in embedded:
        langs = "de+en" if render(ver, "en") is not None else "nur de"
        print(f"  ✓ {ver}: Release-Notes eingebettet ({langs})")
    if skipped:
        print(f"  ℹ ohne Changelog-Abschnitt (keine Notizen): {', '.join(skipped)}")
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
