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
    private lazy var notifications = NotificationController(openDashboard: { [weak self] in
        self?.openDashboard()
    })
    private let appMainMenuController = AppMainMenuController()
    private lazy var dashboardWindow = DashboardWindowController(commandController: dashboardCommandController)
    private lazy var dashboardCommandController = DashboardCommandController(
        settingsStore: settingsStore,
        keywordAnalysisRunner: { [bridge] request in
            try bridge.analyzeKeywords(request: request)
        },
        refreshRunner: { [bridge] in
            try bridge.refresh()
        },
        refreshResultHandler: { [weak self] result in
            self?.handle(result: result)
        }
    )
    private lazy var journalCatalog = loadJournalCatalog()
    private var settingsWindow: SettingsWindowController?
    private let launchOptions: AppLaunchOptions
    private let refreshScheduler = RefreshScheduler()
    private var lastScheduledSettings: AppRefreshSettings.Schedule?
    private var lastDashboardURL: URL?
    private var refreshGate = RefreshRunGate()
    private var statusItem: NSStatusItem?
    private var suppressNextNotifications = false

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
        configureMainApplicationMenu()
        do {
            try BundledRuntimeInstaller.installFromMainBundle(appSupportDirectory: appSupportDirectory)
        } catch {
            appMainMenuController.updateRefreshFailed(message: "Runtime install failed: \(error.localizedDescription)")
        }
        let runtimeSettings = currentRuntimeSettings()
        suppressNextNotifications = false
        applyRuntimeSettings(runtimeSettings, syncLaunchAtLogin: runtimeSettings.startupEnabled)
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
        scheduleTimer()
        requestNotificationAuthorizationThenRefresh(
            postTestNotificationAfterAuthorization: launchOptions.postTestNotificationOnLaunch,
            runtimeSettings: runtimeSettings,
            launchReason: launchOptions.launchReason
        )
    }

    public func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if flag {
            dashboardWindow.show()
        } else {
            openDashboard()
        }
        return true
    }

    public func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        AppLifecyclePolicy.shouldTerminateAfterLastWindowClosed
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

    private func requestNotificationAuthorizationThenRefresh(
        postTestNotificationAfterAuthorization: Bool = false,
        runtimeSettings: RuntimeAppSettings,
        launchReason: LaunchReason
    ) {
        if launchReason == .loginStartup {
            runLaunchRefreshIfNeeded(runtimeSettings: runtimeSettings, launchReason: launchReason)
            return
        }
        guard runtimeSettings.notificationsEnabled else {
            updateNotificationPermission(.denied)
            runLaunchRefreshIfNeeded(runtimeSettings: runtimeSettings, launchReason: launchReason)
            return
        }
        notifications.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.updateNotificationPermission(status)
                self.runLaunchRefreshIfNeeded(runtimeSettings: runtimeSettings, launchReason: launchReason)
                if postTestNotificationAfterAuthorization {
                    self.postTestNotification()
                }
            }
        }
    }

    private func runLaunchRefreshIfNeeded(runtimeSettings: RuntimeAppSettings, launchReason: LaunchReason) {
        guard LaunchRefreshPolicy.shouldRefreshOnLaunch(
            runtimeSettings: runtimeSettings,
            reason: launchReason
        ) else {
            return
        }
        refreshNow(reason: launchReason, notificationRuntimeSettings: runtimeSettings)
    }

    private func updateNotificationPermission(_ status: UNAuthorizationStatus) {
        appMainMenuController.updatePermission(Self.permissionText(status))
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
        rescheduleTimer(settings: AppRefreshSettings.load(from: bridge.configURL))
    }

    private func rescheduleTimer(settings: AppRefreshSettings.Schedule) {
        refreshScheduler.schedule(interval: settings.intervalSeconds, startTime: settings.refreshStartTime) { [weak self] in
            self?.refreshNow(reason: .scheduledRefresh)
        }
        lastScheduledSettings = settings
    }

    private func handleSettingsChange(_ settings: AppSettings) -> Bool {
        do {
            try settingsStore.save(settings)
            applyRuntimeSettings(settings.runtime, syncLaunchAtLogin: true)
            if RefreshSchedulePolicy.shouldReschedule(
                lastScheduledSettings: lastScheduledSettings,
                settings: settings
            ) {
                rescheduleTimer(settings: AppRefreshSettings.Schedule(
                    intervalSeconds: TimeInterval(settings.intervalSeconds),
                    refreshStartTime: settings.refreshStartTime
                ))
            }
            return true
        } catch {
            appMainMenuController.updateRefreshFailed(message: error.localizedDescription)
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
                appMainMenuController.updateRefreshFailed(message: "Settings save failed")
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
            appMainMenuController.updateRefreshFailed(message: error.localizedDescription)
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

    private func refreshNow(
        reason: LaunchReason = .manualRefresh,
        notificationRuntimeSettings: RuntimeAppSettings? = nil
    ) {
        guard refreshGate.begin() else {
            return
        }
        let notificationSettings = notificationRuntimeSettings ?? currentRuntimeSettings()
        if LaunchRefreshPolicy.shouldSuppressNotifications(
            runtimeSettings: notificationSettings,
            reason: reason
        ) {
            suppressNextNotifications = true
        }
        appMainMenuController.updateRefreshStarted()
        let bridge = self.bridge
        DispatchQueue.global(qos: .background).async { [weak self] in
            do {
                let result = try bridge.refresh()
                DispatchQueue.main.async {
                    self?.handleRefreshSuccess(result)
                }
            } catch {
                DispatchQueue.main.async {
                    self?.handleRefreshFailure(error)
                }
            }
        }
    }

    private func handleRefreshSuccess(_ result: RefreshResult) {
        refreshGate.finish()
        handle(result: result)
    }

    private func handleRefreshFailure(_ error: Error) {
        refreshGate.finish()
        appMainMenuController.updateRefreshFailed(message: error.localizedDescription)
    }

    private func handle(result: RefreshResult) {
        appMainMenuController.update(result: result)
        let dashboardURL = URL(fileURLWithPath: result.dashboardPath)
        lastDashboardURL = dashboardURL
        if shouldPostNotifications() {
            for article in result.articles {
                notifications.post(article: article, dashboardURL: dashboardURL)
            }
        }
        suppressNextNotifications = false
    }

    private func postTestNotification() {
        let dashboardURL = lastDashboardURL ?? appSupportDirectory
            .appendingPathComponent("work/paper-monitor/dashboard/latest.html")
        notifications.post(article: NotificationController.testArticle(), dashboardURL: dashboardURL)
    }

    private func openDashboard() {
        let fallbackURL = lastDashboardURL ?? appSupportDirectory
            .appendingPathComponent("work/paper-monitor/dashboard/latest.html")
        let dashboardURL: URL
        do {
            dashboardURL = try bridge.renderDashboard()
            lastDashboardURL = dashboardURL
        } catch {
            appMainMenuController.updateRefreshFailed(message: "Dashboard render failed: \(error.localizedDescription)")
            dashboardURL = fallbackURL
        }
        dashboardWindow.load(fileURL: dashboardURL)
    }

    private func currentRuntimeSettings() -> RuntimeAppSettings {
        (try? settingsStore.load().runtime) ?? .default
    }

    private func shouldPostNotifications() -> Bool {
        let runtime = currentRuntimeSettings()
        guard runtime.notificationsEnabled else {
            return false
        }
        if suppressNextNotifications {
            return false
        }
        return true
    }

    private func applyRuntimeSettings(_ runtime: RuntimeAppSettings, syncLaunchAtLogin: Bool) {
        if syncLaunchAtLogin {
            do {
                try LaunchAtLoginController.setEnabled(runtime.startupEnabled)
            } catch {
                appMainMenuController.updateRefreshFailed(message: "Launch at login failed: \(error.localizedDescription)")
            }
        }
        configureStatusItem(visible: runtime.showTrayIcon)
    }

    private func configureStatusItem(visible: Bool) {
        if !visible {
            if let statusItem {
                NSStatusBar.system.removeStatusItem(statusItem)
            }
            statusItem = nil
            return
        }
        if statusItem == nil {
            statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
            statusItem?.button?.title = "PM"
            statusItem?.button?.target = self
            statusItem?.button?.action = #selector(statusItemClicked)
            statusItem?.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
    }

    private func statusMenu() -> NSMenu {
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Open Dashboard", action: #selector(statusOpenDashboard), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Settings...", action: #selector(statusOpenSettings), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Refresh Now", action: #selector(statusRefreshNow), keyEquivalent: ""))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit \(AppIdentity.displayName)", action: #selector(statusQuit), keyEquivalent: ""))
        for item in menu.items {
            item.target = self
        }
        return menu
    }

    @objc private func statusOpenDashboard() {
        openDashboard()
    }

    @objc private func statusItemClicked() {
        let event = NSApp.currentEvent
        switch StatusItemClickPolicy.action(for: event?.type, clickCount: event?.clickCount ?? 1) {
        case .openDashboard:
            openDashboard()
        case .showMenu:
            showStatusMenu()
        }
    }

    private func showStatusMenu() {
        guard let button = statusItem?.button else {
            return
        }
        statusMenu().popUp(
            positioning: nil,
            at: NSPoint(x: 0, y: button.bounds.height),
            in: button
        )
    }

    @objc private func statusOpenSettings() {
        openSettings()
    }

    @objc private func statusRefreshNow() {
        refreshNow(reason: .manualRefresh)
    }

    @objc private func statusQuit() {
        NSApp.terminate(nil)
    }
}

enum AppLifecyclePolicy {
    static let shouldTerminateAfterLastWindowClosed = false
}
