"""Host-side local IPC listener, request draining and connection-owned replies."""

import ctypes
import json
import queue
import threading
import time

from ..rpc_codec import decode_text
from .base import RpcTransport, TransportError
from .pipe_native import (
    _BUFFER_BYTES,
    _CONNECT_POLL_SECONDS,
    DEFAULT_PIPE_NAME,
    ERROR_PIPE_CONNECTED,
    GENERIC_READ,
    GENERIC_WRITE,
    INVALID_HANDLE_VALUE,
    OPEN_EXISTING,
    PIPE_ACCESS_DUPLEX,
    PIPE_READMODE_MESSAGE,
    PIPE_REJECT_REMOTE_CLIENTS,
    PIPE_TYPE_MESSAGE,
    PIPE_UNLIMITED_INSTANCES,
    PIPE_WAIT,
    NativePipeIO,
    pipe_path,
)


class _ServerPipeConnection(object):
    """句柄值可复用，连接对象不可复用。

    请求、待发队列、关闭操作都持有这个对象。I/O 与 CloseHandle 共用锁，
    防止检查身份后、真正 WriteFile 前句柄已被回收；取消 I/O 用独立状态锁，
    既能唤醒阻塞读写，又不会在 CloseHandle 后取消另一个连接的同值句柄。
    """

    def __init__(self, handle, background=False):
        self.handle = handle
        self.outbox = queue.Queue() if background else None
        self.closing = threading.Event()
        self._io_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = False

    def call(self, function, *args):
        with self._io_lock:
            if self.closing.is_set():
                return None
            return function(self.handle, *args)

    def cancel(self, dll):
        with self._state_lock:
            if not self._closed:
                try:
                    dll.CancelIoEx(self.handle, None)
                except Exception:
                    pass

    def close(self, dll):
        self.closing.set()
        # 取消可能落在另一个线程检查 closing 与进入内核 I/O 之间，必须在
        # 等锁期间继续取消；一次 CancelIoEx 不足以保证同步句柄能被关闭。
        while not self._io_lock.acquire(timeout=_CONNECT_POLL_SECONDS):
            self.cancel(dll)
        try:
            with self._state_lock:
                if self._closed:
                    return
                self._closed = True
                try:
                    dll.DisconnectNamedPipe(self.handle)
                except Exception:
                    pass
                try:
                    dll.CloseHandle(self.handle)
                except Exception:
                    pass
        finally:
            self._io_lock.release()


