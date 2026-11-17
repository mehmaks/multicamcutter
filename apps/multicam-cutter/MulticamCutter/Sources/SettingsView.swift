import SwiftUI
import Sparkle

struct SettingsView: View {
    /// Optional, weil Previews und der Dev-Build ohne laufenden Updater
    /// auskommen muessen.
    var updater: SPUUpdater? = nil
    var updaterIsActive: Bool = false

    private enum Tab: Hashable {
        case general, clip, nodding
    }

    var body: some View {
        TabView {
            GeneralSettingsTab(updater: updater, updaterIsActive: updaterIsActive)
                .tabItem {
                    Label("General", systemImage: "gearshape")
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
                Text("Nodding patterns").font(.headline)
                Spacer()
                Text(loc(source == "user" ? "Customized" : "Default"))
                    .font(.caption2)
                    .foregroundStyle(source == "user" ? .brandSecondary : .secondary)
            }
            Text(loc("Global thresholds & filters for head-nod detection (nodding_patterns.json) — "
                 + "expert values. Turning individual patterns on or off is done per preset "
                 + "in the analysis panel (Expert settings → Cutaway rules). If the JSON is broken, "
                 + "the analysis automatically uses the defaults."))
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            TextEditor(text: $text)
                .font(.system(.caption, design: .monospaced))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(4)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))

