import SwiftUI
import UniformTypeIdentifiers

// MARK: - Zuordnungs-Wizard
//
// Ersetzt den alten Canvas + rechten Inspector + linke Sidebar durch einen
// geführten 3-Schritt-Fluss (siehe Klick-Dummy / brain/TODOs.md → Personen):
//   1 Personen benennen · 2 Personen auf Kameras ziehen · 3 Übersicht & Start
// Reine Präsentationsschicht über demselben Modell (persons/camRoles).

// ── Personen-Identitätsfarben (gedämpft, konkurrieren nicht mit Lime/Flieder) ──
private let personPalette: [Color] = [
    Color(.sRGB, red: 120/255, green: 166/255, blue: 230/255, opacity: 1),  // blau
    Color(.sRGB, red: 230/255, green: 143/255, blue: 176/255, opacity: 1),  // rosé
    Color(.sRGB, red: 224/255, green: 177/255, blue:  92/255, opacity: 1),  // amber
    Color(.sRGB, red: 134/255, green: 179/255, blue: 154/255, opacity: 1),  // teal
    Color(.sRGB, red: 176/255, green: 150/255, blue: 230/255, opacity: 1),  // lavendel
    Color(.sRGB, red: 224/255, green: 138/255, blue: 110/255, opacity: 1),  // terracotta
]

@MainActor
private func personColor(_ personId: Int, _ engine: EngineController) -> Color {
    let idx = engine.activeMics.firstIndex { $0.id == personId } ?? 0
    return personPalette[idx % personPalette.count]
}

private func personInitials(_ name: String) -> String {
    let parts = name.split { $0 == " " || $0 == "_" || $0 == "-" }
    let a = parts.first?.first.map(String.init) ?? "?"
    let b = parts.count > 1 ? (parts[1].first.map(String.init) ?? "") : ""
    return (a + b).uppercased()
}

@MainActor
private func avatar(_ personId: Int, _ name: String, size: CGFloat, _ engine: EngineController) -> some View {
    ZStack {
        Circle().fill(personColor(personId, engine)).frame(width: size, height: size)
        Text(personInitials(name))
            .font(.system(size: size * 0.36, weight: .bold))
            .foregroundStyle(.black)
    }
}

// MARK: - Container

/// Standard-Inhaltsbreite aller Wizard-Seiten (User-Entscheid 24.07., revidiert:
/// die fruehere Screen-3-Breite gilt durchgaengig — bei 720 brachen die
/// Uebersichts-Spalten um. Das Fenster ist darauf fixiert,
/// s. ContentView.enforceWizardWindowChrome).
enum WizardLayout {
    static let contentWidth: CGFloat = 1080
}

/// Natuerliche Hoehe des Wizard-Inhalts (fuer Fenster-Fitting, s. ContentView).
struct WizardContentHeightKey: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

/// Sichtbare Hoehe des Scroll-Bereichs (fuer Fenster-Fitting, s. ContentView).
struct WizardViewportHeightKey: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

struct WizardView: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(spacing: 0) {
            header
            Rectangle().fill(Color.wizBorder).frame(height: 1)
            ScrollView {
                Group {
                    switch engine.wizardStep {
                    case .persons:  PersonsStep()
                    case .cameras:  CamerasStep()
                    case .overview: OverviewStep()
                    }
                }
                .frame(maxWidth: .infinity)          // Steps setzen eigene Breite + werden zentriert
                .padding(.horizontal, 28)
                .padding(.vertical, 24)
                // Natuerliche Inhaltshoehe melden (inkl. Padding) — ContentView
                // passt die Fensterhoehe je Wizard-Seite dem Inhalt an.
                .background(GeometryReader { g in
                    Color.clear.preference(key: WizardContentHeightKey.self,
                                           value: g.size.height)
                })
            }
            // Sichtbarer Scroll-Bereich: die Differenz Inhalt − Viewport ist exakt
            // das, was dem Fenster fehlt (oder zu viel ist) — unabhaengig von
            // Titelleiste/Header/Footer.
            .background(GeometryReader { g in
                Color.clear.preference(key: WizardViewportHeightKey.self,
                                       value: g.size.height)
            })
            Rectangle().fill(Color.wizBorder).frame(height: 1)
            WizardFooter()
        }
        .background(wizBackground)
        .foregroundStyle(Color.wizText)
        // Beim Seitenwechsel laufende Audio-Vorschau stoppen — sonst spielt eine
        // auf Seite 1 gestartete Spur auf Seite 2/3 unsichtbar weiter.
        .onChange(of: engine.wizardStep) { _, _ in engine.stopAllPlayback() }
        .sheet(isPresented: $engine.isConverting) {
            FpsConversionSheet().environmentObject(engine)
        }
        .alert("Conversion failed",
               isPresented: Binding(get: { engine.convertError != nil },
                                    set: { if !$0 { engine.convertError = nil } })) {
            Button("OK", role: .cancel) { engine.convertError = nil }
        } message: { Text(engine.convertError ?? "") }
    }

    // Kein flaches Schwarz: sanfter Verlauf + dezente Lime/Flieder-Radials wie im
    // Dummy — dadurch wirkt der Grund weniger dunkel und deutlich harmonischer.
    private var wizBackground: some View {
        ZStack {
            LinearGradient(colors: [Color.wizBg2, Color.wizBg], startPoint: .top, endPoint: .bottom)
            RadialGradient(colors: [Color.brandAccent.opacity(0.05), .clear],
                           center: .topTrailing, startRadius: 0, endRadius: 620)
            RadialGradient(colors: [Color.brandSecondary.opacity(0.045), .clear],
                           center: .bottomLeading, startRadius: 0, endRadius: 560)
        }
        .ignoresSafeArea()
    }

    private var header: some View {
        VStack(spacing: 0) {
            // Episodenname (editierbar) direkt unter der Titelleiste. Der App-Titel
            // steht in der Leiste selbst. Feedback-Button liegt oben rechts.
            HStack(spacing: 10) {
                EditableLabel(text: $engine.episodeName, icon: "clapperboard")
                    .font(.headline)
                Spacer()
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 11)

            Rectangle().fill(Color.wizBorder).frame(height: 1)

            // Stepper als eigene, linksbündige Zeile (wie im Dummy).
            HStack {
                WizardStepBar()
                Spacer()
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 11)
        }
    }
}

// MARK: - Stepper

struct WizardStepBar: View {
    @EnvironmentObject var engine: EngineController
    private let steps: [(WizardStep, String)] = [
        (.persons, "People"), (.cameras, "Cameras"), (.overview, "Overview"),
    ]

    var body: some View {
        HStack(spacing: 8) {
            ForEach(Array(steps.enumerated()), id: \.offset) { i, item in
                if i > 0 {
                    Rectangle().fill(Color.wizBorder).frame(width: 34, height: 1)
                }
                stepButton(index: i, step: item.0, label: item.1)
            }
        }
    }

    @ViewBuilder
    private func stepButton(index: Int, step: WizardStep, label: String) -> some View {
        let active = engine.wizardStep == step
        let done = engine.wizardStep.rawValue > step.rawValue
        Button { engine.wizardStep = step } label: {
            HStack(spacing: 8) {
                ZStack {
                    Circle()
                        .fill(active ? Color.brandAccent
                              : (done ? Color.brandAccent.opacity(0.16) : Color.wizSurface))
                        .overlay(Circle().stroke(done ? Color.brandAccent.opacity(0.5) : Color.wizBorder, lineWidth: 1))
                        .frame(width: 25, height: 25)
                    if done {
                        LucideIcon("check", size: 11).foregroundStyle(.brandAccent)
                    } else {
                        Text("\(index + 1)").font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(active ? Color.black : Color.wizMuted)
                    }
                }
                Text(label).font(.subheadline).fontWeight(active ? .semibold : .regular)
                    .foregroundStyle(active ? Color.wizText : Color.wizMuted)
            }
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Intro-Kopf je Screen

struct WizardIntro: View {
    let title: String
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.system(size: 22, weight: .semibold))
            Text(text).font(.system(size: 15)).lineSpacing(3).foregroundStyle(.wizMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: 640, alignment: .leading)
    }
}

// MARK: - Screen 1: Personen

struct PersonsStep: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            WizardIntro(title: "Name your speakers",
                        text: "We create one person from each audio track automatically. Give them "
                            + "names you'll recognize in the edit. Just throw away any tracks that "
                            + "aren't a speaker's microphone (room tone, music).")

