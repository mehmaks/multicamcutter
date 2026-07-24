import SwiftUI

// UI-Regel „fluechtige Informationen" (siehe brain/Design-System.md):
// Info-Banner, die nur informieren und keine Entscheidung blockieren, blenden
// sich nach ~7,5 s selbst aus. Hover pausiert das Ausblenden (wer liest, wird
// nicht ueberrascht); das X bleibt fuer sofortiges Schliessen. NICHT anwenden
// auf Warnungen, die eine Handlung erfordern (FPS-Mismatch, Fehler, Blocker).

struct AutoDismiss: ViewModifier {
    var seconds: Double = 7.5
    let dismiss: () -> Void
    @State private var hovering = false

    func body(content: Content) -> some View {
        content
            .onHover { hovering = $0 }
            .task {
                try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                guard !Task.isCancelled else { return }
                // Solange der Mauszeiger auf dem Banner liegt, warten.
                while hovering {
                    try? await Task.sleep(nanoseconds: 500_000_000)
                    guard !Task.isCancelled else { return }
                }
                withAnimation(.easeOut(duration: 0.4)) { dismiss() }
            }
    }
}

extension View {
    /// Blendet fluechtige Info-Banner nach `seconds` automatisch aus.
    func autoDismiss(after seconds: Double = 7.5,
                     _ dismiss: @escaping () -> Void) -> some View {
        modifier(AutoDismiss(seconds: seconds, dismiss: dismiss))
    }
}

/// Schliess-Button (X) mit ablaufendem Ring: der Ring zeigt sichtbar, wann sich
/// ein fluechtiges Info-Banner von selbst schliesst (User-Wunsch 25.07.).
/// Uebernimmt AUCH das automatische Ausblenden — ersetzt also den separaten
/// `.autoDismiss`-Modifier am selben Banner (sonst liefen zwei Timer). `paused`
/// kommt vom Banner (Hover pausiert, damit wer liest nicht ueberrascht wird);
/// Klick schliesst sofort.
struct CountdownDismissButton: View {
    var seconds: Double = 7.5
    var diameter: CGFloat = 18
    @Binding var paused: Bool
    let dismiss: () -> Void

    @State private var remaining: Double

    init(seconds: Double = 7.5, diameter: CGFloat = 18,
         paused: Binding<Bool>, dismiss: @escaping () -> Void) {
        self.seconds = seconds
        self.diameter = diameter
        self._paused = paused
        self.dismiss = dismiss
        self._remaining = State(initialValue: seconds)
    }

    var body: some View {
        Button(action: dismiss) {
            ZStack {
                Circle()                                   // Spur
                    .stroke(Color.wizMuted.opacity(0.25), lineWidth: 1.5)
                Circle()                                   // ablaufender Rest
                    .trim(from: 0, to: max(0, remaining / seconds))
                    .stroke(Color.brandAccent.opacity(0.7),
                            style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
                    .rotationEffect(.degrees(-90))         // startet oben
                LucideIcon("x", size: diameter * 0.5)
                    .foregroundStyle(.wizMuted)
            }
            .frame(width: diameter, height: diameter)
        }
        .buttonStyle(.plain)
        .help("Hinweis ausblenden")
        .task {
            // ~30 fps herunterzaehlen; pausiert solange der Zeiger auf dem Banner
            // liegt. @Binding im Loop zu lesen sieht Aenderungen (wie AutoDismiss
            // mit @State) — der Backing-Store ist stabil.
            let tick = 1.0 / 30.0
            while remaining > 0 {
                try? await Task.sleep(nanoseconds: UInt64(tick * 1_000_000_000))
                if Task.isCancelled { return }
                if !paused { remaining -= tick }
            }
            withAnimation(.easeOut(duration: 0.4)) { dismiss() }
        }
    }
}
