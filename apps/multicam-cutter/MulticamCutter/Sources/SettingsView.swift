import SwiftUI

struct SettingsView: View {
    private enum Tab: Hashable {
        case general, license
    }

    var body: some View {
        TabView {
            GeneralSettingsTab()
                .tabItem {
                    Label("Allgemein", systemImage: "gearshape")
                }
                .tag(Tab.general)

            LicenseSettingsTab()
                .tabItem {
                    Label("Lizenz", systemImage: "key")
                }
                .tag(Tab.license)
        }
        .frame(width: 450, height: 280)
        // Ohne das nutzen die Tab-Icons/Labels den blauen System-Akzent statt Lime
        // (ContentView/About haben den Tint schon, der Settings-Scene fehlte er).
        .tint(.brandAccent)
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
    @State private var licenseStatus: String = "Wird geprüft..."
    @State private var licenseEmail: String = ""
    @State private var subLine: String = ""          // "Verlängert sich am ..." / "Endet am ..."
    @State private var subIsWarning: Bool = false     // gekündigt/fällig → lila (brandSecondary)
    @State private var isValid: Bool = false
    @State private var isGrace: Bool = false
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
