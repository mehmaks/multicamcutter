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
        if let image = Self.image(named: name) {
            Image(nsImage: image)
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: size, height: size)
        }
    }

    @MainActor private static var cache: [String: NSImage] = [:]

    @MainActor private static func image(named name: String) -> NSImage? {
        if let hit = cache[name] { return hit }
        guard let url = Bundle.module.url(forResource: name, withExtension: "svg",
                                          subdirectory: "Icons"),
              let img = NSImage(contentsOf: url) else { return nil }
        img.isTemplate = true      // Alpha-Maske → Tint folgt foregroundStyle
        cache[name] = img
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
