"""Own one native client handle and cancel only its active request."""

import ctypes
import json
import threading
import time

from ..rpc_codec import decode_text
from .base import RpcTransport, TransportError, TransportTimeout
from .pipe_native import (
    _CONNECT_POLL_SECONDS,
    DEFAULT_PIPE_NAME,
    ERROR_FILE_NOT_FOUND,
    ERROR_PIPE_BUSY,
    GENERIC_READ,
    GENERIC_WRITE,
    INVALID_HANDLE_VALUE,
    OPEN_EXISTING,
    PIPE_READMODE_MESSAGE,
    NativePipeIO,
    _validate_pipe_response,
    pipe_path,
)


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


class _ClientHandleFinalizer(object):
    """Release only the connection registered to this thread identity and token."""

    __slots__ = ("_transport", "_ident", "_token")

    def __init__(self, transport, ident, token):
        self._transport = transport
        self._ident = ident
        self._token = token

    def __del__(self):
        try:
            self._transport._release_thread_handle(self._ident, self._token)
        except Exception:
            # 解释器退出边缘模块可能已被拆半，句柄由 OS 收，别在这里出事。
            pass


class NamedPipeClient(RpcTransport):
    """Persistent per-thread client connections with one deadline per RPC."""

    name = "pipe"

    def __init__(
        self, account_id="", print_prefix="[qmtairlock]", pipe_name=DEFAULT_PIPE_NAME, connect_timeout_seconds=5.0
    ):
        super(NamedPipeClient, self).__init__(account_id, print_prefix)
        self.pipe_name = str(pipe_name or DEFAULT_PIPE_NAME)
        self.path = pipe_path(self.pipe_name, account_id)
        self.connect_timeout_seconds = float(connect_timeout_seconds)
        self._wire = NativePipeIO()
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._client_local = threading.local()
        self._client_threads = {}
        self._closed = False

    def _client_handle(self):
        """Native handle used by the standalone stdio relay."""
        return self._client_connection().handle

    def _client_connection(self, deadline=None):
        with self._lock:
            if self._closed:
                raise TransportError("pipe client is closed")
            connection = getattr(self._client_local, "connection", None)
            if connection is not None:
                return connection
        self._sweep_dead_thread_handles()
        dll = self._wire.dll()
        deadline = min(deadline or float("inf"), time.monotonic() + self.connect_timeout_seconds)
        while True:
            with self._lock:
                if self._closed:
                    raise TransportError("pipe client is closed")
            if time.monotonic() >= deadline:
                raise TransportTimeout("named pipe connection timeout")
            handle = dll.CreateFileW(self.path, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
            if handle != INVALID_HANDLE_VALUE:
                break
            err = self._wire.last_error()
            if err not in (ERROR_PIPE_BUSY, ERROR_FILE_NOT_FOUND):
                raise TransportError("cannot connect to %s (err=%s)" % (self.path, err))
            time.sleep(min(_CONNECT_POLL_SECONDS, max(0.0, deadline - time.monotonic())))
        connection = ClientConnection(dll, handle)
        try:
            mode = self._wire._wintypes.DWORD(PIPE_READMODE_MESSAGE)
            if not dll.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
                raise TransportError("cannot set pipe message mode")
            ident = threading.current_thread().ident
            token = object()
            with self._lock:
                if self._closed or time.monotonic() >= deadline:
                    raise TransportError("pipe closed or connection deadline expired")
                self._client_local.connection = connection
                self._client_local.finalizer = _ClientHandleFinalizer(self, ident, token)
                stale = self._client_threads.get(ident)
                self._client_threads[ident] = (connection, token)
            if stale is not None:
                stale[0].close()
            return connection
        except Exception:
            connection.close()
            raise

    def _release_thread_handle(self, ident, token):
        """线程退出时关它自己的句柄 —— finalizer 的唯一入口。

        必须 (ident, token) 全等才动手：注册表里已是别的 token，说明这个
        ident 被新线程领走了，旧句柄由新线程注册时的 stale 分支（或
        _sweep）代关。内核句柄值会被回收复用，错关一次就是杀了一个无辜的
        活句柄 —— 那种 bug 只会在高并发下偶发，最难查。
        """
        with self._lock:
            entry = self._client_threads.get(ident)
            if entry is None or entry[1] is not token:
                return
            del self._client_threads[ident]
        entry[0].close()

    def _sweep_dead_thread_handles(self):
        """finalizer 没跑成的条目在这里兜底，每次新建连接前过一次。

        ident 同一时刻只属于一条活线程，所以不在 threading.enumerate()
        里的 ident 一定是死线程的残留。finalizer 在 CPython 上是随线程
        退出即时触发的，这里只为回收时点不保证的运行时（或解释器退出
        边缘）兜底。
        """
        dead = []
        with self._lock:
            # 采样与注册同锁，否则旧快照会漏掉刚注册的活线程并误关句柄。
            live = set(t.ident for t in threading.enumerate())
            for ident, entry in list(self._client_threads.items()):
                if ident in live:
                    continue
                del self._client_threads[ident]
                dead.append(entry[0])
        for connection in dead:
            connection.close()

    def send_request(self, request, timeout_seconds):
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        payload = json.dumps(request, ensure_ascii=False, default=str).encode("utf-8")
        try:
            connection = self._client_connection(deadline)

            def exchange(handle):
                self._wire.write(handle, payload)
                raw = self._wire.read(handle)
                if not raw:
                    raise TransportTimeout("named pipe request interrupted; outcome unknown")
                return json.loads(decode_text(raw))

            response = connection.run(exchange, deadline)
            return _validate_pipe_response(request, response)
        except (TransportError, ValueError, OSError) as exc:
            self._drop_client_handle()
            if isinstance(exc, TransportError):
                raise
            raise TransportError("invalid pipe response; outcome unknown") from exc

    def _drop_client_handle(self):
        connection = getattr(self._client_local, "connection", None)
        if connection is None:
            return
        with self._lock:
            self._client_threads.pop(threading.current_thread().ident, None)
        connection.close()
        self._client_local.connection = None

    def stop(self):
        with self._lifecycle_lock:
            with self._lock:
                self._closed = True
                connections = [entry[0] for entry in self._client_threads.values()]
                self._client_threads = {}
            for connection in connections:
                connection.close()
            self._client_local = threading.local()
            super(NamedPipeClient, self).stop()
