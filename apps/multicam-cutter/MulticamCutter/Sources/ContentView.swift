import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var engine: EngineController
    @State private var mainWindow: NSWindow?
    @State private var frameBeforeRun: NSRect?

    /// Breite, auf die das Fenster während der Analyse schrumpft.
    private static let runWidth: CGFloat = 760

    var body: some View {
        // Feedback-Button sitzt jetzt im Wizard-Footer neben „Zurück" (nicht mehr
        // global oben rechts). ErrorView + Menü haben weiterhin eigene Einstiege.
        ZStack {
            stateContent
        }
        .background(WindowAccessor { window in
            mainWindow = window
            configureWindowChrome(window)
        })
        .sheet(isPresented: $engine.showingFeedback) {
            FeedbackView().environmentObject(engine)
        }
        .sheet(isPresented: $engine.showClipPrompt) {
            ClipDownloadPrompt().environmentObject(engine)
        }
        .sheet(isPresented: $engine.isDownloadingClip) {
            ClipDownloadSheet().environmentObject(engine)
        }
        .alert("Download fehlgeschlagen",
               isPresented: Binding(get: { engine.clipError != nil },
                                    set: { if !$0 { engine.clipError = nil } })) {
            Button("OK", role: .cancel) { engine.clipError = nil }
        } message: {
            Text((engine.clipError ?? "") + "\n\nDu kannst die Analyse ohne Bilderkennung "
                 + "starten — schalte dazu „Ungünstige Cutaways verschieben (CLIP)\" in "
                 + "den Experteneinstellungen aus.")
        }
        .onChange(of: engine.state) { oldState, newState in
            animateWindowWidth(for: newState)
            handleMacIntegrations(from: oldState, to: newState)
        }
        .onChange(of: engine.stepNum) { _, _ in updateDockProgress() }
        .onChange(of: engine.stepPercent) { _, _ in updateDockProgress() }
        .onChange(of: engine.wizardStep) { _, step in
            growWindowForOverview(step)
        }
    }

    /// Vereinheitlichte, dunkle Titelleiste wie im Dummy: transparent, ohne Titeltext,
    /// Inhalt reicht unter die Leiste. Der Wizard-Header zeigt dort „MultiCamCutter ·
    /// Episode" rechts neben den Ampel-Buttons.
    private func configureWindowChrome(_ window: NSWindow) {
        // Dunkle, transparente Titelleiste — aber Titel SICHTBAR und Inhalt UNTER der
        // Leiste (kein fullSizeContentView). So steht der App-Titel sauber allein oben,
        // der Episodenname bleibt im Header darunter.
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .visible
        window.title = "MultiCamCutter"
        window.styleMask.remove(.fullSizeContentView)
        window.backgroundColor = NSColor(srgbRed: 14/255, green: 16/255, blue: 12/255, alpha: 1)
    }

    /// Screen 3 ist höher (Übersicht + Einstellungen). Fenster bei Bedarf wachsen
    /// lassen (Oberkante fix, nach unten), damit die Einstellungen nicht beschnitten sind.
    private func growWindowForOverview(_ step: WizardStep) {
        guard let window = mainWindow, step == .overview else { return }
        let target: CGFloat = 940
        guard window.frame.height < target else { return }
        var f = window.frame
        let top = f.maxY
        f.size.height = target
        f.origin.y = top - target
        window.setFrame(f, display: true, animate: true)
    }

    /// Die Progress-View braucht deutlich weniger Breite als das Setup: beim
    /// Analyse-Start das Fenster animiert zur Mitte hin schmälern, danach exakt
    /// die vorherige Geometrie wiederherstellen.
    private func animateWindowWidth(for state: AppState) {
        guard let window = mainWindow else { return }

        if state == .running {
            // Nur einmal schmälern — und nur, wenn überhaupt breiter als das Ziel.
            guard frameBeforeRun == nil, window.frame.width > Self.runWidth else { return }
            frameBeforeRun = window.frame
            let target = NSRect(x: window.frame.midX - Self.runWidth / 2,
                                y: window.frame.origin.y,
                                width: Self.runWidth,
                                height: window.frame.height)
            window.setFrame(target, display: true, animate: true)
            return
        }

        // Jeder Nicht-Running-Zustand stellt die gemerkte Geometrie wieder her.
        guard let restore = frameBeforeRun else { return }
        // NACH dem View-Wechsel (ProgressView_ → ResultView/WizardView) restaurieren:
        // synchron würde SwiftUIs Content-Sizing der neuen View die Breite direkt
        // wieder überschreiben.
        DispatchQueue.main.async {
            window.setFrame(restore, display: true, animate: true)
        }
        // Die Geometrie ERST freigeben, wenn wir zurück im Projekt sind.
        // .running → .done → .ready sind ZWEI Wechsel, und bei jedem passt SwiftUI die
        // Breite neu an den Content an — also muss auch zweimal restauriert werden.
        // (Früher wurde schon bei .done verworfen, deshalb blieb das Fenster bei der
        // Rückkehr ins Projekt schmal.)
        if state == .ready || state == .idle { frameBeforeRun = nil }
    }

    /// Dock-Balken bei Fortschritt aktualisieren (nur während der Analyse).
    private func updateDockProgress() {
        guard engine.state == .running else { return }
        DockProgress.shared.show(engine.overallProgress)
    }

    /// Dock-Balken + System-Notification an den Analyse-Lebenszyklus koppeln.
    private func handleMacIntegrations(from old: AppState, to new: AppState) {
        if new == .running {
            AnalysisNotifier.requestAuthIfNeeded()
            DockProgress.shared.show(0)
            return
        }
        // Übergänge NUR aus dem laufenden Zustand heraus melden.
        guard old == .running else { return }
        DockProgress.shared.hide()
        switch new {
        case .done:
            AnalysisNotifier.notify(title: "Analyse abgeschlossen",
                                    body: "\(engine.episodeName) ist fertig geschnitten.")
        case .error:
            AnalysisNotifier.notify(title: "Analyse fehlgeschlagen",
                                    body: engine.errorMessage.isEmpty ? "Es ist ein Fehler aufgetreten."
                                                                       : engine.errorMessage)
        case .ready:   // cancel() geht auf .ready zurück
            AnalysisNotifier.notify(title: "Analyse abgebrochen",
                                    body: "Die Analyse wurde gestoppt.")
        default:
            break
        }
    }

    @ViewBuilder
    private var stateContent: some View {
        switch engine.state {
        case .idle:
            FolderDropView()
        case .scanning:
            VStack(spacing: 16) {
                Spacer()
                Text(engine.scanLabel)
                    .font(.title3)
                SwiftUI.ProgressView(value: engine.scanPercent, total: 100)
                    .progressViewStyle(.linear)
                    .frame(width: 300)
                Text("\(Int(engine.scanPercent))%")
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
                Spacer()
            }
        case .ready:
            WizardView()
        case .running:
            ProgressView_()
        case .done:
            ResultView()
        case .error:
            ErrorView()
        }
    }
}

