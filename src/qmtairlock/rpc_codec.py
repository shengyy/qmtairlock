"""JSON encoding for native QMT values, without file or network I/O."""

import datetime as _dt
import json
import math

TYPED_PAYLOAD_FLAG = "__bigqmt_typed__"


def decode_text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def loads_rpc_response(value):
    response = json.loads(value)
    if isinstance(response, dict):
        response[TYPED_PAYLOAD_FLAG] = "__bigqmt_type__" in value
    return response


def _maybe_scalar(value):
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            return value
    return value


def to_jsonable(value):
    kind = type(value)
    if kind is float:
        return None if math.isnan(value) or math.isinf(value) else value
    if kind is int or kind is str or kind is bool or (value is None):
        return value
    if kind is dict:
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if kind is list:
        return [to_jsonable(item) for item in value]
    value = _maybe_scalar(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "isoformat") and value.__class__.__module__.startswith("pandas"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if hasattr(value, "to_dict") and hasattr(value, "columns") and hasattr(value, "index"):
        try:
            frame = value.reset_index()
            return {
                "__bigqmt_type__": "DataFrame",
                "columns": [str(col) for col in frame.columns],
                "records": to_jsonable(frame.to_dict("records")),
            }
        except Exception:
            return str(value)
    if hasattr(value, "to_dict") and hasattr(value, "index") and (not isinstance(value, dict)):
        try:
            return {"__bigqmt_type__": "Series", "data": to_jsonable(value.to_dict())}
        except Exception:
            return str(value)
    if (
        hasattr(value, "major_axis")
        and hasattr(value, "minor_axis")
        and hasattr(value, "items")
        and (not isinstance(value, dict))
    ):
        try:
            labels = [str(item) for item in value.items]
            return {
                "__bigqmt_type__": "Panel",
                "items": labels,
                "major_axis": [str(item) for item in value.major_axis],
                "minor_axis": [str(item) for item in value.minor_axis],
                "data": {str(item): to_jsonable(value[item]) for item in value.items},
            }
        except Exception:
            return str(value)
    if hasattr(value, "tolist") and (not isinstance(value, (str, bytes, bytearray))):
        try:
            return to_jsonable(value.tolist())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    if hasattr(value, "__dict__"):
        return {key: to_jsonable(item) for key, item in vars(value).items() if not key.startswith("_")}
    return str(value)


def _normalize_mapping_value(value):
    """Make one mapping value JSON-safe without flattening its shape."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return dict(((str(k), _normalize_mapping_value(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return [_normalize_mapping_value(v) for v in value]
    rows = _normalize_detail_rows([value])
    return rows[0] if rows else {}


def _normalize_detail_rows(rows):
    """Convert get_trade_detail_data row objects into JSON-serializable dicts."""
    if not rows:
        return []
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(row)
            continue
        item = {}
        for name in dir(row):
            if name.startswith("_"):
                continue
            if not name.isidentifier():
                continue
            try:
                value = getattr(row, name)
            except Exception:
                continue
            if callable(value):
                continue
            item[name] = value
        result.append(item)
    return result


def _jsonable_scalar(value):
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _normalize_grouped_detail_rows(rows):
    """Serialize get_history_trade_detail_data's documented grouped answer."""
    if not rows:
        return []
    result = []
    for entry in rows:
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[1], (list, tuple)):
            timetag, details = entry
            result.append({"timetag": _jsonable_scalar(timetag), "details": _normalize_detail_rows(details)})
        else:
            result.extend(_normalize_detail_rows([entry]))
    return result
