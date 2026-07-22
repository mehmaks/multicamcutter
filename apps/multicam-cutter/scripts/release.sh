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
SIGN_IDENTITY="$SIGN_IDENTITY" bash "$SCRIPT_DIR/notarize.sh"

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

PYBIN="${PYBIN:-$APP_DIR/../../venv/bin/python3}"
[ -x "$PYBIN" ] || PYBIN="python3"

echo "► generate_appcast (signiert jede DMG mit dem Sparkle-Schlüssel)..."
# --maximum-versions begrenzt den Feed auf die 5 neuesten Eintraege. Der Appcast
# bestimmt, was im Bucket liegen MUSS: alles, was er bewirbt, muss abrufbar sein,
# sonst laeuft ein Update ins 404. Umgekehrt darf geloescht werden, was aus dem
# Feed herausgefallen ist — ohne diese Grenze waechst der Bucket unbegrenzt und
# nichts ist je gefahrlos entfernbar.
#
# BEWUSST OHNE --auto-prune-update-files: das loescht die alten DMGs auch LOKAL,
# und generate_appcast braucht sie, um kuenftige Deltas dagegen zu rechnen.
# Lokal bleibt also alles liegen; aufgeraeumt wird nur im Bucket, von Hand.
# OHNE --embed-release-notes: das kann nur EINE, einsprachige <description>.
# Die zweisprachige Einbettung macht embed_release_notes.py danach.
"$GEN_APPCAST" "$UPDATES_DIR" \
    --download-url-prefix "$DOWNLOAD_URL_PREFIX" \
    --maximum-versions 5
echo "  ✓ $UPDATES_DIR/appcast.xml"

# Changelog zweisprachig ins <item> einbetten: <description xml:lang="de"> (Pflicht)
# und, falls CHANGELOG.en.md den Abschnitt hat, xml:lang="en". Die Website waehlt
# per Locale mit Fallback auf DE (Contract, brain/Appcast-Hosting.md → GEKLÄRT).
# Exit 2 = deutscher Abschnitt fehlt → Release abbrechen. Kein Release ohne Notizen.
echo "► Changelog → Release-Notes ($VERSION, de + optional en)..."
"$PYBIN" "$SCRIPT_DIR/embed_release_notes.py" "$VERSION" "$UPDATES_DIR/appcast.xml"
_notes_rc=$?
if [ "$_notes_rc" = "2" ]; then
    echo "✗ Kein deutscher Changelog-Abschnitt für $VERSION in CHANGELOG.md — abgebrochen."
    echo "  Bitte '## $VERSION' ergänzen (englisch optional in CHANGELOG.en.md)."
    exit 1
elif [ "$_notes_rc" != "0" ]; then
    echo "✗ Release-Notes konnten nicht eingebettet werden (Code $_notes_rc)."
    exit 1
fi

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
