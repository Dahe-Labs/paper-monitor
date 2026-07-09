import Foundation

public enum SettingsStoreError: Error, Equatable, LocalizedError {
    case noSelectedJournals
    case invalidInterval
    case invalidRefreshStartTime
    case missingOpenAlexAPIKey

    public var errorDescription: String? {
        switch self {
        case .noSelectedJournals:
            return "Select at least one journal or source."
        case .invalidInterval:
            return "Refresh interval must be greater than zero."
        case .invalidRefreshStartTime:
            return "Refresh start time must be empty or in HH:MM format."
        case .missingOpenAlexAPIKey:
            return "OpenAlex API key is required when OpenAlex is enabled."
        }
    }
}

public final class SettingsStore {
    private let configURL: URL
    private let fileManager: FileManager

    public init(configURL: URL) {
        self.configURL = configURL
        self.fileManager = .default
    }

    public func load() throws -> AppSettings {
        let payload = try loadPayloadIfPresent()
        var settings = AppSettings.default

        if let schemaVersion = Self.intValue(payload["settings_schema_version"]) {
            settings.schemaVersion = schemaVersion
        }

        let journalScopePayload = Self.dictionary(payload["journal_scope"]) ?? [:]
        let selectedJournals = Self.normalizedSelectedJournals(
            from: journalScopePayload["selected_journals"],
            fallback: payload["journals"]
        )
        let topNFallback = selectedJournals.isEmpty ? settings.journalScope.topN : selectedJournals.count
        let topN = Self.intValue(journalScopePayload["top_n"]) ?? topNFallback
        settings.journalScope = JournalScope(
            topN: SettingsNormalizer.clampedTopN(topN),
            selectedJournals: selectedJournals
        )

        if let intervalSeconds = Self.intValue(payload["interval_seconds"]), intervalSeconds > 0 {
            settings.intervalSeconds = intervalSeconds
        }
        if let refreshStartTime = Self.refreshStartTimeValue(payload["refresh_start_time"]) {
            settings.refreshStartTime = refreshStartTime
        }
        settings.runtime = Self.runtimeAppSettings(payload["app_settings"], fallback: settings.runtime)

        if let includeTerms = Self.stringArray(payload["include_terms"]) {
            settings.includeTerms = SettingsNormalizer.dedupeNonEmpty(includeTerms)
        }
        if let excludeTerms = Self.stringArray(payload["exclude_terms"]) {
            settings.excludeTerms = SettingsNormalizer.dedupeNonEmpty(excludeTerms)
        }

        let searchDirectionPayload = Self.dictionary(payload["search_direction"]) ?? [:]
        let sourcesPayload = Self.dictionary(payload["sources"]) ?? [:]
        let crossrefPayload = Self.dictionary(sourcesPayload["crossref"]) ?? [:]
        let openalexPayload = Self.dictionary(sourcesPayload["openalex"]) ?? [:]
        settings.openAlex = Self.openAlexSourceSettings(openalexPayload, fallback: settings.openAlex)

        var searchDirection = settings.searchDirection
        searchDirection.preset = Self.nonEmptyString(searchDirectionPayload["preset"]) ?? searchDirection.preset
        searchDirection.label = Self.nonEmptyString(searchDirectionPayload["label"]) ?? searchDirection.label
        searchDirection.crossrefQuery = Self.nonEmptyString(searchDirectionPayload["crossref_query"])
            ?? Self.nonEmptyString(crossrefPayload["query"])
            ?? searchDirection.crossrefQuery
        searchDirection.openalexQuery = Self.nonEmptyString(searchDirectionPayload["openalex_query"])
            ?? Self.nonEmptyString(openalexPayload["query"])
            ?? searchDirection.openalexQuery
        searchDirection.queryManuallyEdited = Self.boolValue(searchDirectionPayload["query_manually_edited"])
            ?? searchDirection.queryManuallyEdited
        let requestedPresetID = searchDirection.preset
        if let preset = SearchPresetCatalog.bundled.definition(for: requestedPresetID),
           preset.isCustom {
            searchDirection.preset = preset.id
            searchDirection.queryManuallyEdited = true
        } else if let preset = SearchPresetCatalog.bundled.definition(for: requestedPresetID),
                  !preset.isCustom {
            let wasLegacyAlias = preset.id != requestedPresetID
            searchDirection.preset = preset.id
            searchDirection.label = preset.label
            if wasLegacyAlias && !searchDirection.queryManuallyEdited {
                searchDirection.crossrefQuery = preset.crossrefQuery
                searchDirection.openalexQuery = preset.openalexQuery
                settings.includeTerms = SettingsNormalizer.dedupeNonEmpty(preset.includeTerms)
                settings.excludeTerms = SettingsNormalizer.dedupeNonEmpty(preset.excludeTerms)
            }
        }
        settings.searchDirection = searchDirection

        return settings
    }

