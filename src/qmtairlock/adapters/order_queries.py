"""Native ORDER/DEAL snapshots and field inspection, on the strategy thread."""

from ..account_scope import ACCOUNT_TYPE_CODES, account_type_for
from ..models import OrderSnapshot, TradeSnapshot
from ..native_time import date_time_seconds
from .order_types import _action_from_offset_flag
from .position_bigqmt import _attr, _full_code, skip_unparsable_row

_SHAPE_MASK_MAX = 200
_STRATEGY_NAME_FIELDS = ("strategyName", "m_strStrategyName", "strategy_name", "m_strSource")


def _first_nonzero(row, names, default=0.0):
    """First candidate attribute with a non-zero numeric value."""
    for name in names:
        value = getattr(row, name, None)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number:
            return number
    return default


def _row_strategy_name(row):
    """First NON-EMPTY strategy-name candidate on a QMT row, or ""."""
    for name in _STRATEGY_NAME_FIELDS:
        text = str(_attr(row, (name,), "") or "").strip()
        if text:
            return text
    return ""


def _data_attribute_names(row):
    """Public non-callable attribute names on a QMT row object."""
    names = []
    for name in dir(row):
        if name.startswith("_"):
            continue
        try:
            value = getattr(row, name)
        except Exception:
            continue
        if not callable(value):
            names.append(name)
    return sorted(names)


def _report_missing_order_time(row):
    if _missing_order_time_reported:
        return
    _missing_order_time_reported.append(True)
    try:
        available = sorted((n for n in dir(row) if n.startswith("m_")))
    except Exception:
        available = []
    print(
        "[bigqmt_order] order_time not found (tried %s / %s); ORDER row exposes: %s"
        % (", ".join(_ORDER_DATE_FIELDS), ", ".join(_ORDER_TIME_FIELDS), ", ".join(available) or "<none>")
    )


def _status_message(row):
    for name in _STATUS_MSG_FIELDS:
        value = _attr(row, (name,))
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _order_time_seconds(row):
    """把 ORDER 行的报单日期+时间转成 Unix 秒, 拿不到返回 0。"""
    raw_time = _attr(row, _ORDER_TIME_FIELDS)
    raw_date = _attr(row, _ORDER_DATE_FIELDS)
    if raw_time is None and raw_date is None:
        _report_missing_order_time(row)
        return 0
    return date_time_seconds(raw_date, raw_time)