            HStack {
                Button("Save") { save() }.buttonStyle(.borderedProminent)
                Button("Reset to defaults") { reset() }.disabled(source != "user")
                Spacer()
                if let message {
                    LucideLabel(message, icon: messageIsError ? "octagon-x" : "check", size: 11)
                        .font(.caption).foregroundStyle(messageIsError ? .red : .green).lineLimit(1)
                }
            }
            Text("Applies on the next analysis run.").font(.caption2).foregroundStyle(.tertiary)
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
            source = "user"; message = "Saved"; messageIsError = false
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) {
                if message == "Saved" { message = nil }
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
            Text("Image recognition (CLIP)").font(.headline)
            Text(loc("Optional model (≈ 581 MB). Filters out unsuitable cutaway frames "
                 + "(e.g. drinking). Everything else runs normally without it."))
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                switch modelInstalled {
                case .some(true):
                    LucideLabel("Model loaded", icon: "circle-check", size: 13)
                        .foregroundStyle(.green)
                case .some(false):
                    LucideLabel("Model not loaded", icon: "circle-arrow-down", size: 13)
                        .foregroundStyle(.secondary)
                    Button("Download") { engine.downloadClipModel() }
                        .disabled(engine.isDownloadingClip)
                case .none:
                    SwiftUI.ProgressView().controlSize(.small)
                    Text("checking …").font(.caption).foregroundStyle(.secondary)
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
                Text("Filter prompts").font(.headline)
                Spacer()
                Text(loc(source == "user" ? "Customized" : "Default"))
                    .font(.caption2)
                    .foregroundStyle(source == "user" ? .brandSecondary : .secondary)
            }
            Text(loc("One prompt per line, in English (that's what CLIP expects). "
                 + "Ignore = such images are avoided as cutaways, "
                 + "Neutral = explicitly allowed."))
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            promptEditor("IGNORE", text: $ignoreText)
            promptEditor("NEUTRAL", text: $neutralText)

            HStack {
                Button("Save") { save() }
                    .buttonStyle(.borderedProminent)
                Button("Reset to defaults") { reset() }
                    .disabled(source != "user")
                Spacer()
                if justSaved {
                    LucideLabel("Saved", icon: "check", size: 11)
                        .font(.caption).foregroundStyle(.green)
                }
            }
            Text("Applies on the next analysis run.")
                .font(.caption2).foregroundStyle(.tertiary)
        }
    }

    private func promptEditor(_ title: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(loc(title)).font(.caption2).fontWeight(.bold).foregroundStyle(.secondary)
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
    /// Telemetrie-Zustimmung: 0 = ungefragt, 1 = an, 2 = aus (geteilt mit Telemetry.swift).
    @AppStorage("analyticsConsent") private var analyticsConsent = 0

    var body: some View {
        Form {
            if let updater {
                UpdateSettingsSection(updater: updater, isActive: updaterIsActive)
            }

            Section("Appearance") {
                Toggle("Boost contrast of preview images", isOn: $thumbnailAutoContrast)
                Text(loc("Lifts flat Log footage in the camera previews (also while "
                     + "scrubbing). Purely cosmetic — analysis and export stay untouched."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Privacy") {
                Toggle("Send anonymous usage data", isOn: Binding(
                    get: { analyticsConsent == 1 },
                    set: { analyticsConsent = $0 ? 1 : 2 }))
                Text(loc("Helps improve the app: only anonymous numbers (number of cameras, "
                     + "microphones, speakers, duration, run time, device, settings) — "
                     + "never names, files or paths. Can be turned off here any time."))
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
        Section("AAF clip names") {
            Toggle("Cut reasons in clip names", isOn: $clipNameReasons)
            Text(loc("Names every cut in the AAF after its reason (speaker, transition …) — "
                 + "helps you see the reason right on the clip while reviewing. DaVinci Resolve "
                 + "shows it on the timeline clip; Premiere Pro adds one extra (correctly linked) "
                 + "clip per reason to the project. If you'd rather have exactly "
                 + "one clip per camera, turn it off."))
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if clipNameReasons {
                Text(loc("Pattern for the name. Placeholders: %S source file · %R cut reason · "
                     + "%P person · %L smart label (person for speaker cuts, otherwise reason). "
                     + "Empty placeholders are removed cleanly along with their separator."))
                    .font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack {
                    TextField("Pattern", text: $clipNamePattern)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(.body, design: .monospaced))
                    if clipNamePattern != "%L - %S" {
                        Button("Default") { clipNamePattern = "%L - %S" }
                            .buttonStyle(.link).font(.caption)
                    }
                }

                VStack(alignment: .leading, spacing: 3) {
                    clipNamePreviewRow("Speaker clip", source: "C0352",
                                       reason: "Speaker", person: "Andreas", label: "Andreas")
                    clipNamePreviewRow("Cutaway (wide shot)", source: "C0352",
                                       reason: "Transition", person: "", label: "Transition")
                }
                .padding(.top, 2)
            }
        }
    }

    private func clipNamePreviewRow(_ title: String, source: String,
                                    reason: String, person: String, label: String) -> some View {
        HStack(spacing: 8) {
            Text(loc(title)).font(.caption2).foregroundStyle(.tertiary)
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
        Section("Frame-rate conversion") {
            Text(loc("When a video file is converted to the timeline frame rate, the app picks "
                 + "the codec to match the source format — HEVC 10-bit for 4:2:0 (action cams, "
                 + "drones), ProRes for 4:2:2/4:4:4 (pro cameras). The defaults are "
                 + "calibrated for a source-faithful, gradable copy. Only change these if you "
                 + "know exactly what you're doing."))
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("HEVC quality (4:2:0 footage)")
                    Spacer()
                    Text("\(convertHevcQuality)")
                        .monospacedDigit().foregroundStyle(.secondary)
                    if convertHevcQuality != 72 {
                        Button("Default") { convertHevcQuality = 72 }
                            .buttonStyle(.link).font(.caption)
                    }
                }
                Slider(value: Binding(get: { Double(convertHevcQuality) },
                                      set: { convertHevcQuality = Int($0.rounded()) }),
                       in: 50...95, step: 1)
                Text(loc("Higher = closer to the original, but larger files. 72 matches the "
                     + "previous quality (practically lossless)."))
                    .font(.caption2).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Picker("ProRes profile (4:2:2 footage)", selection: $convertProResProfile) {
                Text("Standard").tag("standard")
                Text("HQ").tag("hq")
            }
            Text(loc("Only for true 4:2:2/4:4:4 footage. HQ is practically lossless, "
                 + "Standard a bit smaller. (4:4:4 always uses ProRes 4444.)"))
                .font(.caption2).foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
