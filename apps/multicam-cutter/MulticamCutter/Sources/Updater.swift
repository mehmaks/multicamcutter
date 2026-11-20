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

// MARK: - Update-Kanal (stabil / Beta)

/// Beta-Kanal: Beta-Versionen stehen im SELBEN Appcast wie stabile, aber mit
/// `<sparkle:channel>beta</sparkle:channel>`. Sparkle zeigt sie nur, wenn
/// `allowedChannels` "beta" enthaelt — alle anderen Installationen sehen sie nie.
/// Contract mit der Website: `brain/Appcast-Hosting.md` → Beta-Kanal.
enum UpdateChannel {
    static let defaultsKey = "updates.betaChannel"
    static var betaEnabled: Bool { UserDefaults.standard.bool(forKey: defaultsKey) }
    /// Laeuft gerade eine Beta? Erkannt an der Anzeige-Version (`1.1.0-beta.1`).
    static var isBetaBuild: Bool { AppVersion.short.lowercased().contains("beta") }

    /// Wer eine Beta installiert (z. B. per Download von der Website), will auch die
    /// nächsten Betas bekommen. Deshalb schaltet eine Beta-Version den Kanal beim Start
    /// selbst ein — aber nur, solange der Nutzer den Schalter nie angefasst hat
    /// (Schlüssel fehlt). Ein bewusstes „aus" bleibt aus. (User 20.11.)
    static func betaBuildSchaltetKanalEin() {
        guard isBetaBuild, UserDefaults.standard.object(forKey: defaultsKey) == nil else { return }
        UserDefaults.standard.set(true, forKey: defaultsKey)
    }
}

/// Sparkle fragt vor jeder Pruefung, welche Kanaele erlaubt sind.
final class UpdaterChannelDelegate: NSObject, SPUUpdaterDelegate {
    func allowedChannels(for updater: SPUUpdater) -> Set<String> {
        UpdateChannel.betaEnabled ? ["beta"] : []
    }
}

/// Sucht im Appcast die neueste STABILE Version (Eintrag ohne `sparkle:channel`).
/// Fuer die Rueckkehr von einer Beta: Sparkle selbst installiert nie eine aeltere
/// Version — die App bietet deshalb den Download der stabilen DMG an.
struct StableRelease {
    let shortVersion: String
    let downloadURL: URL

    static func latest() async -> StableRelease? {
        guard let feed = (Bundle.main.infoDictionary?["SUFeedURL"] as? String).flatMap(URL.init(string:)),
              let (data, _) = try? await URLSession.shared.data(from: feed) else { return nil }
        let parser = AppcastItemParser()
        let xml = XMLParser(data: data)
        xml.delegate = parser
        guard xml.parse() else { return nil }
        // Neueste nach Build-Nummer (Zeitstempel), nicht nach Anzeige-Version
        let best = parser.items
            .filter { $0.channel == nil && $0.url != nil }
            .max { (Int($0.build) ?? 0) < (Int($1.build) ?? 0) }
        guard let b = best, let url = b.url else { return nil }
        return StableRelease(shortVersion: b.short, downloadURL: url)
    }
}

private final class AppcastItemParser: NSObject, XMLParserDelegate {
    struct Item { var channel: String?; var build = ""; var short = ""; var url: URL? }
    var items: [Item] = []
    private var current: Item?
    private var text = ""
    /// Delta-Updates stehen als eigene <enclosure> in <sparkle:deltas> — nicht die DMG.
    private var inDeltas = false

    func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes: [String: String] = [:]) {
        text = ""
        if name == "item" { current = Item() }
        if name == "sparkle:deltas" { inDeltas = true }
        if name == "enclosure", current != nil, !inDeltas {
            current?.url = attributes["url"].flatMap(URL.init(string:))
            if let v = attributes["sparkle:version"] { current?.build = v }
            if let s = attributes["sparkle:shortVersionString"] { current?.short = s }
        }
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) { text += string }
    func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?,
                qualifiedName qName: String?) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        switch name {
        case "sparkle:deltas": inDeltas = false
        case "sparkle:channel": current?.channel = t
        case "sparkle:version": current?.build = t
        case "sparkle:shortVersionString": current?.short = t
        case "item": if let c = current { items.append(c) }; current = nil
        default: break
        }
    }
}

// MARK: - Sparkle-Updater

/// Duenner Wrapper um SPUStandardUpdaterController. Wird in der App als `let`
/// gehalten. Der Standard-User-Driver liefert die komplette Update-UI
/// (Verfuegbar-Dialog, Fortschritt, Neustart) von Sparkle.
@MainActor
final class UpdaterController {
    let controller: SPUStandardUpdaterController
    /// Sparkle haelt den Delegate nur schwach → hier stark referenzieren.
    private let channelDelegate = UpdaterChannelDelegate()

    var updater: SPUUpdater { controller.updater }
    /// Laeuft der Updater ueberhaupt? Im Dev-Build (`swift run`, keine
    /// Info.plist mit SUFeedURL) ist er nicht gestartet — dann darf die UI
    /// keinen Pruefen-Button anbieten, der ins Leere greift.
    let isActive: Bool

