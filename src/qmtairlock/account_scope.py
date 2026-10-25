"""Request-scoped account types, configured in memory by the strategy host."""

import threading
import time
from contextlib import contextmanager

ACCOUNT_TYPE_CODES = {
    "FUTURE": 1,
    "STOCK": 2,
    "CREDIT": 3,
    "FUTURE_OPTION": 5,
    "STOCK_OPTION": 6,
    "HUGANGTONG": 7,
    "NEW3BOARD": 10,
    "SHENGANGTONG": 11,
}
_REQUEST = threading.local()


@contextmanager
def dispatch_deadline(deadline):
    previous = getattr(_REQUEST, "deadline", None)
    _REQUEST.deadline = deadline
    try:
        yield
    finally:
        _REQUEST.deadline = previous


def ensure_dispatch_timely():
    deadline = getattr(_REQUEST, "deadline", None)
    if deadline is not None and time.time() >= deadline:
        raise TimeoutError("RequestExpired: not dispatched")


def account_type_name(value):
    if value is None or value == "":
        return ""
    if isinstance(value, int) or str(value).isdigit():
        value = next((name for name, code in ACCOUNT_TYPE_CODES.items() if code == int(value)), "")
    name = str(value).upper()
    if name == "SECURITY":
        name = "STOCK"
    if name not in ACCOUNT_TYPE_CODES:
        raise ValueError("unsupported account type")
    return name


def account_type_for(account_id, default_type="STOCK"):
    return getattr(_REQUEST, "account_type", None) or account_type_name(default_type)


@contextmanager
def request_account_type(value):
    previous = getattr(_REQUEST, "account_type", None)
    _REQUEST.account_type = account_type_name(value) if value is not None else None
    try:
        yield
    finally:
        _REQUEST.account_type = previous


class AccountBinding:
    def __init__(self, account_id, account_types=("STOCK",)):
        self.account_id = str(account_id or "").strip()
        if not self.account_id:
            raise ValueError("account_id is required")
        if isinstance(account_types, str):
            account_types = [account_types]
        self.account_types = tuple(account_type_name(value) for value in account_types)
        if not self.account_types or not all(self.account_types):
            raise ValueError("account_types must be nonempty")

    def validate(self, params, envelope_account=None):
        if envelope_account is not None and str(envelope_account) != self.account_id:
            raise ValueError("RPC account does not match the bound account")
        account = params.get("account_id") or params.get("account") or self.account_id
        if isinstance(account, dict):
            account = account.get("account_id") or account.get("accountID") or account.get("id")
        if str(account) != self.account_id:
            raise ValueError("request account does not match the bound account")
        requested = account_type_name(params.get("account_type")) or self.account_types[0]
        if requested not in self.account_types:
            raise ValueError("account type is not enabled for the bound account")
        return requested

    def account_id_for(self, params):
        self.validate(params)
        return self.account_id
