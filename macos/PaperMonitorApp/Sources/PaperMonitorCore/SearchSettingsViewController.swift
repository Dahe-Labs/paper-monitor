import AppKit

@MainActor
final class SearchSettingsViewController: NSViewController, NSTextFieldDelegate {
    var settings: AppSettings {
        get { editingState.settings }
        set { editingState.settings = newValue }
    }
    var onChange: @MainActor @Sendable (AppSettings) -> Bool

    private let editingState: SettingsEditingState
    private let onImmediateChange: @MainActor () -> Void
    private let journalCatalog: JournalCatalog?
    private let searchPresetCatalog: SearchPresetCatalog
    private let topNStepper = NSStepper()
    private let topNField = NSTextField()
    private let intervalPopup = NSPopUpButton()
    private let refreshStartTimeField = NSTextField()
    private let presetPopup = NSPopUpButton()
    private let crossrefField = NSTextField()
    private let openalexField = NSTextField()
    private let openalexEnabledButton = NSButton(checkboxWithTitle: "", target: nil, action: nil)
    private let openalexDaysField = NSTextField()
    private let openalexPerPageField = NSTextField()
    private let openalexMaxPagesField = NSTextField()
    private let openalexAPIKeyField = NSSecureTextField(frame: .zero)
    private let settingsChangeDebouncer: SearchSettingsChangeDebouncer
    private var isReloadingFromEditingState = false
    private let intervalOptions = [
        ("1h", 3_600),
        ("3h", 10_800),
        ("6h", 21_600),
        ("12h", 43_200),
        ("24h", 86_400),
    ]

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
        searchPresetCatalog: SearchPresetCatalog = .bundled,
        changeDebouncer: SearchSettingsChangeDebouncer? = nil,
        debounceScheduler: @escaping SearchSettingsChangeDebouncer.Scheduler = SearchSettingsChangeDebouncer.defaultScheduler,
        onImmediateChange: @escaping @MainActor () -> Void = {},
        onChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        self.editingState = editingState
        self.onImmediateChange = onImmediateChange
        self.journalCatalog = journalCatalog
        self.searchPresetCatalog = searchPresetCatalog
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

        refreshStartTimeField.stringValue = settings.refreshStartTime
        refreshStartTimeField.placeholderString = "HH:MM"
        refreshStartTimeField.delegate = self
        refreshStartTimeField.target = self
        refreshStartTimeField.action = #selector(refreshStartTimeChanged)
        refreshStartTimeField.widthAnchor.constraint(equalToConstant: 84).isActive = true
        stack.addArrangedSubview(row("Start Refresh Time", refreshStartTimeField))

        presetPopup.addItems(withTitles: searchPresetCatalog.selectablePresets.map(\.label))
        addCustomPresetIfNeeded()
        selectPreset()
        presetPopup.target = self
        presetPopup.action = #selector(presetChanged)
        stack.addArrangedSubview(row("Search Direction", presetPopup))

        configureQueryField(crossrefField, value: settings.searchDirection.crossrefQuery)
        stack.addArrangedSubview(row("Crossref Query", crossrefField))

        configureQueryField(openalexField, value: settings.searchDirection.openalexQuery)
        stack.addArrangedSubview(row("OpenAlex Query", openalexField))

