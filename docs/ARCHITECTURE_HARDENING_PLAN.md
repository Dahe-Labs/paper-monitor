# Paper Monitor Architecture Hardening Plan

This plan keeps the current product direction: shared Python core, a short-lived Windows pywebview window plus native C tray, and a Mac Swift/AppKit shell.

## Phase 1: Contract And Safety (Completed)

- Keep `docs/config.schema.json` as the published config contract.
- Keep `config.example.json` and `paper_monitor.config.DEFAULT_CONFIG` synchronized.
- Add tests for unknown-key preservation in Windows settings writes.
- Treat Crossref public and polite pool limits as source-level behavior, not UI guidance.
- Keep local bridge tokens per server session and localhost-only.

## Phase 2: Repository And Release (Completed)

- Keep the project in one repository with `paper_monitor/`, `windows/`, `macos/`, `scripts/`, `tests/`, `docs/`, and `.github/`.
- Keep `.repo-compare` ignored and use it only for temporary local comparisons.
- Use GitHub Actions for Python tests, Windows packaging, macOS Swift tests, and release artifacts.
- Keep generated build output out of source control except explicit release artifacts.
- Align Mac `SearchPreset` IDs and queries with `paper_monitor/search_presets.py`; current Swift presets should be treated as legacy until they consume the shared contract.

## Phase 3: UI Maintainability (In Progress)

- Keep Windows Settings JavaScript/CSS in static assets; move the remaining Dashboard script and styles out of the Python template in a future focused change.
- Add browser-based smoke tests for Dashboard, Settings, Refresh Now, and bridge authorization.
- Keep Mac Settings and Windows Settings aligned through the config schema, not through duplicated assumptions.

## Phase 4: Source Adapter Layer

- Introduce a small source adapter interface for Crossref, OpenAlex, arXiv, and RSS.
- Standardize retries, caching, source health, warnings, and result normalization.
- Add source-level diagnostics to the dashboard and support bundle.

## Phase 5: Ranking And Feedback

- Add local feedback fields such as saved, ignored, relevant, not relevant, and notes.
- Use feedback to improve keyword suggestions and ranking.
- Add optional LLM summaries or relevance explanations after deterministic filtering remains stable.
