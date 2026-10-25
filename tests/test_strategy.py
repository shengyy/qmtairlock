import builtins
import io
import os
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_strategy import build, collect_sources
from check_host import check


class Transport:
    def __init__(self, **kwargs):
        self.replies = []
        self.stopped = False

    def start_receiving(self, callback, background_threads):
        assert background_threads is False
        self.callback = callback

    def drain_request_queue(self, max_items):
        return 0

    def send_response(self, request, response):
        self.replies.append(response)

    def stop(self):
        self.stopped = True


class Context:
    def set_account(self, account):
        self.account = account

    def run_time(self, name, interval, start):
        self.schedule = (name, interval)

    def get_full_tick(self, codes):
        return {code: {"lastPrice": 10.0} for code in codes}

    def get_stock_list_in_sector(self, sector, *args):
        return ["600000.SH"]


def test_built_strategy_lifecycle_under_forbidden_io(tmp_path):
    output = tmp_path / "QMTAIRLOCK.py"
    manifest = build(output)
    code = compile(output.read_text(encoding="gbk"), "QMTAIRLOCK.py", "exec")
    imports_before = set(sys.modules)
    forbidden = mock.Mock(side_effect=AssertionError("forbidden I/O"))
    namespace = {}
    with (
        mock.patch.object(builtins, "open", forbidden),
        mock.patch.object(io, "open", forbidden),
        mock.patch.object(os, "open", forbidden),
        mock.patch.object(os, "makedirs", forbidden),
        mock.patch.object(socket, "socket", forbidden),
    ):
        exec(code, namespace)
        runtime_module = namespace["_load"]("qmtairlock.strategy_runtime")
        runtime_module.NamedPipeServer = Transport
        namespace["QMT_ACCOUNT_ID"] = "TEST"
        namespace["QMT_RPC_CONFIG"]["account_types"] = ["CREDIT"]
        namespace["get_trade_detail_data"] = lambda *args: []
        namespace["call_formula"] = lambda *args: {"formula": args[0]}
        namespace["query_credit_account"] = lambda aid, seq, ctx: namespace["credit_account_callback"](
            ctx, seq, SimpleNamespace(balance=12)
        )
        ctx = Context()
        runtime = namespace["init"](ctx)
        assert ctx.schedule == ("adjust", "100nMilliSecond")
        for index, method in enumerate(
            (
                "ping",
                "query_account_infos",
                "query_credit_detail",
                "query_credit_account",
                "get_full_tick",
                "call_formula",
            )
        ):
            params = (
                {"codes": ["600000.SH"]}
                if method == "get_full_tick"
                else {"formula_name": "MA", "stock_code": "600000.SH", "period": "1m"}
                if method == "call_formula"
                else {}
            )
            runtime.service.enqueue_payload(
                {"request_id": str(index), "account_id": "TEST", "method": method, "params": params}
            )
            namespace["adjust"](ctx)
        deadline = time.monotonic() + 1
        while len(runtime.service._transport.replies) < 6 and time.monotonic() < deadline:
            namespace["adjust"](ctx)
            time.sleep(0.001)
        assert len(runtime.service._transport.replies) == 6
        assert all(reply["ok"] for reply in runtime.service._transport.replies)
        assert runtime.service._transport.replies[3]["data"]["rows"] == [{"balance": 12}]
        namespace["order_callback"](
            ctx, SimpleNamespace(m_strAccountID="TEST", m_strOrderSysID="0001", m_nOrderStatus=54)
        )
        assert runtime.watch.status_for_sysid("0001") == "54"
        namespace["stop"](ctx)
        assert runtime.service._transport.stopped
        assert not runtime.service._heavy_thread.is_alive()
        forbidden.assert_not_called()
    assert not any(name.startswith("xtquant") for name in set(sys.modules) - imports_before)
    assert "qmtairlock.client" not in manifest["modules"]
    assert check() == len(collect_sources())


def test_flat_load_is_local_and_repeatable(tmp_path):
    output = tmp_path / "QMTAIRLOCK.py"
    build(output)
    code = compile(output.read_text(encoding="gbk"), str(output), "exec")
    ns = {}
    original_import = builtins.__import__
    exec(code, ns)
    version = ns["_load"]("qmtairlock.version")
    expected_version = version.__version__
    version.__version__ = "sentinel"
    exec(code, ns)
    assert ns["_load"]("qmtairlock.version").__version__ == expected_version
    assert builtins.__import__ is original_import


def test_reinit_refuses_to_replace_a_running_native_worker(tmp_path):
    output = tmp_path / "QMTAIRLOCK.py"
    build(output)
    ns = {"_runtime": SimpleNamespace(stop=mock.Mock(side_effect=RuntimeError("still running")))}
    with pytest.raises(RuntimeError, match="still running"):
        exec(compile(output.read_text(encoding="gbk"), str(output), "exec"), ns)


def test_account_and_credit_methods_never_escape_main_thread():
    from qmtairlock.rpc_dispatch import LISTENER_DEFERRED_METHODS
    from qmtairlock.rpc_service import RpcService

    seen = []
    handlers = SimpleNamespace(handle=lambda method, params: seen.append(threading.get_ident()))
    service = RpcService(handlers, "TEST", Transport(), listener_methods=("*", "passorder", "get_debt_contract"))
    main_ident = threading.get_ident()
    for index, method in enumerate(LISTENER_DEFERRED_METHODS):
        request = {"request_id": str(index), "account_id": "TEST", "method": method, "params": {}}
        worker = threading.Thread(target=service.enqueue_payload, args=(request,))
        worker.start()
        worker.join()
    assert seen == []
    service.drain_pending(500)
    assert seen and set(seen) == {main_ident}
