from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from qmtairlock.data_client import BigQmtXtData
from qmtairlock.local_cache import CacheFileInvalid, LocalMarketCache


@pytest.mark.parametrize("indexed", [True, False])
def test_narrow_query_keeps_unrequested_cached_fields(tmp_path, indexed):
    data = BigQmtXtData(
        SimpleNamespace(local_cache_config={"enabled": True, "dir": str(tmp_path), "format": "parquet"})
    )
    stamp = "20260930150000"
    frame = pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [100.0], "amount": [1050.0]},
        index=[stamp],
    )
    if not indexed:
        frame = frame.rename_axis("stime").reset_index()
    responses = [frame, frame[["close"]] if indexed else frame[["stime", "close"]]]
    data.client.call = lambda *args, **kwargs: {"X": responses.pop(0)}
    for fields in ([], ["close"]):
        data.get_market_data_ex(field_list=fields, stock_list=["X"], period="5m", subscribe=False)
    out = data._local_cache().read("X", "5m")
    assert out.iloc[0]["open"] == 10.0
    assert out.iloc[0]["volume"] == 100.0


def test_partial_update_preserves_only_omitted_columns(tmp_path):
    cache = LocalMarketCache(str(tmp_path), fmt="parquet")
    full = {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [100.0], "amount": [1050.0]}
    cache.write("X", "5m", pd.DataFrame(full, index=["20260930150000"]))
    cache.write("X", "5m", pd.DataFrame({"close": [10.6], "volume": [float("nan")]}, index=["20260930150000"]))
    out = cache.read("X", "5m").iloc[0]
    assert out["open"] == 10.0
    assert out["close"] == 10.6
    assert pd.isna(out["volume"])


STAMPS = ["20261120093100", "20261120093200"]


def _bars(**overrides):
    columns = {"open": [10.0, 10.1], "high": [10.2, 10.3], "low": [9.9, 10.0], "close": [10.1, 10.2]}
    columns.update(volume=[100.0, 0.0], amount=[1010.0, 0.0])
    columns.update(overrides)
    return pd.DataFrame(columns, index=STAMPS)


def test_invalid_rows_are_rejected_before_the_merge_and_counted(tmp_path):
    cache = LocalMarketCache(str(tmp_path))
    assert cache.write("X", "1m", _bars(close=[0.0, 10.2], high=[10.2, 9.0])) == 0
    assert cache.rejected_rows == {"invalid close": 1, "high/low outside open/close": 2}
    assert cache.read("X", "1m") is None
    assert cache.write("X", "1m", _bars()) == 2  # an untraded minute with zero volume is a real bar
    assert list(cache.read("X", "1m").index) == STAMPS


def test_a_new_file_without_core_bar_columns_is_never_written(tmp_path):
    cache = LocalMarketCache(str(tmp_path))
    assert cache.write("X", "1m", _bars().drop(columns=["amount"])) == 0
    assert cache.rejected_rows == {"missing columns": 2}
    assert cache.read("X", "1m") is None


def test_an_invalid_file_is_reported_with_its_path_and_left_in_place(tmp_path):
    cache = LocalMarketCache(str(tmp_path))
    path = cache.path("X", "1m")
    Path(path).parent.mkdir(parents=True)
    _bars().drop(columns=["amount"]).to_parquet(path)
    with pytest.raises(CacheFileInvalid, match="missing columns amount") as failed:
        cache.read("X", "1m")
    assert path in str(failed.value)
    _bars(low=[10.5, 10.0]).to_parquet(path)
    with pytest.raises(CacheFileInvalid, match="high/low outside open/close: 1"):
        cache.read("X", "1m")
    Path(path).write_bytes(b"not parquet")
    with pytest.raises(CacheFileInvalid, match="unreadable"):
        cache.read("X", "1m")
    assert Path(path).exists()


def test_requested_fields_missing_from_the_cache_are_an_error(tmp_path):
    data = BigQmtXtData(
        SimpleNamespace(local_cache_config={"enabled": True, "dir": str(tmp_path), "format": "parquet"})
    )
    data._local_cache().write("X", "1m", _bars())
    with pytest.raises(CacheFileInvalid, match="missing column\\(s\\) preClose"):
        data.get_local_data(field_list=["close", "preClose"], stock_list=["X"], period="1m")


def test_a_merge_never_builds_on_an_invalid_file(tmp_path):
    cache = LocalMarketCache(str(tmp_path))
    path = cache.path("X", "1m")
    Path(path).parent.mkdir(parents=True)
    _bars().drop(columns=["amount"]).to_parquet(path)
    before = Path(path).read_bytes()
    with pytest.raises(CacheFileInvalid, match="missing columns amount"):
        cache.write("X", "1m", _bars())
    assert Path(path).read_bytes() == before


def test_audit_lists_invalid_files_without_touching_them(tmp_path):
    cache = LocalMarketCache(str(tmp_path))
    cache.write("GOOD", "1m", _bars())
    bad = cache.path("BAD", "1m")
    _bars().drop(columns=["amount"]).to_parquet(bad)
    assert cache.audit() == [(bad, "missing columns amount")]
    assert Path(bad).exists()
