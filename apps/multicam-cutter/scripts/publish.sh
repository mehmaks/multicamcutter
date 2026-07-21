#!/bin/bash
set -euo pipefail

# ── MultiCamCutter Publish („nach außen") ──────────────────────────────────
#   bash scripts/publish.sh 0.5.0
#
# Nimmt, was release.sh erzeugt hat, und bringt es online:
#   1. DMG   → Cloudflare R2 (rclone; wrangler nur bis 300 MiB, siehe unten)
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
#   R2_BUCKET     Name des R2-Buckets (Pflicht), z. B. multicamcutter-downloads
#   RCLONE_REMOTE rclone-Remote (Default: r2)
#   R2_ENDPOINT   nur für den aws-CLI-Pfad
#   WEB_REPO     Website-Repo (Default: ~/Developer/multicamcutter-web)
#   ASSUME_YES=1 überspringt die Rückfrage (für unbeaufsichtigte Läufe)

VERSION=""
SKIP_UPLOAD="${SKIP_UPLOAD:-0}"
for arg in "$@"; do
    case "$arg" in
        --skip-upload) SKIP_UPLOAD=1 ;;
        -*) echo "Unbekannte Option: $arg"; exit 1 ;;
        *)  VERSION="$arg" ;;
    esac
done
[ -n "$VERSION" ] || {
    echo "Usage: bash scripts/publish.sh <version> [--skip-upload]"
    echo "  --skip-upload  DMG wurde von Hand hochgeladen; nur pruefen + Appcast veroeffentlichen."
    exit 1
}

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
[ -n "${R2_BUCKET:-}" ] || [ "${SKIP_UPLOAD:-0}" = "1" ] || {
    echo "✗ R2_BUCKET nicht gesetzt."
    echo "  Bucket-Name findest du mit: npx wrangler r2 bucket list"
    echo "  Dann: R2_BUCKET=<name> bash scripts/publish.sh $VERSION"
    exit 1
}

# ── Uploader wählen ────────────────────────────────────────────────────────
# wrangler kann nur bis 300 MiB (harte Grenze, kein Multipart) — unsere DMGs
# liegen bei ~500 MiB. Deshalb wird rclone bevorzugt: spricht R2 über die
# S3-API und lädt automatisch in Teilen hoch. Erkannt wird VOR der Rückfrage,
# damit man nicht erst bestätigt und dann scheitert.
WRANGLER_LIMIT=$((300 * 1024 * 1024))
DMG_BYTES="$(stat -f%z "$DMG")"
if [ "$SKIP_UPLOAD" = "1" ]; then
    # Von Hand hochgeladen. Die Pruefung in Schritt 2 bleibt — sie ist hier sogar
    # WICHTIGER als beim automatischen Upload, weil beim manuellen Weg genau die
    # Fehler passieren, die sie abfaengt: falscher Objekt-Key, falscher
    # Content-Type, abgebrochener Transfer.
    UPLOADER="(von Hand)"
elif command -v rclone >/dev/null 2>&1; then
    UPLOADER="rclone"
elif command -v aws >/dev/null 2>&1 && [ -n "${R2_ENDPOINT:-}" ]; then
    UPLOADER="aws"
elif [ "$DMG_BYTES" -le "$WRANGLER_LIMIT" ]; then
    UPLOADER="wrangler"
else
    echo "✗ Kein geeignetes Upload-Werkzeug für $(echo "$DMG_BYTES" | awk '{printf "%.0f MiB", $1/1048576}')."
    echo ""
    echo "  wrangler kann nur bis 300 MiB (harte Grenze, kein Multipart)."
    echo "  Empfehlung — rclone, einmalig einrichten:"
    echo "    brew install rclone"
    echo "    rclone config    # n) new remote, Typ: s3, Provider: Cloudflare"
    echo "                     # Access Key + Secret aus Cloudflare → R2 → API-Token"
    echo "                     # Endpoint: https://<account-id>.r2.cloudflarestorage.com"
    echo "    Remote muss 'r2' heissen (oder RCLONE_REMOTE=<name> setzen)."
    echo ""
    echo "  ⚠️ Die R2-Zugangsdaten gehören in die rclone-Config, NICHT ins Repo."
    exit 1
fi

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

# ── Weitere Dateien, die der Feed BEWIRBT ──────────────────────────────────
# Sparkle laedt zuerst das Delta und faellt nur bei Fehler auf die volle DMG
# zurueck. Fehlt das Delta im Bucket, "funktioniert" das Update deshalb
# trotzdem -- es laedt bloss ein paar hundert MB statt ein paar hundert KB,
# ohne dass irgendwo ein Fehler auftaucht. Genau so lag es bis 0.5.2: der
# Feed bewarb drei Deltas, hochgeladen wurde nie eines.
#
# Grundregel: ALLES, was der Appcast referenziert, muss im Bucket liegen.
EXTRA_KEYS=()
while read -r key; do
    [ -n "$key" ] || continue
    [ "$key" = "$OBJECT_KEY" ] && continue          # Haupt-DMG laeuft separat
    [ -f "$UPDATES/$key" ] || continue              # nicht lokal -> nichts zu tun
    EXTRA_KEYS+=("$key")
done < <(grep -o 'url="[^"]*"' "$APPCAST" | sed 's/url="//;s/"//' | xargs -n1 basename | sort -u)

