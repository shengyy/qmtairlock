import sys
import time

import pandas as pd

from qmtairlock.adapters.market_bars import _frame_axis_rows
from qmtairlock.adapters.market_frames import _frame_rows
from qmtairlock.rpc_dispatch import BigQmtRpcHandlers


def _native_daily_frame():
    # Native bar frames are indexed by time strings; pandas 3 gives them the str dtype.
    index = pd.Index(["20261120", "20261123"], dtype="str")
    return pd.DataFrame({"close": [10.0, 10.5], "preClose": [9.9, 10.0], "stime": list(index)}, index=index)


def test_frame_rows_reads_label_indexed_native_frames_by_position():
    rows = _frame_rows(_native_daily_frame())
    assert [row["close"] for row in rows] == [10.0, 10.5]
    assert [row["stime"] for row in rows] == ["20261120", "20261123"]


def test_frame_rows_reads_a_mapping_of_series_by_position():
    frame = _native_daily_frame()
    rows = _frame_rows({"close": frame["close"], "stime": frame["stime"]})
    assert rows == [{"close": 10.0, "stime": "20261120"}, {"close": 10.5, "stime": "20261123"}]


def test_frame_axis_rows_keep_labels_and_values():
    pairs = _frame_axis_rows(_native_daily_frame())
    assert [label for label, _row in pairs] == ["20261120", "20261123"]
    assert pairs[1][1]["preClose"] == 10.0


def test_ping_reports_the_host_interpreter_and_loaded_libraries():
    reply = BigQmtRpcHandlers("TEST").ping({})
    assert abs(reply["server_time"] - time.time()) < 5
    host = reply["host"]
    assert host["python"] == "%d.%d.%d" % sys.version_info[:3]
    assert host["pandas"] == pd.__version__
    assert host["numpy"] == sys.modules["numpy"].__version__


def _bars_with(context):
    from qmtairlock.adapters.market_bars import MarketBars
    from qmtairlock.adapters.market_context import MarketContext

    return MarketBars(MarketContext(context, {}))


def test_market_reads_never_subscribe_unless_asked():
    from types import SimpleNamespace

    seen = []

    def get_market_data_ex(**kwargs):
        seen.append(kwargs.get("subscribe"))
        return {"600000.SH": _native_daily_frame()}

    bars = _bars_with(SimpleNamespace(get_market_data_ex=get_market_data_ex))
    bars.get_market_data_ex(field_list=["close"], stock_list=["600000.SH"], period="1d")
    bars.get_market_data_ex(field_list=["close"], stock_list=["600000.SH"], period="1d", subscribe=True)
    assert seen == [False, True]


def test_multi_level_frame_columns_fail_instead_of_becoming_tuple_strings():
    import pytest

    from qmtairlock.rpc_codec import to_jsonable

    columns = pd.MultiIndex.from_tuples([("600000.SH", "close"), ("000001.SZ", "close")])
    with pytest.raises(ValueError, match="multi-level"):
        to_jsonable(pd.DataFrame([[1.0, 2.0]], columns=columns))
