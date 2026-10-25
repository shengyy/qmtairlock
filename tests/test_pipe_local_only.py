"""The server listener accepts only same-host clients."""

from types import SimpleNamespace
from unittest import mock

from qmtairlock.transports.pipe_native import INVALID_HANDLE_VALUE, PIPE_REJECT_REMOTE_CLIENTS
from qmtairlock.transports.pipe_server import NamedPipeServer


def test_rpc_pipe_rejects_remote_clients():
    server = NamedPipeServer(account_id="test")
    server._running = True

    def create(*args):
        assert args[2] & PIPE_REJECT_REMOTE_CLIENTS
        server._running = False
        return INVALID_HANDLE_VALUE

    dll = SimpleNamespace(CreateNamedPipeW=mock.Mock(side_effect=create))
    server._wire.dll = lambda: dll
    server._accept_loop()
    dll.CreateNamedPipeW.assert_called_once()
