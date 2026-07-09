import AppKit
import Foundation

public enum LaunchReason: String, Equatable, Sendable {
    case processLaunch = "process_launch"
    case loginStartup = "login_startup"
    case manualRefresh = "manual_refresh"
    case scheduledRefresh = "scheduled_refresh"
}

public enum LaunchRefreshPolicy {
    public static func shouldRefreshOnLaunch(
        runtimeSettings: RuntimeAppSettings,
        reason: LaunchReason
    ) -> Bool {
        switch reason {
        case .processLaunch, .loginStartup:
            return runtimeSettings.refreshOnLaunch
        case .manualRefresh, .scheduledRefresh:
            return false
        }
    }

    public static func shouldSuppressNotifications(
        runtimeSettings: RuntimeAppSettings,
        reason: LaunchReason
    ) -> Bool {
        reason == .loginStartup && runtimeSettings.silentStartupNotifications
    }

    public static func shouldOpenDashboardOnLaunch(reason _: LaunchReason) -> Bool {
        false
    }
}

public enum LaunchPresentationPolicy {
    public static func activationPolicy(for reason: LaunchReason) -> NSApplication.ActivationPolicy {
        switch reason {
        case .loginStartup:
            return .accessory
        case .processLaunch, .manualRefresh, .scheduledRefresh:
            return .regular
        }
    }
}
