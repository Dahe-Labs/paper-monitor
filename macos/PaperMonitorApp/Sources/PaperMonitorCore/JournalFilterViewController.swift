import AppKit

@MainActor
final class JournalFilterViewController: NSViewController, NSSearchFieldDelegate {
    var settings: AppSettings {
        get { editingState.settings }
        set { editingState.settings = newValue }
    }

    private let editingState: SettingsEditingState
    private let catalog: JournalCatalog
    private let onJournalChange: @MainActor () -> Void
    private let settingsChangeDebouncer: SearchSettingsChangeDebouncer
    private let topNField = NSTextField()
    private let topNStepper = NSStepper()
    private let selectedCountLabel = NSTextField(labelWithString: "")
    private let searchField = NSSearchField()
    private let tableView = NSTableView()
    private let emptyLabel = NSTextField(labelWithString: "")
    private var filteredEntries: [JournalCatalogEntry] = []
    private var isReloadingFromEditingState = false

    convenience init(
        settings: AppSettings,
        catalog: JournalCatalog,
        onChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        self.init(
            editingState: SettingsEditingState(settings: settings),
            catalog: catalog,
            onChange: onChange
        )
    }

    init(
        editingState: SettingsEditingState,
        catalog: JournalCatalog,
        changeDebouncer: SearchSettingsChangeDebouncer? = nil,
        onJournalChange: @escaping @MainActor () -> Void = {},
        onChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        self.editingState = editingState
        self.catalog = catalog
        self.onJournalChange = onJournalChange
        self.settingsChangeDebouncer = changeDebouncer ?? SearchSettingsChangeDebouncer(onChange: onChange)
        self.filteredEntries = catalog.entriesByImpactFactor
        super.init(nibName: nil, bundle: nil)
        title = "Journal Filter"
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func loadView() {
        let rootView = NSView()
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .width
        stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 20, left: 24, bottom: 20, right: 24)
        stack.translatesAutoresizingMaskIntoConstraints = false
        rootView.addSubview(stack)
        view = rootView

        configureTopNControls()
        configureSearchField()
        configureTable()
        configureEmptyLabel()

        stack.addArrangedSubview(topRow())
        stack.addArrangedSubview(searchField)
        stack.addArrangedSubview(scrollView())
        stack.addArrangedSubview(emptyLabel)

        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: rootView.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: rootView.trailingAnchor),
            stack.topAnchor.constraint(equalTo: rootView.topAnchor),
            stack.bottomAnchor.constraint(equalTo: rootView.bottomAnchor),
        ])

        reloadFromEditingState()
    }

    private var integerFormatter: NumberFormatter {
        let formatter = NumberFormatter()
        formatter.numberStyle = .none
        formatter.allowsFloats = false
        formatter.minimum = 1
        formatter.maximum = 50
        return formatter
    }

    private func configureTopNControls() {
        topNStepper.minValue = 1
        topNStepper.maxValue = 50
        topNStepper.increment = 1
        topNStepper.target = self
        topNStepper.action = #selector(topNChanged)

        topNField.formatter = integerFormatter
        topNField.delegate = self
        topNField.target = self
        topNField.action = #selector(topNFieldChanged)
        topNField.widthAnchor.constraint(equalToConstant: 64).isActive = true
    }

    private func configureSearchField() {
        searchField.placeholderString = "Filter journals"
        searchField.delegate = self
        searchField.target = self
        searchField.action = #selector(filterChanged)
    }

    private func configureTable() {
        tableView.dataSource = self
        tableView.delegate = self
        tableView.columnAutoresizingStyle = .uniformColumnAutoresizingStyle
        tableView.usesAlternatingRowBackgroundColors = true
        tableView.rowHeight = 28

        let selectedColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("selected"))
        selectedColumn.title = ""
        selectedColumn.width = 40
        selectedColumn.minWidth = 40
        selectedColumn.maxWidth = 40
        tableView.addTableColumn(selectedColumn)

        let journalColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("journal"))
        journalColumn.title = "Journal"
        journalColumn.width = 220
        journalColumn.minWidth = 180
        tableView.addTableColumn(journalColumn)

        let impactColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("impactFactor"))
        impactColumn.title = "IF"
        impactColumn.width = 70
        impactColumn.minWidth = 60
        tableView.addTableColumn(impactColumn)

        let levelColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("level"))
        levelColumn.title = "Level"
        levelColumn.width = 120
        levelColumn.minWidth = 90
        tableView.addTableColumn(levelColumn)
    }

    private func configureEmptyLabel() {
        emptyLabel.textColor = .secondaryLabelColor
        emptyLabel.alignment = .center
        emptyLabel.isHidden = true
    }

    private func topRow() -> NSStackView {
        let topNLabel = NSTextField(labelWithString: "Top N Journals")
        topNLabel.alignment = .right
        topNLabel.widthAnchor.constraint(equalToConstant: 150).isActive = true

        selectedCountLabel.setContentHuggingPriority(.required, for: .horizontal)

        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)

        let row = NSStackView(views: [topNLabel, topNField, topNStepper, spacer, selectedCountLabel])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        return row
    }

    private func scrollView() -> NSScrollView {
        let scroll = NSScrollView()
        scroll.borderType = .bezelBorder
        scroll.documentView = tableView
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.autohidesScrollers = true
        scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 240).isActive = true
        return scroll
    }

    private func applyFilter() {
        let query = searchField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if query.isEmpty {
            filteredEntries = catalog.entriesByImpactFactor
        } else {
            filteredEntries = catalog.entriesByImpactFactor.filter { entry in
                entry.journal.lowercased().contains(query)
                    || entry.level.lowercased().contains(query)
                    || entry.aliases.contains { $0.lowercased().contains(query) }
            }
        }
        tableView.reloadData()
        refreshEmptyState()
    }

    private func updateTopN(_ value: Int) {
        var selection = JournalSelection(
            topN: value,
            selectedJournals: settings.journalScope.selectedJournals
        )
        if !catalog.entries.isEmpty {
            selection.applyTopN(catalog)
        }

        settings.journalScope.topN = selection.topN
        settings.journalScope.selectedJournals = selection.selectedJournals
        refreshControls()
        tableView.reloadData()
        emitChange()
    }

    private func setSelected(_ selected: Bool, journal: String) {
        var selection = JournalSelection(
            topN: settings.journalScope.topN,
            selectedJournals: settings.journalScope.selectedJournals
        )
        selection.setSelected(selected, journal: journal)
        settings.journalScope.selectedJournals = selection.selectedJournals
        refreshControls()
        tableView.reloadData()
        emitChange()
    }

    private func refreshControls() {
        let topN = SettingsNormalizer.clampedTopN(settings.journalScope.topN)
        topNField.integerValue = topN
        topNStepper.integerValue = topN
        if catalog.entries.isEmpty {
            selectedCountLabel.stringValue = "Selected \(settings.journalScope.selectedJournals.count)"
        } else {
            selectedCountLabel.stringValue = "Selected \(settings.journalScope.selectedJournals.count) / \(catalog.entries.count)"
        }
        refreshEmptyState()
    }

    private func refreshEmptyState() {
        if catalog.entries.isEmpty {
            emptyLabel.stringValue = "Journal catalog unavailable"
            emptyLabel.isHidden = false
        } else if filteredEntries.isEmpty {
            emptyLabel.stringValue = "No matching journals"
            emptyLabel.isHidden = false
        } else {
            emptyLabel.isHidden = true
        }
    }

    @discardableResult
    private func emitChange() -> Bool {
        let didSave = settingsChangeDebouncer.flush(settings)
        onJournalChange()
        return didSave
    }

    func reloadFromEditingState() {
        _ = view
        isReloadingFromEditingState = true
        refreshControls()
        applyFilter()
        isReloadingFromEditingState = false
    }

    @objc private func topNChanged() {
        updateTopN(topNStepper.integerValue)
    }

    @objc private func topNFieldChanged() {
        updateTopN(topNField.integerValue)
    }

    @objc private func filterChanged() {
        guard !isReloadingFromEditingState else {
            return
        }
        applyFilter()
    }

    func controlTextDidChange(_ notification: Notification) {
        guard !isReloadingFromEditingState else {
            return
        }
        if notification.object as? NSSearchField === searchField {
            applyFilter()
        }
    }

    func controlTextDidEndEditing(_ notification: Notification) {
        guard notification.object as? NSTextField === topNField else {
            return
        }
        updateTopN(topNField.integerValue)
    }

    var selectedCountForTesting: Int {
        settings.journalScope.selectedJournals.count
    }

    var selectedJournalNamesForTesting: [String] {
        settings.journalScope.selectedJournals
    }

    var visibleJournalNamesForTesting: [String] {
        _ = view
        return filteredEntries.map(\.journal)
    }

    func applyTopNForTesting(_ value: Int) {
        _ = view
        updateTopN(value)
    }

    func toggleJournalForTesting(_ journal: String, selected: Bool) {
        _ = view
        setSelected(selected, journal: journal)
    }

    func filterForTesting(_ query: String) {
        _ = view
        searchField.stringValue = query
        applyFilter()
    }
}

