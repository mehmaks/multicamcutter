import SwiftUI
import AppKit

// MARK: - Datenmodell (aus Resources/acknowledgements.json)

struct Acknowledgement: Codable, Identifiable {
    let name: String
    let version: String
    let license: String
    let url: String
    let note: String
    let text: String
    var id: String { name }
}

private struct AcknowledgementsData: Codable { let components: [Acknowledgement] }

/// Laedt die von `scripts/collect_licenses.py` erzeugte JSON. Im gebauten .app
/// aus den Resources, im Dev-Build (`swift run`) aus `scripts/` relativ zur Quelle.
enum AcknowledgementsLoader {
    static func load() -> [Acknowledgement] {
        if let url = Bundle.main.url(forResource: "acknowledgements", withExtension: "json"),
           let comps = decode(url) { return comps }

        let devURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // Sources
            .deletingLastPathComponent()   // MulticamCutter
            .deletingLastPathComponent()   // multicam-cutter
            .appendingPathComponent("scripts/acknowledgements.json")
        return decode(devURL) ?? []
    }

    private static func decode(_ url: URL) -> [Acknowledgement]? {
        guard let data = try? Data(contentsOf: url),
              let decoded = try? JSONDecoder().decode(AcknowledgementsData.self, from: data)
        else { return nil }
        return decoded.components
    }
}

// MARK: - View (Master-Detail, scrollbare Lizenztexte)

struct AcknowledgementsView: View {
    private let components: [Acknowledgement]
    @State private var selection: Acknowledgement.ID?

    init(components: [Acknowledgement]? = nil) {
        let comps = components ?? AcknowledgementsLoader.load()
        self.components = comps
        _selection = State(initialValue: comps.first?.id)
    }

    var body: some View {
        NavigationSplitView {
            ScrollViewReader { proxy in
                List(components, selection: $selection) { c in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(c.name)
                        Text(c.license)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    .tag(c.id)
                    .id(c.id)
                }
                .onAppear { if let sel = selection { proxy.scrollTo(sel, anchor: .top) } }
            }
            .navigationSplitViewColumnWidth(min: 200, ideal: 250)
        } detail: {
            if let sel = components.first(where: { $0.id == selection }) {
                detail(sel)
            } else if components.isEmpty {
                ContentUnavailableView {
                    Label { Text("No license info loaded") } icon: {
                        LucideIcon("file-search", size: 40)
                    }
                } description: {
                    Text("acknowledgements.json is missing from the bundle.")
                }
            } else {
                ContentUnavailableView {
                    Label { Text("Select a component") } icon: {
                        LucideIcon("file-text", size: 40)
                    }
                }
            }
        }
        .frame(minWidth: 720, minHeight: 460)
    }

    @ViewBuilder
    private func detail(_ c: Acknowledgement) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text(c.name).font(.title2.bold())
                    if !c.version.isEmpty {
                        Text(c.version).font(.callout).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if !c.url.isEmpty, let url = URL(string: c.url) {
                        Link(destination: url) {
                            LucideLabel("Project page", icon: "external-link", size: 13)
                        }
                        .font(.callout)
                    }
                }
                Text(c.license)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.brandAccent)
                if !c.note.isEmpty {
                    Text(c.note)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(20)

            Divider()

            // NSTextView statt SwiftUI-ScrollView: startet zuverlässig oben
            // (SwiftUIs .textSelection scrollte den langen GPL-Text nach dem
            // Öffnen selbst wieder mittig), performant + nativ selektierbar.
            SelectableText(text: c.text)
        }
        .id(c.id)
    }
}

// MARK: - Fenster (AppKit-gehostet, per Button aus dem Ueber-Dialog)

@MainActor
final class AcknowledgementsWindowController {
    static let shared = AcknowledgementsWindowController()
    private var window: NSWindow?

    func show() {
        if window == nil {
            let hosting = NSHostingController(rootView: AcknowledgementsView().tint(.brandAccent))
            let w = NSWindow(contentViewController: hosting)
            w.title = "Open-source licenses"
            w.styleMask = [.titled, .closable, .resizable, .miniaturizable]
            w.setContentSize(NSSize(width: 840, height: 560))
            w.isReleasedWhenClosed = false
            w.center()
            window = w
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

// MARK: - Selektierbare, scrollbare Textanzeige (NSTextView)

/// NSTextView-basiert, weil SwiftUIs `ScrollView` + `.textSelection` den langen
/// GPL-Text nach dem Öffnen selbst wieder mittig scrollte. NSTextView startet
/// zuverlässig oben und ist bei großen Texten performanter — bleibt selektierbar.
struct SelectableText: NSViewRepresentable {
    let text: String

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSTextView.scrollableTextView()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        if let tv = scroll.documentView as? NSTextView {
            tv.isEditable = false
            tv.isSelectable = true
            tv.drawsBackground = false
            tv.textContainerInset = NSSize(width: 16, height: 16)
            tv.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        }
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let tv = scroll.documentView as? NSTextView, tv.string != text else { return }
        tv.string = text
        tv.textColor = .labelColor
        // Nach dem Setzen sicher nach oben — auch nach dem Layout-Durchlauf.
        DispatchQueue.main.async {
            tv.scrollRangeToVisible(NSRange(location: 0, length: 0))
            scroll.contentView.scroll(to: .zero)
            scroll.reflectScrolledClipView(scroll.contentView)
        }
    }
}
