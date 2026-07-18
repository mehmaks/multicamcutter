#!/bin/bash
set -euo pipefail

# ── MulticamCutter.app Bundle Builder ──────────────────────────────────────
# Baut die SwiftUI-App + Engine zu einem verteilbaren .app Bundle.
#
# Voraussetzungen:
#   - swift build (SwiftUI-App)
#   - PyInstaller-Bundle unter dist/multicam-engine/
#   - ffmpeg + ffprobe (Homebrew oder statisch)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/.."
TOOLKIT_ROOT="$APP_DIR/../.."
BUILD_DIR="$APP_DIR/release"
APP_BUNDLE="$BUILD_DIR/MultiCamCutter.app"

# ── Versionierung ──────────────────────────────────────────────────────────
# CFBundleShortVersionString: Marketing-Version — bewusst per Hand hochziehen.
MARKETING_VERSION="0.4.0"
# CFBundleVersion: Build-Nummer. MUSS monoton steigen (Sparkle vergleicht DIESE,
# nicht die Marketing-Version!) UND jeden Build unterscheidbar machen — sonst kann
# man Bug-Reports keinem Stand zuordnen. Ein UTC-Zeitstempel erfuellt beides ohne
# State-Datei und zeigt nebenbei, wann gebaut wurde.
BUILD_NUMBER="$(date -u +%Y%m%d%H%M)"
GIT_COMMIT="$(git -C "$TOOLKIT_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
git -C "$TOOLKIT_ROOT" diff --quiet HEAD 2>/dev/null || GIT_COMMIT="${GIT_COMMIT}-dirty"

echo "=== MulticamCutter.app Builder ==="
echo "  Version: $MARKETING_VERSION  Build: $BUILD_NUMBER  Commit: $GIT_COMMIT"
echo ""

# 1. SwiftUI-App bauen (Release)
echo "► Swift build (Release)..."
cd "$APP_DIR/MulticamCutter"
swift build -c release 2>&1 | tail -3
SWIFT_BIN_PATH="$(swift build -c release --show-bin-path)"
SWIFT_BINARY="$SWIFT_BIN_PATH/MulticamCutter"
SPARKLE_FW="$SWIFT_BIN_PATH/Sparkle.framework"
echo "  Binary: $SWIFT_BINARY"

# 2. Engine-Bundle prüfen
ENGINE_DIR="$APP_DIR/dist/multicam-engine"
if [ ! -f "$ENGINE_DIR/multicam-engine" ]; then
    echo "FEHLER: Engine-Bundle nicht gefunden unter $ENGINE_DIR"
    echo "Bitte zuerst: pyinstaller scripts/multicam_engine.spec"
    exit 1
fi
echo "► Engine-Bundle: $(du -sh "$ENGINE_DIR" | cut -f1)"

# 3. .app Bundle erstellen
echo "► Erstelle .app Bundle..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources/multicam-engine"

# Binary
cp "$SWIFT_BINARY" "$APP_BUNDLE/Contents/MacOS/MulticamCutter"

# Sparkle.framework einbetten (Auto-Update)
if [ -d "$SPARKLE_FW" ]; then
    echo "  Kopiere Sparkle.framework..."
    mkdir -p "$APP_BUNDLE/Contents/Frameworks"
    cp -R "$SPARKLE_FW" "$APP_BUNDLE/Contents/Frameworks/"
    # rpath: Binary wird via @rpath/Sparkle.framework/... gelinkt — Suchpfad
    # auf Contents/Frameworks setzen (der .build-@loader_path zeigt ins Leere)
    BIN="$APP_BUNDLE/Contents/MacOS/MulticamCutter"
    if ! otool -l "$BIN" | grep -q "@executable_path/../Frameworks"; then
        install_name_tool -add_rpath "@executable_path/../Frameworks" "$BIN"
    fi
else
    echo "  ⚠ Sparkle.framework nicht gefunden unter $SPARKLE_FW — Auto-Update fehlt"
fi

