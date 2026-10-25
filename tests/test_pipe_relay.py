"""完整帧之后宁可未知，绝不让重连变成第二笔委托。"""

import io
import json
import os
import struct
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

from qmtairlock.transports.base import TransportError, TransportTimeout
from qmtairlock.transports.pipe_relay import MAX_FRAME_BYTES, frame_header, read_frame, relay, write_frame
from qmtairlock.transports.pipe_relay_transport import PipeRelayTransport

FAKE = '\nimport json, os, struct, sys, time\nmode = sys.argv[1]\ndef exact(n):\n    data = b""\n    while len(data) < n:\n        chunk = sys.stdin.buffer.read(n - len(data))\n        if not chunk: sys.exit(0)\n        data += chunk\n    return data\ndef read():\n    return exact(struct.unpack("!I", exact(4))[0])\ndef write(data):\n    data = struct.pack("!I", len(data)) + data\n    if mode == "fragment":\n        for i in range(0, len(data), 7):\n            sys.stdout.buffer.write(data[i:i+7]); sys.stdout.buffer.flush()\n    else:\n        sys.stdout.buffer.write(data); sys.stdout.buffer.flush()\nhello = json.loads(read())\nif mode == "handshake_stall": time.sleep(60)\nwrite(b"")\nif mode == "write_stall": time.sleep(60)\nwhile True:\n    raw = read()\n    # 每收到一个完整请求就留下回执，跨进程核对重发次数。\n    if len(sys.argv) > 2:\n        with open(sys.argv[2], "ab") as f: f.write(raw + b"\\n")\n    if mode == "stall": time.sleep(60)\n    if mode == "eof": sys.exit(0)\n    if mode == "crash": os._exit(9)\n    if mode == "partial":\n        sys.stdout.buffer.write(b"\\x00\\x00"); sys.stdout.buffer.flush(); sys.exit(0)\n    if mode == "oversize":\n        sys.stdout.buffer.write(struct.pack("!I", 0xffffffff)); sys.stdout.buffer.flush(); sys.exit(0)\n    if mode == "bad_json": write(b"{"); continue\n    req = json.loads(raw)\n    response = dict(pid=os.getpid(), hello=hello, echo=req, request_id=req.get("request_id"))\n    if mode == "mismatch": response["request_id"] = "somebody-elses-order"\n    if mode == "missing_id": response.pop("request_id")\n    write(json.dumps(response).encode())\n'


