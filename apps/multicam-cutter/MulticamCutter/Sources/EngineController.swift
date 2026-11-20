import SwiftUI
import Foundation
import AVFoundation
import Accelerate
import CryptoKit

/// Meldet das Ende der Wiedergabe (ersetzt den frueheren asyncAfter-Timer, der
/// nach dem Seeken in der Waveform falsch laege).
final class PlayerFinishDelegate: NSObject, AVAudioPlayerDelegate {
    private let onFinish: () -> Void
    init(onFinish: @escaping () -> Void) { self.onFinish = onFinish }
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        onFinish()
    }
}

// MARK: - App State

enum AppState {
    case idle
    case scanning   // Engine --scan laeuft
    case ready      // Ordner gescannt, Zuordnung + Parameter einstellbar
    case running    // Pipeline laeuft
    case done
    case error
}

/// Schritte des Zuordnungs-Wizards (siehe Klick-Dummy / brain/TODOs.md → Personen).
/// 1 Personen benennen · 2 Personen auf Kameras ziehen · 3 Übersicht & Start.
enum WizardStep: Int, CaseIterable {
    case persons, cameras, overview
}

// MARK: - Media Models

struct CameraInfo: Identifiable, Hashable {
    let id: Int          // index
    let filename: String
    let path: String
    var displayName: String
    var thumbnailPath: String?
    var durationSeconds: Double
    var assignedMics: [Int]  // mic indices
    /// Im Quelldateien-Panel aktiviert. Deaktivierte Quellen sind fuer Canvas
    /// UND Analyse nicht vorhanden (werden der Engine gar nicht uebergeben).
    var included: Bool = true
    /// Source-FPS aus dem Scan (ffprobe r_frame_rate). 0 = nicht lesbar.
    var fps: Double = 0
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
    static func == (lhs: CameraInfo, rhs: CameraInfo) -> Bool { lhs.id == rhs.id }
}

struct MicInfo: Identifiable, Hashable {
    let id: Int          // index
    let filename: String
    let path: String
    var displayName: String
    var previewPath: String?
    /// Dominante Stelle der Spur (Engine-Scan) — Start-Default fuer den Play-Knopf.
    var previewOffsetS: Double = 0
    /// Trennung/Isolation in dB (Median-Pegelabstand, wenn diese Person spricht).
    /// nil = nicht messbar. Rein informativ (kein Gate, siehe brain/TODOs.md).
    var separationDb: Double? = nil
    var durationSeconds: Double
    /// Siehe CameraInfo.included.
    var included: Bool = true
    /// Gesplittete Rekorder-Aufnahme (z. B. Zoom: neue Datei nach 1 GB): die
    /// Originalteile in Aufnahmereihenfolge. `path` zeigt dann auf die temporaere
    /// Gesamt-WAV der Engine (Analyse, Waveform, Abspielen); der AAF-Export
    /// verweist auf die Teile. Leer = normale Einzeldatei.
    var parts: [String] = []
    /// true = vom Nutzer verbunden („Gehört zu …"), false = automatisch erkannt.
    var partsManual: Bool = false

    func hash(into hasher: inout Hasher) { hasher.combine(id) }
    static func == (lhs: MicInfo, rhs: MicInfo) -> Bool { lhs.id == rhs.id }
}

/// Eine Quelle, die der Sync nicht automatisch einordnen konnte (Engine-Message
/// `sync_unresolved`). Der Nutzer loest sie im SyncResolutionSheet auf:
/// manuellen Offset setzen oder Quelle ausschliessen. `path` ist stabil ueber
/// Re-Runs — interne Labels (MIC3) verrutschen bei Ausschluessen.
struct UnsyncableSource: Identifiable, Hashable {
    let label: String
    let path: String
    let filename: String
    let reason: String
    let bestConfidence: Double
    let candidateOffsetFrames: Int
    var id: String { path }
}

// MARK: - Feature-Schalter

enum FeatureFlags {
    /// „Mund + Mikro" (Beta 1.1.0): vorerst abgeschaltet, Code bleibt (19.11.).
    /// Die Engine ignoriert den Parameter ebenfalls (`MOUTH_REACTIONS_AVAILABLE`
    /// in run_from_bin.py). Wieder an: beide auf true.
    static let mouthReactions = false
}

// MARK: - Parameters

struct PipelineParams: Equatable {
    // Basis (immer sichtbar)
    var minShot: Double = 3.0
    var reactionDur: Double = 1.8
    var noddingEnabled: Bool = true
    var speakingEnabled: Bool = true
    var pauseCutawayEnabled: Bool = false
    var thresholdDb: Double = 6.0
    var pauseTrimEnabled: Bool = false
    var maxPause: Double = 1.0

    // Expert: Schnittregeln
    var maxShot: Double = 14.0
    var cleanupDur: Double = 1.8

    // Expert: Sprecher-Erkennung
    var minEdit: Double = 1.0
    var changeDelay: Double = 0.3
    var pauseCutMode: String = "middle"
    /// Versatz des Kamerawechsels bei L-/J-Cut gegenüber der Pausenmitte (s), gekappt
    /// durch die verbleibende Pause. 1,0 = bei üblichen Pausenwerten die volle Verschiebung.
    var pauseCutOffset: Double = 1.0
    var pauseSilenceDb: Double = -40.0


    // Expert: Cutaway-Regeln
    var preRoll: Int = 15
    var randomness: Double = 0.2
    var minConf: Double = 0.60
    var speakingMaxDur: Double = 2.5
    // Einwürfe haben Vorrang vor Nicken (Nicken weicht, wenn es einen Einwurf blockieren würde)
    var speakingPriority: Bool = false
    /// Einwurf-Cutaways dürfen die Einstellung davor kürzer als min_shot machen
    /// (Untergrenze bleibt cleanup_dur).
    var speakingIgnoreMinShot: Bool = false
    /// Debug: Gesichtsgitter, erkannte Reaktionen und Dateiname im Vorschaubild.
    var previewOverlay: Bool = false
    // Slider-Bausteine (Stufen-Ansicht): Schnittabstand je Cutaway-Typ, Konfidenz je
    // Nick-Muster (> 1 = Muster aus), Strenge der Einwurf-Erkennung auf der Analysespur.
    // Standardwerte = bisheriges Verhalten.
    var noddingCooldownS: Double = 0
    var speakingCooldownS: Double = 0
    var noddingPatternMinConf: [String: Double] = [:]
    var speakingUmgebungDb: Double = 6
    var speakingUebersprechenDb: Double = 12
    // Beta „Mund + Mikro": Einwürfe zusätzlich über Mundbewegung erkennen
    var mouthReactionsEnabled: Bool = false
    var mouthDeadband: Double = 1.0
    var mouthWindow: Double = 0.33
    var pauseCutawayMinPause: Double = 2.0
    var clipFilterEnabled: Bool = false

    // Expert: Totale
    var totaleSimulDur: Double = 3.0
    /// Bei MEHREREN als Totale markierten Kameras: round_robin (reihum) | random
    /// (zufaellig, reproduzierbar) | first (nur die erste, altes Verhalten).
    var totaleMode: String = "round_robin"

    // Expert: Bildsprache (Übergänge über größere Einstellungen). Greift nur mit
    // einer Totale/Medium — siehe brain/Bildsprache.md. Ship-Default: nur
    // Sprecherwechsel an, Cutaway-Rückwege aus.
    var transitionSpeakerChange: Bool = true
    var transitionReturnFactor: Double = 2.5
    var transitionCutawayNodding: Bool = false
    var transitionCutawaySpeaking: Bool = false
    var transitionCutawayPause: Bool = false
    var transitionCutawayCooldown: Int = 6
    var transitionCutawayCooldownS: Double = 8.0

    // Material-Eigenschaft, kein Kreativregler: Bestätigt der Nutzer, dass alle
    // Mikrofone aus EINEM Mehrspur-Recorder kommen, teilen sie sich eine Clock.
    // Eine still aufgenommene Spur bremst den Sync dann nicht mehr aus (sie erbt
    // den gemeinsamen Offset, statt den Lauf abzubrechen). Nur relevant ab 2 Mics.
    var micsSameRecorder: Bool = false

    /// Occasion-Liste für die Engine (transition_cutaway_back) aus den drei Schaltern.
    var cutawayBackList: [String] {
        var l: [String] = []
        if transitionCutawayNodding  { l.append("nodding") }
        if transitionCutawaySpeaking { l.append("speaking_reaction") }
        if transitionCutawayPause    { l.append("pause") }
        return l
    }

    // Nodding-Pattern-Toggles PRO PRESET: pattern-name → enabled. Leer = alle
    // Defaults aus nodding_patterns.json. Geht als "nodding_patterns" an die Engine
    // (überschreibt dort je Pattern das enabled) und wird mit dem Preset gespeichert.
    var noddingPatterns: [String: Bool] = [:]

    func toJSON() -> String {
        let dict: [String: Any] = [
            "min_shot": minShot,
            "max_shot": maxShot,
            "cleanup_dur": cleanupDur,
            "reaction_dur": reactionDur,
            "pause_trim_enabled": pauseTrimEnabled,
            "max_pause": maxPause,
            "pause_cut_mode": pauseCutMode,
            "pause_cut_offset_s": pauseCutOffset,
            "pause_silence_db": pauseSilenceDb,
            "min_conf": minConf,
            "min_edit": minEdit,
            "change_delay": changeDelay,
            "nodding_enabled": noddingEnabled,
            "speaking_enabled": speakingEnabled,
            "pause_cutaway_enabled": pauseCutawayEnabled,
            "pause_cutaway_min_pause": pauseCutawayMinPause,
            "clip_filter_enabled": clipFilterEnabled,
            "pre_roll": preRoll,
            "randomness": randomness,
            "speaking_max_dur": speakingMaxDur,
            "speaking_priority": speakingPriority,
            "speaking_ignore_min_shot": speakingIgnoreMinShot,
            "preview_overlay": previewOverlay,
            "nodding_cooldown_s": noddingCooldownS,
            "speaking_cooldown_s": speakingCooldownS,
            "nodding_pattern_min_conf": noddingPatternMinConf,
            "speaking_umgebung_db": speakingUmgebungDb,
            "speaking_uebersprechen_db": speakingUebersprechenDb,
            "mouth_reactions_enabled": mouthReactionsEnabled,
            "mouth_deadband_s": mouthDeadband,
            "mouth_window_s": mouthWindow,
            "threshold_db": thresholdDb,
            "totale_simul_dur": totaleSimulDur,
            "totale_mode": totaleMode,
            "nodding_patterns": noddingPatterns,
            "transition_speaker_change": transitionSpeakerChange,
            "transition_return_factor": transitionReturnFactor,
            "transition_cutaway_back": cutawayBackList,
            "transition_cutaway_cooldown": transitionCutawayCooldown,
            "transition_cutaway_cooldown_s": transitionCutawayCooldownS,
            "mics_same_recorder": micsSameRecorder,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: dict),
              let str = String(data: data, encoding: .utf8) else { return "{}" }
        return str
    }

    func toDict() -> [String: Any] {
        [
            "min_shot": minShot, "max_shot": maxShot, "cleanup_dur": cleanupDur,
            "reaction_dur": reactionDur, "pause_trim_enabled": pauseTrimEnabled,
            "max_pause": maxPause, "pause_cut_mode": pauseCutMode,
            "pause_cut_offset_s": pauseCutOffset,
            "pause_silence_db": pauseSilenceDb,
            "min_conf": minConf, "min_edit": minEdit, "change_delay": changeDelay,
            "nodding_enabled": noddingEnabled, "speaking_enabled": speakingEnabled,
            "pause_cutaway_enabled": pauseCutawayEnabled,
            "pause_cutaway_min_pause": pauseCutawayMinPause,
            "clip_filter_enabled": clipFilterEnabled,
            "pre_roll": preRoll, "randomness": randomness,
            "speaking_max_dur": speakingMaxDur,
            "speaking_priority": speakingPriority,
            "speaking_ignore_min_shot": speakingIgnoreMinShot,
            "preview_overlay": previewOverlay,
            "nodding_cooldown_s": noddingCooldownS,
            "speaking_cooldown_s": speakingCooldownS,
            "nodding_pattern_min_conf": noddingPatternMinConf,
            "speaking_umgebung_db": speakingUmgebungDb,
            "speaking_uebersprechen_db": speakingUebersprechenDb,
            "mouth_reactions_enabled": mouthReactionsEnabled,
            "mouth_deadband_s": mouthDeadband, "mouth_window_s": mouthWindow,
            "threshold_db": thresholdDb, "totale_simul_dur": totaleSimulDur,
            "totale_mode": totaleMode,
            "nodding_patterns": noddingPatterns,
            "transition_speaker_change": transitionSpeakerChange,
            "transition_return_factor": transitionReturnFactor,
            "transition_cutaway_back": cutawayBackList,
            "transition_cutaway_cooldown": transitionCutawayCooldown,
            "transition_cutaway_cooldown_s": transitionCutawayCooldownS,
            "mics_same_recorder": micsSameRecorder,
        ]
    }

