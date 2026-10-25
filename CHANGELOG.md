# Changelog

## [Unreleased]

### Fixed

- Keep single-date dividend queries on the callback thread so queued history reads cannot delay them; only date ranges use the heavy worker.
- Propagate native position-statistics query errors instead of returning an empty result.

## [0.1.1] - 2026-10-25

### Changed

- Separate host listener, shared message I/O and client connection ownership; enforce the host module boundary during builds.
- Consolidate option analysis workflows in OptionsClient and keep numerical routines in option_analytics.
- Present the project as a local IPC research runtime with current intended-use, compliance and disclaimer statements.

## [0.1.0] - 2026-10-25

### Added

- Local IPC RPC host, Windows client and WSL stdio relay with request deadlines and connection ownership.
- STOCK market/account operations, credit queries, option queries and local analytics, built-in formula and extension queries.
- Single and batch execution, native order mapping and polling callbacks with a silent initial baseline.
- Client Parquet cache, modular GBK `QMTAIRLOCK.py` strategy builder and runtime boundary checks.
- Current-state documentation, local quality gates and a manual-only CI workflow.

### Fixed

- Validate launcher parameters before closing a running terminal; automatic launch selects the full QMT terminal.
