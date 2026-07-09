import AppKit

@MainActor
final class AppSettingsViewController: NSViewController {
    private let editingState: SettingsEditingState
    private let settingsChangeDebouncer: SearchSettingsChangeDebouncer

    private let startupButton = NSButton(checkboxWithTitle: "Launch Paper Monitor when you sign in", target: nil, action: nil)
    private let trayButton = NSButton(checkboxWithTitle: "Show menu bar / tray icon", target: nil, action: nil)
    private let notificationsButton = NSButton(checkboxWithTitle: "Send desktop notifications for new matched papers", target: nil, action: nil)
    private let quietStartupButton = NSButton(checkboxWithTitle: "Suppress notifications during quiet startup refresh", target: nil, action: nil)
    private let refreshOnLaunchButton = NSButton(checkboxWithTitle: "Refresh automatically when the app starts", target: nil, action: nil)

    init(
        editingState: SettingsEditingState,
        changeDebouncer: SearchSettingsChangeDebouncer
    ) {
        self.editingState = editingState
        self.settingsChangeDebouncer = changeDebouncer
        super.init(nibName: nil, bundle: nil)
        title = "App Settings"
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func loadView() {
        view = NSView()
        view.translatesAutoresizingMaskIntoConstraints = false

        let description = NSTextField(labelWithString: "Startup and notification behavior")
        description.font = .preferredFont(forTextStyle: .headline)

        for button in buttons {
            button.target = self
            button.action = #selector(optionChanged)
            button.setContentHuggingPriority(.required, for: .vertical)
        }

        let stack = NSStackView(views: [description] + buttons)
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false

        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 28),
            stack.topAnchor.constraint(equalTo: view.topAnchor, constant: 28),
            stack.trailingAnchor.constraint(lessThanOrEqualTo: view.trailingAnchor, constant: -28),
        ])
        reloadFromEditingState()
    }

    func reloadFromEditingState() {
        let runtime = editingState.settings.runtime
        startupButton.state = runtime.startupEnabled ? .on : .off
        trayButton.state = runtime.showTrayIcon ? .on : .off
        notificationsButton.state = runtime.notificationsEnabled ? .on : .off
        quietStartupButton.state = runtime.silentStartupNotifications ? .on : .off
        refreshOnLaunchButton.state = runtime.refreshOnLaunch ? .on : .off
    }

    @objc private func optionChanged() {
        let settings = editingState.update { settings in
            settings.runtime = RuntimeAppSettings(
                startupEnabled: startupButton.state == .on,
                showTrayIcon: trayButton.state == .on,
                notificationsEnabled: notificationsButton.state == .on,
                silentStartupNotifications: quietStartupButton.state == .on,
                refreshOnLaunch: refreshOnLaunchButton.state == .on
            )
        }
        settingsChangeDebouncer.schedule(settings)
    }

    private var buttons: [NSButton] {
        [
            startupButton,
            trayButton,
            notificationsButton,
            quietStartupButton,
            refreshOnLaunchButton,
        ]
    }
}
