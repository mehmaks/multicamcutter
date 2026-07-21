#!/bin/bash
set -euo pipefail

# ── Retina-Hintergrund fuer das Installations-DMG bauen ────────────────────
#   bash scripts/dmg_background_tiff.sh ~/Desktop/mein-hintergrund@2x.png
#
# Nimmt EINE Grafik in doppelter Aufloesung (1280x800), rechnet die
# 1x-Fassung (640x400) herunter und verbindet beide zu einer
# Multi-Representation-TIFF. Ergebnis: scripts/dmg-background.tiff
#
# Warum ueberhaupt TIFF: Finder legt den DMG-Hintergrund in PIXELN = PUNKTEN an
# und skaliert nicht. Eine 1280x800-PNG erschiene daher als 1280x800 PUNKTE —
# sichtbar waere nur das linke obere Viertel. Eine TIFF mit beiden
# Repraesentationen loest das: macOS nimmt die 1x-Groesse fuer das Layout und
# zeichnet auf Retina aus der 2x-Fassung.

SRC="${1:-}"
[ -n "$SRC" ] || { echo "Usage: bash scripts/dmg_background_tiff.sh <hintergrund@2x.png>"; exit 1; }
[ -f "$SRC" ] || { echo "✗ Datei nicht gefunden: $SRC"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$SCRIPT_DIR/../../.."
OUT="$SCRIPT_DIR/dmg-background.tiff"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

W=$(sips -g pixelWidth  "$SRC" | awk '/pixelWidth/{print $2}')
H=$(sips -g pixelHeight "$SRC" | awk '/pixelHeight/{print $2}')
echo "  Eingabe: ${W}x${H}"
if [ "$W" != "1280" ] || [ "$H" != "800" ]; then
    echo "✗ Erwartet werden 1280x800 (doppelte Groesse von 640x400)."
    echo "  Das Layout-Raster steht in brain/Distribution-Setup.md — alle"
    echo "  Positionen dort gelten fuer 640x400, also hier verdoppelt:"
    echo "    App-Icon Mitte      340, 372      (belegt 212-468, 244-500)"
    echo "    Programme-Icon      940, 372      (belegt 812-1068, 244-500)"
    echo "    Finder-Labels       y 500-556 freihalten"
    exit 1
fi

# 1x herunterrechnen. Pillow mit Lanczos liefert bei Text sichtbar bessere
# Kanten als sips; sips bleibt Rueckfallebene, falls das venv fehlt.
PYBIN="$ROOT/venv/bin/python3"
if [ -x "$PYBIN" ] && "$PYBIN" -c "import PIL" 2>/dev/null; then
    "$PYBIN" - "$SRC" "$TMP/bg.png" <<'PY'
import sys
from PIL import Image
src, dst = sys.argv[1], sys.argv[2]
Image.open(src).convert("RGB").resize((640, 400), Image.LANCZOS).save(dst, "PNG")
PY
    echo "  1x erzeugt (Pillow/Lanczos)"
else
    cp "$SRC" "$TMP/bg.png"
    sips -z 400 640 "$TMP/bg.png" >/dev/null
    echo "  1x erzeugt (sips)"
fi
cp "$SRC" "$TMP/bg@2x.png"

tiffutil -cathidpicheck "$TMP/bg.png" "$TMP/bg@2x.png" -out "$OUT" >/dev/null
echo ""
echo "✓ $OUT"
echo "  enthaelt 640x400 (Layout) + 1280x800 (Retina)"
echo "  Wird beim naechsten 'bash scripts/release.sh <version>' automatisch verwendet."