            // Zweispaltig ab 2 Spuren (1080er-Standardbreite, User-Wunsch 24.07.):
            // ~530 pt je Karte reichen der Waveform locker, und viele Spuren
            // kosten nur die halbe Hoehe. Eine einzelne Spur bleibt volle Breite.
            if engine.activeMics.count >= 2 {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 12),
                                    GridItem(.flexible(), spacing: 12)],
                          alignment: .leading, spacing: 12) {
                    ForEach(engine.activeMics) { mic in
                        PersonRow(mic: mic)
                    }
                }
            } else {
                ForEach(engine.activeMics) { mic in
                    PersonRow(mic: mic)
                }
            }

            if engine.activeMics.isEmpty {
                Text("No active audio tracks.").foregroundStyle(.wizMuted)
            } else {
                let n = engine.activeMics.count
                Text("\(n) person\(n == 1 ? "" : "s") — one per audio track.")
                    .font(.callout).foregroundStyle(.wizMuted)
            }

            // Nur sinnvoll ab 2 Spuren: bestätigt der Nutzer ein Ein-Recorder-Setup,
            // erbt eine still aufgenommene Spur den gemeinsamen Offset, statt den
            // Sync abzubrechen (siehe waveform_sync.py → mics_same_recorder).
            if engine.activeMics.count >= 2 {
                // Schalter DIREKT neben Label + (?) — ueber die volle
                // 1080er-Breite gespreizt (WizToggle mit Spacer) las sich
                // beides nicht mehr als zusammengehoerig.
                HStack(spacing: 8) {
                    Text("All audio tracks come from one multitrack recorder")
                        .font(.system(size: 14))
                    WizHelpBadge(ParamHelp.micsSameRecorder)
                    WizSwitch(isOn: $engine.params.micsSameRecorder)
                }
                .padding(.top, 4)
            }

            if !engine.excludedMics.isEmpty {
                WizRestoreChips(title: "Hidden tracks",
                                items: engine.excludedMics.map { (id: $0.id, name: $0.displayName) },
                                restore: { engine.setMicIncluded($0, true) })
                    .padding(.top, 6)
            }
        }
        .frame(maxWidth: WizardLayout.contentWidth, alignment: .leading)
    }
}

struct PersonRow: View {
    let mic: MicInfo
    @EnvironmentObject var engine: EngineController
    @State private var draft = ""
    @FocusState private var focused: Bool

    private var isPlaying: Bool { engine.playingMicId == mic.id }
    private var liveName: String { engine.micInfos.first { $0.id == mic.id }?.displayName ?? mic.displayName }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
        HStack(spacing: 14) {
            avatar(mic.id, liveName, size: 44, engine)

            VStack(alignment: .leading, spacing: 1) {
                // Stift direkt hinter dem Namen: signalisiert „hier kannst du
                // tippen" — das plain-TextField allein sieht wie ein Label aus.
                HStack(spacing: 5) {
                    TextField("Name", text: $draft)
                        .textFieldStyle(.plain)
                        .font(.system(size: 16, weight: .semibold))
                        .focused($focused)
                        .onSubmit { commit() }
                        .onChange(of: focused) { _, f in if !f { commit() } }
                        .fixedSize()
                    LucideIcon("pencil", size: 12)
                        .foregroundStyle(.wizFaint)
                        .onTapGesture { focused = true }
                        .help("Edit name")
                    Spacer(minLength: 0)
                }
                HStack(spacing: 7) {
                    Text(mic.filename)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.wizFaint)
                    if let sep = mic.separationDb {
                        SeparationBadge(db: sep)
                    }
                }
            }

            Spacer()

            Button { engine.toggleMicPreview(mic) } label: {
                LucideIcon(isPlaying ? "circle-pause" : "circle-play", size: 19)
                    .foregroundStyle(isPlaying ? Color.brandAccent : Color.secondary)
            }
            .buttonStyle(.plain)
            .help("Play the whole track (starts at the loudest point) — "
                  + "or click straight into the waveform")

            Button { engine.deletePerson(mic.id) } label: {
                LucideIcon("trash-2", size: 15).foregroundStyle(.wizMuted)
            }
            .buttonStyle(.plain)
            .help("This track isn't a speaker — remove")
        }

        // Wellenform der ganzen Spur — Klick springt an die Position
        // (Fremd-Feedback 22.07.: der 5-s-Schnipsel war zu unverlaesslich,
        // um unbekanntes Material schnell Personen zuzuordnen).
        WaveformStrip(mic: mic)
        }
        .padding(12)
        .background(Color.wizSurface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.wizBorder, lineWidth: 1))
        .onAppear { draft = liveName }
        // Sicherheitsnetz: Verlässt man Screen 1 (z. B. „Weiter"), ohne mit Enter zu
        // bestätigen, geht die Umbenennung sonst verloren — beim Verschwinden committen.
        .onDisappear { commit() }
    }

    private func commit() {
        let trimmed = draft.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { draft = liveName } else if trimmed != liveName { engine.renameMic(mic.id, to: trimmed) }
    }
}

/// Trennung/Isolation einer Tonspur in dB (Median-Pegelabstand, wenn diese
/// Person spricht). BEWUSST neutral gefaerbt und ohne Schwelle/Ampel — der Wert
/// ist informativ, damit man ueber mehrere Folgen ein Gefuehl fuer „normal"
/// bekommt; er taugt NICHT als Qualitaets-Gate (die Korrelation zur Fehlerrate
/// ist zu wackelig, siehe brain/TODOs.md).
struct SeparationBadge: View {
    let db: Double

    var body: some View {
        HStack(spacing: 3) {
            LucideIcon("audio-waveform", size: 10)
            Text("\(fmtDb(db)) dB")
                .font(.caption2.weight(.medium))
        }
        .foregroundStyle(.wizMuted)
        .help("Separation of this track: how much louder it is than the others "
              + "when this person speaks. Higher values mean less "
              + "bleed. Just for info — doesn't affect the cut.")
    }

    private func fmtDb(_ v: Double) -> String {
        String(format: "%.1f", v).replacingOccurrences(of: ".", with: ",")
    }
}

/// Wellenform der ganzen Spur im Voice-Message-Stil: abgerundete Balken mit
/// Luecken, der gespielte Teil in Akzentfarbe, ein Punkt als Playhead, darunter
/// Position + Gesamtdauer. Klick springt an die Position und spielt ab dort.
/// Peaks kommen on-demand aus dem EngineController (einmal je Datei, gecacht);
/// waehrend der Berechnung steht ein Platzhalter mit Prozentanzeige.
struct WaveformStrip: View {
    let mic: MicInfo
    @EnvironmentObject var engine: EngineController

    private static let barWidth: CGFloat = 3
    private static let barGap: CGFloat = 2.5

    var body: some View {
        TimelineView(.animation(minimumInterval: 0.05,
                                paused: engine.playingMicId != mic.id)) { _ in
            VStack(spacing: 3) {
                GeometryReader { geo in
                    waveformOrPlaceholder
                        .contentShape(Rectangle())
                        .gesture(SpatialTapGesture().onEnded { value in
                            guard mic.durationSeconds > 0, geo.size.width > 0,
                                  engine.micWaveforms[mic.id] != nil else { return }
                            let frac = min(max(0, value.location.x / geo.size.width), 1)
                            engine.playMic(mic, at: frac * mic.durationSeconds)
                        })
                }
                .frame(height: 32)

                HStack {
                    if let t = engine.playbackTime(for: mic.id) {
                        Text(Self.fmt(t)).foregroundStyle(Color.brandAccent)
                    }
                    Spacer()
                    if mic.durationSeconds > 0 {
                        Text(Self.fmt(mic.durationSeconds)).foregroundStyle(.wizFaint)
                    }
                }
                .font(.system(.caption2, design: .monospaced))
            }
        }
        .onAppear { engine.requestWaveform(for: mic) }
    }

