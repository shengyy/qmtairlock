import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from qmtairlock.client_callbacks import ExecutionCallbacks
from qmtairlock.trader_client import BigQmtXtTrader


def row(tag, sysid="0001", trade_id="D1", status=50):
    return SimpleNamespace(
        account_id="TEST",
        account_type=2,
        stock_code="600000.SH",
        order_sysid=sysid,
        order_remark=tag,
        traded_id=trade_id,
        order_status=status,
        commission=1.25,
        traded_time=1000,
    )


def identity(tag):
    return {"account_id": "TEST", "account_type": 2, "stock_code": "600000.SH", "remark": tag}


def test_completed_request_releases_its_events_without_waiting_for_unrelated_jobs():
    trader = SimpleNamespace(query_execution_snapshot=Mock(return_value={"orders": [], "trades": []}))
    callbacks = ExecutionCallbacks(trader, "TEST")
    callbacks.poll_once()
    callbacks.begin_async(1, identity("first"))
    callbacks.begin_async(2, identity("second"))
    first, unrelated = row("first"), row("unrelated", "0003", "D3")
    trader.query_execution_snapshot.return_value = {"orders": [first, unrelated], "trades": [first]}
    callbacks.poll_once()
    assert callbacks._delivery.get_nowait() == ("on_stock_order", unrelated)
    callbacks.finish_async(1, "on_order_stock_async_response", "response1")
    delivered = [callbacks._delivery.get_nowait() for _ in range(3)]
    assert [item[0] for item in delivered] == ["on_order_stock_async_response", "on_stock_order", "on_stock_trade"]
    assert delivered[-1][1].commission == 1.25 and delivered[-1][1].traded_time == 1000
    assert list(callbacks._barriers) == [2]


def test_poll_failure_does_not_reset_baseline_or_replay_trades():
    baseline, current = row("old"), row("new", "0002", "D2")
    trader = SimpleNamespace(
        query_execution_snapshot=Mock(
            side_effect=[
                {"orders": [baseline], "trades": [baseline]},
                RuntimeError("temporarily unavailable"),
                {"orders": [baseline, current], "trades": [baseline, current]},
                {"orders": [baseline, current], "trades": [baseline, current]},
            ]
        )
    )
    callbacks = ExecutionCallbacks(trader, "TEST")
    callbacks.poll_once()
    with pytest.raises(RuntimeError):
        callbacks.poll_once()
    callbacks.poll_once()
    callbacks.poll_once()
    assert callbacks._delivery.qsize() == 2


def test_two_first_async_submissions_share_one_owner_and_wait_for_baseline(monkeypatch):
    import qmtairlock.client_callbacks as module

    entered, release, baseline_done = threading.Event(), threading.Event(), threading.Event()
    starts = []

    class Callbacks:
        def __init__(self, trader, account):
            starts.append(self)

        def poll_once(self):
            entered.set()
            assert release.wait(2)
            baseline_done.set()

        def start(self):
            pass

        def stop(self):
            pass

        def begin_async(self, seq, identity):
            assert baseline_done.is_set()

        def finish_async(self, *args):
            pass

    monkeypatch.setattr(module, "ExecutionCallbacks", Callbacks)
    trader = BigQmtXtTrader("TEST")
    dispatched = []
    trader.order_stock_result = lambda *args: dispatched.append(baseline_done.is_set()) or {"order_sys_id": "0001"}
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(trader.order_stock_async, "TEST", "600000.SH", 23, 100, 11, 10)
        assert entered.wait(1)
        second = pool.submit(trader.order_stock_async, "TEST", "600000.SH", 23, 100, 11, 10)
        release.set()
        assert sorted([first.result(), second.result()]) == [1, 2]
    # Drain the ordered worker before close marks unsent requests as cancelled.
    trader._async._jobs.put(None)
    trader._async._worker.join(1)
    assert len(starts) == 1 and dispatched == [True, True]
    trader.stop()


def test_failed_baseline_does_not_publish_half_initialized_subscription():
    trader = BigQmtXtTrader("TEST")
    trader.query_execution_snapshot = Mock(side_effect=RuntimeError("baseline unavailable"))
    with pytest.raises(RuntimeError):
        trader.subscribe("TEST")
    assert trader._callbacks is None and trader._async is None
    trader.stop()


def test_native_trade_ids_reused_on_another_day_are_new_events():
    baseline, next_day = row("first"), row("second")
    next_day.traded_time += 86400
    trader = SimpleNamespace(
        query_execution_snapshot=Mock(
            side_effect=[{"orders": [], "trades": [baseline]}, {"orders": [], "trades": [next_day]}]
        )
    )
    callbacks = ExecutionCallbacks(trader, "TEST")
    callbacks.poll_once()
    callbacks.poll_once()
    assert callbacks._delivery.get_nowait() == ("on_stock_trade", next_day)
