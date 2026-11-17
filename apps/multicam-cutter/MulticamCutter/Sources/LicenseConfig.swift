import Foundation

/// Backend-Konfiguration. Die App ist kostenlos — keine Lizenzpruefung mehr.
/// Das Backend wird nur noch fuer Feedback, Telemetrie und Datenschutz-Link genutzt.
enum LicenseConfig {
    /// Basis-URL des Backends. Endpoints: /api/feedback, /api/telemetry.
    static let apiBase = "https://multicamcutter.pantake.com"
}