// MARK: - Folder Drop

struct FolderDropView: View {
    @EnvironmentObject var engine: EngineController
    @State private var isTargeted = false

    var body: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "folder.badge.plus")
                .font(.system(size: 64))
                .foregroundStyle(isTargeted ? .brandAccent : .secondary)

            Text("Episode-Ordner hierher ziehen")
                .font(.title2)
                .foregroundStyle(.secondary)

            Text("oder")
                .foregroundStyle(.tertiary)

            Button("Ordner auswählen...") {
                selectFolder()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onDrop(of: [UTType.fileURL], isTargeted: $isTargeted) { providers in
            handleDrop(providers)
        }
    }

    private func selectFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.message = "Ordner mit Kamera- und Mikrofon-Dateien auswählen"
        if panel.runModal() == .OK, let url = panel.url {
            engine.setFolder(url)
        }
    }

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
            guard let data = item as? Data,
                  let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                DispatchQueue.main.async {
                    engine.setFolder(url)
                }
            }
        }
        return true
    }
}

/// Live-Log waehrend der ffmpeg-Konvertierung. Modal, weil danach neu gescannt wird.
/// Fortschritt der FPS-Konvertierung — gleicher Aufbau wie `ClipDownloadSheet`:
/// Icon links, Titel (Datei + n/m), Balken, „mm:ss von mm:ss (Z %)". Der rohe
/// ffmpeg-Log erscheint nur noch im Fehlerfall (an der Fehlermeldung).
struct FpsConversionSheet: View {
    @EnvironmentObject var engine: EngineController

