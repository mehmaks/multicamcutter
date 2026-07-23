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
