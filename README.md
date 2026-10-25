# qmtairlock

Local IPC bridge and Python client for QMT research and experimentation (non-commercial).

[简体中文](README.zh-CN.md) · [Product scope](PRODUCT.md) · [Documentation](docs/README.md) · [Validation status](docs/status.md)

> **Research & Experimental Use Only — Non-commercial intended use**
>
> This project is intended for personal quantitative research, software architecture learning and local experiments. Please do not use it for commercial purposes; the maintainers provide no commercial service or support.
>
> Do not use it for managing funds for others, unlawful securities or futures operations, leveraged sub-account funding, multi-account trading platforms, or remote access exposed to untrusted networks. Users must comply with applicable law, the [证券公司交易信息系统接入管理规范（试行）](https://www.amac.org.cn/xwfb/tzgg/202608/t20260828_28053.html), their broker's terminal agreement, access permissions and risk-control requirements.
>
> This software provides neither investment advice nor trading signals. It is provided **AS IS**, without express or implied warranties. Users bear the risks of operational failure, data inaccuracies, order anomalies, account exposure and direct or indirect loss. To the fullest extent permitted by applicable law, the authors disclaim liability for such use and losses.
>
> This is an independent technical experiment, unaffiliated with and not officially endorsed by XtQuant / QMT or any securities company. This is a statement of intended use; software license terms are in [LICENSE](LICENSE).

The strategy is a self-contained standard-library runtime with in-memory state and zero external middleware dependencies. It uses QMT's native APIs and a same-host message channel. Windows clients connect locally; WSL clients use a Windows Python stdio relay. The generated GBK entry is `QMTAIRLOCK.py`.

## Install and read

The client requires Python 3.10 or newer. Install the `data` extra for pandas frames and Parquet caching:

```sh
python -m pip install 'qmtairlock[data] @ git+https://github.com/shengyy/qmtairlock.git@v0.1.1'
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
