import SwiftUI

// MARK: - Experteneinstellungen in den Kacheln (User 21.11.)
//
// Statt einer eigenen Experten-Liste klappt „Experteneinstellungen" in jeder Kachel
// unter den Stufen-Schaltern die zugehörigen Einzelwerte auf. Alles, was zu keiner
// Kachel gehört, steht in der Kachel „Weitere". Beides schreibt in `engine.params`;
// verstellte Werte zeigen an der Stufe „angepasst".

/// Einzelwerte einer Stufen-Kachel (unter den Stufen-Schaltern).
struct ExpertenInhalt: View {
    @EnvironmentObject var engine: EngineController
    let kategorieId: String
    /// Nick-Muster (Name + Standard) aus nodding_patterns.json.
    @State private var musterDefs: [(name: String, enabled: Bool)] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Rectangle().fill(Color.wizBorder).frame(height: 1).padding(.top, 2).padding(.bottom, 2)
            switch kategorieId {
            case "tempo": tempo
            case "kopfnicken": kopfnicken
            case "sprachreaktionen": sprachreaktionen
            case "pausen": pausen
            case "totale": totale
            default: EmptyView()
            }
        }
        .environment(\.wizKompakt, true)
        .task { if kategorieId == "kopfnicken" { await musterLaden() } }
    }

    private func musterLaden() async {
        guard let np = await engine.getNoddingPatterns(),
              let data = np.content.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pats = obj["patterns"] as? [[String: Any]] else { return }
        musterDefs = pats.map { (name: $0["name"] as? String ?? "?",
                                 enabled: $0["enabled"] as? Bool ?? true) }
    }

    private var tempo: some View {
        Group {
            WizSlider("Min. shot length", $engine.params.minShot, 0.5...10, suffix: " s", help: ParamHelp.minShot)
                .angepasst(Stufen.istAngepasst("min_shot", engine.params))
            WizSlider("Max. shot length", $engine.params.maxShot, 1...60, suffix: " s", help: ParamHelp.maxShot)
                .angepasst(Stufen.istAngepasst("max_shot", engine.params))
            WizSlider("Cutaway length", $engine.params.reactionDur, 0.5...5, suffix: " s", help: ParamHelp.reactionDur)
                .angepasst(Stufen.istAngepasst("reaction_dur", engine.params))
            WizSlider("Min. cleanup length", $engine.params.cleanupDur, 0.1...5, suffix: " s", help: ParamHelp.cleanupDur)
                .angepasst(Stufen.istAngepasst("cleanup_dur", engine.params))
            WizSlider("Min. segment length", $engine.params.minEdit, 0.1...5, suffix: " s", help: ParamHelp.minEdit)
                .angepasst(Stufen.istAngepasst("min_edit", engine.params))
            WizSlider("Randomness", $engine.params.randomness, 0...0.5, format: "%.2f", help: ParamHelp.randomness)
                .angepasst(Stufen.istAngepasst("randomness", engine.params))
        }
    }

    private var kopfnicken: some View {
        Group {
            WizSlider("Gap between nod cutaways", $engine.params.noddingCooldownS, 0...30, suffix: " s",
                      format: "%.0f", help: ParamHelp.noddingCooldownS)
                .angepasst(Stufen.istAngepasst("nodding_cooldown_s", engine.params))
            WizSlider("Min. confidence", Binding(
                get: { engine.params.minConf * 100 },
                set: { engine.params.minConf = $0 / 100 }), 0...100, suffix: " %", format: "%.0f",
                      help: ParamHelp.minConf)
                .angepasst(Stufen.istAngepasst("min_conf", engine.params))
            ForEach(musterDefs, id: \.name) { pat in
                WizToggle(pat.name.replacingOccurrences(of: "_", with: " ").capitalized,
                          Binding(get: { engine.params.noddingPatterns[pat.name] ?? pat.enabled },
                                  set: { engine.params.noddingPatterns[pat.name] = $0 }))
                .angepasst((engine.params.noddingPatterns[pat.name] ?? pat.enabled) != pat.enabled)
                // Konfidenz je Muster (Teil der Stufe „Treffsicherheit"); über 100 % = aus.
                WizSlider("Confidence", Binding(
                    get: { Stufen.musterKonfidenz(pat.name, engine.params) * 100 },
                    set: { engine.params.noddingPatternMinConf[pat.name] = $0 > 100.5 ? 1.01 : $0 / 100 }),
                          50...101, help: ParamHelp.noddingPatternMinConf,
                          anzeige: { $0 > 100.5 ? loc("off") : String(format: "%.0f %%", $0) })
                    .angepasst(Stufen.musterKonfidenzAngepasst(pat.name, engine.params))
                    .disabled(!(engine.params.noddingPatterns[pat.name] ?? pat.enabled))
            }
        }
    }

    private var sprachreaktionen: some View {
        Group {
            WizSlider("Gap between interjection cutaways", $engine.params.speakingCooldownS, 0...30, suffix: " s",
                      format: "%.0f", help: ParamHelp.speakingCooldownS)
                .angepasst(Stufen.istAngepasst("speaking_cooldown_s", engine.params))
            WizSlider("Max. interjection length", $engine.params.speakingMaxDur, 0.5...10, suffix: " s",
                      help: ParamHelp.speakingMaxDur)
                .angepasst(Stufen.istAngepasst("speaking_max_dur", engine.params))
            WizToggle("Priority over head nods", $engine.params.speakingPriority, help: ParamHelp.speakingPriority)
                .disabled(!engine.params.noddingEnabled)
                .angepasst(Stufen.istAngepasst("speaking_priority", engine.params))
            WizToggle("Interjections may shorten shots", $engine.params.speakingIgnoreMinShot,
                      help: ParamHelp.speakingIgnoreMinShot)
                .angepasst(Stufen.istAngepasst("speaking_ignore_min_shot", engine.params))
            if FeatureFlags.mouthReactions {
                WizToggle("Mouth movement (beta)", $engine.params.mouthReactionsEnabled, help: ParamHelp.mouthReactionsEnabled)
                    .angepasst(Stufen.istAngepasst("mouth_reactions_enabled", engine.params))
                if engine.params.mouthReactionsEnabled {
                    WizSlider("Ignore at speaker change", $engine.params.mouthDeadband, 0...3, suffix: " s", help: ParamHelp.mouthDeadband)
                        .angepasst(Stufen.istAngepasst("mouth_deadband_s", engine.params))
                    WizSlider("Measuring window", $engine.params.mouthWindow, 0.2...1.0, suffix: " s", format: "%.2f", help: ParamHelp.mouthWindow)
                        .angepasst(Stufen.istAngepasst("mouth_window_s", engine.params))
                }
            }
        }
    }

    private var pausen: some View {
        Group {
            WizSlider("Max. pause", $engine.params.maxPause, 0.1...3, suffix: " s", help: ParamHelp.maxPause)
                .angepasst(Stufen.istAngepasst("max_pause", engine.params))
            // Werte 1:1 aus der Pipeline (pause_trim_edl.py): middle | l-cut | j-cut | random
            WizSegmented("Cut mode", $engine.params.pauseCutMode,
                         options: [("middle", "Middle"), ("l-cut", "L-Cut"),
                                   ("j-cut", "J-Cut"), ("random", "Random")],
                         help: ParamHelp.pauseCutMode)
                .angepasst(Stufen.istAngepasst("pause_cut_mode", engine.params))
            if engine.params.pauseCutMode != "middle" {
                WizSlider("Cut offset", $engine.params.pauseCutOffset, 0...10, suffix: " s",
                          help: ParamHelp.pauseCutOffset)
                    .angepasst(Stufen.istAngepasst("pause_cut_offset_s", engine.params))
            }
            WizSlider("Silence threshold", $engine.params.pauseSilenceDb, -80...(-10), suffix: " dB",
                      format: "%.0f", help: ParamHelp.pauseSilenceDb)
                .angepasst(Stufen.istAngepasst("pause_silence_db", engine.params))
            WizToggle("Cutaways in pauses", $engine.params.pauseCutawayEnabled, help: ParamHelp.pauseCutawayEnabled)
                .angepasst(Stufen.istAngepasst("pause_cutaway_enabled", engine.params))
            if engine.params.pauseCutawayEnabled {
                WizSlider("Min. pause length", $engine.params.pauseCutawayMinPause, 0.5...10, suffix: " s",
                          help: ParamHelp.pauseCutawayMinPause)
                    .angepasst(Stufen.istAngepasst("pause_cutaway_min_pause", engine.params))
            }
        }
    }

    private var totale: some View {
        Group {
            WizSlider("Crosstalk until wide shot", $engine.params.totaleSimulDur, 0.5...10, suffix: " s",
                      help: ParamHelp.totaleSimulDur)
                .angepasst(Stufen.istAngepasst("totale_simul_dur", engine.params))
            WizToggle("After head nod", $engine.params.transitionCutawayNodding, help: ParamHelp.transitionCutawayNodding)
                .angepasst(Stufen.rueckwegAngepasst("nodding", engine.params))
            WizToggle("After interjection", $engine.params.transitionCutawaySpeaking, help: ParamHelp.transitionCutawaySpeaking)
                .angepasst(Stufen.rueckwegAngepasst("speaking_reaction", engine.params))
            WizToggle("After pause", $engine.params.transitionCutawayPause, help: ParamHelp.transitionCutawayPause)
                .angepasst(Stufen.rueckwegAngepasst("pause", engine.params))
            WizSlider("Cooldown (cuts)", Binding(
                get: { Double(engine.params.transitionCutawayCooldown) },
                set: { engine.params.transitionCutawayCooldown = Int($0) }),
                      0...20, format: "%.0f", help: ParamHelp.transitionCutawayCooldown)
                .angepasst(Stufen.istAngepasst("transition_cutaway_cooldown", engine.params))
            WizSlider("Cooldown (time)", $engine.params.transitionCutawayCooldownS, 0...30, suffix: " s",
                      format: "%.0f", help: ParamHelp.transitionCutawayCooldownS)
                .angepasst(Stufen.istAngepasst("transition_cutaway_cooldown_s", engine.params))
            WizToggle("Transition on speaker change", $engine.params.transitionSpeakerChange,
                      help: ParamHelp.transitionSpeakerChange)
                .angepasst(Stufen.istAngepasst("transition_speaker_change", engine.params))
            WizSlider("Transition threshold", $engine.params.transitionReturnFactor, 1.5...4.0, suffix: "×",
                      format: "%.1f", help: ParamHelp.transitionReturnFactor)
                .angepasst(Stufen.istAngepasst("transition_return_factor", engine.params))
            WizSegmented("Multiple wide shots", $engine.params.totaleMode,
                         options: [("round_robin", "Round-robin"), ("random", "Random"), ("first", "First only")],
                         help: ParamHelp.totaleMode)
                .angepasst(Stufen.istAngepasst("totale_mode", engine.params))
        }
    }
}

