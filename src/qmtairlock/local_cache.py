"""Client-only Parquet cache: validated rows, atomic locked merges that preserve omitted columns."""

import os
from contextlib import contextmanager

from .logging_setup import get_logger

log = get_logger("local_cache")

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


_PRICE_COLS = ("open", "high", "low", "close", "price", "lastPrice")
_SIZE_COLS = ("volume", "amount")
BAR_COLUMNS = ("open", "high", "low", "close", "volume", "amount")


def _is_bar_period(period):
    text = str(period or "")
    return not (text.startswith("tick") or text.startswith("l2"))


def _missing_bar_columns(df, period):
    """Core bar columns a bar-period file lacks; a file without them cannot serve a bar."""
    if not _is_bar_period(period):
        return []
    return [name for name in BAR_COLUMNS if name not in df.columns]


class CacheFileInvalid(ValueError):
    """A cached file that fails the bar checks; the file is reported, never deleted."""


def _row_problems(df):
    """``{reason: boolean row mask}`` for bars no cache file may hold.

    Missing values (NaN) are "not supplied" and pass; supplied values must be
    real, so QMT's all-zero no-data padding fails on its prices. Zero-volume
    bars stay: untraded minutes are real native bars and cannot be told apart
    from ``fill_data=True`` padding by value.
    """
    import pandas as pd

    columns = list(df.columns)
    problems = {}
    axis, on_index = _time_axis(df)
    if axis is None:
        problems["no time axis"] = pd.Series(True, index=df.index)
    else:
        labels = pd.Series(df.index if on_index else df[axis].values, index=df.index).astype(str)
        digits = labels.str.replace(r"\D", "", regex=True).str.len()
        problems["invalid time"] = ~digits.between(8, 14)
    for column in _PRICE_COLS:
        if column in columns:
            values = pd.to_numeric(df[column], errors="coerce")
            problems["invalid " + column] = values.notna() & ~(values > 0) | df[column].notna() & values.isna()
    for column in _SIZE_COLS:
        if column in columns:
            values = pd.to_numeric(df[column], errors="coerce")
            problems["invalid " + column] = values.notna() & ~(values >= 0) | df[column].notna() & values.isna()
    if all(name in columns for name in ("open", "high", "low", "close")):
        o, h, low, c = (pd.to_numeric(df[name], errors="coerce") for name in ("open", "high", "low", "close"))
        problems["high/low outside open/close"] = (h < o) | (h < c) | (h < low) | (low > o) | (low > c)
    return {reason: mask.fillna(False).astype(bool) for reason, mask in problems.items() if mask.any()}


def _problem_summary(problems):
    return ", ".join("%s: %d" % (reason, int(mask.sum())) for reason, mask in sorted(problems.items()))


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
        self.rejected_rows = {}

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
        incoming = self._accepted_rows(code, period, df.copy())
        primary = self.path(code, period, dividend_type)
        directory = os.path.dirname(primary)
        if directory and (not os.path.isdir(directory)):
            os.makedirs(directory, exist_ok=True)
        with _write_lock(primary[: -len(self._ext())] + ".lock"):
            return self._merge(code, period, dividend_type, incoming, primary)

    def _reject(self, reason, count):
        self.rejected_rows[reason] = self.rejected_rows.get(reason, 0) + int(count)

    def _read_checked(self, path, period):
        """A cached file that passes the bar checks, or CacheFileInvalid naming the file and reason."""
        try:
            df = self._read_file(path)
        except Exception as exc:
            raise CacheFileInvalid("%s: unreadable (%s: %s)" % (path, type(exc).__name__, exc)) from exc
        missing = _missing_bar_columns(df, period)
        if missing:
            raise CacheFileInvalid("%s: missing columns %s" % (path, ",".join(missing)))
        problems = _row_problems(df)
        if problems:
            raise CacheFileInvalid("%s: %s" % (path, _problem_summary(problems)))
        return df

    def _accepted_rows(self, code, period, df):
        """Drop rows that fail the bar checks before they can reach a merge, and count them."""
        problems = _row_problems(df)
        if not problems:
            return df
        rejected = None
        for reason, mask in problems.items():
            self._reject(reason, mask.sum())
            rejected = mask if rejected is None else rejected | mask
        log.warning(
            "cache rejected %d row(s) for %s %s (%s)", int(rejected.sum()), code, period, _problem_summary(problems)
        )
        return df[~rejected]

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
            old = self._read_checked(existing, period)
            _, old_on_index = _time_axis(old)
            # A narrower update is completed from the stored row; the completed row must pass the same checks.
            merged = self._accepted_rows(code, period, _preserve_omitted_columns(old, incoming))
            if incoming_on_index and old_on_index:
                merged = pd.concat([old, merged])
            elif incoming_on_index and (not old_on_index):
                merged = incoming
            else:
                merged = pd.concat([old, merged], ignore_index=True)
        missing = _missing_bar_columns(merged, period)
        if missing:
            self._reject("missing columns", incoming.shape[0])
            log.warning(
                "cache rejected %d row(s) for %s %s (missing columns %s)",
                incoming.shape[0],
                code,
                period,
                ",".join(missing),
            )
            return self._read_file(existing).shape[0] if existing else 0
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
        df = self._read_checked(existing, period)
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

    def audit(self):
        """Read-only: ``[(path, reason), ...]`` for every cached file that fails the checks."""
        failures = []
        for root, _dirs, fnames in os.walk(self.cache_dir):
            for fname in sorted(fnames):
                if not fname.endswith(self._ext()):
                    continue
                path = os.path.join(root, fname)
                period = os.path.relpath(path, self.cache_dir).split(os.sep)[0]
                try:
                    self._read_checked(path, period)
                except CacheFileInvalid as exc:
                    failures.append((path, str(exc)[len(path) + 2 :]))
        return failures

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
