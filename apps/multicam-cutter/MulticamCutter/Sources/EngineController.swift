import SwiftUI
import Foundation
import AVFoundation

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
    var durationSeconds: Double
    /// Siehe CameraInfo.included.
    var included: Bool = true

    func hash(into hasher: inout Hasher) { hasher.combine(id) }
    static func == (lhs: MicInfo, rhs: MicInfo) -> Bool { lhs.id == rhs.id }
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
    var pauseSilenceDb: Double = -40.0

    // Expert: Crossbleed-Gate
    var crossbleedGateEnabled: Bool = false
    var gateFloor: Double = -25.0
    var gateHysteresis: Double = 2.0
    var gateWindow: Double = 80.0
    var gateAttack: Double = 15.0
    var gateRelease: Double = 80.0
    var gateBothThreshold: Double = 3.0
    var gateUseFiltered: Bool = false

    // Expert: Cutaway-Regeln
    var preRoll: Int = 15
    var randomness: Double = 0.2
    var minConf: Double = 0.60
    var riseDb: Double = 6.0
    var speakingMaxDur: Double = 2.5
    var pauseCutawayMinPause: Double = 2.0
    var clipFilterEnabled: Bool = false

    // Expert: Totale
    var totaleSimulDur: Double = 3.0

    func toJSON() -> String {
        let dict: [String: Any] = [
            "min_shot": minShot,
            "max_shot": maxShot,
            "cleanup_dur": cleanupDur,
            "reaction_dur": reactionDur,
            "pause_trim_enabled": pauseTrimEnabled,
            "max_pause": maxPause,
            "pause_cut_mode": pauseCutMode,
            "pause_silence_db": pauseSilenceDb,
            "min_conf": minConf,
            "min_edit": minEdit,
            "change_delay": changeDelay,
            "nodding_enabled": noddingEnabled,
            "speaking_enabled": speakingEnabled,
            "crossbleed_gate_enabled": crossbleedGateEnabled,
            "pause_cutaway_enabled": pauseCutawayEnabled,
            "pause_cutaway_min_pause": pauseCutawayMinPause,
            "clip_filter_enabled": clipFilterEnabled,
            "pre_roll": preRoll,
            "randomness": randomness,
            "rise_db": riseDb,
            "speaking_max_dur": speakingMaxDur,
            "gate_floor": gateFloor,
            "gate_hysteresis": gateHysteresis,
            "gate_window": gateWindow,
            "gate_attack": gateAttack,
            "gate_release": gateRelease,
            "gate_both_threshold": gateBothThreshold,
            "gate_use_filtered": gateUseFiltered,
            "threshold_db": thresholdDb,
            "totale_simul_dur": totaleSimulDur,
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
            "pause_silence_db": pauseSilenceDb,
            "min_conf": minConf, "min_edit": minEdit, "change_delay": changeDelay,
            "nodding_enabled": noddingEnabled, "speaking_enabled": speakingEnabled,
            "crossbleed_gate_enabled": crossbleedGateEnabled,
            "pause_cutaway_enabled": pauseCutawayEnabled,
            "pause_cutaway_min_pause": pauseCutawayMinPause,
            "clip_filter_enabled": clipFilterEnabled,
            "pre_roll": preRoll, "randomness": randomness,
            "rise_db": riseDb, "speaking_max_dur": speakingMaxDur,
            "gate_floor": gateFloor, "gate_hysteresis": gateHysteresis,
            "gate_window": gateWindow, "gate_attack": gateAttack,
            "gate_release": gateRelease, "gate_both_threshold": gateBothThreshold,
            "gate_use_filtered": gateUseFiltered,
            "threshold_db": thresholdDb, "totale_simul_dur": totaleSimulDur,
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
        if let v = dict["pause_silence_db"] as? Double { pauseSilenceDb = v }
        if let v = dict["min_conf"] as? Double { minConf = v }
        if let v = dict["min_edit"] as? Double { minEdit = v }
        if let v = dict["change_delay"] as? Double { changeDelay = v }
        if let v = dict["nodding_enabled"] as? Bool { noddingEnabled = v }
        if let v = dict["speaking_enabled"] as? Bool { speakingEnabled = v }
        if let v = dict["crossbleed_gate_enabled"] as? Bool { crossbleedGateEnabled = v }
        if let v = dict["pause_cutaway_enabled"] as? Bool { pauseCutawayEnabled = v }
        if let v = dict["pause_cutaway_min_pause"] as? Double { pauseCutawayMinPause = v }
        if let v = dict["clip_filter_enabled"] as? Bool { clipFilterEnabled = v }
        if let v = dict["pre_roll"] as? Int { preRoll = v }
        if let v = dict["randomness"] as? Double { randomness = v }
        if let v = dict["rise_db"] as? Double { riseDb = v }
        if let v = dict["speaking_max_dur"] as? Double { speakingMaxDur = v }
        if let v = dict["gate_floor"] as? Double { gateFloor = v }
        if let v = dict["gate_hysteresis"] as? Double { gateHysteresis = v }
        if let v = dict["gate_window"] as? Double { gateWindow = v }
        if let v = dict["gate_attack"] as? Double { gateAttack = v }
        if let v = dict["gate_release"] as? Double { gateRelease = v }
        if let v = dict["gate_both_threshold"] as? Double { gateBothThreshold = v }
        if let v = dict["gate_use_filtered"] as? Bool { gateUseFiltered = v }
        if let v = dict["threshold_db"] as? Double { thresholdDb = v }
        if let v = dict["totale_simul_dur"] as? Double { totaleSimulDur = v }
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

    /// Eingebaute Standard-Presets
    private let builtInPresets: [(String, String, PipelineParams)] = [
        ("podcast_2cam", "Podcast 2-Cam", PipelineParams()),
        ("interview_fast", "Interview (schnell)", {
            var p = PipelineParams()
            p.maxShot = 10.0
            p.cleanupDur = 1.2
            p.reactionDur = 1.5
            return p
        }()),
        // Werte aus dem bewährten Web-Preset „Jena United" übernommen
        // (~/.resolve-toolkit/multicam_presets/). Beim Portieren umgerechnet:
        // min_conf 69 % → 0.69, pause_cut_mode „Middle" → „middle".
        // Nicht gesetzte Parameter entsprechen den PipelineParams-Defaults.
        ("talk_relaxed", "Talk (entspannt)", {
            var p = PipelineParams()
            p.minShot = 2.3
            p.cleanupDur = 1.6
            p.reactionDur = 1.7
            p.pauseTrimEnabled = true
            p.crossbleedGateEnabled = true
            p.preRoll = 5
            p.minConf = 0.69
            p.pauseCutawayEnabled = true
            // CLIP bewusst AUS in allen Built-ins: Der Filter braucht ein 577-MB-Modell,
            // das erst geladen werden muss. Ein Extra — niemand soll beim ersten Lauf
            // ungefragt damit konfrontiert werden. Wer's will, aktiviert es im
            // Expertenmodus (dann kommt der Download-Prompt) und speichert sein Preset.
            p.clipFilterEnabled = false
            return p
        }()),
    ]

    func listPresets() -> [Preset] {
        var result = builtInPresets.map { Preset(id: $0.0, name: $0.1, builtIn: true) }

        // User-Presets aus dem Dateisystem
        if let files = try? FileManager.default.contentsOfDirectory(
            at: presetsDir, includingPropertiesForKeys: nil
        ) {
            for file in files where file.pathExtension == "json" {
                let id = file.deletingPathExtension().lastPathComponent
                if result.contains(where: { $0.id == id }) { continue }
                // Name aus JSON lesen
                if let data = try? Data(contentsOf: file),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let name = json["name"] as? String {
                    result.append(Preset(id: id, name: name, builtIn: false))
                }
            }
        }
        return result
    }

    func loadPreset(_ id: String) -> PipelineParams? {
        // Built-in?
        if let builtIn = builtInPresets.first(where: { $0.0 == id }) {
            return builtIn.2
        }
        // User-Preset
        let file = presetsDir.appendingPathComponent("\(id).json")
        guard let data = try? Data(contentsOf: file),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let paramsDict = json["params"] as? [String: Any] else { return nil }
        var params = PipelineParams()
        params.apply(paramsDict)
        return params
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
    @Published var folderURL: URL?
    @Published var episodeName: String = ""
    @Published var cameraInfos: [CameraInfo] = []
    @Published var micInfos: [MicInfo] = []
    @Published var fps: Double = 25.0
    @Published var params = PipelineParams()

    // Progress (Pipeline)
    @Published var stepLabel: String = ""
    @Published var stepNum: Int = 0
    @Published var totalSteps: Int = 1
    @Published var stepPercent: Double = 0
    @Published var stepETA: String = ""

    /// Gesamtfortschritt 0…1 über alle Schritte (für den Dock-Balken). stepNum ist 1-basiert.
    var overallProgress: Double {
        guard totalSteps > 0 else { return 0 }
        let f = (Double(stepNum - 1) + stepPercent / 100) / Double(totalSteps)
        return min(max(f, 0), 1)
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
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: session, options: .prettyPrinted) else { return }
        try? data.write(to: url)
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

        // Cam labels + zuordnungen wiederherstellen (nur wenn Dateien noch passen)
        if let savedCams = session["cameras"] as? [[String: Any]] {
            for saved in savedCams {
                guard let id = saved["id"] as? Int,
                      let filename = saved["filename"] as? String,
                      let idx = cameraInfos.firstIndex(where: { $0.id == id && $0.filename == filename }) else { continue }
                if let displayName = saved["display_name"] as? String {
                    cameraInfos[idx].displayName = displayName
                }
                if let mics = saved["assigned_mics"] as? [Int] {
                    cameraInfos[idx].assignedMics = mics
                }
                // Aeltere Sessions kennen "included"/"tag" nicht → Defaults beibehalten.
                if let included = saved["included"] as? Bool {
                    cameraInfos[idx].included = included
                }
            }
        }

        // Mic labels wiederherstellen
        if let savedMics = session["mics"] as? [[String: Any]] {
            for saved in savedMics {
                guard let id = saved["id"] as? Int,
                      let filename = saved["filename"] as? String,
                      let idx = micInfos.firstIndex(where: { $0.id == id && $0.filename == filename }) else { continue }
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
        stepLabel = "Starte..."
        stepNum = 0
        totalSteps = 1
        stepPercent = 0
        stepETA = ""
        logMessages = []
        resultAAF = nil
        resultStats = nil

        Task {
            await runEngine(folder: folder)
        }
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
        logMessages = []
        state = .ready
    }

    // MARK: - Audio Preview

    func toggleMicPreview(_ mic: MicInfo) {
        // Gleicher Mic — Stop
        if playingMicId == mic.id {
            audioPlayer?.stop()
            audioPlayer = nil
            playingMicId = nil
            return
        }
        // Anderer Mic oder keiner — alten stoppen, neuen starten
        audioPlayer?.stop()
        audioPlayer = nil
        playingMicId = nil

        guard let path = mic.previewPath else { return }
        let url = URL(fileURLWithPath: path)
        do {
            let player = try AVAudioPlayer(contentsOf: url)
            player.play()
            audioPlayer = player
            playingMicId = mic.id
            // Auto-Reset wenn fertig
            let duration = player.duration
            DispatchQueue.main.asyncAfter(deadline: .now() + duration + 0.1) { [weak self] in
                if self?.playingMicId == mic.id {
                    self?.playingMicId = nil
                    self?.audioPlayer = nil
                }
            }
        } catch {
            // Playback fehlgeschlagen — still ignorieren
        }
    }

    func stopAllPlayback() {
        audioPlayer?.stop()
        audioPlayer = nil
        playingMicId = nil
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
                await MainActor.run { clipError = "Engine nicht gefunden"; isDownloadingClip = false }
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
                    clipError = "Download konnte nicht gestartet werden: \(error.localizedDescription)"
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
                    clipError = "Download fehlgeschlagen (Code \(process.terminationStatus))."
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
            return "Kein gültiges JSON."
        }
        guard obj["global"] != nil, obj["patterns"] is [Any] else {
            return "JSON braucht die Felder 'global' und 'patterns'."
        }
        let url = noddingUserPatternsURL
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                    withIntermediateDirectories: true)
            try data.write(to: url)
            return nil
        } catch { return "Schreiben fehlgeschlagen: \(error.localizedDescription)" }
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
    var fpsMismatches: [CameraInfo] {
        activeCams.filter { $0.fps <= 0 || abs($0.fps - fps) > 0.01 }
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
            let args = ["--convert-fps", "--fps", String(fps), "--files"] + targets
            guard let (execPath, baseArgs) = engineCommand(extraArgs: args) else {
                await MainActor.run {
                    convertError = "Engine nicht gefunden"
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
                    convertError = "Konvertierung konnte nicht gestartet werden: \(error.localizedDescription)"
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
                            convertLabel = msg["label"] as? String ?? convertLabel
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
                    convertError = "Konvertierung fehlgeschlagen (Code \(code))."
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
        guard let (execPath, baseArgs) = engineCommand(extraArgs: ["--folder", folder.path, "--scan"]) else {
            errorMessage = "Engine oder Python nicht gefunden"
            state = .error
            return
        }

        scanLabel = "Ordner wird gescannt..."
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
            errorMessage = "Scan fehlgeschlagen: \(error.localizedDescription)"
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
                        if let label = json["label"] as? String { scanLabel = label }
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
            errorMessage = "Scan: keine Ausgabe vom Engine-Prozess"
            state = .error
            return
        }

        // scan_complete Zeile finden
        guard let scanLine = allLines.last(where: { $0.contains("scan_complete") }),
              let lineData = scanLine.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
              let camerasArr = json["cameras"] as? [[String: Any]],
              let micsArr = json["mics"] as? [[String: Any]] else {
            errorMessage = "Scan: Ergebnis konnte nicht gelesen werden.\nEngine-Output: \(output.prefix(200))"
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
                durationSeconds: mic["duration_s"] as? Double ?? 0
            ))
        }

        // Keine Auto-Zuordnung — Mics starten als "nicht zugeordnet".
        // User ordnet manuell per Drag & Drop zu.

        cameraInfos = newCams
        micInfos = newMics

        if cameraInfos.count < 2 {
            errorMessage = "Mindestens 2 Kamera-Clips erwartet, \(cameraInfos.count) gefunden."
            state = .error
            return
        }
        if micInfos.isEmpty {
            errorMessage = "Keine Mikrofon-Dateien gefunden."
            state = .error
            return
        }

        // Gespeicherte Session laden (Labels, Zuordnungen, Parameter)
        if loadSession() {
            logMessages.append("Session wiederhergestellt (.multicam)")
        }

        // Phase 5: Existiert schon eine Zuordnung (Person auf Cam), direkt zur
        // Übersicht springen statt den Wizard von Schritt 1 zu starten.
        if decideWizardStep {
            wizardStep = cameraInfos.contains { !$0.assignedMics.isEmpty } ? .overview : .persons
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

        guard let (execPath, baseArgs) = engineCommand(extraArgs: extraArgs) else {
            errorMessage = "Engine oder Python nicht gefunden"
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
            errorMessage = "Engine konnte nicht gestartet werden: \(error.localizedDescription)"
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
                errorMessage = "Engine beendet mit Code \(process.terminationStatus)"
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
            if let label = json["label"] as? String {
                stepLabel = label
                stepPercent = 0
                stepETA = ""
            }
            if let num = json["step_num"] as? Int { stepNum = num }
            if let total = json["total_steps"] as? Int { totalSteps = total }
            stopPreviewPolling()
            logMessages.append("Schritt \(stepNum)/\(totalSteps): \(stepLabel)")

        case "step_start_sub":
            // Subprocess-Step innerhalb von run_analysis
            if let label = json["label"] as? String {
                stepLabel = label
                stepPercent = 0
                stepETA = ""
                stepNum += 1
            }
            // Facemesh-Preview starten/stoppen
            if let path = json["preview_path"] as? String {
                startPreviewPolling(path: path)
            } else {
                stopPreviewPolling()
            }
            logMessages.append("Schritt \(stepNum)/\(totalSteps): \(stepLabel)")

        case "step_progress":
            if let percent = json["percent"] as? Double {
                stepPercent = percent
            }
            if let eta = json["eta"] as? String, !eta.isEmpty {
                stepETA = eta
            }

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
                stats["Dauer"] = "\(min)m \(sec)s"
            }
            if let byType = json["events_by_type"] as? [String: Int] {
                for (key, count) in byType.sorted(by: { $0.key < $1.key }) {
                    stats[key] = "\(count)x"
                }
            }
            resultStats = stats
            state = .done

        case "log":
            if let message = json["message"] as? String {
                logMessages.append(message)
            }

        case "session_start":
            logMessages.append("Session gestartet")

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
        LicenseConfig.apply(to: &env)
        env["PYTHONUNBUFFERED"] = "1"
        if let dir = ffmpegDirectory {
            let existing = env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
            env["PATH"] = dir + ":" + existing
        }
        return env
    }
}
