#!/bin/bash
set -euo pipefail

# ── MultiCamCutter Publish („nach außen") ──────────────────────────────────
#   bash scripts/publish.sh 0.5.0
#
# Nimmt, was release.sh erzeugt hat, und bringt es online:
#   1. DMG   → Cloudflare R2 (npx wrangler, keine globale Installation nötig)
#   2. PRÜFEN, ob das DMG wirklich abrufbar und vollständig ist
#   3. appcast.xml → Website-Repo, committen, pushen (Vercel deployt beim Push)
#   4. PRÜFEN, ob der deployte Feed dem lokalen entspricht
#
# ⚠️ REIHENFOLGE IST SICHERHEITSRELEVANT: erst das DMG, dann der Feed. Ginge der
#    Appcast zuerst live, böte Sparkle allen Nutzern ein Update an, dessen Datei
#    noch nicht existiert — kaputte Installation statt keiner. Schlägt Schritt 2
#    fehl, bricht das Skript ab und der Feed bleibt unangetastet.
#
# Der Publish bleibt bewusst ein eigener, bestätigter Schritt (siehe
# brain/Distribution-Setup.md). Das Skript nimmt die Tipparbeit ab, nicht die
# Entscheidung: es zeigt zuerst vollständig, was es tun wird, und fragt einmal.
#
# Env:
#   R2_BUCKET    Name des R2-Buckets (Pflicht). Zu finden im Cloudflare-Dashboard
#                unter R2, oder via `npx wrangler r2 bucket list`.
#   WEB_REPO     Website-Repo (Default: ~/Developer/multicamcutter-web)
#   ASSUME_YES=1 überspringt die Rückfrage (für unbeaufsichtigte Läufe)

VERSION="${1:-}"
[ -n "$VERSION" ] || { echo "Usage: bash scripts/publish.sh <version>   z.B. 0.5.0"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/.."
UPDATES="$APP_DIR/release/updates"
DMG="$UPDATES/MultiCamCutter-$VERSION.dmg"
APPCAST="$UPDATES/appcast.xml"
WEB_REPO="${WEB_REPO:-$HOME/Developer/multicamcutter-web}"

# ── Vorbedingungen ─────────────────────────────────────────────────────────
[ -f "$DMG" ]     || { echo "✗ DMG fehlt: $DMG"; echo "  Erst: bash scripts/release.sh $VERSION"; exit 1; }
[ -f "$APPCAST" ] || { echo "✗ appcast.xml fehlt: $APPCAST"; exit 1; }
[ -d "$WEB_REPO/.git" ] || { echo "✗ Website-Repo nicht gefunden: $WEB_REPO"; echo "  Mit WEB_REPO=… überschreiben."; exit 1; }
[ -n "${R2_BUCKET:-}" ] || {
    echo "✗ R2_BUCKET nicht gesetzt."
    echo "  Bucket-Name findest du mit: npx wrangler r2 bucket list"
    echo "  Dann: R2_BUCKET=<name> bash scripts/publish.sh $VERSION"
    exit 1
}

# Erwartete Werte AUS DEM SIGNIERTEN FEED lesen — nicht selbst berechnen. Der
# Feed ist die Wahrheit: Sparkle prüft gegen genau diese Länge und Signatur.
ENCLOSURE_URL="$(grep -o 'url="[^"]*"' "$APPCAST" | head -1 | sed 's/url="//;s/"//')"
EXPECTED_LEN="$(grep -o 'length="[0-9]*"' "$APPCAST" | head -1 | sed 's/length="//;s/"//')"
OBJECT_KEY="$(basename "$ENCLOSURE_URL")"
ACTUAL_LEN="$(stat -f%z "$DMG")"
FEED_VERSION="$(grep -o '<sparkle:shortVersionString>[^<]*' "$APPCAST" | head -1 | sed 's/.*>//')"

if [ "$ACTUAL_LEN" != "$EXPECTED_LEN" ]; then
    echo "✗ Größe der DMG passt nicht zum Feed:"
    echo "    Datei: $ACTUAL_LEN Bytes"
    echo "    Feed:  $EXPECTED_LEN Bytes"
    echo "  Der Feed wurde für eine andere Datei signiert — release.sh erneut laufen lassen."
    exit 1
fi
if [ "$FEED_VERSION" != "$VERSION" ]; then
    echo "✗ Feed enthält Version $FEED_VERSION, du veröffentlichst $VERSION."
    exit 1
fi
if [ "$OBJECT_KEY" != "MultiCamCutter-$VERSION.dmg" ]; then
    echo "✗ Enclosure-Dateiname '$OBJECT_KEY' passt nicht zu Version $VERSION."
    exit 1
fi

# ── Vorschau + eine Rückfrage ──────────────────────────────────────────────
echo ""
echo "═══ Publish MultiCamCutter $VERSION ═══"
echo ""
echo "  1. DMG → Cloudflare R2"
echo "       Datei:       $DMG"
echo "       Größe:       $(echo "$ACTUAL_LEN" | awk '{printf "%.0f MB (%d Bytes)", $1/1048576, $1}')"
echo "       Bucket:      $R2_BUCKET"
echo "       Objekt-Key:  $OBJECT_KEY"
echo "       Content-Type: application/octet-stream"
echo ""
echo "  2. appcast.xml → $WEB_REPO/public/appcast.xml"
echo "       committen + pushen (Vercel deployt beim Push)"
echo ""
echo "  3. Verifizieren: $ENCLOSURE_URL"
echo ""
echo "  Danach ist das Update für ALLE bestehenden Installationen sichtbar."
echo ""
if [ "${ASSUME_YES:-0}" != "1" ]; then
    read -r -p "Veröffentlichen? [j/N] " ans
    case "$ans" in [jJyY]*) ;; *) echo "Abgebrochen — nichts verändert."; exit 0;; esac