    @ViewBuilder
    private var waveformOrPlaceholder: some View {
        if let peaks = engine.micWaveforms[mic.id] {
            Canvas { ctx, size in
                let mid = size.height / 2
                let slot = Self.barWidth + Self.barGap
                let count = max(1, Int(size.width / slot))
                let bucketsPerBar = max(1, peaks.count / count)
                let playedX: CGFloat? = {
                    guard let t = engine.playbackTime(for: mic.id),
                          mic.durationSeconds > 0 else { return nil }
                    return size.width * CGFloat(t / mic.durationSeconds)
                }()

                // Sample-Peak + sqrt: am echten Material die klarste Darstellung
                // (RMS/Mittelwert und dB-Mapping sahen flacher aus — Log hebt
                // leise Passagen an und nimmt genau da Kontrast, wo man ihn will).
                for i in 0..<count {
                    let start = i * bucketsPerBar
                    let end = min(peaks.count, start + bucketsPerBar)
                    guard start < end else { break }
                    let p = peaks[start..<end].max() ?? 0
                    let amp = max(1.5, CGFloat(Double(p).squareRoot()) * (mid - 2))
                    let x = CGFloat(i) * slot + Self.barWidth / 2
                    var bar = Path()
                    bar.move(to: CGPoint(x: x, y: mid - amp))
                    bar.addLine(to: CGPoint(x: x, y: mid + amp))
                    let played = playedX.map { x <= $0 } ?? false
                    ctx.stroke(bar,
                               with: .color(played ? Color.brandAccent
                                                   : Color.secondary.opacity(0.45)),
                               style: StrokeStyle(lineWidth: Self.barWidth, lineCap: .round))
                }

                if let px = playedX {
                    let r: CGFloat = 4.5
                    ctx.fill(Path(ellipseIn: CGRect(x: min(max(px - r, 0), size.width - 2 * r),
                                                    y: mid - r, width: 2 * r, height: 2 * r)),
                             with: .color(Color.brandAccent))
                }
            }
        } else {
            RoundedRectangle(cornerRadius: 4)
                .fill(Color.wizBorder.opacity(0.35))
                .overlay(
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini)
                        Text("Computing waveform … "
                             + "\(engine.waveformProgress[mic.id] ?? 0) %")
                            .font(.caption2).foregroundStyle(.wizFaint)
                    }
                )
        }
    }

    private static func fmt(_ seconds: Double) -> String {
        let t = Int(seconds.rounded())
        if t >= 3600 {
            return String(format: "%d:%02d:%02d", t / 3600, (t % 3600) / 60, t % 60)
        }
        return String(format: "%d:%02d", t / 60, t % 60)
    }
}

// MARK: - Screen 2: Kameras

struct CamerasStep: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            WizardIntro(title: "Who's on which camera?",
                        text: "Drag each person onto every camera that shows them. The app figures out "
                            + "on its own whether a camera is a close-up or a wide shot — you don't "
                            + "have to label anything.")

            if !engine.fpsMismatches.isEmpty { FpsMismatchBanner() }
            if !engine.suspiciouslyShortCams.isEmpty { ShortCamBanner() }
            if !engine.unsupportedCloseCams.isEmpty { UnsupportedCloseCamsBanner() }

            HStack(alignment: .top, spacing: 26) {
                VStack(alignment: .leading, spacing: 12) {
                    railTitle("People")
                    ForEach(engine.persons) { p in
                        PersonToken(person: p)
                    }
                    Text("Drag a person onto every camera that shows them. Multiple assignments allowed.")
                        .font(.caption2).foregroundStyle(.wizFaint)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 4)
                }
                .frame(width: 200)

                VStack(alignment: .leading, spacing: 12) {
                    railTitle("Cameras")
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 210, maximum: 260), spacing: 16)],
                              alignment: .leading, spacing: 16) {
                        ForEach(engine.activeCams) { cam in
                            WizardCamCard(cam: cam)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            if !engine.excludedCams.isEmpty {
                WizRestoreChips(title: "Hidden cameras",
                                items: engine.excludedCams.map { (id: $0.id, name: $0.displayName) },
                                restore: { engine.setCamIncluded($0, true) })
            }
        }
        .frame(maxWidth: WizardLayout.contentWidth, alignment: .leading)
    }

    private func railTitle(_ t: String) -> some View {
        Text(t.uppercased()).font(.caption2).fontWeight(.bold)
            .foregroundStyle(.wizFaint).tracking(1)
    }
}

struct PersonToken: View {
    let person: Person
    @EnvironmentObject var engine: EngineController

    private var placed: Bool { engine.activeCams.contains { $0.assignedMics.contains(person.id) } }

    var body: some View {
        HStack(spacing: 9) {
            avatar(person.id, person.name, size: 26, engine)
            Text(person.name).font(.system(size: 14)).lineLimit(1)
            if !placed { Text("· free").font(.caption2).foregroundStyle(.brandSecondary) }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 6).padding(.horizontal, 8)
        .background(Color.wizSurface, in: Capsule())
        .overlay(Capsule().stroke(
            placed ? Color.wizBorder : Color.brandSecondary.opacity(0.5), lineWidth: 1))
        .contentShape(Capsule())
        .onDrag { NSItemProvider(object: String(person.id) as NSString) }
    }
}

struct WizardCamCard: View {
    let cam: CameraInfo
    @EnvironmentObject var engine: EngineController
    @State private var targeted = false

    private var role: EngineController.CamRole { engine.camRoles()[cam.id] ?? .unused }
    private var assigned: [Person] {
        // LIVE aus dem Engine-State lesen, NICHT aus dem `cam`-Snapshot: CameraInfo ist
        // per id gleich (custom `==`), daher frischt SwiftUI den Snapshot nicht auf,
        // wenn sich nur assignedMics ändert → Pills erschienen sonst erst nach Rückkehr.
        let live = engine.cameraInfos.first { $0.id == cam.id }?.assignedMics ?? []
        return live.compactMap { pid in engine.persons.first { $0.id == pid } }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScrubbableThumbnail(videoPath: cam.path,
                                initialThumbnailPath: cam.thumbnailPath,
                                durationSeconds: cam.durationSeconds)
                .overlay(alignment: .topTrailing) { rolePill }

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    Text(cam.displayName).font(.subheadline).fontWeight(.medium).lineLimit(1)
                    Spacer(minLength: 4)
                    Button { engine.setCamIncluded(cam.id, false) } label: {
                        LucideIcon("trash-2", size: 12).foregroundStyle(.wizMuted)
                    }
                    .buttonStyle(.plain)
                    .help("This camera isn't part of the project — remove")
                }

                // FPS-Mismatch direkt AN der betroffenen Karte zeigen — sonst
                // weiß man nur "irgendeine Kamera passt nicht" und muss suchen.
                if engine.isFpsMismatch(cam) {
                    HStack(spacing: 4) {
                        LucideIcon("triangle-alert", size: 9)
                        Text(cam.fps > 0
                             ? "\(Self.fmtFps(cam.fps)) fps — Project: \(Self.fmtFps(engine.fps))"
                             : "Frame rate unreadable")
                            .font(.caption2)
                    }
                    .foregroundStyle(.orange)
                    .help("This camera doesn't match the project frame rate. When the "
                          + "analysis starts, you'll be offered a conversion.")
                }

                if assigned.isEmpty {
                    Text("Drag a person here").font(.caption).foregroundStyle(.wizFaint).padding(.vertical, 2)
                } else {
                    FlowLayout(spacing: 6) {
                        ForEach(assigned) { p in personChip(p) }
                    }
                }

