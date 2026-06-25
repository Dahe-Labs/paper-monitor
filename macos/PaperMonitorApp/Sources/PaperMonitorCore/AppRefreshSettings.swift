import Foundation

public struct RefreshScheduleSettings: Equatable, Sendable {
    public var intervalSeconds: TimeInterval
    public var startTime: String?

    public init(intervalSeconds: TimeInterval, startTime: String?) {
        self.intervalSeconds = intervalSeconds
        self.startTime = AppRefreshSettings.normalizedStartTime(startTime)
    }
}

public enum AppRefreshSettings {
    public static let defaultIntervalSeconds: TimeInterval = 43_200

    public static func loadIntervalSeconds(from configURL: URL) -> TimeInterval {
        guard let data = try? Data(contentsOf: configURL) else {
            return defaultIntervalSeconds
        }
        return intervalSeconds(from: data)
    }

    public static func loadSchedule(from configURL: URL) -> RefreshScheduleSettings {
        guard let data = try? Data(contentsOf: configURL) else {
            return RefreshScheduleSettings(intervalSeconds: defaultIntervalSeconds, startTime: nil)
        }
        return schedule(from: data)
    }

    public static func schedule(from data: Data) -> RefreshScheduleSettings {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return RefreshScheduleSettings(intervalSeconds: defaultIntervalSeconds, startTime: nil)
        }
        return RefreshScheduleSettings(
            intervalSeconds: intervalSeconds(from: data),
            startTime: normalizedStartTime(payload["refresh_start_time"] as? String)
        )
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

    public static func normalizedStartTime(_ value: String?) -> String? {
        guard let value else {
            return nil
        }
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            return nil
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
