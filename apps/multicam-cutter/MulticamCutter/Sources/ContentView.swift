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
        ZStack(alignment: .topTrailing) {
            stateContent
            FeedbackButton()
                .padding(.top, 10)
                .padding(.trailing, 14)
        }
        .background(WindowAccessor { mainWindow = $0 })
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
                 + "starten — schalte dazu „Ungünstige Cutaways verschieben (CLIP)\" im "
                 + "Expertenmodus aus.")
        }
        .onChange(of: engine.state) { _, newState in
            animateWindowWidth(for: newState)
        }
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
        } else if let restore = frameBeforeRun {
            frameBeforeRun = nil
            window.setFrame(restore, display: true, animate: true)
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
            SetupView()
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

// MARK: - Setup (Hush-Style: Settings links, Content rechts)

struct SetupView: View {
    @EnvironmentObject var engine: EngineController
    @AppStorage("showSourcesInspector") private var showInspector = true

    private var allMicsAssigned: Bool {
        engine.unassignedMics.isEmpty
    }

    /// Warum der Start (noch) nicht geht — nil = alles bereit. Deaktivierte Quellen
    /// koennen die Analyse unmoeglich machen, deshalb hier mitpruefen.
    private var startBlockedReason: String? {
        if engine.activeCams.count < 2 {
            return "Mindestens 2 Kameras aktivieren (Quelldateien-Panel)"
        }
        if engine.activeMics.isEmpty {
            return "Mindestens eine Mikrofonspur aktivieren (Quelldateien-Panel)"
        }
        // Cams ohne Mic und ohne Totale-Tag fallen aus der Analyse — es müssen
        // genug übrig bleiben, sonst startet man ins Leere.
        if engine.analysisCams.count < 2 {
            return "Mindestens 2 Kameras brauchen ein Mic oder das Totale-Tag"
        }
        if !engine.fpsMismatches.isEmpty {
            return "FPS-Mismatch — bitte oben beheben"
        }
        if !allMicsAssigned {
            return "Bitte alle Mikrofonspuren zuordnen"
        }
        return nil
    }

    private func fpsText(_ v: Double) -> String {
        v <= 0 ? "?" : (v.rounded() == v ? String(Int(v)) : String(format: "%.2f", v))
    }

    var body: some View {
        VStack(spacing: 0) {
            NavigationSplitView {
                // ── Linke Seite: Settings ────────────────────────────────
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        Section {
                            EditableLabel(text: $engine.episodeName, icon: "film.stack")
                        } header: {
                            Text("Episode")
                                .font(.headline)
                                .foregroundStyle(.secondary)
                        }

                        Divider()

                        HStack {
                            Text("Parameter")
                                .font(.headline)
                                .foregroundStyle(.secondary)
                            Spacer()
                            PresetPicker()
                        }

                        ParameterForm()
                    }
                    .padding()
                }
                .navigationSplitViewColumnWidth(min: 240, ideal: 300, max: 400)
            } detail: {
                // ── Rechte Seite: Kamera-Zuordnung ───────────────────────
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        Text("Kamera-Zuordnung")
                            .font(.title2)
                            .fontWeight(.semibold)
                            .padding(.horizontal)

                        if !engine.fpsMismatches.isEmpty {
                            fpsMismatchBanner
                                .padding(.horizontal)
                        }

                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 220, maximum: 300), spacing: 16)],
                                  alignment: .leading, spacing: 16) {
                            // Nur aktivierte Kameras. Bewusst ueber die Indizes von
                            // cameraInfos, damit CameraCard(camIndex:) weiter stimmt.
                            ForEach(engine.cameraInfos.indices.filter { engine.cameraInfos[$0].included },
                                    id: \.self) { idx in
                                CameraCard(camIndex: idx)
                            }
                        }
                        .padding(.horizontal)

                        if !engine.unassignedMics.isEmpty {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Nicht zugeordnet")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .padding(.horizontal)

                                FlowLayout(spacing: 8) {
                                    ForEach(engine.unassignedMics) { mic in
                                        MicPill(mic: mic)
                                    }
                                }
                                .padding(.horizontal)
                            }
                        }

                        Spacer().frame(height: 16)
                    }
                    .padding(.top)
                    .contentShape(Rectangle())
                    .onTapGesture { engine.selectedCamId = nil }   // Klick ins Leere = abwählen
                }
            }
            .navigationSplitViewStyle(.prominentDetail)
            // Inspector am SplitView, NICHT am aeusseren VStack: sonst haengt er
            // neben allem — auch neben der Button-Leiste, die dann vor dem
            // Fensterrand endet. So sitzt er ueber der Leiste, und „Analyse starten"
            // geht durch bis rechts.
            .inspector(isPresented: $showInspector) {
                InspectorPanel()
                    .inspectorColumnWidth(min: 220, ideal: 260, max: 400)
            }

            // ── Fixierter Button ──────────────────────────────────────
            Divider()
            VStack(spacing: 6) {
                if let reason = startBlockedReason {
                    Text(reason)
                        .font(.caption)
                        .foregroundStyle(.brandSecondary)
                }
                Button {
                    engine.start()
                } label: {
                    Label("Analyse starten", systemImage: "play.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(startBlockedReason != nil)
            }
            .padding(.horizontal)
            .padding(.vertical, 12)
            .background(.bar)
        }
        .sheet(isPresented: $engine.isConverting) {
            FpsConversionSheet()
                .environmentObject(engine)
        }
        .alert("Konvertierung fehlgeschlagen",
               isPresented: Binding(get: { engine.convertError != nil },
                                    set: { if !$0 { engine.convertError = nil } })) {
            Button("OK", role: .cancel) { engine.convertError = nil }
        } message: {
            Text(engine.convertError ?? "")
        }
        .toolbar {
            ToolbarItem {
                Button {
                    showInspector.toggle()
                } label: {
                    Image(systemName: "sidebar.right")
                }
                .help("Quelldateien ein-/ausblenden")
            }
        }
    }
}

