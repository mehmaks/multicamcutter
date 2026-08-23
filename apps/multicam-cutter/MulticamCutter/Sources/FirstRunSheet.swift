import SwiftUI

/// Einmaliger Hinweis beim allerersten Start: was das Material mitbringen muss.
///
/// Warum ueberhaupt: Die Anforderungen sind nicht offensichtlich, und wer sie
/// verletzt, merkt es erst nach einem kompletten Analyselauf — oder schlimmer,
/// am unbrauchbaren Schnitt. Ein Satz vorher spart einen Fehlversuch.
///
/// Bewusst NUR harte Voraussetzungen, keine Bedienungsanleitung: sonst wird das
/// Fenster weggeklickt, ohne gelesen zu werden. Alles hier ist am Code geprueft,
/// nicht aus dem Gedaechtnis geschrieben — Belege stehen an den Punkten.
struct FirstRunSheet: View {
    /// Stand des INHALTS, nicht der App-Version. Hochzaehlen, sobald sich an den
    /// Voraussetzungen unten etwas aendert — dann sehen auch Bestandsnutzer den
    /// Hinweis noch einmal.
    ///
    /// Bewusst nicht an `CFBundleShortVersionString` gekoppelt: an einem einzigen
    /// Tag gingen 0.5.0, 0.5.1 und 0.5.2 raus. Bei Versionsbindung waere derselbe
    /// unveraenderte Text dreimal erschienen — nach zweimal Wegklicken liest ihn
    /// niemand mehr, gerade dann nicht, wenn er sich wirklich mal aendert.
    static let contentRevision = 3

    /// Zuletzt bestaetigter Stand. 0 = noch nie gesehen.
    @AppStorage("firstRunInfoSeenRevision") private var seenRevision = 0
    @Environment(\.dismiss) private var dismiss

    private struct Requirement: Identifiable {
        let id = UUID()
        let icon: String
        let title: String
        let detail: String
    }

    private let requirements: [Requirement] = [
        .init(icon: "audio-waveform",
              title: "Every camera needs its own audio track",
              // shared/waveform_sync.py korreliert jede Quelle gegen eine Referenz
              // (standardmaessig das laengste Mikrofon).
              detail: "Sync compares the cameras' audio tracks with each "
                    + "other. A camera without usable audio can't be placed "
                    + "— not even by hand."),
        .init(icon: "speech",
              title: "A separate microphone for each person",
              detail: "Who's speaking is determined from the volume of each "
                    + "microphone. A shared microphone for several people "
                    + "can't be split apart."),
        // Bewusst KEIN Punkt zur Kamera-/Sprecherwechsel-Mechanik hier (22.07.):
        // Das ist App-Verhalten, keine Material-Anforderung, und passte nicht zur
        // Überschrift „Was dein Material mitbringen muss". Erklärung dazu gehört
        // in die Bildsprache-Hilfetexte, nicht in diese Einstiegs-Checkliste.
        .init(icon: "refresh-cw",
              title: "The recordings must overlap in time",
              detail: "Without a shared time span, sync has no reference "
                    + "point. A lead-in at the start is fine."),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                LucideIcon("list-checks", size: 26)
                    .foregroundStyle(.brandAccent)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Before you start")
                        .font(.title3.bold())
                    Text("What your footage needs")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 14) {
                ForEach(requirements) { req in
                    HStack(alignment: .top, spacing: 10) {
                        LucideIcon(req.icon, size: 15)
                            .foregroundStyle(.brandAccent)
                            .frame(width: 22, alignment: .center)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(loc(req.title))
                                .font(.callout.weight(.medium))
                            Text(loc(req.detail))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }

            // Bewusst als Entwarnung formuliert, nicht als Anforderung: die App
            // erkennt abweichende Bildraten selbst (EngineController.fpsMismatches)
            // und bietet die Umwandlung an (--convert-fps).
            LucideLabel("Different frame rates are no problem — the app detects "
                        + "them and offers to convert the affected files.",
                        icon: "info", size: 11)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            Divider()

            HStack {
                Text(loc(seenRevision == 0
                     ? "This note appears again when something here changes."
                     : "Something here has changed."))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer()

                Button("Got it") {
                    seenRevision = Self.contentRevision
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 460)
    }
}