                Button { engine.setCamShowsAllPersons(cam.id) } label: {
                    Text("shows everyone").font(.caption2).frame(maxWidth: .infinity)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.wizMuted)
                .padding(.vertical, 5)
                .overlay(RoundedRectangle(cornerRadius: 7)
                    .stroke(Color.wizBorder, style: StrokeStyle(lineWidth: 1, dash: [3])))
            }
            .padding(11)
        }
        .background(Color.wizSurface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14)
            .stroke(targeted ? Color.brandAccent : Color.wizBorder, lineWidth: targeted ? 2 : 0.5))
        .onDrop(of: [UTType.plainText], isTargeted: $targeted) { providers in
            guard let provider = providers.first else { return false }
            provider.loadItem(forTypeIdentifier: UTType.plainText.identifier, options: nil) { item, _ in
                guard let data = item as? Data,
                      let str = String(data: data, encoding: .utf8),
                      let pid = Int(str) else { return }
                DispatchQueue.main.async { engine.addPersonToCam(pid, cam.id) }
            }
            return true
        }
    }

    /// "25" statt "25.000", "23.976" bleibt "23.976".
    private static func fmtFps(_ v: Double) -> String {
        String(format: "%.3f", v)
            .replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }

    @ViewBuilder private var rolePill: some View {
        switch role {
        case .wide:
            LucideLabel("Wide", icon: "columns-2", size: 10)
                .font(.caption2.weight(.medium)).lineLimit(1).fixedSize()
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(Color.brandSecondary).foregroundStyle(.black)
                .clipShape(Capsule()).padding(6)
        case .close:
            Text("Close").font(.caption2.weight(.medium))
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(Color.brandAccent.opacity(0.18)).foregroundStyle(Color.brandAccent)
                .clipShape(Capsule()).padding(6)
        case .unused:
            EmptyView()
        }
    }

    private func personChip(_ p: Person) -> some View {
        HStack(spacing: 5) {
            avatar(p.id, p.name, size: 18, engine)
            Text(p.name).font(.caption2).lineLimit(1)
            Button { engine.removePersonFromCam(p.id, cam.id) } label: {
                LucideIcon("x", size: 8).foregroundStyle(.wizMuted)
            }
            .buttonStyle(.plain)
        }
        .padding(.leading, 3).padding(.trailing, 6).padding(.vertical, 3)
        .background(Color.wizSurface2, in: Capsule())
    }
}

// (WizardRoleLegend entfernt — die Nah/Totale-Pills auf den Cards sagen es bereits.)

// MARK: - FPS-Mismatch-Banner (eigenständig — auch vom Wizard genutzt)

struct FpsMismatchBanner: View {
    @EnvironmentObject var engine: EngineController

    private func fpsText(_ v: Double) -> String {
        v <= 0 ? "?" : (v.rounded() == v ? String(Int(v)) : String(format: "%.2f", v))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                LucideIcon("triangle-alert", size: 14)
                Text("Wrong frame rate").fontWeight(.semibold)
            }
            .foregroundStyle(.brandSecondary)

            Text("These cameras don't have the timeline frame rate (\(fpsText(engine.fps))). Without "
                 + "correction, picture and sound drift apart and the timeline ends on a freeze frame.")
                .font(.caption).foregroundStyle(.wizMuted)
                .fixedSize(horizontal: false, vertical: true)

            ForEach(engine.fpsMismatches) { cam in
                Text("• \(cam.displayName) — \(fpsText(cam.fps)) fps")
                    .font(.system(.caption, design: .monospaced))
            }

            Button { engine.convertMismatchedFps() } label: {
                LucideLabel("Convert file(s) to \(fpsText(engine.fps)) fps",
                            icon: "refresh-cw", size: 12)
            }
            .buttonStyle(.borderedProminent).controlSize(.small)

            Text("Creates copies next to the originals (practically lossless, timecode is preserved). "
                 + "Takes a while depending on file size — roughly 10 minutes per GB.")
                .font(.caption2).foregroundStyle(.wizFaint)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.brandSecondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.brandSecondary.opacity(0.4), lineWidth: 1))
    }
}

// MARK: - Warnung: auffällig kurze Kamera

struct ShortCamBanner: View {
    @EnvironmentObject var engine: EngineController

    private func mins(_ s: Double) -> String {
        let m = Int(s) / 60, sec = Int(s) % 60
        return m > 0 ? "\(m):\(String(format: "%02d", sec)) min" : "\(sec) s"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                LucideIcon("triangle-alert", size: 14)
                Text("Unusually short camera").fontWeight(.semibold)
            }
            .foregroundStyle(.brandSecondary)

            Text("This camera is much shorter than the other sources. From the point "
                 + "where it ends, its picture freezes — the cut gets a freeze frame "
                 + "there. If that's unintended (for example a canceled conversion whose "
                 + "partial file was left behind), replace the file with the complete one. If the "
                 + "camera really was only active for a shorter time, you can continue — but watch for the "
                 + "freeze frame from its end.")
                .font(.caption).foregroundStyle(.wizMuted)
                .fixedSize(horizontal: false, vertical: true)

            ForEach(engine.suspiciouslyShortCams) { cam in
                Text("• \(cam.displayName) — \(mins(cam.durationSeconds))")
                    .font(.system(.caption, design: .monospaced))
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.brandSecondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.brandSecondary.opacity(0.4), lineWidth: 1))
    }
}

// MARK: - Warnung: mehr als 2 Kameras (Sync deckt nur die ersten beiden ab)

struct UnsupportedCloseCamsBanner: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                LucideIcon("triangle-alert", size: 14)
                Text("More than 2 close-up cameras — not yet supported").fontWeight(.semibold)
            }
            .foregroundStyle(.brandSecondary)

            Text("Speaker detection compares exactly two close-up cameras. A third "
                 + "would never get its turn as speaker — the person on it would stay "
                 + "silent in the edit, without anything failing. That's why the start is locked.\n\n"
                 + "Wide shots aren't affected: any number is allowed and they're "
                 + "used for cutaways.")
                .font(.caption).foregroundStyle(.wizMuted)
                .fixedSize(horizontal: false, vertical: true)

            Text("This would affect:").font(.caption).foregroundStyle(.wizFaint).padding(.top, 2)
            ForEach(engine.unsupportedCloseCams) { cam in
                Text("• \(cam.displayName)")
                    .font(.system(.caption, design: .monospaced))
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.brandSecondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.brandSecondary.opacity(0.4), lineWidth: 1))
    }
}

// MARK: - Screen 3: Übersicht & Start