        configureOpenAlexSourceControls()
        stack.addArrangedSubview(row("OpenAlex Enabled", openalexEnabledButton))
        stack.addArrangedSubview(row("OpenAlex Days", openalexDaysField))
        stack.addArrangedSubview(row("OpenAlex Per Page", openalexPerPageField))
        stack.addArrangedSubview(row("OpenAlex Pages", openalexMaxPagesField))
        stack.addArrangedSubview(row("OpenAlex API Key", openalexAPIKeyField))
    }

    private var integerFormatter: NumberFormatter {
        let formatter = NumberFormatter()
        formatter.numberStyle = .none
        formatter.allowsFloats = false
        formatter.minimum = 1
        formatter.maximum = 50
        return formatter
    }

    private func boundedIntegerFormatter(minimum: Int, maximum: Int) -> NumberFormatter {
        let formatter = NumberFormatter()
        formatter.numberStyle = .none
        formatter.allowsFloats = false
        formatter.minimum = NSNumber(value: minimum)
        formatter.maximum = NSNumber(value: maximum)
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

    private func configureOpenAlexSourceControls() {
        openalexEnabledButton.state = settings.openAlex.enabled ? .on : .off
        openalexEnabledButton.target = self
        openalexEnabledButton.action = #selector(openAlexEnabledChanged)

        configureIntegerField(
            openalexDaysField,
            value: settings.openAlex.daysBack,
            maxValue: 3650,
            action: #selector(openAlexIntegerFieldChanged)
        )
        configureIntegerField(
            openalexPerPageField,
            value: settings.openAlex.perPage,
            maxValue: 200,
            action: #selector(openAlexIntegerFieldChanged)
        )
        configureIntegerField(
            openalexMaxPagesField,
            value: settings.openAlex.maxPages,
            maxValue: 50,
            action: #selector(openAlexIntegerFieldChanged)
        )
        openalexAPIKeyField.stringValue = settings.openAlex.apiKey
        openalexAPIKeyField.delegate = self
        openalexAPIKeyField.target = self
        openalexAPIKeyField.action = #selector(openAlexAPIKeyChanged)
        openalexAPIKeyField.widthAnchor.constraint(greaterThanOrEqualToConstant: 240).isActive = true
    }

    private func configureIntegerField(
        _ field: NSTextField,
        value: Int,
        maxValue: Int,
        action: Selector
    ) {
        field.integerValue = value
        field.formatter = boundedIntegerFormatter(minimum: 1, maximum: maxValue)
        field.delegate = self
        field.target = self
        field.action = action
        field.widthAnchor.constraint(equalToConstant: 72).isActive = true
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
        if let preset = searchPresetCatalog.definition(for: settings.searchDirection.preset),
           !preset.isCustom,
           let index = searchPresetCatalog.selectablePresets.firstIndex(where: { $0.id == preset.id }) {
            presetPopup.selectItem(at: index)
        } else if presetPopup.numberOfItems > searchPresetCatalog.selectablePresets.count {
            presetPopup.selectItem(at: searchPresetCatalog.selectablePresets.count)
        }
    }

    private func addCustomPresetIfNeeded() {
        if let preset = searchPresetCatalog.definition(for: settings.searchDirection.preset),
           !preset.isCustom {
            return
        }
        let label = settings.searchDirection.label.trimmingCharacters(in: .whitespacesAndNewlines)
        presetPopup.addItem(withTitle: label.isEmpty ? "Custom" : "Custom: \(label)")
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

    @objc private func refreshStartTimeChanged() {
        settings.refreshStartTime = SettingsNormalizer.normalizedRefreshStartTime(refreshStartTimeField.stringValue)
            ?? refreshStartTimeField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        refreshStartTimeField.stringValue = settings.refreshStartTime
        emitChange()
    }

    @objc private func presetChanged() {
        let index = presetPopup.indexOfSelectedItem
        guard searchPresetCatalog.selectablePresets.indices.contains(index) else {
            return
        }
        applyPreset(searchPresetCatalog.selectablePresets[index])
    }

    private func applyPreset(_ preset: SearchPresetDefinition) {
        searchPresetCatalog.apply(preset, to: &settings)
        crossrefField.stringValue = settings.searchDirection.crossrefQuery
        openalexField.stringValue = settings.searchDirection.openalexQuery
        emitChange()
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

    @objc private func openAlexEnabledChanged() {
        updateOpenAlexSource(
            enabled: openalexEnabledButton.state == .on,
            daysBack: openalexDaysField.integerValue,
            perPage: openalexPerPageField.integerValue,
            maxPages: openalexMaxPagesField.integerValue,
            apiKey: openalexAPIKeyField.stringValue,
            debounced: false
        )
    }

    @objc private func openAlexIntegerFieldChanged() {
        updateOpenAlexSource(
            enabled: openalexEnabledButton.state == .on,
            daysBack: openalexDaysField.integerValue,
            perPage: openalexPerPageField.integerValue,
            maxPages: openalexMaxPagesField.integerValue,
            apiKey: openalexAPIKeyField.stringValue,
            debounced: false
        )
    }

    @objc private func openAlexAPIKeyChanged() {
        updateOpenAlexSource(
            enabled: openalexEnabledButton.state == .on,
            daysBack: openalexDaysField.integerValue,
            perPage: openalexPerPageField.integerValue,
            maxPages: openalexMaxPagesField.integerValue,
            apiKey: openalexAPIKeyField.stringValue,
            debounced: true
        )
    }

    func updateOpenAlexSource(
        enabled: Bool,
        daysBack: Int,
        perPage: Int,
        maxPages: Int,
        apiKey: String,
        debounced: Bool
    ) {
        settings.openAlex.enabled = enabled
        settings.openAlex.daysBack = SettingsNormalizer.clampedOpenAlexDaysBack(daysBack)
        settings.openAlex.perPage = SettingsNormalizer.clampedOpenAlexPerPage(perPage)
        settings.openAlex.maxPages = SettingsNormalizer.clampedOpenAlexMaxPages(maxPages)
        settings.openAlex.apiKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        reloadOpenAlexSourceControls()
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
        } else if field === openalexAPIKeyField {
            openAlexAPIKeyChanged()
        }
    }

    func controlTextDidEndEditing(_ notification: Notification) {
        guard let field = notification.object as? NSTextField else {
            return
        }
        if field === topNField {
            updateTopN(topNField.integerValue)
        } else if field === refreshStartTimeField {
            refreshStartTimeChanged()
        } else if field === openalexDaysField || field === openalexPerPageField || field === openalexMaxPagesField {
            openAlexIntegerFieldChanged()
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
        isReloadingFromEditingState = false
    }

    private func reloadOpenAlexSourceControls() {
        _ = view
        isReloadingFromEditingState = true
        openalexEnabledButton.state = settings.openAlex.enabled ? .on : .off
        openalexDaysField.integerValue = settings.openAlex.daysBack
        openalexPerPageField.integerValue = settings.openAlex.perPage
        openalexMaxPagesField.integerValue = settings.openAlex.maxPages
        let firstResponder = view.window?.firstResponder
        if firstResponder == nil || firstResponder !== openalexAPIKeyField.currentEditor() {
            openalexAPIKeyField.stringValue = settings.openAlex.apiKey
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
        guard let definition = searchPresetCatalog.definition(for: preset.rawValue),
              !definition.isCustom else {
            return
        }
        applyPreset(definition)
    }

    func applyPresetForTesting(id: String) {
        guard let definition = searchPresetCatalog.definition(for: id),
              !definition.isCustom else {
            return
        }
        applyPreset(definition)
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

    func updateOpenAlexSourceForTesting(
        enabled: Bool,
        daysBack: Int,
        perPage: Int,
        maxPages: Int,
        apiKey: String,
        debounced: Bool
    ) {
        _ = view
        openalexEnabledButton.state = enabled ? .on : .off
        openalexDaysField.integerValue = daysBack
        openalexPerPageField.integerValue = perPage
        openalexMaxPagesField.integerValue = maxPages
        openalexAPIKeyField.stringValue = apiKey
        updateOpenAlexSource(
            enabled: enabled,
            daysBack: daysBack,
            perPage: perPage,
            maxPages: maxPages,
            apiKey: apiKey,
            debounced: debounced
        )
    }

    var openAlexSourceSettingsForTesting: OpenAlexSourceSettings {
        _ = view
        return settings.openAlex
    }
}
