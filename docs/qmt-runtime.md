# QMT runtime

## Host setup

Build `dist/QMTAIRLOCK.py` using the command in [Contributing](../CONTRIBUTING.md). Copy the generated file into the QMT strategy editor as GBK. The editable configuration region is bounded by `QMT_CONFIG_BEGIN` and `QMT_CONFIG_END`:

```python
QMT_ACCOUNT_ID = "YOUR_ACCOUNT"
QMT_RPC_CONFIG = {
    "account_types": ["STOCK"],
    "allow_order_methods": False,
    "pipe": {"pipe_name": "qmtairlock"},
    "schedule_adjust_interval": "100nMilliSecond",
}
```

Set the account type explicitly to `CREDIT` or `STOCK_OPTION` when using those domains. A list can allow multiple native types for the same bound account id; each request must select an allowed type. Do not enable order methods just to test read APIs. Keep local account configuration outside version control.

The host must supply `ContextInfo.run_time` and the native methods required by the chosen domain. `init` captures injected functions such as `get_trade_detail_data`, `passorder`, `cancel` and credit/formula globals. `adjust` runs scheduled work; order and credit callbacks update only in-memory state. `stop` closes connections and workers. A terminal that does not provide a method returns an explicit RPC error rather than an invented empty account.

## Runtime environment and threads

The host is a **self-contained standard-library runtime with in-memory state and zero external middleware dependencies**. Sources parse as Python 3.6. Runtime boundary checks validate the embedded module graph and the allowed dependency surface.

The host graph includes the server listener, shared message I/O and native domain handlers. Client connection management, WSL relay processes, desktop launchers and local Parquet storage remain in their own external runtime. QMT manages its native data and strategy loading.

Account reads, credit contract queries and writes execute on the strategy callback thread. One worker handles expensive market/formula reads. `gil_switch_interval_seconds` defaults to 0.001; this changes Python scheduling, not native calls that hold the GIL. A stalled native function can still stall QMT. `max_requests_per_tick` defaults to 64 and `drain_budget_seconds` to 0.05; these bound queue draining, not a native call already running.

## Windows and WSL clients

Windows clients select the local channel using the configured account id and the same `pipe_name` on both ends.

For WSL, install the same qmtairlock version in a Windows Python environment, then configure the Linux client with an argument list:

```python
config = {
    "pipe": {
        "pipe_name": "qmtairlock",
        "relay_command": [
            "/mnt/c/Python313/python.exe", "-I", "-m",
            "qmtairlock.transports.pipe_relay",
        ],
        "connect_timeout_seconds": 5,
    },
    "local_cache": {
        "enabled": True, "dir": "./market-cache", "format": "parquet",
        "fallback_rpc": False,
    },
}
```

Replace the example interpreter path with an installed Windows Python executable. `-I` requires the package to be installed in that interpreter. Stdout carries binary frames only; stderr carries relay diagnostics. Pass arguments as separate list elements. A client timeout terminates its failed relay process; it does not prove cancellation of a native order.

Configuration defaults and accepted keys are enforced by `config.py` and `strategy_runtime.py`; new configuration must be added at those owners. [Status](status.md) records which environments have actually been exercised.