// MARK: - FPS-Mismatch-Banner + Konvertierung

extension SetupView {
    /// Weicht die Source-FPS von der Timeline-FPS ab, rechnet die EDL/AAF-Pipeline mit
    /// falschen Source-Frames → Drift + Standbild am Ende. Deshalb blockieren statt warnen.
    @ViewBuilder
    var fpsMismatchBanner: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                Text("FPS-Mismatch")
                    .fontWeight(.semibold)
            }
            .foregroundStyle(.brandSecondary)

            Text("Diese Kameras haben nicht die Timeline-Framerate (\(fpsText(engine.fps))). "
                 + "Ohne Korrektur driften Bild und Ton auseinander und am Ende der Timeline "
                 + "steht ein Standbild.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ForEach(engine.fpsMismatches) { cam in
                Text("• \(cam.displayName) — \(fpsText(cam.fps)) fps")
                    .font(.system(.caption, design: .monospaced))
            }

            Button {
                engine.convertMismatchedFps()
            } label: {
                Label("Datei(en) auf \(fpsText(engine.fps)) fps konvertieren",
                      systemImage: "arrow.triangle.2.circlepath")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)

            Text("Erzeugt Kopien neben den Originalen (praktisch verlustfrei, Timecode bleibt "
                 + "erhalten). Dauert je nach Dateigröße — grob im 10-Minuten-Bereich pro GB.")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.brandSecondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(.brandSecondary.opacity(0.4), lineWidth: 1))
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

// MARK: - Quelldateien-Panel (rechter Inspector)

/// Zeigt ALLE gescannten Quellen. Die Checkbox entscheidet, ob eine Datei fuer
/// Canvas UND Analyse existiert — deaktivierte Quellen werden der Engine gar nicht
/// erst uebergeben (siehe EngineController.activeCams/activeMics).
// MARK: - Inspector-Panel (Reiter Quellen / Personen)

/// Rechtes Panel mit zwei Reitern. „Quellen" ist die Datei-Sicht (Cams/Mics
/// aktivieren, umbenennen), „Personen" gruppiert denselben Graphen nach Person.
struct InspectorPanel: View {
    @State private var tab: Tab = .sources

    enum Tab: String, CaseIterable, Identifiable {
        case sources = "Quellen"
        case persons = "Personen"
        var id: String { rawValue }
    }

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                ForEach(Tab.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(8)

            Divider()

            switch tab {
            case .sources: SourcesInspector()
            case .persons: PersonsInspector()
            }
        }
    }
}

// MARK: - Personen-Inspector

