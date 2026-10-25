import ctypes
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from qmtairlock.adapters.order_gateway import BigQmtOrderGateway
from qmtairlock.adapters.order_queries import OrderQueries
from qmtairlock.adapters.position_bigqmt import BigQmtPositionProvider
from qmtairlock.models import CancelResult, OrderRequest, OrderSubmitResult
from qmtairlock.order_watch import OrderWatchTable
from qmtairlock.rpc_dispatch import BigQmtRpcHandlers
from qmtairlock.rpc_service import RpcService
from qmtairlock.rpc_settlement import PendingSettlement, SettlementManager
from qmtairlock.trader_client import BigQmtXtTrader
from qmtairlock.transports.base import TransportError
from qmtairlock.transports.pipe_client import ClientConnection, NamedPipeClient


def handlers(kind="STOCK", native=None):
    native = native or Mock(return_value=[])
    writes = Mock()
    gateway = BigQmtOrderGateway(object(), "TEST", writes, Mock(return_value=False), native, account_type=kind)
    queries = OrderQueries(None, native, "TEST")
    queries.account_type = kind
    owner = BigQmtRpcHandlers(
        "TEST",
        position_provider=BigQmtPositionProvider(native, kind),
        order_gateway=gateway,
        order_queries=queries,
        allow_order_methods=True,
        account_types=[kind],
    )
    return owner, writes


@pytest.mark.parametrize("public,native", [(value, value + 2) for value in range(48, 58)])
def test_option_public_order_types_reach_correct_native_operation(public, native):
    owner, writes = handlers("STOCK_OPTION")
    result = owner.handle(
        "submit_order",
        {"stock_code": "10000001.SHO", "order_type": public, "order_volume": 1, "price": 0.1, "wait_settlement": False},
    )
    assert result.status == "SUBMITTED"
    assert writes.call_args.args[0] == native


@pytest.mark.parametrize(
    "public,native", [(value, value) for value in range(27, 33)] + [(value, value + 30) for value in range(40, 46)]
)
def test_credit_order_types_preserve_special_and_direct_repayment(public, native):
    owner, writes = handlers("CREDIT")
    owner.handle(
        "submit_order",
        {"stock_code": "600000.SH", "order_type": public, "order_volume": 100, "price": 10, "wait_settlement": False},
    )
    assert writes.call_args.args[0] == native


def test_option_sell_open_keeps_direction_independent_of_offset():
    row = SimpleNamespace(
        m_strInstrumentID="10000001",
        m_strExchangeID="SHO",
        m_nDirection=49,
        m_nOffsetFlag=48,
        m_strOrderSysID="000001",
        m_nOrderStatus=50,
        m_nVolumeTotalOriginal=1,
    )
    owner, _ = handlers("STOCK_OPTION", Mock(return_value=[row]))
    order = owner.handle("query_orders", {})[0]
    assert order.action == "SELL" and order.account_type == 6
    trader = BigQmtXtTrader("TEST")
    obj = trader._order_from_dict("TEST", vars(order))
    assert obj.order_type == 50 and obj.order_sysid == "000001"


def test_raw_passorder_accepts_zero_native_optype_without_settlement():
    owner, writes = handlers("FUTURE")
    result = owner.handle("passorder", {"op_type": 0, "order_type": 1101, "order_code": "IF2612.IF", "volume": 1})
    assert result["submitted"] and writes.call_args.args[0] == 0


def test_batch_requires_tags_and_never_retries_an_unknown_dispatch():
    owner, writes = handlers()
    item = {"stock_code": "600000.SH", "order_type": 23, "order_volume": 100, "price": 10}
    rejected = owner.handle("submit_orders_batch", {"orders": [item]})
    assert rejected[0]["explicit_failure"] and not rejected[0]["accepted"]
    writes.assert_not_called()
    item["order_remark"] = "unique-intent"
    writes.side_effect = RuntimeError("native dispatch unknown")
    first = owner.handle("submit_orders_batch", {"orders": [item]})
    second = owner.handle("submit_orders_batch", {"orders": [item]})
    assert first[0]["explicit_failure"] is False and second[0]["idempotent"]
    writes.assert_called_once()


@pytest.mark.parametrize(
    "status,expected", [(50, False), (51, True), (52, True), (53, True), (54, True), (56, False), (57, False)]
)
def test_cancel_confirmation_uses_native_state_instead_of_native_boolean(status, expected):
    watch = OrderWatchTable()
    watch.note({"order_sys_id": "0001", "status": 50})
    queries = SimpleNamespace(
        query_orders_strict=Mock(return_value=[SimpleNamespace(order_sys_id="0001", status=status)])
    )
    manager = SettlementManager(queries, watch)
    pending = PendingSettlement(
        "cancel", CancelResult(not expected), "TEST", "STOCK", time.monotonic() - 1, order_sys_id="0001"
    )
    assert manager.step(pending)
    assert pending.result.success is expected
    queries.query_orders_strict.assert_called_once()


