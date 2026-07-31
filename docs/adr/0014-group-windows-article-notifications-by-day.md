# Group Windows article notifications by delivery day

A Refresh Run remains one atomic lifecycle notification batch so deduplication and at-most-once delivery do not change. The Windows adapter may present that batch as up to `max_notifications` individual article Toasts, capped at the Windows per-app history capacity of 20. Articles beyond that display limit are consumed with the same batch and are not retried separately.

Each displayed article has its own browser target and contains only a title and journal. The title is limited to two rendered lines, the journal uses a smaller caption style, and the Toast has no application-defined actions. Activating the Toast uses Windows protocol activation to open the article URL with the user's default browser.

All Toasts delivered on the same local calendar day share a Toast Header and notification group identifier. The Header provides the visible Notification Center grouping and system-controlled expand/collapse behavior; stable per-article tags avoid duplicate entries within that day.
