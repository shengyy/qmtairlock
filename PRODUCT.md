# Product scope

qmtairlock connects trusted Python applications to one configured QMT account through Windows local IPC. The terminal owns funds, positions, orders and trades. The bridge exposes native facts and execution operations; applications own strategies, risk limits and durable execution intent.

## Supported domains

| Domain | Boundary |
|---|---|
| STOCK | Quotes, full-market ticks, bars, dividends, instruments, sectors, trading calendars, assets, positions, orders and trades |
| Execution | Single/batch orders and cancels, native `passorder`, client polling callbacks; no automatic resend of unknown writes |
| Credit | Account/detail and contract queries, credit order enums, 30-second counter-query limit and a maximum 120-second callback snapshot age |
| Options | Native chain/history/position queries and order enum conversion; standard-library BSM, IV and Greeks on the client |
| Host extensions | `ContextInfo` or injected formulas, ETF components, IPO/quota, Hong Kong rates and financial data |
| Client storage | Optional Parquet bars, keyed by instrument, period and adjustment mode |
| Transport | Same-machine Windows local IPC; WSL uses a Windows Python stdio relay |

Availability of individual native queries depends on terminal build and entitlements. Implemented method coverage is not a claim that every broker supports it; [status](docs/status.md) holds validation evidence.

## Responsibilities

The host is a self-contained standard-library runtime with in-memory state and zero external middleware dependencies. Its native calls follow the terminal's available API and permissions. Applications own durable execution intent, strategy logic, risk limits and account-level operational decisions.

Native download functions manage QMT's own data store. Optional client Parquet storage and external build/launcher tools have separate lifecycles. The public API consists of `BigQmtRpcClient`, `BigQmtXtData`, `BigQmtXtTrader`, composed credit/options clients and the documented RPC surface. Constructor configuration is explicit; unsupported methods and unknown keys return errors.

## Intended use and disclaimer

> **Research & Experimental Use Only — Non-commercial intended use**
>
> This project is intended for personal quantitative research, software architecture learning and local experiments. Please do not use it for commercial purposes; the maintainers provide no commercial service or support.
>
> Do not use it for managing funds for others, unlawful securities or futures operations, leveraged sub-account funding, multi-account trading platforms, or remote access exposed to untrusted networks. Users must comply with applicable law, the [证券公司交易信息系统接入管理规范（试行）](https://www.amac.org.cn/xwfb/tzgg/202608/t20260828_28053.html), their broker's terminal agreement, access permissions and risk-control requirements.
>
> This software provides neither investment advice nor trading signals. It is provided **AS IS**, without express or implied warranties. Users bear the risks of operational failure, data inaccuracies, order anomalies, account exposure and direct or indirect loss. To the fullest extent permitted by applicable law, the authors disclaim liability for such use and losses.
>
> This is an independent technical experiment, unaffiliated with and not officially endorsed by XtQuant / QMT or any securities company. This is a statement of intended use; software license terms are in [LICENSE](LICENSE).
