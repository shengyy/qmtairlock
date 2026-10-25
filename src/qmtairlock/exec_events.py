"""Normalize native execution callbacks; no transport or persistence side effects."""

import time

from .native_time import date_time_seconds

_STRATEGY_NAME_FIELDS = ("strategyName", "m_strStrategyName", "strategy_name", "m_strSource")

EVENT_ORDER = "order"
EVENT_TRADE = "trade"
EVENT_ORDER_ERROR = "order_error"
EVENT_CANCEL_ERROR = "cancel_error"
ENTRUST_BUY = 48
ENTRUST_SELL = 49
ENTRUST_PLEDGE_IN = 81
ENTRUST_PLEDGE_OUT = 66
OFFSET_OPEN = 48
OFFSET_CLOSE = 49
OFFSET_CLOSE_TODAY = 51
OFFSET_CLOSE_YESTERDAY = 52
_BUY_DIRECTIONS = {ENTRUST_BUY, str(ENTRUST_BUY), OFFSET_OPEN, str(OFFSET_OPEN), 23, "23", "BUY", "buy", "B"}
_SELL_DIRECTIONS = {
    ENTRUST_SELL,
    str(ENTRUST_SELL),
    OFFSET_CLOSE,
    str(OFFSET_CLOSE),
    OFFSET_CLOSE_TODAY,
    str(OFFSET_CLOSE_TODAY),
    OFFSET_CLOSE_YESTERDAY,
    str(OFFSET_CLOSE_YESTERDAY),
    24,
    "24",
    "SELL",
    "sell",
    "S",
}
_FUTURES_OP_BUY = frozenset({0, 4, 5, 8, 9, 12, 13, 14})
_FUTURES_OP_SELL = frozenset({1, 2, 3, 6, 7, 10, 11, 15})
_ETF_OPTION_OP_BUY = frozenset({50, 53, 55})
_ETF_OPTION_OP_SELL = frozenset({51, 52, 54})


def _attr(obj, names, default=None):
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return default


def _strategy_name_of(obj):
    """First NON-EMPTY strategy-name candidate, or ""."""
    for name in _STRATEGY_NAME_FIELDS:
        value = _attr(obj, [name], "")
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _with_exchange_suffix(raw_code, obj):
    """Append the exchange suffix to a bare instrument code."""
    text = str(raw_code or "")
    if not text or "." in text:
        return text
    exchange = str(_attr(obj, ["m_strExchangeID", "m_strMarketID", "exchange_id", "market"], "") or "").strip().upper()
    if exchange:
        return "%s.%s" % (text, exchange)
    return text


def _action_from_direction(direction):
    if direction in _BUY_DIRECTIONS:
        return "BUY"
    if direction in _SELL_DIRECTIONS:
        return "SELL"
    return ""


def _is_buy(val):
    v = int(val)
    return v in _BUY_DIRECTIONS


def _is_sell(val):
    v = int(val)
    return v in _SELL_DIRECTIONS


def _conflict_resolve(d_val, o_val, obj):
    """When m_nDirection and m_nOffsetFlag disagree, arbitrate via m_nOpType."""
    op = _attr(obj, ["m_nOpType", "op_type", "order_type"])
    if op is not None:
        try:
            op_int = int(op)
            if op_int in _BUY_DIRECTIONS:
                return d_val if _is_buy(d_val) else o_val if _is_buy(o_val) else op
            if op_int in _SELL_DIRECTIONS:
                return d_val if _is_sell(d_val) else o_val if _is_sell(o_val) else op
            if op_int in _FUTURES_OP_BUY or op_int in _ETF_OPTION_OP_BUY:
                return d_val if _is_buy(d_val) else o_val if _is_buy(o_val) else op
            if op_int in _FUTURES_OP_SELL or op_int in _ETF_OPTION_OP_SELL:
                return d_val if _is_sell(d_val) else o_val if _is_sell(o_val) else op
        except (TypeError, ValueError):
            if op in _BUY_DIRECTIONS:
                return d_val if _is_buy(d_val) else o_val if _is_buy(o_val) else op
            if op in _SELL_DIRECTIONS:
                return d_val if _is_sell(d_val) else o_val if _is_sell(o_val) else op
    return o_val


