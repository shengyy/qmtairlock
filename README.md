# qmtairlock

A named-pipe bridge for the Windows QMT strategy host, with Python clients for market data, account queries and trading.

[简体中文](README.zh-CN.md) · [Product scope](PRODUCT.md) · [Documentation](docs/README.md) · [Validation status](docs/status.md)

The strategy uses QMT's `ContextInfo` and injected native functions. It runs from one generated GBK Python file, uses standard-library code and named pipes, and does not open files or sockets. Windows clients connect directly; WSL clients use a Windows Python process over framed stdio.

## Install and read

The client requires Python 3.10 or newer. Install the `data` extra for pandas frames and Parquet caching:

```sh
python -m pip install 'qmtairlock[data] @ git+https://github.com/shengyy/qmtairlock.git@v0.1.0'
```

With a configured, running strategy on the same Windows machine:

```python
from qmtairlock.client import BigQmtRpcClient
from qmtairlock.data_client import BigQmtXtData
from qmtairlock.trader_client import BigQmtXtTrader

client = BigQmtRpcClient("YOUR_ACCOUNT")
try:
    print(client.call("ping"))
    data = BigQmtXtData(client)
    print(data.get_full_tick(["600000.SH", "000001.SZ"]))
    bars = data.get_market_data_ex(stock_list=["600000.SH"], period="1d", count=20)
finally:
    client.close()

trader = BigQmtXtTrader("YOUR_ACCOUNT")
try:
    print(trader.query_stock_asset("YOUR_ACCOUNT"))
finally:
    trader.stop()
```

See [host setup and WSL configuration](docs/qmt-runtime.md) before connecting. Trading RPCs are disabled by default. Query support depends on the broker terminal's native APIs and data permissions.

## Capabilities

- STOCK quotes, full-market ticks, bars, dividends, instruments, sectors, calendars and account snapshots.
- Single and batch order/cancel requests, native `passorder`, and execution callbacks synthesized by client polling.
- Credit account and contract queries, rate-limited counter snapshots and credit order types.
- Option chains, positions, order types, and client-side BSM pricing, implied volatility and Greeks.
- Built-in formula RPC, ETF components, IPO quotas, Hong Kong exchange rates and financial data.
- Explicit client-only Parquet caching. Cache reads never start RPC downloads.

[RPC contract](docs/rpc-contract.md) explains deadlines, unknown write outcomes and domain entry points. [Contributing](CONTRIBUTING.md) contains the local checks and build commands. GitHub Actions runs only when manually requested.

Licensed under [MIT](LICENSE).
