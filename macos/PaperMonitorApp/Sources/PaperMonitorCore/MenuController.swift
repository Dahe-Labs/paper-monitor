import AppKit

@MainActor
public final class MenuController: NSObject {
    struct MenuItemSnapshot: Equatable {
        let title: String
        let keyEquivalent: String
        let actionName: String?
    }

    struct StatusItemSnapshot: Equatable {
        let title: String
        let hasImage: Bool
        let isVisible: Bool
    }

    private let statusItem: NSStatusItem
    private let menu = NSMenu()
    private let lastRunItem = NSMenuItem(title: "Last Run: never", action: nil, keyEquivalent: "")
    private let lastResultItem = NSMenuItem(title: "Last Result: none", action: nil, keyEquivalent: "")
    private let permissionItem = NSMenuItem(title: "Notification Permission: unknown", action: nil, keyEquivalent: "")
    private let refreshItem = NSMenuItem(title: "Refresh Now", action: #selector(refreshNowAction), keyEquivalent: "r")

    public var onOpenDashboard: (() -> Void)?
    public var onOpenSettings: (() -> Void)?
    public var onRefreshNow: (() -> Void)?
    public var onTestNotification: (() -> Void)?
    public var onQuit: (() -> Void)?

    public init(
        presentation: MenuBarPresentation = .default,
        iconLoader: MenuBarIconLoader = MenuBarIconLoader()
    ) {
        statusItem = NSStatusBar.system.statusItem(withLength: presentation.length)
        super.init()
        statusItem.autosaveName = AppIdentity.menuBarAutosaveName
        statusItem.isVisible = true
        statusItem.button?.title = presentation.title
        statusItem.button?.toolTip = presentation.toolTip
        if let icon = iconLoader.image(for: presentation) {
            statusItem.button?.image = icon
            statusItem.button?.imagePosition = presentation.title.isEmpty ? .imageOnly : .imageLeft
            statusItem.button?.imageScaling = .scaleProportionallyDown
        } else if presentation.title.isEmpty {
            statusItem.button?.title = AppIdentity.menuBarShortTitle
        }
        menu.addItem(NSMenuItem(title: AppIdentity.displayName, action: nil, keyEquivalent: ""))
        menu.addItem(.separator())
        menu.addItem(lastRunItem)
        menu.addItem(lastResultItem)
        menu.addItem(permissionItem)
        menu.addItem(.separator())

        let openDashboard = NSMenuItem(title: "Open Dashboard", action: #selector(openDashboardAction), keyEquivalent: "o")
        openDashboard.target = self
        menu.addItem(openDashboard)

        let settings = NSMenuItem(title: "Settings...", action: #selector(openSettingsAction), keyEquivalent: ",")
        settings.target = self
        menu.addItem(settings)

        refreshItem.target = self
        menu.addItem(refreshItem)

        let testNotification = NSMenuItem(title: "Test Notification", action: #selector(testNotificationAction), keyEquivalent: "t")
        testNotification.target = self
        menu.addItem(testNotification)

        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit", action: #selector(quitAction), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)

        statusItem.menu = menu
    }

    var menuItemsForTesting: [MenuItemSnapshot] {
        menu.items.map { item in
            MenuItemSnapshot(
                title: item.title,
                keyEquivalent: item.keyEquivalent,
                actionName: item.action.map(NSStringFromSelector)
            )
        }
    }

    var statusItemSnapshotForTesting: StatusItemSnapshot {
        StatusItemSnapshot(
            title: statusItem.button?.title ?? "",
            hasImage: statusItem.button?.image != nil,
            isVisible: statusItem.isVisible
        )
    }

    var statusItemAutosaveNameForTesting: String? {
        statusItem.autosaveName
    }

    func triggerMenuItemForTesting(title: String) {
        guard let item = menu.item(withTitle: title) else {
            return
        }
        menu.performActionForItem(at: menu.index(of: item))
    }

    public func update(result: RefreshResult) {
        lastRunItem.title = "Last Run: \(DateFormatter.localizedString(from: Date(), dateStyle: .short, timeStyle: .short))"
        lastResultItem.title = RefreshPresentation.resultTitle(for: result)
        refreshItem.isEnabled = true
    }

    public func updateRefreshStarted() {
        lastResultItem.title = RefreshPresentation.refreshingResultTitle
        refreshItem.isEnabled = false
    }

    public func updateRefreshFailed() {
        lastResultItem.title = RefreshPresentation.failedResultTitle
        refreshItem.isEnabled = true
    }

    public func updatePermission(_ text: String) {
        permissionItem.title = RefreshPresentation.permissionTitle(text)
    }

    @objc private func openDashboardAction() {
        onOpenDashboard?()
    }

    @objc private func openSettingsAction() {
        onOpenSettings?()
    }

    @objc private func refreshNowAction() {
        onRefreshNow?()
    }

    @objc private func testNotificationAction() {
        onTestNotification?()
    }

    @objc private func quitAction() {
        onQuit?()
    }
}
