import AppKit
import Foundation
import UserNotifications

@MainActor
public final class AppDelegate: NSObject, NSApplicationDelegate {
    private let appSupportDirectory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/PaperMonitor")
    private lazy var bridge = PythonBridge(appSupportDirectory: appSupportDirectory)
    private lazy var settingsStore = SettingsStore(configURL: bridge.configURL)
    private let activationCoordinator = AppActivationCoordinator()
    private let notifications = NotificationController()
    private let menuController = MenuController()
    private let appMainMenuController = AppMainMenuController()
    private lazy var dashboardWindow = DashboardWindowController(commandController: dashboardCommandController)
    private lazy var dashboardCommandController = DashboardCommandController(
        settingsStore: settingsStore,
        keywordAnalysisRunner: { [bridge] request in
            try bridge.analyzeKeywords(request: request)
        }
    )
    private lazy var journalCatalog = loadJournalCatalog()
    private var settingsWindow: SettingsWindowController?
    private let launchOptions: AppLaunchOptions
    private let refreshScheduler = RefreshScheduler()
    private var lastScheduledInterval: TimeInterval?
    private var lastDashboardURL: URL?
    private var refreshGate = RefreshRunGate()

    public init(launchOptions: AppLaunchOptions = AppLaunchOptions()) {
        self.launchOptions = launchOptions
        super.init()
    }

    public func applicationDidFinishLaunching(_ notification: Notification) {
        if activationCoordinator.isDuplicateInstance() {
            if launchOptions.postTestNotificationOnLaunch {
                activationCoordinator.requestTestNotificationFromRunningInstance()
            } else {
                activationCoordinator.requestOpenDashboardFromRunningInstance()
            }
            NSApp.terminate(nil)
            return
        }
        BundledRuntimeInstaller.installFromMainBundle(appSupportDirectory: appSupportDirectory)
        activationCoordinator.observeOpenDashboard { [weak self] in
            Task { @MainActor in
                self?.openDashboard()
            }
        }
        activationCoordinator.observeTestNotification { [weak self] in
            Task { @MainActor in
                self?.postTestNotification()
            }
        }
        configureMainApplicationMenu()
        configureMenu()
        scheduleTimer()
        requestNotificationAuthorizationThenRefresh(
            postTestNotificationAfterAuthorization: launchOptions.postTestNotificationOnLaunch
        )
    }

