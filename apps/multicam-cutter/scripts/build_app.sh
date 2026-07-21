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
# Per Env überschreibbar (release.sh reicht die Release-Version so durch).
MARKETING_VERSION="${MARKETING_VERSION:-0.4.0}"
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

# ── Veraltete Engine erkennen ──────────────────────────────────────────────
# build_app.sh friert die Engine NICHT selbst ein, es kopiert nur
# dist/multicam-engine ins Bundle. Ohne diese Pruefung landet stillschweigend
# ein alter Stand im Release: am 21.07. ging 0.5.0 mit einer Engine vom 19.07.
# raus -- ohne den Pause-Trim-Fix, die AAF-Clipnamen und den FP-Filter. Der
# Build meldete dabei Erfolg.
if [ -f "$ENGINE_DIR/multicam-engine" ]; then
    STALE="$(find "$TOOLKIT_ROOT/modules" "$TOOLKIT_ROOT/shared" \
                  "$TOOLKIT_ROOT/licensing" "$APP_DIR/engine" \
                  -name '*.py' -newer "$ENGINE_DIR/multicam-engine" 2>/dev/null \
             | grep -v '/dist/\|/release/' || true)"
    if [ -n "$STALE" ]; then
        echo "✗ Die eingefrorene Engine ist AELTER als der Quellcode."
        echo "  Neuer als dist/multicam-engine/multicam-engine:"
        echo "$STALE" | sed "s|$TOOLKIT_ROOT/||; s|^|      |"
        echo ""
        echo "  Diese Aenderungen waeren NICHT im Release. Erst neu einfrieren:"
        echo "      cd $APP_DIR && pyinstaller scripts/multicam_engine.spec"
        echo ""
        echo "  (Bewusst kein Auto-Rebuild: der Lauf dauert mehrere Minuten und"
        echo "   soll eine Entscheidung bleiben. SKIP_ENGINE_CHECK=1 uebergeht die"
        echo "   Pruefung.)"
        [ "${SKIP_ENGINE_CHECK:-0}" = "1" ] || exit 1
        echo "  ⚠ SKIP_ENGINE_CHECK=1 — Pruefung uebersprungen."
    fi
fi

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
    <key>CFBundlePackageType</key>
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
    <!-- Standardwert fuer die automatische Pruefung. Sobald der Nutzer den
         Schalter in den Einstellungen umlegt, gewinnt SEINE Wahl (Sparkle legt
         sie in den UserDefaults ab); dieser Wert greift also nur bei
         Neuinstallationen und bei allen, die nie etwas umgestellt haben.
         `true` unterdrueckt zugleich Sparkles Rueckfrage beim ersten Start. -->
    <key>SUEnableAutomaticChecks</key>
    <true/>
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

# 3b. Signierung. install_name_tool hat die Linker-ad-hoc-Sig des Binaries
# invalidiert — ohne Neu-Signierung startet die App auf arm64 nicht.
#
# Zwei Modi (per Env SIGN_IDENTITY):
#   - unset / "-"  → Ad-hoc (Dev-Build, laeuft nur lokal, KEINE Notarisierung)
#   - "Developer ID Application: …"  → Distributions-Sign mit Hardened Runtime +
#     Entitlements, inside-out. Danach kann scripts/notarize.sh die DMG notarisieren.
SIGN_IDENTITY="${SIGN_IDENTITY:--}"
ENTITLEMENTS="$APP_DIR/scripts/MulticamCutter.entitlements"
ENGINE_ROOT="$APP_BUNDLE/Contents/Resources/multicam-engine"

if [ "$SIGN_IDENTITY" = "-" ]; then
    echo "► Ad-hoc-Signierung (Dev, nicht verteilbar)..."
    # Sparkle.framework behaelt seine eigene (gueltige) Signatur, daher KEIN --deep.
    # Fehler NICHT verschlucken: eine kaputt signierte App startet nicht sauber.
    # (Ist schon passiert, als ein paralleler make_dmg.sh am selben Bundle war.)
    if ! codesign --force --sign - "$APP_BUNDLE"; then
        echo "  ✗ Signierung FEHLGESCHLAGEN — Build abgebrochen."
        echo "    Tipp: laeuft parallel ein make_dmg.sh/Build auf demselben Bundle?"
        exit 1
    fi
