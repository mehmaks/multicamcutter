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
    /// Einmal gesehen = nie wieder. Zuruecksetzbar ueber die Einstellungen.
    @AppStorage("hasSeenFirstRunInfo") private var hasSeenFirstRunInfo = false
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
              // shared/waveform_sync.py korreliert den Kameraton gegen CAM1.
              detail: "Die Synchronisierung vergleicht die Tonspuren der Kameras "
                    + "miteinander. Eine Kamera ohne brauchbaren Ton lässt sich "
                    + "nicht einordnen — auch nicht von Hand."),
        .init(icon: "person.wave.2",
              title: "Ein eigenes Mikrofon je Person",
              detail: "Wer spricht, wird über die Lautstärke der einzelnen "
                    + "Mikrofone bestimmt. Ein gemeinsames Mikrofon für mehrere "
                    + "Personen lässt sich nicht auftrennen."),
        .init(icon: "person.2",
              title: "Zurzeit zwei Personen als Sprecher",
              // build_base_edl_from_audio.rms_diarize vergleicht genau zwei Seiten.
              detail: "Weitere Kameras sind willkommen und werden als Totale oder "
                    + "Cutaway genutzt — als sprechende Person erkennt die Analyse "
                    + "aber derzeit nur zwei."),
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
                Text("Dieser Hinweis erscheint nur einmal.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer()

                Button("Verstanden") {
                    hasSeenFirstRunInfo = true
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
