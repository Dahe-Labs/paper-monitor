import Foundation

public struct JournalScope: Equatable, Codable, Sendable {
    public var topN: Int
    public var selectedJournals: [String]

    public init(topN: Int, selectedJournals: [String]) {
        self.topN = topN
        self.selectedJournals = selectedJournals
    }

    enum CodingKeys: String, CodingKey {
        case topN = "top_n"
        case selectedJournals = "selected_journals"
    }
}

public struct SearchDirection: Equatable, Codable, Sendable {
    public var preset: String
    public var label: String
    public var crossrefQuery: String
    public var openalexQuery: String
    public var queryManuallyEdited: Bool

    public init(
        preset: String,
        label: String,
        crossrefQuery: String,
        openalexQuery: String,
        queryManuallyEdited: Bool
    ) {
        self.preset = preset
        self.label = label
        self.crossrefQuery = crossrefQuery
        self.openalexQuery = openalexQuery
        self.queryManuallyEdited = queryManuallyEdited
    }

    enum CodingKeys: String, CodingKey {
        case preset
        case label
        case crossrefQuery = "crossref_query"
        case openalexQuery = "openalex_query"
        case queryManuallyEdited = "query_manually_edited"
    }
}

public struct RuntimeAppSettings: Equatable, Sendable {
    public var startupEnabled: Bool
    public var showTrayIcon: Bool
    public var notificationsEnabled: Bool
    public var silentStartupNotifications: Bool
    public var refreshOnLaunch: Bool

    public init(
        startupEnabled: Bool,
        showTrayIcon: Bool,
        notificationsEnabled: Bool,
        silentStartupNotifications: Bool,
        refreshOnLaunch: Bool
    ) {
        self.startupEnabled = startupEnabled
        self.showTrayIcon = showTrayIcon
        self.notificationsEnabled = notificationsEnabled
        self.silentStartupNotifications = silentStartupNotifications
        self.refreshOnLaunch = refreshOnLaunch
    }

    public static let `default` = RuntimeAppSettings(
        startupEnabled: false,
        showTrayIcon: true,
        notificationsEnabled: true,
        silentStartupNotifications: true,
        refreshOnLaunch: true
    )
}

public struct OpenAlexSourceSettings: Equatable, Sendable {
    public var enabled: Bool
    public var daysBack: Int
    public var perPage: Int
    public var maxPages: Int
    public var apiKey: String

    public init(
        enabled: Bool,
        daysBack: Int,
        perPage: Int,
        maxPages: Int,
        apiKey: String
    ) {
        self.enabled = enabled
        self.daysBack = daysBack
        self.perPage = perPage
        self.maxPages = maxPages
        self.apiKey = apiKey
    }

    public static let `default` = OpenAlexSourceSettings(
        enabled: false,
        daysBack: 15,
        perPage: 100,
        maxPages: 3,
        apiKey: ""
    )
}

public struct AppSettings: Equatable, Sendable {
    public var schemaVersion: Int
    public var journalScope: JournalScope
    public var intervalSeconds: Int
    public var refreshStartTime: String
    public var runtime: RuntimeAppSettings
    public var includeTerms: [String]
    public var excludeTerms: [String]
    public var searchDirection: SearchDirection
    public var openAlex: OpenAlexSourceSettings

    public init(
        schemaVersion: Int,
        journalScope: JournalScope,
        intervalSeconds: Int,
        refreshStartTime: String = "",
        runtime: RuntimeAppSettings = .default,
        includeTerms: [String],
        excludeTerms: [String],
        searchDirection: SearchDirection,
        openAlex: OpenAlexSourceSettings = .default
    ) {
        self.schemaVersion = schemaVersion
        self.journalScope = journalScope
        self.intervalSeconds = intervalSeconds
        self.refreshStartTime = refreshStartTime
        self.runtime = runtime
        self.includeTerms = includeTerms
        self.excludeTerms = excludeTerms
        self.searchDirection = searchDirection
        self.openAlex = openAlex
    }

    public static let `default` = AppSettings(
        schemaVersion: 2,
        journalScope: JournalScope(topN: 15, selectedJournals: []),
        intervalSeconds: 43_200,
        refreshStartTime: "",
        runtime: .default,
        includeTerms: [],
        excludeTerms: [],
        searchDirection: SearchPresetCatalog.bundled.defaultSearchDirection(),
        openAlex: .default
    )
}

@MainActor
final class SettingsEditingState {
    var settings: AppSettings

    init(settings: AppSettings) {
        self.settings = settings
    }

