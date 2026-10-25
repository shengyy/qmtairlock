# coding: utf-8
"""Windows stdio relay for same-host messages using standard-library code.

Frames carry a four-byte big-endian length and an unchanged JSON payload.
The initial handshake selects the local channel and connection deadline.
Stdout is reserved for frames; diagnostics are written to stderr.
"""

import json
import math
import os
import queue
import struct
import sys
import threading

MAX_FRAME_BYTES = 256 * 1024 * 1024


def frame_header(size):
    if not 0 <= size <= MAX_FRAME_BYTES:
        raise ValueError("relay frame exceeds 256 MiB")
    return struct.pack("!I", size)


def frame_size(header):
    size = struct.unpack("!I", header)[0]
    frame_header(size)
    return size


def _read_exact(stream, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("truncated relay frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream):
    """None 只表示帧边界的 EOF；半个 header/payload 是断帧，不能转发。"""
    first = stream.read(4)
    if not first:
        return None
    header = first + _read_exact(stream, 4 - len(first))
    return _read_exact(stream, frame_size(header))


def write_frame(stream, payload):
    data = memoryview(frame_header(len(payload)) + payload)
    while data:
        written = stream.write(data)
        if not written:
            raise EOFError("relay stdout closed")
        data = data[written:]
    stream.flush()


def relay(read_next, output, transport_factory=None):
    """Forward only complete frames, once each, preserving the native JSON payload."""
    from .pipe_client import NamedPipeClient

    raw = read_next()
    if raw is None:
        return
    hello = json.loads(raw.decode("utf-8"))
    path = hello["pipe_path"]
    if not isinstance(path, str) or not path.startswith("\\\\.\\pipe\\") or "\x00" in path:
        raise ValueError("relay requires a local Windows pipe path")
    timeout = float(hello.get("connect_timeout_seconds", 5.0))
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("connect_timeout_seconds must be finite and positive")
    transport = (transport_factory or NamedPipeClient)(connect_timeout_seconds=timeout)
    transport.path = path
    try:
        # 原生连接器已在期限内重试 PIPE_BUSY / FILE_NOT_FOUND。
        handle = transport._client_handle()
        write_frame(output, b"")
        while True:
            payload = read_next()
            if payload is None:
                return
            if transport._wire.write(handle, payload) != len(payload):
                raise OSError("short pipe message write; outcome unknown")
            response = transport._wire.read(handle)
            if not response:
                raise EOFError("pipe disconnected")
            write_frame(output, response)
    finally:
        transport.stop()


def _diagnostic(exc):
    # 不带管道路径/账号，不打印 traceback，不让换行污染一行一条的诊断。
    message = str(exc).replace("\r", " ").replace("\n", " ")
    print("pipe_relay: %s: %s" % (type(exc).__name__, message), file=sys.stderr, flush=True)


def main():
    if os.name != "nt":
        _diagnostic(RuntimeError("run this module with Windows Python"))
        return 1
    # Windows CRT 文本模式会改写 CR/LF，并把 0x1a 当 EOF，必须显式 binary。
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    frames = queue.Queue(maxsize=1)

    def pump_stdin():
        """父进程关闭 stdin 时连阻塞中的 ReadFile 也必须退出。

        不能等 RPC 返回才读到 EOF（QMT 可能永远不回包）。中继没有持久化
        状态，每个 stdout 帧已 flush；此时退出进程由 Windows 关闭全部句柄，
        比跨线程 CancelIoEx 与下一次同步 ReadFile 的竞态更可靠。
        """
        try:
            while True:
                frame = read_frame(sys.stdin.buffer.raw)
                if frame is None:
                    os._exit(0)
                frames.put(frame)
        except Exception as exc:
            _diagnostic(exc)
            os._exit(1)

    reader = threading.Thread(target=pump_stdin, name="bigqmt-relay-stdin")
    reader.daemon = True
    reader.start()
    try:
        relay(frames.get, sys.stdout.buffer)
        return 0
    except Exception as exc:
        # CreateFileW 的异常含路径，只报告阶段及错误类型，账号不进诊断。
        _diagnostic(RuntimeError("pipe connection or exchange failed (%s)" % type(exc).__name__))
        return 1


if __name__ == "__main__":
    try:
        _exit_code = main()
    except Exception as exc:
        _diagnostic(RuntimeError("relay startup failed (%s)" % type(exc).__name__))
        _exit_code = 1
    # stdin pump 可能仍在 Windows CRT 的阻塞读里。所有帧/诊断已经 flush，
    # 由 OS 直接回收句柄，别让 Python 终结标准流时再等待该守护线程。
    os._exit(_exit_code)