def _extract_direction(obj):
    """Extract buy/sell direction, matching query_orders' reliable logic."""
    offset = _attr(obj, ["m_nOffsetFlag", "offset_flag"])
    direction = _attr(obj, ["m_nDirection", "direction"])
    if offset is not None and direction is None:
        try:
            o = int(offset)
            if o in _BUY_DIRECTIONS or o in _SELL_DIRECTIONS:
                return offset
        except (TypeError, ValueError):
            if offset in _BUY_DIRECTIONS or offset in _SELL_DIRECTIONS:
                return offset
    if direction is not None and offset is None:
        try:
            d = int(direction)
            if d in _BUY_DIRECTIONS or d in _SELL_DIRECTIONS:
                return direction
            if d != 0:
                return direction
        except (TypeError, ValueError):
            if direction in _BUY_DIRECTIONS or direction in _SELL_DIRECTIONS:
                return direction
            return direction
    if direction is not None and offset is not None:
        try:
            d = int(direction)
            o = int(offset)
            d_valid = d in _BUY_DIRECTIONS or d in _SELL_DIRECTIONS
            o_valid = o in _BUY_DIRECTIONS or o in _SELL_DIRECTIONS
            if d_valid and o_valid:
                if d == o:
                    return direction
                return _conflict_resolve(d, o, obj)
            if d_valid and (not o_valid):
                return direction
            if o_valid and (not d_valid):
                return offset
        except (TypeError, ValueError):
            pass
    return _attr(obj, ["m_nOpType", "op_type", "order_type"])


def event_account_id(obj):
    """The account a native order / deal object names, or ""."""
    return str(_attr(obj, ["m_strAccountID", "account_id"], "") or "").strip()


def normalize_order_event(order, account_id="", account_type="STOCK"):
    """Build a JSON-able order event dict from a Big QMT orderInfo object."""
    direction = (
        _attr(order, ["m_nDirection", "direction"]) if account_type == "STOCK_OPTION" else _extract_direction(order)
    )
    return {
        "event_type": EVENT_ORDER,
        "account_id": str(_attr(order, ["m_strAccountID", "account_id"], account_id) or account_id or ""),
        "stock_code": _with_exchange_suffix(
            _attr(order, ["m_strInstrumentID", "stock_code", "m_strInstrument"], ""), order
        ),
        "order_sys_id": str(_attr(order, ["m_strOrderSysID", "order_sys_id", "order_sysid", "order_id"], "") or ""),
        "order_volume": _attr(order, ["m_nVolumeTotalOriginal", "m_nVolumeTotal", "order_volume", "volume"]),
        "traded_volume": _attr(order, ["m_nVolumeTraded", "traded_volume"]),
        "price": _attr(order, ["m_dLimitPrice", "price", "limit_price"]),
        "traded_price": _attr(order, ["m_dTradedPrice", "traded_price", "avg_traded_price"]),
        "trade_amount": _attr(order, ["m_dTradeAmount", "trade_amount"]),
        "price_type": _attr(order, ["m_nOrderPriceType", "price_type"]),
        "status": _attr(order, ["m_nOrderStatus", "order_status", "status"]),
        "direction": direction,
        "action": _action_from_direction(direction),
        "offset_flag": _attr(order, ["m_nOffsetFlag", "offset_flag"]),
        "strategy_name": _strategy_name_of(order),
        "instrument_name": str(_attr(order, ["m_strInstrumentName", "instrument_name"], "") or ""),
        "remark": str(_attr(order, ["m_strRemark", "order_remark", "remark", "user_order_id"], "") or ""),
        "user_order_id": str(_attr(order, ["m_strRemark", "user_order_id", "order_remark", "remark"], "") or ""),
        "opt_name": str(_attr(order, ["m_strOptName", "opt_name"], "") or ""),
        "status_msg": str(
            _attr(order, ["m_strCancelInfo", "m_strErrorMsg", "m_strStatusMsg", "status_msg", "error_msg"], "") or ""
        ),
        "order_time": date_time_seconds(
            _attr(order, ["m_strInsertDate", "m_strOrderDate", "insert_date", "order_date"]),
            _attr(order, ["m_strInsertTime", "m_strOrderTime", "insert_time", "order_time"]),
        ),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_at_ts": time.time(),
    }


