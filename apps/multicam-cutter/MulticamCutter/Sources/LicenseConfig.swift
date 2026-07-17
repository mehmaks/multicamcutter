import Foundation

/// Zentrale Lizenz-Konfiguration. Setzt die Env-Vars, mit denen die Python-Engine
/// den Lizenzmodus + das Backend anspricht (siehe licensing/license.py).
enum LicenseConfig {
    /// Abo-Modus über das Backend (signierte Lease). Für Dev per Shell-Env
    /// `TOOLKIT_LICENSE_MODE=dummy` überschreibbar (siehe apply(to:)).
    static let mode = "remote"

    /// Basis-URL des Backends (Lizenz + Feedback). Endpoints: /api/license/activate,
    /// /api/license/validate, /api/feedback.
    static let apiBase = "https://multicamcutter.pantake.com"

    /// Ergänzt die Lizenz-Env-Vars — respektiert bereits gesetzte (Dev-Override).
    static func apply(to env: inout [String: String]) {
        if env["TOOLKIT_LICENSE_MODE"] == nil { env["TOOLKIT_LICENSE_MODE"] = mode }
        if env["TOOLKIT_LICENSE_API"] == nil { env["TOOLKIT_LICENSE_API"] = apiBase }
    }
}