struct OverviewStep: View {
    @EnvironmentObject var engine: EngineController
    // Hover ueber dem „Ordner bekannt"-Banner pausiert dessen Selbst-Ausblenden
    // (Ring im CountdownDismissButton), damit wer liest nicht ueberrascht wird.
    @State private var bannerHovering = false

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            // Beim Wieder-Oeffnen eines bekannten Ordners springt der Wizard direkt
            // hierher — ohne Erklaerung wirkt das wie ein Fehler (Fremd-Feedback).
            if engine.sessionRestored {
                HStack(alignment: .top, spacing: 10) {
                    LucideIcon("history", size: 15)
                        .foregroundStyle(Color.brandAccent)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Folder recognized — assignments loaded").fontWeight(.semibold)
                        Text("The app has restored your earlier people, cameras, and settings "
                             + "for this folder. Using the steps above, you can "
                             + "change anything at any time.")
                            .font(.caption).foregroundStyle(.wizMuted)
                            .fixedSize(horizontal: false, vertical: true)
                        Button("Reset assignments") { engine.resetSession() }
                            .buttonStyle(.plain)
                            .font(.caption)
                            .underline()
                            .foregroundStyle(Color.brandAccent)
                            .padding(.top, 2)
                            .help("Deletes the saved assignments (.multicam) and starts over")
                    }
                    Spacer()
                    // X mit ablaufendem Ring: zeigt, wann sich das Banner selbst
                    // schliesst. Uebernimmt das Auto-Ausblenden (kein separater
                    // .autoDismiss mehr — sonst zwei Timer). Hover pausiert.
                    CountdownDismissButton(paused: $bannerHovering) {
                        engine.sessionRestored = false
                    }
                    .foregroundStyle(.wizMuted)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.brandAccent.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.brandAccent.opacity(0.35), lineWidth: 1))
                .transition(.opacity)
                // Fluechtige Info (Design-System): der Reset-Link verschwindet mit
                // dem Ausblenden bis zum naechsten Start — ok (User-Entscheid 24.07.).
                .onHover { bannerHovering = $0 }
            }

            WizardIntro(title: "Does everything look right?",
                        text: "The app derived this from your assignments — shot sizes included. "
                            + "If something's wrong, go back a step and fix it. Otherwise: start the analysis.")

            HStack(alignment: .top, spacing: 22) {
                VStack(alignment: .leading, spacing: 12) {
                    sectionTitle("Shot sizes per person")
                    if engine.persons.isEmpty {
                        Text("No people.").font(.callout).foregroundStyle(.wizMuted)
                    }
                    ForEach(engine.persons) { p in LadderRow(person: p) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                VStack(alignment: .leading, spacing: 12) {
                    sectionTitle("Cameras")
                    ForEach(engine.activeCams) { cam in CamSummaryRow(cam: cam) }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            derivedNote

            WizardSettings()
        }
        .frame(maxWidth: WizardLayout.contentWidth, alignment: .leading)
    }

    private var derivedNote: some View {
        let totalen = engine.activeCams.filter { engine.camRoles()[$0.id] == .wide }.count
        let n = engine.persons.count
        let c = engine.activeCams.count
        return (
            Text("Automatically detected: ").fontWeight(.semibold).foregroundStyle(Color.brandSecondary)
            + Text("\(n) speaker\(n == 1 ? "" : "s"), \(c) camera\(c == 1 ? "" : "s"), "
                 + "\(totalen) wide shot\(totalen == 1 ? "" : "s"). A camera with several people stays "
                 + "a close-up as long as it frames one of them tightest — only once "
                 + "everyone is closer elsewhere does it become a wide shot.").foregroundStyle(Color.wizMuted)
        )
        .font(.callout)
        .fixedSize(horizontal: false, vertical: true)
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.brandSecondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.brandSecondary.opacity(0.25), lineWidth: 1))
    }

    private func sectionTitle(_ t: String) -> some View {
        Text(t.uppercased()).font(.caption2).fontWeight(.bold)
            .foregroundStyle(.wizFaint).tracking(1)
    }
}

struct LadderRow: View {
    let person: Person
    @EnvironmentObject var engine: EngineController

