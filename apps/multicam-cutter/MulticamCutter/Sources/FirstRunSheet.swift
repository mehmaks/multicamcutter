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
        .init(icon: "waveform.badge.magnifyingglass",
              title: "Jede Kamera braucht eine eigene Tonspur",
              // shared/waveform_sync.py korreliert jede Quelle gegen eine Referenz
              // (standardmaessig das laengste Mikrofon).
              detail: "Die Synchronisierung vergleicht die Tonspuren der Kameras "
                    + "miteinander. Eine Kamera ohne brauchbaren Ton lässt sich "
                    + "nicht einordnen — auch nicht von Hand."),
        .init(icon: "person.wave.2",
              title: "Ein eigenes Mikrofon je Person",
              detail: "Wer spricht, wird über die Lautstärke der einzelnen "
                    + "Mikrofone bestimmt. Ein gemeinsames Mikrofon für mehrere "
                    + "Personen lässt sich nicht auftrennen."),
        // Bewusst KEIN Punkt zur Kamera-/Sprecherwechsel-Mechanik hier (22.07.):
        // Das ist App-Verhalten, keine Material-Anforderung, und passte nicht zur
        // Überschrift „Was dein Material mitbringen muss". Erklärung dazu gehört
        // in die Bildsprache-Hilfetexte, nicht in diese Einstiegs-Checkliste.
        .init(icon: "clock.arrow.2.circlepath",
              title: "Die Aufnahmen müssen sich zeitlich überlappen",
              detail: "Ohne gemeinsamen Zeitraum findet die Synchronisierung "
                    + "keinen Bezugspunkt. Ein Vorlauf am Anfang ist unproblematisch."),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Image(systemName: "checklist")
                    .font(.system(size: 26))
                    .foregroundStyle(.brandAccent)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Bevor du startest")
                        .font(.title3.bold())
                    Text("Was dein Material mitbringen muss")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 14) {
                ForEach(requirements) { req in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: req.icon)
                            .font(.system(size: 15))
                            .foregroundStyle(.brandAccent)
                            .frame(width: 22, alignment: .center)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(req.title)
                                .font(.callout.weight(.medium))
                            Text(req.detail)
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
            Label("Unterschiedliche Bildraten sind kein Hindernis — die App erkennt "
                  + "sie und bietet an, die betroffenen Dateien umzuwandeln.",
                  systemImage: "info.circle")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            Divider()

            HStack {
                Text(seenRevision == 0
                     ? "Dieser Hinweis erscheint wieder, wenn sich etwas daran ändert."
                     : "Hier hat sich etwas geändert.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer()

                Button("Verstanden") {
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
