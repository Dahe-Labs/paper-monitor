import Foundation

public struct JournalCatalogEntry: Equatable, Decodable {
    public let rank: Int
    public let journal: String
    public let aliases: [String]
    public let impactFactor: Double?
    public let impactFactorYear: Int?
    public let fiveYearImpactFactor: Double?
    public let level: String
    public let sourceURL: String
    public let defaultSelected: Bool
    public let category: String
    public let impactMetric: String
    public let impactLabel: String

    public init(
        rank: Int,
        journal: String,
        aliases: [String],
        impactFactor: Double?,
        impactFactorYear: Int?,
        fiveYearImpactFactor: Double?,
        level: String,
        sourceURL: String,
        defaultSelected: Bool = true,
        category: String = "",
        impactMetric: String = "Journal Impact Factor",
        impactLabel: String = "IF"
    ) {
        self.rank = rank
        self.journal = journal
        self.aliases = aliases
        self.impactFactor = impactFactor
        self.impactFactorYear = impactFactorYear
        self.fiveYearImpactFactor = fiveYearImpactFactor
        self.level = level
        self.sourceURL = sourceURL
        self.defaultSelected = defaultSelected
        self.category = category
        self.impactMetric = impactMetric
        self.impactLabel = impactLabel
    }

    enum CodingKeys: String, CodingKey {
        case rank
        case journal
        case aliases
        case impactFactor = "impact_factor"
        case impactFactorYear = "impact_factor_year"
        case fiveYearImpactFactor = "five_year_impact_factor"
        case level
        case sourceURL = "source_url"
        case defaultSelected = "default_selected"
        case category
        case impactMetric = "impact_metric"
        case impactLabel = "impact_label"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            rank: try container.decode(Int.self, forKey: .rank),
            journal: try container.decode(String.self, forKey: .journal),
            aliases: try container.decodeIfPresent([String].self, forKey: .aliases) ?? [],
            impactFactor: try container.decodeIfPresent(Double.self, forKey: .impactFactor),
            impactFactorYear: try container.decodeIfPresent(Int.self, forKey: .impactFactorYear),
            fiveYearImpactFactor: try container.decodeIfPresent(Double.self, forKey: .fiveYearImpactFactor),
            level: try container.decodeIfPresent(String.self, forKey: .level) ?? "",
            sourceURL: try container.decodeIfPresent(String.self, forKey: .sourceURL) ?? "",
            defaultSelected: try container.decodeIfPresent(Bool.self, forKey: .defaultSelected) ?? true,
            category: try container.decodeIfPresent(String.self, forKey: .category) ?? "",
            impactMetric: try container.decodeIfPresent(String.self, forKey: .impactMetric) ?? "Journal Impact Factor",
            impactLabel: try container.decodeIfPresent(String.self, forKey: .impactLabel) ?? "IF"
        )
    }
}

public struct JournalCatalog: Equatable {
    public let entries: [JournalCatalogEntry]

    public static func load(from url: URL) throws -> JournalCatalog {
        let data = try Data(contentsOf: url)
        let payload = try JSONDecoder().decode(Payload.self, from: data)
        return JournalCatalog(entries: payload.journals.sorted { $0.rank < $1.rank })
    }

    public var entriesByImpactFactor: [JournalCatalogEntry] {
        Self.entriesSortedByImpactFactor(entries)
    }

    public func topJournals(_ count: Int) -> [JournalCatalogEntry] {
        Array(entriesByImpactFactor.filter(\.defaultSelected).prefix(SettingsNormalizer.clampedTopN(count)))
    }

    public func entry(named journal: String) -> JournalCatalogEntry? {
        let key = Self.normalizedName(journal)
        guard !key.isEmpty else {
            return nil
        }

        return entries.first { entry in
            Self.normalizedName(entry.journal) == key
                || entry.aliases.contains { Self.normalizedName($0) == key }
        }
    }

    public static func entriesSortedByImpactFactor(_ entries: [JournalCatalogEntry]) -> [JournalCatalogEntry] {
        entries.sorted { lhs, rhs in
            switch (lhs.impactFactor, rhs.impactFactor) {
            case let (lhsImpact?, rhsImpact?):
                if lhsImpact != rhsImpact {
                    return lhsImpact > rhsImpact
                }
            case (_?, nil):
                return true
            case (nil, _?):
                return false
            case (nil, nil):
                break
            }

            if lhs.rank != rhs.rank {
                return lhs.rank < rhs.rank
            }
            return lhs.journal.localizedCaseInsensitiveCompare(rhs.journal) == .orderedAscending
        }
    }

    private static func normalizedName(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .split(separator: " ")
            .joined(separator: " ")
    }

    private struct Payload: Decodable {
        let journals: [JournalCatalogEntry]
    }
}