def test_late_old_callback_cannot_supply_a_new_orders_identity():
    watch = OrderWatchTable()
    now = time.time()
    watch.note(
        {
            "order_sys_id": "OLD",
            "status": 50,
            "remark": "same",
            "stock_code": "600000.SH",
            "action": "BUY",
            "order_time": now - 3600,
        }
    )
    order = OrderRequest("s", "TEST", "BUY", "600000.SH", 100, 10, 11, "test", remark="same", order_type=23)
    pending = PendingSettlement(
        "order", OrderSubmitResult("SUBMITTED", "same"), "TEST", "STOCK", time.monotonic() + 1, order
    )
    manager = SettlementManager(SimpleNamespace(query_orders_strict=lambda *args: []), watch)
    assert manager.step(pending) is False
    assert pending.result.order_sys_id is None


def test_baseline_query_cannot_send_an_order_after_its_deadline(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("qmtairlock.account_scope.time.time", lambda: clock[0])

    def slow_query(*args):
        clock[0] += 2
        return []

    owner, writes = handlers(native=Mock(side_effect=slow_query))
    service = RpcService(owner, "TEST", Mock())
    request = {
        "account_id": "TEST",
        "request_id": "expiring",
        "timeout_seconds": 1,
        "method": "submit_order",
        "params": {"stock_code": "600000.SH", "order_type": 23, "order_volume": 100},
    }
    service.enqueue_payload(request)
    service.drain_pending()
    writes.assert_not_called()
    assert service._order_requests[("TEST", "expiring")]["state"] == "refused"


def test_account_exception_stays_an_rpc_error_and_valid_asset_can_be_converted():
    owner, _ = handlers(native=Mock(side_effect=RuntimeError("counter unavailable")))
    reply = RpcService(owner, "TEST", Mock()).process_request(
        {"request_id": "asset", "account_id": "TEST", "method": "get_asset"}
    )
    assert not reply["ok"] and "counter unavailable" in reply["error"]
    trader = BigQmtXtTrader("TEST")
    trader.client.call = Mock(return_value={"account_id": "TEST", "cash": 10, "total_asset": 20})
    assert trader.query_stock_asset("TEST").cash == 10


@pytest.mark.parametrize(
    "method",
    [
        "query_account_infos",
        "query_stock_positions",
        "query_position_statistics",
        "query_stock_orders",
        "query_stock_trades",
        "query_execution_snapshot",
    ],
)
def test_native_account_query_failure_is_never_an_empty_result(method):
    owner, _ = handlers(native=Mock(side_effect=RuntimeError("counter unavailable")))
    reply = RpcService(owner, "TEST", Mock()).process_request(
        {"request_id": method, "account_id": "TEST", "method": method}
    )
    assert reply["ok"] is False and reply["data"] is None
    assert "counter unavailable" in reply["error"]


@pytest.mark.parametrize("field", ["m_nVolume", "m_nCanUseVolume", "m_nYesterdayVolume"])
def test_missing_position_quantity_fails_but_native_zero_is_kept(field):
    row = SimpleNamespace(
        m_strInstrumentID="600000",
        m_strExchangeID="SH",
        m_nVolume=0,
        m_nCanUseVolume=0,
        m_nYesterdayVolume=0,
    )
    owner, _ = handlers(native=Mock(return_value=[row]))
    position = owner.handle("query_stock_positions", {})[0]
    assert (position.volume, position.available, position.yesterday_volume) == (0, 0, 0)
    delattr(row, field)
    reply = RpcService(owner, "TEST", Mock()).process_request(
        {"request_id": "missing", "account_id": "TEST", "method": "query_stock_positions"}
    )
    assert reply["ok"] is False and field in reply["error"]


def test_native_write_failure_is_unknown_and_never_resent():
    transport = NamedPipeClient("TEST")
    transport._client_connection = Mock(return_value=ClientConnection(Mock(), 42))
    transport._wire.write = Mock(side_effect=TransportError("already delivered, completion unknown"))
    transport._drop_client_handle = Mock()
    with pytest.raises(TransportError):
        transport.send_request({"request_id": "x"}, 1)
    transport._wire.write.assert_called_once()


def test_native_short_write_is_rejected():
    transport = NamedPipeClient("TEST")
    transport._wire._wintypes = SimpleNamespace(DWORD=ctypes.c_uint32)

    def short(handle, payload, length, written, overlap):
        written._obj.value = length - 1
        return True

    transport._wire.dll = lambda: SimpleNamespace(WriteFile=short)
    with pytest.raises(TransportError, match="short pipe write"):
        transport._wire.write(42, b"{}")


def test_batch_identity_cannot_silently_accept_a_different_order():
    owner, writes = handlers()
    item = {"stock_code": "600000.SH", "order_type": 23, "order_volume": 100, "price": 10, "order_remark": "one-intent"}
    assert owner.handle("submit_orders_batch", {"orders": [item]})[0]["accepted"]
    conflict = owner.handle("submit_orders_batch", {"orders": [dict(item, order_volume=200)]})[0]
    assert conflict["error"] == "IDEMPOTENCY_KEY_CONFLICT" and not conflict["accepted"]
    writes.assert_called_once()
