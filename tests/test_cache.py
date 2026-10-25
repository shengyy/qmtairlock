from types import SimpleNamespace

import pandas as pd
import pytest

from qmtairlock.data_client import BigQmtXtData
from qmtairlock.local_cache import LocalMarketCache


@pytest.mark.parametrize("indexed", [True, False])
def test_narrow_query_keeps_unrequested_cached_fields(tmp_path, indexed):
    data = BigQmtXtData(
        SimpleNamespace(local_cache_config={"enabled": True, "dir": str(tmp_path), "format": "parquet"})
    )
    stamp = "20260930150000"
    frame = pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [100.0]}, index=[stamp]
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
    cache.write("X", "5m", pd.DataFrame({"open": [10.0], "close": [10.5], "volume": [100.0]}, index=["20260930150000"]))
    cache.write("X", "5m", pd.DataFrame({"close": [10.6], "volume": [float("nan")]}, index=["20260930150000"]))
    out = cache.read("X", "5m").iloc[0]
    assert out["open"] == 10.0
    assert out["close"] == 10.6
    assert pd.isna(out["volume"])