    @discardableResult
    public func addIncludeTerm(_ term: String) throws -> AppSettings {
        var settings = try load()
        SearchTermEditor.updateIncludeTerms(settings.includeTerms + [term], in: &settings)
        try save(settings)
        return settings
    }

    public func save(_ settings: AppSettings) throws {
        let selectedJournals = SettingsNormalizer.dedupeNonEmpty(settings.journalScope.selectedJournals)
        guard !selectedJournals.isEmpty else {
            throw SettingsStoreError.noSelectedJournals
        }
        guard settings.intervalSeconds > 0 else {
            throw SettingsStoreError.invalidInterval
        }
        guard let refreshStartTime = SettingsNormalizer.normalizedRefreshStartTime(settings.refreshStartTime) else {
            throw SettingsStoreError.invalidRefreshStartTime
        }
        if settings.openAlex.enabled && settings.openAlex.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw SettingsStoreError.missingOpenAlexAPIKey
        }

        var payload = try loadPayloadIfPresent()
        payload["settings_schema_version"] = max(settings.schemaVersion, 2)
        var journalScope = Self.dictionary(payload["journal_scope"]) ?? [:]
        journalScope["top_n"] = SettingsNormalizer.clampedTopN(settings.journalScope.topN)
        journalScope["selected_journals"] = selectedJournals
        payload["journal_scope"] = journalScope
        payload["interval_seconds"] = settings.intervalSeconds
        payload["refresh_start_time"] = refreshStartTime
        payload["app_settings"] = [
            "startup_enabled": settings.runtime.startupEnabled,
            "show_tray_icon": settings.runtime.showTrayIcon,
            "notifications_enabled": settings.runtime.notificationsEnabled,
            "silent_startup_notifications": settings.runtime.silentStartupNotifications,
            "refresh_on_launch": settings.runtime.refreshOnLaunch,
        ]
        payload["include_terms"] = SettingsNormalizer.dedupeNonEmpty(settings.includeTerms)
        payload["exclude_terms"] = SettingsNormalizer.dedupeNonEmpty(settings.excludeTerms)
        payload["journals"] = selectedJournals
        var searchDirection = Self.dictionary(payload["search_direction"]) ?? [:]
        searchDirection["preset"] = settings.searchDirection.preset
        searchDirection["label"] = settings.searchDirection.label
        searchDirection["crossref_query"] = settings.searchDirection.crossrefQuery
        searchDirection["openalex_query"] = settings.searchDirection.openalexQuery
        searchDirection["query_manually_edited"] = settings.searchDirection.queryManuallyEdited
        payload["search_direction"] = searchDirection

        var sources = Self.dictionary(payload["sources"]) ?? [:]
        var crossref = Self.dictionary(sources["crossref"]) ?? [:]
        crossref["journal_titles"] = Self.formalJournalTitles(selectedJournals)
        crossref["query"] = settings.searchDirection.crossrefQuery
        sources["crossref"] = crossref

        var openalex = Self.dictionary(sources["openalex"]) ?? [:]
        openalex["enabled"] = settings.openAlex.enabled
        openalex["days_back"] = SettingsNormalizer.clampedOpenAlexDaysBack(settings.openAlex.daysBack)
        openalex["per_page"] = SettingsNormalizer.clampedOpenAlexPerPage(settings.openAlex.perPage)
        openalex["max_pages"] = SettingsNormalizer.clampedOpenAlexMaxPages(settings.openAlex.maxPages)
        openalex["api_key"] = settings.openAlex.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        openalex["query"] = settings.searchDirection.openalexQuery
        sources["openalex"] = openalex
        var arxiv = Self.dictionary(sources["arxiv"]) ?? [:]
        arxiv["enabled"] = Self.containsSourceCandidate(selectedJournals, sourceKey: "arxiv")
        sources["arxiv"] = arxiv
        payload["sources"] = sources

