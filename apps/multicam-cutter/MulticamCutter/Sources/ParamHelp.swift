import SwiftUI

// MARK: - Parameter-Hilfetexte
//
// Verbatim übernommen aus dem Web-UI-Schema `config/schemas/multicam_params.json`
// (Feld `help`), damit App und Web-Modul dieselben Erklärungen zeigen.
// Bei Parameter-Änderungen: dort UND hier nachziehen.
// Ausnahme: `fps` ist app-spezifisch (im Web-Schema nicht vorhanden).

enum ParamHelp {
    // Schnittregeln
    static let minShot = "How long a camera stays on screen at minimum before a cut to a reaction is allowed."
    static let maxShot = "If a camera stays on longer than this without a cut, the app automatically switches to a reaction."
    static let reactionDur = "How long a reaction is shown at minimum."
    static let cleanupDur = "Cuts shorter than this are removed automatically."

    // Sprecher-Erkennung
    static let thresholdDb = "How much louder someone has to be than the active speaker for a speaker change to be detected."
    static let minEdit = "Very short speech segments are merged with the next one. Prevents cutting back and forth too often."
    static let changeDelay = "How long a person has to stay louder without a break before the cut goes to them. Prevents cuts on brief overlaps."

    // Cutaway-Typen
    static let noddingEnabled = "Detects a head nod from a listening person and cuts to them at that moment."
    static let minConf = "How confident the detection has to be before a head nod is used as a cut."
    static let speakingEnabled = "Detects brief interjections or sounds from a person who isn't the active speaker and cuts to them at that moment."
    static let riseDb = "How much the baseline has to rise to trigger an interjection cutaway."
    static let speakingMaxDur = "Maximum length of an interjection cutaway. Normally the cutaway ends organically when the baseline drops."
    static let speakingAnalysespurEnabled = "Beta: finds interjections on a cleaned-up copy of each microphone, with the other person's voice and the background noise removed. Short \"mhm\" and \"yes\" stand out clearly there, so far more interjections are found. Takes about a minute longer."
    static let speakingPriority = "When a head-nod cutaway would block an interjection cutaway shortly after it (because of the minimum shot length), the nod gives way and the interjection is cut instead."
    static let mouthReactionsEnabled = "Beta: also recognises interjections from the listening person by their mouth movement. A cut is only added when the mouth moves AND their own microphone picks up sound — this finds many short interjections the sound alone misses. Takes no extra time if head-nod detection is on."
    static let mouthDeadband = "Right around a change of speaker, mouth movement is ignored — there the new speaker is already starting to talk, which isn't an interjection. Value per side, e.g. 1 s = 1 s before and 1 s after the change."
    static let mouthWindow = "How long the mouth movement is measured over. Shorter catches very short interjections like “yes”, longer is calmer and triggers less often."
    static let pauseCutawayEnabled = "Cuts to another camera during a speech pause of the active speaker."
    static let pauseCutawayMinPause = "How long a speech pause has to be at minimum for a cutaway to be inserted."
    static let clipFilterEnabled = "Uses image recognition to check whether a cutaway shows an unwanted scene (e.g. “person drinking”) and moves it automatically. Prompts can be set in the app settings."

    // Cutaway-Feintuning
    static let preRoll = "The cut is set this many frames earlier so the reaction feels more natural."
    static let randomness = "How much the length of the reaction shots may vary. Higher values make the edit feel less mechanical."

    // Pausen-Trimming
    static let pauseTrimEnabled = "Automatically shorten overly long speech pauses at speaker changes."
    static let maxPause = "Maximum pause length that is kept. Longer pauses are trimmed to this value."
    static let pauseCutMode = "Sets where the video cut sits within a pause."
    static let totaleMode = "When several cameras are marked as wide shots: which one gets cut to? Round-robin steps through them in order, Random shuffles them (the same on every run), First only always takes the same one. No effect with just one wide shot."
    static let pauseSilenceDb = "dB threshold below which both microphones count as silent. Default: -40 dB."

