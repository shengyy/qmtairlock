"""Deserialize QMT frames and retain their source time axis and native units."""

import datetime as _dt
import warnings

from .logging_setup import get_logger

log = get_logger("data")
PARTIAL_MARKER_ATTR = "__bigqmt_partial__"
_partial_warned = set()
PRE_CLOSE_BACKFILL_PERIODS = ("1w", "1mon", "1q", "1hy", "1y")


def _attach_partial_marker(frame, marker):
    if not isinstance(marker, dict):
        return frame
    try:
        frame.attrs[PARTIAL_MARKER_ATTR] = dict(marker)
    except Exception:
        pass
    return frame


def _partial_marker(frame):
    """The server's degraded-answer marker on a frame, or None."""
    try:
        marker = frame.attrs.get(PARTIAL_MARKER_ATTR)
    except Exception:
        return None
    return marker if isinstance(marker, dict) else None


def _warn_partial_market_data(markers):
    """Say once per distinct degradation that the answer is not the full one."""
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        key = (
            str(marker.get("reason") or ""),
            str(marker.get("period") or ""),
            str(marker.get("source") or ""),
            ",".join((str(name) for name in marker.get("missing") or [])),
            bool(marker.get("fill_data_dropped")),
        )
        if key in _partial_warned:
            continue
        _partial_warned.add(key)
        message = (
            "bigqmt: %s bars for period=%s were served by %s, not the usual path: columns served %s%s%s. See DataFrame.attrs[%r]."
            % (
                marker.get("reason") or "partial",
                marker.get("period") or "?",
                marker.get("source") or "?",
                ",".join((str(name) for name in marker.get("served") or [])) or "-",
                "; MISSING %s" % ",".join((str(n) for n in marker["missing"])) if marker.get("missing") else "",
                "; fill_data did not reach the terminal" if marker.get("fill_data_dropped") else "",
                PARTIAL_MARKER_ATTR,
            )
        )
        warnings.warn(message, stacklevel=2)
        log.warning("%s", message)


def _restore_jsonable(value):
    if isinstance(value, dict):
        marker = value.get("__bigqmt_type__")
        if marker == "DataFrame":
            try:
                import pandas as pd

                frame = pd.DataFrame(value.get("records") or [], columns=value.get("columns") or None)
            except Exception:
                return value.get("records") or []
            _attach_partial_marker(frame, value.get("__bigqmt_partial__"))
            return frame
        if marker == "Panel":
            return {key: _restore_jsonable(item) for key, item in (value.get("data") or {}).items()}
        if marker == "Series":
            try:
                import pandas as pd

                return pd.Series(value.get("data") or {})
            except Exception:
                return value.get("data") or {}
        return {key: _restore_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore_jsonable(item) for item in value]
    return value


def _divid_day_key(key):
    """A big-QMT ms timestamp key -> the YYYYMMDD string xtdata indexes by."""
    import datetime as _dt

    text = str(key).strip()
    if len(text) == 8 and text.isdigit():
        return text
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    seconds = number / 1000.0 if number > 100000000000.0 else number
    day = _dt.datetime(1970, 1, 1) + _dt.timedelta(seconds=seconds + _SHANGHAI_OFFSET_S)
    return day.strftime("%Y%m%d")


def _divid_factors_frame(data):
    """``dict{ms: [7 values]}`` -> the DataFrame ``xtdata.get_divid_factors`` returns."""
    if not isinstance(data, dict):
        return data
    import pandas as pd

    columns = list(DIVID_FRAME_COLUMNS)
    if not data:
        return pd.DataFrame(columns=columns, dtype="float64")
    rows = {}
    for key, value in data.items():
        try:
            time_ms = float(key)
        except (TypeError, ValueError):
            time_ms = float("nan")
        if isinstance(value, dict):
            if value.get("time") is not None:
                try:
                    time_ms = float(value["time"])
                except (TypeError, ValueError):
                    pass
            factors = [value.get(name) for name in DIVID_FACTOR_COLUMNS]
        else:
            seq = list(value) if isinstance(value, (list, tuple)) else [value]
            factors = (seq + [None] * len(DIVID_FACTOR_COLUMNS))[: len(DIVID_FACTOR_COLUMNS)]
        rows[_divid_day_key(key)] = [time_ms] + factors
    frame = pd.DataFrame.from_dict(rows, orient="index", columns=columns)
    return frame.astype("float64")


def _digits_only(value):
    return "".join((ch for ch in str(value or "") if ch.isdigit()))