@pytest.fixture
def make_transport(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX stdio client; Windows relay covered by native e2e")
    made = []

    def make(mode="echo", receipt=None):
        command = [sys.executable, "-u", "-c", FAKE, mode]
        if receipt is not None:
            command.append(str(receipt))
        t = PipeRelayTransport(command, account_id="test-account", connect_timeout_seconds=2)
        made.append(t)
        return t

    yield make
    for t in made:
        t.stop()


def test_fragmented_and_large_frames():

    class ShortStream(io.BytesIO):
        def read(self, n=-1):
            return super().read(min(n, 3))

        def write(self, b):
            return super().write(b[:5])

    stream = ShortStream()
    payload = b"\x00\r\n\x1a" * (1 << 19)
    write_frame(stream, payload)
    stream.seek(0)
    assert read_frame(stream) == payload
    assert read_frame(stream) is None
    assert read_frame(io.BytesIO(b"\x00\x00\x00\x00")) == b""


@pytest.mark.parametrize("data", [b"\x00", frame_header(5) + b"ab"])
def test_truncated_frame_never_delivered(data):
    with pytest.raises(EOFError):
        read_frame(io.BytesIO(data))


def test_frame_bound():
    with pytest.raises(ValueError):
        frame_header(MAX_FRAME_BYTES + 1)
    with pytest.raises(ValueError):
        read_frame(io.BytesIO(struct.pack("!I", 4294967295)))


def test_relay_forwards_exact_bytes_without_retries():
    events = []

    class Pipe:
        def __init__(self, **kw):
            self.kw = kw

        def _client_handle(self):
            events.append((self.path, self.kw))
            return 10

        def _write(self, handle, payload):
            events.append(payload)
            return len(payload)

        def _read(self, handle):
            return b'{"ok":true}'

        def stop(self):
            events.append("closed")

    payload = b'{"method":"cancel","params":{"id":"abc"}}'
    frames = iter([json.dumps(dict(pipe_path="\\\\.\\pipe\\test")).encode(), payload, None])
    out = io.BytesIO()
    relay(lambda: next(frames), out, Pipe)
    out.seek(0)
    assert read_frame(out) == b""
    assert read_frame(out) == b'{"ok":true}'
    assert events == [("\\\\.\\pipe\\test", {"connect_timeout_seconds": 5.0}), payload, "closed"]


def test_relay_write_error_is_not_retried():
    events = []

    class Pipe:
        def __init__(self, **kw):
            pass

        def _client_handle(self):
            return 10

        def _write(self, *a):
            events.append("write")
            raise OSError("broken")

        def stop(self):
            events.append("closed")

    frames = iter([b'{"pipe_path":"\\\\\\\\.\\\\pipe\\\\test"}', b"order"])
    with pytest.raises(OSError):
        relay(lambda: next(frames), io.BytesIO(), Pipe)
    assert events == ["write", "closed"]


def test_lazy_persistent_per_thread_and_wire_parity(make_transport):
    t = make_transport("fragment")
    assert t._processes == {}
    request = dict(method="order_stock", params={"remark": "测试" + "x" * (2 << 20)})
    first = t.send_request(request, 10)
    second = t.send_request({"method": "cancel"}, 5)
    assert first["echo"] == request
    assert first["pid"] == second["pid"]
    assert first["hello"]["pipe_path"] == "\\\\.\\pipe\\qmtairlock_test-account"
    assert "test-account" not in t.command


@pytest.mark.parametrize(
    "mode,exception",
    [
        ("stall", TransportTimeout),
        ("eof", TransportError),
        ("crash", TransportError),
        ("partial", TransportError),
        ("oversize", TransportError),
        ("bad_json", TransportError),
    ],
)
def test_completed_request_never_resent_and_next_call_rebuilds(make_transport, tmp_path, mode, exception):
    receipt = tmp_path / "received"
    t = make_transport(mode, receipt)
    with pytest.raises(exception):
        t.send_request({"method": "order_stock"}, 0.3)
    assert receipt.read_text().count("order_stock") == 1
    assert t._processes == {}
    t.command[-2] = "echo"
    assert t.send_request({"method": "ping"}, 2)["echo"]["method"] == "ping"
    assert receipt.read_text().count("order_stock") == 1


@pytest.mark.parametrize("mode", ["handshake_stall", "write_stall"])
def test_timeout_covers_handshake_and_blocked_stdin(make_transport, mode):
    t = make_transport(mode)
    started = time.monotonic()
    with pytest.raises(TransportTimeout):
        t.send_request({"blob": "x" * (4 << 20)}, 0.2)
    assert time.monotonic() - started < 2
    assert t._processes == {}


def test_partial_stdin_failure_retries_only_once(make_transport, tmp_path, monkeypatch):
    t = make_transport(receipt=tmp_path / "receipt")
    original = os.write
    writes = []
    broken = False

    def write(fd, data):
        nonlocal broken
        if b'"method"' in data.tobytes() and (not broken):
            broken = True
            n = original(fd, data[:9])
            writes.append(fd)
            return n
        if broken and len(writes) == 1:
            writes.append(fd)
            raise BrokenPipeError()
        return original(fd, data)

    monkeypatch.setattr(os, "write", write)
    assert t.send_request({"method": "order_stock"}, 3)["echo"]["method"] == "order_stock"
    assert (tmp_path / "receipt").read_text().count("order_stock") == 1
    assert len(writes) == 2


def test_two_stdin_failures_stop_after_one_retry(make_transport, monkeypatch):
    t = make_transport()
    original = os.write
    writes = []

    def write(fd, data):
        if b'"method"' in data.tobytes():
            writes.append(fd)
            raise BrokenPipeError()
        return original(fd, data)

    monkeypatch.setattr(os, "write", write)
    with pytest.raises(TransportError):
        t.send_request({"method": "cancel"}, 2)
    assert len(writes) == 2
    assert t._processes == {}


def test_threads_release_processes_and_do_not_share(make_transport):
    t = make_transport()
    barrier = threading.Barrier(7)
    pids, errors, processes = ([], [], [])

    def run():
        try:
            pids.append(t.send_request({"method": "ping"}, 3)["pid"])
            processes.append(t._local.relay.process)
            barrier.wait(timeout=5)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(6)]
    for thread in threads:
        thread.start()
    try:
        barrier.wait(timeout=5)
    except threading.BrokenBarrierError:
        pass
    finally:
        for thread in threads:
            thread.join(timeout=5)
    assert errors == []
    assert len(set(pids)) == 6
    assert t._processes == {}
    assert all((p.poll() is not None for p in processes))


def test_old_finalizer_does_not_close_new_connection(make_transport):
    t = make_transport()
    t.send_request({}, 2)
    old = t._local.finalizer
    t._drop()
    t.send_request({}, 2)
    current = t._local.relay
    old.__del__()
    assert current.process.poll() is None
    t.stop()
    assert current.process.poll() is not None


def test_stop_interrupts_pending_reads(make_transport, tmp_path):
    receipt = tmp_path / "receipt"
    t = make_transport("stall", receipt)
    errors = []

    def run():
        try:
            t.send_request({"method": "order_stock"}, 0)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 3
    while not receipt.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert receipt.exists()
    processes = [entry[0].process for entry in t._processes.values()]
    t.stop()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], TransportError)
    assert all((p.poll() is not None for p in processes))
    assert receipt.read_text().count("order_stock") == 1
    t.stop()


@pytest.mark.parametrize("command", ["python relay.py", [], [1], [""], ["bad\x00arg"]])
def test_argv_validation(command):
    with pytest.raises(ValueError):
        PipeRelayTransport(command)


