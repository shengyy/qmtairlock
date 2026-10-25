"""Convert native row arrays into typed market-data frame payloads."""


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _float_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _int_or_default(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_flag(value):
    """A request flag as a bool, with JSON's spellings of false honoured."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "none")
    return bool(value)


def _row_day(row):
    """The YYYYMMDD a bar belongs to, from whichever time column it carries."""
    for key in ("stime", "time", "date", "datetime", "timetag"):
        raw = row.get(key)
        if raw in (None, ""):
            continue
        text = str(raw).strip()
        digits = "".join((ch for ch in text if ch.isdigit()))
        if len(digits) >= 13:
            try:
                import datetime as _d

                return _d.datetime.fromtimestamp(int(digits[:13]) / 1000.0).strftime("%Y%m%d")
            except Exception:
                continue
        if len(digits) >= 8:
            return digits[:8]
    return ""


def _frame_rows(frame):
    """A market-data frame as a list of row dicts, whatever shape it arrived in."""
    if frame is None:
        return []
    if isinstance(frame, dict) and frame.get("__bigqmt_type__") == "DataFrame":
        return _frame_rows(frame.get("records") or [])
    if hasattr(frame, "columns") and hasattr(frame, "iloc"):
        try:
            columns = list(frame.columns)
            return [{name: frame[name][i] for name in columns} for i in range(len(frame))]
        except Exception:
            return []
    if isinstance(frame, (list, tuple)):
        return [row for row in frame if isinstance(row, dict)]
    if isinstance(frame, dict):
        columns = {k: v for k, v in frame.items() if hasattr(v, "__len__") and (not isinstance(v, (str, bytes)))}
        if not columns:
            return [dict(frame)]
        length = min((len(v) for v in columns.values()))
        return [{k: v[i] for k, v in columns.items()} for i in range(length)]
    return []


def _raw_frame_columns(field_list):
    columns = [str(field) for field in field_list or []]
    if columns and "stime" not in columns:
        columns.insert(0, "stime")
    return columns


def _records_have_rows(records):
    """True when ``records`` carries at least one bar."""
    if records is None:
        return False
    if isinstance(records, dict):
        if records.get("__bigqmt_type__") == "DataFrame":
            return _records_have_rows(records.get("records"))
        for column in records.values():
            try:
                if len(column) > 0:
                    return True
            except TypeError:
                if column not in (None, ""):
                    return True
        return False
    try:
        return len(records) > 0
    except TypeError:
        return bool(records)


def _market_data_answer_empty(answer):
    """True when no code in the answer carries a single row."""
    if not isinstance(answer, dict) or not answer:
        return True
    for value in answer.values():
        if isinstance(value, dict) and value.get("__bigqmt_type__") == "DataFrame":
            if _records_have_rows(value.get("records")):
                return False
        elif hasattr(value, "index"):
            try:
                if len(value.index) > 0:
                    return False
            except Exception:
                return False
        elif _records_have_rows(value):
            return False
    return True


def _raw_market_data_payload(payload, field_list, stock_list, partial=None):
    """Serialisable ``{code: DataFrame envelope}``."""
    if not isinstance(payload, dict):
        return payload
    source = {str(code): records for code, records in payload.items()}
    codes = []
    for code in list(stock_list or []) + list(source):
        text = str(code)
        if text not in codes:
            codes.append(text)
    columns = _raw_frame_columns(field_list)
    frames = {}
    for code in codes:
        frame = {"__bigqmt_type__": "DataFrame", "columns": columns, "records": source.get(code) or []}
        if partial:
            frame["__bigqmt_partial__"] = dict(partial)
        frames[code] = frame
    return frames
