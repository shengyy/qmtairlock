"""Single-send RPC client over native named pipes or the WSL stdio relay."""

import threading
import uuid

from .config import client_config, positive_seconds
from .data_frames import _restore_jsonable
from .rpc_codec import TYPED_PAYLOAD_FLAG
from .transports.base import TransportError
from .transports.factory import build_transport


class RpcServerRepliedError(RuntimeError):
    """An explicit server error; write outcome may still be unknown."""


class BigQmtRpcClient:
    def __init__(self, account_id, config=None, timeout_seconds=6):
        self.account_id = str(account_id or "").strip()
        if not self.account_id:
            raise ValueError("account_id is required")
        self.timeout_seconds = positive_seconds(timeout_seconds)
        self.pipe_config, self.local_cache_config = client_config(config)
        self.transport_name = "pipe"
        self._transport_instance = None
        self._transport_lock = threading.RLock()
        self._closed = False

    def _transport(self):
        with self._transport_lock:
            if self._closed:
                raise RuntimeError("RPC client is closed")
            if self._transport_instance is None:
                self._transport_instance = build_transport(self.pipe_config, self.account_id)
            return self._transport_instance

    def close(self):
        with self._transport_lock:
            self._closed = True
            instance, self._transport_instance = self._transport_instance, None
        if instance is not None:
            instance.stop()

    def call(self, method, params=None, account_id=None, timeout_seconds=None, request_id=None):
        account = str(account_id or self.account_id)
        if account != self.account_id:
            raise ValueError("client is bound to another account")
        timeout = positive_seconds(self.timeout_seconds if timeout_seconds is None else timeout_seconds)
        request = {
            "schema_version": 1,
            "request_id": str(request_id or uuid.uuid4().hex),
            "account_id": account,
            "method": str(method),
            "params": dict(params or {}),
            "timeout_seconds": timeout,
        }
        response = self._transport().send_request(request, timeout)
        if not isinstance(response, dict) or response.get("request_id") != request["request_id"]:
            raise TransportError("RPC response request_id mismatch; outcome unknown")
        if response.get("account_id") != account:
            raise TransportError("RPC response account mismatch; outcome unknown")
        if response.get("ok") is not True:
            raise RpcServerRepliedError(response.get("error") or "RPC failed")
        if response.get("server_error"):
            raise RpcServerRepliedError(response["server_error"])
        if response.get(TYPED_PAYLOAD_FLAG) is False:
            return response.get("data")
        return _restore_jsonable(response.get("data"))

    def call_tracked(self, method, params=None, **kwargs):
        request_id = uuid.uuid4().hex
        try:
            return request_id, self.call(method, params, request_id=request_id, **kwargs)
        except Exception as exc:
            exc.request_id = request_id
            raise
