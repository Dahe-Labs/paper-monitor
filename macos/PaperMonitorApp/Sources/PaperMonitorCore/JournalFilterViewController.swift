import AppKit

private extension NSPasteboard.PasteboardType {
    static let paperMonitorJournal = NSPasteboard.PasteboardType("com.local.paper-monitor.journal")
}

@MainActor
private final class JournalDropStackView: NSStackView {
    var onJournalDrop: ((String) -> Void)?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        registerForDraggedTypes([.paperMonitorJournal, .string])
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        registerForDraggedTypes([.paperMonitorJournal, .string])
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        journal(from: sender) == nil ? [] : .copy
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        guard let journal = journal(from: sender) else {
            return false
        }
        onJournalDrop?(journal)
        return true
    }

    private func journal(from sender: NSDraggingInfo) -> String? {
        let pasteboard = sender.draggingPasteboard
        let value = pasteboard.string(forType: .paperMonitorJournal) ?? pasteboard.string(forType: .string)
        let clean = DualListSelection.normalizedDisplayValue(value ?? "")
        return clean.isEmpty ? nil : clean
    }
}

@MainActor
private final class DraggableJournalButton: NSButton, NSDraggingSource {
    var journal: String = ""

    override func mouseDragged(with event: NSEvent) {
        let clean = DualListSelection.normalizedDisplayValue(journal)
        guard !clean.isEmpty else {
            return
        }
        let pasteboardItem = NSPasteboardItem()
        pasteboardItem.setString(clean, forType: .paperMonitorJournal)
        pasteboardItem.setString(clean, forType: .string)
        let draggingItem = NSDraggingItem(pasteboardWriter: pasteboardItem)
        draggingItem.setDraggingFrame(bounds, contents: snapshot())
        beginDraggingSession(with: [draggingItem], event: event, source: self)
    }

    func draggingSession(
        _ session: NSDraggingSession,
        sourceOperationMaskFor context: NSDraggingContext
    ) -> NSDragOperation {
        .move
    }

