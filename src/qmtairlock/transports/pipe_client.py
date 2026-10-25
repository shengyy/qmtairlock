"""Own one native client handle and cancel only its active request."""

import threading
import time

from .base import TransportError, TransportTimeout


class ClientConnection(object):
    def __init__(self, dll, handle):
        self.dll = dll
        self.handle = handle
        self.closing = threading.Event()
        self._io_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = False
        self._active = None

    def _cancel(self, token=None):
        with self._state_lock:
            if self._closed or (token is not None and self._active is not token):
                return
            try:
                self.dll.CancelIoEx(self.handle, None)
            except Exception:
                pass

    def _watch(self, token, finished, deadline):
        if finished.wait(max(0.0, deadline - time.monotonic())):
            return
        # Cancellation can precede entry into synchronous Win32 I/O. Repeat
        # until this operation exits, while checking its identity under lock.
        while not finished.is_set():
            self._cancel(token)
            finished.wait(0.01)

    def run(self, function, deadline):
        with self._io_lock:
            if self.closing.is_set():
                raise TransportError("pipe client is closed")
            if time.monotonic() >= deadline:
                raise TransportTimeout("named pipe request deadline expired")
            token = object()
            finished = threading.Event()
            with self._state_lock:
                self._active = token
            watchdog = threading.Thread(target=self._watch, args=(token, finished, deadline))
            watchdog.daemon = True
            watchdog.start()
            try:
                result = function(self.handle)
            finally:
                with self._state_lock:
                    self._active = None
                    finished.set()
                watchdog.join()
            if self.closing.is_set():
                raise TransportError("pipe closed during request; outcome unknown")
            if time.monotonic() >= deadline:
                raise TransportTimeout("named pipe request timeout; outcome unknown")
            return result

    def close(self):
        self.closing.set()
        while not self._io_lock.acquire(timeout=0.01):
            self._cancel()
        try:
            with self._state_lock:
                if self._closed:
                    return
                self._closed = True
                try:
                    self.dll.CloseHandle(self.handle)
                except Exception:
                    pass
        finally:
            self._io_lock.release()
