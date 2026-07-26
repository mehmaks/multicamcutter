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
              text: "Nur anonyme Zahlen: wie viele Kameras, Mikrofone und Personen, "
                  + "wie lang die Aufnahmen sind, wie lange ein Durchlauf dauert, dein "
                  + "Mac-Modell und welche Funktionen an waren."),
        .init(icon: "circle-x",
              text: "Niemals Namen, Dateien, Pfade oder Bilder. Kein Konto, keine "
                  + "Werbung, kein fremder Tracker."),
        .init(icon: "shield-check",
              text: "Anonym gespeichert auf einem Server in der EU. So sehe ich, wie "
                  + "groß echte Projekte sind und wie schnell die App auf welcher "
                  + "Hardware läuft — und mache sie besser."),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                LucideIcon("shield-check", size: 26)
                    .foregroundStyle(.brandAccent)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Anonym mithelfen?")
                        .font(.title3.bold())
                    Text("Ganz freiwillig — und jederzeit abschaltbar.")
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
                    LucideLabel("Was genau? — Datenschutz", icon: "external-link", size: 11)
                        .font(.caption)
                }
            }

            Divider()

            HStack(alignment: .firstTextBaseline) {
                Text("Ändern kannst du das später jederzeit in den "
                     + "Einstellungen → Datenschutz.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Spacer(minLength: 12)

                Button("Nein danke") {
                    analyticsConsent = 2
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Button("Ja, anonym helfen") {
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
