import SwiftUI
import AppKit

@main
struct MulticamCutterApp: App {
    @StateObject private var engine = EngineController()
    private let updater = UpdaterController()

    init() {
        // Als regulaere GUI-App registrieren (Dock-Icon + Keyboard-Fokus)
        NSApplication.shared.setActivationPolicy(.regular)
        // Tooltips schneller einblenden. AppKit wartet per Default ~1–2 s;
        // NSInitialToolTipDelay ist in Millisekunden und gilt nur fuer diese App.
        UserDefaults.standard.set(200, forKey: "NSInitialToolTipDelay")
        // Temporaere Gesamt-WAVs gesplitteter Aufnahmen: Reste eines Absturzes
        // jetzt wegraeumen, beim Beenden wieder (sie sind je ~1 GB gross).
        EngineController.removeSplitJoinDirectory()
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification, object: nil, queue: nil
        ) { _ in
            EngineController.removeSplitJoinDirectory()
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(engine)
                .frame(minWidth: 720, minHeight: 520)
                .tint(.brandAccent)
                .onAppear {
                    NSApplication.shared.activate(ignoringOtherApps: true)
                }
        }
        .windowStyle(.titleBar)
        .defaultSize(width: 1100, height: 680)
        .commands {
            CommandGroup(replacing: .newItem) {}

            // About-Dialog mit Version + "Auf Update prüfen"
            CommandGroup(replacing: .appInfo) {
                Button("About MultiCamCutter") {
                    AboutWindowController.shared.show(updater: updater.updater)
                }
            }

            CommandGroup(replacing: .help) {
                Button("Report a bug…") {
                    engine.presentFeedback(fromError: false)
                }
            }

            CommandMenu("Project") {
                Button("New") {
                    engine.reset()
                }
                .keyboardShortcut("n")

                Button("Open folder...") {
                    let panel = NSOpenPanel()
                    panel.canChooseFiles = false
                    panel.canChooseDirectories = true
                    panel.allowsMultipleSelection = false
                    panel.message = "Choose episode folder"
                    if panel.runModal() == .OK, let url = panel.url {
                        engine.setFolder(url)
                    }
                }
                .keyboardShortcut("o")
            }
        }


        // Eigenes Log-Fenster (Cmd+L). Landet automatisch im "Fenster"-Menue.
        // Bleibt offen — auch nach Fehler und nach Analyse-Ende.
        Window("Log", id: "log") {
            LogWindow()
                .environmentObject(engine)
                .tint(.brandAccent)
        }
        .keyboardShortcut("l")

        Settings {
            SettingsView(updater: updater.updater, updaterIsActive: updater.isActive)
                .environmentObject(engine)   // CLIP-Tab liest @EnvironmentObject engine
        }
    }
}
