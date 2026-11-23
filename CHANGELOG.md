# Changelog

## [Unreleased]

### Changed

- Target the QMT 2.1.36 host (embedded Python 3.12, pandas 3, numpy 2) as the only host baseline; the Python 3.6 syntax limit and its ctypes fallbacks are removed.
- Build `QMTAIRLOCK.py` as pure ASCII so the host's source decoding cannot alter non-ASCII literals; the build fails if escaping would change any constant.

### Added

- `get_request_outcome` is answered in arrival order behind orders read before it, so a query sent right after a timed-out order sees that order's final state instead of `unknown`.
- Requests carry the client deadline (`deadline_at`); a request that waited unread past it, for example behind a native download, is refused instead of running later (one second of clock tolerance).
- Batch history downloads run one chunk of `download_chunk_codes` stocks per callback tick, so `ping` and other short requests are answered between chunks; when the deadline would pass, the reply is `DownloadIncomplete: k/n` with the downloaded and pending stocks.
- Bar reads pass `subscribe=False` to `get_market_data_ex` unless the caller asks to subscribe.
- `RequestExpired` replies carry the server time and the client deadline; `ping` returns `server_time` and the client offers a read-only `clock_skew()`.
- The local cache checks bar rows before every merge, counts rejected rows, requires the core bar columns in bar-period files and raises `CacheFileInvalid` with the file and reason on reading an invalid file; `audit()` lists invalid files read-only.
- `ping` reports the host interpreter version and, when already loaded by the host, pandas and numpy versions.

### Fixed

- Read native bar frames by position so label-indexed pandas 3 frames no longer turn dividend-range scans into empty results; frame shape errors now propagate instead of returning no rows. Frames with multi-level columns are rejected instead of being encoded with tuple-string column names.

- Keep single-date dividend queries on the callback thread so queued history reads cannot delay them; only date ranges use the heavy worker.
- Keep native history downloads on the callback thread so large market reads cannot queue ahead of a small download.
- Restore native history download channels: single-stock globals, batch callback signatures and ContextInfo methods; reject every failed native result, including failures before a later successful stock.
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
