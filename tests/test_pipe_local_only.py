"""三个服务端 CreateNamedPipeW 调用都必须限制在同机，能力探测也不例外。"""

from types import SimpleNamespace
from unittest import mock

from qmtairlock.transports.pipe_transport import INVALID_HANDLE_VALUE, PIPE_REJECT_REMOTE_CLIENTS, NamedPipeTransport


def test_rpc_pipe_rejects_remote_clients():
    server = NamedPipeTransport(account_id="test")
    server._running = True

    def create(*args):
        assert args[2] & PIPE_REJECT_REMOTE_CLIENTS
        server._running = False
        return INVALID_HANDLE_VALUE

    dll = SimpleNamespace(CreateNamedPipeW=mock.Mock(side_effect=create))
    server._dll = lambda: dll
    server._accept_loop()
    dll.CreateNamedPipeW.assert_called_once()