    var body: some View {
        let ladder = engine.shotLadder(for: person.id)
        let roles = engine.camRoles()
        HStack(alignment: .top, spacing: 12) {
            HStack(spacing: 9) {
                avatar(person.id, person.name, size: 30, engine)
                Text(person.name).font(.system(size: 14.5, weight: .semibold))
            }
            .frame(width: 150, alignment: .leading)

            if ladder.isEmpty {
                Text("no camera").font(.caption).foregroundStyle(.brandSecondary)
            } else {
                FlowLayout(spacing: 7) {
                    ForEach(Array(ladder.enumerated()), id: \.offset) { i, cam in
                        shotChip(cam, wide: roles[cam.id] == .wide, tag: tag(i, ladder.count))
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(11)
        .background(Color.wizSurface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.wizBorder, lineWidth: 1))
    }

    private func tag(_ i: Int, _ count: Int) -> String {
        if i == 0 { return "tightest" }
        if i == count - 1 { return "widest" }
        return "wider"
    }

    private func shotChip(_ cam: CameraInfo, wide: Bool, tag: String) -> some View {
        HStack(spacing: 5) {
            // Breite cappen, sonst nimmt die Pill in der FlowLayout die volle
            // intrinsische Breite des Dateinamens und ragt aus dem Container.
            // Mittig kürzen behält Anfang UND Endung (…_25fps.mp4) sichtbar.
            Text(cam.displayName).font(.system(.caption2, design: .monospaced))
                .lineLimit(1).truncationMode(.middle)
                .frame(maxWidth: 180, alignment: .leading)
            Text(tag).font(.system(size: 9)).opacity(0.7)
        }
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background((wide ? Color.brandSecondary : Color.brandAccent).opacity(0.14),
                    in: RoundedRectangle(cornerRadius: 8))
        .foregroundStyle(wide ? Color.brandSecondary : Color.brandAccent)
        .overlay(RoundedRectangle(cornerRadius: 8)
            .stroke((wide ? Color.brandSecondary : Color.brandAccent).opacity(0.3), lineWidth: 1))
    }
}

struct CamSummaryRow: View {
    let cam: CameraInfo
    @EnvironmentObject var engine: EngineController

    var body: some View {
        let role = engine.camRoles()[cam.id] ?? .unused
        let who = cam.assignedMics
            .compactMap { pid in engine.persons.first { $0.id == pid }?.name }
            .joined(separator: ", ")
        HStack(spacing: 10) {
            Text(cam.displayName).font(.system(.caption, design: .monospaced)).frame(width: 96, alignment: .leading)
            Text(who.isEmpty ? "—" : who).font(.caption).foregroundStyle(.wizMuted)
                .lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
            rolePill(role)
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(Color.wizSurface, in: RoundedRectangle(cornerRadius: 9))
        .overlay(RoundedRectangle(cornerRadius: 9).stroke(Color.wizBorder, lineWidth: 1))
    }

    @ViewBuilder private func rolePill(_ role: EngineController.CamRole) -> some View {
        switch role {
        case .wide:
            Text("Wide").font(.caption2.weight(.semibold))
                .padding(.horizontal, 8).padding(.vertical, 2)
                .background(Color.brandSecondary).foregroundStyle(.black).clipShape(Capsule())
        case .close:
            Text("Close").font(.caption2.weight(.semibold))
                .padding(.horizontal, 8).padding(.vertical, 2)
                .background(Color.brandAccent.opacity(0.16)).foregroundStyle(Color.brandAccent).clipShape(Capsule())
        case .unused:
            Text("Unused").font(.caption2)
                .padding(.horizontal, 8).padding(.vertical, 2)
                .foregroundStyle(.wizFaint)
                .overlay(Capsule().stroke(Color.wizBorder, lineWidth: 1))
        }
    }
}

// MARK: - Footer-Navigation

struct WizardFooter: View {
    @EnvironmentObject var engine: EngineController

    /// Warum der Start (noch) nicht geht — nil = bereit.
    private var startBlockedReason: String? {
        if engine.activeCams.count < 2 { return "At least 2 cameras needed" }
        if engine.persons.isEmpty { return "At least one person needed" }
        if engine.analysisCams.count < 2 { return "At least 2 cameras need a person" }
        if !engine.fpsMismatches.isEmpty { return "Frame rate differs — please fix above" }
        // Die Diarisierung vergleicht genau zwei NAH-Kameras; eine dritte bliebe
        // stumm. Totalen sind erlaubt (siehe UnsupportedCloseCamsBanner).
        if !engine.unsupportedCloseCams.isEmpty { return "More than 2 close-up cameras — not yet supported" }
        if !engine.unassignedMics.isEmpty { return "Every person needs at least one camera" }
        return nil
    }

    var body: some View {
        HStack(spacing: 14) {
            Button("Back") { go(-1) }
                .buttonStyle(WizSecondaryButton())
                .disabled(engine.wizardStep == .persons)
                .opacity(engine.wizardStep == .persons ? 0.4 : 1)

            FeedbackButton()   // Bug/Feedback melden — jetzt im Footer neben „Zurück"

            Spacer()

            if engine.wizardStep == .overview {
                if let reason = startBlockedReason {
                    Text(reason).font(.caption).foregroundStyle(.brandSecondary)
                }
                WizPresetDropdown()
                Button { engine.start() } label: {
                    LucideLabel("Start analysis", icon: "play", size: 14)
                }
                .buttonStyle(WizPrimaryButton())
                .disabled(startBlockedReason != nil)
                .opacity(startBlockedReason == nil ? 1 : 0.4)
            } else {
                Button { go(1) } label: { Text("Next").frame(minWidth: 70) }
                    .buttonStyle(WizPrimaryButton())
            }
        }
        .padding(.horizontal, 24).padding(.vertical, 12)
        .background(Color.wizBg)
    }

    private func go(_ delta: Int) {
        let next = engine.wizardStep.rawValue + delta
        if let step = WizardStep(rawValue: next) { engine.wizardStep = step }
    }
}

// MARK: - Einstellungen (Variante C)
//
// Kuratierte Einfach-Ansicht (immer sichtbar). Der Textlink „Experteneinstellungen"
// TAUSCHT den ganzen Inhalt gegen die volle Liste in ihren Rubriken (kein Anhängen,
// kein Experten-Toggle). Beide Ansichten schreiben in denselben `engine.params`.

struct WizardSettings: View {
    @EnvironmentObject var engine: EngineController
    @State private var expert = false
    /// Nicken-Muster (Name + Default-enabled) aus nodding_patterns.json — für die
    /// Pattern-Toggles in „Cutaway Regeln". Die tatsächlichen Werte liegen PRO PRESET
    /// in engine.params.noddingPatterns.
    @State private var noddingPatternDefs: [(name: String, enabled: Bool)] = []

    private var columns: [GridItem] {
        [GridItem(.flexible(), spacing: 40), GridItem(.flexible(), spacing: 40)]
    }

    private func loadPatternDefs() async {
        guard let np = await engine.getNoddingPatterns(),
              let data = np.content.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pats = obj["patterns"] as? [[String: Any]] else { return }
        noddingPatternDefs = pats.map { (name: $0["name"] as? String ?? "?",
                                         enabled: $0["enabled"] as? Bool ?? true) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Settings").font(.headline).padding(.bottom, 10)
            Rectangle().fill(Color.wizBorder).frame(height: 1)

            if expert { expertList } else { simpleList }

            Button {
                withAnimation(.easeInOut(duration: 0.15)) { expert.toggle() }
            } label: {
                HStack(spacing: 6) {
                    if expert { LucideIcon("chevron-up", size: 9) }
                    Text(expert ? "Simple view" : "Expert settings")
                    if !expert { LucideIcon("chevron-down", size: 9) }
                }
                .font(.system(size: 13.5, weight: .medium))
                .foregroundStyle(.brandSecondary)
            }
            .buttonStyle(.plain)
            .padding(.top, 12)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .background(Color.wizSurface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.wizBorder, lineWidth: 1))
        .task { await loadPatternDefs() }
    }

    // Kuratierte 8 Essentials
    private var simpleList: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 0) {
            WizSlider("Min. shot length", $engine.params.minShot, 0.5...10, suffix: " s", help: ParamHelp.minShot)
            WizSlider("Cutaway length", $engine.params.reactionDur, 0.5...5, suffix: " s", help: ParamHelp.reactionDur)
            WizToggle("Speech detection", $engine.params.speakingEnabled, help: ParamHelp.speakingEnabled)
            WizToggle("Detect head nods", $engine.params.noddingEnabled, help: ParamHelp.noddingEnabled)
            WizToggle("Trim pauses", $engine.params.pauseTrimEnabled, help: ParamHelp.pauseTrimEnabled)
            WizToggle("Pause cutaways", $engine.params.pauseCutawayEnabled, help: ParamHelp.pauseCutawayEnabled)
            WizSlider("Threshold", $engine.params.thresholdDb, 0.5...20, suffix: " dB", help: ParamHelp.thresholdDb)
            WizSlider("Max. shot length", $engine.params.maxShot, 1...60, suffix: " s", help: ParamHelp.maxShot)
        }
    }

    // Volle Liste — Rubriken/Benennung/Reihenfolge 1:1 wie die Web-UI im Expertmode
    // (config/schemas/multicam_params.json). Ausnahme: LUT ist „auf Halde" (Brain).
    private var expertList: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                group("General cut rules", first: true) {
                    WizSlider("Min. shot length", $engine.params.minShot, 0.5...10, suffix: " s", help: ParamHelp.minShot)
                    WizSlider("Min. cleanup length", $engine.params.cleanupDur, 0.1...5, suffix: " s", help: ParamHelp.cleanupDur)
                    WizSlider("Max. shot length", $engine.params.maxShot, 1...60, suffix: " s", help: ParamHelp.maxShot)
                }
                group("Speaker detection") {
                    WizSlider("Threshold", $engine.params.thresholdDb, 0.5...20, suffix: " dB", help: ParamHelp.thresholdDb)
                    WizSlider("Min. segment length", $engine.params.minEdit, 0.1...5, suffix: " s", help: ParamHelp.minEdit)
                    WizSlider("Change delay", $engine.params.changeDelay, 0...2, suffix: " s", help: ParamHelp.changeDelay)
                }
                group("Pause trimming") {
                    WizToggle("Trim pauses", $engine.params.pauseTrimEnabled, help: ParamHelp.pauseTrimEnabled)
                    WizSlider("Max. pause", $engine.params.maxPause, 0.1...3, suffix: " s", help: ParamHelp.maxPause)
                    WizSlider("Silence threshold", $engine.params.pauseSilenceDb, -80...(-10), suffix: " dB", format: "%.0f", help: ParamHelp.pauseSilenceDb)
                    // Werte 1:1 aus dem Schema/der Pipeline (pause_trim_edl.py):
                    // middle | l-cut | j-cut | random — NICHT none/end.
                    WizSegmented("Cut mode", $engine.params.pauseCutMode,
                                 options: [("middle", "Middle"), ("l-cut", "L-Cut"),
                                           ("j-cut", "J-Cut"), ("random", "Random")],
                                 help: ParamHelp.pauseCutMode)
                }
                group("Crossbleed filter") {
                    WizToggle("Crossbleed gate", $engine.params.crossbleedGateEnabled, help: ParamHelp.crossbleedGateEnabled)
                    WizSlider("Attenuation", $engine.params.gateFloor, -60...(-5), suffix: " dB", format: "%.0f", help: ParamHelp.gateFloor)
                    WizSlider("Hysteresis", $engine.params.gateHysteresis, 0.5...10, suffix: " dB", help: ParamHelp.gateHysteresis)
                    WizSlider("Window", $engine.params.gateWindow, 20...500, suffix: " ms", format: "%.0f", help: ParamHelp.gateWindow)
                    WizSlider("Attack", $engine.params.gateAttack, 1...200, suffix: " ms", format: "%.0f", help: ParamHelp.gateAttack)
                    WizSlider("Release", $engine.params.gateRelease, 10...500, suffix: " ms", format: "%.0f", help: ParamHelp.gateRelease)
                    WizSlider("Simultaneous threshold", $engine.params.gateBothThreshold, 0.5...10, suffix: " dB", help: ParamHelp.gateBothThreshold)
                }
                // Allgemeine Cutaway-Regeln (gelten für ALLE Cutaway-Typen)
                group("Cutaway rules") {
                    WizSlider("Cutaway length", $engine.params.reactionDur, 0.5...5, suffix: " s", help: ParamHelp.reactionDur)
                    WizSlider("Pre-roll", Binding(
                        get: { Double(engine.params.preRoll) },
                        set: { engine.params.preRoll = Int($0) }), 0...50, suffix: " f", format: "%.0f",
                                  help: ParamHelp.preRoll)
                    WizSlider("Randomness", $engine.params.randomness, 0...0.5, format: "%.2f", help: ParamHelp.randomness)
                    WizToggle("Move unsuitable cutaways", $engine.params.clipFilterEnabled, help: ParamHelp.clipFilterEnabled)
                    WizSegmented("Multiple wide shots", $engine.params.totaleMode,
                                 options: [("round_robin", "Round-robin"), ("random", "Random"),
                                           ("first", "First only")],
                                 help: ParamHelp.totaleMode)
                }
                // Je Cutaway-Typ eine eigene Rubrik: Master-Toggle + NUR die Parameter,
                // die wirklich dazugehören.
                group("Head nods") {
                    WizToggle("Enabled", $engine.params.noddingEnabled, help: ParamHelp.noddingEnabled)
                    WizSlider("Min. confidence", Binding(
                        get: { engine.params.minConf * 100 },
                        set: { engine.params.minConf = $0 / 100 }), 0...100, suffix: " %", format: "%.0f",
                                  help: ParamHelp.minConf)
                }
                // Muster-Toggles — PRO PRESET (engine.params.noddingPatterns), dynamisch
                // aus nodding_patterns.json. Gehören zu „Kopfnicken".
                if !noddingPatternDefs.isEmpty {
                    subLabel("Patterns")
                    LazyVGrid(columns: columns, alignment: .leading, spacing: 0) {
                        ForEach(noddingPatternDefs, id: \.name) { pat in
                            WizToggle(pat.name.replacingOccurrences(of: "_", with: " ").capitalized,
                                      Binding(get: { engine.params.noddingPatterns[pat.name] ?? pat.enabled },
                                              set: { engine.params.noddingPatterns[pat.name] = $0 }))
                        }
                    }
                }
                group("Interjections") {
                    WizToggle("Enabled", $engine.params.speakingEnabled, help: ParamHelp.speakingEnabled)
                    WizSlider("Rise", $engine.params.riseDb, 1...20, suffix: " dB", help: ParamHelp.riseDb)
                    WizSlider("Max. cutaway length", $engine.params.speakingMaxDur, 0.5...10, suffix: " s", help: ParamHelp.speakingMaxDur)
                }
                group("Silence") {
                    WizToggle("Enabled", $engine.params.pauseCutawayEnabled, help: ParamHelp.pauseCutawayEnabled)
                    WizSlider("Min. pause length", $engine.params.pauseCutawayMinPause, 0.5...10, suffix: " s", help: ParamHelp.pauseCutawayMinPause)
                }
                // Bildsprache: nur wenn es eine größere Einstellung gibt — sonst
                // haben die Übergänge keine gemeinsame Kamera und wären wirkungslos.
                if engine.hasWideCamera {
                    group("Visual language", description: ParamHelp.bildspracheIntro) {
                        WizToggle("Transition on speaker change", $engine.params.transitionSpeakerChange,
                                  help: ParamHelp.transitionSpeakerChange)
                        WizSlider("Transition threshold", $engine.params.transitionReturnFactor,
                                  1.5...4.0, suffix: "×", format: "%.1f",
                                  help: ParamHelp.transitionReturnFactor)
                    }
                    subLabel("Return after cutaway via a wider shot")
                    LazyVGrid(columns: columns, alignment: .leading, spacing: 0) {
                        WizToggle("After head nod", $engine.params.transitionCutawayNodding,
                                  help: ParamHelp.transitionCutawayNodding)
                        WizToggle("After interjection", $engine.params.transitionCutawaySpeaking,
                                  help: ParamHelp.transitionCutawaySpeaking)
                        WizToggle("After pause", $engine.params.transitionCutawayPause,
                                  help: ParamHelp.transitionCutawayPause)
                    }
                    LazyVGrid(columns: columns, alignment: .leading, spacing: 0) {
                        WizSlider("Cooldown (cuts)", Binding(
                            get: { Double(engine.params.transitionCutawayCooldown) },
                            set: { engine.params.transitionCutawayCooldown = Int($0) }),
                                  0...20, suffix: "", format: "%.0f",
                                  help: ParamHelp.transitionCutawayCooldown)
                        WizSlider("Cooldown (time)", $engine.params.transitionCutawayCooldownS,
                                  0...30, suffix: " s", format: "%.0f",
                                  help: ParamHelp.transitionCutawayCooldownS)
                    }
                }
            }
        }
        .frame(maxHeight: 300)
    }

    @ViewBuilder
    private func group<C: View>(_ title: String, first: Bool = false, description: String = "",
                                @ViewBuilder _ content: () -> C) -> some View {
        // Trennlinie über jeder Rubrik (wie unter „Einstellungen") — außer der ersten,
        // die direkt unter der Einstellungen-Trennlinie sitzt.
        if !first {
            Rectangle().fill(Color.wizBorder).frame(height: 1).padding(.top, 16)
        }
        Text(title.uppercased())
            .font(.caption2).fontWeight(.bold).foregroundStyle(.brandSecondary).tracking(0.8)
            .padding(.top, first ? 16 : 12).padding(.bottom, 2)
        // Optionaler Einleitungstext für Rubriken, deren Sinn sich nicht aus den
        // Parameternamen erschließt (z.B. Bildsprache).
        if !description.isEmpty {
            Text(description)
                .font(.caption2).foregroundStyle(.wizMuted)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.bottom, 6)
        }
        LazyVGrid(columns: columns, alignment: .leading, spacing: 0) { content() }
    }

    @ViewBuilder
    private func subLabel(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.caption2).fontWeight(.semibold).foregroundStyle(.wizMuted).tracking(0.8)
            .padding(.top, 12).padding(.bottom, 2)
    }
}

