import AppKit

@MainActor
final class SettingsWindowController: NSWindowController, NSWindowDelegate {
    private let tabViewController = NSTabViewController()
    private let applyAccessoryController = NSTitlebarAccessoryViewController()
    private let applyButton = NSButton(title: "Apply", target: nil, action: nil)
    private let applyStatusLabel = NSTextField(labelWithString: "")
    private let editingState: SettingsEditingState
    private let settingsChangeDebouncer: SearchSettingsChangeDebouncer
    private let applyState: SettingsApplyState
    private let onSettingsChange: @MainActor @Sendable (AppSettings) -> Bool

    init(
        settings: AppSettings,
        journalCatalog: JournalCatalog?,
        onSettingsChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        let editingState = SettingsEditingState(settings: settings)
        let applyState = SettingsApplyState(initialSettings: settings)
        let settingsChangeDebouncer = SearchSettingsChangeDebouncer(
            onPending: { settings in
                applyState.markDirty(settings)
            },
            onChange: { settings in
                applyState.markDirty(settings)
                return true
            }
        )
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
        self.applyState = applyState
        self.onSettingsChange = onSettingsChange
        super.init(window: window)
        window.delegate = self
        window.contentViewController = tabViewController
        applyState.onStateChange = { [weak self] in
            self?.refreshApplyControls()
        }
        configureApplyAccessory(on: window)
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
        refreshApplyControls()
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
        _ = settingsChangeDebouncer.flushPending(editingState.settings)
        guard applyState.isDirty else {
            refreshApplyControls()
            return true
        }

        if onSettingsChange(applyState.latestSettings) {
            applyState.markSaved()
            refreshApplyControls(statusText: "Settings saved")
            return true
        }

        refreshApplyControls(statusText: "Save failed")
        return false
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        flushPendingChanges()
    }

    func windowWillClose(_ notification: Notification) {
        _ = flushPendingChanges()
    }

    private func configureApplyAccessory(on window: NSWindow) {
        applyButton.target = self
        applyButton.action = #selector(applyButtonPressed)
        applyButton.bezelStyle = .rounded

        applyStatusLabel.textColor = .secondaryLabelColor
        applyStatusLabel.font = .preferredFont(forTextStyle: .caption1)
        applyStatusLabel.setContentHuggingPriority(.required, for: .horizontal)

        let stack = NSStackView(views: [applyStatusLabel, applyButton])
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 8
        stack.edgeInsets = NSEdgeInsets(top: 0, left: 0, bottom: 0, right: 6)

        applyAccessoryController.view = stack
        applyAccessoryController.layoutAttribute = .right
        window.addTitlebarAccessoryViewController(applyAccessoryController)
    }

    private func refreshApplyControls(statusText: String? = nil) {
        applyButton.isEnabled = applyState.isDirty
        if let statusText {
            applyStatusLabel.stringValue = statusText
        } else if applyState.isDirty {
            applyStatusLabel.stringValue = "Unsaved changes"
        } else if applyStatusLabel.stringValue != "Settings saved" {
            applyStatusLabel.stringValue = ""
        }
    }

    @objc private func applyButtonPressed() {
        _ = flushPendingChanges()
    }

    var isApplyButtonEnabledForTesting: Bool {
        applyButton.isEnabled
    }

    var applyStatusTextForTesting: String {
        applyStatusLabel.stringValue
    }

    @discardableResult
    func triggerApplyForTesting() -> Bool {
        flushPendingChanges()
    }
}

private final class SettingsTabControllerBox {
    weak var searchSettingsController: SearchSettingsViewController?
    weak var journalFilterController: JournalFilterViewController?
}

@MainActor
private final class SettingsApplyState {
    private(set) var latestSettings: AppSettings
    private(set) var isDirty = false
    var onStateChange: (@MainActor () -> Void)?

    init(initialSettings: AppSettings) {
        self.latestSettings = initialSettings
    }

    func markDirty(_ settings: AppSettings) {
        latestSettings = settings
        isDirty = true
        onStateChange?()
    }

    func markSaved() {
        isDirty = false
        onStateChange?()
    }
}
