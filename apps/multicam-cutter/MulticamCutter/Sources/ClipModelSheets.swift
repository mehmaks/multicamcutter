import SwiftUI

/// Nachfrage vor dem einmaligen CLIP-Download. Bewusst KEIN heimlicher Download:
/// 581 MB laedt man nicht ungefragt — und wer's nicht will, soll die App trotzdem
/// voll nutzen koennen (dann wird der Parameter dauerhaft abgeschaltet).
struct ClipDownloadPrompt: View {
    @EnvironmentObject var engine: EngineController

    private var sizeText: String {
        ByteCountFormatter.string(fromByteCount: engine.clipTotal, countStyle: .file)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                LucideIcon("sparkles", size: 26)
                    .foregroundStyle(.brandAccent)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Bilderkennung nachladen?")
                        .font(.title3.bold())
                    Text("Einmalig \(sizeText)")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }

            Text("„Ungünstige Cutaways verschieben\" prüft per Bilderkennung (CLIP), ob ein "
                 + "Cutaway z. B. jemanden beim Trinken zeigt, und verschiebt ihn. Dafür wird "
                 + "einmalig ein Modell geladen.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            LucideLabel("Danach läuft alles offline — das Modell bleibt gespeichert, auch nach "
                        + "App-Updates.", icon: "shield-check", size: 11)
                .font(.caption)
                .foregroundStyle(.secondary)

            Divider()

            HStack {
                Button("Ohne Bilderkennung fortfahren") {
                    engine.declineClipAndStart()
                }
                .help("Schaltet den Parameter aus. Alles andere funktioniert normal.")

                Spacer()

                Button("Laden (\(sizeText))") {
                    engine.downloadClipModelAndStart()
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 460)
    }
}

/// Download-Fortschritt — Aufbau nach `look examples/download.png`:
/// Icon links, Name fett, Balken, „X von Y (Z %)", Abbrechen rechts.
struct ClipDownloadSheet: View {
    @EnvironmentObject var engine: EngineController

    private var fraction: Double {
        engine.clipTotal > 0 ? min(1, Double(engine.clipDone) / Double(engine.clipTotal)) : 0
    }

    private var byteText: String {
        let f = ByteCountFormatter()
        f.countStyle = .file
        // Ohne das schreibt der Formatter bei 0 Bytes „Zero KB".
        f.allowsNonnumericFormatting = false
        let done = f.string(fromByteCount: engine.clipDone)
        let total = f.string(fromByteCount: engine.clipTotal)
        return "\(done) von \(total) (\(Int(fraction * 100)) %)"
    }

    var body: some View {
        HStack(spacing: 14) {
            LucideIcon("sparkles", size: 30)
                .foregroundStyle(.brandAccent)

            VStack(alignment: .leading, spacing: 6) {
                Text("Bilderkennung (CLIP)")
                    .font(.headline)
                SwiftUI.ProgressView(value: fraction)
                    .progressViewStyle(.linear)
                Text(byteText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }

            Button {
                engine.cancelClipDownload()
            } label: {
                LucideIcon("circle-x", size: 22)
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .help("Download abbrechen")
        }
        .padding(20)
        .frame(width: 460)
    }
}