        try writePayloadAtomically(payload)
    }

    private func loadPayloadIfPresent() throws -> [String: Any] {
        guard fileManager.fileExists(atPath: configURL.path) else {
            return [:]
        }

        let data = try Data(contentsOf: configURL)
        guard !data.isEmpty else {
            return [:]
        }

        let object = try JSONSerialization.jsonObject(with: data)
        guard let payload = object as? [String: Any] else {
            throw CocoaError(.fileReadCorruptFile)
        }
        return payload
    }

    private func writePayloadAtomically(_ payload: [String: Any]) throws {
        try fileManager.createDirectory(
            at: configURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )

        var data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
        data.append(contentsOf: [0x0A])

        let tempURL = configURL
            .deletingLastPathComponent()
            .appendingPathComponent(".\(configURL.lastPathComponent).\(UUID().uuidString).tmp")
        var tempFileIsPending = false
        do {
            try data.write(to: tempURL, options: [])
            tempFileIsPending = true
            if fileManager.fileExists(atPath: configURL.path) {
                _ = try fileManager.replaceItemAt(
                    configURL,
                    withItemAt: tempURL,
                    backupItemName: nil,
                    options: []
                )
            } else {
                try fileManager.moveItem(at: tempURL, to: configURL)
            }
            tempFileIsPending = false
        } catch {
            if tempFileIsPending {
                try? fileManager.removeItem(at: tempURL)
            }
            throw error
        }
    }

    private static func normalizedSelectedJournals(from value: Any?, fallback: Any?) -> [String] {
        let selectedJournals = SettingsNormalizer.dedupeNonEmpty(stringArray(value) ?? [])
        if !selectedJournals.isEmpty {
            return selectedJournals
        }
        return SettingsNormalizer.dedupeNonEmpty(stringArray(fallback) ?? [])
    }

    private static func formalJournalTitles(_ values: [String]) -> [String] {
        values.filter { normalizedKey($0) != "arxiv" }
    }

    private static func containsSourceCandidate(_ values: [String], sourceKey: String) -> Bool {
        let normalized = normalizedKey(sourceKey)
        return values.contains { normalizedKey($0) == normalized }
    }

    private static func normalizedKey(_ value: String) -> String {
        value.lowercased().split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    private static func dictionary(_ value: Any?) -> [String: Any]? {
        value as? [String: Any]
    }

    private static func stringArray(_ value: Any?) -> [String]? {
        if let strings = value as? [String] {
            return strings
        }
        if let values = value as? [Any] {
            return values.compactMap { $0 as? String }
        }
        return nil
    }

    private static func intValue(_ value: Any?) -> Int? {
        if value is Bool {
            return nil
        }
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite
        else {
            return nil
        }
        return Int(exactly: number)
    }

    private static func boolValue(_ value: Any?) -> Bool? {
        if let value = value as? Bool {
            return value
        }
        if let number = value as? NSNumber {
            return number.boolValue
        }
        if let string = value as? String {
            switch string.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
            case "true", "yes", "1":
                return true
            case "false", "no", "0":
                return false
            default:
                return nil
            }
        }
        return nil
    }

    private static func nonEmptyString(_ value: Any?) -> String? {
        guard let string = value as? String else {
            return nil
        }
        let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func refreshStartTimeValue(_ value: Any?) -> String? {
        guard value != nil else {
            return nil
        }
        return AppRefreshSettings.normalizedRefreshStartTime(value) ?? ""
    }

    private static func runtimeAppSettings(_ value: Any?, fallback: RuntimeAppSettings) -> RuntimeAppSettings {
        let payload = dictionary(value) ?? [:]
        return RuntimeAppSettings(
            startupEnabled: boolValue(payload["startup_enabled"]) ?? fallback.startupEnabled,
            showTrayIcon: boolValue(payload["show_tray_icon"]) ?? fallback.showTrayIcon,
            notificationsEnabled: boolValue(payload["notifications_enabled"]) ?? fallback.notificationsEnabled,
            silentStartupNotifications: boolValue(payload["silent_startup_notifications"]) ?? fallback.silentStartupNotifications,
            refreshOnLaunch: boolValue(payload["refresh_on_launch"]) ?? fallback.refreshOnLaunch
        )
    }

    private static func openAlexSourceSettings(_ payload: [String: Any], fallback: OpenAlexSourceSettings) -> OpenAlexSourceSettings {
        OpenAlexSourceSettings(
            enabled: boolValue(payload["enabled"]) ?? fallback.enabled,
            daysBack: SettingsNormalizer.clampedOpenAlexDaysBack(intValue(payload["days_back"]) ?? fallback.daysBack),
            perPage: SettingsNormalizer.clampedOpenAlexPerPage(intValue(payload["per_page"]) ?? fallback.perPage),
            maxPages: SettingsNormalizer.clampedOpenAlexMaxPages(intValue(payload["max_pages"]) ?? fallback.maxPages),
            apiKey: (stringValue(payload["api_key"]) ?? fallback.apiKey)
                .trimmingCharacters(in: .whitespacesAndNewlines)
        )
    }

    private static func stringValue(_ value: Any?) -> String? {
        guard let string = value as? String else {
            return nil
        }
        return string
    }
}
