# Paper Monitor

Paper Monitor discovers research content through finite refresh runs and presents newly relevant articles without requiring a continuously running application.

## Language

**Article**:
A research item discovered during one or more refresh runs and identified consistently across those runs.
_Avoid_: Result, item, paper record

**Article Identity**:
The set of exact stable identifiers used to determine whether results from one or more sources refer to the same Article. Similar wording alone never establishes identity.
_Avoid_: Listing ID, fuzzy title match, URL-only identity

**Article Lifecycle**:
The progression of an Article from detection through listing, presentation or notification, and eventual replacement by a Retired Article Fingerprint.
_Avoid_: Dashboard state, notification queue, article cache

**Article Listing**:
The compact representation of an Article presented in the main window: title, authors, journal, Journal Impact Reference, and URL. An abstract is never part of an Article Listing.
_Avoid_: File, article record, search result

**Journal Impact Reference**:
A frozen OpenAlex two-year mean citedness value used only as rough journal-level context. It is not a Clarivate Journal Impact Factor and never determines Article selection or notification eligibility.
_Avoid_: Journal Impact Factor, Article quality score, acceptance threshold

**Retired Article Fingerprint**:
A non-reversible identity retained after an Article Listing expires, used only to prevent the same Article from being presented or notified again. It contains no article metadata.
_Avoid_: Archived Article, hidden listing, history record

**Refresh Run**:
One bounded attempt to search the configured sources and record its outcome and discovered articles.
_Avoid_: Sync, scan, background loop

**Partial Refresh Run**:
A Refresh Run in which at least one configured source succeeded and at least one source was degraded or failed. Articles returned by successful sources remain valid results.
_Avoid_: Failed run, incomplete database, discarded refresh

**Refresh Intent**:
Whether a Refresh Run was requested without visible results (`Background`) or from the visible dashboard (`Visible`). Intent changes notification delivery, not source acquisition or persistence rules.
_Avoid_: Reason string, scheduler flag, caller name

**Refresh Execution**:
The bounded work that owns one Refresh Run from global ownership through source acquisition, transient matching, persistence, and intent-appropriate notification delivery.
_Avoid_: Refresh thread, scheduler callback, tray job

**Presented Article**:
An article whose summary has been successfully rendered in a visible Paper Monitor window. Presentation does not imply that the user opened or read the full article.
_Avoid_: Read article, clicked article, loaded article

**Notification-Eligible Article**:
An article that has never been presented and has never previously produced a system notification for the current Windows user. Repeated detection and metadata changes do not restore notification eligibility.
_Avoid_: New result, unread article, pending toast

**Refresh Notification**:
The single system notification that summarizes all Notification-Eligible Articles from one Refresh Run. A one-Article notification names that Article; a multi-Article notification reports the count and a short title preview.
_Avoid_: Per-Article notification batch, repeated toast, refresh alert stream

**Tray Host**:
The optional native Windows notification-area adapter that exposes menu commands and launches bounded Paper Monitor processes without owning refresh timing or application state.
_Avoid_: Background application, scheduler, hidden dashboard, refresh daemon
