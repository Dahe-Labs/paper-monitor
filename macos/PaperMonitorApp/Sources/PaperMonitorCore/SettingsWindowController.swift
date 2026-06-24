import AppKit

@MainActor
final class SettingsWindowController: NSWindowController, NSWindowDelegate {
    private let tabViewController = NSTabViewController()
    private let editingState: SettingsEditingState
    private let settingsChangeDebouncer: SearchSettingsChangeDebouncer

    init(
        settings: AppSettings,
        journalCatalog: JournalCatalog?,
        onSettingsChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        let editingState = SettingsEditingState(settings: settings)
        let settingsChangeDebouncer = SearchSettingsChangeDebouncer(onChange: onSettingsChange)
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 860, height: 620),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.isReleasedWhenClosed = false
        window.title = AppIdentity.settingsWindowTitle
        window.minSize = NSSize(width: 640, height: 420)
        window.center()
        self.editingState = editingState
        self.settingsChangeDebouncer = settingsChangeDebouncer
        super.init(window: window)
        window.delegate = self
        window.contentViewController = tabViewController
        let controllerBox = SettingsTabControllerBox()
        let termsController = SearchTermsViewController(
            editingState: editingState,
            changeDebouncer: settingsChangeDebouncer,
            onTermsChange: { [controllerBox] in
                controllerBox.searchSettingsController?.reloadQueriesFromEditingState()
            },
            onChange: onSettingsChange
        )
        let searchSettingsController = SearchSettingsViewController(
            editingState: editingState,
            journalCatalog: journalCatalog,
            changeDebouncer: settingsChangeDebouncer,
            onImmediateChange: { [controllerBox, weak termsController] in
                termsController?.reloadFromEditingState()
                controllerBox.journalFilterController?.reloadFromEditingState()
            },
            onChange: onSettingsChange
        )
        let journalFilterController = JournalFilterViewController(
            editingState: editingState,
            catalog: journalCatalog ?? JournalCatalog(entries: []),
            changeDebouncer: settingsChangeDebouncer,
            onJournalChange: { [controllerBox] in
                controllerBox.searchSettingsController?.reloadJournalScopeFromEditingState()
            },
            onChange: onSettingsChange
        )
        controllerBox.searchSettingsController = searchSettingsController
        controllerBox.journalFilterController = journalFilterController
        tabViewController.addTabViewItem(NSTabViewItem(viewController: searchSettingsController))
        tabViewController.addTabViewItem(NSTabViewItem(viewController: termsController))
        tabViewController.addTabViewItem(NSTabViewItem(viewController: journalFilterController))
    }

    required init?(coder: NSCoder) {
        nil
    }

    func show() {
        showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @discardableResult
    func flushPendingChanges() -> Bool {
        settingsChangeDebouncer.flushPending(editingState.settings)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        flushPendingChanges()
    }

    func windowWillClose(_ notification: Notification) {
        _ = flushPendingChanges()
    }
}

private final class SettingsTabControllerBox {
    weak var searchSettingsController: SearchSettingsViewController?
    weak var journalFilterController: JournalFilterViewController?
}
