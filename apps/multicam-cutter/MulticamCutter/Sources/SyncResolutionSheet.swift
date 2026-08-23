import SwiftUI

/// Loest Quellen auf, die der Sync nicht automatisch einordnen konnte
/// (Engine-Message `sync_unresolved`, Punkt 1 / Baustein 2+3). Pro Quelle:
/// einen manuellen Offset in Frames setzen ODER die Quelle ausschliessen.
/// Danach startet die Analyse erneut. Die uebrigen Quellen sind bereits synchron.
struct SyncResolutionSheet: View {
    @ObservedObject var engine: EngineController

    enum Choice: Hashable { case manual, exclude }
    @State private var choice: [String: Choice] = [:]
    @State private var offsetText: [String: String] = [:]

    /// Referenzkamera, auf die die Offsets normiert sind (Dateiname statt „1. Kamera").
    private var refName: String {
        engine.syncReferenceFilename.isEmpty ? "the first camera" : engine.syncReferenceFilename
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                Text("Some sources couldn't be synced automatically")
                    .font(.headline)
            }
            Text("For each affected source: enter an offset in frames (relative to \(refName)) or exclude the source from the edit. The remaining sources are already in sync.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ScrollView {
                VStack(spacing: 12) {
                    // Schwaechste Quelle (niedrigste Confidence) zuerst — das ist die,
                    // die am ehesten Aufmerksamkeit braucht.
                    ForEach(engine.syncUnresolvedSources
                        .sorted { $0.bestConfidence < $1.bestConfidence }) { src in
                        sourceCard(src)
                    }
                }
                .padding(.vertical, 2)
            }
            .frame(maxHeight: 340)

            HStack {
                Button("Cancel") { engine.cancelSyncResolution() }
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button("Sync again") { apply() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .tint(.brandAccent)
            }
        }
        .padding(24)
        .frame(width: 580)
        .onAppear(perform: seedDefaults)
    }

    @ViewBuilder
    private func sourceCard(_ src: UnsyncableSource) -> some View {
        let current = choice[src.id] ?? .manual
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(src.filename).fontWeight(.semibold)
                Spacer()
                Text("\(src.bestConfidence, specifier: "%.0f")×")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            Text(src.reason)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            Picker("", selection: Binding(
                get: { choice[src.id] ?? .manual },
                set: { choice[src.id] = $0 }
            )) {
                Text("Manual offset").tag(Choice.manual)
                Text("Exclude").tag(Choice.exclude)
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            if current == .manual {
                HStack(spacing: 8) {
                    TextField("Frames", text: Binding(
                        get: { offsetText[src.id] ?? "\(src.candidateOffsetFrames)" },
                        set: { offsetText[src.id] = $0 }
                    ))
                    .frame(width: 90)
                    .textFieldStyle(.roundedBorder)
                    // Rot umrandet: hier ist eine Eingabe/Bestaetigung noetig.
                    .overlay(RoundedRectangle(cornerRadius: 5)
                        .stroke(Color.red.opacity(0.85), lineWidth: 1.5))
                    Text("Frames (relative to \(refName)) · Suggestion: \(src.candidateOffsetFrames)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else {
                Text(loc("Excluded from the edit — the person on this track "
                     + "won't be detected then."))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.gray.opacity(0.10)))
    }

    private func seedDefaults() {
        for src in engine.syncUnresolvedSources {
            if choice[src.id] == nil { choice[src.id] = .manual }
            if offsetText[src.id] == nil { offsetText[src.id] = "\(src.candidateOffsetFrames)" }
        }
    }

    private func apply() {
        var exclude = Set<String>()
        var manual: [String: Int] = [:]
        for src in engine.syncUnresolvedSources {
            switch choice[src.id] ?? .manual {
            case .exclude:
                exclude.insert(src.path)
            case .manual:
                let txt = (offsetText[src.id] ?? "").trimmingCharacters(in: .whitespaces)
                manual[src.path] = Int(txt) ?? src.candidateOffsetFrames
            }
        }
        engine.resolveSyncAndRetry(excludePaths: exclude, manualOffsets: manual)
    }
}
