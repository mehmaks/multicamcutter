import SwiftUI

// MARK: - Parameter-Hilfetexte
//
// Verbatim übernommen aus dem Web-UI-Schema `config/schemas/multicam_params.json`
// (Feld `help`), damit App und Web-Modul dieselben Erklärungen zeigen.
// Bei Parameter-Änderungen: dort UND hier nachziehen.
// Ausnahme: `fps` ist app-spezifisch (im Web-Schema nicht vorhanden).

enum ParamHelp {
    // Schnittregeln
    static let minShot = "Wie lange eine Kamera mindestens zu sehen ist, bevor zu einer Reaktion geschnitten werden darf."
    static let maxShot = "Bleibt eine Kamera länger als dieser Wert ohne Schnitt, wird automatisch zu einer Reaktion gewechselt."
    static let reactionDur = "Wie lange eine Reaktion mindestens gezeigt wird."
    static let cleanupDur = "Schnitte kürzer als dieser Wert werden automatisch entfernt."

    // Sprecher-Erkennung
    static let thresholdDb = "Wie deutlich lauter jemand sein muss als die aktiv sprechende Person, damit ein Sprecherwechsel erkannt wird."
    static let minEdit = "Sehr kurze Sprechabschnitte werden mit dem nächsten zusammengelegt. Verhindert zu häufiges Hin- und Herschneiden."
    static let changeDelay = "Wie lange eine Person durchgehend lauter sein muss, bevor auf diese geschnitten wird. Verhindert Schnitte bei kurzen Überschneidungen."

    // Cutaway-Typen
    static let noddingEnabled = "Erkennt Kopfnicken einer zuhörenden Person und schneidet in diesem Moment auf sie."
    static let minConf = "Wie sicher die Erkennung sein muss, bevor ein Nicken als Schnitt verwendet wird."
    static let speakingEnabled = "Erkennt kurze Einwürfe oder Laute einer nicht aktiv sprechenden Person und schneidet in diesem Moment auf sie."
    static let riseDb = "Wie stark die Baseline ansteigen muss, um einen Sprach-Cutaway auszulösen."
    static let speakingMaxDur = "Maximale Dauer eines Sprach-Cutaways. Im Normalfall endet der Cutaway organisch wenn die Baseline abfällt."
    static let pauseCutawayEnabled = "Schneidet während einer Sprechpause der aktiv sprechenden Person auf eine andere Kamera."
    static let pauseCutawayMinPause = "Wie lang eine Sprechpause mindestens sein muss, damit ein Cutaway eingefügt wird."
    static let clipFilterEnabled = "Prüft per Bilderkennung, ob ein Cutaway eine unerwünschte Szene zeigt (z.B. „Person trinkt“) und verschiebt ihn automatisch. Prompts können in den App-Einstellungen festgelegt werden."

    // Cutaway-Feintuning
    static let preRoll = "Der Schnitt wird um diese Anzahl Bilder früher gesetzt, damit die Reaktion natürlicher wirkt."
    static let randomness = "Wie stark die Länge der Reaktionsaufnahmen variieren darf. Höhere Werte machen den Schnitt weniger maschinell."

    // Pausen-Trimming
    static let pauseTrimEnabled = "Überlange Sprechpausen bei Sprecherwechseln automatisch kürzen."
    static let maxPause = "Maximale Pausenlänge die bestehen bleibt. Längere Pausen werden auf diesen Wert gekürzt."
    static let pauseCutMode = "Legt fest, wo der Videocut in einer Pause liegt."
    static let totaleMode = "Bei mehreren als Totale markierten Kameras: welche wird geschnitten? Reihum wechselt der Reihe nach durch, Zufällig mischt sie (bei jedem Lauf gleich), Nur die erste nimmt immer dieselbe. Bei nur einer Totale ohne Wirkung."
    static let pauseSilenceDb = "dB-Schwelle unter der beide Mikrofone als still gelten. Standard: -40 dB."

