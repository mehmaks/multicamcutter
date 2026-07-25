import Foundation

/// Anonyme Nutzungs-Telemetrie (Punkt 6). Contract: brain/Telemetrie-API.md.
///
/// HARTE Regeln (siehe Contract):
/// - Eigene, zufaellige `analytics_id` (UUID) — NIE die Lizenz-/Geraete-ID.
/// - NUR Zahlen/Enums senden — nie Namen, Pfade, Freitext.
/// - Opt-in, jederzeit widerrufbar (Settings-Toggle). Default: AUS/ungefragt.
/// - fire-and-forget nach erfolgreichem Lauf; blockiert/scheitert den Lauf NIE.
enum Telemetry {

    /// Zustimmungs-Status: 0 = ungefragt, 1 = an, 2 = aus. (UserDefaults-Key wird
    /// vom Settings-Toggle @AppStorage("analyticsConsent") geteilt.)
    static var consentState: Int { UserDefaults.standard.integer(forKey: "analyticsConsent") }
    static var enabled: Bool { consentState == 1 }

    /// Zufaellige, lokal erzeugte ID — einmalig, ohne jeden Lizenzbezug.
    static var analyticsId: String {
        let key = "analyticsId"
        if let existing = UserDefaults.standard.string(forKey: key), !existing.isEmpty {
            return existing
        }
        let id = UUID().uuidString
        UserDefaults.standard.set(id, forKey: key)
        return id
    }

    static var endpoint: URL? { URL(string: LicenseConfig.apiBase + "/api/telemetry") }

    /// Sendet ein `analysis_completed`-Event. `payload` enthaelt bereits sources/
    /// runtime/settings/preset/device (alles Zahlen/Enums — vom Aufrufer gebaut).
    /// Tut nichts, wenn nicht zugestimmt. Fehler/Response werden ignoriert.
    static func sendAnalysisCompleted(_ payload: [String: Any]) {
        guard enabled, let url = endpoint else { return }
        var full = payload
        full["analytics_id"] = analyticsId
        full["app_version"] = AppVersion.display
        full["event"] = "analysis_completed"
        guard JSONSerialization.isValidJSONObject(full),
              let body = try? JSONSerialization.data(withJSONObject: full) else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        // fire-and-forget: kein await, Response/Fehler bewusst ignoriert.
        URLSession.shared.dataTask(with: req).resume()
    }
}

/// Geraete-Kontext fuer den Benchmark (nur Zahlen/kurze Enums — keine PII).
enum TelemetryDevice {
    static func sysctlString(_ name: String) -> String {
        var size = 0
        sysctlbyname(name, nil, &size, nil, 0)
        guard size > 0 else { return "unbekannt" }
        var buf = [CChar](repeating: 0, count: size)
        sysctlbyname(name, &buf, &size, nil, 0)
        return String(cString: buf)
    }
    /// z.B. "Apple M2 Ultra".
    static var cpu: String { sysctlString("machdep.cpu.brand_string") }
    static var cores: Int { ProcessInfo.processInfo.processorCount }
    static var ramGb: Int { Int(ProcessInfo.processInfo.physicalMemory / 1_073_741_824) }

    static var payload: [String: Any] {
        [
            "model": SystemInfo.deviceModel,   // z.B. "Mac14,14"
            "chip": cpu,
            "cores": cores,
            "ram_gb": ramGb,
            "os": SystemInfo.osVersion,
        ]
    }
}
