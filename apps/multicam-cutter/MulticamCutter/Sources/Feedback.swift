import SwiftUI
import AppKit
import Darwin

// MARK: - System-Infos (für den Report-Kontext)

enum SystemInfo {
    static var osVersion: String {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        return "macOS \(v.majorVersion).\(v.minorVersion).\(v.patchVersion)"
    }

    /// Hardware-Modell (z.B. "Mac14,14") via sysctl — ohne Berechtigungen.
    static var deviceModel: String {
        var size = 0
        sysctlbyname("hw.model", nil, &size, nil, 0)
        guard size > 0 else { return "unknown" }
        var buf = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.model", &buf, &size, nil, 0)
        return String(cString: buf)
    }
}

// MARK: - Datenmodell

/// Kontext, den EngineController beim Öffnen des Formulars mitgibt.
struct FeedbackDraft {
    var fromError = false
    var errorMessage = ""
    var log = ""
    var episode = ""
}

private struct FeedbackPayload: Encodable {
    let summary: String
    let description: String
    let email: String
    let kind: String            // "bug" | "feedback"
    let source: String          // "manual" | "error"
    let error_message: String
    let app_version: String
    let os_version: String
    let device_model: String
    let episode: String
    let log: String
    let log_truncated: Bool
}

private struct FeedbackResult: Decodable {
    let status: String
    let issue_url: String?
    let number: Int?
}

// MARK: - Service (POST an /api/feedback, siehe brain/Feedback-API.md)

private enum FeedbackService {
    struct SendError: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    static var endpoint: URL? { URL(string: LicenseConfig.apiBase + "/api/feedback") }

    static func send(_ payload: FeedbackPayload) async throws -> FeedbackResult {
        guard let url = endpoint else { throw SendError(message: "Invalid endpoint URL") }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 30
        req.httpBody = try JSONEncoder().encode(payload)

        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
        guard (200..<300).contains(code) else {
            throw SendError(message: String(localized: "Server responded with HTTP \(code)."))
        }
        // Backend liefert idealerweise issue_url/number; fehlt es, gilt es trotzdem als ok.
        return (try? JSONDecoder().decode(FeedbackResult.self, from: data))
            ?? FeedbackResult(status: "ok", issue_url: nil, number: nil)
    }
}

// MARK: - Overlay-Button (immer sichtbar)

struct FeedbackButton: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        Button {
            engine.presentFeedback(fromError: false)
        } label: {
            LucideIcon("message-square-warning", size: 14)
        }
        .buttonStyle(.plain)
        .foregroundStyle(.secondary)
        .help("Feedback / Report a bug")
    }
}

// MARK: - Formular (Sheet)

struct FeedbackView: View {
    @EnvironmentObject var engine: EngineController
    @Environment(\.dismiss) private var dismiss

    private enum Phase: Equatable {
        case editing, sending, success(url: String?, number: Int?), failure(String)
    }

    @State private var summary = ""
    @State private var details = ""
    @State private var email = ""
    @State private var attachLog = true
    @State private var phase: Phase = .editing

    // aus dem Draft übernommen
    @State private var fromError = false
    @State private var errorMessage = ""
    @State private var log = ""
    @State private var episode = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(fromError ? "Report a bug" : "Feedback / Report a bug")
                .font(.title2.bold())

