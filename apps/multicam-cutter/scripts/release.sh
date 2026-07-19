#!/bin/bash
set -euo pipefail

# ── MultiCamCutter Release (ein Befehl) ────────────────────────────────────
#   bash scripts/release.sh 0.5.0
#
# Macht in einem Rutsch:
#   1. Version setzen (an build_app.sh durchgereicht)
#   2. Mit Developer ID signiert bauen (Hardened Runtime)
#   3. Notarisieren + stapeln + verifizieren (scripts/notarize.sh)
#   4. Sparkle-Appcast erzeugen — NUR wenn DOWNLOAD_URL_PREFIX gesetzt ist
#
# Das Hochladen (DMG → Objekt-Storage, appcast.xml → Website) bleibt bewusst ein
# separater, bestätigter Schritt („nach außen gehen") — release.sh zeigt am Ende,
# was zu tun ist.
#
# MUSS im eigenen Terminal laufen (nicht headless): codesign UND generate_appcast
# greifen auf private Schlüssel im Login-Schlüsselbund zu. Beim ersten Mal je ein
# Dialog → „Immer erlauben"; danach nie wieder.
#
# Env:
#   SIGN_IDENTITY        Developer-ID-String (Default: aus dem Schlüsselbund erkannt)
#   NOTARY_PROFILE       notarytool-Profil (Default: MulticamNotary)
#   DOWNLOAD_URL_PREFIX  Enclosure-Prefix im Appcast
#                        (Default: https://multicamcutter.pantake.com/downloads/ — fixer
#                         Contract, siehe brain/Appcast-Hosting.md; R2 dahinter ist live)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/.."

# ── 1. Version prüfen ──────────────────────────────────────────────────────
VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Aufruf: bash scripts/release.sh <version>   (z. B. 0.5.0)"
    exit 1
fi

# ── 2. Signier-Identität ermitteln ─────────────────────────────────────────
SIGN_IDENTITY="${SIGN_IDENTITY:-$(security find-identity -v -p codesigning \
    | awk -F'"' '/Developer ID Application/{print $2; exit}')}"
if [ -z "$SIGN_IDENTITY" ]; then
    echo "✗ Kein 'Developer ID Application'-Zertifikat im Schlüsselbund gefunden."
    echo "  Prüfen: security find-identity -v -p codesigning"
    exit 1
fi

echo "=== MultiCamCutter Release $VERSION ==="
echo "  Identität: $SIGN_IDENTITY"
echo "  Notary:    ${NOTARY_PROFILE:-MulticamNotary}"
echo ""

# ── 3. Signiert bauen ──────────────────────────────────────────────────────
echo "───── [1/3] Build + Developer-ID-Signierung ─────"
MARKETING_VERSION="$VERSION" SIGN_IDENTITY="$SIGN_IDENTITY" bash "$SCRIPT_DIR/build_app.sh"

# ── 4. Notarisieren ────────────────────────────────────────────────────────
echo ""
echo "───── [2/3] Notarisierung ─────"
bash "$SCRIPT_DIR/notarize.sh"

DMG="$APP_DIR/release/MultiCamCutter.dmg"

# ── 5. Appcast (optional) ──────────────────────────────────────────────────
echo ""
echo "───── [3/3] Appcast ─────"
# Prefix ist ein fixer Contract (R2 hinter multicamcutter.pantake.com/downloads/
# ist live) — daher Default, kein Überspringen mehr. Per Env überschreibbar.
DOWNLOAD_URL_PREFIX="${DOWNLOAD_URL_PREFIX:-https://multicamcutter.pantake.com/downloads/}"

GEN_APPCAST="$(find "$APP_DIR/MulticamCutter/.build/artifacts" -name generate_appcast -type f 2>/dev/null | head -1)"
[ -x "$GEN_APPCAST" ] || { echo "✗ generate_appcast nicht gefunden (erst 'swift build')"; exit 1; }

UPDATES_DIR="$APP_DIR/release/updates"
DMG_NAME="MultiCamCutter-$VERSION.dmg"
mkdir -p "$UPDATES_DIR"
# Versionierter Dateiname → keine Kollision im Storage über Releases hinweg.
# ALLE bisherigen Release-DMGs sollten hier liegen bleiben, damit der Appcast
# die komplette Update-Historie (inkl. Deltas) behält.
cp "$DMG" "$UPDATES_DIR/$DMG_NAME"

echo "► generate_appcast (signiert jede DMG mit dem Sparkle-Schlüssel)..."
"$GEN_APPCAST" "$UPDATES_DIR" --download-url-prefix "$DOWNLOAD_URL_PREFIX"
echo "  ✓ $UPDATES_DIR/appcast.xml"

# ── 6. Nächste (manuelle) Schritte ─────────────────────────────────────────
echo ""
echo "=== Release $VERSION fertig ==="
echo "  DMG:     $DMG"
echo "  Appcast: $UPDATES_DIR/appcast.xml"
echo ""
echo "Noch von Hand (Publish — bewusst separat):"
echo "  1. release/updates/$DMG_NAME → Cloudflare R2 hochladen"
echo "     · Objekt-Key EXAKT = \"$DMG_NAME\" (muss zur Enclosure-URL passen)"
echo "     · Content-Type: application/octet-stream"
echo "  2. release/updates/appcast.xml → Website-Repo, Vercel public/appcast.xml"
echo "  3. Testen: Über-Dialog → „Auf Update prüfen\" bietet $VERSION an"
echo "  Details: brain/Appcast-Hosting.md"
