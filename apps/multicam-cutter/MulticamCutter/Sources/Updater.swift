import SwiftUI
import AppKit
import Combine
import Sparkle

// MARK: - Versions-Info (Single Source: Info.plist, Fallback fuer Dev)

enum AppVersion {
    static var short: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0"
    }
    static var build: String {
        Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
    }
    /// Git-Stand des Builds (Kurz-SHA, ggf. `-dirty`). Von build_app.sh gesetzt.
    static var gitCommit: String {
        Bundle.main.infoDictionary?["GitCommit"] as? String ?? "unknown"
    }
    /// Build-Nummer ist ein UTC-Zeitstempel (YYYYMMDDHHMM) — siehe build_app.sh.
    static var display: String { "Version \(short) (\(build)) · \(gitCommit)" }
}

// MARK: - Sparkle-Updater

/// Duenner Wrapper um SPUStandardUpdaterController. Wird in der App als `let`
/// gehalten. Der Standard-User-Driver liefert die komplette Update-UI
/// (Verfuegbar-Dialog, Fortschritt, Neustart) von Sparkle.
@MainActor
final class UpdaterController {
    let controller: SPUStandardUpdaterController

    var updater: SPUUpdater { controller.updater }

    init() {
        // Ohne SUFeedURL (z.B. `swift run` ohne Info.plist) startet der Updater
        // nicht — sonst zeigt Sparkle einen Fehler-Alert. Im .app-Bundle ist die
        // URL gesetzt und der Updater startet regulaer.
        let hasFeed = (Bundle.main.infoDictionary?["SUFeedURL"] as? String)?.isEmpty == false
        controller = SPUStandardUpdaterController(
            startingUpdater: hasFeed,
            updaterDelegate: nil,
            userDriverDelegate: nil
        )
    }
}

/// Beobachtet `canCheckForUpdates`, damit der Button waehrend eines laufenden
/// Checks deaktiviert wird.
@MainActor
final class UpdaterViewModel: ObservableObject {
    @Published var canCheckForUpdates = false

    init(updater: SPUUpdater) {
        updater.publisher(for: \.canCheckForUpdates)
            .assign(to: &$canCheckForUpdates)
    }
}

// MARK: - Ueber-Dialog (mit "Auf Update pruefen")

struct AboutView: View {
    private let updater: SPUUpdater
    @StateObject private var viewModel: UpdaterViewModel

    init(updater: SPUUpdater) {
        self.updater = updater
        _viewModel = StateObject(wrappedValue: UpdaterViewModel(updater: updater))
    }

    var body: some View {
        VStack(spacing: 10) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 88, height: 88)

            Text("MultiCamCutter")
                .font(.title2.bold())

            Text(AppVersion.display)
                .font(.callout)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)   // zum Kopieren in Bug-Reports

            Text("Automatischer Multicam-Schnitt für Podcasts")
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Button("Auf Update prüfen") {
                updater.checkForUpdates()
            }
            .disabled(!viewModel.canCheckForUpdates)
            .padding(.top, 4)

            Button("Open-Source-Lizenzen") {
                AcknowledgementsWindowController.shared.show()
            }
            .buttonStyle(.link)
            .padding(.top, 2)

            Text("© 2026")
                .font(.caption)
                .foregroundStyle(.tertiary)
                .padding(.top, 2)
        }
        .padding(28)
        .frame(width: 320)
    }
}

// MARK: - Ueber-Fenster (AppKit-gehostet, robust ueber Menu-Command)

/// Haelt ein einzelnes Ueber-Fenster. AppKit statt SwiftUI-Window-Scene, damit
/// das Fenster garantiert nur auf Menuebefehl (nicht beim Start) erscheint.
@MainActor
final class AboutWindowController {
    static let shared = AboutWindowController()
    private var window: NSWindow?

    func show(updater: SPUUpdater) {
        if window == nil {
            let hosting = NSHostingController(rootView: AboutView(updater: updater).tint(.brandAccent))
            let w = NSWindow(contentViewController: hosting)
            w.title = "Über MultiCamCutter"
            w.styleMask = [.titled, .closable]
            w.isReleasedWhenClosed = false
            w.center()
            window = w
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
