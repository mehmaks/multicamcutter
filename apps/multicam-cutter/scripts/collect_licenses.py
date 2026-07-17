#!/usr/bin/env python3
"""Sammelt Open-Source-Lizenztexte fuer den Acknowledgements-View.

Quellen:
1. Frozen-Bundle `dist/multicam-engine/_internal/*.dist-info/` — die tatsaechlich
   ausgelieferten (kompilierten) Python-Pakete, verbatim aus ihren LICENSE-Dateien.
2. `scripts/extra_licenses/index.json` — handkuratierte Extras (FFmpeg/GPL, Sparkle,
   Python-Runtime sowie reine Python-Pakete, die im PYZ liegen und kein dist-info
   im _internal haben: requests, pyaaf2, mediapipe, opencv, soundfile).

Ergebnis: `scripts/acknowledgements.json` -> von build_app.sh in die .app kopiert,
vom SwiftUI-AcknowledgementsView geladen.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # apps/multicam-cutter
FROZEN = ROOT / "dist" / "multicam-engine" / "_internal"
EXTRA_DIR = ROOT / "scripts" / "extra_licenses"
OUT = ROOT / "scripts" / "acknowledgements.json"

# Huebschere Anzeigenamen fuer die Auto-gesammelten Pakete
PRETTY = {
    "torch": "PyTorch", "pyyaml": "PyYAML", "pillow": "Pillow",
    "scikit_learn": "scikit-learn", "huggingface_hub": "Hugging Face Hub",
    "typing_extensions": "typing-extensions", "markupsafe": "MarkupSafe",
    "jinja2": "Jinja2", "transformers": "Transformers", "numpy": "NumPy",
    "scipy": "SciPy",
}
LICENSE_FILE_RE = re.compile(r"^(LICENSE|LICENCE|COPYING|NOTICE)", re.IGNORECASE)


def guess_license(distinfo: Path) -> str:
    """License-Label aus METADATA best-effort ableiten."""
    meta = distinfo / "METADATA"
    if not meta.exists():
        return "Siehe Lizenztext"
    expr = classifier = simple = None
    for line in meta.read_text(errors="ignore").splitlines():
        if line.startswith("License-Expression:"):
            expr = line.split(":", 1)[1].strip()
        elif line.startswith("Classifier: License :: OSI Approved ::"):
            classifier = line.split("::")[-1].strip()
        elif line.startswith("License:") and len(line) < 60:
            simple = line.split(":", 1)[1].strip()
        if line.startswith("Name:"):  # Header vorbei
            continue
    return expr or classifier or simple or "Siehe Lizenztext"


def read_license_texts(distinfo: Path) -> str:
    """Alle LICENSE/COPYING/NOTICE-Dateien eines dist-info verbatim zusammenfassen."""
    parts = []
    # dist-info/licenses/* (neuere Wheels) + dist-info/* (aeltere)
    for base in (distinfo / "licenses", distinfo):
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*") if base.name == "licenses" else base.glob("*")):
            if f.is_file() and LICENSE_FILE_RE.match(f.name):
                try:
                    parts.append(f.read_text(errors="ignore").strip())
                except Exception:
                    pass
    # Deduplizieren (licenses/ und Top-Level koennen dieselbe Datei doppeln)
    seen, uniq = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return "\n\n".join(uniq)


def collect_frozen() -> dict:
    comps = {}
    if not FROZEN.is_dir():
        print(f"  ! Frozen-Bundle fehlt: {FROZEN}")
        return comps
    for di in sorted(FROZEN.glob("*.dist-info")):
        m = re.match(r"(.+)-([\d][^-]*)\.dist-info$", di.name)
        if not m:
            continue
        raw, version = m.group(1), m.group(2)
        text = read_license_texts(di)
        if not text:
            continue  # ohne Lizenztext nicht auflisten
        name = PRETTY.get(raw.lower(), raw)
        comps[name.lower()] = {
            "name": name, "version": version,
            "license": guess_license(di), "url": "", "note": "", "text": text,
        }
    return comps


def collect_extras() -> dict:
    comps = {}
    index = EXTRA_DIR / "index.json"
    if not index.exists():
        print(f"  ! Extras-Index fehlt: {index}")
        return comps
    for e in json.loads(index.read_text()):
        f = EXTRA_DIR / e["file"]
        if not f.exists():
            print(f"  ! Extra-Text fehlt: {f}")
            continue
        comps[e["name"].lower()] = {
            "name": e["name"], "version": e.get("version", ""),
            "license": e.get("license", "Siehe Lizenztext"),
            "url": e.get("url", ""), "note": e.get("note", ""),
            "text": f.read_text(errors="ignore").strip(),
        }
    return comps


def is_copyleft(lic: str) -> bool:
    return bool(re.search(r"GPL|MPL|EUPL|copyleft", lic, re.IGNORECASE))


def main():
    merged = collect_frozen()
    merged.update(collect_extras())  # Extras haben Vorrang bei Namensgleichheit
    comps = list(merged.values())
    # Copyleft (GPL/LGPL/MPL) zuerst — rechtlich relevanteste oben —, dann alphabetisch
    comps.sort(key=lambda c: (not is_copyleft(c["license"]), c["name"].lower()))
    OUT.write_text(json.dumps({"components": comps}, ensure_ascii=False, indent=2))
    print(f"  {len(comps)} Komponenten -> {OUT.relative_to(ROOT)}")
    for c in comps[:6]:
        print(f"    - {c['name']} ({c['license']})")
    print("    ...")


if __name__ == "__main__":
    main()
