import Foundation

public enum EnglishDateFormatter {
    private static func formatter(dateFormat: String) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = dateFormat
        return formatter
    }

    public static func compactDate(_ date: Date) -> String {
        formatter(dateFormat: "MMM d, yyyy").string(from: date)
    }

    public static func detailDate(_ date: Date) -> String {
        formatter(dateFormat: "MMMM d, yyyy").string(from: date)
    }

    public static func compactDateTime(_ date: Date) -> String {
        formatter(dateFormat: "MMM d, yyyy, h:mm a").string(from: date)
    }
}