    mutating func apply(_ dict: [String: Any]) {
        if let v = dict["min_shot"] as? Double { minShot = v }
        if let v = dict["max_shot"] as? Double { maxShot = v }
        if let v = dict["cleanup_dur"] as? Double { cleanupDur = v }
        if let v = dict["reaction_dur"] as? Double { reactionDur = v }
        if let v = dict["pause_trim_enabled"] as? Bool { pauseTrimEnabled = v }
        if let v = dict["max_pause"] as? Double { maxPause = v }
        if let v = dict["pause_cut_mode"] as? String { pauseCutMode = v }
        if let v = dict["pause_cut_offset_s"] as? Double { pauseCutOffset = v }
        if let v = dict["pause_silence_db"] as? Double { pauseSilenceDb = v }
        if let v = dict["min_conf"] as? Double { minConf = v }
        if let v = dict["min_edit"] as? Double { minEdit = v }
        if let v = dict["change_delay"] as? Double { changeDelay = v }
        if let v = dict["nodding_enabled"] as? Bool { noddingEnabled = v }
        if let v = dict["speaking_enabled"] as? Bool { speakingEnabled = v }
        if let v = dict["pause_cutaway_enabled"] as? Bool { pauseCutawayEnabled = v }
        if let v = dict["pause_cutaway_min_pause"] as? Double { pauseCutawayMinPause = v }
        if let v = dict["clip_filter_enabled"] as? Bool { clipFilterEnabled = v }
        if let v = dict["pre_roll"] as? Int { preRoll = v }
        if let v = dict["randomness"] as? Double { randomness = v }
        if let v = dict["speaking_max_dur"] as? Double { speakingMaxDur = v }
        if let v = dict["speaking_priority"] as? Bool { speakingPriority = v }
        if let v = dict["speaking_ignore_min_shot"] as? Bool { speakingIgnoreMinShot = v }
        if let v = dict["preview_overlay"] as? Bool { previewOverlay = v }
        if let v = dict["nodding_cooldown_s"] as? Double { noddingCooldownS = v }
        if let v = dict["speaking_cooldown_s"] as? Double { speakingCooldownS = v }
        if let v = dict["nodding_pattern_min_conf"] as? [String: Double] { noddingPatternMinConf = v }
        if let v = dict["speaking_umgebung_db"] as? Double { speakingUmgebungDb = v }
        if let v = dict["speaking_uebersprechen_db"] as? Double { speakingUebersprechenDb = v }
        if let v = dict["mouth_reactions_enabled"] as? Bool { mouthReactionsEnabled = v }
        if let v = dict["mouth_deadband_s"] as? Double { mouthDeadband = v }
        if let v = dict["mouth_window_s"] as? Double { mouthWindow = v }
        if let v = dict["threshold_db"] as? Double { thresholdDb = v }
        if let v = dict["totale_simul_dur"] as? Double { totaleSimulDur = v }
        if let v = dict["totale_mode"] as? String { totaleMode = v }
        // Aus JSON kommen Bools als NSNumber(CFBoolean) → `as? Bool` bridged sie.
        if let raw = dict["nodding_patterns"] as? [String: Any] {
            noddingPatterns = raw.compactMapValues { $0 as? Bool }
        }
        if let v = dict["transition_speaker_change"] as? Bool { transitionSpeakerChange = v }
        if let v = dict["transition_return_factor"] as? Double { transitionReturnFactor = v }
        if let v = dict["transition_cutaway_cooldown"] as? Int { transitionCutawayCooldown = v }
        if let v = dict["transition_cutaway_cooldown_s"] as? Double { transitionCutawayCooldownS = v }
        if let list = dict["transition_cutaway_back"] as? [String] {
            transitionCutawayNodding  = list.contains("nodding")
            transitionCutawaySpeaking = list.contains("speaking_reaction")
            transitionCutawayPause    = list.contains("pause")
        }
        if let v = dict["mics_same_recorder"] as? Bool { micsSameRecorder = v }
    }
}

// MARK: - Personen

/// Eine Person ist an genau EIN Mikrofon gebunden (beim Scan automatisch pro Mic
/// angelegt). Ihre Kameras sind alle aktiven Cams, deren Mic-Zuordnung dieses Mic
/// enthaelt. Rein abgeleitet aus dem bestehenden Cam↔Mic-Graphen: die Engine sieht
/// davon (noch) nichts — der Kontrakt bleibt `cam.assignedMics` + `--cam-types`.
///
/// Host/Gast gab es frueher als CamTag, taten aber nichts. Wenn Rollen kommen,
/// dann als Eigenschaft der Person (z. B. „Host bekommt weniger Cutaways"),
/// nicht als Kamera-Tag.
struct Person: Identifiable, Hashable {
    let id: Int          // == micId (die Person ist an ihr Mic verankert)
    var name: String     // Anzeigename (Default = Mic-Anzeigename)
    let micId: Int
    var camIds: [Int]    // aktive Cams, die diesem Mic zugeordnet sind
}

// MARK: - Preset Management

struct Preset: Identifiable, Hashable {
    let id: String  // filename ohne .json
    let name: String
    let builtIn: Bool
}

final class PresetManager: Sendable {
    static let shared = PresetManager()

