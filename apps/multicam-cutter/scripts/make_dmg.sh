#!/bin/bash
set -euo pipefail

# ── MultiCamCutter DMG Builder ─────────────────────────────────────────────
# Packt release/MultiCamCutter.app in eine verteilbare .dmg mit
# Applications-Verknüpfung + Erste-Start-Anleitung.
#
# Env NOTARIZED=1  → schlanke Anleitung ohne Gatekeeper-Umgehung (die App ist
#                    Developer-ID-signiert; notarize.sh notarisiert die DMG danach).
# sonst            → Ad-hoc/Test-DMG: LIESMICH erklärt, wie man die
#                    Gatekeeper-Warnung beim ersten Start umgeht.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/.."
APP="$APP_DIR/release/MultiCamCutter.app"
STAGING="$APP_DIR/release/dmg-staging"
DMG="$APP_DIR/release/MultiCamCutter.dmg"
VOL="MultiCamCutter"

[ -d "$APP" ] || { echo "FEHLER: App nicht gefunden: $APP (erst build_app.sh)"; exit 1; }

echo "► Staging vorbereiten..."
rm -rf "$STAGING" "$DMG"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Programme"

# Erste-Start-Anleitung — Text hängt davon ab, ob die App notarisiert wird.
if [ "${NOTARIZED:-0}" = "1" ]; then
# Notarisiert: KEINE Textdatei. Das gestaltete Fenster erklaert den Vorgang
# bereits (ziehen -> auswerfen -> oeffnen) und nennt die Kontaktadresse. Eine
# zusaetzliche Datei wuerde an beliebiger Stelle im Layout landen und die
# Komposition stoeren. Beim ERSTEN Start gibt es dank Notarisierung ohnehin
# nur den normalen "aus dem Internet geladen"-Hinweis.
:
else
cat > "$STAGING/⚠️ ERSTER START — bitte lesen.txt" << 'EOF'
MultiCamCutter — so startest du die App zum ersten Mal
========================================================

╔════════════════════════════════════════════════════════════════════╗
║  WICHTIG: Die App NICHT direkt aus diesem Fenster starten!           ║
║  Zieh sie ZUERST nach "Programme" und starte sie von DORT.           ║
║  (Startest du sie aus der DMG und wirfst die DMG aus, stürzt sie ab.) ║
╚════════════════════════════════════════════════════════════════════╝

1) Zieh "MultiCamCutter" links in den Ordner "Programme".

2) Wirf dieses DMG-Volume aus (⏏ im Finder, oder auf den Schreibtisch-
   Datenträger rechtsklicken → "Auswerfen").

