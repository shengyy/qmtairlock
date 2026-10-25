"""Native message I/O, addressing and wire identity validation shared by both roles."""

import ctypes
import os
import threading

from .base import TransportError

DEFAULT_PIPE_NAME = "qmtairlock"
_PIPE_ROOT = "\\\\.\\pipe\\"

# kernel32 constants (winbase.h)
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008  # 同机信任边界：拒绝 SMB 远程客户端。
PIPE_UNLIMITED_INSTANCES = 255
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_PIPE_CONNECTED = 535
ERROR_PIPE_BUSY = 231
ERROR_MORE_DATA = 234
ERROR_OPERATION_ABORTED = 995
ERROR_INVALID_HANDLE = 6
ERROR_BROKEN_PIPE = 109
ERROR_FILE_NOT_FOUND = 2

_BUFFER_BYTES = 1 << 20  # 1MB: whole-market quote frames are large
_CONNECT_POLL_SECONDS = 0.05


def _kernel32():
    if os.name != "nt":
        raise TransportError(
            "native named pipes require Windows (os.name=%r); configure a WSL relay on POSIX" % os.name
        )
    from ctypes import wintypes

    # 部分券商 QMT 内置 Python 3.6 的 ctypes.wintypes 缺 HANDLE/BOOL
    # （切 pipe 即 AttributeError）。Win32 HANDLE 是指针宽、BOOL 是
    # 32 位有符号整型，用 c_void_p / c_int32 兜底，类型全的 build 不受影响。
    handle_type = getattr(wintypes, "HANDLE", ctypes.c_void_p)
    bool_type = getattr(wintypes, "BOOL", ctypes.c_int32)

    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer, dword = ctypes.c_void_p, wintypes.DWORD
    signatures = {
        "CreateNamedPipeW": (handle_type, [ctypes.c_wchar_p, dword, dword, dword, dword, dword, dword, pointer]),
        "CreateFileW": (handle_type, [ctypes.c_wchar_p, dword, dword, pointer, dword, dword, handle_type]),
        "ReadFile": (bool_type, [handle_type, pointer, dword, pointer, pointer]),
        "WriteFile": (bool_type, [handle_type, pointer, dword, pointer, pointer]),
        "PeekNamedPipe": (bool_type, [handle_type, pointer, dword, pointer, pointer, pointer]),
        "SetNamedPipeHandleState": (bool_type, [handle_type, pointer, pointer, pointer]),
        "ConnectNamedPipe": (bool_type, [handle_type, pointer]),
        "CancelIoEx": (bool_type, [handle_type, pointer]),
        "DisconnectNamedPipe": (bool_type, [handle_type]),
        "CloseHandle": (bool_type, [handle_type]),
    }
    for name, (result_type, arguments) in signatures.items():
        function = getattr(dll, name)
        function.restype = result_type
        function.argtypes = arguments
    return dll, wintypes


def pipe_path(name=DEFAULT_PIPE_NAME, account_id=""):
    """Local pipe name scoped by the configured account id."""
    suffix = ("_" + str(account_id)) if account_id else ""
    return _PIPE_ROOT + str(name or DEFAULT_PIPE_NAME) + suffix


def _validate_pipe_response(request, response):
    """完整请求发出后的错配属于未知结果，绝不能触发下单/撤单重发。"""
    if not isinstance(response, dict) or response.get("request_id") != request.get("request_id"):
        raise TransportError("pipe response request_id mismatch; outcome unknown")
    return response


class NativePipeIO:
    """Own the native API binding and per-thread buffers for complete messages."""

    def __init__(self):
        self._k32 = None
        self._wintypes = None
        self._io_local = threading.local()

    def dll(self):
        if self._k32 is None:
            self._k32, self._wintypes = _kernel32()
        return self._k32

    def last_error(self):
        return ctypes.get_last_error()

    def write(self, handle, payload):
        dll = self.dll()
        written = self._wintypes.DWORD()
        ok = dll.WriteFile(handle, payload, len(payload), ctypes.byref(written), None)
        if not ok:
            raise TransportError("WriteFile failed (err=%s)" % self.last_error())
        if written.value != len(payload):
            raise TransportError("short pipe write; outcome unknown")
        return written.value

    def _read_buffer(self):
        """Reuse one message buffer per I/O thread."""
        buf = getattr(self._io_local, "buf", None)
        if buf is None:
            buf = ctypes.create_string_buffer(_BUFFER_BYTES)
            self._io_local.buf = buf
        return buf

    def read(self, handle):
        """Read one message; b"" only for a CancelIoEx wake, raise for a real close.

        Two outcomes MUST be told apart now that writes are driven by waking
        the reader: CancelIoEx (a writer woke us so we can write) returns
        ERROR_OPERATION_ABORTED -- that is a wake, not a close; a peer going
        away (ERROR_BROKEN_PIPE / ERROR_INVALID_HANDLE) IS a close and the
        connection is over.
        """
        dll = self.dll()
        buf = self._read_buffer()
        read = self._wintypes.DWORD()
        chunks = []
        while True:
            ok = dll.ReadFile(handle, buf, _BUFFER_BYTES, ctypes.byref(read), None)
            if read.value:
                chunks.append(ctypes.string_at(buf, read.value))
            if ok:
                break
            err = self.last_error()
            if err == ERROR_MORE_DATA:
                continue
            if err == ERROR_OPERATION_ABORTED:
                return b""  # a writer woke us to write; not a close
            if err in (ERROR_INVALID_HANDLE, ERROR_BROKEN_PIPE):
                raise TransportError("pipe closed (err=%s)" % err)
            raise TransportError("ReadFile failed (err=%s)" % err)
        return b"".join(chunks)