/// Zeigt denselben Cam↔Mic-Graphen, aber gruppiert nach Person (= Mic). Zuordnen
/// passiert weiterhin per Drag&Drop auf dem Canvas; hier sieht man das Ergebnis
/// aus Personen-Sicht — die Grundlage fuer spaetere Personen-Features (Rollen,
/// Bildgroessen-Wechsel Close↔Totale derselben Person).
struct PersonsInspector: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        Form {
            if engine.persons.isEmpty {
                Section {
                    Text("Noch keine Mikrofone — pro importiertem Mic wird automatisch "
                         + "eine Person angelegt.")
                        .foregroundStyle(.secondary)
                }
            }

            ForEach(engine.persons) { person in
                Section(person.name) {
                    Label(micFilename(person.micId), systemImage: "mic.fill")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    let cams = person.camIds.compactMap { id in
                        engine.cameraInfos.first { $0.id == id }
                    }
                    if cams.isEmpty {
                        Label("Keine Kamera zugeordnet", systemImage: "video.slash")
                            .font(.caption)
                            .foregroundStyle(.brandSecondary)
                    } else {
                        ForEach(cams) { cam in
                            HStack(spacing: 8) {
                                Image(systemName: "video.fill").foregroundStyle(.tertiary)
                                Text(cam.displayName).lineLimit(1).truncationMode(.middle)
                                if cam.isWide {
                                    Spacer()
                                    Text("Totale")
                                        .font(.caption2)
                                        .foregroundStyle(.brandSecondary)
                                }
                            }
                        }
                    }
                }
            }

