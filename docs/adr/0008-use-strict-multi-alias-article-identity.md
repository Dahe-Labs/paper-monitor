# Use strict multi-alias Article Identity

The fingerprint-retention clause below is superseded by [ADR 0018](0018-hard-delete-expired-article-state.md).

Article Identity will match exact normalized aliases in priority order: DOI, stable source identifier, canonical URL, and finally the exact combination of normalized title, first author, and publication year. Paper Monitor will not use fuzzy title matching, and Retired Article Fingerprints will preserve non-reversible hashes for every known alias so the same Article remains deduplicated across sources.
