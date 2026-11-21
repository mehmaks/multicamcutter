import SwiftUI

// MARK: - Stufen-Ansicht (ersetzt die frühere „Einfache Ansicht")
//
// Kacheln je Kategorie: großes Piktogramm (Klick = Kategorie an/aus), Titel mit (?),
// darunter bis zu zwei Stufen-Schalter mit je drei Stufen. Alles schreibt direkt in
// `engine.params` (siehe Stufen.swift) — die Experteneinstellungen zeigen dieselben
// Werte. Layout nach User-Skizze (brain/Slider-Ansicht-Plan.md → „Anordnung").

struct StufenAnsicht: View {
    @EnvironmentObject var engine: EngineController
    /// Experteneinstellungen: Einzelwerte in den Kacheln + Kachel „Weitere".
    var experte: Bool = false

    /// Kacheln der Ansicht: Stufen-Kategorien, im Expertenmodus plus „Weitere" (nil).
    private var kacheln: [StufenKategorie?] {
        kategorien.map { Optional($0) } + (experte ? [nil] : [])
    }

    private var kategorien: [StufenKategorie] {
        Stufen.kategorien.filter { !$0.nurMitTotale || engine.hasWideCamera }
    }

    private let spalten = 3

    /// Kacheln in Reihen zu je drei; die Zusammenfassung füllt den Rest der letzten
    /// Reihe (bei vier Kacheln zwei Spalten, mit Totale eine) bzw. eine eigene Reihe.
    private var reihen: [[StufenKategorie?]] {
        stride(from: 0, to: kacheln.count, by: spalten).map {
            Array(kacheln[$0..<min($0 + spalten, kacheln.count)])
        }
    }

    var body: some View {
        let rest = spalten - (reihen.last?.count ?? 0)
        Grid(horizontalSpacing: 14, verticalSpacing: 14) {
            ForEach(Array(reihen.enumerated()), id: \.offset) { i, reihe in
                GridRow(alignment: .top) {
                    ForEach(Array(reihe.enumerated()), id: \.offset) { _, k in
                        if let k { StufenKachel(kategorie: k, experte: experte) } else { WeitereKachel() }
                    }
                    if i == reihen.count - 1 && rest > 0 {
                        StufenZusammenfassung().gridCellColumns(rest)
                    }
                }
            }
            if rest == 0 {
                GridRow { StufenZusammenfassung().gridCellColumns(spalten) }
            }
        }
        .padding(.top, 16)
    }
}

/// „Was dich erwartet" — die gewählten Stufen in einfacher Sprache, live. Gestaltet
/// wie der Infokasten „Automatisch erkannt" (zurückhaltend, Flieder-Ton).
struct StufenZusammenfassung: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        (
            Text(loc("What to expect") + ": ").fontWeight(.semibold).foregroundStyle(Color.brandSecondary)
            + Text(verbatim: Stufen.zusammenfassung(engine.params, mitTotale: engine.hasWideCamera))
                .foregroundStyle(Color.wizMuted)
        )
        .font(.callout)
        .lineSpacing(3)
        .fixedSize(horizontal: false, vertical: true)
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.brandSecondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.brandSecondary.opacity(0.25), lineWidth: 1))
    }
}

struct StufenKachel: View {
    @EnvironmentObject var engine: EngineController
    let kategorie: StufenKategorie
    var experte: Bool = false

    private var schaltbar: Bool { !kategorie.anSchluessel.isEmpty }
    /// Nur ein Regler mit demselben Namen wie die Kachel (z. B. Tempo) → keine
    /// doppelte Überschrift.
    private var einRegler: Bool {
        kategorie.regler.count == 1 && kategorie.regler[0].titel == kategorie.titel
    }
    private var an: Bool { !schaltbar || Stufen.istAn(kategorie, engine.params) }

    private func umschalten() {
        guard schaltbar else { return }
        var p = engine.params
        Stufen.schalte(kategorie, an: !an, in: &p)
        withAnimation(.easeInOut(duration: 0.15)) { engine.params = p }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Piktogramm — Klick schaltet die Kategorie
            HStack {
                Spacer()
                LucideIcon(kategorie.piktogramm, size: 64)
                    .foregroundStyle(an ? Color.brandAccent : Color.wizFaint)
                    .opacity(an ? 1 : 0.55)
                    .contentShape(Rectangle())
                    .onTapGesture { umschalten() }
                    .help(schaltbar ? loc(an ? "Click to turn off" : "Click to turn on") : "")
                    .accessibilityAddTraits(schaltbar ? .isButton : [])
                Spacer()
            }
            HStack(spacing: 8) {
                Text(loc(kategorie.titel)).font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(an ? Color.wizText : Color.wizMuted)
                WizHelpBadge(kategorie.hilfe)
                Spacer()
                if einRegler, Stufen.stufe(kategorie.regler[0], in: engine.params) == nil {
                    Text(loc("custom")).font(.caption2).foregroundStyle(.brandSecondary)
                        .help(loc("Changed in the expert settings — pick a level to reset."))
                }
                if schaltbar {
                    WizSwitch(isOn: Binding(get: { an }, set: { neu in if neu != an { umschalten() } }))
                }
            }
            ForEach(kategorie.regler) { r in
                StufenSchalter(regler: r, kategorie: kategorie, ohneTitel: einRegler)
                    .disabled(!an)
                    .opacity(an ? 1 : 0.4)
            }
            if experte {
                ExpertenInhalt(kategorieId: kategorie.id)
                    .disabled(!an)
                    .opacity(an ? 1 : 0.4)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .frame(maxWidth: .infinity, minHeight: 236, alignment: .top)
        .background(Color.wizSurface2, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.wizBorder, lineWidth: 1))
    }
}

/// Drei Stufen als Segment-Schalter (Look wie `WizSegmented`), Text im Schalter.
struct StufenSchalter: View {
    @EnvironmentObject var engine: EngineController
    let regler: StufenRegler
    let kategorie: StufenKategorie
    var ohneTitel: Bool = false

    var body: some View {
        let aktiv = Stufen.stufe(regler, in: engine.params)
        VStack(alignment: .leading, spacing: 6) {
            if !ohneTitel { HStack(spacing: 6) {
                Text(loc(regler.titel)).font(.system(size: 13))
                WizHelpBadge(regler.hilfe)
                Spacer()
                if aktiv == nil {
                    Text(loc("custom")).font(.caption2).foregroundStyle(.brandSecondary)
                        .help(loc("Changed in the expert settings — pick a level to reset."))
                }
            } }
            HStack(spacing: 2) {
                ForEach(Array(regler.stufen.enumerated()), id: \.offset) { i, name in
                    let on = aktiv == i
                    Text(loc(name))
                        .font(.system(size: 11.5, weight: on ? .semibold : .regular))
                        .lineLimit(1).minimumScaleFactor(0.8)
                        .foregroundStyle(on ? Color.black : Color.wizMuted)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 5)
                        .background(on ? Color.brandAccent : Color.clear, in: RoundedRectangle(cornerRadius: 6))
                        .contentShape(Rectangle())
                        .onTapGesture {
                            var p = engine.params
                            Stufen.setze(regler, i, von: kategorie, in: &p)
                            engine.params = p
                        }
                }
            }
            .padding(2)
            .background(Color.wizSurface, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.wizBorder2, lineWidth: 1))
        }
    }
}