    func update(_ mutate: (inout AppSettings) -> Void) -> AppSettings {
        mutate(&settings)
        return settings
    }
}

public enum SettingsNormalizer {
    public static func clampedTopN(_ value: Int) -> Int {
        min(50, max(1, value))
    }

    public static func dedupeNonEmpty(_ values: [String]) -> [String] {
        var result: [String] = []
        var seen = Set<String>()
        for value in values {
            let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
            let key = text.lowercased().split(separator: " ").joined(separator: " ")
            if !text.isEmpty, !seen.contains(key) {
                seen.insert(key)
                result.append(text)
            }
        }
        return result
    }

    public static func normalizedRefreshStartTime(_ value: String) -> String? {
        AppRefreshSettings.normalizedRefreshStartTime(value)
    }

    public static func clampedOpenAlexDaysBack(_ value: Int) -> Int {
        min(3650, max(1, value))
    }

    public static func clampedOpenAlexPerPage(_ value: Int) -> Int {
        min(200, max(1, value))
    }

    public static func clampedOpenAlexMaxPages(_ value: Int) -> Int {
        min(50, max(1, value))
    }
}

public struct SearchPresetDefinition: Equatable, Codable, Sendable {
    public var id: String
    public var label: String
    public var crossrefQuery: String
    public var openalexQuery: String
    public var includeTerms: [String]
    public var excludeTerms: [String]
    public var aliases: [String]
    public var isCustom: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case label
        case crossrefQuery = "crossref_query"
        case openalexQuery = "openalex_query"
        case includeTerms = "include_terms"
        case excludeTerms = "exclude_terms"
        case aliases
        case isCustom = "is_custom"
    }
}

private enum SearchPresetCatalogError: Error {
    case emptyCatalog
    case missingDefaultPreset(String)
}

public struct SearchPresetCatalog: Equatable, Codable, Sendable {
    public var defaultPresetID: String
    public var presets: [SearchPresetDefinition]

    enum CodingKeys: String, CodingKey {
        case defaultPresetID = "default_preset"
        case presets
    }

    public var selectablePresets: [SearchPresetDefinition] {
        presets.filter { !$0.isCustom }
    }

    public var defaultPreset: SearchPresetDefinition {
        definition(for: defaultPresetID, includeAliases: false) ?? presets.first ?? Self.fallback.presets[0]
    }

    public func definition(for id: String, includeAliases: Bool = true) -> SearchPresetDefinition? {
        let clean = id.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else {
            return nil
        }
        return presets.first { preset in
            preset.id == clean || (includeAliases && preset.aliases.contains(clean))
        }
    }

    public func defaultSearchDirection() -> SearchDirection {
        let preset = defaultPreset
        return SearchDirection(
            preset: preset.id,
            label: preset.label,
            crossrefQuery: preset.crossrefQuery,
            openalexQuery: preset.openalexQuery,
            queryManuallyEdited: false
        )
    }

    public func apply(_ preset: SearchPresetDefinition, to settings: inout AppSettings) {
        settings.searchDirection.preset = preset.id
        settings.searchDirection.label = preset.label
        settings.searchDirection.crossrefQuery = preset.crossrefQuery
        settings.searchDirection.openalexQuery = preset.openalexQuery
        settings.includeTerms = SettingsNormalizer.dedupeNonEmpty(preset.includeTerms)
        settings.excludeTerms = SettingsNormalizer.dedupeNonEmpty(preset.excludeTerms)
        settings.searchDirection.queryManuallyEdited = false
    }

    public func regenerateQueriesIfAllowed(for settings: inout AppSettings) {
        guard !settings.searchDirection.queryManuallyEdited else {
            return
        }
        settings.searchDirection.crossrefQuery = settings.includeTerms.joined(separator: " OR ")
        settings.searchDirection.openalexQuery = settings.includeTerms.joined(separator: " OR ")
    }

    public static let bundled = loadBundledOrFallback()

    public static func load(from url: URL) throws -> SearchPresetCatalog {
        let catalog = try JSONDecoder().decode(SearchPresetCatalog.self, from: Data(contentsOf: url))
        try catalog.validate()
        return catalog
    }

    private func validate() throws {
        guard !presets.isEmpty else {
            throw SearchPresetCatalogError.emptyCatalog
        }
        guard definition(for: defaultPresetID, includeAliases: false) != nil else {
            throw SearchPresetCatalogError.missingDefaultPreset(defaultPresetID)
        }
    }