// ── Slider-/Toggle-Zeilen (2-spaltig, Label nah am Wert) ──

/// Kleines (?) neben einem Parameter. Zeigt den Hilfetext als nativen Tooltip beim
/// Überfahren (macOS `.help`). Nur sichtbar, wenn ein Text hinterlegt ist.
struct WizHelpBadge: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        LucideIcon("circle-question-mark", size: 12)
            .foregroundStyle(.wizFaint)
            .help(text)
    }
}

struct WizSlider: View {
    let label: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    var suffix: String = ""
    var format: String = "%.1f"
    var help: String = ""

    init(_ label: String, _ value: Binding<Double>, _ range: ClosedRange<Double>,
         suffix: String = "", format: String = "%.1f", help: String = "") {
        self.label = label; self._value = value; self.range = range
        self.suffix = suffix; self.format = format; self.help = help
    }

    var body: some View {
        HStack(spacing: 12) {
            Text(label).font(.system(size: 14)).lineLimit(1)
            if !help.isEmpty { WizHelpBadge(help) }
            Spacer(minLength: 8)
            WizSliderControl(value: $value, range: range)
            Text(String(format: format, value).replacingOccurrences(of: ".", with: ",") + suffix)
                .font(.system(.caption, design: .monospaced)).foregroundStyle(.wizMuted)
                .frame(width: 54, alignment: .trailing)
        }
        .padding(.vertical, 9)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Color.wizBorder.opacity(0.5)).frame(height: 0.5)
        }
    }
}

struct WizToggle: View {
    let label: String
    @Binding var isOn: Bool
    var help: String = ""

    init(_ label: String, _ isOn: Binding<Bool>, help: String = "") {
        self.label = label; self._isOn = isOn; self.help = help
    }

    var body: some View {
        HStack {
            Text(label).font(.system(size: 14)).lineLimit(1)
            if !help.isEmpty { WizHelpBadge(help) }
            Spacer()
            WizSwitch(isOn: $isOn)
        }
        .padding(.vertical, 7)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Color.wizBorder.opacity(0.5)).frame(height: 0.5)
        }
    }
}

/// Mehrfachumschalter (Segmented) im Wizard-Look — statt eines System-Dropdowns.
/// Aktives Segment in Lime mit schwarzer Schrift, Rest gedämpft. Zeilen-Stil wie
/// WizSlider/WizToggle (Label · Control · Unterstrich).
struct WizSegmented: View {
    let label: String
    @Binding var selection: String
    let options: [(value: String, display: String)]
    var help: String = ""