def _parse_qmt_stime(value):
    digits = _digits_only(value)
    if len(digits) >= 14:
        try:
            return _dt.datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None
    if len(digits) >= 8:
        try:
            return _dt.datetime.strptime(digits[:8], "%Y%m%d")
        except ValueError:
            return None
    return None


def _qmt_stime_index(value):
    digits = _digits_only(value)
    if len(digits) >= 14:
        return digits[:14]
    if len(digits) >= 8:
        return digits[:8]
    return str(value or "")


def _is_epoch_placeholder_label(value):
    """True for a bar label that predates the A-share market itself."""
    digits = _digits_only(value)
    if len(digits) < 8:
        return False
    return digits[:8] < _EPOCH_PLACEHOLDER_FLOOR


def _qmt_datetime_to_epoch_ms(dt_value):
    china_tz = _dt.timezone(_dt.timedelta(hours=8))
    return int(dt_value.replace(tzinfo=china_tz).timestamp() * 1000)


def _normalize_market_data_frame(df, field_list=None):
    try:
        columns = list(df.columns)
    except Exception:
        return df
    if "stime" not in columns:
        return df
    requested = [str(field) for field in field_list or []]
    try:
        out = df.copy()
        stimes = list(out["stime"])
        out.index = [_qmt_stime_index(value) for value in stimes]
        if "time" in out.columns or "time" in requested:
            out["time"] = [
                _qmt_datetime_to_epoch_ms(parsed) if parsed is not None else None
                for parsed in (_parse_qmt_stime(value) for value in stimes)
            ]
        keep = [position for position, value in enumerate(stimes) if not _is_epoch_placeholder_label(value)]
        if len(keep) != len(stimes):
            out = out.iloc[keep]
        if requested:
            keep = [field for field in requested if field in out.columns]
            if keep:
                return out[keep]
        if "stime" in out.columns:
            return out.drop(columns=["stime"])
        return out
    except Exception:
        return df


def _ensure_preclose_from_lag(df, field_list=None, period=None):
    """preClose 行级兜底: 该列缺失/为0 且当日 close 有效时, 用前收 lag 补。"""
    try:
        if not hasattr(df, "columns") or "close" not in df.columns:
            return df
        requested = [str(f) for f in field_list or []]
        wants_column = not requested or "preClose" in requested
        close = df["close"]
        valid_close = close.notna() & (close > 0)
        lag = close.shift(1)
        fill = lag.where(lag.notna() & (lag > 0), close)
        if "preClose" not in df.columns:
            if not wants_column:
                return df
            out = df.copy()
            out["preClose"] = fill.where(valid_close, 0)
            return out
        if str(period or "") in PRE_CLOSE_BACKFILL_PERIODS:
            return df
        if not bool(valid_close.any()):
            return df
        bad = (df["preClose"].isna() | (df["preClose"] == 0)) & valid_close
        if not bool(bad.any()):
            return df
        out = df.copy()
        out.loc[bad, "preClose"] = fill[bad]
        return out
    except Exception:
        return df


def _ensure_suspend_flag_column(df, field_list=None):
    """suspendFlag 列形状兜底: 空 field_list(=全字段)或点名时, 缺列则补 0。"""
    try:
        if not hasattr(df, "columns"):
            return df
        if "suspendFlag" in df.columns:
            return df
        requested = [str(f) for f in field_list or []]
        if requested and "suspendFlag" not in requested:
            return df
        out = df.copy()
        out["suspendFlag"] = 0
        return out
    except Exception:
        return df


def _ensure_kline_columns(df, field_list=None, period=None):
    """K 线可选列的形状兜底组合: preClose(lag) 之后补 suspendFlag。"""
    return _ensure_suspend_flag_column(
        _ensure_preclose_from_lag(df, field_list=field_list, period=period), field_list=field_list
    )


def _normalize_market_data_result(data, field_list=None, period=None):
    if not isinstance(data, dict):
        return _ensure_kline_columns(data, field_list=field_list, period=period)
    return {
        code: _ensure_kline_columns(
            _normalize_market_data_frame(frame, field_list=field_list), field_list=field_list, period=period
        )
        for code, frame in data.items()
    }


DIVID_FACTOR_COLUMNS = ("interest", "stockBonus", "stockGift", "allotNum", "allotPrice", "gugai", "dr")
DIVID_FRAME_COLUMNS = ("time",) + DIVID_FACTOR_COLUMNS
_SHANGHAI_OFFSET_S = 8 * 3600
_EPOCH_PLACEHOLDER_FLOOR = "19900101"
