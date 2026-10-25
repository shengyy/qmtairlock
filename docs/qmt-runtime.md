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

## Sandbox and threads

Host sources parse as Python 3.6 and use only standard-library modules accepted by the build gate. The generated code does not call `open`, `io.open`, `os.open`, `os.makedirs` or `socket.socket`. Native named-pipe handles are accessed through `ctypes`; no packages are installed in QMT's embedded Python.

This boundary covers bridge-owned code. QMT itself loads the strategy, imports its standard library and may persist data internally when a native download is requested. Client cache, builds and external relay processes are outside the host sandbox.

Account reads, credit contract queries and writes execute on the strategy callback thread. One worker handles expensive market/formula reads. `gil_switch_interval_seconds` defaults to 0.001; this changes Python scheduling, not native calls that hold the GIL. A stalled native function can still stall QMT. `max_requests_per_tick` defaults to 64 and `drain_budget_seconds` to 0.05; these bound queue draining, not a native call already running.

## Windows and WSL clients

On Windows, the client opens `\\.\pipe\qmtairlock_YOUR_ACCOUNT`. Use the same `pipe_name` on both ends.

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

Replace the example interpreter path with an installed Windows Python executable. `-I` requires the package to be installed in that interpreter. Stdout carries binary frames only; stderr carries relay diagnostics. Do not add shell quoting or a TCP listener. A client timeout terminates its failed relay process; it does not prove cancellation of a native order.

Configuration defaults and accepted keys are enforced by `config.py` and `strategy_runtime.py`; new configuration must be added at those owners. [Status](status.md) records which environments have actually been exercised.
