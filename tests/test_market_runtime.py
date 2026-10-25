import threading
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from qmtairlock.strategy_runtime import StrategyRuntime


class QueuedTransport:
    def __init__(self):
        self.requests = deque()
        self.replies = []

    def start_receiving(self, callback, background_threads):
        assert background_threads is False
        self.callback = callback

    def drain_request_queue(self, max_items):
        count = 0
        while self.requests and count < max_items:
            self.callback(self.requests.popleft())
            count += 1
        return count

    def send_response(self, request, response):
        self.replies.append(response)

    def stop(self):
        pass


@pytest.mark.parametrize(
    "method,start,end,native_dates",
    [
        ("get_divid_factors", "20261023", "20261023", ("20261023",)),
        ("getDividFactors", "20261023", "20261023", ("20261023",)),
        ("get_divid_factors", " 20261023 ", "20261023", ("20261023",)),
        ("get_divid_factors", "20261023", "", ("20261023",)),
        ("get_divid_factors", "", "20261023", ("20261023",)),
        ("get_divid_factors", "", "", ()),
    ],
)
def test_single_date_dividend_finishes_in_same_adjust_while_history_is_blocked(method, start, end, native_dates):
    started, release = threading.Event(), threading.Event()
    calls = []

    def download(*args, **kwargs):
        started.set()
        assert release.wait(2)

    def dividends(*args):
        calls.append((threading.get_ident(), args))
        return {}

    transport = QueuedTransport()
    context = SimpleNamespace(run_time=Mock(), get_divid_factors=dividends, get_market_data_ex=download)
    runtime = StrategyRuntime(context, "TEST", {}, {}, transport)
    runtime.start()
    try:
        transport.requests.append(
            {
                "request_id": "history",
                "account_id": "TEST",
                "method": "get_market_data_ex",
                "params": {"stock_list": ["600000.SH"], "period": "5m", "start_time": "20261019"},
            }
        )
        runtime.adjust()
        assert started.wait(1)
        transport.requests.append(
            {
                "request_id": "dividend",
                "account_id": "TEST",
                "method": method,
                "params": {"stock_code": "600000.SH", "start_time": start, "end_time": end},
            }
        )
        runtime.adjust()
        assert calls == [(threading.get_ident(), ("600000.SH",) + native_dates)]
        assert [(reply["request_id"], reply["ok"]) for reply in transport.replies] == [("dividend", True)]
    finally:
        release.set()
        runtime.stop()
    assert not runtime.service._heavy_thread.is_alive()


@pytest.mark.parametrize("method", ["download_history_data", "download_history_data2"])
def test_native_download_does_not_queue_behind_a_large_market_read(method):
    started, release = threading.Event(), threading.Event()
    calls = []

    def market(**kwargs):
        started.set()
        assert release.wait(2)
        return {}

    def download(stock, period, start, end):
        calls.append((threading.get_ident(), (stock, period, start, end)))

    transport = QueuedTransport()
    context = SimpleNamespace(run_time=Mock(), get_market_data_ex=market)
    runtime = StrategyRuntime(context, "TEST", {}, {method: download}, transport)
    runtime.start()
    try:
        transport.requests.append(
            {
                "request_id": "market",
                "account_id": "TEST",
                "method": "get_market_data_ex",
                "params": {"stock_list": ["600000.SH"], "period": "5m", "start_time": "20261019"},
            }
        )
        runtime.adjust()
        assert started.wait(1)
        code_arg = {"stock_code": "600000.SH"} if method == "download_history_data" else {"stock_list": ["600000.SH"]}
        transport.requests.append(
            {
                "request_id": "download",
                "account_id": "TEST",
                "method": method,
                "params": dict(code_arg, period="5m", start_time="20261023", end_time="20261023"),
            }
        )
        runtime.adjust()
        assert calls == [(threading.get_ident(), (next(iter(code_arg.values())), "5m", "20261023", "20261023"))]
        assert [(reply["request_id"], reply["ok"], reply["data"]) for reply in transport.replies] == [
            ("download", True, True)
        ]
    finally:
        release.set()
        runtime.stop()


def test_dividend_range_runs_on_history_worker():
    finished = threading.Event()
    calls = []

    def dividends(*args):
        calls.append((threading.get_ident(), args))
        finished.set()
        return {"sample": [1.0]}

    transport = QueuedTransport()
    runtime = StrategyRuntime(SimpleNamespace(run_time=Mock(), get_divid_factors=dividends), "TEST", {}, {}, transport)
    runtime.start()
    try:
        transport.requests.append(
            {
                "request_id": "range",
                "account_id": "TEST",
                "method": "get_divid_factors",
                "params": {"stock_code": "600000.SH", "start_time": "20261019", "end_time": "20261023"},
            }
        )
        runtime.adjust()
        assert finished.wait(1)
        assert calls == [(runtime.service._heavy_thread.ident, ("600000.SH", "20261019", "20261023"))]
        assert calls[0][0] != threading.get_ident()
    finally:
        runtime.stop()
