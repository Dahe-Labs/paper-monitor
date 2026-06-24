import Foundation

public enum DashboardNavigationPolicy {
    public static func externalURLToOpen(
        for url: URL?,
        isUserClick: Bool,
        targetFrameIsMissing: Bool
    ) -> URL? {
        guard let url,
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme)
        else {
            return nil
        }

        return isUserClick || targetFrameIsMissing ? url : nil
    }
}
