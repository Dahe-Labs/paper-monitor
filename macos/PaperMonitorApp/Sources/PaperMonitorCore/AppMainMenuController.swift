import AppKit

@MainActor
final class AppMainMenuController: NSObject {
    struct MenuItemSnapshot: Equatable {
        let title: String
        let actionName: String?
    }

    private let mainMenu = NSMenu()
    private let appMenu = NSMenu()
    private let lastRunItem = NSMenuItem(title: "Last Run: never", action: nil, keyEquivalent: "")
    private let lastResultItem = NSMenuItem(title: "Last Result: none", action: nil, keyEquivalent: "")
    private let permissionItem = NSMenuItem(title: "Notification Permission: unknown", action: nil, keyEquivalent: "")
    private let refreshItem = NSMenuItem(title: "Refresh Now", action: #selector(refreshNowAction), keyEquivalent: "r")

    var onOpenDashboard: (() -> Void)?
    var onOpenSettings: (() -> Void)?
    var onRefreshNow: (() -> Void)?
    var onTestNotification: (() -> Void)?
    var onQuit: (() -> Void)?

    override init() {
        super.init()
        buildMenu()
    }

    func install() {
        NSApp.mainMenu = mainMenu
    }

    var menuItemsForTesting: [MenuItemSnapshot] {
        let items = appMenu.items.filter { !$0.isSeparatorItem }
        return [MenuItemSnapshot(title: AppIdentity.displayName, actionName: nil)] + items.map { item in
            MenuItemSnapshot(
                title: item.title,
                actionName: item.action.map(NSStringFromSelector)
            )
        }
    }

    func triggerMenuItemForTesting(title: String) {
        guard let item = appMenu.item(withTitle: title) else {
            return
        }
        appMenu.performActionForItem(at: appMenu.index(of: item))
    }

    private func buildMenu() {
        let appItem = NSMenuItem(title: AppIdentity.displayName, action: nil, keyEquivalent: "")
        appItem.submenu = appMenu
        mainMenu.addItem(appItem)

        addItem("Open Dashboard", action: #selector(openDashboardAction), keyEquivalent: "o")
        addItem("Settings...", action: #selector(openSettingsAction), keyEquivalent: ",")
        refreshItem.target = self
        appMenu.addItem(refreshItem)
        addItem("Test Notification", action: #selector(testNotificationAction), keyEquivalent: "t")
        appMenu.addItem(.separator())
        appMenu.addItem(lastRunItem)
        appMenu.addItem(lastResultItem)
        appMenu.addItem(permissionItem)
        appMenu.addItem(.separator())
        addItem("Quit \(AppIdentity.displayName)", action: #selector(quitAction), keyEquivalent: "q")
    }

    private func addItem(_ title: String, action: Selector, keyEquivalent: String) {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: keyEquivalent)
        item.target = self
        appMenu.addItem(item)
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

    func update(result: RefreshResult) {
        lastRunItem.title = "Last Run: \(DateFormatter.localizedString(from: Date(), dateStyle: .short, timeStyle: .short))"
        lastResultItem.title = RefreshPresentation.resultTitle(for: result)
        refreshItem.isEnabled = true
    }

    func updateRefreshStarted() {
        lastResultItem.title = RefreshPresentation.refreshingResultTitle
        refreshItem.isEnabled = false
    }

    func updateRefreshFailed() {
        lastResultItem.title = RefreshPresentation.failedResultTitle
        refreshItem.isEnabled = true
    }

    func updatePermission(_ text: String) {
        permissionItem.title = RefreshPresentation.permissionTitle(text)
    }
}
