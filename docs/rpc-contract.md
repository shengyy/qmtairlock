# RPC contract

## Envelope and transport

Requests are UTF-8 JSON objects:

```json
{"schema_version":1,"request_id":"unique-id","account_id":"YOUR_ACCOUNT","method":"ping","params":{},"timeout_seconds":6,"deadline_at":1795000000.0}
```

`deadline_at` is the client's wall-clock deadline as a float of epoch seconds, stamped by `BigQmtRpcClient.call`. It is optional for hand-written clients; any other value type is refused.

Replies repeat `request_id` and `account_id`, with `ok`, `data` or `error`; an error reply may also carry `data` detail, exposed as `RpcServerRepliedError.data`. `handled_at` is the host's naive local ISO time. Clients reject mismatched identities. Typed payload metadata preserves frames, arrays and native object fields. Missing position quantities are errors; valid native zero quantities remain zero. Broker order identifiers stay strings, including leading zeros. `OrderId` additionally supports integer-style client APIs while carrying the exact string in `order_sys_id`.

Native ACCOUNT, POSITION, POSITION_STATISTICS, ORDER and DEAL query exceptions propagate as RPC errors.

The local channel exchanges one complete JSON request or response per message. The WSL relay wraps each message in a four-byte unsigned big-endian length followed by the payload (maximum 256 MiB). Its first frame is a JSON handshake containing `pipe_path` and `connect_timeout_seconds`; an empty frame acknowledges a successful connection. Truncated frames never become native messages.

## Methods and domain clients

| Domain | Entry points |
|---|---|
| Health | `BigQmtRpcClient.call("ping")` returns account types, package version, the write gate, `server_time` (host epoch seconds) and `host`: `python` (`major.minor.micro`), the embedded interpreter version. Library versions are not reported: the host does not import pandas or numpy, the 2.1.33 host with the Python 3.12 library does not expose them as loaded modules, and reading installed metadata would import `pathlib` and read files, which the host boundary forbids. `BigQmtRpcClient.clock_skew()` reads `server_time` against the local send/receive midpoint and reports `skew_seconds` and `round_trip_seconds`; it never adjusts a clock |
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

The client applies one connection/write/read deadline. The server deadline is the earlier of its receive time plus `timeout_seconds` and `deadline_at` plus one second of clock tolerance; a request can wait unread in the channel while the callback thread is busy, so the client deadline is what bounds it. Any request other than cancellation that reaches dispatch after that deadline is refused with `RequestExpired: not dispatched` and never runs. That reply's `data` carries `server_now`, `received_at`, `deadline_at` and `timeout_seconds`, so a queue delay can be told apart from a client clock that is behind the host. A refusal caused by queue delay is sent after the client has already timed out, so the client reads it through `get_request_outcome` (state `refused`), which is answered in arrival order after any order read before it; only a client whose clock is behind receives it directly. Clocks are never corrected and orders are never relaxed; orders are checked again immediately before native dispatch. Cancellation remains eligible to run. A timeout or lost connection after sending can leave an unknown native result. There is no transparent retry of that request.

In-memory server deduplication covers `(account_id, request_id)` and a bounded batch identity journal. It is not durable across a strategy restart. Applications must persist their own execution intent and reconcile unknown outcomes against QMT facts before deciding any next action.

Convenience single orders reconcile native order identity against a pre-dispatch baseline, remark, instrument, direction and native time. `wait_settlement=False` reports submission without claiming a broker id. `passorder` reports native dispatch only. A cancel is confirmed only by a terminal native status; accepted and confirmed are distinct.

Batch orders default to idempotent mode and require an explicit unique `order_remark` per intent. Reusing that identity with a different payload fails. Batch results are per item and not atomic; earlier items may already be submitted if a later item fails. `accepted` reports dispatch and `confirmed` reports reconciliation. Batch cancellation returns dispatch status, not final cancellation confirmation.