def test_module_entry_does_not_open_files_or_sockets():
    script = '\nimport builtins, io, os, socket, runpy\nforbidden = []\ndef deny(*args, **kwargs):\n    forbidden.append("IO")\n    raise AssertionError("forbidden")\nfor module, names in ((builtins, ("open",)), (io, ("open",)),\n    (os, ("open", "makedirs", "mkdir", "replace", "remove")),\n    (socket, ("socket", "create_connection"))):\n    for name in names: setattr(module, name, deny)\n# Windows 的 main 会等待 stdin；这里仅加载真实 -m 的父包和模块闭包。\nrunpy.run_module("qmtairlock.transports.pipe_relay", run_name="relay_import_test")\nassert not forbidden, forbidden\n'
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


def test_sweep_does_not_reap_a_thread_registered_after_its_snapshot(make_transport, monkeypatch):
    t = make_transport()
    original = threading.enumerate
    owner = threading.current_thread().ident
    ready, release = (threading.Event(), threading.Event())
    pids, errors = ([], [])

    def use():
        try:
            pids.append(t.send_request({}, 2)["pid"])
            ready.set()
            release.wait(timeout=3)
            pids.append(t.send_request({}, 2)["pid"])
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=use)

    def snapshot():
        live = original()
        if threading.current_thread().ident == owner:
            worker.start()
            ready.wait(timeout=0.2)
        return live

    monkeypatch.setattr(threading, "enumerate", snapshot)
    t._sweep()
    assert ready.wait(timeout=3)
    release.set()
    worker.join(timeout=3)
    assert not worker.is_alive() and errors == []
    assert len(pids) == 2 and pids[0] == pids[1]


@pytest.mark.parametrize("error", [2, 231])
def test_relay_native_connector_retries_only_startup_errors(error, monkeypatch):
    import ctypes
    from types import SimpleNamespace

    from qmtairlock.transports.pipe_transport import INVALID_HANDLE_VALUE, NamedPipeTransport

    transport = NamedPipeTransport(connect_timeout_seconds=1)
    dll = mock.Mock()
    dll.CreateFileW.side_effect = [INVALID_HANDLE_VALUE, INVALID_HANDLE_VALUE, 42]
    transport._dll = lambda: dll
    transport._wintypes = SimpleNamespace(DWORD=ctypes.c_uint32)
    transport._last_error = lambda: error
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda duration: sleeps.append(duration))
    try:
        assert transport._client_handle() == 42
        assert len(sleeps) == 2
    finally:
        transport.stop()


def test_relay_native_connector_respects_connect_deadline():
    from qmtairlock.transports.pipe_transport import INVALID_HANDLE_VALUE, NamedPipeTransport

    transport = NamedPipeTransport(connect_timeout_seconds=0.01)
    dll = mock.Mock()
    dll.CreateFileW.return_value = INVALID_HANDLE_VALUE
    transport._dll = lambda: dll
    transport._last_error = lambda: 231
    started = time.monotonic()
    with pytest.raises(TransportError):
        transport._client_handle()
    assert time.monotonic() - started < 0.5
    assert transport._client_threads == {}


def test_missing_relay_command_is_a_transport_error():
    t = PipeRelayTransport(["/nonexistent-bigqmt-relay-python"])
    with pytest.raises(TransportError):
        t.send_request({"method": "order_stock"}, 1)
    assert t._processes == {}
    t.stop()


def test_module_pipe_failure_exits_with_stdin_still_open():
    script = '\nimport os,sys,types,runpy\nfrom qmtairlock.transports.pipe_transport import NamedPipeTransport\nNamedPipeTransport._client_handle = lambda self: 42\nNamedPipeTransport._write = lambda self,h,payload: len(payload)\ndef broken(*args): raise OSError("pipe closed")\nNamedPipeTransport._read = broken\nNamedPipeTransport.stop = lambda self: None\nsys.modules["msvcrt"] = types.SimpleNamespace(setmode=lambda *args: None)\nos.name = "nt"\nos.O_BINARY = 0\nrunpy.run_module("qmtairlock.transports.pipe_relay",run_name="__main__")\n'
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        write_frame(process.stdin, json.dumps(dict(pipe_path="\\\\.\\pipe\\test")).encode())
        write_frame(process.stdin, b'{"method":"cancel"}')
        assert process.wait(timeout=5) == 1
        assert process.stdout.read() == frame_header(0)
        assert len(process.stderr.read().splitlines()) == 1
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


@pytest.mark.parametrize("mode", ["mismatch", "missing_id"])
def test_response_id_mismatch_drops_relay_without_resend(make_transport, tmp_path, mode):
    receipt = tmp_path / "requests"
    transport = make_transport(mode, receipt)
    request = dict(request_id="our-order", method="order_stock", params={})
    with pytest.raises(TransportError, match="request_id mismatch"):
        transport.send_request(request, timeout_seconds=2)
    assert [json.loads(line) for line in receipt.read_text().splitlines()] == [request]
    assert not transport._processes
    transport.command[-2] = "echo"
    following = dict(request_id="next-query", method="query_stock_orders", params={})
    assert transport.send_request(following, timeout_seconds=2)["request_id"] == "next-query"
    assert [json.loads(line) for line in receipt.read_text().splitlines()] == [request, following]
