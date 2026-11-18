#!/usr/bin/env python3
"""Kanal-Vermerke im Appcast absichern (Beta-Kanal).

generate_appcast markiert mit --channel nur die NEU erzeugte Version. Ob aeltere
Eintraege ihren <sparkle:channel> beim Regenerieren behalten, ist nicht
dokumentiert. Verliert eine Beta ihren Vermerk, bekaemen ALLE Nutzer sie als
normales Update angeboten. Deshalb nach generate_appcast:

  1. Jeder Eintrag (per Build-Nummer <sparkle:version>) bekommt exakt den Kanal,
     den er im VORHERIGEN Feed hatte.
  2. Die neue Version bekommt "beta" genau dann, wenn --beta gesetzt ist.
  3. Pruefung: Danach muss alles stimmen, sonst Exit 1 (release.sh bricht ab,
     bevor etwas veroeffentlicht wird).

Text-basiert statt XML-Bibliothek: die Datei enthaelt CDATA-Beschreibungen, die
ein Parser beim Zurueckschreiben veraendern koennte.

Aufruf: appcast_channels.py ALT.xml NEU.xml VERSION [--beta]
"""
import re
import sys
from pathlib import Path

ITEM = re.compile(r"<item>.*?</item>", re.S)
BUILD = re.compile(r"<sparkle:version>([^<]+)</sparkle:version>")
SHORT = re.compile(r"<sparkle:shortVersionString>([^<]+)</sparkle:shortVersionString>")
CHAN = re.compile(r"[ \t]*<sparkle:channel>([^<]*)</sparkle:channel>\n?")


def channels(text):
    out = {}
    for it in ITEM.findall(text):
        b = BUILD.search(it)
        if b:
            c = CHAN.search(it)
            out[b.group(1)] = (c.group(1).strip() if c else None,
                               (SHORT.search(it) or [None, ""])[1])
    return out


def set_channel(item, chan):
    item = CHAN.sub("", item)
    if chan:
        # direkt nach <title> einfuegen, Einrueckung uebernehmen
        m = re.search(r"([ \t]*)<title>.*?</title>\n", item)
        ind = m.group(1) if m else "            "
        pos = m.end() if m else item.index(">") + 1
        item = item[:pos] + f"{ind}<sparkle:channel>{chan}</sparkle:channel>\n" + item[pos:]
    return item


def main():
    old_p, new_p, version = sys.argv[1], sys.argv[2], sys.argv[3]
    beta = "--beta" in sys.argv[4:]
    old = channels(Path(old_p).read_text(encoding="utf-8")) if Path(old_p).exists() else {}
    text = Path(new_p).read_text(encoding="utf-8")

    def fix(m):
        it = m.group()
        b = BUILD.search(it)
        s = SHORT.search(it)
        if not b:
            return it
        if s and s.group(1) == version and b.group(1) not in old:
            want = "beta" if beta else None          # die neue Version
        elif b.group(1) in old:
            want = old[b.group(1)][0]                 # wie im alten Feed
        else:
            return it                                 # unbekannt: unangetastet (wird gemeldet)
        return set_channel(it, want)

    text = ITEM.sub(fix, text)
    Path(new_p).write_text(text, encoding="utf-8")

    # Pruefung
    new = channels(text)
    errors = []
    for build, (chan, short) in new.items():
        if build in old and old[build][0] != chan:
            errors.append(f"{short} ({build}): Kanal {chan!r}, vorher {old[build][0]!r}")
        elif build not in old and short != version:
            errors.append(f"{short} ({build}): unbekannter Eintrag, Kanal nicht pruefbar")
    cur = [v for v in new.values() if v[1] == version]
    if not cur:
        errors.append(f"Version {version} fehlt im Feed")
    elif cur[0][0] != ("beta" if beta else None):
        errors.append(f"{version}: Kanal {cur[0][0]!r}, erwartet {'beta' if beta else 'stabil'}")
    for build, (chan, short) in sorted(new.items(), key=lambda kv: kv[0], reverse=True):
        print(f"  {short:16} {build}  {'BETA' if chan == 'beta' else 'stabil'}")
    if errors:
        print("✗ Kanal-Pruefung fehlgeschlagen:\n  " + "\n  ".join(errors))
        return 1
    print("  ✓ Kanal-Vermerke geprueft")
    return 0


if __name__ == "__main__":
    sys.exit(main())