class OrderQueries:
    def __init__(self, context_info=None, get_trade_detail_data_func=None, account_id=""):
        self.context_info = context_info
        self.get_trade_detail_data = get_trade_detail_data_func
        self.account_id = str(account_id)
        self.account_type = "STOCK"

    def _resolve_account_type(self, account_id):
        return account_type_for(account_id, self.account_type)

    def _account_type_code(self, account_id=None):
        return ACCOUNT_TYPE_CODES.get(self._resolve_account_type(account_id), 2)

    def _instrument_name(self, row, stock_code, cache):
        """证券名称 —— from the row if QMT put it there, else ContextInfo."""
        name = str(_attr(row, ("m_strInstrumentName", "instrument_name", "stock_name"), "") or "")
        if name:
            return name
        if stock_code in cache:
            return cache[stock_code]
        resolved = ""
        getter = getattr(self.context_info, "get_stock_name", None)
        if getter is not None:
            try:
                resolved = str(getter(stock_code) or "")
            except Exception:
                resolved = ""
        cache[stock_code] = resolved
        return resolved

    def _require_query_func(self):
        if self.get_trade_detail_data is None:
            raise RuntimeError("get_trade_detail_data is not available in Big QMT runtime")
        return self.get_trade_detail_data

    def query_native_rows(self, account_id, kind, strategy_name=""):
        """The terminal's own ORDER / DEAL rows for ``account_id``, unconverted."""
        query = self._require_query_func()
        account_type = self._resolve_account_type(account_id)
        return query(account_id, account_type, str(kind or "ORDER").upper(), strategy_name) or []

    def query_orders(self, account_id, strategy_name):
        return self.query_orders_strict(account_id, strategy_name)

    def query_orders_strict(self, account_id, strategy_name):
        query = self._require_query_func()
        account_type = self._resolve_account_type(account_id)
        rows = query(account_id, account_type, "ORDER", strategy_name) or []
        result = []
        account_type_code = self._account_type_code(account_id)
        name_cache = {}
        for row in rows:
            try:
                stock_code = _full_code(
                    _attr(row, ("m_strInstrumentID", "instrument_id", "stock_code")),
                    _attr(row, ("m_strExchangeID", "exchange_id", "market")),
                )
            except Exception as exc:
                skip_unparsable_row("ORDER", row, exc)
                continue
            result.append(
                OrderSnapshot(
                    order_sys_id=str(_attr(row, ("m_strOrderSysID", "order_sys_id"), "") or ""),
                    user_order_id=str(_attr(row, ("m_strRemark", "user_order_id", "remark"), "") or ""),
                    stock_code=stock_code,
                    action=_action_from_offset_flag(
                        _attr(row, ("m_nOffsetFlag", "offset_flag"), 0),
                        _attr(row, ("m_nOpType", "op_type"), None),
                        self._resolve_account_type(account_id),
                        _attr(row, ("m_nDirection", "direction")),
                    ),
                    volume=int(_attr(row, ("m_nVolumeTotalOriginal", "volume"), 0) or 0),
                    traded_volume=int(_attr(row, ("m_nVolumeTraded", "traded_volume"), 0) or 0),
                    status=str(_attr(row, ("m_nOrderStatus", "status"), "") or ""),
                    strategy_name=_row_strategy_name(row) or strategy_name or "",
                    price=float(_attr(row, ("m_dLimitPrice", "m_dPrice", "price"), 0.0) or 0.0),
                    remark=str(_attr(row, ("m_strRemark", "remark"), "") or ""),
                    order_time=_order_time_seconds(row),
                    status_msg=_status_message(row),
                    price_type=_attr(row, ("m_nOrderPriceType", "price_type")),
                    traded_price=float(_attr(row, ("m_dTradedPrice", "traded_price", "avg_traded_price"), 0.0) or 0.0),
                    trade_amount=float(_attr(row, ("m_dTradeAmount", "trade_amount", "amount"), 0.0) or 0.0),
                    account_type=account_type_code,
                    instrument_name=self._instrument_name(row, stock_code, name_cache),
                    secu_account=str(_attr(row, ("m_strShareholderID", "m_strSecuAccount", "secu_account"), "") or ""),
                    offset_flag=_attr(row, ("m_nOffsetFlag", "offset_flag")),
                    direction=_attr(row, ("m_nDirection", "direction")),
                    op_type=_attr(row, ("m_nOpType", "op_type")),
                    entrust_type=_attr(row, ("m_eEntrustType", "entrust_type")),
                    opt_name=str(_attr(row, ("m_strOptName", "opt_name"), "") or ""),
                )
            )
        return result

    def query_trades(self, account_id, strategy_name):
        return self.query_trades_strict(account_id, strategy_name)

    def query_trades_strict(self, account_id, strategy_name):
        query = self._require_query_func()
        account_type = self._resolve_account_type(account_id)
        if str(strategy_name or "").strip():
            rows = query(account_id, account_type, "DEAL", strategy_name) or []
        else:
            rows = query(account_id, account_type, "DEAL") or []
        result = []
        account_type_code = self._account_type_code(account_id)
        name_cache = {}
        for row in rows:
            traded_at_raw = _attr(row, ("m_strTradeTime", "trade_time", "traded_at"), "")
            try:
                stock_code = _full_code(
                    _attr(row, ("m_strInstrumentID", "instrument_id", "stock_code")),
                    _attr(row, ("m_strExchangeID", "exchange_id", "market")),
                )
            except Exception as exc:
                skip_unparsable_row("DEAL", row, exc)
                continue
            result.append(
                TradeSnapshot(
                    trade_id=str(_attr(row, ("m_strTradeID", "trade_id"), "") or ""),
                    order_sys_id=str(_attr(row, ("m_strOrderSysID", "order_sys_id"), "") or ""),
                    stock_code=stock_code,
                    action=_action_from_offset_flag(
                        _attr(row, ("m_nOffsetFlag", "offset_flag"), 0),
                        _attr(row, ("m_nOpType", "op_type"), None),
                        self._resolve_account_type(account_id),
                        _attr(row, ("m_nDirection", "direction")),
                    ),
                    volume=int(_attr(row, ("m_nVolume", "volume"), 0) or 0),
                    price=float(_attr(row, ("m_dPrice", "m_dTradePrice", "price"), 0.0) or 0.0),
                    traded_at=str(traded_at_raw or ""),
                    user_order_id=str(_attr(row, ("m_strRemark", "user_order_id", "remark"), "") or ""),
                    amount=float(_attr(row, ("m_dTradeAmount", "amount"), 0.0) or 0.0),
                    strategy_name=_row_strategy_name(row) or strategy_name or "",
                    traded_time=date_time_seconds(
                        _attr(row, ("m_strTradeDate", "trade_date", "m_strDealDate")), traded_at_raw
                    ),
                    account_type=account_type_code,
                    instrument_name=self._instrument_name(row, stock_code, name_cache),
                    secu_account=str(_attr(row, ("m_strShareholderID", "m_strSecuAccount", "secu_account"), "") or ""),
                    commission=_first_nonzero(row, ("m_dComssion", "m_dCommission", "commission")),
                    offset_flag=_attr(row, ("m_nOffsetFlag", "offset_flag")),
                    direction=_attr(row, ("m_nDirection", "direction")),
                    op_type=_attr(row, ("m_nOpType", "op_type")),
                    entrust_type=_attr(row, ("m_eEntrustType", "entrust_type")),
                    opt_name=str(_attr(row, ("m_strOptName", "opt_name"), "") or ""),
                )
            )
        return result

    @staticmethod
    def _field_shape(value):
        """A field's shape with its identity removed."""
        text = "" if value is None else str(value)
        masked = []
        for ch in text[:_SHAPE_MASK_MAX]:
            if ch.isdigit():
                masked.append("#")
            elif ch.isalpha():
                masked.append("a")
            else:
                masked.append(ch)
        return {
            "length": len(text),
            "empty": not text,
            "segments": [len(part) for part in text.split("|")] if text else [],
            "mask": "".join(masked),
        }

    def describe_detail_fields(self, account_id, detail_types=None, shape_fields=None):
        """Which attributes QMT's own ORDER / DEAL rows actually carry."""
        query = self._require_query_func()
        wanted_shapes = [str(name) for name in shape_fields or [] if str(name or "").strip()]
        described = {}
        for detail_type in detail_types or ("ORDER", "DEAL"):
            entry = {"rows": 0, "attributes": [], "error": ""}
            try:
                rows = query(account_id, self._resolve_account_type(account_id), str(detail_type)) or []
                entry["rows"] = len(rows)
                if rows:
                    entry["attributes"] = _data_attribute_names(rows[0])
                    if wanted_shapes:
                        shapes = {}
                        for name in wanted_shapes:
                            distinct = {}
                            for row in rows:
                                shape = self._field_shape(_attr(row, (name,), ""))
                                key = shape["mask"]
                                if key not in distinct:
                                    shape["rows"] = 0
                                    distinct[key] = shape
                                distinct[key]["rows"] += 1
                            shapes[name] = sorted(distinct.values(), key=lambda s: -s["rows"])
                        entry["shapes"] = shapes
            except Exception as exc:
                entry["error"] = "%s: %s" % (type(exc).__name__, exc)
            described[str(detail_type)] = entry
        return described

    def query_submission_identities_strict(self, account_id, strategy_name):
        orders = self.query_orders_strict(account_id, strategy_name)
        trades = self.query_trades_strict(account_id, strategy_name)
        return (orders, trades)


_ORDER_DATE_FIELDS = ("m_strInsertDate", "m_strOrderDate", "insert_date", "order_date")
_ORDER_TIME_FIELDS = ("m_strInsertTime", "m_strOrderTime", "insert_time", "order_time")
_missing_order_time_reported = []
_STATUS_MSG_FIELDS = ("m_strCancelInfo", "m_strErrorMsg", "m_strStatusMsg", "status_msg", "error_msg")
