# Hard-delete expired Article state

Paper Monitor will permanently delete an Article and all of its identity aliases after the thirty-day active retention window. It will not retain a retired fingerprint, hidden archive, or other durable identity after expiry. This reduces stored reading-history traces and keeps the Article Lifecycle interface focused on active presentation and notification state; an Article rediscovered after the retention window is treated as a new detection.

This decision supersedes only the retired-fingerprint clauses in ADR 0003 and ADR 0008. Their active-retention and strict exact-identity decisions remain in force.
