import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var engine: EngineController
    @State private var mainWindow: NSWindow?
    @State private var frameBeforeRun: NSRect?
    /// Fenster-Constraints vor dem Lauf — während der Analyse wird alles fixiert.
    @State private var windowStateBeforeRun: WindowConstraints?
    /// Materialhinweis (siehe FirstRunSheet). Gespeichert wird der zuletzt
    /// bestaetigte INHALTS-Stand, damit geaenderte Voraussetzungen erneut erscheinen.
    @AppStorage("firstRunInfoSeenRevision") private var firstRunInfoSeenRevision = 0
    @State private var showFirstRunInfo = false
    /// Gemessene Wizard-Hoehen fuers Content-Fitting (s. fitWindowToWizardContent).
    @State private var wizardContentHeight: CGFloat = 0
    @State private var wizardViewportHeight: CGFloat = 0
    /// Fitting-Sicherungen: waehrend der Animation keine neuen Fits (Zwischen-
    /// frames liefern veraltete Messwerte → Aufschaukeln, Realfall 24.07.);
    /// Flip-Flop-Detektor stoppt echte Rueckkopplungen.
    @State private var windowFitInProgress = false
    @State private var recentFitTargets: [CGFloat] = []
    @State private var fitSuppressedAtContent: CGFloat? = nil

    /// Alles, was die Analyse-Sperre überschreibt, um es danach zurückzugeben.
    private struct WindowConstraints {
        let minSize: NSSize
        let maxSize: NSSize
        let contentMin: NSSize
        let contentMax: NSSize
        let wasResizable: Bool
    }

    /// Breite, auf die das Fenster während der Analyse schrumpft.
    private static let runWidth: CGFloat = 760
    /// Am laufenden Analysefenster ausgemessen (inkl. Titelleiste).
    private static let runHeight: CGFloat = 552
    /// Standard-Fensterbreite: Wizard-Inhaltsbreite (720) + 2×28 Rand.
    private static let wizardWindowWidth: CGFloat = WizardLayout.contentWidth + 56

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
        .sheet(isPresented: $showFirstRunInfo) {
            FirstRunSheet()
        }
        .onAppear {
            // Erst nach dem Fensteraufbau: ein Sheet, das im selben Zyklus wie
            // das Fenster erscheint, sitzt sonst gelegentlich ohne Elternfenster
            // in der Bildschirmmitte.
            guard firstRunInfoSeenRevision < FirstRunSheet.contentRevision else { return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                showFirstRunInfo = true
            }
        }
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
        .onPreferenceChange(WizardContentHeightKey.self) { h in
            wizardContentHeight = h
            fitWindowToWizardContent()
        }
        .onPreferenceChange(WizardViewportHeightKey.self) { h in
            wizardViewportHeight = h
            fitWindowToWizardContent()
        }
        .onChange(of: engine.wizardStep) { _, _ in
            // Frischer Start je Seite: Flip-Flop-Gedaechtnis leeren.
            recentFitTargets = []
            fitSuppressedAtContent = nil
            fitWindowToWizardContent()
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
        enforceWizardWindowChrome(window)
    }

    /// Fixe Standardbreite + Resize-Sperre (User-Entscheid 24.07.): mit der
    /// automatischen Hoehenanpassung hat manuelles Resizing keinen Zweck mehr —
    /// es erzeugte nur den Leerraum, den das Content-Fitting eliminiert.
    /// Idempotent und WIEDERHOLT anzuwenden: SwiftUI stellt `.resizable` bei
    /// Content-View-Wechseln wieder her (gleiche Lektion wie beim Analyse-Lock).
    private func enforceWizardWindowChrome(_ window: NSWindow) {
        guard frameBeforeRun == nil,               // Analyse-Modus verwaltet sich selbst
              !window.styleMask.contains(.fullScreen) else { return }
        if window.styleMask.contains(.resizable) {
            window.styleMask.remove(.resizable)
        }
        if abs(window.frame.width - Self.wizardWindowWidth) > 1 {
            var f = window.frame
            let top = f.maxY
            let midX = f.midX
            f.size.width = Self.wizardWindowWidth
            f.origin.x = midX - Self.wizardWindowWidth / 2
            f.origin.y = top - f.size.height
            window.setFrame(f, display: true, animate: true)
        }
    }

    /// Fenster passt sich je Wizard-Seite dem INHALT an (User-Wunsch 24.07. —
    /// ersetzt das alte „Screen 3 → fix 940 pt", das unten viel Leerraum liess).
    ///
    /// Der Trick: Inhalt und sichtbarer Scroll-Bereich werden gemessen; ihre
    /// Differenz ist EXAKT das, was dem Fenster fehlt (oder zu viel ist) —
    /// Titelleiste/Header/Footer muessen nie beziffert werden. Obergrenze:
    /// Bildschirmhoehe (abzgl. Rand) bzw. 1100 pt — darueber scrollt der
    /// Inhalt wie bisher. Oberkante bleibt fix (waechst/schrumpft nach unten).
    private func fitWindowToWizardContent() {
        // Breite + Resize-Sperre bei jeder Gelegenheit nachziehen (SwiftUI
        // stellt .resizable bei View-Wechseln wieder her).
        if let w = mainWindow { enforceWizardWindowChrome(w) }
        guard let window = mainWindow,
              engine.state == .ready,             // nur im Wizard, nie im Lauf
              frameBeforeRun == nil,              // nicht waehrend Analyse-Restore
              !window.styleMask.contains(.fullScreen),
              !window.inLiveResize,               // nie gegen den Nutzer ziehen
              !windowFitInProgress,               // erst ausanimieren, dann messen
              wizardContentHeight > 0, wizardViewportHeight > 0 else { return }

        // Nach erkannter Rueckkopplung: stillhalten, bis sich der Inhalt
        // WIRKLICH aendert (>10 pt) oder die Seite wechselt.
        if let s = fitSuppressedAtContent {
            if abs(s - wizardContentHeight) < 10 { return }
            fitSuppressedAtContent = nil
        }

        let delta = wizardContentHeight - wizardViewportHeight
        guard abs(delta) > 4 else { return }      // stabil: passt schon

        let screenLimit = (window.screen ?? NSScreen.main)?.visibleFrame.height ?? 1100
        let maxH = min(1100, screenLimit - 24)
        let minH: CGFloat = 520

        var f = window.frame
        let top = f.maxY
        let target = min(max(f.height + delta, minH), maxH)
        guard abs(target - f.height) > 4 else { return }   // an der Grenze geklemmt

        // Flip-Flop-Detektor (A → B → A): der Inhalt haengt dann von der
        // Fensterhoehe ab — anhalten statt endlos pumpen (Realfall 24.07.:
        // Endlos-Animation auf Screen 3).
        if recentFitTargets.count >= 2,
           abs(recentFitTargets[recentFitTargets.count - 2] - target) < 4 {
            fitSuppressedAtContent = wizardContentHeight
            return
        }
        recentFitTargets.append(target)
        if recentFitTargets.count > 3 { recentFitTargets.removeFirst() }

        f.size.height = target
        f.origin.y = top - target
        windowFitInProgress = true
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.25
            window.animator().setFrame(f, display: true)
        }, completionHandler: {
            // Nach dem Settle genau EIN Korrekturlauf mit frischen Messwerten —
            // waehrend der Animation eingetroffene Werte werden bewusst verworfen.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                windowFitInProgress = false
                fitWindowToWizardContent()
            }
        })
    }

    /// Die Progress-View braucht deutlich weniger Platz als das Setup: beim
    /// Analyse-Start bekommt das Fenster eine feste Größe (und ist so lange
    /// nicht skalierbar), danach exakt die vorherige Geometrie zurück.
    private func animateWindowWidth(for state: AppState) {
        guard let window = mainWindow else { return }

        if state == .running {
            // Nur einmal setzen. Kein Größenvergleich mehr: im Analyse-Modus gilt
            // die feste Geometrie, auch wenn das Fenster vorher kleiner war.
            guard frameBeforeRun == nil else { return }
            frameBeforeRun = window.frame
            windowStateBeforeRun = WindowConstraints(
                minSize:      window.minSize,
                maxSize:      window.maxSize,
                contentMin:   window.contentMinSize,
                contentMax:   window.contentMaxSize,
                wasResizable: window.styleMask.contains(.resizable))
            // Um den Mittelpunkt herum verkleinern — bei fixem origin.y würde
            // die Titelleiste sichtbar nach unten springen.
            let target = NSRect(x: window.frame.midX - Self.runWidth  / 2,
                                y: window.frame.midY - Self.runHeight / 2,
                                width:  Self.runWidth,
                                height: Self.runHeight)
            window.setFrame(target, display: true, animate: true)
            applyRunWindowLock(window)
            // Noch einmal nach dem Layout-Durchgang: SwiftUI konfiguriert das
            // Fenster beim Wechsel der Content-View neu und stellt .resizable
            // dabei wieder her. Zusätzlich hält der Fortschritts-Heartbeat die
            // Sperre nach (updateDockProgress).
            DispatchQueue.main.async { applyRunWindowLock(window) }
            return
        }

        // Jeder Nicht-Running-Zustand stellt die gemerkte Geometrie wieder her.
        guard let restore = frameBeforeRun else { return }
        // ZUERST entsperren: solange min == max gilt, klemmt setFrame auf die
        // Analyse-Größe und die Wiederherstellung liefe ins Leere.
        if let s = windowStateBeforeRun {
            window.minSize        = s.minSize
            window.maxSize        = s.maxSize
            window.contentMinSize = s.contentMin
            window.contentMaxSize = s.contentMax
            if s.wasResizable { window.styleMask.insert(.resizable) }
        }
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
        if state == .ready || state == .idle {
            frameBeforeRun       = nil
            windowStateBeforeRun = nil
        }
    }

    /// Sperrt das Fenster auf die Analyse-Größe. Muss WIEDERHOLT anwendbar sein:
    /// die Szene nutzt `.windowResizability(.automatic)`, SwiftUI konfiguriert das
    /// Fenster beim Wechsel der Content-View neu und stellt `.resizable` dabei
    /// wieder her. Einmaliges Entfernen genügt deshalb nicht (zwei Anläufe kostete
    /// das). Idempotent — tut nichts, wenn schon gesperrt.
    private func applyRunWindowLock(_ window: NSWindow) {
        let fixed = NSSize(width: Self.runWidth, height: Self.runHeight)
        let content = window.contentRect(
            forFrameRect: NSRect(origin: .zero, size: fixed)).size
        if window.minSize != fixed { window.minSize = fixed }
        if window.maxSize != fixed { window.maxSize = fixed }
        // SwiftUI leitet die Fenstergröße aus dem CONTENT ab — ohne diese beiden
        // greift die Frame-Begrenzung oben gar nicht.
        if window.contentMinSize != content { window.contentMinSize = content }
        if window.contentMaxSize != content { window.contentMaxSize = content }
        // Im Vollbild nicht anfassen — das würde den Vollbild-Zustand brechen.
        if !window.styleMask.contains(.fullScreen),
           window.styleMask.contains(.resizable) {
            window.styleMask.remove(.resizable)
        }
    }

    /// Dock-Balken bei Fortschritt aktualisieren (nur während der Analyse).
    private func updateDockProgress() {
        guard engine.state == .running else { return }
        DockProgress.shared.show(engine.overallProgress)
        // Heartbeat: holt die Sperre zurück, falls SwiftUI sie überschrieben hat.
        if let window = mainWindow { applyRunWindowLock(window) }
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
        for (index, item) in result.items.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + item.origin.x, y: bounds.minY + item.origin.y),
                // MIT der gemessenen (auf die Containerbreite gedeckelten) Groesse
                // platzieren, nicht .unspecified. Sonst rendert ein zu breites Kind
                // in seiner vollen Wunschbreite und ragt aus dem Container — genau
                // der Fall langer Kameranamen in der Bildgroessen-Pill bei schmalem
                // Fenster.
                proposal: ProposedViewSize(width: item.size.width, height: item.size.height))
        }
    }

    private func arrange(proposal: ProposedViewSize, subviews: Subviews)
        -> (size: CGSize, items: [(origin: CGPoint, size: CGSize)]) {
        let maxWidth = proposal.width ?? .infinity
        // Kinder gegen die Containerbreite messen (statt .unspecified): ein zu
        // langes Element kuerzt sich damit auf die verfuegbare Breite, statt sie
        // zu ueberschreiten. Kurze Elemente bleiben unveraendert kompakt, weil sie
        // sich ohne maxWidth:.infinity nicht aufblaehen.
        let childProposal = ProposedViewSize(width: maxWidth, height: nil)
        var items: [(origin: CGPoint, size: CGSize)] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0

        for subview in subviews {
            var size = subview.sizeThatFits(childProposal)
            size.width = min(size.width, maxWidth)   // Sicherheitsnetz
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            items.append((CGPoint(x: x, y: y), size))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
        }

        return (CGSize(width: maxWidth, height: y + rowHeight), items)
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

                    // Zaehler und Restzeit sind zwei verschiedene Dinge. Frueher
                    // landete der Zaehler des CLIP-Passes im ETA-Feld und wurde
                    // als "ETA: 341/384" ausgegeben — keine Restzeit.
                    if !engine.stepCounter.isEmpty {
                        Text(engine.stepCounter)
                            .font(.system(.body, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }

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