    private var presetsDir: URL {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MulticamCutter/presets")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    // Eingebaute Presets gibt es seit 20.11. nicht mehr: die einfache Ansicht (Stufen)
    // übernimmt ihre Rolle. Die Preset-Liste enthält nur noch eigene Presets.

    func listPresets() -> [Preset] {
        var result: [Preset] = []
        if let files = try? FileManager.default.contentsOfDirectory(
            at: presetsDir, includingPropertiesForKeys: nil
        ) {
            for file in files where file.pathExtension == "json" {
                let id = file.deletingPathExtension().lastPathComponent
                if let data = try? Data(contentsOf: file),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let name = json["name"] as? String {
                    result.append(Preset(id: id, name: name, builtIn: false))
                }
            }
        }
        return result.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    func loadPreset(_ id: String) -> PipelineParams? {
        let file = presetsDir.appendingPathComponent("\(id).json")
        if let data = try? Data(contentsOf: file),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let paramsDict = json["params"] as? [String: Any] {
            var params = PipelineParams()
            params.apply(paramsDict)
            return params
        }
        return nil
    }

    func savePreset(name: String, params: PipelineParams) -> Preset {
        let id = name.lowercased()
            .replacingOccurrences(of: " ", with: "_")
            .replacingOccurrences(of: "[^a-z0-9_]", with: "", options: .regularExpression)
        let dict: [String: Any] = ["name": name, "params": params.toDict()]
        let file = presetsDir.appendingPathComponent("\(id).json")
        if let data = try? JSONSerialization.data(withJSONObject: dict, options: .prettyPrinted) {
            try? data.write(to: file)
        }
        return Preset(id: id, name: name, builtIn: false)
    }

    func deletePreset(_ id: String) {
        let file = presetsDir.appendingPathComponent("\(id).json")
        try? FileManager.default.removeItem(at: file)
    }

    func exportPreset(_ params: PipelineParams, name: String) -> URL? {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.json]
        panel.nameFieldStringValue = "\(name).json"
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        let dict: [String: Any] = ["name": name, "params": params.toDict()]
        if let data = try? JSONSerialization.data(withJSONObject: dict, options: .prettyPrinted) {
            try? data.write(to: url)
        }
        return url
    }

    func importPreset() -> (String, PipelineParams)? {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url,
              let data = try? Data(contentsOf: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let name = json["name"] as? String,
              let paramsDict = json["params"] as? [String: Any] else { return nil }
        var params = PipelineParams()
        params.apply(paramsDict)
        // Auch lokal speichern
        _ = savePreset(name: name, params: params)
        return (name, params)
    }
}

// MARK: - Engine Controller

@MainActor
class EngineController: ObservableObject {
    @Published var state: AppState = .idle
    @Published var wizardStep: WizardStep = .persons   // aktueller Schritt im Zuordnungs-Wizard
    // Beim erneuten Oeffnen eines bekannten Ordners springt der Wizard direkt zur
    // Uebersicht (gespeicherte Zuordnungen). Ohne Hinweis wirkt das wie ein Fehler
    // ("warum bin ich im dritten Schritt?") — dieses Flag zeigt das Info-Banner.
    @Published var sessionRestored = false
    @Published var folderURL: URL?
    @Published var episodeName: String = ""
    @Published var cameraInfos: [CameraInfo] = []
    @Published var micInfos: [MicInfo] = []
    @Published var fps: Double = 25.0
    /// Startet mit den zuletzt genutzten Einstellungen (app-weit, auch nach Neustart —
    /// User 20.11.). Eine Folge mit eigener `.multicam` überschreibt sie beim Laden.
    /// Jede Änderung wird sofort gemerkt; weg sind sie erst mit den App-Daten.
    @Published var params = EngineController.letzteEinstellungen() {
        didSet { if params != oldValue { Self.merkeEinstellungen(params) } }
    }

    private static let letzteEinstellungenKey = "lastUsedParams"

    static func letzteEinstellungen() -> PipelineParams {
        var p = PipelineParams()
        if let data = UserDefaults.standard.data(forKey: letzteEinstellungenKey),
           let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            p.apply(dict)
        }
        return p
    }

    private static func merkeEinstellungen(_ p: PipelineParams) {
        if let data = try? JSONSerialization.data(withJSONObject: p.toDict()) {
            UserDefaults.standard.set(data, forKey: letzteEinstellungenKey)
        }
    }

    // Progress (Pipeline)
    @Published var stepLabel: String = ""
    @Published var stepNum: Int = 0
    @Published var totalSteps: Int = 1
    @Published var stepPercent: Double = 0
    @Published var stepETA: String = ""
    /// Zaehler des laufenden Schritts, z.B. "341 von 384". Ergaenzt stepETA.
    @Published var stepCounter: String = ""
    /// Relatives Gewicht je Schritt (Engine `step_weights`) fuer einen ehrlichen
    /// Dock-Balken. Leer bzw. Laenge != totalSteps → Gleichgewichtung (alt).
    @Published var stepWeights: [Double] = []

    /// Wall-Clock-Dauer je Pipeline-Phase (Key → Sekunden) für die Telemetrie
    /// (runtime.per_step_s). Gefüllt aus dem `key`-Feld der step_start(_sub)-
    /// Nachrichten; rollt nur bei Key-WECHSEL um, sodass Nodding×N (gleicher Key)
    /// automatisch summiert. Kein @Published — reine Messung, keine UI.
    private var perStepSeconds: [String: Double] = [:]
    private var stepTimingKey: String? = nil
    private var stepTimingStart: Date? = nil

    /// Gesamtfortschritt 0…1 über alle Schritte (für den Dock-Balken). stepNum ist 1-basiert.
    var overallProgress: Double {
        guard totalSteps > 0 else { return 0 }
        // Gewichtet, wenn die Engine passende Gewichte geliefert hat (Nodding/CLIP
        // dominieren) — sonst gleichgewichtet wie bisher.
        if stepWeights.count == totalSteps {
            let total = stepWeights.reduce(0, +)
            if total > 0 {
                let doneSteps = max(min(stepNum - 1, stepWeights.count), 0)
                let done = stepWeights.prefix(doneSteps).reduce(0, +)
                let cur = (stepNum >= 1 && stepNum <= stepWeights.count)
                          ? stepWeights[stepNum - 1] * stepPercent / 100 : 0
                return min(max((done + cur) / total, 0), 1)
            }
        }
        let f = (Double(stepNum - 1) + stepPercent / 100) / Double(totalSteps)
        return min(max(f, 0), 1)
    }

    /// Fortschritt der FPS-Konvertierung fuer den Dock-Balken. Datei
    /// `convertFileIndex` von `convertFileCount`, innerhalb der Datei
    /// `convertDone/convertTotal`. Ohne Sekunden-Total (ganz am Anfang einer
    /// Datei) zaehlt nur der Dateifortschritt. (Bei genau einer Zieldatei — dem
    /// Normalfall — ist das identisch zu `convertDone/convertTotal` und damit
    /// deckungsgleich mit dem Panel.)
    var convertProgress: Double {
        guard convertFileCount > 0 else { return 0 }
        let fileFrac = convertTotal > 0 ? min(max(convertDone / convertTotal, 0), 1) : 0
        let done = Double(max(convertFileIndex - 1, 0)) + fileFrac
        return min(max(done / Double(convertFileCount), 0), 1)
    }
    @Published var logMessages: [String] = []

    // Facemesh-Preview (wird während Nodding-Analyse periodisch aktualisiert)
    @Published var facemeshImage: NSImage?
    private var previewPath: String?
    private var previewTimer: Timer?
    /// Zeitpunkt des Poll-Starts — aeltere Stills (vom vorigen Lauf) werden ignoriert.
    private var previewStartedAt: Date?

    // Progress (Scan)
    @Published var scanLabel: String = ""
    @Published var scanPercent: Double = 0

    // Result
    @Published var resultAAF: String?
    @Published var resultStats: [String: String]?
    @Published var errorMessage: String = ""

    /// Vom Sync als nicht automatisch einordbar gemeldete Quellen (Baustein 2/3).
    @Published var syncUnresolvedSources: [UnsyncableSource] = []
    @Published var showSyncResolution = false
    /// Dateiname der Referenzkamera (Offsets sind darauf normiert) — fuers Sheet,
    /// damit „relativ zur ersten Kamera" nicht geraten werden muss.
    @Published var syncReferenceFilename: String = ""
    /// Manuell gesetzte Sync-Offsets (Pfad -> Frames rel. CAM1) fuer den Re-Run.
    /// Pfad-basiert, damit sie Ausschluss-bedingte Label-Verschiebungen ueberleben;
    /// stale Pfade (anderer Ordner) ignoriert die Engine automatisch.
    @Published var manualSyncOffsets: [String: Int] = [:]

    // Feedback / Bug-Report (Formular in Feedback.swift, Contract in brain/Feedback-API.md)
    @Published var showingFeedback = false
    var feedbackDraft = FeedbackDraft()

    // CLIP-Modell (581 MB, wird auf Wunsch einmalig geladen)
    @Published var showClipPrompt = false
    @Published var isDownloadingClip = false
    @Published var clipDone: Int64 = 0
    @Published var clipTotal: Int64 = 0
    @Published var clipError: String?
    private var clipProcess: Process?

    // FPS-Konvertierung (Mismatch beheben)
    @Published var isConverting = false
    @Published var convertLabel = ""           // Dateiname der aktuellen Konvertierung
    @Published var convertLog: [String] = []   // ffmpeg-Roh-Log (nur fuer Fehler-Diagnose)
    @Published var convertError: String?
    /// Manuelle Verbindung gesplitteter Aufnahmen ging nicht (z. B. anderes Format).
    @Published var joinWarning: String?

    /// Manuelle Korrekturen der Split-Erkennung, per DATEINAME (stabil wie die
    /// übrigen Session-Daten), gespeichert in `.multicam`. Gehen als
    /// `--join-groups`/`--keep-separate` an den Scan — die Engine fügt zusammen.
    private var audioJoinGroups: [[String]] = []
    private var audioKeepSeparate: [String] = []
    @Published var convertFileIndex = 0        // laufende Datei (1-basiert)
    @Published var convertFileCount = 0        // Anzahl zu konvertierender Dateien
    @Published var convertDone: Double = 0     // konvertierte Sekunden der aktuellen Datei
    @Published var convertTotal: Double = 0    // Gesamtdauer der aktuellen Datei
    private var convertProcess: Process?       // fuer Abbrechen (SIGTERM)
    private var convertCanceled = false
    private var convertTargetDurations: [Double] = []  // Dauer je Ziel-Datei (fuer ETA)
    private var convertFileStartedAt: Date?    // Wall-Clock-Start der aktuellen Datei

    // Audio Playback
    @Published var playingMicId: Int? = nil
    private var audioPlayer: AVAudioPlayer?
    private var playerFinishDelegate: PlayerFinishDelegate?

    // Sidebar Selection
    @Published var selectedCamId: Int? = nil
    @Published var selectedMicId: Int? = nil
    @Published var editingCamId: Int? = nil
    @Published var editingMicId: Int? = nil

    /// Mics die keiner Cam zugeordnet sind
    /// Nur die im Quelldateien-Panel aktivierten Quellen. Alles andere existiert
    /// weder auf dem Canvas noch fuer die Analyse.
    var activeCams: [CameraInfo] { cameraInfos.filter { $0.included } }
    var activeMics: [MicInfo] { micInfos.filter { $0.included } }

    /// Ausgeblendete (getrashte) Quellen — für die „wieder aufnehmen"-Chips im Wizard.
    /// Ohne die gäbe es keinen Weg zurück (der Zustand steht persistent in `.multicam`).
    var excludedCams: [CameraInfo] { cameraInfos.filter { !$0.included } }
    var excludedMics: [MicInfo] { micInfos.filter { !$0.included } }

    /// Aktive Cams, die auffällig viel kürzer sind als die längste Quelle — fast immer
    /// eine abgebrochene/unvollständige Konvertierung (verwaiste Teildatei, die die App
    /// sonst still als Cam benutzt → kaputte AAF „timecode extents do not match" + Sync-
    /// Versatz, weil CAM1 die verkürzte Referenz ist). Schwelle bewusst niedrig (50 %),
    /// damit legitim kürzere Clips nicht fälschlich anschlagen.
    var suspiciouslyShortCams: [CameraInfo] {
        let ref = max(activeCams.map(\.durationSeconds).max() ?? 0,
                      activeMics.map(\.durationSeconds).max() ?? 0)
        guard ref > 0 else { return [] }
        return activeCams.filter { $0.durationSeconds > 0 && $0.durationSeconds < ref * 0.5 }
    }

    /// Kameras, die tatsaechlich analysiert werden: aktiviert UND mindestens eine
    /// Person (Mic) zugeordnet. Eine Cam ohne Person hat in der Analyse keine Rolle
    /// und wird der Engine gar nicht uebergeben.
    var analysisCams: [CameraInfo] {
        activeCams.filter { !$0.assignedMics.isEmpty }
    }

    /// analysisCams in ENGINE-Reihenfolge: Close-Cams zuerst (nach Personenzahl
    /// aufsteigend), Totalen ans Ende. Grund: Die Basis-EDL diarisiert binär die
    /// ERSTEN ZWEI Kameras aus `--cams` (RMS CAM1 vs CAM2). Die müssen zwei disjunkte
    /// Close-Cams sein — NIE die Totale (die alle Mics summiert und die Diarisierung
    /// kippen ließe). Diese Ordnung garantiert das, ohne Engine-Änderung.
    /// ALLE positionalen Args (`--cams`/`--cam-mics`/`--cam-types`/`--display-names`)
    /// müssen dieselbe Ordnung nutzen.
    var orderedAnalysisCams: [CameraInfo] {
        let roles = camRoles()
        return analysisCams.sorted { a, b in
            let aWide = roles[a.id] == .wide
            let bWide = roles[b.id] == .wide
            if aWide != bWide { return !aWide }                       // Close vor Totale
            let pa = personIds(of: a).count, pb = personIds(of: b).count
            if pa != pb { return pa < pb }                           // wenige Personen zuerst
            return a.id < b.id                                       // stabil
        }
    }

    /// Frueher: Nah-Kameras jenseits der ersten beiden, die der binaere Schnitt nicht
    /// bedienen konnte. Seit der N-fachen Diarisierung (`build_base_edl_n`) sind mehr
    /// als zwei Nah-Kameras moeglich — die Engine diarisiert ueber alle Personen und
    /// schneidet jede auf ihre engste Kamera. Der Waechter ist damit aufgehoben; die
    /// Property bleibt (leer), damit Banner/Blockmeldung, die sie abfragen, still
    /// verschwinden, ohne dass es weitere Aenderungen braucht.
    var unsupportedCloseCams: [CameraInfo] { [] }

    // MARK: - Personen (abgeleitet)

    /// Eine Person je aktivem Mic. Name = Mic-Anzeigename, Kameras = alle aktiven
    /// Cams, deren Mic-Zuordnung dieses Mic enthaelt. Reine Sicht auf denselben
    /// Graphen — aendert nichts an dem, was die Engine bekommt.
    var persons: [Person] {
        activeMics.map { mic in
            let cams = activeCams.filter { $0.assignedMics.contains(mic.id) }
            return Person(id: mic.id, name: mic.displayName, micId: mic.id,
                          camIds: cams.map { $0.id })
        }
    }

    // MARK: - Bildgrößen-Ableitung (Wizard — „Close gewinnt")

    enum CamRole: String { case close, wide, unused }

    /// Personen einer Kamera = ihre aktiven zugeordneten Mics (Person == Mic).
    private func personIds(of cam: CameraInfo) -> [Int] {
        let active = Set(activeMics.map { $0.id })
        return cam.assignedMics.filter { active.contains($0) }
    }

    /// Bildgröße je Kamera, rein aus dem Personen-Graphen abgeleitet — KEIN manuelles
    /// Flag mehr. Regel: Für jede Person ist ihre engste Kamera die mit den WENIGSTEN
    /// Personen. Eine Kamera ist TOTALE, wenn JEDE Person darauf woanders enger ist;
    /// ist sie für ≥1 Person die engste, ist sie ein CLOSE („Close gewinnt").
    /// Hat das Setup eine größere Einstellung (Totale/Medium)? Nur dann greifen
    /// die Bildsprache-Regeln — sonst gibt es keine gemeinsame größere Kamera.
    var hasWideCamera: Bool {
        camRoles().values.contains(.wide)
    }

    func camRoles() -> [Int: CamRole] {
        // Minimale Personen-Anzahl je Person über alle Kameras, die sie zeigen.
        var minCount: [Int: Int] = [:]
        for cam in activeCams {
            let ppl = personIds(of: cam)
            let n = ppl.count
            guard n > 0 else { continue }
            for pid in ppl { minCount[pid] = min(minCount[pid] ?? n, n) }
        }
        var roles: [Int: CamRole] = [:]
        for cam in activeCams {
            let ppl = personIds(of: cam)
            if ppl.isEmpty { roles[cam.id] = .unused; continue }
            let n = ppl.count
            roles[cam.id] = ppl.contains { minCount[$0] == n } ? .close : .wide
        }
        return roles
    }

    /// Bildgrößen-Leiter einer Person: ihre Kameras, sortiert nach Personen-Anzahl
    /// aufsteigend (engste zuerst) — für die Übersicht (Wizard-Screen 3).
    func shotLadder(for personId: Int) -> [CameraInfo] {
        activeCams
            .filter { $0.assignedMics.contains(personId) }
            .sorted { personIds(of: $0).count < personIds(of: $1).count }
    }

    /// „Person löschen" im Wizard = dieses Mic ist kein Sprecher → aus der Analyse.
    /// (Person == aktives Mic; Ausschließen löst zugleich alle Zuordnungen.)
    func deletePerson(_ personId: Int) { setMicIncluded(personId, false) }

    // MARK: - Personen-Zuordnung (Wizard, MEHRFACH erlaubt)
    //
    // Anders als `assignMic` (eine Cam pro Mic) darf eine Person hier auf MEHREREN
    // Kameras liegen — sie ist ja in Close UND Totale zu sehen. Genau daraus leitet
    // `camRoles()` die Bildgröße ab.

    func addPersonToCam(_ personId: Int, _ camId: Int) {
        guard let idx = cameraInfos.firstIndex(where: { $0.id == camId }) else { return }
        if !cameraInfos[idx].assignedMics.contains(personId) {
            cameraInfos[idx].assignedMics.append(personId)
            saveSession()
        }
    }

    func removePersonFromCam(_ personId: Int, _ camId: Int) {
        guard let idx = cameraInfos.firstIndex(where: { $0.id == camId }) else { return }
        cameraInfos[idx].assignedMics.removeAll { $0 == personId }
        saveSession()
    }

    /// „zeigt alle" auf einer Kamera → alle aktiven Personen zuordnen (Raum-Cam).
    func setCamShowsAllPersons(_ camId: Int) {
        guard let idx = cameraInfos.firstIndex(where: { $0.id == camId }) else { return }
        cameraInfos[idx].assignedMics = activeMics.map { $0.id }
        saveSession()
    }

    var unassignedMics: [MicInfo] {
        let assigned = Set(activeCams.flatMap { $0.assignedMics })
        return activeMics.filter { !assigned.contains($0.id) }
    }

    /// Aktiviert/deaktiviert eine Quelle. Beim Deaktivieren muessen Zuordnungen
    /// aufgeloest werden: ein deaktiviertes Video gibt seine Mics zurueck nach
    /// "Nicht zugeordnet", ein deaktiviertes Mic loest sich von seiner Kamera.
    func setCamIncluded(_ camId: Int, _ included: Bool) {
        guard let idx = cameraInfos.firstIndex(where: { $0.id == camId }) else { return }
        cameraInfos[idx].included = included
        if !included {
            cameraInfos[idx].assignedMics.removeAll()
            if selectedCamId == camId { selectedCamId = nil }
        }
        saveSession()
    }

    func setMicIncluded(_ micId: Int, _ included: Bool) {
        guard let idx = micInfos.firstIndex(where: { $0.id == micId }) else { return }
        micInfos[idx].included = included
        if !included {
            for i in cameraInfos.indices {
                cameraInfos[i].assignedMics.removeAll { $0 == micId }
            }
        }
        saveSession()
    }

    private var engineProcess: Process?

    // MARK: - Folder Selection (triggers scan)

    func setFolder(_ url: URL) {
        folderURL = url
        episodeName = url.lastPathComponent
        cameraInfos = []
        micInfos = []
        state = .scanning

        // wizardStep entscheidet runScan nach loadSession (Phase 5: schon zugeordnet
        // → Übersicht, sonst Schritt 1).
        Task {
            await runScan(folder: url)
        }
    }

    // MARK: - Mic Assignment

    func assignMic(_ micIndex: Int, toCamera camIndex: Int) {
        for i in cameraInfos.indices {
            cameraInfos[i].assignedMics.removeAll { $0 == micIndex }
        }
        if let idx = cameraInfos.firstIndex(where: { $0.id == camIndex }) {
            cameraInfos[idx].assignedMics.append(micIndex)
        }
        saveSession()
    }

    func unassignMic(_ micIndex: Int) {
        for i in cameraInfos.indices {
            cameraInfos[i].assignedMics.removeAll { $0 == micIndex }
        }
        saveSession()
    }

    func removeCam(_ camIndex: Int) {
        // Zugeordnete Mics freigeben
        if let idx = cameraInfos.firstIndex(where: { $0.id == camIndex }) {
            cameraInfos.remove(at: idx)
        }
        saveSession()
    }

    func removeMic(_ micIndex: Int) {
        unassignMic(micIndex)
        micInfos.removeAll { $0.id == micIndex }
        saveSession()
    }

    func renameCam(_ camIndex: Int, to name: String) {
        if let idx = cameraInfos.firstIndex(where: { $0.id == camIndex }) {
            cameraInfos[idx].displayName = name
        }
        saveSession()
    }

    func renameMic(_ micIndex: Int, to name: String) {
        if let idx = micInfos.firstIndex(where: { $0.id == micIndex }) {
            micInfos[idx].displayName = name
        }
        saveSession()
    }

    /// cam_mics Format fuer die Engine: ["1", "0"] oder ["0,1", "2"]
    /// `--cam-mics` ist POSITIONSBASIERT: Eintrag N gehoert zu der N-ten Kamera aus
    /// `--cams`, und die Werte sind Positionen in `--mics`. Da wir der Engine nur die
    /// AKTIVEN Quellen uebergeben, muessen die gespeicherten Mic-IDs auf ihre Position
    /// in `activeMics` umgerechnet werden — sonst landen Mics bei falschen Kameras.
    var camMicsArgs: [String] {
        let activeMicIds = activeMics.map { $0.id }
        return orderedAnalysisCams.map { cam in
            cam.assignedMics
                .compactMap { micId in activeMicIds.firstIndex(of: micId) }
                .map(String.init)
                .joined(separator: ",")
        }
    }

    // MARK: - Session Persistence (.multicam Datei im Episoden-Ordner)

    private var sessionFileURL: URL? {
        folderURL?.appendingPathComponent(".multicam")
    }

    /// Sauberer Reset (Fremd-Feedback-Wunsch): .multicam loeschen und den Ordner
    /// frisch scannen — die App verhaelt sich dann wie beim allerersten Oeffnen
    /// (Wizard ab Schritt 1, Zuordnungen aus den Datei-Defaults).
    func resetSession() {
        if let url = sessionFileURL {
            try? FileManager.default.removeItem(at: url)
        }
        // Auch der Waveform-Platten-Cache dieses Ordners gehoert zum sauberen
        // Reset (User-Wunsch): die Peaks der aktuellen Spuren loeschen.
        for mic in micInfos {
            if let url = Self.waveformCacheURL(for: mic.path) {
                try? FileManager.default.removeItem(at: url)
            }
        }
        micWaveforms = [:]
        waveformProgress = [:]
        sessionRestored = false
        guard let folder = folderURL else { return }
        Task { await runScan(folder: folder, decideWizardStep: true) }
    }

    func saveSession() {
        guard let url = sessionFileURL else { return }
        let session: [String: Any] = [
            "episode_name": episodeName,
            "fps": fps,
            "cameras": cameraInfos.map { cam in
                ["id": cam.id, "filename": cam.filename, "display_name": cam.displayName,
                 "assigned_mics": cam.assignedMics, "included": cam.included] as [String: Any]
            },
            "mics": micInfos.map { mic in
                ["id": mic.id, "filename": mic.filename, "display_name": mic.displayName,
                 "included": mic.included] as [String: Any]
            },
            "params": params.toDict(),
            "audio_joins": audioJoinGroups,
            "audio_keep_separate": audioKeepSeparate,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: session, options: .prettyPrinted) else { return }
        try? data.write(to: url)
    }

    /// Liest NUR die Split-Korrekturen aus `.multicam` — sie werden VOR dem Scan
    /// gebraucht, der Rest der Session erst danach (Match über die Scan-Ergebnisse).
    private func loadAudioJoinSettings() {
        audioJoinGroups = []
        audioKeepSeparate = []
        guard let url = sessionFileURL,
              let data = try? Data(contentsOf: url),
              let session = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        audioJoinGroups = session["audio_joins"] as? [[String]] ?? []
        audioKeepSeparate = session["audio_keep_separate"] as? [String] ?? []
    }

    // MARK: - Gesplittete Aufnahmen manuell korrigieren

    /// Originaldateien einer Spur (eine, oder die Teile einer gesplitteten Aufnahme).
    private func partFilenames(_ mic: MicInfo) -> [String] {
        mic.parts.isEmpty ? [mic.filename] : mic.parts.map { ($0 as NSString).lastPathComponent }
    }

    /// „Gehört zu …": Spur `micId` ist Teil derselben Aufnahme wie `targetId`. Die
    /// Engine ordnet nach Zeitstempel (sonst: Ziel zuerst) und fügt beim Scan zusammen.
    func joinMic(_ micId: Int, into targetId: Int) {
        guard let mic = micInfos.first(where: { $0.id == micId }),
              let target = micInfos.first(where: { $0.id == targetId }) else { return }
        let names = partFilenames(target) + partFilenames(mic)
        audioJoinGroups.removeAll { !Set($0).isDisjoint(with: names) }
        audioKeepSeparate.removeAll { names.contains($0) }
        audioJoinGroups.append(names)
        Task { await rescanForAudioJoins() }
    }

    /// Verbundene Spur wieder in ihre Einzeldateien zerlegen — auch eine falsch
    /// ERKANNTE (dann werden die Teile von der Erkennung ausgenommen).
    func splitMic(_ micId: Int) {
        guard let mic = micInfos.first(where: { $0.id == micId }), mic.parts.count > 1 else { return }
        let names = partFilenames(mic)
        audioJoinGroups.removeAll { !Set($0).isDisjoint(with: names) }
        for n in names where !audioKeepSeparate.contains(n) { audioKeepSeparate.append(n) }
        Task { await rescanForAudioJoins() }
    }

    /// Speichern + neu scannen. Namen/Zuordnungen kommen danach über `.multicam`
    /// (Match per Dateiname) zurück; die verbundene Spur trägt den Namen ihres
    /// ersten Teils. Der Scan ist billig (Thumbnails/Previews gecacht).
    private func rescanForAudioJoins() async {
        guard let folder = folderURL else { return }
        stopAllPlayback()
        saveSession()
        state = .scanning
        await runScan(folder: folder, decideWizardStep: false)
    }

    func loadSession() -> Bool {
        guard let url = sessionFileURL,
              FileManager.default.fileExists(atPath: url.path),
              let data = try? Data(contentsOf: url),
              let session = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return false
        }

        // Episode name
        if let name = session["episode_name"] as? String {
            episodeName = name
        }
        if let savedFps = session["fps"] as? Double {
            fps = savedFps
        }

        // Gespeicherter Mic-Index -> Dateiname (Stand des Speicherns). assigned_mics
        // sind INDIZES; kommt eine Datei dazu oder faellt weg, verrutschen die Indizes
        // und die Zuordnung zeigte sonst auf die falsche Datei (bekannter Bug: neue
        // WAV in bekanntem Ordner -> Kamera an das falsche Mic). Ueber den Dateinamen
        // (im Ordner eindeutig) rechnen wir die gespeicherten Indizes auf die AKTUELLEN um.
        var savedMicFilename: [Int: String] = [:]
        if let savedMics = session["mics"] as? [[String: Any]] {
            for m in savedMics {
                if let mid = m["id"] as? Int, let mfile = m["filename"] as? String {
                    savedMicFilename[mid] = mfile
                }
            }
        }
        func currentMicIndex(forSavedIndex savedIdx: Int) -> Int? {
            guard let fname = savedMicFilename[savedIdx] else { return nil }
            return micInfos.first(where: { $0.filename == fname })?.id
        }

        // Cam labels + zuordnungen wiederherstellen. Match ueber den DATEINAMEN
        // (stabil, eindeutig) — NICHT ueber den gespeicherten Index.
        if let savedCams = session["cameras"] as? [[String: Any]] {
            for saved in savedCams {
                guard let filename = saved["filename"] as? String,
                      let idx = cameraInfos.firstIndex(where: { $0.filename == filename }) else { continue }
                if let displayName = saved["display_name"] as? String {
                    cameraInfos[idx].displayName = displayName
                }
                if let mics = saved["assigned_mics"] as? [Int] {
                    // Gespeicherte Mic-INDIZES ueber ihren Dateinamen auf die aktuellen
                    // Indizes umrechnen; inzwischen entfernte Mics fallen weg.
                    cameraInfos[idx].assignedMics = mics.compactMap { currentMicIndex(forSavedIndex: $0) }
                }
                // Aeltere Sessions kennen "included" nicht → Default beibehalten.
                if let included = saved["included"] as? Bool {
                    cameraInfos[idx].included = included
                }
            }
        }

        // Mic labels wiederherstellen
        if let savedMics = session["mics"] as? [[String: Any]] {
            for saved in savedMics {
                // Auch hier ueber den Dateinamen matchen, nicht ueber den Index.
                guard let filename = saved["filename"] as? String,
                      let idx = micInfos.firstIndex(where: { $0.filename == filename }) else { continue }
                if let displayName = saved["display_name"] as? String {
                    micInfos[idx].displayName = displayName
                }
                if let included = saved["included"] as? Bool {
                    micInfos[idx].included = included
                }
            }
        }

        // Parameter wiederherstellen
        if let savedParams = session["params"] as? [String: Any] {
            params.apply(savedParams)
        }

        return true
    }