    public func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openDashboard()
        return true
    }

    private func configureMainApplicationMenu() {
        appMainMenuController.onOpenDashboard = { [weak self] in
            self?.openDashboard()
        }
        appMainMenuController.onOpenSettings = { [weak self] in
            self?.openSettings()
        }
        appMainMenuController.onRefreshNow = { [weak self] in
            self?.refreshNow()
        }
        appMainMenuController.onTestNotification = { [weak self] in
            self?.postTestNotification()
        }
        appMainMenuController.onQuit = {
            NSApp.terminate(nil)
        }
        appMainMenuController.install()
    }

    private func configureMenu() {
        menuController.onOpenDashboard = { [weak self] in
            self?.openDashboard()
        }
        menuController.onOpenSettings = { [weak self] in
            self?.openSettings()
        }
        menuController.onRefreshNow = { [weak self] in
            self?.refreshNow()
        }
        menuController.onTestNotification = { [weak self] in
            self?.postTestNotification()
        }
        menuController.onQuit = {
            NSApp.terminate(nil)
        }
        UNUserNotificationCenter.current().getNotificationSettings { [weak self] settings in
            let status = settings.authorizationStatus
            DispatchQueue.main.async {
                self?.updateNotificationPermission(status)
            }
        }
    }

    private func requestNotificationAuthorizationThenRefresh(postTestNotificationAfterAuthorization: Bool = false) {
        notifications.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                self?.updateNotificationPermission(status)
                self?.refreshNow()
                if postTestNotificationAfterAuthorization {
                    self?.postTestNotification()
                }
            }
        }
    }

    private func updateNotificationPermission(_ status: UNAuthorizationStatus) {
        menuController.updatePermission(Self.permissionText(status))
    }

    private static func permissionText(_ status: UNAuthorizationStatus) -> String {
        switch status {
        case .authorized:
            return "Granted"
        case .denied:
            return "Denied"
        case .notDetermined:
            return "Not Determined"
        case .provisional:
            return "Provisional"
        case .ephemeral:
            return "Ephemeral"
        @unknown default:
            return "Unknown"
        }
    }

    private func scheduleTimer() {
        let interval = AppRefreshSettings.loadIntervalSeconds(from: bridge.configURL)
        rescheduleTimer(interval: interval)
    }

    private func rescheduleTimer(interval: TimeInterval) {
        refreshScheduler.schedule(interval: interval) { [weak self] in
            self?.refreshNow()
        }
        lastScheduledInterval = interval
    }

    private func handleSettingsChange(_ settings: AppSettings) -> Bool {
        do {
            try settingsStore.save(settings)
            if RefreshSchedulePolicy.shouldReschedule(
                lastScheduledInterval: lastScheduledInterval,
                settingsIntervalSeconds: settings.intervalSeconds
            ) {
                rescheduleTimer(interval: TimeInterval(settings.intervalSeconds))
            }
            return true
        } catch {
            menuController.updateRefreshFailed()
            return false
        }
    }

    private func openSettings() {
        if let existingWindow = settingsWindow?.window, existingWindow.isVisible {
            settingsWindow?.show()
            return
        }

        if let existingController = settingsWindow {
            guard existingController.flushPendingChanges() else {
                menuController.updateRefreshFailed()
                return
            }
            existingController.close()
            settingsWindow = nil
        }

        let settings: AppSettings
        do {
            settings = try SettingsEditorLoadPolicy.settingsForEditor(
                load: { try settingsStore.load() },
                catalog: journalCatalog
            )
        } catch {
            menuController.updateRefreshFailed()
            return
        }

        let controller = SettingsWindowController(
            settings: settings,
            journalCatalog: journalCatalog,
            onSettingsChange: { [weak self] settings in
                self?.handleSettingsChange(settings) ?? false
            }
        )
        settingsWindow = controller
        controller.show()
    }

    private func loadJournalCatalog() -> JournalCatalog? {
        let currentDirectory = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let candidateURLs = [
            bridge.appSupportDirectory.appendingPathComponent("journal_metrics.json"),
            currentDirectory.appendingPathComponent("journal_metrics.json"),
            currentDirectory.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("journal_metrics.json"),
        ]

        for url in candidateURLs {
            if let catalog = try? JournalCatalog.load(from: url) {
                return catalog
            }
        }
        return nil
    }

    private func refreshNow() {
        guard refreshGate.begin() else {
            return
        }
        menuController.updateRefreshStarted()
        let bridge = self.bridge
        DispatchQueue.global(qos: .background).async { [weak self] in
            do {
                let result = try bridge.refresh()
                DispatchQueue.main.async {
                    self?.handleRefreshSuccess(result)
                }
            } catch {
                DispatchQueue.main.async {
                    self?.handleRefreshFailure()
                }
            }
        }
    }

    private func handleRefreshSuccess(_ result: RefreshResult) {
        refreshGate.finish()
        handle(result: result)
    }

    private func handleRefreshFailure() {
        refreshGate.finish()
        menuController.updateRefreshFailed()
    }

    private func handle(result: RefreshResult) {
        menuController.update(result: result)
        let dashboardURL = URL(fileURLWithPath: result.dashboardPath)
        lastDashboardURL = dashboardURL
        for article in result.articles {
            notifications.post(article: article, dashboardURL: dashboardURL)
        }
    }

    private func postTestNotification() {
        let dashboardURL = lastDashboardURL ?? appSupportDirectory
            .appendingPathComponent("work/paper-monitor/dashboard/latest.html")
        notifications.post(article: NotificationController.testArticle(), dashboardURL: dashboardURL)
    }

    private func openDashboard() {
        let dashboardURL = lastDashboardURL ?? appSupportDirectory
            .appendingPathComponent("work/paper-monitor/dashboard/latest.html")
        dashboardWindow.load(fileURL: dashboardURL)
    }
}
