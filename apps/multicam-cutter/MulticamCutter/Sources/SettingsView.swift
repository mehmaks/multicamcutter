import SwiftUI

struct SettingsView: View {
    private enum Tab: Hashable {
        case general, clip, nodding, license
    }

    var body: some View {
        TabView {
            GeneralSettingsTab()
                .tabItem {
                    Label("Allgemein", systemImage: "gearshape")
                }
                .tag(Tab.general)

            ClipSettingsTab()
                .tabItem {
                    Label("CLIP", systemImage: "sparkles")
                }
                .tag(Tab.clip)

            NoddingSettingsTab()
                .tabItem {
                    Label("Nodding", systemImage: "chevron.up.chevron.down")
                }
                .tag(Tab.nodding)

            LicenseSettingsTab()
                .tabItem {
                    Label("Lizenz", systemImage: "key")
                }
                .tag(Tab.license)
        }
        // Höhe am größten Tab orientiert (Nodding: großer JSON-Editor).
        .frame(width: 500, height: 520)
        // Ohne das nutzen die Tab-Icons/Labels den blauen System-Akzent statt Lime
        // (ContentView/About haben den Tint schon, der Settings-Scene fehlte er).
        .tint(.brandAccent)
    }
}

// MARK: - Nodding (roher JSON-Editor der Detektor-Muster, Expert)

struct NoddingSettingsTab: View {
    @EnvironmentObject var engine: EngineController

    struct PatternRow: Identifiable {
        let id = UUID()
        let name: String
        let description: String
        let enabled: Bool
    }

    @State private var text = ""              // rohe JSON — SSOT für Toggles UND Editor
    @State private var patterns: [PatternRow] = []
    @State private var source = "default"     // "user" | "default"
    @State private var showRaw = false
    @State private var message: String?
    @State private var messageIsError = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Nodding-Muster").font(.headline)
                    Spacer()
                    Text(source == "user" ? "Angepasst" : "Standard")
                        .font(.caption2)
                        .foregroundStyle(source == "user" ? .brandSecondary : .secondary)
                }
                Text("Aktiviere oder deaktiviere die einzelnen Erkennungsmuster für das "
                     + "Kopfnicken. Feintuning der Schwellen unten in der rohen Konfiguration.")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                // ── Pattern-Toggles ──
                VStack(spacing: 0) {
                    ForEach(patterns) { p in
                        HStack(alignment: .top, spacing: 10) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(p.name).font(.system(size: 13, weight: .medium))
                                if !p.description.isEmpty {
                                    Text(p.description).font(.caption2).foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                            Spacer(minLength: 8)
                            Toggle("", isOn: Binding(get: { p.enabled }, set: { setEnabled(p, $0) }))
                                .labelsHidden().toggleStyle(.switch)
                        }
                        .padding(.vertical, 8)
                        .overlay(alignment: .bottom) {
                            if p.id != patterns.last?.id {
                                Rectangle().fill(.quaternary).frame(height: 0.5)
                            }
                        }
                    }
                    if patterns.isEmpty {
                        Text("Keine Muster gefunden.").font(.caption).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
                    }
                }

                // ── Rohe Konfiguration (Expert) ──
                DisclosureGroup("Rohe Konfiguration bearbeiten", isExpanded: $showRaw) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Ganze nodding_patterns.json inkl. Globals + Filter/Confidence. "
                             + "Bei defektem JSON nutzt die Analyse automatisch die Defaults.")
                            .font(.caption2).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        TextEditor(text: $text)
                            .font(.system(.caption, design: .monospaced))
                            .frame(height: 220)
                            .padding(4)
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
                        HStack {
                            Button("Speichern") { saveRaw() }.buttonStyle(.borderedProminent)
                            Button("Auf Standard zurücksetzen") { reset() }.disabled(source != "user")
                        }
                    }
                    .padding(.top, 4)
                }
                .font(.system(size: 13, weight: .medium))

                HStack {
                    if let message {
                        Label(message, systemImage: messageIsError ? "xmark.octagon.fill" : "checkmark")
                            .font(.caption).foregroundStyle(messageIsError ? .red : .green).lineLimit(1)
                    }
                    Spacer()
                    Text("Gilt beim nächsten Analyse-Lauf.")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
            .padding()
        }
        .task { await load() }
    }

    // MARK: Laden / Parsen
    private func load() async {
        if let p = await engine.getNoddingPatterns() {
            text = p.content
            source = p.source
        }
        parsePatterns()
        message = nil
    }

    private func parsePatterns() {
        guard let data = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pats = obj["patterns"] as? [[String: Any]] else { patterns = []; return }
        patterns = pats.map {
            PatternRow(name: $0["name"] as? String ?? "?",
                       description: $0["description"] as? String ?? "",
                       enabled: $0["enabled"] as? Bool ?? true)
        }
    }

    // MARK: Toggle (formatschonende String-Chirurgie statt Neu-Serialisierung)
    private func setEnabled(_ p: PatternRow, _ on: Bool) {
        guard let newText = toggledJSON(text, pattern: p.name, to: on) else {
            message = "Konnte \(p.name) nicht umschalten — bitte unten im JSON ändern."
            messageIsError = true
            return
        }
        text = newText
        if let err = engine.saveNoddingPatterns(newText) { message = err; messageIsError = true; return }
        source = "user"; message = nil
        parsePatterns()
    }

    /// Flippt das ERSTE `enabled` nach `"name": "<name>"` (= das Pattern-enabled; das
    /// dynamic_threshold.enabled kommt im JSON später) — ohne die Datei zu reformatieren.
    private func toggledJSON(_ raw: String, pattern name: String, to on: Bool) -> String? {
        guard let nameR = raw.range(of: "\"name\": \"\(name)\"") else { return nil }
        guard let enKey = raw.range(of: "\"enabled\"", range: nameR.upperBound..<raw.endIndex) else { return nil }
        let search = enKey.upperBound..<raw.endIndex
        let tR = raw.range(of: "true", range: search)
        let fR = raw.range(of: "false", range: search)
        let valR: Range<String.Index>?
        switch (tR, fR) {
        case let (t?, f?): valR = t.lowerBound < f.lowerBound ? t : f
        case let (t?, nil): valR = t
        case let (nil, f?): valR = f
        default: valR = nil
        }
        guard let r = valR else { return nil }
        return raw.replacingCharacters(in: r, with: on ? "true" : "false")
    }

    // MARK: Rohe Speicherung / Reset
    private func saveRaw() {
        if let err = engine.saveNoddingPatterns(text) {
            message = err; messageIsError = true
        } else {
            source = "user"; message = "Gespeichert"; messageIsError = false
            parsePatterns()
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) {
                if message == "Gespeichert" { message = nil }
            }
        }
    }

    private func reset() {
        engine.resetNoddingPatterns()
        Task { await load() }
    }
}

