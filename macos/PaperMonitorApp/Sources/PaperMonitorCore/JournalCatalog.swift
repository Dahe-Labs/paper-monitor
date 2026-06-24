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

    enum CodingKeys: String, CodingKey {
        case rank
        case journal
        case aliases
        case impactFactor = "impact_factor"
        case impactFactorYear = "impact_factor_year"
        case fiveYearImpactFactor = "five_year_impact_factor"
        case level
        case sourceURL = "source_url"
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
        Array(entriesByImpactFactor.prefix(SettingsNormalizer.clampedTopN(count)))
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

    private struct Payload: Decodable {
        let journals: [JournalCatalogEntry]
    }
}
