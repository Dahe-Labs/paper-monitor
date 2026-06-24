import Foundation

public struct AppLaunchOptions: Equatable, Sendable {
    public let postTestNotificationOnLaunch: Bool

    public init(arguments: [String] = CommandLine.arguments) {
        postTestNotificationOnLaunch = arguments.contains("--test-notification")
    }
}
