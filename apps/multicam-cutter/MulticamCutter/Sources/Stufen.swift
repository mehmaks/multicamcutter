import Foundation

// MARK: - Stufen-Ansicht (Kennlinien)
//
// Jede Kategorie bekommt ein Piktogramm und höchstens zwei Stufen-Schalter mit je
// DREI Stufen. Eine Stufe ist eine kleine Tabelle „Parameter → Wert" (Kennlinie) und
// schreibt direkt in `PipelineParams` — der Expertenmodus zeigt also immer, was gilt.
// Passt keine Stufe zu den aktuellen Werten (im Expertenmodus verstellt), ist der
// Schalter „angepasst" (keine Stufe aktiv).
//
// Herleitung der Werte: apps/multicam-cutter/brain/Slider-Ansicht-Plan.md
// („Kennlinien"). Mitte = „ausgewogen" = gesichtete Werte bzw. User-Einstellungen.

struct StufenRegler: Identifiable {
    let id: String
    let titel: String
    let hilfe: String
    /// Genau drei Stufen-Namen (links · Mitte · rechts).
    let stufen: [String]
    /// Je Stufe die Parameter, die sie setzt (Schlüssel wie in `PipelineParams.toDict`).
    let werte: [[String: Any]]
}

struct StufenKategorie: Identifiable {
    let id: String
    let titel: String
    let hilfe: String
    /// Datei in Sources/Icons (ohne .svg).
    let piktogramm: String
    /// Bool-Parameter, die „Kategorie an" bedeuten. Leer = immer an (kein Schalter).
    let anSchluessel: [String]
    /// Werte beim Ausschalten (z. B. Pausen: Kürzen UND Pausen-Cutaways aus).
    let ausWerte: [String: Any]
    /// Werte, die die Kategorie beim Einschalten immer setzt (feste Entscheidungen).
    let fest: [String: Any]
    let regler: [StufenRegler]
    /// Nur zeigen, wenn es eine Totale/Halbtotale gibt.
    var nurMitTotale: Bool = false
}

enum Stufen {
    // Unveränderliche Tabelle — [String: Any] ist nicht Sendable, wird aber nie verändert.
    nonisolated(unsafe) static let kategorien: [StufenKategorie] = [
        StufenKategorie(
            id: "tempo", titel: "Tempo",
            hilfe: "How quickly the cut moves: shot lengths and cutaway lengths together.",
            piktogramm: "piktogramm-tempo", anSchluessel: [], ausWerte: [:], fest: [:],
            regler: [
                StufenRegler(
                    id: "tempo", titel: "Tempo",
                    hilfe: "Calm: longer shots and cutaways. Lively: short shots and quick cutaways — e.g. for social clips.",
                    stufen: ["calm", "balanced", "lively"],
                    werte: [
                        ["min_shot": 4.0, "max_shot": 20.0, "reaction_dur": 2.2, "cleanup_dur": 1.8, "randomness": 0.2],
                        ["min_shot": 3.0, "max_shot": 14.0, "reaction_dur": 1.8, "cleanup_dur": 1.5, "randomness": 0.3],
                        ["min_shot": 1.2, "max_shot": 6.5, "reaction_dur": 1.2, "cleanup_dur": 1.0, "randomness": 0.3],
                    ]),
            ]),
        StufenKategorie(
            id: "kopfnicken", titel: "Head nods",
            hilfe: "Cut to the listening person when they nod.",
            piktogramm: "piktogramm-kopfnicken",
            anSchluessel: ["nodding_enabled"], ausWerte: ["nodding_enabled": false], fest: [:],
            regler: [
                StufenRegler(
                    id: "nicken_oft", titel: "How often",
                    hilfe: "Minimum gap between two head-nod cutaways on the same person.",
                    stufen: ["rarely", "balanced", "often"],
                    werte: [["nodding_cooldown_s": 14.0], ["nodding_cooldown_s": 8.0], ["nodding_cooldown_s": 0.0]]),
                StufenRegler(
                    id: "nicken_sicher", titel: "Accuracy",
                    hilfe: "Strict: only clear nods — fewer cutaways, almost no mistakes. Generous: also faint nods, but sometimes laughing, shifting position or drinking.",
                    stufen: ["generous", "balanced", "strict"],
                    werte: [
                        ["min_conf": 0.6, "nodding_pattern_min_conf": ["slow_oscillation": 0.6, "strong_oscillation": 0.6]],
                        ["min_conf": 0.6, "nodding_pattern_min_conf": ["slow_oscillation": 0.7, "strong_oscillation": 1.01]],
                        ["min_conf": 0.6, "nodding_pattern_min_conf": ["slow_oscillation": 1.01, "strong_oscillation": 1.01]],
                    ]),
            ]),
        StufenKategorie(
            id: "sprachreaktionen", titel: "Interjections",
            hilfe: "Cut to the listening person for short interjections such as “mhm” or “yes”.",
            piktogramm: "piktogramm-sprachreaktionen",
            anSchluessel: ["speaking_enabled"], ausWerte: ["speaking_enabled": false],
            // Feste Entscheidungen: Erkennung auf der Analysespur, Einwürfe vor Nicken.
            fest: ["speaking_analysespur_enabled": true, "speaking_priority": true],
            regler: [
                StufenRegler(
                    id: "einwurf_oft", titel: "How often",
                    hilfe: "Minimum gap between two interjection cutaways on the same person.",
                    stufen: ["rarely", "balanced", "often"],
                    werte: [["speaking_cooldown_s": 12.0], ["speaking_cooldown_s": 4.0], ["speaking_cooldown_s": 0.0]]),
                StufenRegler(
                    id: "einwurf_sicher", titel: "Accuracy",
                    hilfe: "Strict: only clearly audible interjections. Generous: also very quiet ones, but sometimes a breath or a knock.",
                    stufen: ["generous", "balanced", "strict"],
                    werte: [
                        ["speaking_uebersprechen_db": 9.0, "speaking_umgebung_db": 4.5],
                        ["speaking_uebersprechen_db": 12.0, "speaking_umgebung_db": 6.0],
                        ["speaking_uebersprechen_db": 15.0, "speaking_umgebung_db": 8.0],
                    ]),
            ]),
        StufenKategorie(
            id: "pausen", titel: "Pauses",
            hilfe: "Shorten long pauses at speaker changes and optionally cut away during them.",
            piktogramm: "piktogramm-pausen",
            anSchluessel: ["pause_trim_enabled"],
            ausWerte: ["pause_trim_enabled": false, "pause_cutaway_enabled": false], fest: [:],
            regler: [
                StufenRegler(
                    id: "pausen_kuerzen", titel: "Shorten pauses",
                    hilfe: "How much pause remains at most: gentle 1.5 s, balanced 1.0 s, tight 0.6 s. Shorter pauses stay as they are.",
                    stufen: ["gentle", "balanced", "tight"],
                    werte: [["max_pause": 1.5], ["max_pause": 1.0], ["max_pause": 0.6]]),
                StufenRegler(
                    id: "pausen_cutaways", titel: "Cutaways in pauses",
                    hilfe: "Cut to the listener during the speaker's pauses: never, only in long pauses (from 3 s) or often (from 1.5 s).",
                    stufen: ["none", "long pauses", "often"],
                    werte: [
                        ["pause_cutaway_enabled": false],
                        ["pause_cutaway_enabled": true, "pause_cutaway_min_pause": 3.0],
                        ["pause_cutaway_enabled": true, "pause_cutaway_min_pause": 1.5],
                    ]),
            ]),
        StufenKategorie(
            id: "totale", titel: "Wide shot",
            hilfe: "How often the wide shot is used: when people talk over each other and on the way back from cutaways.",
            piktogramm: "piktogramm-totale", anSchluessel: [], ausWerte: [:], fest: [:],
            regler: [
                StufenRegler(
                    id: "totale_oft", titel: "How often",
                    hilfe: "Rarely: only for longer crosstalk (from 5 s). Often: already from 2 s, and back via the wide shot after every cutaway.",
                    stufen: ["rarely", "balanced", "often"],
                    werte: [
                        ["totale_simul_dur": 5.0, "transition_cutaway_back": [String]()],
                        ["totale_simul_dur": 3.0, "transition_cutaway_back": ["speaking_reaction"]],
                        ["totale_simul_dur": 2.0, "transition_cutaway_back": ["nodding", "speaking_reaction", "pause"]],
                    ]),
            ],
            nurMitTotale: true),
    ]