    init() {
        // Ohne SUFeedURL (z.B. `swift run` ohne Info.plist) startet der Updater
        // nicht — sonst zeigt Sparkle einen Fehler-Alert. Im .app-Bundle ist die
        // URL gesetzt und der Updater startet regulaer.
        let hasFeed = (Bundle.main.infoDictionary?["SUFeedURL"] as? String)?.isEmpty == false
        isActive = hasFeed
        // Vor dem Start von Sparkle, damit schon die erste Prüfung den Beta-Kanal kennt.
        UpdateChannel.betaBuildSchaltetKanalEin()
        controller = SPUStandardUpdaterController(
            startingUpdater: hasFeed,
            updaterDelegate: channelDelegate,
            userDriverDelegate: nil
        )
    }
}

/// Beobachtet `canCheckForUpdates`, damit der Button waehrend eines laufenden
/// Checks deaktiviert wird.
@MainActor
final class UpdaterViewModel: ObservableObject {
    @Published var canCheckForUpdates = false
    private let updater: SPUUpdater

    /// Automatische Pruefung. Sparkle persistiert das selbst in den
    /// UserDefaults (`SUEnableAutomaticChecks`) — hier wird nur durchgereicht,
    /// KEIN eigener @AppStorage-Schluessel: zwei Quellen fuer denselben Zustand
    /// laufen sonst auseinander.
    var automaticallyChecksForUpdates: Bool {
        get { updater.automaticallyChecksForUpdates }
        set {
            objectWillChange.send()
            updater.automaticallyChecksForUpdates = newValue
        }
    }

    init(updater: SPUUpdater) {
        self.updater = updater
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

            Text("Automatic multicam editing for podcasts")
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Button("Check for updates") {
                updater.checkForUpdates()
            }
            .disabled(!viewModel.canCheckForUpdates)
            .padding(.top, 4)

            Button("Open-source licenses") {
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

// MARK: - Update-Sektion fuer die Einstellungen

/// Zeigt Version, manuelle Pruefung und den Schalter fuer die automatische
/// Pruefung. Bewusst dieselbe Datei wie AboutView: beide haengen am selben
/// SPUUpdater, und getrennte Dateien laden dazu ein, den Zustand doppelt zu
/// halten.
struct UpdateSettingsSection: View {
    private let updater: SPUUpdater
    private let isActive: Bool
    @StateObject private var viewModel: UpdaterViewModel

    init(updater: SPUUpdater, isActive: Bool) {
        self.updater = updater
        self.isActive = isActive
        _viewModel = StateObject(wrappedValue: UpdaterViewModel(updater: updater))
    }

    var body: some View {
        Section("Updates") {
            LabeledContent("Installed") {
                Text(AppVersion.display)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)   // zum Kopieren in Bug-Reports
            }

            if isActive {
                Toggle("Check for updates automatically", isOn: Binding(
                    get: { viewModel.automaticallyChecksForUpdates },
                    set: { viewModel.automaticallyChecksForUpdates = $0 }))
                Text(loc("Checks shortly after launch and then regularly in the "
                     + "background. It only tells you when something is found — "
                     + "nothing is installed until you confirm."))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Button("Check for updates now") {
                    updater.checkForUpdates()
                }
                .disabled(!viewModel.canCheckForUpdates)

                Toggle("Receive beta versions", isOn: Binding(
                    get: { betaEnabled },
                    set: { newValue in
                        betaEnabled = newValue
                        // Beta aus, aber gerade eine Beta installiert → Rueckkehr anbieten
                        if !newValue && UpdateChannel.isBetaBuild { offerStableReturn() }
                    }))
                Text(loc("Beta versions bring new features before the official release. "
                     + "They are tested, but may still contain errors. You can switch "
                     + "back at any time."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                // Dev-Build ohne SUFeedURL: kein Button, der ins Leere greift.
                Text("Update checks are not active in this development version.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .alert(returnAlertTitle, isPresented: $showReturnAlert, presenting: stableRelease) { rel in
            Button(loc("Download stable version")) { NSWorkspace.shared.open(rel.downloadURL) }
            Button(loc("Keep beta"), role: .cancel) {}
        } message: { rel in
            Text(String(format: loc("You are using beta version %@. Updates will no longer offer betas. "
                                    + "Do you want to download the latest stable version %@ now? "
                                    + "Afterwards, open the downloaded file and drag the app into "
                                    + "your Applications folder."),
                        AppVersion.short, rel.shortVersion))
        }
        .alert(loc("Stable version not found"), isPresented: $showReturnError) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(loc("The update feed could not be loaded. You will receive the next stable "
                     + "version automatically, or you can download it from the website."))
        }
    }

    @AppStorage(UpdateChannel.defaultsKey) private var betaEnabled = false
    @State private var stableRelease: StableRelease?
    @State private var showReturnAlert = false
    @State private var showReturnError = false
    private var returnAlertTitle: String { loc("Return to the stable version?") }

    private func offerStableReturn() {
        Task {
            if let rel = await StableRelease.latest() {
                stableRelease = rel
                showReturnAlert = true
            } else {
                showReturnError = true
            }
        }
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
            w.title = "About MultiCamCutter"
            w.styleMask = [.titled, .closable]
            w.isReleasedWhenClosed = false
            w.center()
            window = w
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