extension JournalFilterViewController: NSTableViewDataSource, NSTableViewDelegate {
    func numberOfRows(in tableView: NSTableView) -> Int {
        filteredEntries.count
    }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard filteredEntries.indices.contains(row), let identifier = tableColumn?.identifier else {
            return nil
        }

        let entry = filteredEntries[row]
        switch identifier.rawValue {
        case "selected":
            let button = NSButton(
                checkboxWithTitle: "",
                target: self,
                action: #selector(toggleJournal(_:))
            )
            button.state = settings.journalScope.selectedJournals.contains(entry.journal) ? .on : .off
            button.tag = row
            return button
        case "journal":
            return labelCell(entry.journal)
        case "impactFactor":
            return labelCell(entry.impactFactor.map { String(format: "%.1f", $0) } ?? "-")
        case "level":
            return labelCell(entry.level)
        default:
            return nil
        }
    }

    private func labelCell(_ text: String, alignment: NSTextAlignment = .left) -> NSTableCellView {
        let cell = NSTableCellView()
        let label = NSTextField(labelWithString: text)
        label.lineBreakMode = .byTruncatingTail
        label.alignment = alignment
        label.translatesAutoresizingMaskIntoConstraints = false
        cell.addSubview(label)
        cell.textField = label
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 6),
            label.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -6),
            label.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
        ])
        return cell
    }

    @objc private func toggleJournal(_ sender: NSButton) {
        guard filteredEntries.indices.contains(sender.tag) else {
            return
        }
        let journal = filteredEntries[sender.tag].journal
        setSelected(sender.state == .on, journal: journal)
    }
}
