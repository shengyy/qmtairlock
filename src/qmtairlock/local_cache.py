"""Client-only Parquet cache: atomic, locked merges preserve omitted columns."""

import os
from contextlib import contextmanager

_TIME_COLS = ("stime", "time", "index", "date", "datetime", "timetag")


def _time_col(df):
    cols = list(getattr(df, "columns", []))
    for name in _TIME_COLS:
        if name in cols:
            return name
    return None


def _time_axis(df):
    """Return (name, use_index): where the time axis lives, or (None, False)."""
    index = getattr(df, "index", None)
    try:
        if index is not None and len(index):
            digits = "".join((ch for ch in str(index[0]) if ch.isdigit()))
            if 8 <= len(digits) <= 14:
                return ("__index__", True)
    except Exception:
        pass
    name = _time_col(df)
    if name:
        return (name, False)
    return (None, False)


def _pad_end(value):
    text = str(value)
    return text + "9" * (14 - len(text)) if 0 < len(text) < 14 else text


def _align_start(value, sample):
    """Align a timestamp lower bound to an eight-digit daily cache axis."""
    text = str(value)
    sample_text = str(sample)
    if sample_text.isdigit() and len(sample_text) == 8 and text.isdigit() and (len(text) > 8):
        return text[:8]
    return text


def _drop_placeholder_rows(df):
    """Big QMT fills dates it has no local data for with all-zero rows. A real bar"""
    for col in ("close", "open", "price", "lastPrice"):
        if col in getattr(df, "columns", []):
            try:
                return df[df[col] != 0]
            except Exception:
                return df
    return df


@contextmanager
def _write_lock(path):
    """Serialize read/merge/replace for one logical key across client processes."""
    with open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if handle.tell() == 0:
                handle.write(b"\x00")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _preserve_omitted_columns(old, incoming):
    """A partial query updates supplied columns, including explicit nulls."""
    old_axis, old_index = _time_axis(old)
    new_axis, new_index = _time_axis(incoming)
    missing = [column for column in old.columns if column not in incoming.columns]
    if not missing:
        return incoming
    result = incoming.copy()
    if old_index and new_index:
        previous = old[~old.index.duplicated(keep="last")]
        for column in missing:
            result[column] = previous[column].reindex(incoming.index)
    elif old_axis and new_axis and (not old_index) and (not new_index):
        previous = old.drop_duplicates(subset=[old_axis], keep="last").set_index(old_axis)
        for column in missing:
            if column != old_axis:
                result[column] = incoming[new_axis].map(previous[column])
    return result


class LocalMarketCache:
    def __init__(self, cache_dir, fmt="parquet"):
        if not cache_dir or fmt != "parquet":
            raise ValueError("cache_dir and Parquet format are required")
        self.cache_dir = str(cache_dir)
        self.fmt = "parquet"

    def _existing_path(self, code, period, dividend_type):
        path = self.path(code, period, dividend_type)
        return path if os.path.isfile(path) else None

    @staticmethod
    def _read_file(path):
        import pandas as pd

        return pd.read_parquet(path)

    def _write_file(self, df, path):
        _, on_index = _time_axis(df)
        df.to_parquet(path, index=on_index)

    def _ext(self):
        return ".parquet"

    def path(self, code, period, dividend_type="none"):
        parts = [str(code or ""), str(period or "1d"), str(dividend_type or "none")]
        if any(
            not part or part in (".", "..") or "/" in part or "\\" in part or ":" in part or "\x00" in part
            for part in parts
        ):
            raise ValueError("invalid cache key")
        safe_code, period, div = parts
        return os.path.join(self.cache_dir, period, div, safe_code + self._ext())

    def write(self, code, period, df, dividend_type="none"):
        """Merge ``df`` into the cache for (code, period, dividend_type)."""
        if df is None or not hasattr(df, "shape") or df.shape[0] == 0:
            return 0
        incoming = _drop_placeholder_rows(df.copy())
        primary = self.path(code, period, dividend_type)
        directory = os.path.dirname(primary)
        if directory and (not os.path.isdir(directory)):
            os.makedirs(directory, exist_ok=True)
        with _write_lock(primary[: -len(self._ext())] + ".lock"):
            return self._merge(code, period, dividend_type, incoming, primary)

    def _merge(self, code, period, dividend_type, incoming, primary):
        import pandas as pd

        existing = self._existing_path(code, period, dividend_type)
        if incoming.shape[0] == 0:
            if existing:
                return self._read_file(existing).shape[0]
            return 0
        merged = incoming
        _, incoming_on_index = _time_axis(incoming)
        if existing:
            old = self._read_file(existing)
            _, old_on_index = _time_axis(old)
            merged = _preserve_omitted_columns(old, incoming)
            if incoming_on_index and old_on_index:
                merged = pd.concat([old, merged])
            elif incoming_on_index and (not old_on_index):
                merged = incoming
            else:
                merged = pd.concat([old, merged], ignore_index=True)
        axis, on_index = _time_axis(merged)
        if on_index:
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        elif axis:
            merged = merged.drop_duplicates(subset=[axis], keep="last").sort_values(axis).reset_index(drop=True)
        else:
            merged = merged.drop_duplicates().reset_index(drop=True)
        tmp = primary + ".tmp"
        try:
            self._write_file(merged, tmp)
            os.replace(tmp, primary)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        if existing and existing != primary:
            try:
                os.remove(existing)
            except Exception:
                pass
        return merged.shape[0]

    def read(self, code, period, start_time="", end_time="", count=-1, dividend_type="none"):
        """Return the cached DataFrame for (code, period, dividend_type), filtered."""
        existing = self._existing_path(code, period, dividend_type)
        if not existing:
            return None
        try:
            df = self._read_file(existing)
        except Exception:
            return None
        axis, on_index = _time_axis(df)
        if axis:
            if start_time:
                series = df.index.astype(str) if on_index else df[axis].astype(str)
                start_bound = _align_start(start_time, next(iter(series))) if len(series) else str(start_time)
                df = df[series >= start_bound]
            if end_time:
                series = df.index.astype(str) if on_index else df[axis].astype(str)
                df = df[series <= _pad_end(end_time)]
            df = df.sort_index() if on_index else df.sort_values(axis).reset_index(drop=True)
        try:
            n = int(count)
        except (TypeError, ValueError):
            n = -1
        if n > 0 and df.shape[0] > n:
            df = df.tail(n) if _time_axis(df)[1] else df.tail(n).reset_index(drop=True)
        return df

    def covered(self, code, period, dividend_type="none"):
        """Return (first_time, last_time, rows) for the cache, or None if empty."""
        df = self.read(code, period, dividend_type=dividend_type)
        if df is None or df.shape[0] == 0:
            return None
        axis, on_index = _time_axis(df)
        if not axis:
            return (None, None, df.shape[0])
        series = list(df.index.astype(str)) if on_index else list(df[axis].astype(str))
        return (series[0], series[-1], df.shape[0])

    def stats(self):
        """Return (files, periods) currently cached across all dividend types."""
        files = 0
        periods = set()
        if os.path.isdir(self.cache_dir):
            for root, _dirs, fnames in os.walk(self.cache_dir):
                cached = [f for f in fnames if f.endswith(".parquet")]
                if cached:
                    files += len(cached)
                    rel = os.path.relpath(root, self.cache_dir)
                    periods.add(rel.split(os.sep)[0] if rel != "." else rel)
        return (files, sorted(periods))