    private func snapshot() -> NSImage? {
        guard let bitmap = bitmapImageRepForCachingDisplay(in: bounds) else {
            return nil
        }
        cacheDisplay(in: bounds, to: bitmap)
        let image = NSImage(size: bounds.size)
        image.addRepresentation(bitmap)
        return image
    }
}

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
    private let candidateCountLabel = NSTextField(labelWithString: "")
    private let searchField = NSSearchField()
    private let manualJournalField = NSTextField()
    private let tableView = NSTableView()
    private let emptyLabel = NSTextField(labelWithString: "")
    private let selectedJournalStack = JournalDropStackView()
    private let preprintSourceStack = NSStackView()
    private var filteredEntries: [JournalCatalogEntry] = []
    private var preprintEntries: [JournalCatalogEntry] = []
    private var extraCandidateJournals: [String] = []
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
        self.filteredEntries = Self.formalJournalEntries(in: catalog)
        self.preprintEntries = Self.preprintSourceEntries(in: catalog)
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
        configureManualJournalField()
        configureTable()
        configureEmptyLabel()
        configureSelectedJournalStack()
        configurePreprintSources()

        stack.addArrangedSubview(topRow())
        stack.addArrangedSubview(journalBoard())
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
        searchField.placeholderString = "Search candidate journals"
        searchField.delegate = self
        searchField.target = self
        searchField.action = #selector(filterChanged)
    }

    private func configureManualJournalField() {
        manualJournalField.placeholderString = "Add journal manually"
        manualJournalField.target = self
        manualJournalField.action = #selector(addManualJournal)
        manualJournalField.delegate = self
    }

    private func configureTable() {
        tableView.dataSource = self
        tableView.delegate = self
        tableView.columnAutoresizingStyle = .uniformColumnAutoresizingStyle
        tableView.usesAlternatingRowBackgroundColors = true
        tableView.rowHeight = 30
        tableView.registerForDraggedTypes([.paperMonitorJournal, .string])
        tableView.setDraggingSourceOperationMask(.copy, forLocal: true)

        let selectedColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("selected"))
        selectedColumn.title = ""
        selectedColumn.width = 48
        selectedColumn.minWidth = 48
        selectedColumn.maxWidth = 48
        tableView.addTableColumn(selectedColumn)

        let journalColumn = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("journal"))
        journalColumn.title = "Journal"
        journalColumn.width = 230
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

    private func configureSelectedJournalStack() {
        selectedJournalStack.orientation = .vertical
        selectedJournalStack.alignment = .width
        selectedJournalStack.spacing = 6
        selectedJournalStack.edgeInsets = NSEdgeInsets(top: 8, left: 8, bottom: 8, right: 8)
        selectedJournalStack.onJournalDrop = { [weak self] journal in
            self?.setSelected(true, journal: journal)
        }
    }

    private func configurePreprintSources() {
        preprintSourceStack.orientation = .vertical
        preprintSourceStack.alignment = .leading
        preprintSourceStack.spacing = 6
        preprintSourceStack.translatesAutoresizingMaskIntoConstraints = false
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

    private func journalBoard() -> NSStackView {
        let board = NSStackView(views: [selectedSection(), candidateSection()])
        board.orientation = .horizontal
        board.alignment = .top
        board.distribution = .fillEqually
        board.spacing = 14
        board.heightAnchor.constraint(greaterThanOrEqualToConstant: 380).isActive = true
        return board
    }

    private func selectedSection() -> NSView {
        let section = panelStack(title: "Selected Journals", subtitle: "Click a journal to remove it.")
        section.addArrangedSubview(selectedScrollView())
        return section
    }

    private func candidateSection() -> NSView {
        let section = panelStack(title: "Candidate Journals", subtitle: "Sorted by impact factor, then catalog rank.")
        section.addArrangedSubview(searchField)
        section.addArrangedSubview(manualAddRow())
        section.addArrangedSubview(candidateHeaderRow())
        section.addArrangedSubview(scrollView())
        if !preprintEntries.isEmpty {
            section.addArrangedSubview(preprintSection())
        }
        return section
    }

    private func panelStack(title: String, subtitle: String) -> NSStackView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .width
        stack.spacing = 8
        stack.edgeInsets = NSEdgeInsets(top: 12, left: 12, bottom: 12, right: 12)
        stack.wantsLayer = true
        stack.layer?.borderColor = NSColor.separatorColor.cgColor
        stack.layer?.borderWidth = 1
        stack.layer?.cornerRadius = 8

        let titleLabel = NSTextField(labelWithString: title)
        titleLabel.font = .preferredFont(forTextStyle: .headline)
        let subtitleLabel = NSTextField(labelWithString: subtitle)
        subtitleLabel.textColor = .secondaryLabelColor
        subtitleLabel.maximumNumberOfLines = 2
        subtitleLabel.lineBreakMode = .byWordWrapping
        stack.addArrangedSubview(titleLabel)
        stack.addArrangedSubview(subtitleLabel)
        return stack
    }

    private func selectedScrollView() -> NSScrollView {
        let scroll = NSScrollView()
        scroll.borderType = .bezelBorder
        scroll.documentView = selectedJournalStack
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.autohidesScrollers = true
        scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 280).isActive = true
        return scroll
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

    private func manualAddRow() -> NSStackView {
        let addButton = NSButton(title: "Add", target: self, action: #selector(addManualJournal))
        addButton.bezelStyle = .rounded
        addButton.widthAnchor.constraint(equalToConstant: 72).isActive = true
        let row = NSStackView(views: [manualJournalField, addButton])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        return row
    }

    private func candidateHeaderRow() -> NSStackView {
        candidateCountLabel.textColor = .secondaryLabelColor
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let row = NSStackView(views: [spacer, candidateCountLabel])
        row.orientation = .horizontal
        row.alignment = .centerY
        return row
    }

    private func preprintSection() -> NSView {
        let section = NSStackView()
        section.orientation = .vertical
        section.alignment = .leading
        section.spacing = 8
        section.edgeInsets = NSEdgeInsets(top: 10, left: 10, bottom: 10, right: 10)
        section.wantsLayer = true
        section.layer?.borderColor = NSColor.separatorColor.cgColor
        section.layer?.borderWidth = 1
        section.layer?.cornerRadius = 8

        let title = NSTextField(labelWithString: "Preprint Sources")
        title.font = .preferredFont(forTextStyle: .headline)
        let note = NSTextField(labelWithString: "Optional preprint feeds remain off unless selected.")
        note.textColor = .secondaryLabelColor
        note.lineBreakMode = .byWordWrapping
        note.maximumNumberOfLines = 2

        preprintEntries.forEach { entry in
            let button = NSButton(
                checkboxWithTitle: entry.journal,
                target: self,
                action: #selector(togglePreprintSource(_:))
            )
            button.identifier = NSUserInterfaceItemIdentifier(entry.journal)
            button.toolTip = entry.level.isEmpty ? nil : entry.level
            preprintSourceStack.addArrangedSubview(button)
        }

        section.addArrangedSubview(title)
        section.addArrangedSubview(note)
        section.addArrangedSubview(preprintSourceStack)
        return section
    }

    private func refreshPreprintSources() {
        for arrangedSubview in preprintSourceStack.arrangedSubviews {
            guard
                let button = arrangedSubview as? NSButton,
                let journal = button.identifier?.rawValue
            else {
                continue
            }
            button.state = isJournalSelected(journal) ? .on : .off
        }
    }

    private func applyFilter() {
        let query = searchField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let entries = Self.formalJournalEntries(in: catalog)
            .filter { !isJournalSelected($0.journal) }
        if query.isEmpty {
            filteredEntries = entries
        } else {
            filteredEntries = entries.filter { entry in
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
        emitChange()
    }

    private func setSelected(_ selected: Bool, journal: String) {
        var selection = JournalSelection(
            topN: settings.journalScope.topN,
            selectedJournals: settings.journalScope.selectedJournals
        )
        selection.setSelected(selected, journal: journal)
        settings.journalScope.selectedJournals = selection.selectedJournals
        if selected, catalog.entry(named: journal) == nil {
            addExtraCandidate(journal)
        }
        refreshControls()
        emitChange()
    }

    private func addExtraCandidate(_ journal: String) {
        let clean = journal.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else {
            return
        }
        let key = normalizedJournalName(clean)
        if catalog.entry(named: clean) == nil && !extraCandidateJournals.contains(where: { normalizedJournalName($0) == key }) {
            extraCandidateJournals.append(clean)
        }
    }

    private func refreshControls() {
        let topN = SettingsNormalizer.clampedTopN(settings.journalScope.topN)
        topNField.integerValue = topN
        topNStepper.integerValue = topN
        syncExtraCandidatesFromSelection()
        refreshSelectedJournalList()
        refreshPreprintSources()
        selectedCountLabel.stringValue = "Selected \(settings.journalScope.selectedJournals.count)"
        candidateCountLabel.stringValue = "Available \(filteredEntries.count)"
        applyFilter()
    }

    private func refreshSelectedJournalList() {
        selectedJournalStack.arrangedSubviews.forEach { subview in
            selectedJournalStack.removeArrangedSubview(subview)
            subview.removeFromSuperview()
        }
        if settings.journalScope.selectedJournals.isEmpty {
            let empty = NSTextField(labelWithString: "No journals selected.")
            empty.textColor = .secondaryLabelColor
            empty.alignment = .center
            selectedJournalStack.addArrangedSubview(empty)
            return
        }
        settings.journalScope.selectedJournals.forEach { journal in
            let button = DraggableJournalButton(title: selectedButtonTitle(for: journal), target: self, action: #selector(removeSelectedJournal(_:)))
            button.identifier = NSUserInterfaceItemIdentifier(journal)
            button.journal = journal
            button.alignment = .left
            button.bezelStyle = .rounded
            button.toolTip = "Remove \(journal)"
            selectedJournalStack.addArrangedSubview(button)
        }
    }

    private func selectedButtonTitle(for journal: String) -> String {
        if let entry = catalog.entry(named: journal), let impact = entry.impactFactor {
            return "\(entry.journal)  IF \(String(format: "%.1f", impact))"
        }
        return journal
    }

    private func refreshEmptyState() {
        if catalog.entries.isEmpty {
            emptyLabel.stringValue = "Journal catalog unavailable"
            emptyLabel.isHidden = false
        } else if filteredEntries.isEmpty {
            emptyLabel.stringValue = "No matching candidate journals"
            emptyLabel.isHidden = false
        } else {
            emptyLabel.isHidden = true
        }
        candidateCountLabel.stringValue = "Available \(filteredEntries.count)"
    }

    private func syncExtraCandidatesFromSelection() {
        settings.journalScope.selectedJournals
            .filter { catalog.entry(named: $0) == nil }
            .forEach { addExtraCandidate($0) }
    }

    private func isJournalSelected(_ journal: String) -> Bool {
        let key = normalizedJournalName(journal)
        return settings.journalScope.selectedJournals.contains { normalizedJournalName($0) == key }
    }

    private func normalizedJournalName(_ value: String) -> String {
        DualListSelection.normalizedKey(value)
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
        syncExtraCandidatesFromSelection()
        refreshControls()
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

    @objc private func addManualJournal() {
        let clean = manualJournalField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else {
            return
        }
        setSelected(true, journal: clean)
        manualJournalField.stringValue = ""
    }

    @objc private func removeSelectedJournal(_ sender: NSButton) {
        guard let journal = sender.identifier?.rawValue else {
            return
        }
        setSelected(false, journal: journal)
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

    @objc private func togglePreprintSource(_ sender: NSButton) {
        guard let journal = sender.identifier?.rawValue else {
            return
        }
        setSelected(sender.state == .on, journal: journal)
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

    var preprintSourceNamesForTesting: [String] {
        _ = view
        return preprintEntries.map(\.journal)
    }

    var preprintSourceSelectionForTesting: [String: Bool] {
        _ = view
        return Dictionary(uniqueKeysWithValues: preprintEntries.map { entry in
            (entry.journal, isJournalSelected(entry.journal))
        })
    }

    func applyTopNForTesting(_ value: Int) {
        _ = view
        updateTopN(value)
    }

    func toggleJournalForTesting(_ journal: String, selected: Bool) {
        _ = view
        setSelected(selected, journal: journal)
    }

    func togglePreprintSourceForTesting(_ journal: String, selected: Bool) {
        _ = view
        setSelected(selected, journal: journal)
    }

    func addManualJournalForTesting(_ journal: String) {
        _ = view
        manualJournalField.stringValue = journal
        addManualJournal()
    }

    func filterForTesting(_ query: String) {
        _ = view
        searchField.stringValue = query
        applyFilter()
    }

    private static func formalJournalEntries(in catalog: JournalCatalog) -> [JournalCatalogEntry] {
        catalog.entriesByImpactFactor.filter(\.defaultSelected)
    }

    private static func preprintSourceEntries(in catalog: JournalCatalog) -> [JournalCatalogEntry] {
        catalog.entriesByImpactFactor.filter { !$0.defaultSelected }
    }
}

extension JournalFilterViewController: NSTableViewDataSource, NSTableViewDelegate {
    func numberOfRows(in tableView: NSTableView) -> Int {
        filteredEntries.count
    }

    func tableView(_ tableView: NSTableView, shouldSelectRow row: Int) -> Bool {
        guard filteredEntries.indices.contains(row) else {
            return false
        }
        setSelected(true, journal: filteredEntries[row].journal)
        return false
    }

    func tableView(_ tableView: NSTableView, pasteboardWriterForRow row: Int) -> NSPasteboardWriting? {
        guard filteredEntries.indices.contains(row) else {
            return nil
        }
        let item = NSPasteboardItem()
        item.setString(filteredEntries[row].journal, forType: .paperMonitorJournal)
        item.setString(filteredEntries[row].journal, forType: .string)
        return item
    }

    func tableView(
        _ tableView: NSTableView,
        validateDrop info: NSDraggingInfo,
        proposedRow row: Int,
        proposedDropOperation dropOperation: NSTableView.DropOperation
    ) -> NSDragOperation {
        journal(from: info) == nil ? [] : .move
    }

    func tableView(
        _ tableView: NSTableView,
        acceptDrop info: NSDraggingInfo,
        row: Int,
        dropOperation: NSTableView.DropOperation
    ) -> Bool {
        guard let journal = journal(from: info) else {
            return false
        }
        setSelected(false, journal: journal)
        return true
    }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard filteredEntries.indices.contains(row), let identifier = tableColumn?.identifier else {
            return nil
        }

        let entry = filteredEntries[row]
        switch identifier.rawValue {
        case "selected":
            let button = NSButton(title: "+", target: self, action: #selector(addCandidateJournal(_:)))
            button.bezelStyle = .rounded
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

    @objc private func addCandidateJournal(_ sender: NSButton) {
        guard filteredEntries.indices.contains(sender.tag) else {
            return
        }
        setSelected(true, journal: filteredEntries[sender.tag].journal)
    }

    private func journal(from info: NSDraggingInfo) -> String? {
        let pasteboard = info.draggingPasteboard
        let value = pasteboard.string(forType: .paperMonitorJournal) ?? pasteboard.string(forType: .string)
        let clean = DualListSelection.normalizedDisplayValue(value ?? "")
        return clean.isEmpty ? nil : clean
    }
}
