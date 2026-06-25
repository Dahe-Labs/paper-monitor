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
    public var keywords: [String]
    public var crossrefQuery: String
    public var openalexQuery: String
    public var queryManuallyEdited: Bool

    public init(
        preset: String,
        label: String,
        keywords: [String],
        crossrefQuery: String,
        openalexQuery: String,
        queryManuallyEdited: Bool
    ) {
        self.preset = preset
        self.label = label
        self.keywords = keywords
        self.crossrefQuery = crossrefQuery
        self.openalexQuery = openalexQuery
        self.queryManuallyEdited = queryManuallyEdited
    }

    enum CodingKeys: String, CodingKey {
        case preset
        case label
        case keywords
        case crossrefQuery = "crossref_query"
        case openalexQuery = "openalex_query"
        case queryManuallyEdited = "query_manually_edited"
    }
}

public struct AppSettings: Equatable, Sendable {
    public var schemaVersion: Int
    public var journalScope: JournalScope
    public var intervalSeconds: Int
    public var refreshStartTime: String
    public var includeTerms: [String]
    public var excludeTerms: [String]
    public var searchDirection: SearchDirection

    public init(
        schemaVersion: Int,
        journalScope: JournalScope,
        intervalSeconds: Int,
        refreshStartTime: String,
        includeTerms: [String],
        excludeTerms: [String],
        searchDirection: SearchDirection
    ) {
        self.schemaVersion = schemaVersion
        self.journalScope = journalScope
        self.intervalSeconds = intervalSeconds
        self.refreshStartTime = refreshStartTime
        self.includeTerms = includeTerms
        self.excludeTerms = excludeTerms
        self.searchDirection = searchDirection
    }

    public static let `default` = AppSettings(
        schemaVersion: 1,
        journalScope: JournalScope(topN: 15, selectedJournals: []),
        intervalSeconds: 43_200,
        refreshStartTime: "",
        includeTerms: [],
        excludeTerms: [],
        searchDirection: SearchDirection(
            preset: "solid_state_battery_general",
            label: "Solid-state battery general",
            keywords: ["solid electrolyte", "all-solid-state battery", "solid-state battery"],
            crossrefQuery: "solid electrolyte OR all-solid-state battery OR solid-state battery",
            openalexQuery: "solid electrolyte all-solid-state battery solid-state battery",
            queryManuallyEdited: false
        )
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
}

public enum SearchTermEditor {
    public static func updateIncludeTerms(_ terms: [String], in settings: inout AppSettings) {
        settings.includeTerms = SettingsNormalizer.dedupeNonEmpty(terms)
        settings.searchDirection.keywords = settings.includeTerms
        SearchPreset.regenerateQueriesIfAllowed(for: &settings)
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
        switch self {
        case .solidStateBatteryGeneral:
            return "Solid-state battery general"
        case .solidElectrolyte:
            return "Solid electrolyte"
        case .interfaceImpedance:
            return "Interface / impedance"
        case .lithiumMetalAnode:
            return "Lithium metal anode"
        case .cathodeMaterials:
            return "Cathode materials"
        }
    }

    public var includeTerms: [String] {
        switch self {
        case .solidStateBatteryGeneral:
            return ["all-solid-state battery", "solid-state battery", "solid electrolyte", "electrolyte", "electrode"]
        case .solidElectrolyte:
            return ["solid electrolyte", "sulfide electrolyte", "oxide electrolyte", "halide electrolyte", "LLZO", "LLZTO"]
        case .interfaceImpedance:
            return ["interface", "interfacial impedance", "space charge", "lithium dendrite"]
        case .lithiumMetalAnode:
            return ["lithium metal anode", "Li metal", "dendrite", "anode interface"]
        case .cathodeMaterials:
            return ["cathode", "NCM", "LFP", "layered oxide", "positive electrode"]
        }
    }

    public var excludeTerms: [String] {
        ["solid-state laser", "solid state laser", "solid-state lighting", "solid-state drive"]
    }

    public func apply(to settings: inout AppSettings) {
        settings.searchDirection.preset = rawValue
        settings.searchDirection.label = label
        settings.includeTerms = includeTerms
        settings.searchDirection.keywords = includeTerms
        settings.excludeTerms = excludeTerms
        settings.searchDirection.queryManuallyEdited = false
        SearchPreset.regenerateQueriesIfAllowed(for: &settings)
    }

    public static func regenerateQueriesIfAllowed(for settings: inout AppSettings) {
        guard !settings.searchDirection.queryManuallyEdited else {
            return
        }
        settings.searchDirection.crossrefQuery = settings.includeTerms.joined(separator: " OR ")
        settings.searchDirection.openalexQuery = settings.includeTerms.joined(separator: " ")
    }
}

public enum SearchDirectionEditor {
    public static let customPresetIdentifier = "custom"

    public static func keywords(from text: String) -> [String] {
        let separators = CharacterSet(charactersIn: ",;\n")
        return SettingsNormalizer.dedupeNonEmpty(text.components(separatedBy: separators))
    }

    public static func applyCustomDirection(label: String, keywords: [String], to settings: inout AppSettings) {
        let cleanLabel = label.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanKeywords = SettingsNormalizer.dedupeNonEmpty(keywords)
        settings.searchDirection.preset = customPresetIdentifier
        settings.searchDirection.label = cleanLabel.isEmpty ? "Custom" : cleanLabel
        settings.searchDirection.keywords = cleanKeywords
        settings.includeTerms = cleanKeywords
        settings.searchDirection.queryManuallyEdited = false
        SearchPreset.regenerateQueriesIfAllowed(for: &settings)
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
            catalog.entry(named: journal)?.defaultSelected == false
        }
        selectedJournals = SettingsNormalizer.dedupeNonEmpty(
            catalog.topJournals(topN).map(\.journal) + preservedSources
        )
    }

    public mutating func setSelected(_ selected: Bool, journal: String) {
        let clean = journal.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else {
            return
        }

        if selected {
            selectedJournals = SettingsNormalizer.dedupeNonEmpty(selectedJournals + [clean])
        } else if selectedJournals.count > 1 {
            selectedJournals.removeAll { $0 == clean }
        }
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
    static func shouldReschedule(lastScheduledSettings: RefreshScheduleSettings?, settings: AppSettings) -> Bool {
        RefreshScheduleSettings(
            intervalSeconds: TimeInterval(settings.intervalSeconds),
            startTime: AppRefreshSettings.normalizedStartTime(settings.refreshStartTime)
        ) != lastScheduledSettings
    }

    static func initialDelay(
        interval: TimeInterval,
        startTime: String?,
        now: Date = Date(),
        calendar: Calendar = .current
    ) -> TimeInterval {
        guard interval > 0 else {
            return 0
        }
        guard let startTime = AppRefreshSettings.normalizedStartTime(startTime) else {
            return interval
        }
        let parts = startTime.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else {
            return interval
        }
        var components = calendar.dateComponents([.year, .month, .day], from: now)
        components.hour = parts[0]
        components.minute = parts[1]
        components.second = 0
        guard let today = calendar.date(from: components) else {
            return interval
        }
        if today >= now {
            return today.timeIntervalSince(now)
        }
        guard let tomorrow = calendar.date(byAdding: .day, value: 1, to: today) else {
            return interval
        }
        return tomorrow.timeIntervalSince(now)
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
