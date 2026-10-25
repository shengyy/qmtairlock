"""迟到回包必须认连接对象；的整数句柄复用不能成为回包路由。"""

import json
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from qmtairlock.rpc_service import RpcService
from qmtairlock.transports.base import TransportError
from qmtairlock.transports.pipe_client import ClientConnection, NamedPipeClient
from qmtairlock.transports.pipe_server import NamedPipeServer, _ServerPipeConnection


class _ThreadNamingMarketData:
    pass


def _service(market_data, transport):
    handlers = SimpleNamespace(
        handle=lambda method, params: (
            market_data.get_financial_data() if method == "get_financial_data" else {"pong": True}
        )
    )
    return (handlers, RpcService(handlers, "acct", transport))


def attach(server, handle):
    if hasattr(server, "_register_server_connection"):
        connection = server._register_server_connection(handle)
    else:
        server._server_handles.append(handle)
        connection = handle
    server._drain_handles.append(connection)
    return connection


def close_connection(server, connection):
    if hasattr(server, "_close_server_connection"):
        server._close_server_connection(connection)
    else:
        server._forget_drain_handle(connection)


def fake_wire(server, writes):
    incoming = []
    server._wire.dll = lambda: mock.Mock()
    server._accept_loop = lambda: None
    server._peek_available = lambda handle: bool(incoming)
    server._wire.read = lambda handle: json.dumps(incoming.pop(0)).encode()
    server._wire.write = lambda handle, data: writes.append((handle, json.loads(data)))
    return incoming


class BlockingMarket(_ThreadNamingMarketData):
    def __init__(self):
        super().__init__()
        self.entered, self.release = (threading.Event() for _ in range(2))

    def get_financial_data(self, *args, **kwargs):
        self.entered.set()
        assert self.release.wait(5), "test did not release heavy read"
        return {"old": True}


def request(request_id, method="ping"):
    return dict(request_id=request_id, account_id="acct", method=method, params={})


@pytest.mark.parametrize("stop_service", [False])
def test_late_heavy_reply_cannot_reach_reused_handle(stop_service):
    writes = []
    old = NamedPipeServer()
    incoming = fake_wire(old, writes)
    market = BlockingMarket()
    _, service = _service(market_data=market, transport=old)
    service.start()
    connection = attach(old, 42)
    incoming.append(request("old-request", "get_financial_data"))
    old.drain_request_queue()
    assert market.entered.wait(2)
    worker = service._heavy_thread
    new = old
    try:
        if stop_service:
            service.stop()
            new = NamedPipeServer()
            incoming = fake_wire(new, writes)
            new.start_receiving(lambda req: {"request_id": req["request_id"], "ok": True}, background_threads=False)
        else:
            close_connection(old, connection)
        attach(new, 42)
        incoming.append(request("new-request"))
        new.drain_request_queue()
        market.release.set()
        if stop_service:
            worker.join(2)
        else:
            deadline = time.monotonic() + 2
            while service._heavy_replies.empty() and time.monotonic() < deadline:
                time.sleep(0.005)
            assert not service._heavy_replies.empty()
        service.flush_heavy_replies()
        assert [reply["request_id"] for _, reply in writes] == ["new-request"], writes
        incoming.append(request("next-request"))
        new.drain_request_queue()
        assert [reply["request_id"] for _, reply in writes] == ["new-request", "next-request"]
    finally:
        market.release.set()
        service.stop()
        if new is not old:
            new.stop()
        worker.join(2)


def test_drain_delivers_exactly_one_response():
    server = NamedPipeServer()
    writes = []
    incoming = fake_wire(server, writes)
    server.start_receiving(lambda req: {"request_id": req["request_id"], "ok": True}, background_threads=False)
    try:
        attach(server, 42)
        incoming.extend([request("one"), request("two")])
        server.drain_request_queue()
        assert [reply["request_id"] for _, reply in writes] == ["one", "two"]
    finally:
        server.stop()


@pytest.mark.parametrize("response", [{"request_id": "other", "ok": True}, {"ok": True}])
def test_native_client_rejects_wrong_request_id_without_resending(response):
    client = NamedPipeClient()
    client._client_connection = mock.Mock(return_value=ClientConnection(mock.Mock(), 42))
    client._wire.write = mock.Mock()
    client._wire.read = mock.Mock(return_value=json.dumps(response).encode())
    client._drop_client_handle = mock.Mock()
    with pytest.raises(TransportError):
        client.send_request(request("mine", "order_stock"), 1)
    client._wire.write.assert_called_once()
    client._drop_client_handle.assert_called_once()


def test_close_between_identity_check_and_write_cannot_target_reused_handle():
    server, writes = (NamedPipeServer(), [])
    fake_wire(server, writes)
    server.start_receiving(lambda req: None, background_threads=False)
    old = attach(server, 42)
    checked, resume = (threading.Event(), threading.Event())
    original = old.call

    def delayed_call(*args):
        checked.set()
        assert resume.wait(2)
        return original(*args)

    old.call = delayed_call
    writer = threading.Thread(target=lambda: server.send_response({"_pipe_connection": old}, {"request_id": "old"}))
    writer.start()
    try:
        assert checked.wait(1)
        close_connection(server, old)
        new = attach(server, 42)
        server.send_response({"_pipe_connection": new}, {"request_id": "new"})
        resume.set()
        writer.join(2)
        assert not writer.is_alive()
        assert writes == [(42, {"request_id": "new"})]
        close_connection(server, old)
        assert server._connection_active(new)
        assert not new.closing.is_set()
    finally:
        resume.set()
        writer.join(2)
        server.stop()


def test_closed_background_outbox_is_never_flushed_to_reused_handle():
    server, writes = (NamedPipeServer(), [])
    fake_wire(server, writes)
    server.start_receiving(lambda req: None, background_threads=True)
    try:
        old = server._register_server_connection(42)
        server.send_response({"_pipe_connection": old}, {"request_id": "old"})
        assert old.outbox.qsize() == 1
        close_connection(server, old)
        new = server._register_server_connection(42)
        server._serve_connection(old)
        server.send_response({"_pipe_connection": old}, {"request_id": "later"})
        assert writes == [] and new.outbox.empty()
        assert server._connection_active(new)
    finally:
        server.stop()


def test_close_retries_cancel_if_first_cancel_precedes_kernel_io():
    connection = _ServerPipeConnection(42)
    checked, entered, finished = (threading.Event() for _ in range(3))
    dll = mock.Mock()

    def io_call(handle):
        checked.set()
        assert entered.wait(2)
        assert finished.wait(2)

    def cancel(*args):
        if not entered.is_set():
            entered.set()
        else:
            finished.set()

    dll.CancelIoEx.side_effect = cancel
    worker = threading.Thread(target=lambda: connection.call(io_call))
    worker.start()
    assert checked.wait(1)
    try:
        connection.close(dll)
        worker.join(2)
        assert not worker.is_alive()
        assert dll.CancelIoEx.call_count >= 2
        dll.CloseHandle.assert_called_once_with(42)
        connection.cancel(dll)
        connection.close(dll)
        dll.CloseHandle.assert_called_once_with(42)
    finally:
        entered.set()
        finished.set()
        worker.join(2)