    init(_ label: String, _ selection: Binding<String>, options: [(String, String)], help: String = "") {
        self.label = label; self._selection = selection
        self.options = options.map { (value: $0.0, display: $0.1) }
        self.help = help
    }

    var body: some View {
        HStack(spacing: 12) {
            Text(label).font(.system(size: 14)).lineLimit(1)
            if !help.isEmpty { WizHelpBadge(help) }
            Spacer(minLength: 8)
            HStack(spacing: 2) {
                ForEach(options, id: \.value) { opt in
                    let active = selection == opt.value
                    Text(opt.display)
                        .font(.system(size: 11.5, weight: active ? .semibold : .regular))
                        .foregroundStyle(active ? Color.black : Color.wizMuted)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(active ? Color.brandAccent : Color.clear,
                                    in: RoundedRectangle(cornerRadius: 6))
                        .contentShape(Rectangle())
                        .onTapGesture { selection = opt.value }
                }
            }
            .padding(2)
            .background(Color.wizSurface2, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.wizBorder2, lineWidth: 1))
        }
        .padding(.vertical, 7)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Color.wizBorder.opacity(0.5)).frame(height: 0.5)
        }
    }
}

/// Toggle im Dummy-Look: Capsule + Knopf, Lime an / graue Spur aus. Native
/// `Toggle(.switch)` sah zu system-grau/blau aus.
struct WizSwitch: View {
    @Binding var isOn: Bool
    var body: some View {
        Capsule()
            .fill(isOn ? Color.brandAccent : Color.wizSurface2)
            .frame(width: 38, height: 22)
            .overlay {
                if !isOn { Capsule().stroke(Color.wizBorder2, lineWidth: 1) }
            }
            .overlay(alignment: isOn ? .trailing : .leading) {
                Circle()
                    .fill(isOn ? Color.black.opacity(0.85) : Color.wizMuted)
                    .frame(width: 16, height: 16)
                    .padding(3)
            }
            .contentShape(Capsule())
            .onTapGesture { withAnimation(.easeInOut(duration: 0.15)) { isOn.toggle() } }
            .accessibilityAddTraits(.isButton)
    }
}

// ── Button-Formen aus dem Dummy ──

struct WizPrimaryButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 15, weight: .semibold))
            .foregroundStyle(Color.black)
            .padding(.horizontal, 22).padding(.vertical, 11)
            .background(Color.brandAccent, in: RoundedRectangle(cornerRadius: 11))
            .opacity(configuration.isPressed ? 0.85 : 1)
    }
}

struct WizSecondaryButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(Color.wizText)
            .padding(.horizontal, 18).padding(.vertical, 10)
            .background(Color.wizSurface, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.wizBorder2, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.8 : 1)
    }
}

// ── Slider im Dummy-Look: dünne Spur, Lime-Füllung, kleiner Lime-Knopf ──
// Native macOS-Slider ließen sich nicht auf den schlanken Look bringen.
struct WizSliderControl: View {
    @Binding var value: Double
    let range: ClosedRange<Double>

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let span = range.upperBound - range.lowerBound
            let frac = span > 0 ? min(max((value - range.lowerBound) / span, 0), 1) : 0
            let knobX = 6.5 + CGFloat(frac) * (w - 13)
            ZStack(alignment: .leading) {
                Capsule().fill(Color.wizSurface2).frame(height: 4)
                Capsule().fill(Color.brandAccent).frame(width: knobX, height: 4)
                Circle().fill(Color.brandAccent).frame(width: 13, height: 13)
                    .offset(x: knobX - 6.5)
            }
            .frame(height: 14)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { g in
                guard span > 0, w > 13 else { return }
                let f = min(max((g.location.x - 6.5) / (w - 13), 0), 1)
                value = range.lowerBound + Double(f) * span
            })
        }
        .frame(width: 108, height: 14)
    }
}

// ── Wiederherstellen-Chips für ausgeblendete (getrashte) Quellen ──
// Ohne die käme man an eine einmal getrashte Kamera/Person nur noch übers Löschen
// der `.multicam` heran (der included=false-Zustand ist persistent).
struct WizRestoreChips: View {
    let title: String
    let items: [(id: Int, name: String)]
    let restore: (Int) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(.caption2).fontWeight(.bold).foregroundStyle(.wizFaint).tracking(1)
            FlowLayout(spacing: 8) {
                ForEach(items, id: \.id) { item in
                    Button { restore(item.id) } label: {
                        HStack(spacing: 6) {
                            LucideIcon("undo-2", size: 10)
                            Text(item.name).font(.caption)
                        }
                        .padding(.horizontal, 10).padding(.vertical, 5)
                        .background(Color.wizSurface, in: Capsule())
                        .overlay(Capsule().stroke(Color.wizBorder, lineWidth: 1))
                        .foregroundStyle(.wizMuted)
                    }
                    .buttonStyle(.plain)
                    .help("Add back to the project")
                }
            }
        }
    }
}

// ── Preset-Dropdown im Dummy-Look: „Preset [aktueller Name ▾]" ──
struct WizPresetDropdown: View {
    @EnvironmentObject var engine: EngineController
    @State private var showSaveSheet = false
    @State private var newName = ""
    /// Preset-Liste als echter @State. Vorher wurde `PresetManager.shared.listPresets()`
    /// direkt im Body gelesen — darauf hat SwiftUI KEINE Abhängigkeit, deshalb tauchte ein
    /// frisch gespeichertes Preset nicht im Menü auf. Nach Speichern/Import neu laden.
    /// Nebeneffekt: spart die mehrfachen Verzeichnis-/JSON-Lesevorgänge pro Render.
    @State private var presets: [Preset] = PresetManager.shared.listPresets()

    private func reloadPresets() { presets = PresetManager.shared.listPresets() }

    /// ID des Presets, das exakt den aktuellen Parametern entspricht (sonst „Angepasst").
    private var matchingPresetId: String? {
        presets.first { PresetManager.shared.loadPreset($0.id) == engine.params }?.id
    }

    var body: some View {
        HStack(spacing: 8) {
            Text("Preset").font(.system(size: 13)).foregroundStyle(.wizMuted)

            // Natives Menü-Dropdown: dunkle Box + aktueller Name + Chevron (wie Dummy).
            Picker("", selection: Binding(
                get: { matchingPresetId },
                set: { if let id = $0, let p = PresetManager.shared.loadPreset(id) { engine.params = p } }
            )) {
                if matchingPresetId == nil {
                    Text("Custom").tag(String?.none)
                }
                ForEach(presets) { Text($0.name).tag(Optional($0.id)) }
            }
            .labelsHidden()
            .frame(minWidth: 150)

            // Speichern / Import / Export dahinter (kompaktes Overflow-Menü).
            Menu {
                Button("Save preset …") { newName = ""; showSaveSheet = true }
                Button("Import preset …") {
                    if let (_, p) = PresetManager.shared.importPreset() {
                        engine.params = p
                        reloadPresets()   // Import legt eine Datei an → Liste neu einlesen
                    }
                }
                Button("Export preset …") {
                    _ = PresetManager.shared.exportPreset(engine.params, name: "My Preset")
                }
            } label: {
                LucideIcon("circle-ellipsis", size: 15).foregroundStyle(.wizMuted)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
        }
        .onAppear { reloadPresets() }   // falls anderswo Presets dazugekommen sind
        .sheet(isPresented: $showSaveSheet) {
            VStack(spacing: 16) {
                Text("Save preset").font(.headline)
                TextField("Preset name", text: $newName).textFieldStyle(.roundedBorder).frame(width: 250)
                HStack {
                    Button("Cancel") { showSaveSheet = false }
                    Button("Save") {
                        guard !newName.isEmpty else { return }
                        _ = PresetManager.shared.savePreset(name: newName, params: engine.params)
                        reloadPresets()   // ohne das erscheint das neue Preset nicht im Menü
                        showSaveSheet = false
                    }
                    .buttonStyle(.borderedProminent).disabled(newName.isEmpty)
                }
            }
            .padding(24)
        }
    }
}
