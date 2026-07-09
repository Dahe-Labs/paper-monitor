import Darwin
import Foundation

public struct ArticleNotification: Codable, Equatable, Sendable {
    public let title: String
    public let journal: String
    public let url: String
    public let doi: String
    public let published: String
    public let source: String
    public let matchedTerms: [String]
    public let journalMatch: String?

    public init(
        title: String,
        journal: String,
        url: String,
        doi: String,
        published: String,
        source: String,
        matchedTerms: [String],
        journalMatch: String?
    ) {
        self.title = title
        self.journal = journal
        self.url = url
        self.doi = doi
        self.published = published
        self.source = source
        self.matchedTerms = matchedTerms
        self.journalMatch = journalMatch
    }

    enum CodingKeys: String, CodingKey {
        case title
        case journal
        case url
        case doi
        case published
        case source
        case matchedTerms = "matched_terms"
        case journalMatch = "journal_match"
    }
}

public struct RefreshResult: Codable, Equatable, Sendable {
    public let runId: Int
    public let fetched: Int
    public let matched: Int
    public let newMatches: Int
    public let skipped: Int
    public let dashboardPath: String
    public let articles: [ArticleNotification]
    public let warnings: [String]

    public init(
        runId: Int,
        fetched: Int,
        matched: Int,
        newMatches: Int,
        skipped: Int,
        dashboardPath: String,
        articles: [ArticleNotification],
        warnings: [String] = []
    ) {
        self.runId = runId
        self.fetched = fetched
        self.matched = matched
        self.newMatches = newMatches
        self.skipped = skipped
        self.dashboardPath = dashboardPath
        self.articles = articles
        self.warnings = warnings
    }

    enum CodingKeys: String, CodingKey {
        case runId = "run_id"
        case fetched
        case matched
        case newMatches = "new_matches"
        case skipped
        case dashboardPath = "dashboard_path"
        case articles
        case warnings
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        runId = try container.decode(Int.self, forKey: .runId)
        fetched = try container.decode(Int.self, forKey: .fetched)
        matched = try container.decode(Int.self, forKey: .matched)
        newMatches = try container.decode(Int.self, forKey: .newMatches)
        skipped = try container.decode(Int.self, forKey: .skipped)
        dashboardPath = try container.decode(String.self, forKey: .dashboardPath)
        articles = try container.decode([ArticleNotification].self, forKey: .articles)
        warnings = try container.decodeIfPresent([String].self, forKey: .warnings) ?? []
    }

    public func withWarnings(_ warnings: [String]) -> RefreshResult {
        RefreshResult(
            runId: runId,
            fetched: fetched,
            matched: matched,
            newMatches: newMatches,
            skipped: skipped,
            dashboardPath: dashboardPath,
            articles: articles,
            warnings: warnings
        )
    }
}

public struct DashboardRenderResult: Codable, Equatable, Sendable {
    public let dashboardPath: String

    public init(dashboardPath: String) {
        self.dashboardPath = dashboardPath
    }

    enum CodingKeys: String, CodingKey {
        case dashboardPath = "dashboard_path"
    }
}

public struct KeywordAnalysisRequest: Equatable, Sendable {
    public let dateFrom: String
    public let dateTo: String
    public let sortMode: String
    public let analysisDepth: String
    public let topN: Int
    public let journals: [String]

    public init(dateFrom: String, dateTo: String, sortMode: String, analysisDepth: String = "fast", topN: Int, journals: [String]) {
        self.dateFrom = dateFrom
        self.dateTo = dateTo
        self.sortMode = sortMode
        self.analysisDepth = analysisDepth == "exhaustive" ? "exhaustive" : "fast"
        self.topN = topN
        self.journals = journals
    }
}

public final class PythonBridge: @unchecked Sendable {
    public static let refreshTimeoutSeconds: TimeInterval = 120
    public static let dashboardRenderTimeoutSeconds: TimeInterval = 30
    public static let keywordAnalysisTimeoutSeconds: TimeInterval = 180

    public let appSupportDirectory: URL
    public let pythonPath: String

    public init(appSupportDirectory: URL, pythonPath: String = "/usr/bin/python3") {
        self.appSupportDirectory = appSupportDirectory
        self.pythonPath = pythonPath
    }

    public var configURL: URL {
        appSupportDirectory.appendingPathComponent("config.json")
    }

    public var arguments: [String] {
        [
            "-m",
            "paper_monitor.cli",
            "app-refresh",
            "--config",
            configURL.path,
        ]
    }

    public var renderDashboardArguments: [String] {
        [
            "-m",
            "paper_monitor.cli",
            "render-dashboard",
            "--config",
            configURL.path,
        ]
    }

