import Foundation

public enum AppRefreshSettings {
    public static let defaultIntervalSeconds: TimeInterval = 43_200

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
}
