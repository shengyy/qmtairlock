"""清扫存活快照与注册必须有同一线性化边界。"""

import threading
from unittest import mock

from qmtairlock.transports.pipe_client import ClientConnection, NamedPipeClient


def test_sweep_does_not_close_newly_registered_live_thread(monkeypatch):
    transport = NamedPipeClient()
    dll = mock.Mock()
    transport._wire.dll = lambda: dll
    original = threading.enumerate
    ready, release = (threading.Event(), threading.Event())

    def register():
        with transport._lock:
            transport._client_threads[threading.current_thread().ident] = (ClientConnection(dll, 321), object())
        ready.set()
        release.wait(timeout=3)

    worker = threading.Thread(target=register)

    def snapshot():
        live = original()
        worker.start()
        ready.wait(timeout=0.2)
        return live

    monkeypatch.setattr(threading, "enumerate", snapshot)
    try:
        transport._sweep_dead_thread_handles()
        assert ready.wait(timeout=2)
        dll.CloseHandle.assert_not_called()
        assert worker.ident in transport._client_threads
    finally:
        release.set()
        worker.join(timeout=3)
        transport.stop()