/// Kachel „Weitere" — nur in den Experteneinstellungen: alles, was zu keiner der
/// Stufen-Kacheln gehört (Sprechererkennung, Vorlauf, Cutaway-Filter, Debug).
struct WeitereKachel: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Spacer()
                LucideIcon(WeitereKachel.piktogramm, size: 64).foregroundStyle(Color.brandAccent)
                Spacer()
            }
            HStack(spacing: 8) {
                Text(loc("More")).font(.system(size: 15, weight: .semibold)).foregroundStyle(Color.wizText)
                WizHelpBadge(loc("Settings that don't belong to one of the other tiles."))
                Spacer()
            }
            VStack(alignment: .leading, spacing: 0) {
                Rectangle().fill(Color.wizBorder).frame(height: 1).padding(.top, 2).padding(.bottom, 2)
                WizSlider("Speaker threshold", $engine.params.thresholdDb, 0.5...20, suffix: " dB", help: ParamHelp.thresholdDb)
                    .angepasst(Stufen.istAngepasst("threshold_db", engine.params))
                WizSlider("Change delay", $engine.params.changeDelay, 0...2, suffix: " s", help: ParamHelp.changeDelay)
                    .angepasst(Stufen.istAngepasst("change_delay", engine.params))
                WizSlider("Pre-roll", Binding(
                    get: { Double(engine.params.preRoll) },
                    set: { engine.params.preRoll = Int($0) }), 0...50, suffix: " f", format: "%.0f",
                          help: ParamHelp.preRoll)
                    .angepasst(Stufen.istAngepasst("pre_roll", engine.params))
                WizToggle("Move unsuitable cutaways", $engine.params.clipFilterEnabled, help: ParamHelp.clipFilterEnabled)
                    .angepasst(Stufen.istAngepasst("clip_filter_enabled", engine.params))
                WizToggle("Analysis overlays", $engine.params.previewOverlay, help: ParamHelp.previewOverlay)
                    .angepasst(Stufen.istAngepasst("preview_overlay", engine.params))
            }
            .environment(\.wizKompakt, true)
            Spacer(minLength: 0)
        }
        .padding(14)
        .frame(maxWidth: .infinity, minHeight: 236, alignment: .top)
        .background(Color.wizSurface2, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.wizBorder, lineWidth: 1))
    }

    /// Piktogramm der Kachel (Platzhalter, bis ein eigenes im Stil der anderen da ist).
    static let piktogramm = "circle-ellipsis"
}
