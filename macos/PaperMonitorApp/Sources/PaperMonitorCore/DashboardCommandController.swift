import Foundation
import WebKit

@MainActor
public final class DashboardCommandController: NSObject, WKScriptMessageHandler {
    public nonisolated static let maximumSearchTermLength = 120
    public typealias KeywordAnalysisRunner = @Sendable (KeywordAnalysisRequest) throws -> String
    public typealias RefreshRunner = @Sendable () throws -> RefreshResult

    private let settingsStore: SettingsStore
    private let keywordAnalysisRunner: KeywordAnalysisRunner?
    private let refreshRunner: RefreshRunner?
    private let refreshResultHandler: (@MainActor @Sendable (RefreshResult) -> Void)?
    private var evaluateJavaScript: ((String) -> Void)?
    private var keywordAnalysisTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?

    public init(
        settingsStore: SettingsStore,
        keywordAnalysisRunner: KeywordAnalysisRunner? = nil,
        refreshRunner: RefreshRunner? = nil,
        refreshResultHandler: (@MainActor @Sendable (RefreshResult) -> Void)? = nil,
        evaluateJavaScript: ((String) -> Void)? = nil
    ) {
        self.settingsStore = settingsStore
        self.keywordAnalysisRunner = keywordAnalysisRunner
        self.refreshRunner = refreshRunner
        self.refreshResultHandler = refreshResultHandler
        self.evaluateJavaScript = evaluateJavaScript
    }

    public func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        _ = handle(messageBody: message.body)
    }

    public func setJavaScriptEvaluator(_ evaluateJavaScript: @escaping (String) -> Void) {
        self.evaluateJavaScript = evaluateJavaScript
    }

    @discardableResult
    public func handle(messageBody: Any) -> Bool {
        guard let payload = messageBody as? [String: Any],
              let type = payload["type"] as? String
        else {
            return false
        }

        if type == "addSearchTerm" {
            return handleAddSearchTerm(payload)
        }
        if type == "analyzeKeywords" {
            return handleKeywordAnalysis(payload)
        }
        if type == "refreshNow" {
            return handleRefreshNow()
        }
        return false
    }

    private func handleAddSearchTerm(_ payload: [String: Any]) -> Bool {
        guard let term = payload["term"] as? String,
              let normalizedTerm = Self.normalizedSearchTerm(term)
        else {
            return false
        }
        do {
            _ = try settingsStore.addIncludeTerm(normalizedTerm)
            return true
        } catch {
            NSLog("Paper Monitor dashboard command failed: \(error)")
            return false
        }
    }

    private func handleKeywordAnalysis(_ payload: [String: Any]) -> Bool {
        guard let request = Self.keywordAnalysisRequest(from: payload),
              let keywordAnalysisRunner
        else {
            return false
        }

        if keywordAnalysisTask != nil {
            return true
        }

        keywordAnalysisTask = Task { [weak self, keywordAnalysisRunner, request] in
            defer {
                self?.keywordAnalysisTask = nil
            }
            do {
                let json = try await Task.detached(priority: .userInitiated) {
                    try keywordAnalysisRunner(request)
                }.value
                self?.evaluateJavaScript?(Self.keywordAnalysisCallbackScript(jsonPayload: json))
            } catch {
                self?.evaluateJavaScript?(
                    Self.keywordAnalysisErrorCallbackScript(message: "Crossref analysis failed: \(error)")
                )
            }
        }
        return true
    }

    private func handleRefreshNow() -> Bool {
        guard let refreshRunner else {
            return false
        }
        if refreshTask != nil {
            evaluateJavaScript?(Self.refreshFinishedCallbackScript(ok: false, message: "Already Refreshing"))
            return true
        }

        refreshTask = Task { [weak self, refreshRunner] in
            defer {
                self?.refreshTask = nil
            }
            do {
                let result = try await Task.detached(priority: .userInitiated) {
                    try refreshRunner()
                }.value
                self?.refreshResultHandler?(result)
                self?.evaluateJavaScript?(Self.refreshFinishedCallbackScript(ok: true, message: ""))
            } catch {
                self?.evaluateJavaScript?(
                    Self.refreshFinishedCallbackScript(ok: false, message: "Refresh failed")
                )
            }
        }
        return true
    }

    public nonisolated static func keywordAnalysisRequest(from payload: [String: Any]) -> KeywordAnalysisRequest? {
        guard payload["type"] as? String == "analyzeKeywords",
              let dateFrom = normalizedSearchTerm(payload["date_from"] as? String ?? ""),
              let dateTo = normalizedSearchTerm(payload["date_to"] as? String ?? "")
        else {
            return nil
        }
        let sortMode = normalizedSortMode(payload["sort_mode"] as? String)
        let analysisDepth = normalizedAnalysisDepth(payload["analysis_depth"] as? String)
        let topN = positiveInt(payload["top_n"]) ?? 30
        let journals = (payload["journals"] as? [String] ?? [])
            .compactMap { normalizedSearchTerm($0) }
        return KeywordAnalysisRequest(
            dateFrom: dateFrom,
            dateTo: dateTo,
            sortMode: sortMode,
            analysisDepth: analysisDepth,
            topN: topN,
            journals: journals
        )
    }

    public nonisolated static func keywordAnalysisCallbackScript(jsonPayload: String) -> String {
        "window.paperMonitorReceiveKeywordAnalysis(\(jsonPayload));"
    }

    public nonisolated static func keywordAnalysisErrorCallbackScript(message: String) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: ["error": message], options: [])) ?? Data()
        let json = String(data: data, encoding: .utf8) ?? #"{"error":"Keyword analysis failed"}"#
        return keywordAnalysisCallbackScript(jsonPayload: json)
    }

    public nonisolated static func refreshFinishedCallbackScript(ok: Bool, message: String) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: [ok, message], options: [])) ?? Data()
        let json = String(data: data, encoding: .utf8) ?? #"[false,"Refresh failed"]"#
        return "window.paperMonitorRefreshFinished.apply(window, \(json));"
    }

    public nonisolated static func normalizedSearchTerm(_ term: String) -> String? {
        let whitespace = CharacterSet.whitespacesAndNewlines
        for scalar in term.unicodeScalars where CharacterSet.controlCharacters.contains(scalar) {
            if !whitespace.contains(scalar) {
                return nil
            }
        }

        let normalized = term
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
        guard !normalized.isEmpty,
              normalized.count <= maximumSearchTermLength
        else {
            return nil
        }
        return normalized
    }

    private nonisolated static func normalizedSortMode(_ value: String?) -> String {
        let sortMode = normalizedSearchTerm(value ?? "") ?? "time"
        if ["time", "impact_factor", "relevance"].contains(sortMode) {
            return sortMode
        }
        return "time"
    }

    private nonisolated static func normalizedAnalysisDepth(_ value: String?) -> String {
        let depth = normalizedSearchTerm(value ?? "") ?? "fast"
        return depth == "exhaustive" ? "exhaustive" : "fast"
    }

    private nonisolated static func positiveInt(_ value: Any?) -> Int? {
        if let intValue = value as? Int, intValue > 0 {
            return intValue
        }
        if let number = value as? NSNumber, number.intValue > 0 {
            return number.intValue
        }
        if let string = value as? String,
           let intValue = Int(string),
           intValue > 0 {
            return intValue
        }
        return nil
    }
}
