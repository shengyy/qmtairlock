import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

from test_market_runtime import QueuedTransport

from qmtairlock.strategy_runtime import StrategyRuntime

CODES = ["%06d.SZ" % index for index in range(25)]


def _request(request_id, method, params=None, timeout=30):
    return {
        "request_id": request_id,
        "account_id": "TEST",
        "method": method,
        "params": params or {},
        "timeout_seconds": timeout,
        "deadline_at": time.time() + timeout,
    }


def _download(timeout=30):
    params = {"stock_list": CODES, "period": "1m", "start_time": "20261120", "end_time": "20261120"}
    return _request("download", "download_history_data2", params, timeout)


def _runtime(native, context=None, **config):
    transport = QueuedTransport()
    runtime = StrategyRuntime(
        context or SimpleNamespace(run_time=Mock()), "TEST", config, {"download_history_data2": native}, transport
    )
    runtime.start()
    return runtime, transport


def test_batch_download_runs_one_chunk_per_tick_and_ping_answers_between_chunks():
    chunks = []
    runtime, transport = _runtime(lambda codes, *args: chunks.append(list(codes)))
    try:
        transport.requests.append(_download())
        runtime.adjust()
        assert chunks == [CODES[:10]] and transport.replies == []
        transport.requests.append(_request("ping", "ping"))
        runtime.adjust()
        assert [reply["request_id"] for reply in transport.replies] == ["ping"]
        assert len(chunks) == 2
        runtime.adjust()
        assert chunks == [CODES[:10], CODES[10:20], CODES[20:]]
        assert (transport.replies[-1]["request_id"], transport.replies[-1]["data"]) == ("download", True)
    finally:
        runtime.stop()


def test_deadline_stops_the_next_chunk_and_reports_what_ran():
    chunks = []

    def slow(codes, *args):
        chunks.append(list(codes))
        time.sleep(0.2)

    runtime, transport = _runtime(slow, download_chunk_codes=20)
    try:
        transport.requests.append(_download(timeout=0.3))
        runtime.adjust()
        runtime.adjust()
        assert chunks == [CODES[:20]]
        reply = transport.replies[-1]
        assert (reply["ok"], reply["error"]) == (False, "DownloadIncomplete: 20/25")
        assert reply["data"] == {"downloaded": CODES[:20], "pending": CODES[20:]}
    finally:
        runtime.stop()


def test_native_chunk_failure_reports_progress_and_stops():
    calls = []

    def failing(codes, *args):
        calls.append(list(codes))
        if len(calls) == 2:
            raise OSError("native disk unavailable")

    runtime, transport = _runtime(failing)
    try:
        transport.requests.append(_download())
        for _ in range(4):
            runtime.adjust()
        assert len(calls) == 2
        reply = transport.replies[-1]
        assert reply["ok"] is False and reply["error"] == "OSError: native disk unavailable"
        assert reply["data"] == {"downloaded": CODES[:10], "pending": CODES[10:]}
    finally:
        runtime.stop()


def test_ping_answers_in_the_same_tick_while_a_heavy_read_is_running():
    started, release = threading.Event(), threading.Event()

    def market(**kwargs):
        started.set()
        assert release.wait(2)
        return {}

    runtime, transport = _runtime(Mock(), SimpleNamespace(run_time=Mock(), get_market_data_ex=market))
    try:
        params = {"stock_list": ["600000.SH"], "period": "5m", "start_time": "20261019"}
        transport.requests.append(_request("heavy", "get_market_data_ex", params))
        runtime.adjust()
        assert started.wait(1)
        transport.requests.append(_request("ping", "ping"))
        begun = time.monotonic()
        runtime.adjust()
        assert time.monotonic() - begun < 0.5
        assert [(reply["request_id"], reply["ok"]) for reply in transport.replies] == [("ping", True)]
    finally:
        release.set()
        runtime.stop()