class NamedPipeServer(RpcTransport):
    """Accept local connections and dispatch complete request messages."""

    name = "pipe"

    def __init__(self, account_id="", print_prefix="[qmtairlock]", pipe_name=DEFAULT_PIPE_NAME):
        super(NamedPipeServer, self).__init__(account_id, print_prefix)
        self.pipe_name = str(pipe_name or DEFAULT_PIPE_NAME)
        self.path = pipe_path(self.pipe_name, account_id)
        self._wire = NativePipeIO()
        self._listener = None
        self._server_handles = {}
        self._accepting = None
        self._lifecycle_lock = threading.RLock()
        self._server_lock = threading.RLock()
        self._background_threads = True
        self._drain_handles = []
        self._closed = False

    def start_receiving(self, on_request, **kwargs):
        """Accept connections; select worker I/O or main-thread drain with background_threads."""
        with self._lifecycle_lock:
            if self._closed:
                raise TransportError("pipe transport is closed")
            if self._listener is not None and self._listener.is_alive():
                raise TransportError("pipe listener already running")
            with self._server_lock:
                super(NamedPipeServer, self).start_receiving(on_request)
                background = kwargs.get("background_threads")
                self._background_threads = True if background is None else bool(background)
            self._listener = threading.Thread(target=self._accept_loop, name="bigqmt-pipe-accept")
            self._listener.daemon = True
            self._listener.start()

    def _register_server_connection(self, handle):
        connection = _ServerPipeConnection(handle, self._background_threads)
        with self._server_lock:
            if self._running:
                self._server_handles[handle] = connection
                return connection
        # stop 落在 CreateNamedPipeW 和登记之间：创建者自己关闭，绝不再 accept。
        connection.close(self._wire.dll())
        return None

    def _accept_loop(self):
        dll = self._wire.dll()
        while self._running:
            handle = dll.CreateNamedPipeW(
                self.path,
                PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                PIPE_UNLIMITED_INSTANCES,
                _BUFFER_BYTES,
                _BUFFER_BYTES,
                0,
                None,
            )
            if handle == INVALID_HANDLE_VALUE:
                if not self._running:
                    return
                time.sleep(_CONNECT_POLL_SECONDS)
                continue
            connection = self._register_server_connection(handle)
            if connection is None:
                return
            try:
                with self._server_lock:
                    if not self._running:
                        return
                    self._accepting = connection
                connected = connection.call(dll.ConnectNamedPipe, None)
                if connected is None or (not connected and self._wire.last_error() != ERROR_PIPE_CONNECTED):
                    continue
                with self._server_lock:
                    if not self._running or connection.closing.is_set():
                        return
                    if not self._background_threads:
                        self._drain_handles.append(connection)
                    else:
                        worker = threading.Thread(
                            target=self._serve_connection, args=(connection,), name="bigqmt-pipe-conn"
                        )
                        worker.daemon = True
                        worker.start()
                connection = None  # 已交给 drain/worker，accept 不再负责关闭。
            finally:
                with self._server_lock:
                    self._accepting = None
                if connection is not None:
                    self._close_server_connection(connection)

    def _connection_active(self, connection):
        with self._server_lock:
            return (
                self._running
                and connection is not None
                and self._server_handles.get(connection.handle) is connection
                and not connection.closing.is_set()
            )

    def _write_server_connection(self, connection, payload):
        if not self._connection_active(connection):
            return
        try:
            connection.call(self._wire.write, payload)
        except Exception:
            self._close_server_connection(connection)
            raise

    def _serve_connection(self, connection):
        """同一 worker 串行读写；异步回包仅入该连接自己的队列。

        同步管道句柄不能一边阻塞 ReadFile 一边由 adjust WriteFile。异步
        回包先入队再 CancelIoEx 唤醒读，只有本 worker 向原连接写出。
        关闭后队列随连接作废，不能拿相同的整数句柄向新连接补发。
        """
        outbox = connection.outbox
        try:
            while self._connection_active(connection):
                while not outbox.empty():
                    self._write_server_connection(connection, outbox.get())
                try:
                    raw = connection.call(self._wire.read)
                except TransportError:
                    return
                if not raw:
                    continue  # CancelIoEx 唤醒；关闭时下一轮身份检查会退出。
                try:
                    request = json.loads(decode_text(raw))
                    if not isinstance(request, dict):
                        return
                except Exception:
                    return
                request["_pipe_connection"] = connection
                self.deliver(request)
        finally:
            # stop 后迟到的回包必须丢弃，不能在 finally 按旧整数句柄补发。
            self._close_server_connection(connection)

    def _peek_available(self, handle):
        """这个句柄上有没有待读数据。PeekNamedPipe 不阻塞，可用于同步句柄。"""
        dll = self._wire.dll()
        avail = self._wire._wintypes.DWORD(0)
        ok = dll.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
        if not ok:
            raise TransportError("PeekNamedPipe failed (err=%s)" % self._wire.last_error())
        return avail.value

    def drain_request_queue(self, max_items=20):
        """drain 模式：adjust 线程自己把请求读出来、处理掉、把响应写回去。

        读、handler、写全在同一条线程上，所以没有跨线程交接，也不需要
        outbox + CancelIoEx 那套唤醒机制 —— 那套是 background_threads=True
        时才需要的。

        非阻塞：先 PeekNamedPipe 看有没有数据，有才 ReadFile。没有就跳过，
        绝不能在 adjust 线程上阻塞等下一个请求。
        """
        if self._background_threads:
            return 0  # 工作线程在收，这里不插手
        processed = 0
        with self._server_lock:
            connections = list(self._drain_handles)
        for connection in connections:
            while processed < int(max_items) and self._connection_active(connection):
                try:
                    raw = connection.call(self._read_available)
                    if not raw:
                        break
                    request = json.loads(decode_text(raw))
                    if not isinstance(request, dict):
                        raise ValueError("pipe request must be a JSON object")
                except (TransportError, ValueError):
                    self._close_server_connection(connection)
                    break
                request["_pipe_connection"] = connection
                # deliver 已调用 send_response；再写一次会把重复回包留给下一请求。
                self.deliver(request)
                processed += 1
        return processed

    def _read_available(self, handle):
        return self._wire.read(handle) if self._peek_available(handle) else None

    def send_response(self, request, response):
        """只向仍属于本服务的原连接回包；句柄相同不代表连接相同。"""
        connection = (request or {}).get("_pipe_connection")
        if not self._connection_active(connection):
            return
        payload = json.dumps(response, ensure_ascii=False, default=str).encode("utf-8")
        if connection.outbox is None:
            self._write_server_connection(connection, payload)
        else:
            connection.outbox.put(payload)
            connection.cancel(self._wire.dll())

    def _close_server_connection(self, connection):
        # 从注册表摘除必须认对象，旧 worker 的 finally 不能关新连接的同值句柄。
        connection.closing.set()
        with self._server_lock:
            if self._server_handles.get(connection.handle) is connection:
                del self._server_handles[connection.handle]
            if connection in self._drain_handles:
                self._drain_handles.remove(connection)
        connection.close(self._wire.dll())

    def _wake_accept(self):
        try:
            dll = self._wire.dll()
            handle = dll.CreateFileW(self.path, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
            if handle != INVALID_HANDLE_VALUE:
                dll.CloseHandle(handle)
        except Exception:
            pass

    def stop(self):
        with self._lifecycle_lock:
            with self._server_lock:
                self._running = False
                self._closed = True
                server = list(self._server_handles.values())
                for connection in server:
                    connection.closing.set()
                accepting = self._accepting
            # ConnectNamedPipe 可能刚准备进入内核；自连同时覆盖已经阻塞与
            # 尚未开始的情形（后者得到 ERROR_PIPE_CONNECTED）。
            if accepting is not None:
                self._wake_accept()
            for connection in server:
                self._close_server_connection(connection)
            listener = self._listener
            if listener is not None and listener is not threading.current_thread():
                while listener.is_alive():
                    self._wake_accept()
                    listener.join(_CONNECT_POLL_SECONDS)
            self._listener = None
            super(NamedPipeServer, self).stop()