    // MARK: - Pipeline Start

    /// Startet die Analyse — fragt vorher nach, falls CLIP aktiv ist, das Modell
    /// aber fehlt. Kein heimlicher Download: 581 MB laedt man nicht ungefragt.
    func start() {
        guard folderURL != nil else { return }
        guard params.clipFilterEnabled else { startAnalysis(); return }

        Task {
            let (installed, bytes) = await checkClipModel()
            await MainActor.run {
                if installed {
                    startAnalysis()
                } else {
                    clipTotal = bytes > 0 ? bytes : 581 * 1024 * 1024  // Offline → Schaetzung
                    showClipPrompt = true
                }
            }
        }
    }

    /// Fuehrt die Analyse ohne weitere Rueckfrage aus.
    func startAnalysis() {
        guard let folder = folderURL else { return }
        saveSession()  // Session vor dem Start sichern

        state = .running
        stepLabel = loc("Starting…")
        stepNum = 0
        totalSteps = 1
        stepPercent = 0
        stepETA = ""
        stepCounter = ""
        stepWeights = []
        perStepSeconds = [:]
        stepTimingKey = nil
        stepTimingStart = nil
        logMessages = []
        resultAAF = nil
        resultStats = nil

        Task {
            await runEngine(folder: folder)
        }
    }

    /// Wendet die Aufloesung aus dem SyncResolutionSheet an und startet neu:
    /// ausgeschlossene Quellen werden deaktiviert, manuelle Offsets gesetzt.
    func resolveSyncAndRetry(excludePaths: Set<String>, manualOffsets: [String: Int]) {
        for path in excludePaths {
            if let i = cameraInfos.firstIndex(where: { $0.path == path }) {
                cameraInfos[i].included = false
            } else if let i = micInfos.firstIndex(where: { $0.path == path }) {
                micInfos[i].included = false
            }
        }
        for (path, frames) in manualOffsets where !excludePaths.contains(path) {
            manualSyncOffsets[path] = frames
        }
        syncUnresolvedSources = []
        showSyncResolution = false
        startAnalysis()
    }

    /// Bricht die Aufloesung ab — zurueck zur Einrichtung (Zuordnung/Parameter).
    func cancelSyncResolution() {
        syncUnresolvedSources = []
        showSyncResolution = false
    }

    /// Misst die Wall-Clock-Dauer der Pipeline-Phasen für runtime.per_step_s.
    /// Aufgerufen bei jedem step_start(_sub) mit `key`; rollt nur bei Key-Wechsel
    /// um, sodass Nodding CAM1..N in denselben Eimer summiert.
    private func recordStepTiming(_ key: String) {
        guard key != stepTimingKey else { return }
        if let prev = stepTimingKey, let start = stepTimingStart {
            perStepSeconds[prev, default: 0] += Date().timeIntervalSince(start)
        }
        stepTimingKey = key
        stepTimingStart = Date()
    }

    /// Schließt die laufende Phase ab (bei result/session_end).
    private func closeStepTiming() {
        if let prev = stepTimingKey, let start = stepTimingStart {
            perStepSeconds[prev, default: 0] += Date().timeIntervalSince(start)
        }
        stepTimingKey = nil
        stepTimingStart = nil
    }

