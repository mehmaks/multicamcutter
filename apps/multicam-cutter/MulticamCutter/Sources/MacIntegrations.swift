import AppKit
import UserNotifications

// MARK: - Dock-Fortschrittsbalken während der Analyse
//
// Zeichnet einen kleinen Balken unten auf das Dock-Icon (wie Xcode/Mail), damit man
// den Fortschritt auch bei minimierter/hintergründiger App sofort sieht.

/// Selbst-zeichnende Dock-Tile-View: App-Icon + Fortschrittsbalken. Ein eingebetteter
/// `NSProgressIndicator` rendert in einer Dock-Tile NICHT zuverlässig — daher manuell.
private final class DockProgressView: NSView {
    var fraction: Double = 0 { didSet { needsDisplay = true } }

    override func draw(_ dirtyRect: NSRect) {
        NSApp.applicationIconImage?.draw(in: bounds)

        let h = bounds.height * 0.12
        let inset = bounds.width * 0.14
        let track = NSRect(x: inset, y: bounds.height * 0.10,
                           width: bounds.width - inset * 2, height: h)
        let radius = h / 2

        let bg = NSBezierPath(roundedRect: track, xRadius: radius, yRadius: radius)
        NSColor.black.withAlphaComponent(0.55).setFill(); bg.fill()
        NSColor.white.withAlphaComponent(0.28).setStroke(); bg.lineWidth = 1; bg.stroke()

        let f = CGFloat(min(max(fraction, 0), 1))
        let fillW = max(h, track.width * f)   // min. rund, damit auch bei 0 % sichtbar
        let fill = NSBezierPath(roundedRect: NSRect(x: track.minX, y: track.minY, width: fillW, height: h),
                                xRadius: radius, yRadius: radius)
        NSColor(srgbRed: 198/255, green: 242/255, blue: 78/255, alpha: 1).setFill()  // brandAccent
        fill.fill()
    }
}

@MainActor
final class DockProgress {
    static let shared = DockProgress()
    private var view: DockProgressView?

    /// Fortschritt 0…1 anzeigen (legt die View beim ersten Aufruf an).
    func show(_ fraction: Double) {
        let tile = NSApp.dockTile
        if view == nil {
            let v = DockProgressView(frame: NSRect(x: 0, y: 0, width: 128, height: 128))
            tile.contentView = v
            view = v
        }
        view?.fraction = fraction
        tile.display()
    }

    /// Balken entfernen, Standard-Icon wiederherstellen.
    func hide() {
        NSApp.dockTile.contentView = nil
        view = nil
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