    // Crossbleed-Filter
    static let crossbleedGateEnabled = "Unterdrückt Übersprechen zwischen Mikrofonen vor der Sprechererkennung. Nützlich wenn beide Mics im selben Raum stehen."
    static let gateFloor = "Wie stark das inaktive Mikrofon gedämpft wird. -25 dB unterdrückt Crossbleed stark, lässt aber minimale Raumakustik durch."
    static let gateHysteresis = "Vermeidet „Flattern“ an Grenzen. Ein Wechsel findet erst statt, wenn das andere Mikrofon um diesen Betrag lauter wird."
    static let gateWindow = "Analyse-Fenster für den Pegelvergleich. Größer für Raumhall, kleiner für schnelle Wechsel."
    static let gateAttack = "Wie schnell das Gate öffnet. Kürzer, damit Silbenanfänge nicht verloren gehen."
    static let gateRelease = "Wie langsam das Gate schließt. Längere Werte verhindern Pumping-Effekte."
    static let gateBothThreshold = "Wenn der Pegelunterschied kleiner als dieser Wert ist, werden alle Mikrofone durchgelassen (gleichzeitiges Sprechen)."
    static let gateUseFiltered = "Debug: Verwendet die gefilterten WAVs statt der Originale in der finalen Timeline. Nur zu Testzwecken."

    // Totale
    static let totaleSimulDur = "Wie lange beide gleichzeitig sprechen müssen, bevor auf die Totale geschnitten wird."

    // Allgemein (app-spezifisch, nicht im Web-Schema)
    static let fps = "Bildrate der Timeline. Muss zur Framerate deiner Kameras passen, sonst sitzen die Schnitte nicht korrekt."
    static let micsSameRecorder = "Aktiviere das, wenn alle deine Tonspuren aus demselben Aufnahmegerät (Mehrspur-Recorder) stammen. Dann misst die App sie gemeinsam ein — eine Spur, auf der gerade niemand spricht, kann die Synchronisierung so nicht mehr durcheinanderbringen."

    // Bildsprache — Übergänge über größere Einstellungen
    static let bildspracheIntro = "Diese Einstellungen betreffen Schnitte auf eine größere Einstellung — etwa eine Totale, auf der mehrere Personen zu sehen sind. Sie werden als sanfter Zwischenschritt genutzt, statt hart von einer Nahaufnahme zur nächsten zu springen."
    static let transitionSpeakerChange = "Beim Wechsel zwischen zwei sprechenden Personen kurz auf eine größere Einstellung schneiden, die beide zeigt, statt direkt umzuschneiden."
    static let transitionReturnFactor = "Wie viel länger als Min. Schnittlänge der nächste Schnitt sein muss, damit der Übergang über eine größere Einstellung genutzt wird."
    static let transitionCutawayNodding = "Nach einem Schnitt auf ein Nicken über eine größere Einstellung zurück zur sprechenden Person, statt direkt zurückzuschneiden."
    static let transitionCutawaySpeaking = "Nach einem Schnitt auf einen kurzen Einwurf über eine größere Einstellung zurück zur sprechenden Person."
    static let transitionCutawayPause = "Nach einem Pausen-Cutaway über eine größere Einstellung zurück zur sprechenden Person."
    static let transitionCutawayCooldown = "Wie viele Schnitte vergehen müssen, bevor dieselbe größere Einstellung erneut als Übergang genutzt wird. Verhindert, dass sie zu oft hintereinander kommt. Wenn „Cooldown (Zeit)“ nicht vorher erreicht wird."
    static let transitionCutawayCooldownS = "Wie viele Sekunden vergehen müssen, bevor dieselbe größere Einstellung erneut genutzt wird. Wenn „Cooldown (Schnitte)“ nicht vorher erreicht wird."
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
            .overlay(AppKitToolTip(text: text))   // trägt den Tooltip
            .help(text)                            // Fallback + VoiceOver
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
            Text(title)
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