    private static func loadBundledOrFallback() -> SearchPresetCatalog {
        for url in candidateURLs() {
            if let catalog = try? load(from: url), !catalog.presets.isEmpty {
                return catalog
            }
        }
        return fallback
    }

    private static func candidateURLs() -> [URL] {
        var urls: [URL] = []
        if let bundled = Bundle.main.url(
            forResource: "search_direction_presets",
            withExtension: "json",
            subdirectory: "paper_monitor/resources"
        ) {
            urls.append(bundled)
        }
        let current = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        urls.append(current.appendingPathComponent("../../paper_monitor/resources/search_direction_presets.json"))
        urls.append(current.appendingPathComponent("paper_monitor/resources/search_direction_presets.json"))
        return urls
    }

    private static let fallback = SearchPresetCatalog(
        defaultPresetID: "solid_state_battery_general",
        presets: [
            SearchPresetDefinition(
                id: "solid_state_battery_general",
                label: "Solid-state battery general",
                crossrefQuery: "solid electrolyte OR electrolyte OR all-solid-state battery OR solid-state battery OR electrode OR LLZTO OR LLZO OR silicon anode OR Si anode OR NCM",
                openalexQuery: "solid electrolyte OR electrolyte OR all-solid-state battery OR solid-state battery OR electrode OR LLZTO OR LLZO OR silicon anode OR Si anode OR NCM",
                includeTerms: ["all-solid-state battery", "solid-state battery", "solid electrolyte", "electrolyte", "electrode", "LLZTO", "LLZO", "silicon anode", "Si anode", "NCM"],
                excludeTerms: ["solid-state laser", "solid state laser", "solid-state lighting", "solid-state drive"],
                aliases: [],
                isCustom: false
            ),
            SearchPresetDefinition(
                id: "solid_electrolyte",
                label: "Solid electrolyte",
                crossrefQuery: "solid electrolyte OR sulfide electrolyte OR oxide electrolyte OR halide electrolyte OR argyrodite OR LLZO OR LLZTO OR NASICON",
                openalexQuery: "solid electrolyte OR sulfide electrolyte OR oxide electrolyte OR halide electrolyte OR argyrodite OR LLZO OR LLZTO OR NASICON",
                includeTerms: ["solid electrolyte", "sulfide electrolyte", "oxide electrolyte", "halide electrolyte", "argyrodite", "LLZO", "LLZTO", "NASICON"],
                excludeTerms: ["solid-state laser", "solid state laser", "solid-state lighting", "solid-state drive"],
                aliases: [],
                isCustom: false
            ),
            SearchPresetDefinition(
                id: "lithium_metal_anode",
                label: "Lithium metal anode",
                crossrefQuery: "lithium metal anode OR Li metal anode OR dendrite OR lithium dendrite OR solid electrolyte interphase OR SEI",
                openalexQuery: "lithium metal anode OR Li metal anode OR dendrite OR lithium dendrite OR solid electrolyte interphase OR SEI",
                includeTerms: ["lithium metal anode", "Li metal anode", "dendrite", "lithium dendrite", "solid electrolyte interphase", "SEI"],
                excludeTerms: ["solid-state laser", "solid state laser", "solid-state lighting", "solid-state drive"],
                aliases: [],
                isCustom: false
            ),
            SearchPresetDefinition(
                id: "interface_interphase",
                label: "Interface / interphase",
                crossrefQuery: "solid electrolyte interface OR interphase OR interfacial impedance OR space charge layer OR cathode interface OR anode interface",
                openalexQuery: "solid electrolyte interface OR interphase OR interfacial impedance OR space charge layer OR cathode interface OR anode interface",
                includeTerms: ["solid electrolyte interface", "interphase", "interfacial impedance", "space charge layer", "cathode interface", "anode interface"],
                excludeTerms: ["solid-state laser", "solid state laser", "solid-state lighting", "solid-state drive"],
                aliases: ["interface_impedance"],
                isCustom: false
            ),
            SearchPresetDefinition(
                id: "custom",
                label: "Custom",
                crossrefQuery: "",
                openalexQuery: "",
                includeTerms: [],
                excludeTerms: [],
                aliases: ["cathode_materials"],
                isCustom: true
            ),
        ]
    )
}

public enum SearchTermEditor {
    public static func updateIncludeTerms(_ terms: [String], in settings: inout AppSettings) {
        settings.includeTerms = SettingsNormalizer.dedupeNonEmpty(terms)
        SearchPresetCatalog.bundled.regenerateQueriesIfAllowed(for: &settings)
    }

