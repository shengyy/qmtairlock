"""Native message boundaries and Windows error outcomes through the shared owner."""

import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from qmtairlock.transports.base import TransportError
from qmtairlock.transports.pipe_native import (
    ERROR_BROKEN_PIPE,
    ERROR_MORE_DATA,
    ERROR_OPERATION_ABORTED,
    NativePipeIO,
)


@pytest.fixture
def wire():
    native = NativePipeIO()
    native._k32 = SimpleNamespace(ReadFile=Mock(return_value=0), WriteFile=Mock(return_value=0))
    native._wintypes = SimpleNamespace(DWORD=ctypes.c_uint32)
    return native


@pytest.mark.parametrize("error", [ERROR_BROKEN_PIPE, 5])
def test_native_read_reports_closed_and_other_failures(wire, monkeypatch, error):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    with pytest.raises(TransportError, match="err=%s" % error):
        wire.read(77)


def test_native_cancel_is_a_wakeup(wire, monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: ERROR_OPERATION_ABORTED, raising=False)
    assert wire.read(77) == b""


def test_native_write_failure_preserves_error_without_resending(wire, monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: ERROR_BROKEN_PIPE, raising=False)
    with pytest.raises(TransportError, match="WriteFile failed.*109"):
        wire.write(77, b"one request")
    assert wire._k32.WriteFile.call_count == 1


def test_native_read_assembles_more_data_into_one_message(wire, monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: ERROR_MORE_DATA, raising=False)
    chunks = iter([(b"first", 0), (b"second", 1)])

    def read(handle, buffer, size, count, overlapped):
        payload, complete = next(chunks)
        ctypes.memmove(buffer, payload, len(payload))
        ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32))[0] = len(payload)
        return complete

    wire._k32.ReadFile.side_effect = read
    assert wire.read(77) == b"firstsecond"
    assert wire._k32.ReadFile.call_count == 2
