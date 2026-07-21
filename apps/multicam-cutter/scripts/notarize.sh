#!/bin/bash
set -euo pipefail

# ── MultiCamCutter Notarisierung ───────────────────────────────────────────
# Nimmt die bereits Developer-ID-signierte release/MultiCamCutter.app, baut eine
# DMG, reicht sie bei Apple ein (notarytool --wait), staplet den Ticket an DMG und
# App und verifiziert. Ergebnis: eine verteilbare, notarisierte DMG.
#
# Voraussetzungen (einmalig eingerichtet):
#   - App gebaut MIT Developer ID:
#       SIGN_IDENTITY="Developer ID Application: … (TEAMID)" bash scripts/build_app.sh
#   - notarytool-Profil im Schluesselbund (Standard: MulticamNotary), angelegt via
#       xcrun notarytool store-credentials "MulticamNotary" \
#         --apple-id "<apple-id>" --team-id "<TEAMID>"   (fragt das App-Passwort ab)
#
# Konfigurierbar per Env:
#   NOTARY_PROFILE   Schluesselbund-Profilname (Default: MulticamNotary)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/.."
APP="$APP_DIR/release/MultiCamCutter.app"
DMG="$APP_DIR/release/MultiCamCutter.dmg"
NOTARY_PROFILE="${NOTARY_PROFILE:-MulticamNotary}"

echo "=== MultiCamCutter Notarisierung ==="
echo "  Profil: $NOTARY_PROFILE"
echo ""

# 0. App vorhanden?
[ -d "$APP" ] || { echo "✗ App fehlt: $APP  (erst: SIGN_IDENTITY=… bash scripts/build_app.sh)"; exit 1; }

# 1. Sicherstellen, dass die App Developer-ID-signiert ist MIT Hardened Runtime.
#    Ad-hoc/ohne Runtime wird von Apple sofort abgelehnt — das fangen wir hier ab,
#    statt erst nach dem 1-GB-Upload ein "Invalid" zu kassieren.
SIGINFO="$(codesign -dv --verbose=4 "$APP" 2>&1 || true)"
if ! echo "$SIGINFO" | grep -q "Authority=Developer ID Application"; then
    echo "✗ App ist NICHT Developer-ID-signiert (Ad-hoc?). Neu bauen mit:"
    echo "    SIGN_IDENTITY=\"Developer ID Application: … (TEAMID)\" bash scripts/build_app.sh"
    echo "── codesign sagt ──"; echo "$SIGINFO" | grep -E "Authority|Signature|flags" | head
    exit 1
fi
if ! echo "$SIGINFO" | grep -q "flags=.*runtime"; then
    echo "✗ Hardened Runtime fehlt (flags ohne 'runtime'). Notarisierung würde scheitern."
    echo "$SIGINFO" | grep -E "flags" | head
    exit 1
fi
echo "► Signatur ok: Developer ID + Hardened Runtime"

# Identitaet notfalls SELBST bestimmen. release.sh reicht sie durch, aber
# notarize.sh wird auch direkt aufgerufen (etwa um nach einem Abbruch nur die
# Notarisierung zu wiederholen). Fehlte sie dann, baute make_dmg.sh ein
# UNSIGNIERTES DMG und warnte lediglich — Apple notarisiert das sogar, aber
# Gatekeeper lehnt es beim Oeffnen mit "no usable signature" ab. Der Fehler
# faellt also erst nach Upload, Notarisierung und Download auf.
# Beste Quelle ist die App selbst: so wird das DMG zwingend mit derselben
# Identitaet signiert wie ihr Inhalt.
if [ -z "${SIGN_IDENTITY:-}" ]; then
    SIGN_IDENTITY="$(echo "$SIGINFO" \
        | grep -m1 '^Authority=Developer ID Application' | sed 's/^Authority=//')"
    [ -n "$SIGN_IDENTITY" ] && echo "  Identität aus der App-Signatur: $SIGN_IDENTITY"
fi
if [ -z "$SIGN_IDENTITY" ]; then
    echo "✗ Keine Signatur-Identität ermittelbar — das DMG bliebe unsigniert und"
    echo "  Gatekeeper lehnte es trotz Notarisierung ab. Explizit setzen:"
    echo "    SIGN_IDENTITY=\"Developer ID Application: … (TEAMID)\" bash scripts/notarize.sh"
    exit 1
fi

# 2. DMG bauen (mit schlanker, notarisierter LIESMICH statt Gatekeeper-Umgehung).
echo "► DMG bauen..."
# SIGN_IDENTITY durchreichen, damit make_dmg.sh das DMG signieren kann.
NOTARIZED=1 SIGN_IDENTITY="$SIGN_IDENTITY" bash "$SCRIPT_DIR/make_dmg.sh"
[ -f "$DMG" ] || { echo "✗ DMG nicht erzeugt: $DMG"; exit 1; }

# 3. Einreichen und warten. Der Upload (~1 GB) + Apples Prüfung dauern typisch
#    ein paar Minuten. --wait blockiert bis zum Endstatus.
echo "► Bei Apple einreichen (notarytool submit --wait) — das dauert ein paar Minuten..."
SUBMIT_OUT="$(xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait 2>&1)" || true
echo "$SUBMIT_OUT"
SUB_ID="$(echo "$SUBMIT_OUT" | awk '/id:/{print $2; exit}')"

if ! echo "$SUBMIT_OUT" | grep -q "status: Accepted"; then
    echo ""
    echo "✗ Notarisierung NICHT akzeptiert."
    if [ -n "${SUB_ID:-}" ]; then
        echo "── Apple-Log (Detailgründe) ──"
        xcrun notarytool log "$SUB_ID" --keychain-profile "$NOTARY_PROFILE" || true
    fi
    exit 1
fi
echo "► Akzeptiert (Submission $SUB_ID)"

# 4. Ticket anheften — an die App (offline-tauglich, falls jemand nur die .app
#    weitergibt) UND an die DMG (der eigentliche Distributions-Artefakt).
echo "► Ticket stapeln..."
xcrun stapler staple "$APP"
xcrun stapler staple "$DMG"

# 5. Verifizieren: Ticket sitzt + Gatekeeper akzeptiert die App als "Notarized".
echo "► Verifizieren..."
xcrun stapler validate "$DMG"
if spctl -a -vvv "$APP" 2>&1 | grep -q "source=Notarized Developer ID"; then
    echo "  ✓ Gatekeeper: Notarized Developer ID"
else
    echo "  ⚠ spctl meldete nicht 'Notarized Developer ID' — bitte manuell prüfen:"
    spctl -a -vvv "$APP" 2>&1 | head -4
fi

DMG_SIZE=$(du -sh "$DMG" | cut -f1)
echo ""
echo "=== Notarisierung fertig ==="
echo "  DMG:    $DMG  ($DMG_SIZE)"
echo "  Verteilbar — Gatekeeper lässt die App ohne Umgehung starten."
