#!/bin/bash
set -euo pipefail

# ── MultiCamCutter DMG Builder ─────────────────────────────────────────────
# Packt release/MultiCamCutter.app in eine verteilbare .dmg mit
# Applications-Verknüpfung + Erste-Start-Anleitung.
# HINWEIS: Diese DMG ist ad-hoc signiert, NICHT notarisiert — Tester müssen
# beim ersten Start die Gatekeeper-Warnung umgehen (siehe LIESMICH in der DMG).

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

# Erste-Start-Anleitung
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

echo "► DMG erstellen (komprimieren, dauert bei ~1 GB einen Moment)..."
hdiutil create -volname "$VOL" -srcfolder "$STAGING" -ov -format UDZO "$DMG"

rm -rf "$STAGING"
DMG_SIZE=$(du -sh "$DMG" | cut -f1)
echo ""
echo "=== DMG fertig ==="
echo "  Datei:  $DMG"
echo "  Größe:  $DMG_SIZE"
