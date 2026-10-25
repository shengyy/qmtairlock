from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from qmtairlock.qmt_injected import capture_qmt_injected_funcs
from qmtairlock.rpc_dispatch import BigQmtRpcHandlers
from qmtairlock.rpc_market_handlers import MarketHandlers

CODES = ["600000.SH", "000001.SZ"]
DATES = ("5m", "20261023000000", "20261023235959")


def rpc(native=None, context=None):
    api = capture_qmt_injected_funcs(native or {})
    return BigQmtRpcHandlers("TEST", market_data=MarketHandlers(context or SimpleNamespace(), api))


def request(owner, method="download_history_data2", **extra):
    codes = {"stock_code": CODES[0]} if method == "download_history_data" else {"stock_list": CODES}
    return owner.handle(method, dict(codes, period=DATES[0], start_time=DATES[1], end_time=DATES[2], **extra))


@pytest.mark.parametrize("native_name", ["download_history_data", "down_history_data"])
@pytest.mark.parametrize("method", ["download_history_data", "download_history_data2"])
def test_single_native_globals_accept_none_and_supply_four_arguments(native_name, method):
    native = Mock(return_value=None)
    assert request(rpc({native_name: native}), method, incrementally=True) is True
    codes = CODES[:1] if method == "download_history_data" else CODES
    assert native.call_args_list == [call(code, *DATES) for code in codes]


def test_native_batch_uses_callback_before_four_argument_shape():
    calls = []

    def batch(codes, period, start, end, callback=None):
        calls.append((codes, period, start, end, callback))
        callback({"finished": len(codes)})

    single = Mock(side_effect=AssertionError("batch owner must take precedence"))
    assert request(rpc({"download_history_data2": batch, "download_history_data": single})) is True
    assert len(calls) == 1 and calls[0][:4] == (CODES, *DATES)
    assert callable(calls[0][4])
    single.assert_not_called()


def test_native_batch_supports_four_argument_terminal():
    calls = []

    def batch(codes, period, start, end):
        calls.append((codes, period, start, end))
        return True

    assert request(rpc({"download_history_data2": batch})) is True
    assert calls == [(CODES, *DATES)]


@pytest.mark.parametrize("method", ["download_history_data", "download_history_data2"])
@pytest.mark.parametrize("result", [False, 0, ""])
def test_native_rejection_is_an_rpc_error(method, result):
    native = Mock(return_value=result)
    with pytest.raises(RuntimeError, match="rejected"):
        request(rpc({method: native}), method)
    native.assert_called_once()


@pytest.mark.parametrize("native_name", ["download_history_data", "down_history_data"])
@pytest.mark.parametrize("first_result", [False, OSError("native disk unavailable")])
def test_first_stock_failure_cannot_be_hidden_by_later_success(native_name, first_result):
    native = Mock(side_effect=[first_result, None])
    with pytest.raises(RuntimeError, match=CODES[0]) as failed:
        request(rpc({native_name: native}))
    assert native.call_args_list == [call(code, *DATES) for code in CODES]
    if isinstance(first_result, Exception):
        assert failed.value.__cause__ is first_result


@pytest.mark.parametrize("method", ["download_history_data", "download_history_data2"])
def test_native_exceptions_propagate_without_trying_another_channel(method):
    error = OSError("native disk unavailable")
    native = Mock(side_effect=error)
    alternate = Mock(side_effect=AssertionError("failed calls must not switch native owner"))
    context = SimpleNamespace(**{method: alternate})
    with pytest.raises(OSError) as failed:
        request(rpc({method: native, "down_history_data": alternate}, context), method)
    assert failed.value is error
    native.assert_called_once()
    alternate.assert_not_called()


@pytest.mark.parametrize("method", ["download_history_data", "download_history_data2"])
@pytest.mark.parametrize("result", [None, True, False, OSError("context unavailable")])
def test_context_download_keeps_keyword_shape_and_checks_native_outcome(method, result):
    native = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
    owner = rpc(context=SimpleNamespace(**{method: native}))
    if result is False:
        with pytest.raises(RuntimeError, match="rejected"):
            request(owner, method, incrementally=False)
    elif isinstance(result, Exception):
        with pytest.raises(OSError) as failed:
            request(owner, method, incrementally=False)
        assert failed.value is result
    else:
        assert request(owner, method, incrementally=False) is True
    key = "stock_code" if method == "download_history_data" else "stock_list"
    value = CODES[0] if method == "download_history_data" else CODES
    native.assert_called_once_with(
        **{key: value, "period": DATES[0], "start_time": DATES[1], "end_time": DATES[2], "incrementally": False}
    )


@pytest.mark.parametrize("method", ["download_history_data", "download_history_data2"])
def test_missing_download_channel_is_an_error(method):
    with pytest.raises(RuntimeError, match="no download channel"):
        request(rpc(), method)
