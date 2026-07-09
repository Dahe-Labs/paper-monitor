import Foundation

public enum AppRefreshSettings {
    public struct Schedule: Equatable, Sendable {
        public var intervalSeconds: TimeInterval
        public var refreshStartTime: String

        public init(intervalSeconds: TimeInterval, refreshStartTime: String = "") {
            self.intervalSeconds = intervalSeconds
            self.refreshStartTime = refreshStartTime
        }
    }

    public static let defaultIntervalSeconds: TimeInterval = 43_200

    public static func load(from configURL: URL) -> Schedule {
        guard let data = try? Data(contentsOf: configURL) else {
            return Schedule(intervalSeconds: defaultIntervalSeconds)
        }
        return Schedule(
            intervalSeconds: intervalSeconds(from: data),
            refreshStartTime: refreshStartTime(from: data)
        )
    }

    public static func loadIntervalSeconds(from configURL: URL) -> TimeInterval {
        guard let data = try? Data(contentsOf: configURL) else {
            return defaultIntervalSeconds
        }
        return intervalSeconds(from: data)
    }

    public static func intervalSeconds(from data: Data) -> TimeInterval {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rawValue = payload["interval_seconds"]
        else {
            return defaultIntervalSeconds
        }

        let interval: TimeInterval?
        if let number = rawValue as? NSNumber {
            interval = number.doubleValue
        } else if let string = rawValue as? String {
            interval = TimeInterval(string)
        } else {
            interval = nil
        }

        guard let interval, interval > 0 else {
            return defaultIntervalSeconds
        }
        return interval
    }

    public static func refreshStartTime(from data: Data) -> String {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let value = payload["refresh_start_time"]
        else {
            return ""
        }
        return normalizedRefreshStartTime(value) ?? ""
    }

    public static func normalizedRefreshStartTime(_ value: Any?) -> String? {
        let text = String(describing: value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            return ""
        }
        let parts = text.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2,
              let hour = Int(parts[0]),
              let minute = Int(parts[1]),
              (0...23).contains(hour),
              (0...59).contains(minute)
        else {
            return nil
        }
        return String(format: "%02d:%02d", hour, minute)
    }
}