def normalize_trade_event(trade, account_id=""):
    """Build a JSON-able trade (成交) event dict from a Big QMT dealInfo object."""
    direction = _extract_direction(trade)
    return {
        "event_type": EVENT_TRADE,
        "account_id": str(_attr(trade, ["m_strAccountID", "account_id"], account_id) or account_id or ""),
        "stock_code": _with_exchange_suffix(_attr(trade, ["m_strInstrumentID", "stock_code"], ""), trade),
        "instrument_name": str(_attr(trade, ["m_strInstrumentName", "instrument_name"], "") or ""),
        "order_sys_id": str(_attr(trade, ["m_strOrderSysID", "order_sys_id", "order_sysid", "order_id"], "") or ""),
        "trade_id": str(_attr(trade, ["m_strTradeID", "trade_id"], "") or ""),
        "volume": _attr(trade, ["m_nVolume", "volume", "traded_volume"]),
        "price": _attr(trade, ["m_dPrice", "price", "traded_price"]),
        "amount": _attr(trade, ["m_dTradeAmount", "amount"]),
        "commission": _attr(trade, ["m_dComssion", "m_dCommission", "commission"]),
        "direction": direction,
        "action": _action_from_direction(direction),
        "offset_flag": _attr(trade, ["m_nOffsetFlag", "offset_flag"]),
        "traded_at": str(_attr(trade, ["m_strTradeTime", "traded_at", "trade_time"], "") or ""),
        "remark": str(_attr(trade, ["m_strRemark", "order_remark", "remark", "user_order_id"], "") or ""),
        "user_order_id": str(_attr(trade, ["m_strRemark", "user_order_id", "order_remark", "remark"], "") or ""),
        "strategy_name": _strategy_name_of(trade),
        "traded_time": date_time_seconds(
            _attr(trade, ["m_strTradeDate", "trade_date", "m_strDealDate"]),
            _attr(trade, ["m_strTradeTime", "trade_time", "traded_at"]),
        ),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_at_ts": time.time(),
    }


def normalize_order_error_event(order_error, account_id=""):
    """Build a JSON-able order-error event dict (废单/拒单)."""
    return {
        "event_type": EVENT_ORDER_ERROR,
        "account_id": str(_attr(order_error, ["m_strAccountID", "account_id"], account_id) or account_id or ""),
        "stock_code": str(_attr(order_error, ["m_strInstrumentID", "stock_code"], "") or ""),
        "order_sys_id": str(
            _attr(order_error, ["m_strOrderSysID", "order_sys_id", "order_sysid", "order_id"], "") or ""
        ),
        "error_id": _attr(order_error, ["m_nErrorID", "error_id", "m_nOrderStatus"]),
        "status": _attr(order_error, ["m_nOrderStatus", "status"]),
        "order_remark": str(_attr(order_error, ["m_strRemark", "order_remark", "remark", "user_order_id"], "") or ""),
        "user_order_id": str(_attr(order_error, ["m_strRemark", "user_order_id", "order_remark", "remark"], "") or ""),
        "error_msg": str(
            _attr(
                order_error,
                ["m_strCancelInfo", "m_strErrorMsg", "error_msg", "m_strMsg", "m_strStatusMsg", "status_msg"],
                "",
            )
            or ""
        ),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_at_ts": time.time(),
    }


def normalize_cancel_error_event(cancel_error, account_id=""):
    """Build a JSON-able cancel-error event dict (撤单失败)."""
    return {
        "event_type": EVENT_CANCEL_ERROR,
        "account_id": str(_attr(cancel_error, ["m_strAccountID", "account_id"], account_id) or account_id or ""),
        "stock_code": str(_attr(cancel_error, ["m_strInstrumentID", "stock_code"], "") or ""),
        "order_sys_id": str(
            _attr(cancel_error, ["m_strOrderSysID", "order_sys_id", "order_sysid", "order_id"], "") or ""
        ),
        "error_id": _attr(cancel_error, ["m_nErrorID", "error_id"]),
        "order_remark": str(_attr(cancel_error, ["m_strRemark", "order_remark", "remark", "user_order_id"], "") or ""),
        "user_order_id": str(_attr(cancel_error, ["m_strRemark", "user_order_id", "order_remark", "remark"], "") or ""),
        "error_msg": str(_attr(cancel_error, ["m_strErrorMsg", "error_msg", "m_strMsg"], "") or ""),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "created_at_ts": time.time(),
    }
