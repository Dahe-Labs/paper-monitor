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
}
