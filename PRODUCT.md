# Product scope

qmtairlock connects trusted Python applications to one configured QMT account through Windows named pipes. The terminal owns funds, positions, orders and trades. The bridge exposes native facts and execution operations; applications own strategies, risk limits and durable execution intent.

## Supported domains

| Domain | Boundary |
|---|---|
| STOCK | Quotes, full-market ticks, bars, dividends, instruments, sectors, trading calendars, assets, positions, orders and trades |
| Execution | Single/batch orders and cancels, native `passorder`, client polling callbacks; no automatic resend of unknown writes |
| Credit | Account/detail and contract queries, credit order enums, 30-second counter-query limit and a maximum 120-second callback snapshot age |
| Options | Native chain/history/position queries and order enum conversion; standard-library BSM, IV and Greeks on the client |
| Host extensions | `ContextInfo` or injected formulas, ETF components, IPO/quota, Hong Kong rates and financial data |
| Client storage | Optional Parquet bars, keyed by instrument, period and adjustment mode |
| Transport | Same-machine Windows named pipes; WSL uses a Windows Python stdio relay |

Availability of individual native queries depends on terminal build and entitlements. Implemented method coverage is not a claim that every broker supports it; [status](docs/status.md) holds validation evidence.

## Non-goals

The project has no network service, separate formula server, external message broker, quote push protocol, strategy-side file logger, persistent order journal, trading strategy or account ledger. Native download functions may update QMT's own data store; the bridge itself does not access host files. Local client cache and build tooling execute outside the strategy sandbox.

The public API consists of `BigQmtRpcClient`, `BigQmtXtData`, `BigQmtXtTrader`, composed credit/options clients and the documented RPC surface. Constructor configuration is explicit. Unknown keys and unsupported RPCs fail visibly.