    /// Sendet nach erfolgreichem Lauf anonyme Telemetrie — NUR wenn zugestimmt.
    /// Ausschliesslich Zahlen/Enums (keine Namen/Pfade). Contract: brain/Telemetrie-API.md.
    func sendTelemetryIfEnabled(elapsedS: Double) {
        guard Telemetry.enabled else { return }
        let durs = (activeCams.map { $0.durationSeconds } + activeMics.map { $0.durationSeconds })
            .filter { $0 > 0 }.sorted()
        let total = durs.reduce(0, +)
        let median = durs.isEmpty ? 0 : durs[durs.count / 2]
        var runtime: [String: Any] = ["elapsed_s": Int(elapsedS)]
        // Pro-Schritt-Aufschlüsselung (nur nennenswerte Phasen ≥ 1 s, ganze
        // Sekunden) — zeigt, wo die Zeit hingeht (i.d.R. dominiert Nodding).
        let steps = perStepSeconds.filter { $0.value >= 1.0 }.mapValues { Int($0.rounded()) }
        if !steps.isEmpty { runtime["per_step_s"] = steps }
        let payload: [String: Any] = [
            "sources": [
                "n_cams": activeCams.count,
                "n_mics": activeMics.count,
                "n_speakers": persons.count,
                "total_source_s": Int(total),
                "duration_min_s": Int(durs.first ?? 0),
                "duration_median_s": Int(median),
                "duration_max_s": Int(durs.last ?? 0),
            ],
            "runtime": runtime,
            "preset": Stufen.telemetrieLabel(params),
            "settings": params.toDict(),
            "device": TelemetryDevice.payload,
        ]
        Telemetry.sendAnalysisCompleted(payload)
    }

    // MARK: - Reset

    func reset() {
        engineProcess?.terminate()
        engineProcess = nil
        state = .idle
        folderURL = nil
        cameraInfos = []
        micInfos = []
        stepPercent = 0
        stepNum = 0
        stepLabel = ""
        stepETA = ""
        stepCounter = ""
        logMessages = []
    }

    /// Nicht-destruktiv: zurueck ins Setup, Ordner + Zuordnungen bleiben geladen.
    func backToSetup() {
        state = .ready
    }

    /// Öffnet das Feedback-/Bug-Report-Formular. `fromError` befüllt Fehlermeldung
    /// + Log vor (aus dem Fehler-Screen). Log = die letzten Engine-stdout-Zeilen.
    func presentFeedback(fromError: Bool) {
        feedbackDraft = FeedbackDraft(
            fromError: fromError,
            errorMessage: fromError ? errorMessage : "",
            log: logMessages.suffix(3000).joined(separator: "\n"),
            episode: episodeName
        )
        showingFeedback = true
    }

    func cancel() {
        engineProcess?.terminate()
        engineProcess = nil
        stopPreviewPolling()
        stepPercent = 0
        stepNum = 0
        stepLabel = ""
        stepETA = ""
        stepCounter = ""
        logMessages = []
        state = .ready
    }

    // MARK: - Audio Preview (ganze Spur, seekbar via Waveform)
    //
    // Frueher spielte der Play-Knopf einen 5-s-Schnipsel „ab der lautesten
    // Stelle" — fuer Cutter mit unbekanntem Material zu unzuverlaessig
    // (Fremd-Feedback 22.07.). Jetzt: die GANZE Originalspur, Klick in die
    // Waveform springt an die Position, der Play-Knopf startet an der
    // dominanten Stelle (previewOffsetS).

    /// Spielt die ganze Spur ab `seconds` (nil = dominante Stelle des Scans).
    func playMic(_ mic: MicInfo, at seconds: Double? = nil) {
        // Anderer Mic oder noch kein Player — neu oeffnen.
        if playingMicId != mic.id || audioPlayer == nil {
            audioPlayer?.stop()
            audioPlayer = nil
            playingMicId = nil
            guard let player = try? AVAudioPlayer(
                contentsOf: URL(fileURLWithPath: mic.path)) else { return }
            let delegate = PlayerFinishDelegate { [weak self] in
                Task { @MainActor in self?.stopAllPlayback() }
            }
            player.delegate = delegate
            playerFinishDelegate = delegate
            audioPlayer = player
        }
        audioPlayer?.currentTime = min(seconds ?? mic.previewOffsetS,
                                       max(0, (audioPlayer?.duration ?? 0) - 0.5))
        audioPlayer?.play()
        playingMicId = mic.id
    }

    func toggleMicPreview(_ mic: MicInfo) {
        if playingMicId == mic.id { stopAllPlayback() } else { playMic(mic) }
    }

    func stopAllPlayback() {
        audioPlayer?.stop()
        audioPlayer = nil
        playerFinishDelegate = nil
        playingMicId = nil
    }

    /// Aktuelle Abspielposition der Spur — nil, wenn sie nicht laeuft.
    func playbackTime(for micId: Int) -> Double? {
        guard playingMicId == micId, let p = audioPlayer else { return nil }
        return p.currentTime
    }

    // MARK: - Waveform-Peaks (on-demand, gecacht)

    /// Peaks (0..1) je Mic fuer die Waveform-Anzeige. Einmal pro Datei
    /// berechnet (AVAudioFile, chunked + vDSP) und fuer die Session gecacht.
    @Published var micWaveforms: [Int: [Float]] = [:]
    /// Fortschritt der laufenden Berechnung in Prozent (nur waehrenddessen gesetzt).
    @Published var waveformProgress: [Int: Int] = [:]
    private var waveformInFlight: Set<Int> = []

    func requestWaveform(for mic: MicInfo, buckets: Int = 2048) {
        guard micWaveforms[mic.id] == nil, !waveformInFlight.contains(mic.id) else { return }
        waveformInFlight.insert(mic.id)
        let path = mic.path
        let id = mic.id
        Task.detached(priority: .utility) {
            // Erst der Platten-Cache (wie bei den Thumbnails): Schluessel ist
            // Pfad + Groesse + Aenderungsdatum — aendert sich die Datei, greift
            // automatisch ein neuer Schluessel. (Eine echte Checksumme muesste
            // die kompletten ~750 MB lesen und kostete damit so viel wie die
            // Berechnung selbst.)
            let cacheURL = Self.waveformCacheURL(for: path)
            if let cacheURL, let cached = Self.loadCachedPeaks(cacheURL) {
                await MainActor.run { [weak self] in
                    self?.waveformInFlight.remove(id)
                    self?.micWaveforms[id] = cached
                }
                return
            }
            var lastPct = -1
            let peaks = Self.computeWaveformPeaks(path: path, buckets: buckets) { frac in
                let pct = Int(frac * 100)
                if pct != lastPct {           // nur ganze Prozent publizieren
                    lastPct = pct
                    Task { @MainActor [weak self] in self?.waveformProgress[id] = pct }
                }
            }
            if let peaks, let cacheURL { Self.saveCachedPeaks(peaks, to: cacheURL) }
            await MainActor.run { [weak self] in
                self?.waveformInFlight.remove(id)
                self?.waveformProgress[id] = nil
                if let peaks { self?.micWaveforms[id] = peaks }
            }
        }
    }

    // MARK: Waveform-Platten-Cache