    // MARK: Logik

    /// Aktive Stufe (0…2) oder nil = „angepasst" (Werte passen zu keiner Stufe).
    static func stufe(_ r: StufenRegler, in params: PipelineParams) -> Int? {
        let ist = params.toDict()
        return r.werte.firstIndex { soll in soll.allSatisfy { gleich(ist[$0.key], $0.value) } }
    }

    /// Setzt eine Stufe — und die festen Werte ihrer Kategorie (z. B. Analysespur +
    /// Vorrang vor Nicken bei Sprachreaktionen), damit die Stufe auch wirkt.
    static func setze(_ r: StufenRegler, _ i: Int, von k: StufenKategorie, in params: inout PipelineParams) {
        params.apply(r.werte[i])
        if istAn(k, params) { params.apply(k.fest) }
    }

    static func istAn(_ k: StufenKategorie, _ params: PipelineParams) -> Bool {
        let d = params.toDict()
        return k.anSchluessel.allSatisfy { (d[$0] as? Bool) == true }
    }

    /// Einschalten setzt die festen Werte und für jeden Regler, der gerade
    /// „angepasst" ist, die Mitte — sonst bleibt die gewählte Stufe erhalten.
    static func schalte(_ k: StufenKategorie, an: Bool, in params: inout PipelineParams) {
        if !an { params.apply(k.ausWerte); return }
        var on: [String: Any] = k.fest
        for key in k.anSchluessel { on[key] = true }
        params.apply(on)
        for r in k.regler where stufe(r, in: params) == nil { params.apply(r.werte[1]) }
    }

    private static func gleich(_ a: Any?, _ b: Any) -> Bool {
        switch b {
        case let bv as Double:
            if let av = a as? Double { return abs(av - bv) < 1e-6 }
            if let av = a as? Int { return abs(Double(av) - bv) < 1e-6 }
            return false
        case let bv as Bool:
            return (a as? Bool) == bv
        case let bv as [String]:
            return Set((a as? [String]) ?? []) == Set(bv)
        case let bv as [String: Double]:
            guard let av = a as? [String: Double], av.count == bv.count else { return false }
            return bv.allSatisfy { k, v in av[k].map { abs($0 - v) < 1e-6 } ?? false }
        default:
            return false
        }
    }
}
