import SwiftUI
import AppKit

/// Lucide-Icons (Icon-Set der Website, lucide.dev, ISC — Eintrag in den
/// Acknowledgements). Die SVGs liegen FEST im App-Bundle (SPM-Ressourcen,
/// `Sources/Icons/`, exakt aus lucide-react 1.24.0 der Website extrahiert,
/// stroke-width 2.5 statt Default 2 — bewusst kraeftiger, User 24.07.).
/// Kein Netz, kein Nachladen. Template-Rendering → tintbar via
/// `.foregroundStyle` wie SF Symbols.
///
/// Vollmigration 24.07. — alle sichtbaren UI-Icons. Bewusste Ausnahmen
/// (bleiben SF Symbols): Settings-Tab-Icons und Menüeinträge — dort rendert
/// das System die Icons selbst, eigene Bilder skalieren unzuverlässig.
struct LucideIcon: View {
    let name: String
    var size: CGFloat = 14

    init(_ name: String, size: CGFloat = 14) {
        self.name = name
        self.size = size
    }

    var body: some View {
        if let image = Self.image(named: name, size: size) {
            Image(nsImage: image)
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: size, height: size)
        }
    }

    @MainActor private static var cache: [String: NSImage] = [:]

    /// Optische Strichstärken-Korrektur (User-Feedback 25.07.): Ein fester
    /// SVG-Stroke skaliert linear mit der Icongröße — kleine Icons wirken
    /// dünn, mittlere fett (Play 19 pt wirkte dicker als Pencil 12 pt).
    /// Stattdessen wächst die SICHTBARE Strichstärke nur mit der Wurzel der
    /// Größe: visual = 1.3 · √(size/13). Referenzpunkte: 12 pt → 1.25 pt
    /// (exakt der PoC-Look, der gefiel), 19 pt → 1.57 pt (≈ Lucide-Default-
    /// Gewicht), 64 pt → 2.9 pt statt vorher 6.7 pt.
    @MainActor private static func image(named name: String, size: CGFloat) -> NSImage? {
        let key = "\(name)@\(Int(size.rounded()))"
        if let hit = cache[key] { return hit }
        guard let url = Bundle.module.url(forResource: name, withExtension: "svg",
                                          subdirectory: "Icons"),
              let raw = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        let visual = 1.3 * sqrt(max(size, 1) / 13)
        let svgStroke = visual * 24 / max(size, 1)   // zurückgerechnet auf die 24er-ViewBox
        let svg = raw.replacingOccurrences(of: "stroke-width=\"2.5\"",
                                           with: String(format: "stroke-width=\"%.2f\"", svgStroke))
        guard let img = NSImage(data: Data(svg.utf8)) else { return nil }
        img.isTemplate = true      // Alpha-Maske → Tint folgt foregroundStyle
        cache[key] = img
        return img
    }
}

/// Drop-in für `Label(_:systemImage:)` mit Lucide-Icon.
struct LucideLabel: View {
    let title: String
    let icon: String
    var size: CGFloat = 14

    init(_ title: String, icon: String, size: CGFloat = 14) {
        self.title = title
        self.icon = icon
        self.size = size
    }

    var body: some View {
        Label { Text(title) } icon: { LucideIcon(icon, size: size) }
    }
}