// MARK: - CLIP (Modell-Status + Prompt-Editor)

struct ClipSettingsTab: View {
    @EnvironmentObject var engine: EngineController

    @State private var ignoreText = ""
    @State private var neutralText = ""
    @State private var source = "default"          // "user" | "default"
    @State private var modelInstalled: Bool?       // nil = wird geprüft
    @State private var justSaved = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                modelSection
                Divider()
                promptSection
            }
            .padding()
        }
        .task { await load() }
        // Nach Abschluss eines Downloads (Sheet schließt) den Status neu prüfen.
        .onChange(of: engine.isDownloadingClip) { _, downloading in
            if !downloading { Task { modelInstalled = await engine.checkClipModel().0 } }
        }
    }

    // ── Modell-Status + Download ──
    private var modelSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Bilderkennung (CLIP)").font(.headline)
            Text("Optionales Modell (≈ 581 MB). Filtert ungünstige Cutaway-Frames "
                 + "(z. B. Trinken). Ohne Modell läuft alles andere normal.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                switch modelInstalled {
                case .some(true):
                    Label("Modell geladen", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                case .some(false):
                    Label("Modell nicht geladen", systemImage: "arrow.down.circle")
                        .foregroundStyle(.secondary)
                    Button("Herunterladen") { engine.downloadClipModel() }
                        .disabled(engine.isDownloadingClip)
                case .none:
                    SwiftUI.ProgressView().controlSize(.small)
                    Text("wird geprüft …").font(.caption).foregroundStyle(.secondary)
                }
            }

            if engine.isDownloadingClip {
                SwiftUI.ProgressView(value: Double(engine.clipDone),
                                     total: Double(max(engine.clipTotal, 1)))
                    .frame(maxWidth: 280)
            }
            if let err = engine.clipError {
                Text(err).font(.caption).foregroundStyle(.red)
            }
        }
    }

    // ── Prompt-Editor ──
    private var promptSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Filter-Prompts").font(.headline)
                Spacer()
                Text(source == "user" ? "Angepasst" : "Standard")
                    .font(.caption2)
                    .foregroundStyle(source == "user" ? .brandSecondary : .secondary)
            }
            Text("Ein Prompt pro Zeile, auf Englisch (so erwartet es CLIP). "
                 + "Ignorieren = solche Bilder werden als Cutaway vermieden, "
                 + "Neutral = ausdrücklich erlaubt.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            promptEditor("IGNORIEREN", text: $ignoreText)
            promptEditor("NEUTRAL", text: $neutralText)

            HStack {
                Button("Speichern") { save() }
                    .buttonStyle(.borderedProminent)
                Button("Auf Standard zurücksetzen") { reset() }
                    .disabled(source != "user")
                Spacer()
                if justSaved {
                    Label("Gespeichert", systemImage: "checkmark")
                        .font(.caption).foregroundStyle(.green)
                }
            }
            Text("Gilt beim nächsten Analyse-Lauf.")
                .font(.caption2).foregroundStyle(.tertiary)
        }
    }

    private func promptEditor(_ title: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption2).fontWeight(.bold).foregroundStyle(.secondary)
            TextEditor(text: text)
                .font(.system(.caption, design: .monospaced))
                .frame(height: 84)
                .padding(4)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
        }
    }

    // ── Laden / Speichern ──
    private func load() async {
        if let p = await engine.getClipPrompts() {
            ignoreText = p.ignore.joined(separator: "\n")
            neutralText = p.neutral.joined(separator: "\n")
            source = p.source
        }
        modelInstalled = await engine.checkClipModel().0
    }

    private func lines(_ s: String) -> [String] {
        s.split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    private func save() {
        engine.saveClipPrompts(ignore: lines(ignoreText), neutral: lines(neutralText))
        source = "user"
        justSaved = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { justSaved = false }
    }

    private func reset() {
        engine.resetClipPrompts()
        Task { await load() }
    }
}

