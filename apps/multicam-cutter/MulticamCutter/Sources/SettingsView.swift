import SwiftUI
import Sparkle

struct SettingsView: View {
    /// Optional, weil Previews und der Dev-Build ohne laufenden Updater
    /// auskommen muessen.
    var updater: SPUUpdater? = nil
    var updaterIsActive: Bool = false

    private enum Tab: Hashable {
        case general, clip, nodding, license
    }

    var body: some View {
        TabView {
            GeneralSettingsTab(updater: updater, updaterIsActive: updaterIsActive)
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

// MARK: - Nodding (roher JSON-Editor der GLOBALEN Schwellen/Filter, Expert)
//
// Nur die globalen Schwellen/Filter (nodding_patterns.json). Das AN/AUS der einzelnen
// Muster liegt PRO PRESET im Analyse-Panel (Wizard → Experteneinstellungen →
// „Cutaway Regeln" → Nicken-Muster), nicht hier.

struct NoddingSettingsTab: View {
    @EnvironmentObject var engine: EngineController

    @State private var text = ""
    @State private var source = "default"     // "user" | "default"
    @State private var message: String?
    @State private var messageIsError = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Nodding-Muster").font(.headline)
                Spacer()
                Text(source == "user" ? "Angepasst" : "Standard")
                    .font(.caption2)
                    .foregroundStyle(source == "user" ? .brandSecondary : .secondary)
            }
            Text("Globale Schwellen & Filter der Nicken-Erkennung (nodding_patterns.json) — "
                 + "Expertenwerte. Das Aktivieren/Deaktivieren einzelner Muster liegt pro Preset "
                 + "im Analyse-Panel (Experteneinstellungen → Cutaway Regeln). Bei defektem JSON "
                 + "nutzt die Analyse automatisch die Defaults.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            TextEditor(text: $text)
                .font(.system(.caption, design: .monospaced))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(4)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))

            HStack {
                Button("Speichern") { save() }.buttonStyle(.borderedProminent)
                Button("Auf Standard zurücksetzen") { reset() }.disabled(source != "user")
                Spacer()
                if let message {
                    LucideLabel(message, icon: messageIsError ? "octagon-x" : "check", size: 11)
                        .font(.caption).foregroundStyle(messageIsError ? .red : .green).lineLimit(1)
                }
            }
            Text("Gilt beim nächsten Analyse-Lauf.").font(.caption2).foregroundStyle(.tertiary)
        }
        .padding()
        .task { await load() }
    }

    private func load() async {
        if let p = await engine.getNoddingPatterns() { text = p.content; source = p.source }
        message = nil
    }

    private func save() {
        if let err = engine.saveNoddingPatterns(text) {
            message = err; messageIsError = true
        } else {
            source = "user"; message = "Gespeichert"; messageIsError = false
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
                // Prompts nur zeigen, wenn das Modell da ist — ohne CLIP haben sie
                // keine Wirkung und verwirren nur (User 25.07.). Bei `nil` (Status
                // wird noch geprueft) ebenfalls aus, bis er feststeht.
                if modelInstalled == true {
                    Divider()
                    promptSection
                }
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
                    LucideLabel("Modell geladen", icon: "circle-check", size: 13)
                        .foregroundStyle(.green)
                case .some(false):
                    LucideLabel("Modell nicht geladen", icon: "circle-arrow-down", size: 13)
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
                    LucideLabel("Gespeichert", icon: "check", size: 11)
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
    let updater: SPUUpdater?
    let updaterIsActive: Bool

    // Expertenmodus-Toggle entfernt: obsolet, seit die Parameter im Wizard über
    // „Experteneinstellungen" ein-/ausklappen (Variante C).
    // Denselben Key liest ScrubbableThumbnail — Umschalten wirkt live.
    @AppStorage("thumbnailAutoContrast") private var thumbnailAutoContrast = false
    // Codec-Feineinstellung der Bildraten-Umwandlung. Defaults an echtem 4K-10bit
    // kalibriert (q72 = Bildtreue des alten libx264-crf14). Die Engine liest
    // dieselben Keys per UserDefaults (EngineController.convertMismatchedFps).
    @AppStorage("convertHevcQuality") private var convertHevcQuality = 72
    @AppStorage("convertProResProfile") private var convertProResProfile = "hq"
    // AAF-Clipnamen. Toggle AN (Default) = grund-benannte MasterMobs nach
    // `clipNamePattern`; in Resolve am Timeline-Clip sichtbar, in Premiere je Grund
    // ein zusaetzlicher (korrekt verknuepfter) Clip. AUS = ein Clip pro Kamera.
    // EngineController.startAnalysis reicht das Muster nur bei aktivem Toggle als
    // --clip-name-pattern durch.
    @AppStorage("clipNameReasons") private var clipNameReasons = true
    @AppStorage("clipNamePattern") private var clipNamePattern = "%L - %S"

    var body: some View {
        Form {
            if let updater {
                UpdateSettingsSection(updater: updater, isActive: updaterIsActive)
            }

            Section("Darstellung") {
                Toggle("Kontrast der Vorschaubilder anheben", isOn: $thumbnailAutoContrast)
                Text("Hebt flaches Log-Material in den Kamera-Vorschauen an (auch beim "
                     + "Scrubbing). Rein kosmetisch — Analyse und Export bleiben unberührt.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            // Bewusst KEIN "Materialhinweis erneut anzeigen"-Knopf (entfernt
            // 24.07., User): Der Hinweis erscheint automatisch wieder, sobald
            // sich sein INHALT aendert (contentRevision in FirstRunSheet) —
            // das reicht, ein manueller Reset verwirrt nur.

            conversionSection
            clipNameSection
        }
        .formStyle(.grouped)
        .padding()
    }

    // AAF-Clipnamen: frei konfigurierbares Muster, Live-Vorschau. Bestimmt, was
    // die NLE im Timeline-Segment anzeigt (MasterMob-Name im AAF).
    private var clipNameSection: some View {
        Section("AAF-Clipnamen") {
            Toggle("Schnittgründe in Clipnamen", isOn: $clipNameReasons)
            Text("Benennt jeden Schnitt im AAF nach seinem Grund (Sprecher, Übergang …) — "
                 + "hilft beim Sichten, den Grund direkt am Clip zu sehen. DaVinci Resolve "
                 + "zeigt das am Timeline-Clip; Premiere Pro legt dafür pro Grund einen "
                 + "zusätzlichen (korrekt verknüpften) Clip im Projekt an. Wer lieber genau "
                 + "einen Clip pro Kamera möchte, schaltet es ab.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if clipNameReasons {
                Text("Muster für den Namen. Platzhalter: %S Quelldatei · %R Schnittgrund · "
                     + "%P Person · %L smartes Label (Person bei Sprecher, sonst Grund). "
                     + "Leere Platzhalter werden samt Trenner sauber entfernt.")
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack {
                    TextField("Muster", text: $clipNamePattern)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(.body, design: .monospaced))
                    if clipNamePattern != "%L - %S" {
                        Button("Standard") { clipNamePattern = "%L - %S" }
                            .buttonStyle(.link).font(.caption)
                    }
                }

                VStack(alignment: .leading, spacing: 3) {
                    clipNamePreviewRow("Sprecher-Clip", source: "C0352",
                                       reason: "Sprecher", person: "Andreas", label: "Andreas")
                    clipNamePreviewRow("Cutaway (Totale)", source: "C0352",
                                       reason: "Übergang", person: "", label: "Übergang")
                }
                .padding(.top, 2)
            }
        }
    }

    private func clipNamePreviewRow(_ title: String, source: String,
                                    reason: String, person: String, label: String) -> some View {
        HStack(spacing: 8) {
            Text(title).font(.caption2).foregroundStyle(.tertiary)
                .frame(width: 110, alignment: .leading)
            Text(clipNamePreview(source: source, reason: reason, person: person, label: label))
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary).lineLimit(1).truncationMode(.tail)
        }
    }

    /// Swift-Spiegel der Engine-Namenslogik (build_aaf._name_for) — nur fuer die
    /// Vorschau. Muss mit der Python-Seite konsistent bleiben (Tokens + Tidy).
    private func clipNamePreview(source: String, reason: String,
                                 person: String, label: String) -> String {
        var s = clipNamePattern
        for (tok, val) in [("%S", source), ("%R", reason), ("%P", person), ("%L", label)] {
            s = s.replacingOccurrences(of: tok, with: val)
        }
        func rx(_ pat: String, _ rep: String) {
            s = s.replacingOccurrences(of: pat, with: rep, options: .regularExpression)
        }
        let sep = "[-–—·|/•:]"
        rx("\\s+", " ")
        rx("(\(sep))\\s*(?:\(sep)\\s*)+", "$1 ")   // doppelte Trenner
        rx("^\\s*\(sep)\\s*", "")                    // Trenner vorn
        rx("\\s*\(sep)\\s*$", "")                    // Trenner hinten
        s = s.trimmingCharacters(in: .whitespaces)
        return s.isEmpty ? source : s
    }

    // Bildraten-Umwandlung: Codec richtet sich automatisch nach dem Quellformat
    // (HEVC 10-bit fuer 4:2:0, ProRes fuer 4:2:2/4:4:4). Hier nur die Qualitaets-
    // Feineinstellung fuer Cutter, die bewusst eingreifen wollen.
    private var conversionSection: some View {
        Section("Bildraten-Umwandlung") {
            Text("Wird eine Videodatei auf die Timeline-Bildrate umgewandelt, wählt die App "
                 + "den Codec passend zum Quellformat — HEVC 10-bit für 4:2:0 (Action-Cams, "
                 + "Drohnen), ProRes für 4:2:2/4:4:4 (Profikameras). Die Voreinstellungen sind "
                 + "auf eine quellgetreue, gradebare Kopie kalibriert. Nur ändern, wenn du "
                 + "genau weißt, was du tust.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("HEVC-Qualität (4:2:0-Material)")
                    Spacer()
                    Text("\(convertHevcQuality)")
                        .monospacedDigit().foregroundStyle(.secondary)
                    if convertHevcQuality != 72 {
                        Button("Standard") { convertHevcQuality = 72 }
                            .buttonStyle(.link).font(.caption)
                    }
                }
                Slider(value: Binding(get: { Double(convertHevcQuality) },
                                      set: { convertHevcQuality = Int($0.rounded()) }),
                       in: 50...95, step: 1)
                Text("Höher = näher am Original, aber größere Dateien. 72 entspricht der "
                     + "bisherigen Qualität (praktisch verlustfrei).")
                    .font(.caption2).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Picker("ProRes-Profil (4:2:2-Material)", selection: $convertProResProfile) {
                Text("Standard").tag("standard")
                Text("HQ").tag("hq")
            }
            Text("Nur für echtes 4:2:2/4:4:4-Material. HQ ist praktisch verlustfrei, "
                 + "Standard etwas kleiner. (4:4:4 nutzt immer ProRes 4444.)")
                .font(.caption2).foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
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
    // Arbeitsplaetze bei Mehrplatz-Lizenzen (0 = Backend liefert (noch) keine Zahlen)
    @State private var seatsUsed = 0
    @State private var seatsLimit = 0
    @State private var showDeactivateConfirm = false

    var body: some View {
        Form {
            Section {
                HStack {
                    LucideIcon(isValid ? "badge-check" : "badge-x", size: 22)
                        .foregroundStyle(isValid ? (isGrace ? .brandSecondary : .green) : .red)
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
                        // Nur bei Mehrplatz-Lizenzen (Limit > 1): "1 von 1" waere
                        // Rauschen. Stand = letzter Serverkontakt (Lease-Refresh).
                        if isValid && seatsLimit > 1 {
                            Text("Arbeitsplätze: \(seatsUsed) von \(seatsLimit) belegt")
                                .font(.caption)
                                .foregroundStyle(seatsUsed >= seatsLimit ? .brandSecondary : .secondary)
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
        seatsUsed = json["seats_used"] as? Int ?? 0
        seatsLimit = json["seats_limit"] as? Int ?? 0

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
