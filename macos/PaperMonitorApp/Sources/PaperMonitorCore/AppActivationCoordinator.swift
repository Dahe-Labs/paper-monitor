import AppKit
import Foundation

@MainActor
public final class AppActivationCoordinator {
    public nonisolated static let openDashboardNotificationName = Notification.Name("com.local.paper-monitor.open-dashboard")
    public nonisolated static let testNotificationName = Notification.Name("com.local.paper-monitor.test-notification")

    private let bundleIdentifier: String
    private let processIdentifier: pid_t
    private let notificationCenter: DistributedNotificationCenter

    public init(
        bundleIdentifier: String = Bundle.main.bundleIdentifier ?? "com.local.paper-monitor.app",
        processIdentifier: pid_t = ProcessInfo.processInfo.processIdentifier,
        notificationCenter: DistributedNotificationCenter = .default()
    ) {
        self.bundleIdentifier = bundleIdentifier
        self.processIdentifier = processIdentifier
        self.notificationCenter = notificationCenter
    }

    public func isDuplicateInstance() -> Bool {
        NSRunningApplication.runningApplications(withBundleIdentifier: bundleIdentifier)
            .contains { $0.processIdentifier != processIdentifier }
    }

    public func requestOpenDashboardFromRunningInstance() {
        notificationCenter.postNotificationName(Self.openDashboardNotificationName, object: nil)
    }

    public func requestTestNotificationFromRunningInstance() {
        notificationCenter.postNotificationName(Self.testNotificationName, object: nil)
    }

    public func observeOpenDashboard(_ handler: @escaping @Sendable () -> Void) {
        notificationCenter.addObserver(
            forName: Self.openDashboardNotificationName,
            object: nil,
            queue: .main
        ) { _ in
            handler()
        }
    }

    public func observeTestNotification(_ handler: @escaping @Sendable () -> Void) {
        notificationCenter.addObserver(
            forName: Self.testNotificationName,
            object: nil,
            queue: .main
        ) { _ in
            handler()
        }
    }
}
