import SwiftUI

// MARK: - Marken-Farben
//
// Einzige Quelle fuer den Marken-Akzent. Muss mit der Website uebereinstimmen
// (siehe multicamcutter-web/design.md → "Accent color: lime #C6F24E").
// App-weit gesetzt via `.tint(.brandAccent)` auf den Fenster-Wurzeln; einzelne
// explizite Verwendungen (Drop-Highlight, Selection, Pills) nutzen `.brandAccent`.

extension ShapeStyle where Self == Color {
    /// Lime-Akzent #C6F24E (Dark-Mode-only UI, wie die Website).
    ///
    /// Auf `ShapeStyle where Self == Color` definiert (wie SwiftUIs `.red`/`.blue`),
    /// damit sowohl `Color.brandAccent` als auch die Leading-Dot-Syntax in
    /// `.foregroundStyle(.brandAccent)` / `.tint(.brandAccent)` funktioniert.
    static var brandAccent: Color {
        Color(.sRGB, red: 198 / 255, green: 242 / 255, blue: 78 / 255)
    }

    /// Flieder/Lila #CBA6F7 — zweite Akzentfarbe im Komplementaerkontrast zu Lime.
    /// Ersetzt das fruehere Orange und deckt BEIDE Rollen ab: Akzent (Totale-Marker,
    /// Personen) UND Warnzustaende (FPS-Mismatch, „wird ignoriert", Lizenz-Grace).
    /// Hell genug fuer schwarzen Text auf Pills und als Textfarbe auf dunklem Grund.
    static var brandSecondary: Color {
        Color(.sRGB, red: 203 / 255, green: 166 / 255, blue: 247 / 255)
    }
}