## Credit and callbacks

`query_credit_account` sends an asynchronous native query at most once every 30 seconds. It returns callback snapshot metadata immediately, including age, whether a query was issued and whether stale rows were dropped. It never waits on the QMT callback thread. Snapshots older than 120 seconds are withheld; callers may request a stricter positive age limit. Use `query_credit_detail` for a direct native detail read. Late callbacks for superseded query sequences do not overwrite the current snapshot.

Execution polling starts with a synchronous silent baseline. Subsequent native order changes and new trades produce callbacks on one client dispatcher thread. Query errors keep the previous baseline. Async responses are delivered before matching execution events. Callbacks are not a durable event stream and do not replay trades that predate subscription.

## Market data and cache

`get_full_tick(["SH", "SZ", "BJ"])` requests full-market snapshots; optional `types` filters narrow the returned instruments. Availability still depends on terminal subscriptions and permissions. Internal native warm-up subscriptions do not create a public push channel.

Bar reads pass `subscribe=False` to `get_market_data_ex` unless the caller sets `subscribe`; the 3.12 host otherwise keeps every read code in its subscription pool. A native frame with multi-level columns (multi-instrument answers on the 3.12 host) is an error rather than a frame with tuple-string column names; request one instrument per call. Bar frames preserve native times and units. Derived periods and repaired fields may carry partial metadata; inspect returned attributes and missing symbols. Partial batch failures return successful symbols, while a completely failed call raises. Missing native `preClose` and `suspendFlag` may be filled during frame normalization; callers must not treat these fields as independent native evidence.

Cache keys include instrument, period and dividend mode. Updates lock and merge by timestamp, preserve existing columns omitted by a narrower request, and atomically replace a Parquet file. Before a merge, incoming rows are checked, after a narrower update has been completed from the stored row, and rejected rows are counted in `LocalMarketCache.rejected_rows` by reason: a time label that is not 8–14 digits, a supplied price that is not positive, a supplied volume or amount that is negative or not numeric, or a high/low outside open/close. Missing values (NaN) count as not supplied. Zero-volume bars are kept because untraded minutes are real native bars. A bar-period file (any period except `tick*`/`l2*`) must hold `open, high, low, close, volume, amount`; a write that would create or leave a file without them is rejected. Reading or merging into a file that fails these checks raises `CacheFileInvalid` naming the file and reason; files are never deleted or repaired automatically, and `LocalMarketCache.audit()` lists failing files read-only. `get_local_data` reads only that explicit local cache; it never issues RPC. An instrument whose file fails the checks is left out of the result with a logged warning naming the file and reason, so the other instruments in the same request are still served; an instrument whose valid file lacks a requested field is left out the same way. Native history downloads update QMT's native data, while local Parquet is populated by successful bar reads.

History downloads are owned by `MarketBars`. Injected single-stock globals use `download_history_data` or `down_history_data` with four positional arguments. A native batch global receives a fifth progress callback, then four arguments if that signature raises `TypeError`. Without a batch global, each stock uses the single-stock global; without injected globals, the matching ContextInfo method receives keyword arguments, including `incrementally` when supplied. Native `None` or a truthy result means QMT accepted the download and returns `True`; it does not prove rows were written, so confirm by reading the bars back. Other results and native exceptions are errors. Per-stock batches attempt all stocks in a chunk and report every failed stock.

`download_history_data2` runs in chunks of `download_chunk_codes` stocks (strategy setting, default 10), one chunk per callback tick after that tick's other requests, and only when no read request is still waiting, so `ping` and other requests wait at most one chunk. A chunk inside QMT cannot be interrupted. A chunk is not started when the request deadline would pass before it is expected to finish; the reply is then `ok=false`, `error="DownloadIncomplete: k/n"` and `data={"downloaded": [...], "pending": [...]}`. A native failure stops the batch with that error and the same `data`. Clients that ignore `data` see an ordinary failed download.