    public func analyzeArguments(request: KeywordAnalysisRequest) -> [String] {
        var arguments = [
            "-m",
            "paper_monitor.cli",
            "analyze-keywords",
            "--config",
            configURL.path,
            "--date-from",
            request.dateFrom,
            "--date-to",
            request.dateTo,
            "--sort-mode",
            request.sortMode,
            "--analysis-depth",
            request.analysisDepth,
            "--top-n",
            String(request.topN),
        ]
        for journal in request.journals {
            arguments.append("--journal")
            arguments.append(journal)
        }
        return arguments
    }

    public func refresh() throws -> RefreshResult {
        let output = try runPython(arguments: arguments, timeout: Self.refreshTimeoutSeconds)
        let result = try JSONDecoder().decode(RefreshResult.self, from: output.stdout)
        let warnings = result.warnings + Self.warningLines(from: output.stderr)
        return result.withWarnings(warnings)
    }

    public func renderDashboard() throws -> URL {
        let output = try runPython(arguments: renderDashboardArguments, timeout: Self.dashboardRenderTimeoutSeconds)
        let result = try JSONDecoder().decode(DashboardRenderResult.self, from: output.stdout)
        return URL(fileURLWithPath: result.dashboardPath)
    }

    public func analyzeKeywords(request: KeywordAnalysisRequest) throws -> String {
        let output = try runPython(arguments: analyzeArguments(request: request), timeout: Self.keywordAnalysisTimeoutSeconds)
        guard let json = String(data: output.stdout, encoding: .utf8) else {
            throw PythonBridgeError.refreshFailed("Keyword analysis returned non-UTF-8 output")
        }
        return json.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func runPython(arguments: [String], timeout: TimeInterval) throws -> (stdout: Data, stderr: Data) {
        guard FileManager.default.isExecutableFile(atPath: pythonPath) else {
            throw PythonBridgeError.pythonMissing(pythonPath)
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = arguments
        process.currentDirectoryURL = appSupportDirectory
        process.environment = [
            "PYTHONPATH": appSupportDirectory.path,
        ]

        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr

        let outputReader = ProcessPipeReader(fileHandle: stdout.fileHandleForReading)
        let errorReader = ProcessPipeReader(fileHandle: stderr.fileHandleForReading)
        let termination = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in
            termination.signal()
        }

        do {
            try process.run()
            stdout.fileHandleForWriting.closeFile()
            stderr.fileHandleForWriting.closeFile()
        } catch {
            stdout.fileHandleForWriting.closeFile()
            stderr.fileHandleForWriting.closeFile()
            _ = outputReader.data()
            _ = errorReader.data()
            throw error
        }

        if termination.wait(timeout: .now() + timeout) == .timedOut {
            process.terminate()
            if termination.wait(timeout: .now() + 5) == .timedOut {
                process.forceTerminateIfNeeded()
                _ = termination.wait(timeout: .now() + 2)
            }
            _ = outputReader.data()
            _ = errorReader.data()
            throw PythonBridgeError.pythonTimeout(timeout)
        }

        let output = outputReader.data()
        let errorOutput = errorReader.data()

        if process.terminationStatus != 0 {
            let message = String(data: errorOutput, encoding: .utf8) ?? "Python refresh failed"
            throw PythonBridgeError.nonZeroExit(message)
        }

        return (output, errorOutput)
    }

    public static func warningLines(from data: Data) -> [String] {
        guard let text = String(data: data, encoding: .utf8) else {
            return []
        }
        return text
            .split(whereSeparator: \.isNewline)
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { $0.lowercased().hasPrefix("warning:") }
    }
}

public enum PythonBridgeError: Error, Equatable {
    case refreshFailed(String)
    case pythonMissing(String)
    case pythonTimeout(TimeInterval)
    case nonZeroExit(String)
}

extension PythonBridgeError: LocalizedError {
    public var errorDescription: String? {
        switch self {
        case .refreshFailed(let message):
            return message
        case .pythonMissing(let path):
            return "Python executable is missing or not executable: \(path)"
        case .pythonTimeout(let timeout):
            return "Python process timed out after \(Int(timeout)) seconds."
        case .nonZeroExit(let message):
            return message.isEmpty ? "Python process exited with an error." : message
        }
    }
}

private extension Process {
    func forceTerminateIfNeeded() {
        guard isRunning else {
            return
        }
        kill(processIdentifier, SIGKILL)
    }
}

private final class ProcessPipeReader: @unchecked Sendable {
    private let group = DispatchGroup()
    private let lock = NSLock()
    private var collectedData = Data()

    init(fileHandle: FileHandle) {
        group.enter()
        DispatchQueue.global(qos: .utility).async {
            let data = fileHandle.readDataToEndOfFile()
            self.lock.lock()
            self.collectedData = data
            self.lock.unlock()
            self.group.leave()
        }
    }

    func data() -> Data {
        group.wait()
        lock.lock()
        defer { lock.unlock() }
        return collectedData
    }
}