3) Öffne "MultiCamCutter" jetzt aus dem Ordner "Programme".

   Diese Testversion ist noch NICHT bei Apple notarisiert. Beim ersten Start
   zeigt macOS deshalb eine Sicherheitswarnung ("nicht verifizierter
   Entwickler"). Das ist normal — so startest du trotzdem:

   ▸ Zuverlässigster Weg (Terminal öffnen, Zeile einfügen, Enter):

       xattr -dr com.apple.quarantine "/Applications/MultiCamCutter.app"

     Danach die App ganz normal per Doppelklick öffnen.

   ▸ Ohne Terminal:
       • macOS 14 (Sonoma): Rechtsklick auf die App → "Öffnen" → "Öffnen".
       • macOS 15 (Sequoia): einmal doppelklicken (wird blockiert), dann
         Systemeinstellungen → Datenschutz & Sicherheit → ganz unten
         "Trotzdem öffnen".

   Wichtig: Der Terminal-Weg ist am sichersten, weil die App intern
   Hilfsprogramme startet (Analyse-Engine, ffmpeg). Er gibt das komplette
   Programmpaket frei.

Die App arbeitet komplett lokal auf deinem Mac — nichts wird hochgeladen.

Fragen / Feedback: max@pantake.com
EOF
fi

# ── Gestaltetes DMG ────────────────────────────────────────────────────────
# Ablauf: beschreibbar (UDRW) erzeugen -> mounten -> Hintergrund + Fenster- und
# Icon-Positionen via Finder setzen -> auswerfen -> komprimiert (UDZO) umwandeln.
# Direkt UDZO zu erzeugen ginge schneller, laesst aber keine Gestaltung zu:
# ein schreibgeschuetztes Volume nimmt keine .DS_Store mit den Ansichtsoptionen an.
BG_DIR="$STAGING/.background"
mkdir -p "$BG_DIR"
# Eigene Grafik hat Vorrang: liegt scripts/dmg-background.(tiff|png) vor, wird
# sie genommen; sonst erzeugt make_dmg_background.py eine generische.
BG_FILE=""
for cand in dmg-background.tiff dmg-background.png; do
    if [ -f "$SCRIPT_DIR/$cand" ]; then
        cp "$SCRIPT_DIR/$cand" "$BG_DIR/$cand"; BG_FILE="$cand"; break
    fi
done
PYBIN="${PYBIN:-$APP_DIR/../../venv/bin/python3}"
[ -x "$PYBIN" ] || PYBIN="python3"
if [ -n "$BG_FILE" ]; then
    echo "► Hintergrundgrafik: eigene ($BG_FILE)"
else
    echo "► Hintergrundgrafik erzeugen (generisch)..."
    "$PYBIN" "$SCRIPT_DIR/make_dmg_background.py" "$BG_DIR/background.png"
    BG_FILE="background.png"
fi

RW_DMG="$APP_DIR/release/.rw.dmg"
rm -f "$RW_DMG"
# Grosszuegig dimensionieren: hdiutil kann ein UDRW-Image nicht nachtraeglich
# vergroessern, und zu knapp bemessen scheitert das Kopieren mitten im Vorgang.
# Reserve grosszuegig: ein App-Bundle besteht aus tausenden kleinen Dateien,
# der Blockverschnitt in HFS+ ist entsprechend hoch. 120 MB Aufschlag reichten
# nicht ("hdiutil: create failed - kein Platz verfuegbar"), obwohl 400 GB frei
# waren — die Meldung bezieht sich auf das IMAGE, nicht auf die Platte.
STAGING_MB=$(du -sm "$STAGING" | cut -f1)
SIZE_MB=$(( STAGING_MB + STAGING_MB / 4 + 200 ))
echo "► Beschreibbares Image anlegen (${SIZE_MB} MB)..."
hdiutil create -srcfolder "$STAGING" -volname "$VOL" -fs HFS+ \
    -format UDRW -size "${SIZE_MB}m" "$RW_DMG" >/dev/null

echo "► Fenster gestalten..."
MOUNT_DIR="/Volumes/$VOL"
hdiutil attach "$RW_DMG" -readwrite -noverify -noautoopen >/dev/null
sleep 2

# Fenstergroesse 640x400 Punkte — muss zur Grafik aus make_dmg_background.py
# passen. Finder skaliert den Hintergrund NICHT, er verankert ihn oben links;
# bei abweichender Groesse verrutscht das Layout.
osascript <<APPLESCRIPT || echo "  ⚠ Finder-Gestaltung fehlgeschlagen — DMG bleibt funktionsfähig, nur ungestaltet"
tell application "Finder"
    tell disk "$VOL"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        -- Hoehe enthaelt die Titelleiste: 440 statt 400, damit die
        -- INHALTSflaeche rund 400 Punkte hoch wird und die 640x400-Grafik passt.
        set the bounds of container window to {200, 120, 840, 560}
        set opts to the icon view options of container window
        set arrangement of opts to not arranged
        set icon size of opts to 128
        set text size of opts to 12
        -- POSIX-Pfad statt Doppelpunkt-Notation: letztere scheitert bei einem
        -- versteckten Ordner mit Fehler -10006 ("kann nicht gesetzt werden").
        -- Hintergrund: Finder legt das Bild in PIXELN = PUNKTEN an und verankert
        -- es oben links. Es wird NICHT skaliert. Die Datei muss daher 640x400
        -- sein (bzw. eine TIFF mit 640x400 + 1280x800 fuer Retina, erzeugt via
        -- "tiffutil -cathidpicheck bg.png bg@2x.png -out background.tiff").
        set background picture of opts to POSIX file "$MOUNT_DIR/.background/$BG_FILE"
        set position of item "MultiCamCutter.app" of container window to {170, 186}
        set position of item "Programme" of container window to {470, 186}
        update without registering applications
        delay 1
        -- Fenster schliessen, sonst haelt der Finder das Volume offen und
        -- hdiutil convert scheitert mit "Ressource zeitweilig nicht verfuegbar".
        close
    end tell
end tell
APPLESCRIPT

sync
sleep 2
# Robust auswerfen: der Finder gibt das Volume nicht immer sofort frei.
for attempt in 1 2 3 4 5; do
    hdiutil detach "$MOUNT_DIR" >/dev/null 2>&1 && break
    [ "$attempt" = "5" ] && hdiutil detach "$MOUNT_DIR" -force >/dev/null 2>&1
    sleep 2
done
# Wirklich weg? Sonst produziert convert ein unbrauchbares Image.
for attempt in 1 2 3 4 5; do
    [ ! -d "$MOUNT_DIR" ] && break
    sleep 2
done
[ -d "$MOUNT_DIR" ] && { echo "✗ Volume $MOUNT_DIR laesst sich nicht auswerfen"; exit 1; }

echo "► DMG komprimieren (dauert bei ~1 GB einen Moment)..."
rm -f "$DMG"
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG" >/dev/null
rm -f "$RW_DMG"
rm -rf "$STAGING"

# DMG signieren. Ohne Signatur meldet Gatekeeper beim Oeffnen
# "rejected — source=no usable signature", auch wenn die Notarisierung
# akzeptiert und das Ticket angeheftet wurde. Muss VOR der Einreichung
# passieren, damit die Notarisierung das signierte DMG abdeckt.
if [ -n "${SIGN_IDENTITY:-}" ]; then
    echo "► DMG signieren..."
    codesign --force --sign "$SIGN_IDENTITY" --timestamp "$DMG"
    codesign --verify --verbose=2 "$DMG" 2>&1 | sed 's/^/    /'
else
    echo "  ⚠ SIGN_IDENTITY nicht gesetzt — DMG bleibt unsigniert"
    echo "    Gatekeeper wird es mit 'no usable signature' ablehnen."
fi
DMG_SIZE=$(du -sh "$DMG" | cut -f1)
echo ""
echo "=== DMG fertig ==="
echo "  Datei:  $DMG"
echo "  Größe:  $DMG_SIZE"
