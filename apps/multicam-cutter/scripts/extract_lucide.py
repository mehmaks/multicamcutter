#!/usr/bin/env python3
"""Extrahiert Lucide-Icons aus dem node_modules der Website als SVGs.

Quelle ist lucide-react im Website-Repo — damit sind die App-Icons IMMER
exakt die Version, die auch die Website rendert. Die SVGs landen fest im
App-Bundle (SPM-Ressourcen, Sources/Icons/), stroke-width 2.5 statt
Lucide-Default 2 (User-Entscheid 24.07.: kraeftiger).

    python3 scripts/extract_lucide.py pencil circle-play trash-2 ...
"""

import re
import sys
from pathlib import Path

LUCIDE = Path.home() / "Developer/multicamcutter-web/node_modules/lucide-react/dist/esm/icons"
OUT = Path(__file__).resolve().parent.parent / "MulticamCutter/Sources/Icons"
STROKE_WIDTH = "2.5"

SVG_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="#000" stroke-width="{STROKE_WIDTH}" '
            'stroke-linecap="round" stroke-linejoin="round">')


def extract(name: str) -> bool:
    src = LUCIDE / f"{name}.mjs"
    if not src.exists():
        print(f"  ✗ {name}: nicht in lucide-react gefunden")
        return False
    text = src.read_text(encoding="utf-8")
    # __iconNode-Elemente: ["path", { d: "...", key: "..." }]
    elements = []
    for tag, attrs in re.findall(r'\[\s*"(\w+)",\s*\{([^}]*)\}', text, re.S):
        parts = []
        for m in re.finditer(r'(\w+):\s*(?:"([^"]*)"|([-\d.]+))', attrs):
            k = m.group(1)
            if k == "key":
                continue
            parts.append(f'{k}="{m.group(2) if m.group(2) is not None else m.group(3)}"')
        elements.append(f"<{tag} {' '.join(parts)}/>")
    if not elements:
        print(f"  ✗ {name}: keine Elemente geparst")
        return False
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.svg").write_text(SVG_HEAD + "".join(elements) + "</svg>",
                                     encoding="utf-8")
    print(f"  ✓ {name} ({len(elements)} Elemente)")
    return True


if __name__ == "__main__":
    names = sys.argv[1:]
    if not names:
        print(__doc__)
        raise SystemExit(1)
    ok = all([extract(n) for n in names])
    raise SystemExit(0 if ok else 1)