    public static func updateExcludeTerms(_ terms: [String], in settings: inout AppSettings) {
        settings.excludeTerms = SettingsNormalizer.dedupeNonEmpty(terms)
    }
}

public enum SearchPreset: String, CaseIterable {
    case solidStateBatteryGeneral = "solid_state_battery_general"
    case solidElectrolyte = "solid_electrolyte"
    case interfaceImpedance = "interface_impedance"
    case lithiumMetalAnode = "lithium_metal_anode"
    case cathodeMaterials = "cathode_materials"

    public var label: String {
        definition?.label ?? rawValue
    }

    public var includeTerms: [String] {
        definition?.includeTerms ?? []
    }

    public var excludeTerms: [String] {
        definition?.excludeTerms ?? []
    }

    public func apply(to settings: inout AppSettings) {
        guard let definition else {
            return
        }
        SearchPresetCatalog.bundled.apply(definition, to: &settings)
    }

    public static func regenerateQueriesIfAllowed(for settings: inout AppSettings) {
        SearchPresetCatalog.bundled.regenerateQueriesIfAllowed(for: &settings)
    }

    private var definition: SearchPresetDefinition? {
        SearchPresetCatalog.bundled.definition(for: rawValue)
    }
}

enum SearchSettingsPolicy {
    static func applyTopN(_ value: Int, to settings: inout AppSettings, catalog: JournalCatalog?) {
        let topN = SettingsNormalizer.clampedTopN(value)
        settings.journalScope.topN = topN

        guard let catalog, !catalog.entries.isEmpty else {
            return
        }

        var selection = JournalSelection(
            topN: topN,
            selectedJournals: settings.journalScope.selectedJournals
        )
        selection.applyTopN(catalog)
        if !selection.selectedJournals.isEmpty {
            settings.journalScope.selectedJournals = selection.selectedJournals
        }
    }

    static func windowSettings(loaded: AppSettings?, catalog: JournalCatalog?) -> AppSettings {
        var settings = loaded ?? .default
        if settings.journalScope.selectedJournals.isEmpty {
            applyTopN(settings.journalScope.topN, to: &settings, catalog: catalog)
        }
        return settings
    }
}

public struct JournalSelection: Equatable {
    public var topN: Int
    public private(set) var selectedJournals: [String]

    public init(topN: Int, selectedJournals: [String]) {
        self.topN = SettingsNormalizer.clampedTopN(topN)
        self.selectedJournals = SettingsNormalizer.dedupeNonEmpty(selectedJournals)
    }

    public mutating func applyTopN(_ catalog: JournalCatalog) {
        let preservedSources = selectedJournals.filter { journal in
            guard let entry = catalog.entry(named: journal) else {
                return true
            }
            return entry.defaultSelected == false
        }
        selectedJournals = SettingsNormalizer.dedupeNonEmpty(
            catalog.topJournals(topN).map(\.journal) + preservedSources
        )
    }

    public mutating func setSelected(_ selected: Bool, journal: String) {
        var selection = DualListSelection(selectedItems: selectedJournals)
        if selected {
            selection.add(journal)
        } else if selection.selectedItems.count > 1 {
            selection.remove(journal)
        }
        selectedJournals = selection.selectedItems
    }
}

public struct DualListSelection: Equatable, Sendable {
    public private(set) var selectedItems: [String]

    public init(selectedItems: [String]) {
        self.selectedItems = SettingsNormalizer.dedupeNonEmpty(selectedItems)
    }

    public mutating func add(_ value: String) {
        let clean = Self.normalizedDisplayValue(value)
        guard !clean.isEmpty else {
            return
        }
        selectedItems = SettingsNormalizer.dedupeNonEmpty(selectedItems + [clean])
    }

    public mutating func remove(_ value: String) {
        let key = Self.normalizedKey(value)
        guard !key.isEmpty else {
            return
        }
        selectedItems.removeAll { Self.normalizedKey($0) == key }
    }

    public mutating func setSelected(_ selected: Bool, value: String) {
        if selected {
            add(value)
        } else {
            remove(value)
        }
    }

    public func contains(_ value: String) -> Bool {
        let key = Self.normalizedKey(value)
        return selectedItems.contains { Self.normalizedKey($0) == key }
    }

    public static func availableItems(candidates: [String], selectedItems: [String]) -> [String] {
        let selectedKeys = Set(SettingsNormalizer.dedupeNonEmpty(selectedItems).map(normalizedKey))
        return SettingsNormalizer.dedupeNonEmpty(candidates).filter { !selectedKeys.contains(normalizedKey($0)) }
    }

