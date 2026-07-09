import Foundation

public struct AppLaunchOptions: Equatable, Sendable {
    public let postTestNotificationOnLaunch: Bool
    public let launchReason: LaunchReason

    public init(arguments: [String] = CommandLine.arguments) {
        postTestNotificationOnLaunch = arguments.contains("--test-notification")
        launchReason = arguments.contains("--login-startup") ? .loginStartup : .processLaunch
    }
}
