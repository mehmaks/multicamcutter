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

    // MARK: - Wizard-Palette (grün-getöntes Dunkel, 1:1 aus dem Klick-Dummy)
    // Bewusst eigene Werte statt der System-Graustufen (controlBackgroundColor …),
    // damit der Look exakt dem Dummy entspricht statt neutral-blaugrau zu wirken.
    static var wizBg:       Color { Color(.sRGB, red:  14/255, green:  16/255, blue:  12/255) } // #0e100c
    static var wizBg2:      Color { Color(.sRGB, red:  20/255, green:  23/255, blue:  15/255) } // #14170f (Verlauf-Oberkante)
    static var wizSurface:  Color { Color(.sRGB, red:  25/255, green:  28/255, blue:  21/255) } // #191c15
    static var wizSurface2: Color { Color(.sRGB, red:  32/255, green:  36/255, blue:  27/255) } // #20241b
    static var wizBorder:   Color { Color(.sRGB, red:  43/255, green:  49/255, blue:  38/255) } // #2b3126
    static var wizBorder2:  Color { Color(.sRGB, red:  58/255, green:  65/255, blue:  50/255) } // #3a4132
    static var wizText:     Color { Color(.sRGB, red: 238/255, green: 241/255, blue: 232/255) } // #eef1e8
    static var wizMuted:    Color { Color(.sRGB, red: 152/255, green: 160/255, blue: 140/255) } // #98a08c
    static var wizFaint:    Color { Color(.sRGB, red: 108/255, green: 115/255, blue:  98/255) } // #6c7362
}
