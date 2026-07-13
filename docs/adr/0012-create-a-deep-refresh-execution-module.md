# Create a deep Refresh Execution module

Task Scheduler, the Tray Host, and the visible dashboard will all cross one Refresh Execution seam through `execute(intent)`, where intent is `Background` or `Visible`. The deep module owns global run locking, configuration, source adapters, transient abstract matching, source outcome classification, Article Lifecycle commit, and intent-appropriate notification delivery; callers receive one Refresh Outcome and do not coordinate internal threads, locks, or source details.
