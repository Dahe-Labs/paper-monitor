import AppKit

@MainActor
final class SearchSettingsViewController: NSViewController, NSTextFieldDelegate, NSTextViewDelegate {
    var settings: AppSettings {
        get { editingState.settings }
        set { editingState.settings = newValue }
    }
    var onChange: @MainActor @Sendable (AppSettings) -> Bool

    private let editingState: SettingsEditingState
    private let onImmediateChange: @MainActor () -> Void
    private let journalCatalog: JournalCatalog?
    private let topNStepper = NSStepper()
    private let topNField = NSTextField()
    private let intervalPopup = NSPopUpButton()
    private let refreshStartField = NSTextField()
    private let presetPopup = NSPopUpButton()
    private let directionNameField = NSTextField()
    private let keywordsTextView = NSTextView()
    private let keywordsScrollView = NSScrollView()
    private let crossrefField = NSTextField()
    private let openalexField = NSTextField()
    private let settingsChangeDebouncer: SearchSettingsChangeDebouncer
    private var isReloadingFromEditingState = false
    private let intervalOptions = [
        ("1h", 3_600),
        ("3h", 10_800),
        ("6h", 21_600),
        ("12h", 43_200),
        ("1 day", 86_400),
        ("2 days", 172_800),
    ]
    private let customPresetTitle = "Custom..."

    convenience init(
        settings: AppSettings,
        journalCatalog: JournalCatalog?,
        onChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        self.init(
            editingState: SettingsEditingState(settings: settings),
            journalCatalog: journalCatalog,
            onChange: onChange
        )
    }

    init(
        editingState: SettingsEditingState,
        journalCatalog: JournalCatalog?,
        changeDebouncer: SearchSettingsChangeDebouncer? = nil,
        debounceScheduler: @escaping SearchSettingsChangeDebouncer.Scheduler = SearchSettingsChangeDebouncer.defaultScheduler,
        onImmediateChange: @escaping @MainActor () -> Void = {},
        onChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        self.editingState = editingState
        self.onImmediateChange = onImmediateChange
        self.journalCatalog = journalCatalog
        self.onChange = onChange
        self.settingsChangeDebouncer = changeDebouncer ?? SearchSettingsChangeDebouncer(
            scheduler: debounceScheduler,
            onChange: onChange
        )
        super.init(nibName: nil, bundle: nil)
        title = "Search Settings"
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func loadView() {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 20, left: 24, bottom: 20, right: 24)
        view = stack

        topNStepper.minValue = 1
        topNStepper.maxValue = 50
        topNStepper.increment = 1
        topNStepper.integerValue = settings.journalScope.topN
        topNStepper.target = self
        topNStepper.action = #selector(topNChanged)

        topNField.integerValue = settings.journalScope.topN
        topNField.formatter = integerFormatter
        topNField.delegate = self
        topNField.target = self
        topNField.action = #selector(topNFieldChanged)
        topNField.widthAnchor.constraint(equalToConstant: 64).isActive = true
        stack.addArrangedSubview(row("Top N Journals", topNField, topNStepper))

        intervalPopup.addItems(withTitles: intervalOptions.map(\.0))
        addCustomIntervalIfNeeded()
        selectInterval()
        intervalPopup.target = self
        intervalPopup.action = #selector(intervalChanged)
        stack.addArrangedSubview(row("Refresh Frequency", intervalPopup))

        configureRefreshStartField()
        stack.addArrangedSubview(row("Start Time", refreshStartField))

        presetPopup.addItems(withTitles: SearchPreset.allCases.map(\.label))
        presetPopup.addItem(withTitle: customPresetTitle)
        addCustomPresetIfNeeded()
        selectPreset()
        presetPopup.target = self
        presetPopup.action = #selector(presetChanged)
        stack.addArrangedSubview(row("Search Direction", presetPopup))

        configureDirectionNameField()
        stack.addArrangedSubview(row("Direction Name", directionNameField))

        configureKeywordsTextView()
        stack.addArrangedSubview(row("Keywords", keywordsScrollView))

        configureQueryField(crossrefField, value: settings.searchDirection.crossrefQuery)
        stack.addArrangedSubview(row("Crossref Query", crossrefField))

        configureQueryField(openalexField, value: settings.searchDirection.openalexQuery)
        stack.addArrangedSubview(row("OpenAlex Query", openalexField))
    }