// MARK: - Allgemein

struct GeneralSettingsTab: View {
    // Expertenmodus-Toggle entfernt: obsolet, seit die Parameter im Wizard über
    // „Experteneinstellungen" ein-/ausklappen (Variante C).
    // Denselben Key liest ScrubbableThumbnail — Umschalten wirkt live.
    @AppStorage("thumbnailAutoContrast") private var thumbnailAutoContrast = false

    var body: some View {
        Form {
            Section("Darstellung") {
                Toggle("Kontrast der Vorschaubilder anheben", isOn: $thumbnailAutoContrast)
                Text("Hebt flaches Log-Material in den Kamera-Vorschauen an (auch beim "
                     + "Scrubbing). Rein kosmetisch — Analyse und Export bleiben unberührt.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}

// MARK: - Lizenz

struct LicenseSettingsTab: View {
    // Optimistischer Start: letzten validierten Stand aus dem Cache zeigen, damit der
    // Tab beim Neu-Öffnen nicht erst „inaktiv, wird geprüft" flackert. Die echte
    // Prüfung läuft in onAppear im Hintergrund und aktualisiert dann.
    @State private var licenseStatus: String = {
        let d = UserDefaults.standard
        if d.bool(forKey: "lic.isValid") {
            return d.bool(forKey: "lic.isGrace") ? "Lizenz aktiv (offline)" : "Lizenz aktiv"
        }
        return "Wird geprüft..."
    }()
    @State private var licenseEmail: String = UserDefaults.standard.string(forKey: "lic.email") ?? ""
    @State private var subLine: String = UserDefaults.standard.string(forKey: "lic.subLine") ?? ""
    @State private var subIsWarning: Bool = UserDefaults.standard.bool(forKey: "lic.subWarn")
    @State private var isValid: Bool = UserDefaults.standard.bool(forKey: "lic.isValid")
    @State private var isGrace: Bool = UserDefaults.standard.bool(forKey: "lic.isGrace")
    @State private var isChecking: Bool = false
    @State private var isActivating: Bool = false
    @State private var licenseKey: String = ""
    @State private var statusCode: String = ""   // roher Server-Status (z.B. activation_limit)
    @State private var showDeactivateConfirm = false

    var body: some View {
        Form {
            Section {
                HStack {
                    Image(systemName: isValid ? "checkmark.seal.fill" : "xmark.seal.fill")
                        .foregroundStyle(isValid ? (isGrace ? .brandSecondary : .green) : .red)
                        .font(.title2)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(licenseStatus)
                            .font(.headline)
                        if !licenseEmail.isEmpty {
                            Text(licenseEmail)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        if !subLine.isEmpty {
                            Text(subLine)
                                .font(.caption)
                                .foregroundStyle(subIsWarning ? .brandSecondary : .secondary)
                        }
                    }
                    Spacer()
                    if isChecking || isActivating {
                        SwiftUI.ProgressView().controlSize(.small)
                    } else if isValid {
                        Button("Deaktivieren") {
                            showDeactivateConfirm = true
                        }
                        .controlSize(.small)
                    }
                }
            }

            // Key-Eingabe nur zeigen, wenn keine aktive Lizenz vorliegt
            if !isValid {
                Section("Lizenzschlüssel") {
                    TextField("XXXX-XXXX-XXXX-XXXX", text: $licenseKey)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(.body, design: .monospaced))
                        .onSubmit { activateKey() }

                    Button("Aktivieren") {
                        activateKey()
                    }
                    .disabled(licenseKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isActivating)

                    Text("Den Schlüssel bekommst du nach dem Kauf per E-Mail.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                // Umzug: Lizenz ist auf einem anderen Gerät aktiv
                if statusCode == "activation_limit" {
                    Section {
                        Text("Diese Lizenz ist bereits auf einem anderen Gerät aktiv.")
                            .font(.caption)
                            .foregroundStyle(.brandSecondary)
                        Button("Auf dieses Gerät umziehen") {
                            migrate()
                        }
                        .disabled(isActivating || licenseKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }

                Section {
                    Button("Lizenz erneut prüfen") {
                        checkLicense()
                    }
                    .disabled(isChecking || isActivating)
                }
            }
        }
        .formStyle(.grouped)
        .padding()
        // Deaktivieren gibt einen Server-Slot frei → nicht versehentlich auslösen.
        .confirmationDialog("Lizenz auf diesem Gerät deaktivieren?",
                            isPresented: $showDeactivateConfirm,
                            titleVisibility: .visible) {
            Button("Deaktivieren", role: .destructive) { deactivate() }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Der Geräte-Slot wird auf dem Server wieder freigegeben. Du kannst die "
                 + "Lizenz jederzeit mit deinem Lizenzschlüssel erneut aktivieren — auch "
                 + "auf einem anderen Mac.")
        }
        .onAppear {
            checkLicense()
        }
    }

    private func checkLicense() {
        isChecking = true
        // Lizenzprüfung über die Engine (Python)
        Task {
            let result = await runEngineCommand(["--check-license"])
            await MainActor.run {
                parseLicenseResult(result)
                isChecking = false
            }
        }
    }

    private func activateKey() {
        let key = licenseKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }
        isActivating = true
        licenseStatus = "Wird aktiviert..."
        Task {
            let result = await runEngineCommand(["--set-key", key])
            await MainActor.run {
                parseLicenseResult(result)
                isActivating = false
                if isValid { licenseKey = "" }   // Feld nach Erfolg leeren
            }
        }
    }

    private func deactivate() {
        isChecking = true
        // Löscht lokal + gibt best-effort den Server-Slot frei (Self-Leave).
        Task {
            let result = await runEngineCommand(["--clear-license"])
            await MainActor.run {
                parseLicenseResult(result)
                isChecking = false
            }
        }
    }

    private func migrate() {
        let key = licenseKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }
        isActivating = true
        licenseStatus = "Wird umgezogen..."
        // Takeover: andere Geräte freigeben, dann auf diesem Gerät aktivieren.
        Task {
            let result = await runEngineCommand(["--migrate-key", key])
            await MainActor.run {
                parseLicenseResult(result)
                isActivating = false
                if isValid { licenseKey = "" }
            }
        }
    }

    private func parseLicenseResult(_ output: String) {
        // Engine gibt JSON zurück: {"valid", "email", "expires", "grace", "error"}
        // Bei Multi-Line-Output die letzte JSON-Zeile nehmen.
        let lastLine = output.split(separator: "\n").last.map(String.init) ?? output
        guard let data = lastLine.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            licenseStatus = "Keine Lizenz gefunden"
            isValid = false
            isGrace = false
            subLine = ""
            statusCode = ""
            return
        }

        isValid = json["valid"] as? Bool ?? false
        isGrace = json["grace"] as? Bool ?? false
        statusCode = json["status"] as? String ?? ""
        licenseEmail = json["email"] as? String ?? ""

        if isValid {
            licenseStatus = isGrace ? "Lizenz aktiv (offline)" : "Lizenz aktiv"
        } else if let error = json["error"] as? String, !error.isEmpty {
            licenseStatus = error
        } else {
            licenseStatus = "Keine Lizenz hinterlegt"
        }

        // Abo-Anzeigezeile aus den (optionalen) LemonSqueezy-Feldern.
        // NICHT das Lease-"expires" verwenden (nur rollendes Prüf-Fenster).
        let endsAt = json["ends_at"] as? String ?? ""
        let renewsAt = json["renews_at"] as? String ?? ""
        let status = json["sub_status"] as? String ?? ""
        if !isValid {
            subLine = ""; subIsWarning = false
        } else if !endsAt.isEmpty {
            subLine = "Gekündigt — endet am \(formatDate(endsAt))"; subIsWarning = true
        } else if status == "past_due" {
            subLine = "Zahlung ausstehend"; subIsWarning = true
        } else if status == "on_trial" {
            subLine = renewsAt.isEmpty ? "Testphase" : "Testphase bis \(formatDate(renewsAt))"
            subIsWarning = false
        } else if !renewsAt.isEmpty {
            subLine = "Verlängert sich am \(formatDate(renewsAt))"; subIsWarning = false
        } else {
            subLine = ""; subIsWarning = false
        }

        // Optimistischer Cache für den nächsten Tab-Aufruf (siehe @State-Defaults oben).
        let d = UserDefaults.standard
        d.set(isValid, forKey: "lic.isValid")
        d.set(isGrace, forKey: "lic.isGrace")
        d.set(licenseEmail, forKey: "lic.email")
        d.set(subLine, forKey: "lic.subLine")
        d.set(subIsWarning, forKey: "lic.subWarn")
    }

    /// ISO-Datum (yyyy-MM-dd) → deutsches "dd.MM.yyyy". Fällt auf Eingabe zurück.
    private func formatDate(_ iso: String) -> String {
        let inFmt = DateFormatter()
        inFmt.dateFormat = "yyyy-MM-dd"
        inFmt.locale = Locale(identifier: "en_US_POSIX")
        guard let d = inFmt.date(from: String(iso.prefix(10))) else { return iso }
        let outFmt = DateFormatter()
        outFmt.dateFormat = "dd.MM.yyyy"
        return outFmt.string(from: d)
    }

    private func runEngineCommand(_ args: [String]) async -> String {
        // Engine-Binary im Bundle oder Python im Dev-Modus
        let bundledEngine = Bundle.main.resourceURL?
            .appendingPathComponent("multicam-engine/multicam-engine")

        let process = Process()
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice

        // Lizenz-Modus + Backend-URL an die Engine durchreichen
        var env = ProcessInfo.processInfo.environment
        LicenseConfig.apply(to: &env)
        process.environment = env

        if let engine = bundledEngine, FileManager.default.fileExists(atPath: engine.path) {
            process.executableURL = engine
            process.arguments = args
        } else {
            // Dev-Fallback
            let toolkitRoot = URL(fileURLWithPath: "/Users/maxmenge/Developer/resolve-toolkit")
            let pythonPath = toolkitRoot.appendingPathComponent("venv/bin/python3").path
            let enginePath = toolkitRoot
                .appendingPathComponent("apps/multicam-cutter/engine/multicam_engine.py").path
            guard FileManager.default.fileExists(atPath: pythonPath) else {
                return "{\"valid\": false, \"error\": \"Engine nicht gefunden\"}"
            }
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [enginePath] + args
        }

        do {
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return String(data: data, encoding: .utf8) ?? ""
        } catch {
            return "{\"valid\": false, \"error\": \"\(error.localizedDescription)\"}"
        }
    }
}