upload_object() {   # $1 = lokale Datei, $2 = Objekt-Key
    case "$UPLOADER" in
      rclone)
        rclone copyto "$1" "${RCLONE_REMOTE:-r2}:$R2_BUCKET/$2" \
            --header-upload "Content-Type: application/octet-stream" \
            --s3-no-check-bucket --s3-chunk-size 64M ;;
      aws)
        aws s3 cp "$1" "s3://$R2_BUCKET/$2" \
            --endpoint-url "$R2_ENDPOINT" --content-type "application/octet-stream" ;;
      wrangler)
        npx --yes wrangler r2 object put "$R2_BUCKET/$2" \
            --file="$1" --content-type="application/octet-stream" --remote ;;
    esac
}

# ── Vorschau + eine Rückfrage ──────────────────────────────────────────────
echo ""
echo "═══ Publish MultiCamCutter $VERSION ═══"
echo ""
if [ "$SKIP_UPLOAD" = "1" ]; then
    echo "  1. DMG → ÜBERSPRUNGEN (von Hand hochgeladen) — wird aber geprüft"
    echo "       Erwarteter Objekt-Key: $OBJECT_KEY"
    echo "       Erwartete Größe:       $ACTUAL_LEN Bytes"
else
    echo "  1. DMG → Cloudflare R2"
    echo "       Datei:        $DMG"
    echo "       Größe:        $(echo "$ACTUAL_LEN" | awk '{printf "%.0f MB (%d Bytes)", $1/1048576, $1}')"
    echo "       Bucket:       $R2_BUCKET"
    echo "       Objekt-Key:   $OBJECT_KEY"
    echo "       Content-Type: application/octet-stream"
    echo "       Werkzeug:     $UPLOADER"
fi
if [ "${#EXTRA_KEYS[@]}" -gt 0 ]; then
    echo ""
    echo "  1b. Weitere vom Feed beworbene Dateien (Deltas o.ae.):"
    for k in "${EXTRA_KEYS[@]}"; do
        echo "       · $k ($(stat -f%z "$UPDATES/$k" | awk '{printf "%.1f MB", $1/1048576}'))"
    done
fi
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
if [ "$SKIP_UPLOAD" = "1" ]; then
    echo "  übersprungen — DMG wurde von Hand hochgeladen"
else
echo "► Hochladen (~$(echo "$ACTUAL_LEN" | awk '{printf "%.0f", $1/1048576}') MB, dauert einen Moment)..."
case "$UPLOADER" in
  rclone)
    RCLONE_REMOTE="${RCLONE_REMOTE:-r2}"
    # --s3-no-check-bucket: rclone prueft sonst vorab, ob der Bucket existiert,
    # und versucht ihn anzulegen. Ein R2-Token mit "Object Read & Write" darf das
    # nicht -> 403 AccessDenied auf CreateBucket, obwohl der Bucket laengst da ist
    # und das Token alle noetigen Objektrechte hat.
    rclone copyto "$DMG" "$RCLONE_REMOTE:$R2_BUCKET/$OBJECT_KEY" \
        --header-upload "Content-Type: application/octet-stream" \
        --s3-no-check-bucket \
        --s3-chunk-size 64M --progress
    ;;
  aws)
    aws s3 cp "$DMG" "s3://$R2_BUCKET/$OBJECT_KEY" \
        --endpoint-url "$R2_ENDPOINT" --content-type "application/octet-stream"
    ;;
  wrangler)
    npx --yes wrangler r2 object put "$R2_BUCKET/$OBJECT_KEY" \
        --file="$DMG" --content-type="application/octet-stream" --remote
    ;;
esac

# Deltas und alles andere, was der Feed bewirbt.
for k in "${EXTRA_KEYS[@]}"; do
    echo "► $k"
    upload_object "$UPDATES/$k" "$k"
done
fi

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
    echo "  Zu prüfen: Objekt-Key EXAKT '$OBJECT_KEY' im Bucket,"
    echo "             Content-Type application/octet-stream, Transfer vollständig."
    exit 1
fi
echo "  ✓ abrufbar und vollständig"

# JEDE vom Feed beworbene URL pruefen, nicht nur die erste. Bis 0.5.2 pruefte
# dieser Schritt ausschliesslich die Haupt-DMG -- die drei beworbenen Deltas
# lagen gar nicht im Bucket, und weil Sparkle bei einem fehlenden Delta still
# auf die volle DMG zurueckfaellt, sah jedes Update trotzdem erfolgreich aus.
MISSING=0
while read -r u; do
    [ -n "$u" ] || continue
    [ "$u" = "$ENCLOSURE_URL" ] && continue
    code="$(curl -sSL -o /dev/null -w '%{http_code}' "$u" || true)"
    name="$(basename "$u")"
    if [ "$code" = "200" ]; then
        echo "  ✓ $name"
    else
        echo "  ✗ $name  → HTTP $code"
        MISSING=$((MISSING + 1))
    fi
done < <(grep -o 'url="[^"]*"' "$APPCAST" | sed 's/url="//;s/"//' | sort -u)
if [ "$MISSING" -gt 0 ]; then
    echo ""
    echo "✗ $MISSING vom Feed beworbene Datei(en) sind nicht abrufbar."
    echo "  Der Appcast wird NICHT veröffentlicht — er darf nichts bewerben,"
    echo "  was nicht existiert. Fehlen Deltas, laden alle Nutzer unnötig die"
    echo "  volle DMG; das faellt sonst nirgends auf."
    echo "  Liegen die Dateien lokal in release/updates/, genuegt ein erneuter Lauf."
    exit 1
fi

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
