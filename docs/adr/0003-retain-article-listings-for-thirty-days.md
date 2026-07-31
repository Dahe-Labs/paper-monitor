# Retain Article Listings for thirty days

The fingerprint-retention clause below is superseded by [ADR 0018](0018-hard-delete-expired-article-state.md).

Paper Monitor will keep each Article Listing for thirty days from its first detection and then permanently delete its title, authors, journal, impact factor, and URL. Abstracts may participate transiently in matching during a Refresh Run but are never persisted, and a non-reversible Retired Article Fingerprint remains solely to prevent the same Article from being presented or notified again.