else
    echo "► Developer-ID-Signierung (Hardened Runtime): $SIGN_IDENTITY"
    [ -f "$ENTITLEMENTS" ] || { echo "  ✗ Entitlements fehlen: $ENTITLEMENTS"; exit 1; }
    RUNTIME_OPTS=(--options runtime --timestamp)

    # Inside-out: erst alle eingebetteten Mach-O, dann Container, zuletzt die App.
    # Reihenfolge ist zwingend — signiert man die App zuerst, invalidiert jedes
    # spaetere Innen-Signieren die aeussere Signatur wieder.

    # 1) Alle Mach-O im Engine-Bundle (torch/numpy/… ~650 .dylib/.so, teils ohne
    #    Extension). Libraries sind keine Prozesse → KEINE Entitlements. Liste
    #    einmal einsammeln (file je Datei), dann parallel signieren.
    echo "  · Engine-Libraries einsammeln + signieren..."
    MACHO_LIST="$(mktemp)"
    find "$ENGINE_ROOT" -type f ! -path "$ENGINE_ROOT/multicam-engine" -print0 \
      | while IFS= read -r -d '' f; do
            file -b "$f" 2>/dev/null | grep -q "Mach-O" && printf '%s\0' "$f"
        done > "$MACHO_LIST"
    echo "    $(tr -cd '\0' < "$MACHO_LIST" | wc -c | tr -d ' ') Mach-O-Dateien"
    xargs -0 -P4 -n15 codesign --force "${RUNTIME_OPTS[@]}" --sign "$SIGN_IDENTITY" < "$MACHO_LIST"
    rm -f "$MACHO_LIST"

    # 2) Engine-Executable (eigener Prozess → MIT Entitlements)
    echo "  · Engine-Executable..."
    codesign --force "${RUNTIME_OPTS[@]}" --entitlements "$ENTITLEMENTS" \
        --sign "$SIGN_IDENTITY" "$ENGINE_ROOT/multicam-engine"

    # 3) ffmpeg/ffprobe (eigenstaendige Executables, keine Sonder-Entitlements)
    echo "  · ffmpeg/ffprobe..."
    codesign --force "${RUNTIME_OPTS[@]}" --sign "$SIGN_IDENTITY" \
        "$APP_BUNDLE/Contents/Resources/ffmpeg" "$APP_BUNDLE/Contents/Resources/ffprobe"

    # 4) Sparkle.framework inside-out: XPC-Services + Autoupdate, dann Updater.app,
    #    dann das Framework selbst. (Nicht sandboxed → keine Sonder-Entitlements.)
    SP="$APP_BUNDLE/Contents/Frameworks/Sparkle.framework"
    if [ -d "$SP" ]; then
        echo "  · Sparkle.framework..."
        codesign --force "${RUNTIME_OPTS[@]}" --sign "$SIGN_IDENTITY" \
            "$SP/Versions/B/XPCServices/Downloader.xpc" \
            "$SP/Versions/B/XPCServices/Installer.xpc" \
            "$SP/Versions/B/Autoupdate"
        codesign --force "${RUNTIME_OPTS[@]}" --sign "$SIGN_IDENTITY" "$SP/Versions/B/Updater.app"
        codesign --force "${RUNTIME_OPTS[@]}" --sign "$SIGN_IDENTITY" "$SP"
    fi

    # 5) Zuletzt die App selbst (Hauptprozess → MIT Entitlements). KEIN --deep,
    #    damit die eingebetteten Signaturen von oben erhalten bleiben.
    echo "  · App-Bundle..."
    codesign --force "${RUNTIME_OPTS[@]}" --entitlements "$ENTITLEMENTS" \
        --sign "$SIGN_IDENTITY" "$APP_BUNDLE"
fi

# Gegenprobe (beide Modi): --force --sign kann durchlaufen und trotzdem kein
# gueltiges Bundle-Signature hinterlassen. --deep --strict prueft auch die
# eingebetteten Signaturen mit.
if ! codesign --verify --deep --strict "$APP_BUNDLE" 2>/dev/null; then
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
if [ "$SIGN_IDENTITY" = "-" ]; then
    echo "DMG (Dev):   bash scripts/make_dmg.sh"
    echo "Verteilen:   SIGN_IDENTITY=\"Developer ID Application: …\" bash scripts/build_app.sh && bash scripts/notarize.sh"
else
    echo "Notarisieren + DMG:  bash scripts/notarize.sh"
fi
