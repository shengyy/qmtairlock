"""Native handle ownership under connection, timeout and shutdown races."""

import ctypes
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from qmtairlock.transports.base import TransportError
from qmtairlock.transports.pipe_client import ClientConnection
from qmtairlock.transports.pipe_transport import NamedPipeTransport


def test_stop_during_connect_closes_unregistered_handle_and_refuses_future_requests():
    entered, release = threading.Event(), threading.Event()
    dll = Mock()

    def connect(*args):
        entered.set()
        assert release.wait(1)
        return 77

    dll.CreateFileW.side_effect = connect
    client = NamedPipeTransport()
    client._dll = lambda: dll
    client._wintypes = SimpleNamespace(DWORD=ctypes.c_uint32)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(client.send_request, {"request_id": "one"}, 1)
        assert entered.wait(1)
        client.stop()
        release.set()
        with pytest.raises(TransportError):
            pending.result()
    dll.CloseHandle.assert_called_once_with(77)
    assert not client._client_threads
    with pytest.raises(TransportError, match="closed"):
        client.send_request({"request_id": "two"}, 1)
    dll.WriteFile.assert_not_called()


def test_total_deadline_cancels_a_blocked_write_without_resending():
    cancelled = threading.Event()
    dll = Mock()
    dll.CancelIoEx.side_effect = lambda *args: cancelled.set()
    client = NamedPipeTransport()
    connection = ClientConnection(dll, 77)
    client._client_connection = lambda deadline: connection

    def write(*args):
        assert cancelled.wait(1)
        raise TransportError("write interrupted")

    client._write = Mock(side_effect=write)
    client._read = Mock()
    started = time.monotonic()
    with pytest.raises(TransportError):
        client.send_request({"request_id": "one"}, 0.02)
    assert time.monotonic() - started < 0.5
    client._write.assert_called_once()
    client._read.assert_not_called()
    connection.close()


def test_finishing_request_waits_for_its_canceller_before_reusing_handle():
    cancel_entered, release_cancel, finish_io = (threading.Event() for _ in range(3))
    dll = Mock()

    def cancel(*args):
        cancel_entered.set()
        assert release_cancel.wait(1)

    dll.CancelIoEx.side_effect = cancel
    connection = ClientConnection(dll, 77)
    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(connection.run, lambda handle: finish_io.wait(1), time.monotonic() + 0.01)
        assert cancel_entered.wait(1)
        finish_io.set()
        assert not first.done()
        release_cancel.set()
        with pytest.raises(TransportError):
            first.result()
    before = dll.CancelIoEx.call_count
    assert connection.run(lambda handle: "second", time.monotonic() + 1) == "second"
    assert dll.CancelIoEx.call_count == before
    connection.close()


def test_cancellation_repeats_until_kernel_io_has_started():
    dll = Mock()
    late_io = threading.Event()
    dll.CancelIoEx.side_effect = lambda *args: late_io.set() if dll.CancelIoEx.call_count >= 3 else None
    connection = ClientConnection(dll, 77)
    with pytest.raises(TransportError):
        connection.run(lambda handle: late_io.wait(1), time.monotonic() + 0.01)
    assert dll.CancelIoEx.call_count >= 3
    connection.close()