            if !engine.sharedWideCams.isEmpty {
                Section("Geteilte Totalen") {
                    ForEach(engine.sharedWideCams) { cam in
                        Label(cam.displayName, systemImage: "rectangle.split.2x1")
                    }
                    Text("Ohne Mic — steht allen Personen als Ausweich-Einstellung offen.")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            if !engine.ignoredCams.isEmpty {
                Section("Ohne Person") {
                    ForEach(engine.ignoredCams) { cam in
                        Label(cam.displayName, systemImage: "video.fill")
                            .foregroundStyle(.secondary)
                    }
                    Text("Kein Mic, keine Totale — wird nicht analysiert.")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .formStyle(.grouped)
    }

    private func micFilename(_ id: Int) -> String {
        engine.micInfos.first { $0.id == id }?.filename ?? "—"
    }
}

struct SourcesInspector: View {
    @EnvironmentObject var engine: EngineController
    /// Welche Zeile wird gerade umbenannt — "cam-3" / "mic-1" (Cams und Mics haben
    /// getrennte ID-Raeume, deshalb ein zusammengesetzter Schluessel).
    @State private var editing: String?
    @State private var draft = ""
    @FocusState private var nameFocused: Bool

    var body: some View {
        Form {
            Section("Kameras") {
                if engine.cameraInfos.isEmpty {
                    Text("Keine").foregroundStyle(.secondary)
                }
                ForEach(engine.cameraInfos) { cam in
                    sourceRow(key: "cam-\(cam.id)",
                              name: cam.displayName,
                              duration: cam.durationSeconds,
                              icon: "video.fill",
                              detail: fpsDetail(cam),
                              detailIsWarning: cam.included && (cam.fps <= 0 || abs(cam.fps - engine.fps) > 0.01),
                              isOn: Binding(get: { cam.included },
                                            set: { engine.setCamIncluded(cam.id, $0) }),
                              rename: { engine.renameCam(cam.id, to: $0) })
                }
            }

            Section("Mikrofone") {
                if engine.micInfos.isEmpty {
                    Text("Keine").foregroundStyle(.secondary)
                }
                ForEach(engine.micInfos) { mic in
                    sourceRow(key: "mic-\(mic.id)",
                              name: mic.displayName,
                              duration: mic.durationSeconds,
                              icon: "mic.fill",
                              isOn: Binding(get: { mic.included },
                                            set: { engine.setMicIncluded(mic.id, $0) }),
                              rename: { engine.renameMic(mic.id, to: $0) })
                }
            }
        }
        .formStyle(.grouped)
    }

    /// „25 fps" bzw. „30 fps ≠ 25" wenn die Timeline-FPS abweicht.
    private func fpsDetail(_ cam: CameraInfo) -> String {
        guard cam.fps > 0 else { return "FPS unlesbar" }
        let f = cam.fps.rounded() == cam.fps ? String(Int(cam.fps)) : String(format: "%.2f", cam.fps)
        if abs(cam.fps - engine.fps) > 0.01 {
            let t = engine.fps.rounded() == engine.fps ? String(Int(engine.fps)) : String(format: "%.2f", engine.fps)
            return "\(f) fps ≠ \(t)"
        }
        return "\(f) fps"
    }

    @ViewBuilder
    private func sourceRow(key: String, name: String, duration: Double, icon: String,
                           detail: String? = nil, detailIsWarning: Bool = false,
                           isOn: Binding<Bool>,
                           rename: @escaping (String) -> Void) -> some View {
        HStack(spacing: 8) {
            // `Toggle` MIT Label wuerde die ganze Zeile klickbar machen — dann
            // toggelt jeder Klick auf Name/Stift/Icon die Checkbox. `labelsHidden`
            // rendert nur die Box, der Rest bleibt unberuehrt.
            Toggle("", isOn: isOn)
                .labelsHidden()
                .toggleStyle(.checkbox)

            if editing == key {
                TextField("Name", text: $draft)
                    .textFieldStyle(.roundedBorder)
                    .focused($nameFocused)
                    .onSubmit {
                        rename(draft)
                        editing = nil
                    }
                    .onExitCommand { editing = nil }
                    .task {
                        try? await Task.sleep(for: .milliseconds(50))
                        nameFocused = true
                    }
            } else {
                VStack(alignment: .leading, spacing: 1) {
                    Text(name)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    HStack(spacing: 6) {
                        Text(formatDuration(duration))
                        if let detail {
                            Text("·")
                            Text(detail)
                                .foregroundStyle(detailIsWarning ? .brandSecondary : .secondary)
                        }
                    }
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }

                Button {
                    draft = name
                    editing = key
                } label: {
                    Image(systemName: "pencil")
                        .font(.caption)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .help("Umbenennen")

                Spacer()

                // Auf einen Blick: Kamera oder Mikrofon. Wird wichtiger, sobald
                // ein „Personen"-Reiter dazukommt.
                Image(systemName: icon)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
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
            }
        }
    }
}

// MARK: - Camera Card

struct CameraCard: View {
    let camIndex: Int
    @EnvironmentObject var engine: EngineController
    @State private var isTargeted = false
    private var camera: CameraInfo {
        guard camIndex < engine.cameraInfos.count else { return CameraInfo(id: -1, filename: "", path: "", displayName: "", thumbnailPath: nil, durationSeconds: 0, assignedMics: []) }
        return engine.cameraInfos[camIndex]
    }

    private var assignedMics: [MicInfo] {
        camera.assignedMics.compactMap { micIdx in
            engine.micInfos.first { $0.id == micIdx }
        }
    }

    /// Zentral über den EngineController → exklusiv (nur eine Karte) + abwählbar.
    private var isSelected: Bool { engine.selectedCamId == camera.id }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScrubbableThumbnail(
                videoPath: camera.path,
                initialThumbnailPath: camera.thumbnailPath,
                durationSeconds: camera.durationSeconds
            )
            .overlay(alignment: .topTrailing) {
                if camera.isWide {
                    Label("Totale", systemImage: "rectangle.split.2x1")
                        .font(.caption2.weight(.medium))
                        .lineLimit(1)
                        .fixedSize()          // sonst wird „Totale" zu „Tota" gestaucht
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .background(Color.brandSecondary)
                        .foregroundStyle(.black)
                        .clipShape(Capsule())
                        .padding(6)
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                // Umbenannt wird ausschliesslich im Quelldateien-Panel (Stift-Symbol).
                // Auf dem Canvas waere es eine zweite, versteckte Mechanik.
                Text(camera.displayName)
                    .font(.headline)

                Text(formatDuration(camera.durationSeconds))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if !assignedMics.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(assignedMics) { mic in
                            MicPill(mic: mic, removable: true, onRemove: {
                                engine.unassignMic(mic.id)
                            })
                        }
                    }
                    .padding(.top, 4)
                } else if camera.isWide {
                    // Totale braucht kein Mic — sie wird bei Simultan-Reaktionen genutzt.
                    Text("Totale — kein Mic nötig")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.vertical, 8)
                } else {
                    // Ohne Mic UND ohne Totale-Tag ist die Cam fuer die Analyse irrelevant.
                    // Das sagen wir offen, statt sie (wie frueher) still zur Totale zu machen.
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Mic hierher ziehen")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                        Label("Wird ignoriert — kein Mic, kein Totale-Tag",
                              systemImage: "exclamationmark.circle")
                            .font(.caption2)
                            .foregroundStyle(.brandSecondary)
                    }
                    .padding(.vertical, 6)
                }
            }
            .padding(10)
        }
        .background(isTargeted ? Color.brandAccent.opacity(0.15) : Color(.controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(isTargeted ? Color.brandAccent : Color(.separatorColor), lineWidth: isTargeted ? 2 : 0.5)
        )
        .onDrop(of: [UTType.plainText], isTargeted: $isTargeted) { providers in
            guard let provider = providers.first else { return false }
            provider.loadItem(forTypeIdentifier: UTType.plainText.identifier, options: nil) { item, _ in
                guard let data = item as? Data,
                      let str = String(data: data, encoding: .utf8),
                      let micIndex = Int(str) else { return }
                DispatchQueue.main.async {
                    engine.assignMic(micIndex, toCamera: camera.id)
                }
            }
            return true
        }
        .contentShape(Rectangle())
        .onTapGesture { engine.selectedCamId = camera.id }
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(isSelected ? Color.brandAccent : .clear, lineWidth: 2)
        )
        .contextMenu {
            Toggle(isOn: Binding(get: { camera.isWide },
                                 set: { engine.setCamWide(camera.id, $0) })) {
                Label("Als Totale markieren", systemImage: "rectangle.split.2x1")
            }
        }
        // Kein Entf/Backspace mehr: Quellen werden im Quelldateien-Panel per Checkbox
        // deaktiviert (reversibel) statt destruktiv aus dem Projekt geloescht.
        // Die Auswahl bleibt — sie traegt die Outline und spaeter die Detailanzeige.
    }
}