    nonisolated private static var waveformCacheDir: URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return base
            .appendingPathComponent(Bundle.main.bundleIdentifier ?? "MulticamCutter")
            .appendingPathComponent("waveforms")
    }

    /// Cache-Datei fuer eine Audiodatei — nil, wenn die Datei nicht lesbar ist.
    /// Praefix versioniert das Format: wf1 = Sample-Peaks (Bucket-Zahl egal, das Zeichnen aggregiert). wf2/wf3 waren RMS-Experimente — verworfen. Alte
    /// wf1-Dateien bleiben als winzige Waisen liegen und stoeren nicht.
    nonisolated static func waveformCacheURL(for path: String) -> URL? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let size = attrs[.size] as? Int64,
              let mtime = (attrs[.modificationDate] as? Date)?.timeIntervalSince1970
        else { return nil }
        let key = "\(path)|\(size)|\(mtime)"
        let digest = SHA256.hash(data: Data(key.utf8))
            .map { String(format: "%02x", $0) }.joined()
        let dir = waveformCacheDir
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("wf1_\(digest).peaks")
    }

    nonisolated static func loadCachedPeaks(_ url: URL) -> [Float]? {
        guard let data = try? Data(contentsOf: url),
              !data.isEmpty, data.count % 4 == 0 else { return nil }
        return data.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
    }

    nonisolated static func saveCachedPeaks(_ peaks: [Float], to url: URL) {
        peaks.withUnsafeBytes { try? Data($0).write(to: url, options: .atomic) }
    }

    /// Liest die Datei in Bloecken und nimmt je Bucket das Betragsmaximum
    /// (Sample-Peak, vDSP_maxmgv), normalisiert aufs Gesamtmaximum.
    ///
    /// Bewusst Sample-Peak: RMS+Mittelwert und dB-Mapping wurden am echten
    /// 97-min-Material probiert (23./24.07.) und sahen BEIDE flacher aus —
    /// die Log-Skala hebt leise Passagen an und komprimiert genau dort, wo
    /// Spreizung gewuenscht ist. Linear-Peak laesst Raumton klein und Sprache
    /// herausragen; Urteil des Users am Bild. AVAudioFile dekodiert jede
    /// Bit-Tiefe korrekt.
    nonisolated static func computeWaveformPeaks(path: String, buckets: Int,
                                                 onProgress: ((Double) -> Void)? = nil) -> [Float]? {
        guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path)),
              file.length > 0, buckets > 0 else { return nil }
        let totalFrames = Int(file.length)
        let framesPerBucket = max(1, totalFrames / buckets)
        let chunkFrames: AVAudioFrameCount = 1 << 20
        guard let buf = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                         frameCapacity: chunkFrames) else { return nil }
        var peaks = [Float](repeating: 0, count: buckets)
        var frameIndex = 0
        while frameIndex < totalFrames {
            do { try file.read(into: buf, frameCount: chunkFrames) } catch { break }
            let n = Int(buf.frameLength)
            if n == 0 { break }
            guard let ch = buf.floatChannelData?[0] else { break }
            // Bucketweise Betragsmaxima innerhalb dieses Blocks (vDSP).
            var local = 0
            while local < n {
                let bucket = min(buckets - 1, (frameIndex + local) / framesPerBucket)
                let bucketEndFrame = (bucket + 1) * framesPerBucket
                let len = min(n - local, max(1, bucketEndFrame - (frameIndex + local)))
                var m: Float = 0
                vDSP_maxmgv(ch + local, 1, &m, vDSP_Length(len))
                if m > peaks[bucket] { peaks[bucket] = m }
                local += len
            }
            frameIndex += n
            onProgress?(Double(frameIndex) / Double(totalFrames))
        }
        let maxV = peaks.max() ?? 0
        guard maxV > 0 else { return peaks }
        var scale = 1.0 / maxV
        vDSP_vsmul(peaks, 1, &scale, &peaks, 1, vDSP_Length(buckets))
        return peaks
    }

    // MARK: - CLIP-Modell (optionaler Download)

    /// Liegt das CLIP-Modell lokal? Zweitwert = Download-Groesse in Bytes (0 = unbekannt).
    /// Ist es vorhanden, kostet der Check ~0,2 s und geht NICHT ins Netz.
    func checkClipModel() async -> (Bool, Int64) {
        guard let (execPath, baseArgs) = engineCommand(extraArgs: ["--check-clip-model"]) else {
            return (false, 0)
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: execPath)
        process.arguments = baseArgs
        process.environment = engineEnvironment()
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return (false, 0) }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return (false, 0)
        }
        let installed = json["installed"] as? Bool ?? false
        let bytes = (json["download_bytes"] as? NSNumber)?.int64Value ?? 0
        return (installed, bytes)
    }

    /// Laedt das CLIP-Modell und startet danach die Analyse.
    func downloadClipModelAndStart() {
        runClipDownload { self.startAnalysis() }   // Modell da → jetzt loslegen
    }

    /// Laedt das CLIP-Modell OHNE danach zu analysieren (Settings-Tab „CLIP").
    func downloadClipModel() {
        runClipDownload { }
    }

    private func runClipDownload(then completion: @escaping () -> Void) {
        showClipPrompt = false
        isDownloadingClip = true
        clipDone = 0
        clipError = nil

        Task {
            guard let (execPath, baseArgs) = engineCommand(extraArgs: ["--download-clip-model"]) else {
                await MainActor.run { clipError = "Engine not found"; isDownloadingClip = false }
                return
            }
            let process = Process()
            process.executableURL = URL(fileURLWithPath: execPath)
            process.arguments = baseArgs
            process.environment = engineEnvironment()
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            clipProcess = process
            do { try process.run() } catch {
                await MainActor.run {
                    clipError = String(localized: "Could not start the download: \(error.localizedDescription)")
                    isDownloadingClip = false
                }
                return
            }

            var failure: String?
            let handle = pipe.fileHandleForReading
            var buffer = Data()
            while true {
                let chunk = handle.availableData
                if chunk.isEmpty { break }
                buffer.append(chunk)
                while let nl = buffer.firstIndex(of: 0x0A) {
                    let lineData = buffer[buffer.startIndex..<nl]
                    buffer.removeSubrange(buffer.startIndex...nl)
                    guard let line = String(data: lineData, encoding: .utf8),
                          let d = line.data(using: .utf8),
                          let msg = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
                          let type = msg["type"] as? String else { continue }
                    await MainActor.run {
                        switch type {
                        case "clip_download_start":
                            clipTotal = (msg["total_bytes"] as? NSNumber)?.int64Value ?? clipTotal
                        case "clip_progress":
                            clipDone = (msg["done"] as? NSNumber)?.int64Value ?? clipDone
                            if let t = (msg["total"] as? NSNumber)?.int64Value, t > 0 {
                                clipTotal = t
                            }
                        case "error":
                            failure = msg["message"] as? String
                        default: break
                        }
                    }
                }
            }
            process.waitUntilExit()

            await MainActor.run {
                isDownloadingClip = false
                clipProcess = nil
                if let failure {
                    clipError = failure
                } else if process.terminationStatus != 0 {
                    clipError = String(localized: "Download failed (code \(Int(process.terminationStatus))).")
                } else {
                    completion()
                }
            }
        }
    }

    func cancelClipDownload() {
        clipProcess?.terminate()
        clipProcess = nil
        isDownloadingClip = false
    }

    /// User will kein CLIP: Parameter dauerhaft aus und normal weiterlaufen.
    func declineClipAndStart() {
        params.clipFilterEnabled = false
        showClipPrompt = false
        saveSession()
        startAnalysis()
    }

    // MARK: - CLIP-Prompts (Cutaway-Filter, user-editierbar)

    struct ClipPrompts { var ignore: [String]; var neutral: [String]; var source: String }

    /// Zielort der user-editierten Prompts — identisch mit shared.paths.USER_CLIP_PROMPTS.
    var clipUserPromptsURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MulticamCutter/clip_prompts.json")
    }

    /// Aktive Prompts abfragen (User-Datei bevorzugt, sonst gebündelte Defaults).
    /// Blockiert kurz (~0,2 s Engine-Aufruf) — wie checkClipModel.
    func getClipPrompts() async -> ClipPrompts? {
        guard let (execPath, baseArgs) = engineCommand(extraArgs: ["--get-clip-prompts"]) else { return nil }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: execPath)
        process.arguments = baseArgs
        process.environment = engineEnvironment()
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard let text = String(data: data, encoding: .utf8) else { return nil }
        // Letzte JSON-Zeile nehmen (falls die Engine Vorlauf druckt).
        let lastLine = text.split(separator: "\n").last.map(String.init) ?? text
        guard let jd = lastLine.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jd) as? [String: Any] else { return nil }
        return ClipPrompts(
            ignore: json["ignore"] as? [String] ?? [],
            neutral: json["neutral"] as? [String] ?? [],
            source: json["source"] as? String ?? "default"
        )
    }

    /// User-Prompts speichern (schreibt clipUserPromptsURL). true = ok.
    @discardableResult
    func saveClipPrompts(ignore: [String], neutral: [String]) -> Bool {
        let url = clipUserPromptsURL
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                    withIntermediateDirectories: true)
            let payload: [String: Any] = ["ignore": ignore, "neutral": neutral]
            let data = try JSONSerialization.data(withJSONObject: payload,
                                                  options: [.prettyPrinted, .sortedKeys])
            try data.write(to: url)
            return true
        } catch { return false }
    }

    /// Zurück auf die gebündelten Defaults (löscht die User-Datei).
    func resetClipPrompts() {
        try? FileManager.default.removeItem(at: clipUserPromptsURL)
    }

    // MARK: - Nodding-Muster (roher Detektor-Config-Editor, Expert)

    struct NoddingPatterns { var content: String; var source: String }

    /// Zielort der user-editierten Patterns — identisch mit shared.paths.USER_NODDING_PATTERNS.
    var noddingUserPatternsURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MulticamCutter/nodding_patterns.json")
    }

    /// Aktive nodding_patterns.json abfragen (User-Datei bevorzugt, sonst Defaults).
    func getNoddingPatterns() async -> NoddingPatterns? {
        guard let (execPath, baseArgs) = engineCommand(extraArgs: ["--get-nodding-patterns"]) else { return nil }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: execPath)
        process.arguments = baseArgs
        process.environment = engineEnvironment()
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard let text = String(data: data, encoding: .utf8) else { return nil }
        let lastLine = text.split(separator: "\n").last.map(String.init) ?? text
        guard let jd = lastLine.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jd) as? [String: Any] else { return nil }
        return NoddingPatterns(content: json["content"] as? String ?? "",
                               source: json["source"] as? String ?? "default")
    }

    /// Rohe JSON speichern — nur wenn valide UND mit global+patterns. nil = ok, sonst Fehlertext.
    func saveNoddingPatterns(_ raw: String) -> String? {
        guard let data = raw.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return "Not valid JSON."
        }
        guard obj["global"] != nil, obj["patterns"] is [Any] else {
            return "JSON needs the fields 'global' and 'patterns'."
        }
        let url = noddingUserPatternsURL
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                    withIntermediateDirectories: true)
            try data.write(to: url)
            return nil
        } catch { return "Write failed: \(error.localizedDescription)" }
    }

    /// Zurück auf die gebündelten Defaults (löscht die User-Datei).
    func resetNoddingPatterns() {
        try? FileManager.default.removeItem(at: noddingUserPatternsURL)
    }

    // MARK: - FPS-Mismatch

    /// Aktive Kameras, deren Source-FPS nicht zur Timeline-FPS passt.
    /// Nicht lesbare FPS (0) zaehlt ebenfalls als Mismatch — dann stimmt die
    /// Frame-Rechnung erst recht nicht.
    ///
    /// Warum das blockiert: Weicht die Source-FPS ab, rechnet die EDL/AAF-Pipeline
    /// mit falschen Source-Frames → Audio/Video-Drift + Standbild am Timeline-Ende.
    /// Eine Regel, zwei Verbraucher: die Sammel-Liste UND das Warn-Badge auf der
    /// Kamera-Karte (damit man nicht suchen muss, WELCHE Datei betroffen ist).
    func isFpsMismatch(_ cam: CameraInfo) -> Bool {
        cam.fps <= 0 || abs(cam.fps - fps) > 0.01
    }

    var fpsMismatches: [CameraInfo] {
        activeCams.filter { isFpsMismatch($0) }
    }

    /// Lokalisiert ein von der Engine geliefertes Step-Label (Engine emittiert die
    /// englischen Quell-Strings als Schlüssel). Statische Labels stehen im Katalog;
    /// dynamische ("Head-nod analysis <Cam>", "Converting <Datei>", "Audio preview:
    /// <Mic>") werden über ihren bekannten englischen Präfix übersetzt — der
    /// angehängte Datei-/Kameraname (= Daten) bleibt unverändert.
    func locStepLabel(_ s: String) -> String {
        let hit = loc(s)
        if hit != s { return hit }
        for prefix in ["Reaction analysis", "Head-nod analysis", "Audio preview:", "Converting"] {
            if s.hasPrefix(prefix + " ") {
                return loc(prefix) + String(s.dropFirst(prefix.count))
            }
        }
        return s
    }

    /// Schrittname der Reaktionsanalyse (Nicken + Mund) je Kamera:
    /// „Reaktionsanalyse Seb · Nah (C9667.MP4)". Person = Anzeigename des EINEN
    /// zugeordneten Mics (bei mehreren keine Person), Größe aus der Kamerarolle.
    /// Der Dateiname bleibt in Klammern, damit man die Quelle sicher erkennt.
    func reactionStepLabel(file: String) -> String {
        let base = loc("Reaction analysis")
        guard let cam = cameraInfos.first(where: { $0.filename == file }) else {
            return "\(base) (\(file))"
        }
        var parts: [String] = []
        if cam.assignedMics.count == 1,
           let mic = micInfos.first(where: { $0.id == cam.assignedMics[0] }),
           !mic.displayName.isEmpty {
            parts.append(mic.displayName)
        }
        switch camRoles()[cam.id] {
        case .wide: parts.append(loc("Wide"))
        case .close: parts.append(loc("Close-up"))
        default: break
        }
        let name = parts.joined(separator: " · ")
        return name.isEmpty ? "\(base) (\(file))" : "\(base) \(name) (\(file))"
    }

    /// Leitet die Timeline-FPS aus den gescannten Kameras ab.
    ///
    /// Haben ALLE aktiven Kameras eine lesbare und untereinander gleiche Bildrate
    /// (±0,01), dann IST das die Projekt-FPS — auch wenn sie von den vorbelegten
    /// 25 abweicht (z.B. alle Quellen 29,97). Ohne diese Ableitung stünde die
    /// Timeline fix auf 25 und der Mismatch-Check würde jede nicht-25-Kamera zur
    /// unnötigen Konvertierung drängen, obwohl es GAR KEINE Abweichung zwischen den
    /// Quellen gibt. Sind die Kameras dagegen uneinheitlich (oder eine unlesbar),
    /// bleibt die FPS unangetastet — dann greift der Mismatch-Check zu Recht.
    ///
    /// Läuft nach dem Session-Restore: die real gescannten Dateien sind die Wahrheit,
    /// nicht eine evtl. veraltete gespeicherte FPS.
    func deriveProjectFpsFromCameras() {
        let rates = activeCams.map { $0.fps }
        guard !rates.isEmpty,
              rates.allSatisfy({ $0 > 0 }),          // keine unlesbare Bildrate dabei
              let common = rates.first,
              rates.allSatisfy({ abs($0 - common) <= 0.01 })
        else { return }
        guard abs(fps - common) > 0.01 else { return }   // schon passend → nichts tun
        fps = common
        logMessages.append(String(localized: "Timeline frame rate taken from cameras: \(String(format: "%g", common)) fps"))
    }

    /// Konvertiert die betroffenen Dateien auf die Timeline-FPS und scannt neu.
    /// Laeuft ueber die Engine (`--convert-fps`), damit ffmpeg-Rezept + TC-Erhalt
    /// an einer Stelle liegen (siehe convert_fps_files in multicam_engine.py).
    func convertMismatchedFps() {
        let targets = fpsMismatches.map { $0.path }
        guard !targets.isEmpty, let folder = folderURL else { return }

        isConverting = true
        convertError = nil
        convertLog = []
        convertLabel = ""
        convertFileIndex = 0
        convertFileCount = targets.count
        convertDone = 0
        convertTotal = 0
        convertCanceled = false
        convertFileStartedAt = nil
        // Dauer je Ziel-Datei in derselben Reihenfolge wie `targets` → fuer die ETA.
        convertTargetDurations = fpsMismatches.map { $0.durationSeconds }

        Task {
            // Codec-Feineinstellung aus den Settings (Defaults an echtem Material
            // kalibriert — s. SettingsView „Konvertierung"). object(forKey:) statt
            // integer(forKey:), damit ein fehlender Schluessel den Default 72 nimmt
            // (integer(forKey:) liefert sonst 0).
            let d = UserDefaults.standard
            let hevcQ = (d.object(forKey: "convertHevcQuality") as? Int) ?? 72
            let proresProfile = d.string(forKey: "convertProResProfile") ?? "hq"
            let args = ["--convert-fps", "--fps", String(fps),
                        "--hevc-quality", String(hevcQ),
                        "--prores-profile", proresProfile,
                        "--files"] + targets
            guard let (execPath, baseArgs) = engineCommand(extraArgs: args) else {
                await MainActor.run {
                    convertError = "Engine not found"
                    isConverting = false
                }
                return
            }

            let process = Process()
            process.executableURL = URL(fileURLWithPath: execPath)
            process.arguments = baseArgs
            process.environment = engineEnvironment()
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            convertProcess = process

            do {
                try process.run()
            } catch {
                await MainActor.run {
                    convertError = String(localized: "Could not start the conversion: \(error.localizedDescription)")
                    isConverting = false
                    convertProcess = nil
                }
                return
            }

            var failure: String?
            let handle = pipe.fileHandleForReading
            var buffer = Data()
            while true {
                let chunk = handle.availableData
                if chunk.isEmpty { break }
                buffer.append(chunk)
                while let nl = buffer.firstIndex(of: 0x0A) {
                    let lineData = buffer[buffer.startIndex..<nl]
                    buffer.removeSubrange(buffer.startIndex...nl)
                    guard let line = String(data: lineData, encoding: .utf8), !line.isEmpty else { continue }
                    guard let data = line.data(using: .utf8),
                          let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                          let type = msg["type"] as? String else { continue }
                    let text = msg["message"] as? String ?? ""
                    await MainActor.run {
                        switch type {
                        case "step_start":
                            convertFileIndex = msg["step_num"] as? Int ?? convertFileIndex
                            convertFileCount = msg["total_steps"] as? Int ?? convertFileCount
                            convertDone = 0
                            convertTotal = 0
                            convertFileStartedAt = Date()   // ETA-Basis pro Datei
                        case "convert_progress":
                            convertFileIndex = msg["file_index"] as? Int ?? convertFileIndex
                            convertFileCount = msg["file_count"] as? Int ?? convertFileCount
                            convertLabel = (msg["label"] as? String).map(locStepLabel) ?? convertLabel
                            convertDone = (msg["done"] as? NSNumber)?.doubleValue ?? convertDone
                            convertTotal = (msg["total"] as? NSNumber)?.doubleValue ?? convertTotal
                        case "log":
                            convertLog.append(text)
                        case "error":
                            failure = text
                        default:
                            break
                        }
                    }
                }
            }
            process.waitUntilExit()

            let code = process.terminationStatus
            let canceled = convertCanceled
            let success = (failure == nil && code == 0 && !canceled)
            await MainActor.run {
                isConverting = false
                convertProcess = nil
                if canceled {
                    // Vom User abgebrochen — die Engine hat ffmpeg beendet und die
                    // Teildatei geloescht. Kein Fehler, der Zustand bleibt wie vorher.
                } else if let failure {
                    convertError = failure + convertDiagnosticsTail()
                } else if code != 0 {
                    convertError = String(localized: "Conversion failed (code \(code)).")
                        + convertDiagnosticsTail()
                }
            }
            // Erfolg → Ordner neu einlesen (die neuen _NNfps-Dateien tauchen auf)
            // und die konvertierten Originale abwaehlen.
            if success {
                await rescanAndDeselectOriginals(folder: folder, originals: targets)
            }
        }
    }

    /// Nach erfolgreicher Konvertierung: Ordner neu einlesen (die neuen
    /// `_NNfps`-Dateien erscheinen) und die konvertierten Originale im Panel
    /// abwaehlen. Sie sind durch die framerate-korrekte Fassung ersetzt und wuerden
    /// sonst die Analyse doppeln und weiter als FPS-Mismatch blockieren.
    private func rescanAndDeselectOriginals(folder: URL, originals: [String]) async {
        // gleiche Vorbereitung wie setFolder — aber wir warten den Scan ab, um
        // danach gezielt die Originale abzuwaehlen.
        folderURL = folder
        episodeName = folder.lastPathComponent
        cameraInfos = []
        micInfos = []
        state = .scanning
        // Nach der Konvertierung NICHT zur Übersicht springen — der User war auf dem
        // Kameras-Schritt und muss die neu konvertierte Cam evtl. neu zuordnen.
        await runScan(folder: folder, decideWizardStep: false)

        guard state == .ready else { return }   // Scan-Fehler → nichts anfassen
        let originalPaths = Set(originals)
        for cam in cameraInfos where originalPaths.contains(cam.path) {
            setCamIncluded(cam.id, false)        // loest Mic-Zuordnung + speichert
        }
    }

    /// Letzte ffmpeg-Zeilen fuer die Fehlermeldung. Das Modal zeigt das Live-Log
    /// nicht mehr (nur noch den Balken) — bei einem Fehler will man die Ursache aber
    /// trotzdem sehen, deshalb haengen wir den Schwanz an die Fehlermeldung.
    private func convertDiagnosticsTail() -> String {
        let tail = convertLog.suffix(12)
        return tail.isEmpty ? "" : "\n\n" + tail.joined(separator: "\n")
    }

    /// Bricht die laufende Konvertierung ab. Der SIGTERM beendet in der Engine das
    /// aktuelle ffmpeg und loescht die halbfertige Ausgabedatei (siehe _on_term).
    func cancelConversion() {
        guard isConverting else { return }
        convertCanceled = true
        convertProcess?.terminate()
    }

    /// Geschaetzte Restzeit der Konvertierung in Sekunden — nil, solange keine
    /// belastbare Geschwindigkeit vorliegt. Basis: Wall-Clock-Durchschnitt
    /// (konvertierte Video-Sekunden pro real vergangener Sekunde), inkl. der noch
    /// offenen Dateien. Ruhiger als ffmpegs schwankender Momentanwert.
    var convertEtaSeconds: Double? {
        guard let started = convertFileStartedAt, convertDone > 0.5 else { return nil }
        let elapsed = Date().timeIntervalSince(started)
        guard elapsed > 0.5 else { return nil }
        let speed = convertDone / elapsed        // Video-Sekunden pro Wall-Sekunde
        guard speed > 0.0001 else { return nil }
        var remaining = max(0, convertTotal - convertDone)
        // convertFileIndex ist 1-basiert → [convertFileIndex...] sind die Dateien
        // NACH der aktuellen (0-basiert), deren volle Dauer noch aussteht.
        if convertFileIndex < convertTargetDurations.count {
            remaining += convertTargetDurations[convertFileIndex...].reduce(0, +)
        }
        return remaining / speed
    }

    // MARK: - Facemesh Preview Polling

    private func startPreviewPolling(path: String) {
        previewPath = path
        previewStartedAt = Date()
        facemeshImage = nil          // alte Vorschau sofort weg
        previewTimer?.invalidate()
        previewTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in
                guard let path = self.previewPath, let since = self.previewStartedAt else { return }
                // NUR Stills zeigen, die MediaPipe in DIESEM Lauf geschrieben hat.
                // Sonst liegt die Datei des vorigen Laufs/Projekts noch da und wird
                // sofort beim Step-Start angezeigt (zeigt dann ein fremdes Bild).
                guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
                      let mtime = attrs[.modificationDate] as? Date,
                      mtime >= since,
                      let image = NSImage(contentsOfFile: path) else { return }
                self.facemeshImage = image
            }
        }
    }

    private func stopPreviewPolling() {
        previewTimer?.invalidate()
        previewTimer = nil
        previewPath = nil
        previewStartedAt = nil
        facemeshImage = nil
    }

    // MARK: - Scan (Engine --scan)

    private func runScan(folder: URL, decideWizardStep: Bool = true) async {
        loadAudioJoinSettings()
        var scanArgs = ["--folder", folder.path, "--scan"]
        if !audioJoinGroups.isEmpty,
           let d = try? JSONSerialization.data(withJSONObject: audioJoinGroups),
           let j = String(data: d, encoding: .utf8) {
            scanArgs += ["--join-groups", j]
        }
        if !audioKeepSeparate.isEmpty,
           let d = try? JSONSerialization.data(withJSONObject: audioKeepSeparate),
           let j = String(data: d, encoding: .utf8) {
            scanArgs += ["--keep-separate", j]
        }
        guard let (execPath, baseArgs) = engineCommand(extraArgs: scanArgs) else {
            errorMessage = "Engine or Python not found"
            state = .error
            return
        }

        scanLabel = loc("Scanning folder…")
        scanPercent = 0

        let process = Process()
        process.executableURL = URL(fileURLWithPath: execPath)
        process.arguments = baseArgs
        process.environment = engineEnvironment()

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice

        do {
            try process.run()
        } catch {
            errorMessage = String(localized: "Scan failed: \(error.localizedDescription)")
            state = .error
            return
        }

        // Zeilenweise lesen fuer Live-Progress
        var allLines: [String] = []
        let handle = pipe.fileHandleForReading
        do {
            for try await line in handle.bytes.lines {
                allLines.append(line)
                // scan_progress parsen
                if let lineData = line.data(using: .utf8),
                   let json = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any] {
                    let type = json["type"] as? String ?? ""
                    if type == "scan_progress" {
                        if let pct = json["percent"] as? Double { scanPercent = pct }
                        if let label = json["label"] as? String { scanLabel = locStepLabel(label) }
                    } else if type == "error" {
                        if let msg = json["message"] as? String {
                            errorMessage = msg
                            state = .error
                            process.waitUntilExit()
                            return
                        }
                    }
                }
            }
        } catch {
            // Stream closed
        }

        process.waitUntilExit()

        let output = allLines.joined(separator: "\n")
        guard !output.isEmpty else {
            errorMessage = "Scan: no output from the engine process"
            state = .error
            return
        }

        // scan_complete Zeile finden
        guard let scanLine = allLines.last(where: { $0.contains("scan_complete") }),
              let lineData = scanLine.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
              let camerasArr = json["cameras"] as? [[String: Any]],
              let micsArr = json["mics"] as? [[String: Any]] else {
            errorMessage = String(localized: "Scan: could not read the result.\nEngine output: \(output.prefix(200))")
            state = .error
            return
        }

        // Kamera-Infos aufbauen
        var newCams: [CameraInfo] = []
        for cam in camerasArr {
            let idx = cam["index"] as? Int ?? 0
            let filename = cam["filename"] as? String ?? ""
            newCams.append(CameraInfo(
                id: idx,
                filename: filename,
                path: cam["path"] as? String ?? "",
                displayName: filename,
                thumbnailPath: cam["thumbnail"] as? String,
                durationSeconds: cam["duration_s"] as? Double ?? 0,
                assignedMics: [],
                fps: cam["fps"] as? Double ?? 0
            ))
        }

        // Mic-Infos aufbauen
        var newMics: [MicInfo] = []
        for mic in micsArr {
            let idx = mic["index"] as? Int ?? 0
            let filename = mic["filename"] as? String ?? ""
            newMics.append(MicInfo(
                id: idx,
                filename: filename,
                path: mic["path"] as? String ?? "",
                displayName: filename,
                previewPath: mic["preview"] as? String,
                previewOffsetS: (mic["preview_offset_s"] as? NSNumber)?.doubleValue ?? 0,
                separationDb: (mic["separation_db"] as? NSNumber)?.doubleValue,
                durationSeconds: mic["duration_s"] as? Double ?? 0,
                parts: mic["parts"] as? [String] ?? [],
                partsManual: mic["parts_manual"] as? Bool ?? false
            ))
        }

        if let warnings = json["join_warnings"] as? [String], !warnings.isEmpty {
            joinWarning = warnings.joined(separator: "\n")
        }

        // Keine Auto-Zuordnung — Mics starten als "nicht zugeordnet".
        // User ordnet manuell per Drag & Drop zu.

        cameraInfos = newCams
        micInfos = newMics
        // In-Memory-Waveforms sind nach Mic-INDEX gekeyt — beim Ordnerwechsel
        // wuerden sonst die Peaks des vorigen Ordners angezeigt. Leeren; der
        // Platten-Cache macht das Neuladen bekannter Dateien billig.
        micWaveforms = [:]
        waveformProgress = [:]

        if cameraInfos.count < 2 {
            errorMessage = String(localized: "Expected at least 2 camera clips, found \(cameraInfos.count).")
            state = .error
            return
        }
        if micInfos.isEmpty {
            errorMessage = "No microphone files found."
            state = .error
            return
        }

        // Gespeicherte Session laden (Labels, Zuordnungen, Parameter)
        var restored = false
        if loadSession() {
            logMessages.append("Session wiederhergestellt (.multicam)")
            restored = true
        }

        // Timeline-FPS aus den Kameras ableiten (nach dem Restore, damit die real
        // gescannten Dateien gewinnen): einheitliche abweichende Bildrate = Projekt-FPS.
        deriveProjectFpsFromCameras()

        // Phase 5: Existiert schon eine Zuordnung (Person auf Cam), direkt zur
        // Übersicht springen statt den Wizard von Schritt 1 zu starten.
        if decideWizardStep {
            let hasAssignments = cameraInfos.contains { !$0.assignedMics.isEmpty }
            wizardStep = hasAssignments ? .overview : .persons
            // Hinweis nur, wenn wir WEGEN der gespeicherten Session vorspringen —
            // sonst wundert sich der Nutzer, warum er im dritten Schritt landet.
            sessionRestored = restored && hasAssignments
        }

        state = .ready
    }

    // MARK: - Engine Subprocess (Pipeline)

    private func runEngine(folder: URL) async {
        let aafFilename = episodeName.isEmpty ? "final" : episodeName
        let outputPath = folder.appendingPathComponent("\(aafFilename).aaf").path

        var extraArgs = [
            "--folder", folder.path,
            "--fps", String(fps),
            "--params", params.toJSON(),
            "--output", outputPath,
        ]
        // Nur die aktivierten Quellen explizit uebergeben — die Engine scannt dann
        // NICHT selbst. Alle folgenden Args sind positional und beziehen sich auf
        // genau diese Listen.
        // orderedAnalysisCams: Close-Cams zuerst, Totalen ans Ende (siehe dort) —
        // damit die binäre Diarisierung (erste zwei Cams) nie die Totale erwischt.
        let ordered = orderedAnalysisCams
        extraArgs += ["--cams"] + ordered.map { $0.path }
        extraArgs += ["--mics"] + activeMics.map { $0.path }

        let micArgs = camMicsArgs
        if !micArgs.isEmpty && !micArgs.allSatisfy({ $0.isEmpty }) {
            extraArgs += ["--cam-mics"] + micArgs
        }
        // Bildgröße wird ABGELEITET (Personen-Graph, „Close gewinnt") — kein
        // manuelles Totale-Flag mehr. "wide" = Totale (Simultan-Reaktionen).
        let roles = camRoles()
        let camTypes = ordered.map { roles[$0.id] == .wide ? "wide" : "close" }
        extraArgs += ["--cam-types"] + camTypes
        let displayNames = ordered.map { $0.displayName }
        if let namesData = try? JSONSerialization.data(withJSONObject: displayNames),
           let namesStr = String(data: namesData, encoding: .utf8) {
            extraArgs += ["--display-names", namesStr]
        }
        // Zugeordnete Person je Kamera — ersetzt im AAF das generische "Sprecher".
        // Der Name lebt nur hier (Mic-Anzeigename); die Engine kennt von den Mics
        // sonst nur Pfade wie MIC1.WAV.
        // NUR bei genau einer zugeordneten Person: bei mehreren (Totale) ist aus
        // der Kamera nicht ableitbar, WER spricht — eine Namensliste waere dort
        // die falsche Information. Dann bleibt es bei "Sprecher". In der Praxis
        // bekommen Totalen ohnehin nie reason == 'speaker'; das ist ein Netz.
        let personNames = ordered.map { cam -> String in
            guard cam.assignedMics.count == 1,
                  let mic = activeMics.first(where: { $0.id == cam.assignedMics[0] })
            else { return "" }
            return mic.displayName
        }
        if let pData = try? JSONSerialization.data(withJSONObject: personNames),
           let pStr = String(data: pData, encoding: .utf8) {
            extraArgs += ["--cam-person-names", pStr]
        }

        // AAF-Clipname-Muster — nur wenn „Schnittgruende in Clipnamen" aktiv ist
        // (Default AN). object(forKey:) statt bool(forKey:), damit ein fehlender
        // Schluessel den Default true nimmt (bool(forKey:) liefert sonst false).
        // Aus → ein MasterMob pro Kamera (Dateiname); an → grund-benannte MasterMobs
        // (Resolve am Clip, Premiere je Grund ein zusaetzlicher verknuepfter Clip).
        let reasonsOn = (UserDefaults.standard.object(forKey: "clipNameReasons") as? Bool) ?? true
        if reasonsOn {
            let pattern = (UserDefaults.standard.string(forKey: "clipNamePattern")
                           ?? "%L - %S").trimmingCharacters(in: .whitespaces)
            if !pattern.isEmpty {
                extraArgs += ["--clip-name-pattern", pattern]
            }
        }

        // Manuell gesetzte Sync-Offsets (Baustein 3): diese Quelle wird nicht
        // korreliert, der Wert direkt uebernommen. Nur Pfade der aktivierten
        // Quellen wirken — stale Eintraege ignoriert die Engine.
        let activePaths = Set(orderedAnalysisCams.map { $0.path } + activeMics.map { $0.path })
        for (path, frames) in manualSyncOffsets where activePaths.contains(path) {
            extraArgs += ["--manual-offset", "\(path)=\(frames)"]
        }

        guard let (execPath, baseArgs) = engineCommand(extraArgs: extraArgs) else {
            errorMessage = "Engine or Python not found"
            state = .error
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: execPath)
        process.arguments = baseArgs
        process.environment = engineEnvironment()

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        engineProcess = process

        do {
            try process.run()
        } catch {
            errorMessage = String(localized: "Could not start the engine: \(error.localizedDescription)")
            state = .error
            return
        }

        let handle = pipe.fileHandleForReading
        do {
            for try await line in handle.bytes.lines {
                await processLine(line)
            }
        } catch {
            // Stream closed
        }

        process.waitUntilExit()
        engineProcess = nil

        if process.terminationStatus != 0 && state == .running {
            if errorMessage.isEmpty {
                errorMessage = String(localized: "Engine exited with code \(Int(process.terminationStatus))")
            }
            state = .error
        }
    }

    private func processLine(_ line: String) async {
        // Verschachteltes JSON in Log-Zeilen erkennen (z.B. "text... {"type":"error",...}")
        var jsonLine = line
        if let jsonStart = line.range(of: "{\"type\"") {
            jsonLine = String(line[jsonStart.lowerBound...])
        }

        guard let data = jsonLine.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else {
            logMessages.append(line)
            return
        }

        switch type {
        case "step_start":
            if let key = json["key"] as? String { recordStepTiming(key) }
            if let label = json["label"] as? String {
                stepLabel = locStepLabel(label)
                stepPercent = 0
                stepETA = ""
                stepCounter = ""
            }
            if let num = json["step_num"] as? Int { stepNum = num }
            if let total = json["total_steps"] as? Int { totalSteps = total }
            stopPreviewPolling()
            logMessages.append(String(localized: "Step \(stepNum)/\(totalSteps): \(stepLabel)"))

        case "step_start_sub":
            if let key = json["key"] as? String { recordStepTiming(key) }
            // Subprocess-Step innerhalb von run_analysis
            if let label = json["label"] as? String {
                if let file = json["cam_file"] as? String, !file.isEmpty {
                    stepLabel = reactionStepLabel(file: file)
                } else {
                    stepLabel = locStepLabel(label)
                }
                stepPercent = 0
                stepETA = ""
                stepCounter = ""
                stepNum += 1
            }
            // Facemesh-Preview starten/stoppen
            if let path = json["preview_path"] as? String {
                startPreviewPolling(path: path)
            } else {
                stopPreviewPolling()
            }
            logMessages.append(String(localized: "Step \(stepNum)/\(totalSteps): \(stepLabel)"))

        case "step_detail":
            // Verfeinert den Text des LAUFENDEN Schritts (welcher Pass rechnet
            // gerade). Bewusst OHNE stepNum-Erhoehung -- anders als
            // step_start_sub, das einen echten neuen Schritt markiert.
            if let label = json["label"] as? String {
                stepLabel = locStepLabel(label)
                stepPercent = 0
                stepETA = ""
                stepCounter = ""
            }

        case "step_progress":
            if let percent = json["percent"] as? Double {
                stepPercent = percent
            }
            if let eta = json["eta"] as? String, !eta.isEmpty {
                stepETA = eta
            }
            // "341/384" -> "341 von 384". Der Zaehler stand frueher an der
            // Stelle der ETA und wurde als solche angezeigt; jetzt ist er ein
            // eigenes Feld und ergaenzt die Restzeit, statt sie zu ersetzen.
            if let counter = json["counter"] as? String, !counter.isEmpty {
                stepCounter = counter.replacingOccurrences(of: "/", with: " von ")
            }

        case "step_weights":
            stepWeights = (json["weights"] as? [Any])?
                .compactMap { ($0 as? NSNumber)?.doubleValue } ?? []

        case "warning":
            if let message = json["message"] as? String {
                logMessages.append("WARNING: \(message)")
            }

        case "error":
            if let message = json["message"] as? String {
                errorMessage = message
                logMessages.append("ERROR: \(message)")
            }

        case "result":
            if let aaf = json["aaf"] as? String {
                resultAAF = aaf
            }
            var stats: [String: String] = [:]
            if let total = json["events_total"] as? Int {
                stats["Events"] = "\(total)"
            }
            if let elapsed = json["elapsed_s"] as? Double {
                let min = Int(elapsed) / 60
                let sec = Int(elapsed) % 60
                stats["Duration"] = "\(min)m \(sec)s"
            }
            if let byType = json["events_by_type"] as? [String: Int] {
                for (key, count) in byType.sorted(by: { $0.key < $1.key }) {
                    stats[key] = "\(count)x"
                }
            }
            resultStats = stats
            state = .done
            closeStepTiming()
            sendTelemetryIfEnabled(elapsedS: (json["elapsed_s"] as? Double) ?? 0)

        case "log":
            if let message = json["message"] as? String {
                logMessages.append(message)
            }

        case "session_start":
            logMessages.append("Session gestartet")

        case "sync_unresolved":
            syncReferenceFilename = json["reference"] as? String ?? ""
            if let sources = json["sources"] as? [[String: Any]] {
                syncUnresolvedSources = sources.compactMap { s in
                    guard let path = s["path"] as? String, !path.isEmpty,
                          let label = s["label"] as? String else { return nil }
                    return UnsyncableSource(
                        label: label,
                        path: path,
                        filename: s["filename"] as? String ?? path,
                        reason: s["reason"] as? String ?? "",
                        bestConfidence: (s["best_confidence"] as? NSNumber)?.doubleValue ?? 0,
                        candidateOffsetFrames: (s["candidate_offset_frames"] as? NSNumber)?.intValue ?? 0
                    )
                }
                // Zurueck in die Einrichtung, Sheet legt sich darueber. state != .running,
                // damit das folgende session_end(success=false) NICHT als Fehler zaehlt.
                state = .ready
                showSyncResolution = true
            }

        case "session_end":
            if json["success"] as? Bool == false && state == .running {
                state = .error
            }

        default:
            if let message = json["message"] as? String {
                logMessages.append(message)
            }
        }
    }

    /// Wohin die Engine ihre Lauf-Logs schreibt (muss mit `log_dir` in
    /// multicam_engine.py uebereinstimmen). ~/Library/Logs ist der macOS-Standardort —
    /// dort schaut auch Console.app rein.
    static var logDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/MulticamCutter")
    }

    // MARK: - Temporaere Gesamt-WAVs (gesplittete Aufnahmen)

    /// Hier legt die Engine die zusammengefuegten WAVs gesplitteter Aufnahmen ab
    /// (`MCC_JOIN_DIR`). Nur fuer die Analyse — sie landen nie im Schnittprojekt
    /// (der AAF-Export verweist auf die Originalteile).
    nonisolated static var splitJoinDirectory: URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("MultiCamCutter-joined", isDirectory: true)
    }

    /// Loescht die temporaeren Gesamt-WAVs. Beim Beenden der App und beim Start
    /// (falls die App zuletzt abgestuerzt ist). Beim naechsten Scan entstehen sie neu.
    nonisolated static func removeSplitJoinDirectory() {
        try? FileManager.default.removeItem(at: splitJoinDirectory)
    }

    // MARK: - Path Resolution

    /// True wenn die App als Bundle läuft (nicht via swift run)
    private var isBundled: Bool {
        let bundledEngine = Bundle.main.resourceURL?
            .appendingPathComponent("multicam-engine/multicam-engine")
        return bundledEngine != nil && FileManager.default.fileExists(atPath: bundledEngine!.path)
    }

    /// Resolve-Toolkit Root (nur für Dev-Modus)
    private var toolkitRoot: URL {
        let fromSource = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // Sources/
            .deletingLastPathComponent()  // MulticamCutter/
            .deletingLastPathComponent()  // multicam-cutter/
            .deletingLastPathComponent()  // apps/
        if FileManager.default.fileExists(atPath: fromSource.appendingPathComponent("venv").path) {
            return fromSource
        }
        return URL(fileURLWithPath: "/Users/maxmenge/Developer/resolve-toolkit")
    }

    /// Gibt (executablePath, arguments) zurück.
    /// Im Bundle: Engine-Binary direkt starten (kein Python nötig).
    /// Im Dev: Python + Engine-Script.
    func engineCommand(extraArgs: [String] = []) -> (String, [String])? {
        if isBundled {
            // Bundle-Modus: Engine als standalone Binary
            guard let engineURL = Bundle.main.resourceURL?
                    .appendingPathComponent("multicam-engine/multicam-engine") else { return nil }
            return (engineURL.path, extraArgs)
        } else {
            // Dev-Modus: Python + Script
            guard let pythonPath = findPythonPath(),
                  let enginePath = findEnginePath() else { return nil }
            return (pythonPath, [enginePath] + extraArgs)
        }
    }

    private func findEnginePath() -> String? {
        let devPath = toolkitRoot
            .appendingPathComponent("apps/multicam-cutter/engine/multicam_engine.py")
        if FileManager.default.fileExists(atPath: devPath.path) {
            return devPath.path
        }
        return nil
    }

    private func findPythonPath() -> String? {
        let venvPython = toolkitRoot.appendingPathComponent("venv/bin/python3")
        if FileManager.default.fileExists(atPath: venvPython.path) {
            return venvPython.path
        }
        for path in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"] {
            if FileManager.default.fileExists(atPath: path) {
                return path
            }
        }
        return nil
    }

    /// Verzeichnis mit den gebündelten ffmpeg/ffprobe. Im Bundle: `Resources/`
    /// (dort liegen ffmpeg + ffprobe neben dem multicam-engine-Ordner). Im Dev:
    /// `scripts/` mit den statischen Builds, falls vorhanden (sonst nil → das
    /// Homebrew-ffmpeg aus dem Terminal-PATH).
    private var ffmpegDirectory: String? {
        if isBundled {
            return Bundle.main.resourceURL?.path
        }
        let devDir = toolkitRoot.appendingPathComponent("apps/multicam-cutter/scripts")
        let ffmpeg = devDir.appendingPathComponent("ffmpeg")
        return FileManager.default.fileExists(atPath: ffmpeg.path) ? devDir.path : nil
    }

    /// Standard-Umgebung für Engine-Subprozesse. WICHTIG: stellt ffmpeg/ffprobe
    /// an den Anfang des PATH — die Engine ruft sie als bloße Namen auf, und eine
    /// per Finder/Dock gestartete App erbt KEINEN Homebrew-PATH. Ohne das:
    /// duration_s = 0 und keine Thumbnails (alle ffprobe/ffmpeg-Aufrufe scheitern).
    func engineEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["MCC_JOIN_DIR"] = Self.splitJoinDirectory.path
        if let dir = ffmpegDirectory {
            let existing = env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
            env["PATH"] = dir + ":" + existing
        }
        return env
    }
}
