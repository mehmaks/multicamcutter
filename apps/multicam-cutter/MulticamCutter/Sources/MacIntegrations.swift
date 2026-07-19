import AppKit
import UserNotifications

// MARK: - Dock-Fortschrittsbalken während der Analyse
//
// Zeichnet einen kleinen Balken unten auf das Dock-Icon (wie Xcode/Mail), damit man
// den Fortschritt auch bei minimierter/hintergründiger App sofort sieht.

@MainActor
final class DockProgress {
    static let shared = DockProgress()
    private var bar: NSProgressIndicator?

    /// Fortschritt 0…1 anzeigen (legt den Balken beim ersten Aufruf an).
    func show(_ fraction: Double) {
        let tile = NSApp.dockTile
        if bar == nil {
            // Eigener Content-View ersetzt das Standard-Icon-Rendering → App-Icon selbst
            // zeichnen und den Balken darüberlegen.
            let host = NSImageView(frame: NSRect(x: 0, y: 0, width: 128, height: 128))
            host.image = NSApp.applicationIconImage
            host.imageScaling = .scaleProportionallyUpOrDown
            let pi = NSProgressIndicator(frame: NSRect(x: 14, y: 12, width: 100, height: 14))
            pi.isIndeterminate = false
            pi.minValue = 0
            pi.maxValue = 1
            pi.style = .bar
            host.addSubview(pi)
            tile.contentView = host
            bar = pi
        }
        bar?.doubleValue = min(max(fraction, 0), 1)
        tile.display()
    }

    /// Balken entfernen, Standard-Icon wiederherstellen.
    func hide() {
        NSApp.dockTile.contentView = nil
        bar = nil
        NSApp.dockTile.display()
    }
}

// MARK: - System-Notification bei Analyse-Ende
//
// UNUserNotificationCenter braucht ein echtes App-Bundle (Info.plist + Bundle-ID).
// Im Dev-Lauf via `swift run` gibt es keins → dann still überspringen (kein Crash);
// im gebauten .app (com.jenaunited.multicam-cutter) funktioniert es.

@MainActor
enum AnalysisNotifier {
    private static var available: Bool { Bundle.main.bundleIdentifier != nil }

    /// Einmalig (idempotent) die Erlaubnis anfragen.
    static func requestAuthIfNeeded() {
        guard available else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    /// Banner posten. macOS zeigt es standardmäßig nur, wenn die App NICHT im
    /// Vordergrund ist — genau der Fall „minimiert, Analyse fertig".
    static func notify(title: String, body: String) {
        guard available else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let req = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}
