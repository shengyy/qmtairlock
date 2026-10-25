# RPC contract

## Envelope and transport

Requests are UTF-8 JSON objects:

```json
{"schema_version":1,"request_id":"unique-id","account_id":"YOUR_ACCOUNT","method":"ping","params":{},"timeout_seconds":6}
```

Replies repeat `request_id` and `account_id`, with `ok`, `data` or `error`. Clients reject mismatched identities. Typed payload metadata preserves frames, arrays and native object fields. Missing position quantities are errors; valid native zero quantities remain zero. Broker order identifiers stay strings, including leading zeros. `OrderId` additionally supports integer-style client APIs while carrying the exact string in `order_sys_id`.

The native pipe uses Windows message mode: one JSON message per `WriteFile`. The WSL relay wraps each message in a four-byte unsigned big-endian length followed by the payload (maximum 256 MiB). Its first frame is a JSON handshake containing `pipe_path` and `connect_timeout_seconds`; an empty frame acknowledges a successful connection. Truncated frames never become native messages.

## Methods and domain clients

| Domain | Entry points |
|---|---|
| Health | `BigQmtRpcClient.call("ping")` returns account types, package version and the write gate |
| Market | `BigQmtXtData`: ticks, bars, downloads, dividends, instruments, sectors, calendars and native extension getters |
| Accounts | `BigQmtXtTrader`: asset, positions, position statistics, orders, trades and one combined execution snapshot |
| Execution | `order_stock_result`, `order_stock`, async order/cancel, batch order/cancel and `passorder` |
| Credit | `trader.credit`: `query_credit_detail`, `query_credit_account`, `query_stk_compacts`, `query_credit_subjects`, `query_credit_slo_code`, `query_credit_assure` |
| Credit native contracts | RPC `get_assure_contract`, `get_enable_short_contract`, `get_unclosed_compacts`, `get_closed_compacts`, `get_debt_contract`; all use the main-thread route |
| Options | Native option chain/history/detail/position queries; `data.options` exposes BSM, IV and chain analytics |
| Formulas | `data.call_formula`, `get_formula_result`, `gen_factor_index` and native formula subscription helpers |
| Extensions | ETF components, IPO/quota, Hong Kong rates and financial queries through the native domain routes |

The exact accepted signatures live in the domain client methods and `rpc_dispatch`/`rpc_market_handlers`. Unsupported RPC methods fail; they do not dynamically import an SDK or select another transport. Low-level calls use `client.call(method, params)`.

Every client is bound to one account id. `params.account_type` selects an allowed native account type. Credit methods default to `CREDIT`. For typed trader methods, supply an object with `account_id` and `account_type`, for example `SimpleNamespace(account_id="YOUR_ACCOUNT", account_type=3)` for credit. Public option enums 48–57 map to native operations 50–59; raw `passorder` takes native enums. Invalid account/enum combinations fail before dispatch.

## Outcomes and deadlines

The client applies one connection/write/read deadline. The server assigns its own receive-time deadline and checks it again immediately before an order is sent. An expired queued order is refused; cancellation remains eligible to run. A timeout or lost connection after sending can leave an unknown native result. There is no transparent retry of that request.

In-memory server deduplication covers `(account_id, request_id)` and a bounded batch identity journal. It is not durable across a strategy restart. Applications must persist their own execution intent and reconcile unknown outcomes against QMT facts before deciding any next action.

Convenience single orders reconcile native order identity against a pre-dispatch baseline, remark, instrument, direction and native time. `wait_settlement=False` reports submission without claiming a broker id. `passorder` reports native dispatch only. A cancel is confirmed only by a terminal native status; accepted and confirmed are distinct.

Batch orders default to idempotent mode and require an explicit unique `order_remark` per intent. Reusing that identity with a different payload fails. Batch results are per item and not atomic; earlier items may already be submitted if a later item fails. `accepted` reports dispatch and `confirmed` reports reconciliation. Batch cancellation returns dispatch status, not final cancellation confirmation.

## Credit and callbacks

`query_credit_account` sends an asynchronous native query at most once every 30 seconds. It returns callback snapshot metadata immediately, including age, whether a query was issued and whether stale rows were dropped. It never waits on the QMT callback thread. Snapshots older than 120 seconds are withheld; callers may request a stricter positive age limit. Use `query_credit_detail` for a direct native detail read. Late callbacks for superseded query sequences do not overwrite the current snapshot.

Execution polling starts with a synchronous silent baseline. Subsequent native order changes and new trades produce callbacks on one client dispatcher thread. Query errors keep the previous baseline. Async responses are delivered before matching execution events. Callbacks are not a durable event stream and do not replay trades that predate subscription.

## Market data and cache

`get_full_tick(["SH", "SZ", "BJ"])` requests full-market snapshots; optional `types` filters narrow the returned instruments. Availability still depends on terminal subscriptions and permissions. Internal native warm-up subscriptions do not create a public push channel.

Bar frames preserve native times and units. Derived periods and repaired fields may carry partial metadata; inspect returned attributes and missing symbols. Partial batch failures return successful symbols, while a completely failed call raises. Missing native `preClose` and `suspendFlag` may be filled during frame normalization; callers must not treat these fields as independent native evidence.

Cache keys include instrument, period and dividend mode. Updates lock and merge by timestamp, preserve existing columns omitted by a narrower request, and atomically replace a Parquet file. `get_local_data` reads only that explicit local cache; it never issues RPC. Native history downloads update QMT's native data, while local Parquet is populated by successful bar reads.