    private var fraction: Double {
        engine.convertTotal > 0 ? min(1, engine.convertDone / engine.convertTotal) : 0
    }

    private var title: String {
        let name = engine.convertLabel.isEmpty ? "Konvertiere …" : engine.convertLabel
        guard engine.convertFileCount > 1 else { return name }
        return "\(name)  (\(engine.convertFileIndex)/\(engine.convertFileCount))"
    }

    private var detail: String {
        guard engine.convertTotal > 0 else { return "Wird vorbereitet …" }
        var s = "\(timecode(engine.convertDone)) von \(timecode(engine.convertTotal)) "
              + "(\(Int(fraction * 100)) %)"
        if let eta = engine.convertEtaSeconds, eta.isFinite, eta > 0 {
            s += "  ·  noch ~\(etaText(eta))"
        }
        return s
    }

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "film")
                .font(.system(size: 30))
                .foregroundStyle(.brandAccent)

            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.headline)
                    .lineLimit(1)
                    .truncationMode(.middle)
                SwiftUI.ProgressView(value: fraction)
                    .progressViewStyle(.linear)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }

            Button {
                engine.cancelConversion()
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.title2)
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .help("Konvertierung abbrechen")
        }
        .padding(20)
        .frame(width: 460)
    }

    private func timecode(_ seconds: Double) -> String {
        let t = Int(seconds.rounded())
        return String(format: "%d:%02d", t / 60, t % 60)
    }

    /// Kompakte Restzeit: „45 s" / „4 min" / „2 h 20 min" (Sekunden ab 1 min
    /// weggelassen → das Zappeln bleibt aus).
    private func etaText(_ seconds: Double) -> String {
        let t = Int(seconds.rounded())
        if t >= 3600 { return "\(t / 3600) h \((t % 3600) / 60) min" }
        if t >= 60 { return "\(t / 60) min" }
        return "\(t) s"
    }
}

// MARK: - Editable Label (Doppelklick zum Bearbeiten)

struct EditableLabel: View {
    @Binding var text: String
    var icon: String = "pencil"
    @State private var isEditing = false
    @State private var editText = ""
    @FocusState private var isFocused: Bool
    @EnvironmentObject var engine: EngineController

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .foregroundStyle(.secondary)

            if isEditing {
                TextField("Name", text: $editText)
                    .textFieldStyle(.roundedBorder)
                    .focused($isFocused)
                    .onSubmit {
                        text = editText
                        isEditing = false
                        engine.saveSession()
                    }
                    .onExitCommand { isEditing = false }
                    .task {
                        try? await Task.sleep(for: .milliseconds(50))
                        isFocused = true
                    }
            } else {
                Text(text)
                    .lineLimit(1)
                    .onTapGesture(count: 2) {
                        editText = text
                        isEditing = true
                    }
                Button {
                    editText = text
                    isEditing = true
                } label: {
                    Image(systemName: "pencil").font(.caption)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .help("Episode umbenennen — bestimmt den Namen der erzeugten AAF-Datei")
            }
        }
    }
}