// MARK: - Mic Pill

struct MicPill: View {
    let mic: MicInfo
    var removable: Bool = false
    var onRemove: (() -> Void)?
    @EnvironmentObject var engine: EngineController

    private var isPlaying: Bool { engine.playingMicId == mic.id }

    private var liveName: String {
        engine.micInfos.first { $0.id == mic.id }?.displayName ?? mic.displayName
    }

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "mic.fill")
                .font(.caption2)

            // Umbenennen passiert nur im Quelldateien-Panel (Stift-Symbol).
            Text(liveName)
                .font(.caption)
                .lineLimit(1)

            if removable {
                Button {
                    onRemove?()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.caption2)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.black.opacity(0.55))
            }

            Button {
                engine.toggleMicPreview(mic)
            } label: {
                Image(systemName: isPlaying ? "pause.circle.fill" : "play.circle")
                    .font(.caption2)
            }
            .buttonStyle(.plain)
            .foregroundStyle(isPlaying ? .black : .black.opacity(0.55))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        // Voller Lime-Akzent → Text/Icons müssen dunkel sein (wie die Website:
        // --primary-foreground ist near-black auf dem Akzent).
        .foregroundStyle(.black)
        .background(.brandAccent)
        .clipShape(Capsule())
        .onDrag {
            NSItemProvider(object: String(mic.id) as NSString)
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

// MARK: - Preset Picker

struct PresetPicker: View {
    @EnvironmentObject var engine: EngineController
    @State private var showSaveSheet = false
    @State private var newPresetName = ""

    /// Welches Preset entspricht EXAKT den aktuellen Parametern?
    /// Bewusst berechnet statt gemerkt: Verstellt man nach der Auswahl einen Wert,
    /// verschwindet das Häkchen von selbst. Ein gemerkter Zustand würde dann lügen.
    private var activePresetId: String? {
        PresetManager.shared.listPresets().first {
            PresetManager.shared.loadPreset($0.id) == engine.params
        }?.id
    }

    var body: some View {
        Menu {
            // Picker (inline) statt Buttons → native Häkchen bei der aktiven Auswahl.
            Picker("Preset", selection: Binding(
                get: { activePresetId },
                set: { newId in
                    if let id = newId, let params = PresetManager.shared.loadPreset(id) {
                        engine.params = params
                    }
                }
            )) {
                ForEach(PresetManager.shared.listPresets()) { preset in
                    Text(preset.name).tag(preset.id as String?)
                }
            }
            .pickerStyle(.inline)

            Divider()

            Button("Preset speichern...") {
                newPresetName = ""
                showSaveSheet = true
            }

            Button("Preset importieren...") {
                if let (_, params) = PresetManager.shared.importPreset() {
                    engine.params = params
                }
            }

            Button("Preset exportieren...") {
                _ = PresetManager.shared.exportPreset(engine.params, name: "Mein Preset")
            }
        } label: {
            Label("Presets", systemImage: "slider.horizontal.3")
                .font(.caption)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .sheet(isPresented: $showSaveSheet) {
            VStack(spacing: 16) {
                Text("Preset speichern")
                    .font(.headline)
                TextField("Preset-Name", text: $newPresetName)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 250)
                HStack {
                    Button("Abbrechen") { showSaveSheet = false }
                    Button("Speichern") {
                        guard !newPresetName.isEmpty else { return }
                        _ = PresetManager.shared.savePreset(name: newPresetName, params: engine.params)
                        showSaveSheet = false
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(newPresetName.isEmpty)
                }
            }
            .padding(24)
        }
    }
}

// MARK: - Parameter Form

struct ParameterForm: View {
    @EnvironmentObject var engine: EngineController
    @AppStorage("expertMode") private var expertMode = false

    var body: some View {
        Form {
            Section("Schnittregeln") {
                ParameterRow(label: "Min. Schnittlänge (s)", value: $engine.params.minShot, range: 0.5...10, help: ParamHelp.minShot)
                ParameterRow(label: "Max. Schnittlänge (s)", value: $engine.params.maxShot, range: 1...60, help: ParamHelp.maxShot)
                if expertMode {
                    ParameterRow(label: "Cutaway-Länge (s)", value: $engine.params.reactionDur, range: 0.5...5, help: ParamHelp.reactionDur)
                    ParameterRow(label: "Cleanup-Mindestlänge (s)", value: $engine.params.cleanupDur, range: 0.1...5, help: ParamHelp.cleanupDur)
                }
            }

            if expertMode {
                Section("Sprecher-Erkennung") {
                    ParameterRow(label: "Schwelle (dB)", value: $engine.params.thresholdDb, range: 0.5...20, help: ParamHelp.thresholdDb)
                    ParameterRow(label: "Min. Segmentlänge (s)", value: $engine.params.minEdit, range: 0.1...5, help: ParamHelp.minEdit)
                    ParameterRow(label: "Wechsel-Verzögerung (s)", value: $engine.params.changeDelay, range: 0...2, help: ParamHelp.changeDelay)
                }

                Section("Cutaway-Typen") {
                    HelpToggle("Kopfnicken", isOn: $engine.params.noddingEnabled, help: ParamHelp.noddingEnabled)
                    if engine.params.noddingEnabled {
                        ParameterRow(label: "Min. Konfidenz (%)", value: Binding(
                            get: { engine.params.minConf * 100 },
                            set: { engine.params.minConf = $0 / 100 }
                        ), range: 0...100, help: ParamHelp.minConf)
                    }

                    HelpToggle("Sprachreaktionen", isOn: $engine.params.speakingEnabled, help: ParamHelp.speakingEnabled)
                    if engine.params.speakingEnabled {
                        ParameterRow(label: "Rise (dB)", value: $engine.params.riseDb, range: 1...20, help: ParamHelp.riseDb)
                        ParameterRow(label: "Max. Cutaway-Dauer (s)", value: $engine.params.speakingMaxDur, range: 0.5...10, help: ParamHelp.speakingMaxDur)
                    }

                    HelpToggle("Stille-Cutaways", isOn: $engine.params.pauseCutawayEnabled, help: ParamHelp.pauseCutawayEnabled)
                    if engine.params.pauseCutawayEnabled {
                        ParameterRow(label: "Min. Pausenlänge (s)", value: $engine.params.pauseCutawayMinPause, range: 0.5...10, help: ParamHelp.pauseCutawayMinPause)
                    }

                    HelpToggle("Ungünstige Cutaways verschieben (CLIP)", isOn: $engine.params.clipFilterEnabled, help: ParamHelp.clipFilterEnabled)
                }

                Section("Cutaway-Feintuning") {
                    ParameterRow(label: "Pre-Roll (Frames)", value: Binding(
                        get: { Double(engine.params.preRoll) },
                        set: { engine.params.preRoll = Int($0) }
                    ), range: 0...50, help: ParamHelp.preRoll)
                    HStack {
                        HelpLabel("Zufallsfaktor", help: ParamHelp.randomness)
                        Spacer()
                        Slider(value: $engine.params.randomness, in: 0...0.5, step: 0.05)
                            .frame(width: 100)
                        Text(String(format: "%.2f", engine.params.randomness))
                            .font(.system(.caption, design: .monospaced))
                            .frame(width: 35)
                    }
                }
            }

            Section("Pausen-Trimming") {
                HelpToggle("Pausen kürzen", isOn: $engine.params.pauseTrimEnabled, help: ParamHelp.pauseTrimEnabled)
                if engine.params.pauseTrimEnabled {
                    ParameterRow(label: "Max. Pause (s)", value: $engine.params.maxPause, range: 0.1...3, help: ParamHelp.maxPause)
                    if expertMode {
                        Picker(selection: $engine.params.pauseCutMode) {
                            Text("Middle").tag("middle")
                            Text("L-Cut").tag("l-cut")
                            Text("J-Cut").tag("j-cut")
                            Text("Zufall").tag("random")
                        } label: {
                            HelpLabel("Schnittmodus", help: ParamHelp.pauseCutMode)
                        }
                        ParameterRow(label: "Stille-Schwelle (dB)", value: $engine.params.pauseSilenceDb, range: -80...(-10), help: ParamHelp.pauseSilenceDb)
                    }
                }
            }

            if expertMode {
                Section("Crossbleed-Filter") {
                    HelpToggle("Crossbleed-Gate", isOn: $engine.params.crossbleedGateEnabled, help: ParamHelp.crossbleedGateEnabled)
                    if engine.params.crossbleedGateEnabled {
                        ParameterRow(label: "Dämpfung (dB)", value: $engine.params.gateFloor, range: -60...(-5), help: ParamHelp.gateFloor)
                        ParameterRow(label: "Hysterese (dB)", value: $engine.params.gateHysteresis, range: 0.5...10, help: ParamHelp.gateHysteresis)
                        ParameterRow(label: "Fenster (ms)", value: $engine.params.gateWindow, range: 20...500, help: ParamHelp.gateWindow)
                        ParameterRow(label: "Attack (ms)", value: $engine.params.gateAttack, range: 1...200, help: ParamHelp.gateAttack)
                        ParameterRow(label: "Release (ms)", value: $engine.params.gateRelease, range: 10...500, help: ParamHelp.gateRelease)
                        ParameterRow(label: "Gleichzeitig-Schwelle (dB)", value: $engine.params.gateBothThreshold, range: 0.5...10, help: ParamHelp.gateBothThreshold)
                        HelpToggle("Gate-Audio in Timeline", isOn: $engine.params.gateUseFiltered, help: ParamHelp.gateUseFiltered)
                    }
                }

                Section("Totale") {
                    ParameterRow(label: "Min. Simultandauer (s)", value: $engine.params.totaleSimulDur, range: 0.5...10, help: ParamHelp.totaleSimulDur)
                }

                Section("Allgemein") {
                    HStack {
                        HelpLabel("FPS", help: ParamHelp.fps)
                        Spacer()
                        TextField("", value: $engine.fps, format: .number)
                            .frame(width: 60)
                            .textFieldStyle(.roundedBorder)
                    }
                }
            }
        }
        .formStyle(.grouped)
    }
}

// MARK: - Parameter Row

struct ParameterRow: View {
    let label: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    var help: String = ""

    var body: some View {
        HStack {
            Text(label)
            if !help.isEmpty { HelpBadge(text: help) }
            Spacer()
            TextField("", value: $value, format: .number.precision(.fractionLength(1)))
                .frame(width: 60)
                .textFieldStyle(.roundedBorder)
        }
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

            if !engine.logMessages.isEmpty {
                DisclosureGroup("Log") {
                    ScrollViewReader { proxy in
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 2) {
                                ForEach(Array(engine.logMessages.suffix(80).enumerated()), id: \.offset) { idx, msg in
                                    Text(msg)
                                        .font(.system(.caption, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                        .textSelection(.enabled)
                                        .id(idx)
                                }
                            }
                            .padding(8)
                        }
                        .frame(height: 180)
                        .onChange(of: engine.logMessages.count) { _, _ in
                            proxy.scrollTo(engine.logMessages.count - 1, anchor: .bottom)
                        }
                    }
                }
                .frame(width: 500)
            }

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
