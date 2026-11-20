import SwiftUI

// MARK: - Farbwechsel des Fortschrittsbalkens (User-Idee 20.11.)
//
// Der Balken beginnt im CI-Lime, hält jede Farbe ~15 s und blendet dann über 5 s in
// die nächste. Die nächste Farbe wird zufällig aus dem Pool gezogen (nie zweimal
// dieselbe hintereinander). Alle Farben leben wie Lime und Flieder in der hellen
// Pastellwelt, damit sie auf dem dunklen Grund gleich stark wirken.
//
// Ohne gespeicherten Zustand: Die Farbe ergibt sich rein aus der vergangenen Zeit
// und einem Zufalls-Startwert je Anzeige — Abschnitt k nimmt seine Farbe aus
// einem Hash von (Startwert, k). Dadurch flackert nichts, wenn SwiftUI neu zeichnet.

enum Farbwechsel {
    /// Pool in sRGB 0…255. Index 0 = Startfarbe (CI-Lime).
    static let pool: [(Double, Double, Double)] = [
        (198, 242, 78),   // Lime (CI)
        (203, 166, 247),  // Flieder (CI-Zweitfarbe)
        (142, 240, 196),  // Mint
        (140, 207, 245),  // Himmelblau
        (247, 185, 139),  // Pfirsich
        (245, 166, 200),  // Rosé
        (242, 226, 122),  // Butter
        (126, 230, 224),  // Aqua
    ]
    static let halten: Double = 15
    static let blenden: Double = 5

    /// Farbindex des Abschnitts k (k = 0 → Lime).
    static func index(_ k: Int, seed: UInt64) -> Int {
        var i = 0
        for n in stride(from: 1, through: max(0, k), by: 1) {
            // SplitMix64 auf (seed, n) → reproduzierbarer Zufall ohne Zustand
            var z = seed &+ UInt64(n) &* 0x9E37_79B9_7F4A_7C15
            z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
            z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
            z ^= z >> 31
            let r = Int(z % UInt64(pool.count - 1))
            i = r >= i ? r + 1 : r   // nie dieselbe Farbe zweimal
        }
        return i
    }

    static func farbe(nach sekunden: Double, seed: UInt64) -> Color {
        let zyklus = halten + blenden
        let k = Int(sekunden / zyklus)
        let t = sekunden - Double(k) * zyklus
        let a = pool[index(k, seed: seed)]
        guard t > halten else { return rgb(a) }
        let b = pool[index(k + 1, seed: seed)]
        // weiches Ein- und Ausblenden statt linearem Übergang
        let x = (t - halten) / blenden
        let s = x * x * (3 - 2 * x)
        return rgb((a.0 + (b.0 - a.0) * s, a.1 + (b.1 - a.1) * s, a.2 + (b.2 - a.2) * s))
    }

    private static func rgb(_ c: (Double, Double, Double)) -> Color {
        Color(.sRGB, red: c.0 / 255, green: c.1 / 255, blue: c.2 / 255)
    }
}

/// Linearer Fortschrittsbalken mit langsamem, zufälligem Farbwechsel. `start`/`seed`
/// kommen vom Aufrufer, damit der Wechsel über alle Schritte eines Laufs weiterläuft
/// (der Balken verschwindet zwischen zwei Schritten kurz).
struct FarbwechselBalken: View {
    let wert: Double
    let gesamt: Double
    let start: Date
    let seed: UInt64

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20)) { ctx in
            SwiftUI.ProgressView(value: wert, total: gesamt)
                .progressViewStyle(.linear)
                .tint(Farbwechsel.farbe(nach: ctx.date.timeIntervalSince(start), seed: seed))
        }
    }
}