    // Crossbleed-Filter
    static let crossbleedGateEnabled = "Suppresses crosstalk between microphones before speaker detection. Useful when both mics are in the same room."
    static let gateFloor = "How much the inactive microphone is attenuated. -25 dB suppresses crossbleed strongly but lets a little room tone through."
    static let gateHysteresis = "Avoids “fluttering” at the boundaries. A switch only happens once the other microphone gets louder by this amount."
    static let gateWindow = "Analysis window for the level comparison. Larger for room reverb, smaller for fast switches."
    static let gateAttack = "How fast the gate opens. Shorter so the starts of syllables aren't lost."
    static let gateRelease = "How slowly the gate closes. Longer values prevent pumping."
    static let gateBothThreshold = "When the level difference is smaller than this, all microphones pass through (people speaking at once)."
    static let gateUseFiltered = "Debug: uses the filtered WAVs instead of the originals in the final timeline. For testing only."

    // Totale
    static let totaleSimulDur = "How long both have to speak at once before the cut goes to the wide shot."

    // Allgemein (app-spezifisch, nicht im Web-Schema)
    static let fps = "Frame rate of the timeline. Must match your cameras' frame rate, otherwise the cuts won't sit correctly."
    static let micsSameRecorder = "Turn this on if all your audio tracks come from the same recording device (a multitrack recorder). The app then syncs them together — so a track where no one is speaking can no longer throw off the sync."

    // Bildsprache — Übergänge über größere Einstellungen
    static let bildspracheIntro = "These settings apply to cuts to a wider shot — such as a wide shot showing several people. They're used as a gentle in-between step, instead of jumping hard from one close-up to the next."
    static let transitionSpeakerChange = "When switching between two speaking people, briefly cut to a wider shot showing both, instead of cutting over directly."
    static let transitionReturnFactor = "How much longer than the min. cut length the next cut has to be for the transition via a wider shot to be used."
    static let transitionCutawayNodding = "After a cut to a head nod, return to the speaker via a wider shot instead of cutting straight back."
    static let transitionCutawaySpeaking = "After a cut to a brief interjection, return to the speaker via a wider shot."
    static let transitionCutawayPause = "After a pause cutaway, return to the speaker via a wider shot."
    static let transitionCutawayCooldown = "How many cuts have to pass before the same wider shot is used again as a transition. Prevents it from coming up too often in a row. Used when “Cooldown (time)” isn't reached first."
    static let transitionCutawayCooldownS = "How many seconds have to pass before the same wider shot is used again. Used when “Cooldown (cuts)” isn't reached first."
}

// MARK: - (?)-Badge + Wrapper

/// Echter AppKit-Tooltip. SwiftUIs `.help(...)` zeigte in den Form-Zeilen nichts an
/// (weder Hover noch Klick); ein transparenter NSView mit `toolTip` darüber wirkt
/// zuverlässig — AppKit legt dafür selbst die Tracking-Area an.
private struct AppKitToolTip: NSViewRepresentable {
    let text: String

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        view.toolTip = text
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        nsView.toolTip = text
    }
}

/// Kleines (?) hinter einem Parameternamen. Erklärung erscheint als Tooltip beim Hovern.
struct HelpBadge: View {
    let text: String

    var body: some View {
        LucideIcon("circle-question-mark", size: 11)
            .foregroundStyle(.secondary)
            .overlay(AppKitToolTip(text: loc(text)))   // trägt den Tooltip
            .help(loc(text))                           // Fallback + VoiceOver
    }
}

/// Parametername + (?), für Picker/eigene Zeilen.
struct HelpLabel: View {
    let title: String
    let help: String

    init(_ title: String, help: String) {
        self.title = title
        self.help = help
    }

    var body: some View {
        HStack(spacing: 4) {
            Text(loc(title))
            HelpBadge(text: help)
        }
    }
}

/// Toggle mit (?) hinter der Beschriftung.
struct HelpToggle: View {
    let title: String
    @Binding var isOn: Bool
    let help: String

    init(_ title: String, isOn: Binding<Bool>, help: String) {
        self.title = title
        self._isOn = isOn
        self.help = help
    }

    var body: some View {
        Toggle(isOn: $isOn) {
            HelpLabel(title, help: help)
        }
    }
}
