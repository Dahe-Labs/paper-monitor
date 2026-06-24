import AppKit

@MainActor
final class SearchTermsViewController: NSViewController, NSTextViewDelegate {
    var settings: AppSettings {
        get { editingState.settings }
        set { editingState.settings = newValue }
    }
    var onChange: @MainActor @Sendable (AppSettings) -> Bool

    private let editingState: SettingsEditingState
    private let onTermsChange: @MainActor () -> Void
    private let includeField = NSTextView()
    private let excludeField = NSTextView()
    private let settingsChangeDebouncer: SearchSettingsChangeDebouncer
    private var isReloadingFromEditingState = false

    convenience init(
        settings: AppSettings,
        onChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        self.init(
            editingState: SettingsEditingState(settings: settings),
            onChange: onChange
        )
    }

    init(
        editingState: SettingsEditingState,
        changeDebouncer: SearchSettingsChangeDebouncer? = nil,
        onTermsChange: @escaping @MainActor () -> Void = {},
        onChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        self.editingState = editingState
        self.onTermsChange = onTermsChange
        self.onChange = onChange
        self.settingsChangeDebouncer = changeDebouncer ?? SearchSettingsChangeDebouncer(onChange: onChange)
        super.init(nibName: nil, bundle: nil)
        title = "Search Terms"
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func loadView() {
        let rootView = NSView()
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .width
        stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 20, left: 24, bottom: 20, right: 24)
        stack.translatesAutoresizingMaskIntoConstraints = false
        rootView.addSubview(stack)
        view = rootView

        configureTextView(includeField, value: settings.includeTerms.joined(separator: "\n"))
        configureTextView(excludeField, value: settings.excludeTerms.joined(separator: "\n"))

        let includeScroll = scroll(includeField)
        let excludeScroll = scroll(excludeField)
        includeScroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 130).isActive = true
        excludeScroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 130).isActive = true

        stack.addArrangedSubview(label("Include Terms"))
        stack.addArrangedSubview(includeScroll)
        stack.addArrangedSubview(label("Exclude Terms"))
        stack.addArrangedSubview(excludeScroll)
        includeScroll.heightAnchor.constraint(equalTo: excludeScroll.heightAnchor).isActive = true

        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: rootView.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: rootView.trailingAnchor),
            stack.topAnchor.constraint(equalTo: rootView.topAnchor),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: rootView.bottomAnchor),
        ])
    }

    private func label(_ text: String) -> NSTextField {
        let label = NSTextField(labelWithString: text)
        label.font = .preferredFont(forTextStyle: .headline)
        return label
    }

    private func configureTextView(_ textView: NSTextView, value: String) {
        textView.string = value
        textView.delegate = self
        textView.isRichText = false
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.minSize = NSSize(width: 0, height: 0)
        textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.containerSize = NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude)
    }

    private func scroll(_ textView: NSTextView) -> NSScrollView {
        let scrollView = NSScrollView()
        scrollView.borderType = .bezelBorder
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.documentView = textView
        return scrollView
    }

    private func emitDebouncedChange() {
        settingsChangeDebouncer.scheduleLatest { [editingState] in
            editingState.settings
        }
    }

    @discardableResult
    func flushPendingChanges() -> Bool {
        settingsChangeDebouncer.flushPending(settings)
    }

    func reloadFromEditingState() {
        _ = view
        isReloadingFromEditingState = true
        includeField.string = settings.includeTerms.joined(separator: "\n")
        excludeField.string = settings.excludeTerms.joined(separator: "\n")
        isReloadingFromEditingState = false
    }

    func updateTerms(includeTerms: [String], excludeTerms: [String], debounced: Bool) {
        SearchTermEditor.updateIncludeTerms(includeTerms, in: &settings)
        SearchTermEditor.updateExcludeTerms(excludeTerms, in: &settings)
        onTermsChange()
        if debounced {
            emitDebouncedChange()
        } else {
            _ = settingsChangeDebouncer.flush(settings)
        }
    }

    func textDidChange(_ notification: Notification) {
        guard !isReloadingFromEditingState else {
            return
        }
        updateTerms(
            includeTerms: includeField.string.components(separatedBy: .newlines),
            excludeTerms: excludeField.string.components(separatedBy: .newlines),
            debounced: true
        )
    }

    func appendIncludeTermForTesting(_ term: String, debounced: Bool) {
        _ = view
        if includeField.string.isEmpty {
            includeField.string = term
        } else {
            includeField.string += "\n\(term)"
        }
        updateTerms(
            includeTerms: includeField.string.components(separatedBy: .newlines),
            excludeTerms: excludeField.string.components(separatedBy: .newlines),
            debounced: debounced
        )
    }
}
