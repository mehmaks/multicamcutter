#!/bin/bash
# Baut die Dev-App /tmp/mcc_dev/MultiCamCutter.app aus dem aktuellen `swift build`
# (mit DE-Katalog, Icons, Sparkle, App-Icon) und startet sie.
# Nacktes `swift run` reicht nicht: ohne Bundle fehlen DE-Texte und Lucide-Icons.
#
#   bash apps/multicam-cutter/scripts/dev_app.sh                 # normal starten
#   MCC_DEMO_ERGEBNIS=/pfad/mit/aaf+xml bash …/dev_app.sh          # direkt auf die Ergebnis-Seite
set -e
cd "$(dirname "$0")/../MulticamCutter"
swift build >/dev/null
B=$(swift build --show-bin-path)
pkill -f mcc_dev/MultiCamCutter || true
rm -rf /tmp/mcc_dev
A=/tmp/mcc_dev/MultiCamCutter.app/Contents
mkdir -p $A/MacOS $A/Frameworks $A/Resources/Icons
cp "$B/MulticamCutter" $A/MacOS/
cp -R "$B/Sparkle.framework" $A/Frameworks/
cp -R "$B/Sparkle.framework" $A/MacOS/
cp -R "$B/MulticamCutter_MulticamCutter.bundle" $A/Resources/
cp Sources/Icons/*.svg $A/Resources/Icons/
cp ../scripts/AppIcon.icns $A/Resources/AppIcon.icns
for l in de en; do [ -d Localization/$l.lproj ] && mkdir -p $A/Resources/$l.lproj && cp Localization/$l.lproj/* $A/Resources/$l.lproj/; done
cat > $A/Info.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.jenaunited.multicam-cutter</string>
<key>CFBundleName</key><string>MultiCamCutter</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundleExecutable</key><string>MulticamCutter</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.1.0-dev</string>
<key>CFBundleVersion</key><string>1</string>
<key>CFBundleLocalizations</key><array><string>en</string><string>de</string></array>
<key>CFBundleDevelopmentRegion</key><string>en</string>
<key>NSPrincipalClass</key><string>NSApplication</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
</dict></plist>
EOF
install_name_tool -add_rpath @executable_path/../Frameworks $A/MacOS/MulticamCutter 2>/dev/null || true
codesign -f -s - --deep /tmp/mcc_dev/MultiCamCutter.app >/dev/null 2>&1
if [ -n "$MCC_DEMO_ERGEBNIS" ]; then
    open -n --env MCC_DEMO_ERGEBNIS="$MCC_DEMO_ERGEBNIS" /tmp/mcc_dev/MultiCamCutter.app
else
    open -n /tmp/mcc_dev/MultiCamCutter.app
fi
