import Foundation

public struct RefreshRunGate: Equatable, Sendable {
    public private(set) var isRefreshing: Bool

    public init(isRefreshing: Bool = false) {
        self.isRefreshing = isRefreshing
    }

    public mutating func begin() -> Bool {
        if isRefreshing {
            return false
        }
        isRefreshing = true
        return true
    }

    public mutating func finish() {
        isRefreshing = false
    }
}

public enum RefreshPresentation {
    public static let refreshingResultTitle = "Last Result: Refreshing..."
    public static let failedResultTitle = "Last Result: Refresh failed"

    public static func resultTitle(for result: RefreshResult) -> String {
        var title = "Last Result: Fetched \(result.fetched) · Matched \(result.matched) · New \(result.newMatches)"
        if !result.warnings.isEmpty {
            title += " · Warnings \(result.warnings.count)"
        }
        return title
    }

    public static func permissionTitle(_ text: String) -> String {
        "Notification Permission: \(text)"
    }

    public static func failedResultTitle(message: String?) -> String {
        guard let message, !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return failedResultTitle
        }
        return "Last Result: Refresh failed - \(shortMessage(message))"
    }

    private static func shortMessage(_ value: String, limit: Int = 120) -> String {
        let compact = value.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        if compact.count <= limit {
            return compact
        }
        let endIndex = compact.index(compact.startIndex, offsetBy: max(0, limit - 1))
        return String(compact[..<endIndex]).trimmingCharacters(in: .whitespacesAndNewlines) + "..."
    }
}
