# Architektur

## Zwei Schichten

1. **SwiftUI-App** (`MulticamCutter/Sources/`): Nativer Mac-Client
2. **multicam-engine** (`engine/`): Python-CLI als Subprocess

Swift startet den Engine-Prozess, liest JSON-Lines von stdout, steuert UI.
Engine kennt kein SwiftUI — kommuniziert ausschliesslich ueber stdout.

## Dateien

| Datei | Rolle |
|-------|-------|
| `MulticamCutterApp.swift` | App-Entry, Window, Menue, Activation Policy |
| `ContentView.swift` | Alle Views (Sidebar, Setup, Progress, Result, Error) |
| `EngineController.swift` | State-Machine, Subprocess-Management, Presets, Session |
| `ScrubbableThumbnail.swift` | AVAssetImageGenerator-basiertes Hover-Scrubbing |
| `Theme.swift` | Marken-Akzent `Color.brandAccent` (Lime #C6F24E) |
| `ParamHelp.swift` | Parameter-Hilfetexte (aus Web-Schema) + (?)-Badge/Toggle/Label |
| `Updater.swift` | Sparkle-Wrapper, Über-Dialog, „Auf Update prüfen" |
| `Acknowledgements.swift` | Open-Source-Lizenzen (lädt acknowledgements.json) |
| `Feedback.swift` | Bug-Report-Formular + POST an /api/feedback (GitHub Issue) |
| `engine/multicam_engine.py` | CLI-Entry: --scan und --folder Modi |
| `engine/protocol.py` | JsonLineWriter, __PROGRESS__-Parsing, Display-Namen |

## App-Bundle (Distribution)

```
MultiCamCutter.app/Contents/
  MacOS/MulticamCutter              <- SwiftUI Binary
  Frameworks/
    Sparkle.framework               <- Auto-Update (via SPM, eingebettet)
  Resources/
    multicam-engine/                <- PyInstaller OneDir Bundle
      multicam-engine               <- Standalone Python Binary
      face_landmarker.task          <- MediaPipe Model (4 MB)
    ffmpeg, ffprobe                 <- Static arm64-Builds (self-contained, osxexperts.net)
    AppIcon.icns                    <- Offizielles Icon (multicamcutter-web/assets)
    acknowledgements.json           <- Open-Source-Lizenztexte (scripts/collect_licenses.py)
  Info.plist                        <- SUFeedURL, SUPublicEDKey, CFBundleIconFile
```

`build_app.sh` baut das Bundle manuell (kein Xcode). Deshalb muss Sparkle
**per Skript** eingebettet werden — Xcode wuerde das sonst automatisch tun:
1. `swift build -c release` legt `Sparkle.framework` neben das Binary (`--show-bin-path`)
2. Framework nach `Contents/Frameworks/` kopieren (cp -R, Symlinks bleiben)
3. `install_name_tool -add_rpath @executable_path/../Frameworks` auf das Binary
   (Load-Command ist `@rpath/Sparkle.framework/Versions/B/Sparkle`)
4. Ad-hoc `codesign --force --sign - <app>` (OHNE --deep): install_name_tool
   invalidiert die Linker-ad-hoc-Sig → App startet sonst nicht auf arm64.
   Sparkle behaelt seine eigene gueltige Signatur (org.sparkle-project.Sparkle).

## Pfadaufloesung (Dev vs Bundle)

`EngineController.toolkitRoot` sucht:
1. Relativ zu `#filePath` (Xcode-Build)
2. Fallback: hardcoded Dev-Pfad

Engine-Binary: Bundle > Dev-Pfad
Python: venv > Homebrew > System

## Dependencies im Bundle

Must-have: Python 3.12, PyTorch, MediaPipe, OpenCV, numpy, scipy, soundfile,
pyaaf2, torchaudio, transformers + CLIP, ffmpeg + ffprobe.
Lizenz (Remote-Modus): **requests** (HTTP) + **cryptography** (Ed25519-Signatur).
Beide MÜSSEN im Bundle sein — sonst schlägt die Signaturprüfung still fehl
(alle Lizenzen ungültig). In hidden_imports des Spec + im Build-venv installiert.

Nicht im Bundle: Whisper, DaVinci Resolve API, Streamlit.

## Distribution

DMG ueber Website (kein App Store — embedded Python nicht erlaubt).
Apple Developer Account (99$/Jahr), Notarization via `xcrun notarytool`.

## Auto-Update (Sparkle)

- **Framework**: Sparkle 2.x via SPM (`Package.swift`), Version 2.9.4.
- **Wrapper**: `Sources/Updater.swift` — `UpdaterController` haelt den
  `SPUStandardUpdaterController` (@MainActor). Startet nur wenn `SUFeedURL`
  gesetzt ist (in Dev/`swift run` ohne Info.plist bleibt er aus → kein Alert).
- **UI**: Ueber-Dialog ist ein AppKit-gehostetes Fenster (`AboutWindowController`
  + SwiftUI `AboutView`), geoeffnet ueber `CommandGroup(replacing: .appInfo)`.
  Enthaelt Version (`AppVersion` liest Info.plist) + "Auf Update pruefen"-Button.
  Button `disabled`, solange `canCheckForUpdates == false` (KVO-Publisher).
- **Noch offen bis Website live**: EdDSA-Keypair (`generate_keys`), Public Key
  in `SUPublicEDKey`, Appcast-XML hosten, `SUEnableAutomaticChecks` auf `true`,
  Releases mit `sign_update` signieren. Bis dahin zeigt der Button erwartungs-
  gemaess einen Netzwerkfehler (Platzhalter-Feed nicht erreichbar).
