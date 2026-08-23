import SwiftUI

/// Einmalige Frage beim ersten Start (bzw. beim ersten Start nach dem Update, das
/// die Telemetrie einfuehrt): Darf die App anonyme Nutzungszahlen senden?
///
/// Opt-in, DSGVO-konform — freiwillig, transparent, jederzeit widerrufbar
/// (Einstellungen → Datenschutz, geteilter Key `analyticsConsent`). Erscheint nur,
/// solange noch nie gefragt wurde (consentState == 0), und bewusst NACH dem
/// Material-Hinweis (Sequenzierung in ContentView). Contract: brain/Telemetrie-API.md.
///
/// Bewusst kein „nudge": Escape/„Nein danke" ist die datensparsame Wahl (cancelAction),
/// und Enter loest KEINE Zustimmung aus — Zustimmung braucht einen echten Klick.
struct TelemetryConsentSheet: View {
    /// Geteilt mit Settings-Toggle + Telemetry.swift: 0 = ungefragt, 1 = an, 2 = aus.
    @AppStorage("analyticsConsent") private var analyticsConsent = 0
    @Environment(\.dismiss) private var dismiss

    /// Datenschutz-Seite der Website (DE). Route der Web-Session: /{locale}/privacy.
    private var privacyURL: URL? { URL(string: LicenseConfig.apiBase + "/de/privacy") }

    private struct Point: Identifiable {
        let id = UUID()
        let icon: String
        let text: String
    }

    private let points: [Point] = [
        .init(icon: "circle-check",
              text: "Only anonymous numbers: how many cameras, microphones and people, "
                  + "how long the recordings are, how long a run takes, your "
                  + "Mac model and which features were on."),
        .init(icon: "circle-x",
              text: "Never names, files, paths or images. No account, no "
                  + "ads, no third-party tracker."),
        .init(icon: "shield-check",
              text: "Stored anonymously on a server in the EU. This shows me how "
                  + "big real projects are and how fast the app runs on which "
                  + "hardware — and lets me make it better."),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                LucideIcon("shield-check", size: 26)
                    .foregroundStyle(.brandAccent)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Help out anonymously?")
                        .font(.title3.bold())
                    Text("Completely optional — and can be turned off any time.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 14) {
                ForEach(points) { p in
                    HStack(alignment: .top, spacing: 10) {
                        LucideIcon(p.icon, size: 15)
                            .foregroundStyle(.brandAccent)
                            .frame(width: 22, alignment: .center)
                        Text(p.text)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            if let privacyURL {
                Link(destination: privacyURL) {
                    LucideLabel("What exactly? — Privacy", icon: "external-link", size: 11)
                        .font(.caption)
                }
            }

            Divider()

            HStack(alignment: .firstTextBaseline) {
                Text("You can change this later any time in "
                     + "Settings → Privacy.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Spacer(minLength: 12)

                Button("No thanks") {
                    analyticsConsent = 2
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Button("Yes, help anonymously") {
                    analyticsConsent = 1
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(20)
        .frame(width: 460)
    }
}
