import SwiftUI
import AVFoundation

/// Video-Thumbnail das bei Mouse-Hover den Frame basierend auf der
/// horizontalen Position scrubt. Linker Rand = erster Frame,
/// rechter Rand = letzter Frame.
struct ScrubbableThumbnail: View {
    let videoPath: String
    let initialThumbnailPath: String?
    let durationSeconds: Double
    /// Callback wenn User per Klick ein Thumbnail setzt (Pfad zum gespeicherten JPEG)
    var onThumbnailSet: ((String) -> Void)?

    @State private var isHovering = false
    @State private var scrubImage: NSImage?
    @State private var pinnedImage: NSImage?
    @State private var hoverFraction: Double = 0
    @State private var currentTimeLabel: String = ""

    private var displayImage: NSImage? {
        if isHovering, let scrub = scrubImage {
            return scrub
        }
        if let pinned = pinnedImage {
            return pinned
        }
        if let path = initialThumbnailPath {
            return NSImage(contentsOfFile: path)
        }
        return nil
    }

    var body: some View {
        // 16:9-Box AUS DER BREITE abgeleitet (Color.clear + .fit): so kann das
        // Thumbnail nie vertikal wuchern. Frueher lag die Ratio direkt auf dem Bild
        // mit `.fill` — dadurch dehnte es sich, sobald eine Karte hoeher wurde
        // (Totale-Pill / 2 Mics), und lief ueber die darunterliegenden Elemente.
        Color.clear
            .overlay {
                ZStack(alignment: .bottomLeading) {
                    if let image = displayImage {
                        Image(nsImage: image)
                            .resizable()
                            .scaledToFill()
                    } else {
                        Rectangle()
                            .fill(.quaternary)
                            .overlay {
                                Image(systemName: "video.slash")
                                    .font(.title)
                                    .foregroundStyle(.secondary)
                            }
                    }

                    // Timecode-Label bei Hover
                    if isHovering {
                        Text(currentTimeLabel)
                            .font(.system(.caption2, design: .monospaced))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(.black.opacity(0.7))
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 4))
                            .padding(6)

                        // Positions-Indikator (dünne Linie)
                        GeometryReader { geo in
                            Rectangle()
                                .fill(.white.opacity(0.6))
                                .frame(width: 1)
                                .offset(x: hoverFraction * geo.size.width)
                        }
                    }
                }
            }
            .aspectRatio(16/9, contentMode: .fit)
            .clipped()
        .onContinuousHover { phase in
            switch phase {
            case .active:
                isHovering = true
            case .ended:
                isHovering = false
                scrubImage = nil
            }
        }
        .overlay {
            // GeometryReader fuer korrekte Breiten-Berechnung
            GeometryReader { geo in
                Color.clear
                    .contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location):
                            isHovering = true
                            let fraction = max(0, min(1, location.x / geo.size.width))
                            hoverFraction = fraction
                            let timeS = fraction * durationSeconds
                            currentTimeLabel = formatTime(timeS)
                            requestFrame(at: timeS)
                        case .ended:
                            isHovering = false
                            scrubImage = nil
                        }
                    }
                    .onTapGesture {
                        // Klick waehrend Hover: aktuellen Frame als Thumbnail pinnen
                        guard let image = scrubImage else { return }
                        pinnedImage = image
                        // Als JPEG speichern und Callback aufrufen
                        if let tiffData = image.tiffRepresentation,
                           let bitmap = NSBitmapImageRep(data: tiffData),
                           let jpegData = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.85]) {
                            if let thumbPath = initialThumbnailPath {
                                try? jpegData.write(to: URL(fileURLWithPath: thumbPath))
                                onThumbnailSet?(thumbPath)
                            }
                        }
                    }
            }
        }
    }

    // MARK: - Frame Extraction

    /// Debounced Frame-Request (max alle 50ms ein neuer Frame)
    @State private var lastRequestTime: Date = .distantPast

    private func requestFrame(at timeSeconds: Double) {
        let now = Date()
        guard now.timeIntervalSince(lastRequestTime) > 0.05 else { return }
        lastRequestTime = now

        let path = videoPath
        let time = timeSeconds

        Task.detached(priority: .userInitiated) {
            let image = await extractFrame(from: path, at: time)
            await MainActor.run {
                scrubImage = image
            }
        }
    }

    private func extractFrame(from path: String, at timeSeconds: Double) async -> NSImage? {
        let url = URL(fileURLWithPath: path)
        let asset = AVURLAsset(url: url)
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 480, height: 270)  // Kleine Preview genuegt
        generator.requestedTimeToleranceBefore = CMTime(seconds: 1, preferredTimescale: 600)
        generator.requestedTimeToleranceAfter = CMTime(seconds: 1, preferredTimescale: 600)

        let cmTime = CMTime(seconds: timeSeconds, preferredTimescale: 600)

        do {
            let (cgImage, _) = try await generator.image(at: cmTime)
            return NSImage(cgImage: cgImage, size: NSSize(width: cgImage.width, height: cgImage.height))
        } catch {
            return nil
        }
    }

    private func formatTime(_ seconds: Double) -> String {
        let h = Int(seconds) / 3600
        let m = (Int(seconds) % 3600) / 60
        let s = Int(seconds) % 60
        if h > 0 {
            return String(format: "%d:%02d:%02d", h, m, s)
        }
        return String(format: "%d:%02d", m, s)
    }
}