fi

# ── 1. DMG hochladen ───────────────────────────────────────────────────────
echo ""
echo "───── [1/4] DMG → R2 ─────"
echo "► Hochladen (~$(echo "$ACTUAL_LEN" | awk '{printf "%.0f", $1/1048576}') MB, dauert einen Moment)..."
npx --yes wrangler r2 object put "$R2_BUCKET/$OBJECT_KEY" \
    --file="$DMG" --content-type="application/octet-stream" --remote

# ── 2. Upload prüfen — BEVOR der Feed live geht ────────────────────────────
echo ""
echo "───── [2/4] Upload prüfen ─────"
echo "► HEAD $ENCLOSURE_URL"
HEAD_OUT="$(curl -sSL -o /dev/null -D - "$ENCLOSURE_URL" 2>&1 || true)"
GOT_CODE="$(echo "$HEAD_OUT" | grep -E "^HTTP/" | tail -1 | awk '{print $2}')"
GOT_LEN="$(echo "$HEAD_OUT"  | grep -i "^content-length:" | tail -1 | tr -d '\r' | awk '{print $2}')"
GOT_TYPE="$(echo "$HEAD_OUT" | grep -i "^content-type:"   | tail -1 | tr -d '\r' | awk '{print $2}')"
echo "    Status:       ${GOT_CODE:-?}"
echo "    Content-Length: ${GOT_LEN:-?}  (erwartet $EXPECTED_LEN)"
echo "    Content-Type:   ${GOT_TYPE:-?}"
if [ "${GOT_CODE:-}" != "200" ] || [ "${GOT_LEN:-}" != "$EXPECTED_LEN" ]; then
    echo ""
    echo "✗ DMG ist nicht korrekt abrufbar — der Appcast wird NICHT veröffentlicht."
    echo "  Damit bleibt der Feed konsistent: kein Nutzer bekommt ein Update"
    echo "  angeboten, dessen Datei fehlt oder unvollständig ist."
    [ "${GOT_LEN:-}" != "$EXPECTED_LEN" ] && echo "  Häufigste Ursache: Upload abgebrochen (wrangler hat ein Größenlimit)."
    exit 1
fi
echo "  ✓ abrufbar und vollständig"

# ── 3. Appcast veröffentlichen ─────────────────────────────────────────────
echo ""
echo "───── [3/4] Appcast → Website ─────"
cp "$APPCAST" "$WEB_REPO/public/appcast.xml"
if git -C "$WEB_REPO" diff --quiet -- public/appcast.xml; then
    echo "  appcast.xml unverändert — nichts zu committen"
else
    git -C "$WEB_REPO" add public/appcast.xml
    git -C "$WEB_REPO" commit -q -m "Appcast: MultiCamCutter $VERSION"
    git -C "$WEB_REPO" push -q
    echo "  ✓ committet und gepusht — Vercel deployt jetzt"
fi

# ── 4. Deployten Feed prüfen ───────────────────────────────────────────────
echo ""
echo "───── [4/4] Feed prüfen ─────"
FEED_URL="https://multicamcutter.pantake.com/appcast.xml"
echo "► Warte auf Deploy (bis zu 90 s)..."
for i in $(seq 1 18); do
    LIVE="$(curl -sS "$FEED_URL" 2>/dev/null || true)"
    if echo "$LIVE" | grep -q "MultiCamCutter-$VERSION.dmg"; then
        echo "  ✓ Feed liefert $VERSION"
        break
    fi
    [ "$i" = "18" ] && {
        echo "  ⚠ Feed zeigt nach 90 s noch nicht $VERSION."
        echo "    Das DMG liegt bereits korrekt — nur der Deploy fehlt noch."
        echo "    Prüfen: $FEED_URL"
        exit 1
    }
    sleep 5
done

echo ""
echo "=== $VERSION ist live ==="
echo "  DMG:   $ENCLOSURE_URL"
echo "  Feed:  $FEED_URL"
echo ""
echo "Letzter Schritt von Hand (nicht automatisierbar):"
echo "  Aus einer ÄLTEREN Installation heraus: Über MultiCamCutter →"
echo "  „Auf Update prüfen\" muss $VERSION anbieten, laden und installieren."