# Engine-Bundle
echo "  Kopiere Engine-Bundle..."
cp -R "$ENGINE_DIR"/* "$APP_BUNDLE/Contents/Resources/multicam-engine/"

# ffmpeg/ffprobe: statische arm64-Builds bevorzugt (self-contained, laufen auf
# Macs OHNE Homebrew). Quelle: https://www.osxexperts.net/ (ffmpeg81arm.zip +
# ffprobe81arm.zip). GPL-Build → Lizenz + Quell-Link in Acknowledgements nötig.
# Homebrew-Kopie ist nur Dev-Fallback (nicht verteilbar — /opt/homebrew-dylibs).
FFMPEG_STATIC="$APP_DIR/scripts/ffmpeg"
FFPROBE_STATIC="$APP_DIR/scripts/ffprobe"
if [ -f "$FFMPEG_STATIC" ] && [ -f "$FFPROBE_STATIC" ]; then
    echo "  Verwende statische ffmpeg/ffprobe"
    cp "$FFMPEG_STATIC" "$APP_BUNDLE/Contents/Resources/"
    cp "$FFPROBE_STATIC" "$APP_BUNDLE/Contents/Resources/"
else
    echo "  Kopiere Homebrew ffmpeg/ffprobe (nicht-statisch, nur für Dev)"
    cp "$(which ffmpeg)" "$APP_BUNDLE/Contents/Resources/ffmpeg" || echo "  ⚠ ffmpeg nicht gefunden"
    cp "$(which ffprobe)" "$APP_BUNDLE/Contents/Resources/ffprobe" || echo "  ⚠ ffprobe nicht gefunden"
fi

# App-Icon
ICON_SRC="$APP_DIR/scripts/AppIcon.icns"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
    echo "  App-Icon: AppIcon.icns"
else
    echo "  ⚠ AppIcon.icns fehlt (scripts/make_icon.py + iconutil)"
fi

# Open-Source-Lizenzen (Acknowledgements) sammeln + einbetten.
# PFLICHT wegen GPL-ffmpeg (Lizenztext + Quell-Link). Sammler liest die
# dist-info-LICENSE-Dateien des Frozen-Bundles + scripts/extra_licenses/.
echo "► Sammle Open-Source-Lizenzen..."
if python3 "$APP_DIR/scripts/collect_licenses.py"; then
    cp "$APP_DIR/scripts/acknowledgements.json" "$APP_BUNDLE/Contents/Resources/acknowledgements.json"
    echo "  acknowledgements.json eingebettet"
else
    echo "  ⚠ Lizenz-Sammler fehlgeschlagen — Acknowledgements-View bleibt leer"
fi

# Info.plist
cat > "$APP_BUNDLE/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>MultiCamCutter</string>
    <key>CFBundleDisplayName</key>
    <string>MultiCamCutter</string>
    <key>CFBundleIdentifier</key>
    <string>com.jenaunited.multicam-cutter</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundlePackagetype</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>MulticamCutter</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSSupportsAutomaticTermination</key>
    <true/>
    <key>NSSupportsSuddenTermination</key>
    <true/>
    <!-- Eigene Domain (multicamcutter.pantake.com) hostet Appcast + /api/*.
         Bei kuenftigem Domainwechsel: 301-Redirect von hier, damit bestehende
         Installs weiter Updates finden (Sparkle folgt der SUFeedURL). -->
    <key>SUFeedURL</key>
    <string>https://multicamcutter.pantake.com/appcast.xml</string>
    <key>SUPublicEDKey</key>
    <string>kcPVTCojTVp36MscXhRzKlgyNAa/fkekxnoVfsxfRDY=</string>
    <key>SUEnableAutomaticChecks</key>
    <false/>
</dict>
</plist>
PLIST

# Version in die Info.plist schreiben (das Heredoc oben ist bewusst nicht
# variablen-expandiert, damit der Plist-Text unangetastet bleibt).
PLIST="$APP_BUNDLE/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$MARKETING_VERSION" "$PLIST"
plutil -replace CFBundleVersion            -string "$BUILD_NUMBER"      "$PLIST"
plutil -replace GitCommit                  -string "$GIT_COMMIT"        "$PLIST" 2>/dev/null \
  || plutil -insert GitCommit -string "$GIT_COMMIT" "$PLIST"

# PkgInfo
echo -n "APPL????" > "$APP_BUNDLE/Contents/PkgInfo"

# 3b. Ad-hoc-Signierung (lokal). install_name_tool hat die Linker-ad-hoc-Sig
# des Binaries invalidiert — ohne Neu-Signierung startet die App auf arm64 nicht.
# Sparkle.framework behaelt seine eigene (gueltige) Signatur, daher KEIN --deep.
# Der finale Developer-ID-Sign + Notarization kommt im Distributions-Schritt.
echo "► Ad-hoc-Signierung..."
# Fehler NICHT verschlucken und NICHT weiterbauen: Eine unsignierte App startet auf
# anderen Macs nicht sauber — die wollen wir nicht klammheimlich ausliefern.
# (Ist schon passiert, als ein paralleler make_dmg.sh gleichzeitig am Bundle war.)
if ! codesign --force --sign - "$APP_BUNDLE"; then
    echo "  ✗ Signierung FEHLGESCHLAGEN — Build abgebrochen."
    echo "    Tipp: laeuft parallel ein make_dmg.sh/Build auf demselben Bundle?"
    exit 1
fi
# Gegenprobe: --force --sign kann durchlaufen und trotzdem kein Bundle-Signature
# hinterlassen (dann bleibt nur die linker-signed Mach-O-Sig, Info.plist=not bound).
if ! codesign --verify --strict "$APP_BUNDLE" 2>/dev/null; then
    echo "  ✗ Signatur ungueltig nach dem Signieren — Build abgebrochen."
    codesign -dv "$APP_BUNDLE" 2>&1 | head -4
    exit 1
fi
echo "  ok"

# 4. Ergebnis
APP_SIZE=$(du -sh "$APP_BUNDLE" | cut -f1)
echo ""
echo "=== Build fertig ==="
echo "  App: $APP_BUNDLE"
echo "  Größe: $APP_SIZE"
echo ""
echo "Starten mit:  open $APP_BUNDLE"
echo "DMG erstellen:  bash scripts/make_dmg.sh"