    public static func normalizedDisplayValue(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: " ")
    }

    public static func normalizedKey(_ value: String) -> String {
        normalizedDisplayValue(value).lowercased()
    }
}

enum SettingsEditorLoadPolicyError: Error, Equatable {
    case noSelectedJournals
}

enum SettingsEditorLoadPolicy {
    static func settingsForEditor(load: () throws -> AppSettings, catalog: JournalCatalog?) throws -> AppSettings {
        let settings = SearchSettingsPolicy.windowSettings(loaded: try load(), catalog: catalog)
        if settings.journalScope.selectedJournals.isEmpty {
            throw SettingsEditorLoadPolicyError.noSelectedJournals
        }
        return settings
    }
}

enum RefreshSchedulePolicy {
    static func shouldReschedule(lastScheduledSettings: AppRefreshSettings.Schedule?, settings: AppSettings) -> Bool {
        let next = AppRefreshSettings.Schedule(
            intervalSeconds: TimeInterval(settings.intervalSeconds),
            refreshStartTime: settings.refreshStartTime
        )
        return next != lastScheduledSettings
    }
}

protocol SearchSettingsDebounceToken: AnyObject {
    func cancel()
}

@MainActor
final class SearchSettingsChangeDebouncer {
    typealias Scheduler = @MainActor (
        _ delay: TimeInterval,
        _ action: @escaping @MainActor @Sendable () -> Void
    ) -> SearchSettingsDebounceToken

    private let delay: TimeInterval
    private let scheduler: Scheduler
    private let onPending: (@MainActor @Sendable (AppSettings) -> Void)?
    private let onChange: @MainActor @Sendable (AppSettings) -> Bool
    private var generation = 0
    private var token: SearchSettingsDebounceToken?
    private var pendingSettingsProvider: (@MainActor @Sendable () -> AppSettings)?

    init(
        delay: TimeInterval = 0.6,
        scheduler: @escaping Scheduler = SearchSettingsChangeDebouncer.defaultScheduler,
        onPending: (@MainActor @Sendable (AppSettings) -> Void)? = nil,
        onChange: @escaping @MainActor @Sendable (AppSettings) -> Bool
    ) {
        self.delay = delay
        self.scheduler = scheduler
        self.onPending = onPending
        self.onChange = onChange
    }

    func schedule(_ settings: AppSettings) {
        scheduleLatest { settings }
    }

    func scheduleLatest(_ latestSettings: @escaping @MainActor @Sendable () -> AppSettings) {
        generation += 1
        let scheduledGeneration = generation
        pendingSettingsProvider = latestSettings
        onPending?(latestSettings())
        token?.cancel()
        token = scheduler(delay) { [weak self] in
            guard let self, scheduledGeneration == self.generation else {
                return
            }
            guard let pendingSettingsProvider = self.pendingSettingsProvider else {
                return
            }
            let settings = pendingSettingsProvider()
            self.token = nil
            if self.onChange(settings) {
                self.pendingSettingsProvider = nil
            }
        }
    }

    @discardableResult
    func flush(_ settings: AppSettings) -> Bool {
        generation += 1
        token?.cancel()
        token = nil
        if onChange(settings) {
            pendingSettingsProvider = nil
            return true
        }
        pendingSettingsProvider = { settings }
        return false
    }

    @discardableResult
    func flushPending() -> Bool {
        guard let pendingSettingsProvider else {
            return true
        }
        let settings = pendingSettingsProvider()
        generation += 1
        token?.cancel()
        token = nil
        if onChange(settings) {
            self.pendingSettingsProvider = nil
            return true
        }
        return false
    }

    @discardableResult
    func flushPending(_ settings: AppSettings) -> Bool {
        guard pendingSettingsProvider != nil else {
            return true
        }
        generation += 1
        token?.cancel()
        token = nil
        if onChange(settings) {
            pendingSettingsProvider = nil
            return true
        }
        pendingSettingsProvider = { settings }
        return false
    }

    static func defaultScheduler(
        delay: TimeInterval,
        action: @escaping @MainActor @Sendable () -> Void
    ) -> SearchSettingsDebounceToken {
        let timer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { _ in
            Task { @MainActor in
                action()
            }
        }
        return TimerSearchSettingsDebounceToken(timer: timer)
    }
}

private final class TimerSearchSettingsDebounceToken: SearchSettingsDebounceToken {
    private var timer: Timer?

    init(timer: Timer) {
        self.timer = timer
    }

    func cancel() {
        timer?.invalidate()
        timer = nil
    }
}
