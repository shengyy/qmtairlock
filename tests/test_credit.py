from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from qmtairlock.account_scope import AccountBinding
from qmtairlock.credit_client import CreditClient
from qmtairlock.rpc_credit import CreditHandlers
from qmtairlock.rpc_native import NativeQueries


def test_counter_query_rate_freshness_and_out_of_order_callbacks(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("qmtairlock.rpc_credit.time.time", lambda: clock[0])
    native = Mock()
    credit = CreditHandlers(
        NativeQueries(AccountBinding("TEST", ["CREDIT"]), object(), {"query_credit_account": native})
    )
    first = credit._handle_query_credit_account({})
    assert first["query_issued"] and first["rows"] == []
    seq1 = native.call_args.args[1]
    assert credit.note_credit_account(seq1, SimpleNamespace(balance=100))
    clock[0] += 29
    assert credit._handle_query_credit_account({})["query_issued"] is False
    assert native.call_count == 1
    clock[0] += 1
    assert credit._handle_query_credit_account({})["query_issued"]
    seq2 = native.call_args.args[1]
    assert seq2 != seq1
    assert credit.note_credit_account(seq1, SimpleNamespace(balance=1)) is False
    assert credit.note_credit_account(seq2, SimpleNamespace(balance=200))
    clock[0] += 121
    answer = credit._handle_query_credit_account({})
    assert answer["dropped_stale"] and answer["rows"] == []


@pytest.mark.parametrize("age", [0, -1, 121, float("inf"), float("nan")])
def test_caller_cannot_disable_credit_stale_protection(age):
    credit = CreditHandlers(NativeQueries(AccountBinding("TEST", ["CREDIT"]), object(), {}))
    with pytest.raises(ValueError):
        credit._handle_query_credit_account({"max_age_seconds": age})


def test_credit_client_keeps_query_errors():
    client = SimpleNamespace(account_id="TEST", call=Mock(side_effect=RuntimeError("counter unavailable")))
    with pytest.raises(RuntimeError, match="unavailable"):
        CreditClient(client).query_credit_detail("TEST")