    private var integerFormatter: NumberFormatter {
        let formatter = NumberFormatter()
        formatter.numberStyle = .none
        formatter.allowsFloats = false
        formatter.minimum = 1
        formatter.maximum = 50
        return formatter
    }

    private func configureQueryField(_ field: NSTextField, value: String) {
        field.stringValue = value
        field.delegate = self
        field.target = self
        field.action = #selector(queryChanged)
        field.lineBreakMode = .byTruncatingTail
        field.widthAnchor.constraint(greaterThanOrEqualToConstant: 360).isActive = true
    }

    private func configureRefreshStartField() {
        refreshStartField.stringValue = settings.refreshStartTime
        refreshStartField.placeholderString = "HH:mm"
        refreshStartField.delegate = self
        refreshStartField.target = self
        refreshStartField.action = #selector(refreshStartChanged)
        refreshStartField.widthAnchor.constraint(equalToConstant: 96).isActive = true
    }

    private func configureDirectionNameField() {
        directionNameField.stringValue = settings.searchDirection.label
        directionNameField.delegate = self
        directionNameField.target = self
        directionNameField.action = #selector(customDirectionChanged)
        directionNameField.widthAnchor.constraint(greaterThanOrEqualToConstant: 360).isActive = true
    }

    private func configureKeywordsTextView() {
        keywordsTextView.string = keywordText(for: settings)
        keywordsTextView.delegate = self
        keywordsTextView.font = .systemFont(ofSize: NSFont.systemFontSize)
        keywordsTextView.isRichText = false
        keywordsTextView.isAutomaticQuoteSubstitutionEnabled = false
        keywordsTextView.isAutomaticDashSubstitutionEnabled = false

        keywordsScrollView.documentView = keywordsTextView
        keywordsScrollView.hasVerticalScroller = true
        keywordsScrollView.borderType = .bezelBorder
        keywordsScrollView.widthAnchor.constraint(greaterThanOrEqualToConstant: 360).isActive = true
        keywordsScrollView.heightAnchor.constraint(equalToConstant: 74).isActive = true
    }

    private func row(_ label: String, _ views: NSView...) -> NSStackView {
        let labelView = NSTextField(labelWithString: label)
        labelView.alignment = .right
        labelView.widthAnchor.constraint(equalToConstant: 150).isActive = true
        labelView.setContentHuggingPriority(.required, for: .horizontal)
        labelView.setContentCompressionResistancePriority(.required, for: .horizontal)

        let row = NSStackView(views: [labelView] + views)
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        row.translatesAutoresizingMaskIntoConstraints = false
        return row
    }

    private func selectInterval() {
        if let index = intervalOptions.firstIndex(where: { $0.1 == settings.intervalSeconds }) {
            intervalPopup.selectItem(at: index)
        } else if intervalPopup.numberOfItems > intervalOptions.count {
            intervalPopup.selectItem(at: intervalOptions.count)
        }
    }

    private func addCustomIntervalIfNeeded() {
        guard !intervalOptions.contains(where: { $0.1 == settings.intervalSeconds }) else {
            return
        }
        intervalPopup.addItem(withTitle: "Custom (\(settings.intervalSeconds)s)")
    }

    private func selectPreset() {
        if let preset = SearchPreset(rawValue: settings.searchDirection.preset),
           let index = SearchPreset.allCases.firstIndex(of: preset) {
            presetPopup.selectItem(at: index)
        } else {
            refreshCustomPresetMenuItem()
            presetPopup.selectItem(at: SearchPreset.allCases.count)
        }
        updateCustomControls()
    }