            if case .success(let url, let number) = phase {
                successPanel(url: url, number: number)
            } else {
                form
            }
        }
        .padding(20)
        .frame(width: 480)
        .onAppear(perform: seed)
    }

    // MARK: Formular

    @ViewBuilder
    private var form: some View {
        if fromError && !errorMessage.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                LucideLabel("This error message will be included:", icon: "triangle-alert", size: 11)
                    .font(.caption).foregroundStyle(.brandSecondary)
                Text(errorMessage)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.textBackgroundColor).opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
        }

        TextField("Subject", text: $summary, prompt: Text("Briefly: what happened?"))
            .textFieldStyle(.roundedBorder)

        VStack(alignment: .leading, spacing: 4) {
            Text("Description").font(.caption).foregroundStyle(.secondary)
            TextEditor(text: $details)
                .font(.body)
                .frame(height: 120)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color(.separatorColor), lineWidth: 0.5))
        }

        TextField("Email for follow-up (optional)", text: $email)
            .textFieldStyle(.roundedBorder)

        Toggle(isOn: $attachLog) {
            VStack(alignment: .leading, spacing: 1) {
                Text("Attach analysis log")
                Text("Includes file paths and names from your project.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
        }
        .disabled(log.isEmpty)
        .opacity(log.isEmpty ? 0.5 : 1)

        Text("Included: \(AppVersion.display) · \(SystemInfo.osVersion) · \(SystemInfo.deviceModel)")
            .font(.caption2).foregroundStyle(.tertiary)

        if case .failure(let msg) = phase {
            Text(msg).font(.caption).foregroundStyle(.red)
        }

        HStack {
            Button("Cancel") { dismiss() }
                .keyboardShortcut(.cancelAction)
            if case .failure = phase {
                Button("Copy details") { copyDetails() }
            }
            Spacer()
            Button {
                send()
            } label: {
                if phase == .sending {
                    ProgressView().controlSize(.small)
                } else {
                    Text("Send")
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(!canSend)
            .keyboardShortcut(.defaultAction)
        }
    }

    // MARK: Erfolg

    @ViewBuilder
    private func successPanel(url: String?, number: Int?) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            LucideLabel(number.map { String(localized: "Report #\($0) created — thanks!") } ?? loc("Report sent — thanks!"),
                        icon: "circle-check", size: 15)
                .foregroundStyle(.green)
                .font(.headline)
            if let url, let u = URL(string: url) {
                Link("Open in browser", destination: u)
            }
            HStack {
                Spacer()
                Button("Close") { dismiss() }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    // MARK: Logik

    private var canSend: Bool {
        phase == .editing &&
        !(summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
          details.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    private func seed() {
        let d = engine.feedbackDraft
        fromError = d.fromError
        errorMessage = d.errorMessage
        log = d.log
        episode = d.episode
        attachLog = !d.log.isEmpty
        if fromError && !d.errorMessage.isEmpty && summary.isEmpty {
            summary = "Error: " + String(d.errorMessage.prefix(50))
        }
    }

    private func buildPayload() -> FeedbackPayload {
        var logOut = attachLog ? log : ""
        var truncated = false
        if logOut.count > 100_000 {
            logOut = String(logOut.suffix(100_000))
            truncated = true
        }
        return FeedbackPayload(
            summary: summary.trimmingCharacters(in: .whitespacesAndNewlines),
            description: details,
            email: email.trimmingCharacters(in: .whitespacesAndNewlines),
            kind: fromError ? "bug" : "feedback",
            source: fromError ? "error" : "manual",
            error_message: fromError ? errorMessage : "",
            app_version: AppVersion.display,
            os_version: SystemInfo.osVersion,
            device_model: SystemInfo.deviceModel,
            episode: episode,
            log: logOut,
            log_truncated: truncated
        )
    }

    private func send() {
        guard canSend else { return }
        phase = .sending
        let payload = buildPayload()
        Task {
            do {
                let result = try await FeedbackService.send(payload)
                await MainActor.run { phase = .success(url: result.issue_url, number: result.number) }
            } catch {
                await MainActor.run { phase = .failure("Sending failed: \(error.localizedDescription)") }
            }
        }
    }

    /// Fallback wenn Senden scheitert: kompletten Report als Text in die Zwischenablage.
    private func copyDetails() {
        let p = buildPayload()
        let text = """
        Subject: \(p.summary)

        \(p.description)

        ---
        App: \(p.app_version) · \(p.os_version) · \(p.device_model)
        Episode: \(p.episode)
        Email: \(p.email)
        \(p.source == "error" ? "Error: \(p.error_message)\n" : "")
        Log:
        \(p.log)
        """
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}