// MARK: - Flow Layout (für Mic-Pills die umbrechen)

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = arrange(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(proposal: proposal, subviews: subviews)
        for (index, origin) in result.origins.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y),
                                  proposal: .unspecified)
        }
    }

    private func arrange(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, origins: [CGPoint]) {
        let maxWidth = proposal.width ?? .infinity
        var origins: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            origins.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
        }

        return (CGSize(width: maxWidth, height: y + rowHeight), origins)
    }
}

// MARK: - Progress

struct ProgressView_: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(spacing: 16) {
            Spacer()

            if let image = engine.facemeshImage {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxWidth: 400, maxHeight: 225)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            Text(engine.stepLabel)
                .font(.title2)
                .fontWeight(.medium)

            if engine.stepPercent > 0 {
                // Determinate: Prozent bekannt
                SwiftUI.ProgressView(value: engine.stepPercent, total: 100)
                    .progressViewStyle(.linear)
                    .frame(width: 400)

                HStack(spacing: 16) {
                    Text("\(Int(engine.stepPercent))%")
                        .font(.system(.body, design: .monospaced))
                        .foregroundStyle(.secondary)

                    if !engine.stepETA.isEmpty && engine.stepETA != "--:--" {
                        Text("ETA: \(engine.stepETA)")
                            .font(.system(.body, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                // Indeterminate: kein Prozent, oszillierender Balken
                SwiftUI.ProgressView()
                    .progressViewStyle(.linear)
                    .frame(width: 400)
            }

            Text("Schritt \(engine.stepNum) von \(engine.totalSteps)")
                .font(.subheadline)
                .foregroundStyle(.tertiary)

            Button(role: .destructive) {
                engine.cancel()
            } label: {
                Text("Abbrechen")
            }
            .buttonStyle(.bordered)
            .padding(.top, 4)

            // Log-Expander entfernt: das Live-Log wohnt jetzt im eigenen Fenster
            // (Menü „Fenster") mit echten Log-Dateien.

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Result

struct ResultView: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.green)

            Text("Fertig!")
                .font(.title)

            if let aaf = engine.resultAAF {
                Text(aaf)
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(.secondary)

                Button("Im Finder anzeigen") {
                    NSWorkspace.shared.selectFile(aaf, inFileViewerRootedAtPath: "")
                }
                .buttonStyle(.borderedProminent)
            }

            if let stats = engine.resultStats {
                GroupBox("Statistik") {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 4) {
                        ForEach(Array(stats.sorted(by: { $0.key < $1.key })), id: \.key) { key, value in
                            GridRow {
                                Text(key)
                                    .foregroundStyle(.secondary)
                                Text(value)
                            }
                        }
                    }
                    .padding(8)
                }
            }

            HStack(spacing: 16) {
                Button("Zurück zum Projekt") {
                    engine.backToSetup()
                }
                .buttonStyle(.bordered)

                Button("Neuen Ordner wählen") {
                    engine.reset()
                }
                .buttonStyle(.link)
            }
            .padding(.top)

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Error

struct ErrorView: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.red)

            Text("Fehler")
                .font(.title)

            Text(engine.errorMessage)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 400)

            HStack {
                Button("Erneut versuchen") {
                    engine.start()
                }
                Button("Zurück") {
                    engine.reset()
                }
                Button("Fehler melden") {
                    engine.presentFeedback(fromError: true)
                }
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Helpers

/// Reicht das NSWindow der Hosting-View nach oben durch (für Fenster-Animationen).
struct WindowAccessor: NSViewRepresentable {
    let onResolve: (NSWindow) -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        // Beim Erzeugen ist `view.window` noch nil — erst nach dem Einhängen abfragen.
        DispatchQueue.main.async {
            if let window = view.window { onResolve(window) }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}

func formatDuration(_ seconds: Double) -> String {
    let min = Int(seconds) / 60
    let sec = Int(seconds) % 60
    return "\(min):\(String(format: "%02d", sec)) min"
}

extension View {
    @ViewBuilder
    func `if`<Content: View>(_ condition: Bool, transform: (Self) -> Content) -> some View {
        if condition {
            transform(self)
        } else {
            self
        }
    }
}