    private func addCustomPresetIfNeeded() {
        guard SearchPreset(rawValue: settings.searchDirection.preset) == nil,
              presetPopup.numberOfItems == SearchPreset.allCases.count
        else {
            return
        }
        presetPopup.addItem(withTitle: customPresetTitle)
    }

    private func refreshCustomPresetMenuItem() {
        guard presetPopup.numberOfItems > SearchPreset.allCases.count else {
            return
        }
        let label = settings.searchDirection.label.trimmingCharacters(in: .whitespacesAndNewlines)
        presetPopup.item(at: SearchPreset.allCases.count)?.title = label.isEmpty ? "Custom" : "Custom: \(label)"
    }

    private func updateCustomControls() {
        let isCustom = SearchPreset(rawValue: settings.searchDirection.preset) == nil
        directionNameField.isEnabled = isCustom
        keywordsTextView.isEditable = isCustom
        keywordsTextView.textColor = isCustom ? .labelColor : .secondaryLabelColor
    }

    private func keywordText(for settings: AppSettings) -> String {
        let keywords = settings.searchDirection.keywords.isEmpty ? settings.includeTerms : settings.searchDirection.keywords
        return keywords.joined(separator: "\n")
    }

    @discardableResult
    private func emitChange() -> Bool {
        let didSave = settingsChangeDebouncer.flush(settings)
        onImmediateChange()
        return didSave
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

    private func updateTopN(_ value: Int) {
        let clampedValue = SettingsNormalizer.clampedTopN(value)
        SearchSettingsPolicy.applyTopN(clampedValue, to: &settings, catalog: journalCatalog)
        topNField.integerValue = clampedValue
        topNStepper.integerValue = clampedValue
        emitChange()
    }

    @objc private func topNChanged() {
        updateTopN(topNStepper.integerValue)
    }

    @objc private func topNFieldChanged() {
        updateTopN(topNField.integerValue)
    }

    @objc private func intervalChanged() {
        let index = intervalPopup.indexOfSelectedItem
        guard intervalOptions.indices.contains(index) else {
            return
        }
        settings.intervalSeconds = intervalOptions[index].1
        emitChange()
    }

    @objc private func refreshStartChanged() {
        settings.refreshStartTime = AppRefreshSettings.normalizedStartTime(refreshStartField.stringValue)
            ?? refreshStartField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        emitDebouncedChange()
    }

    @objc private func presetChanged() {
        let index = presetPopup.indexOfSelectedItem
        if SearchPreset.allCases.indices.contains(index) {
            applyPreset(SearchPreset.allCases[index])
            return
        }
        applyCustomDirection(
            label: directionNameField.stringValue.isEmpty ? "Custom" : directionNameField.stringValue,
            keywordsText: keywordsTextView.string,
            debounced: false
        )
    }

    private func applyPreset(_ preset: SearchPreset) {
        preset.apply(to: &settings)
        directionNameField.stringValue = settings.searchDirection.label
        keywordsTextView.string = keywordText(for: settings)
        selectPreset()
        crossrefField.stringValue = settings.searchDirection.crossrefQuery
        openalexField.stringValue = settings.searchDirection.openalexQuery
        emitChange()
    }

    @objc private func customDirectionChanged() {
        applyCustomDirection(
            label: directionNameField.stringValue,
            keywordsText: keywordsTextView.string,
            debounced: true
        )
    }

    private func applyCustomDirection(label: String, keywordsText: String, debounced: Bool) {
        SearchDirectionEditor.applyCustomDirection(
            label: label,
            keywords: SearchDirectionEditor.keywords(from: keywordsText),
            to: &settings
        )
        refreshCustomPresetMenuItem()
        presetPopup.selectItem(at: SearchPreset.allCases.count)
        updateCustomControls()
        crossrefField.stringValue = settings.searchDirection.crossrefQuery
        openalexField.stringValue = settings.searchDirection.openalexQuery
        if debounced {
            emitDebouncedChange()
        } else {
            emitChange()
        }
    }

    @objc private func queryChanged() {
        updateQueries(
            crossrefQuery: crossrefField.stringValue,
            openalexQuery: openalexField.stringValue,
            debounced: true
        )
    }

    func updateQueries(crossrefQuery: String, openalexQuery: String, debounced: Bool) {
        settings.searchDirection.crossrefQuery = crossrefQuery
        settings.searchDirection.openalexQuery = openalexQuery
        settings.searchDirection.queryManuallyEdited = true
        if debounced {
            emitDebouncedChange()
        } else {
            emitChange()
        }
    }

    func controlTextDidChange(_ notification: Notification) {
        guard !isReloadingFromEditingState else {
            return
        }
        guard let field = notification.object as? NSTextField else {
            return
        }
        if field === crossrefField || field === openalexField {
            queryChanged()
        } else if field === refreshStartField {
            refreshStartChanged()
        } else if field === directionNameField {
            customDirectionChanged()
        }
    }

    func textDidChange(_ notification: Notification) {
        guard !isReloadingFromEditingState else {
            return
        }
        guard notification.object as? NSTextView === keywordsTextView else {
            return
        }
        customDirectionChanged()
    }

    func controlTextDidEndEditing(_ notification: Notification) {
        guard let field = notification.object as? NSTextField else {
            return
        }
        if field === topNField {
            updateTopN(topNField.integerValue)
        }
    }

    var selectedPresetTitleForTesting: String? {
        presetPopup.selectedItem?.title
    }

    func reloadQueriesFromEditingState() {
        _ = view
        isReloadingFromEditingState = true
        let firstResponder = view.window?.firstResponder
        if firstResponder == nil || firstResponder !== crossrefField.currentEditor() {
            crossrefField.stringValue = settings.searchDirection.crossrefQuery
        }
        if firstResponder == nil || firstResponder !== openalexField.currentEditor() {
            openalexField.stringValue = settings.searchDirection.openalexQuery
        }
        if firstResponder == nil || firstResponder !== keywordsTextView {
            keywordsTextView.string = keywordText(for: settings)
        }
        isReloadingFromEditingState = false
    }

    func reloadJournalScopeFromEditingState() {
        _ = view
        isReloadingFromEditingState = true
        let topN = SettingsNormalizer.clampedTopN(settings.journalScope.topN)
        let firstResponder = view.window?.firstResponder
        if firstResponder == nil || firstResponder !== topNField.currentEditor() {
            topNField.integerValue = topN
        }
        topNStepper.integerValue = topN
        isReloadingFromEditingState = false
    }

    func applyPresetForTesting(_ preset: SearchPreset) {
        applyPreset(preset)
    }

    func applyTopNForTesting(_ value: Int) {
        _ = view
        updateTopN(value)
    }

    var topNValueForTesting: Int {
        _ = view
        return topNField.integerValue
    }

    func editCrossrefQueryForTesting(_ query: String, debounced: Bool) {
        _ = view
        crossrefField.stringValue = query
        updateQueries(
            crossrefQuery: crossrefField.stringValue,
            openalexQuery: openalexField.stringValue,
            debounced: debounced
        )
    }

    func applyCustomDirectionForTesting(label: String, keywordsText: String, debounced: Bool) {
        _ = view
        directionNameField.stringValue = label
        keywordsTextView.string = keywordsText
        applyCustomDirection(label: label, keywordsText: keywordsText, debounced: debounced)
    }

    var intervalTitlesForTesting: [String] {
        _ = view
        return intervalPopup.itemTitles
    }

    var selectedIntervalTitleForTesting: String? {
        _ = view
        return intervalPopup.selectedItem?.title
    }

    var refreshStartTimeForTesting: String {
        _ = view
        return refreshStartField.stringValue
    }
}
