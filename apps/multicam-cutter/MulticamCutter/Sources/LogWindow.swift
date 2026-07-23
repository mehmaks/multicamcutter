import SwiftUI
import AppKit

/// Eigenes Log-Fenster (Cmd+L). Zeigt den laufenden Engine-Output und fuehrt zu den
/// persistenten Log-Dateien.
///
/// Warum ein eigenes Fenster: Bei einem Fehler wechselt die UI in den ErrorView —
/// das Log war damit weg, obwohl es fuer die Diagnose am wichtigsten ist. Hier bleibt
/// es sichtbar, auch nach Analyse-Ende.
///
/// Historie kommt aus den **Dateien**, nicht aus dem Speicher: Die Engine schreibt pro
/// Lauf ein JSONL nach ~/Library/Logs/MulticamCutter/ (siehe EngineController.logDirectory).
struct LogWindow: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Text("\(engine.logMessages.count) Zeilen")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer()

                Button {
                    copyAll()
                } label: {
                    LucideLabel("Kopieren", icon: "copy", size: 13)
                }
                .disabled(engine.logMessages.isEmpty)

                Button {
                    NSWorkspace.shared.open(EngineController.logDirectory)
                } label: {
                    LucideLabel("Log-Ordner öffnen", icon: "folder", size: 13)
                }
                .help("Alle bisherigen Läufe als Datei — ~/Library/Logs/MulticamCutter")
            }
            .padding(8)

            Divider()

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 1) {
                        ForEach(Array(engine.logMessages.enumerated()), id: \.offset) { i, line in
                            Text(line)
                                .font(.system(.caption2, design: .monospaced))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(i)
                        }
                    }
                    .padding(8)
                }
                .onChange(of: engine.logMessages.count) {
                    // Mitlaufen, damit man bei langen Analysen das Ende sieht.
                    if let last = engine.logMessages.indices.last {
                        proxy.scrollTo(last, anchor: .bottom)
                    }
                }
            }
            .overlay {
                if engine.logMessages.isEmpty {
                    ContentUnavailableView {
                        Label { Text("Kein Log für diesen Lauf") } icon: {
                            LucideIcon("file-text", size: 40)
                        }
                    } description: {
                        Text("Frühere Läufe liegen als Datei im Log-Ordner.")
                    }
                }
            }
        }
        .frame(minWidth: 620, minHeight: 380)
    }

    private func copyAll() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(engine.logMessages.joined(separator: "\n"), forType: .string)
    }
}
