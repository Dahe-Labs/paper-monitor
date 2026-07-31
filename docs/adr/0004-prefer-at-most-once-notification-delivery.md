# Prefer at-most-once notification delivery

Paper Monitor prioritizes avoiding duplicate notifications over guaranteed delivery. A clear rejection before Windows accepts a notification may be retried, but an accepted or ambiguous delivery attempt is never retried automatically, accepting a rare missed notification after a crash rather than risking a duplicate.
