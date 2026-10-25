"""Account, credit, convertible and option order-type mapping."""

from .. import constants as _xtconstant
from ..option_order_type import option_native_optype


def enum_integer(value, name):
    if isinstance(value, bool):
        raise ValueError("%s must be an integer enum" % name)
    try:
        number = int(value)
        if isinstance(value, str):
            valid = value.strip() == str(number)
        else:
            valid = value == number
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError("%s must be an integer enum" % name)
    return number


def validate_native_optype(value, account_type):
    value = enum_integer(value, "op_type")
    kind = str(account_type).upper()
    allowed = {
        "STOCK": {23, 24, 80, 81},
        "CREDIT": {23, 24, 27, 28, 29, 30, 31, 32, 33, 34, 70, 71, 72, 73, 74, 75, 82, 83},
        "STOCK_OPTION": set(range(50, 60)),
        "FUTURE": set(range(16)),
        "FUTURE_OPTION": set(range(16)),
        "HUGANGTONG": {23, 24},
        "SHENGANGTONG": {23, 24},
        "NEW3BOARD": {23, 24},
    }.get(kind, set())
    if value not in allowed:
        raise ValueError("op_type %s is not supported for %s" % (value, kind))
    return value


def resolve_order_type(order_type, action, account_type):
    """Translate a public order enum and bind it to one enabled account domain."""
    if order_type is None:
        if account_type not in {"STOCK", "CREDIT", "HUGANGTONG", "SHENGANGTONG", "NEW3BOARD"}:
            raise ValueError("order_type is required")
        value = {"BUY": 23, "SELL": 24}.get(str(action).upper())
    else:
        value = enum_integer(order_type, "order_type")
    if account_type == "STOCK_OPTION":
        native = option_native_optype(value)
    elif account_type == "CREDIT":
        native = CREDIT_OPTYPE_BY_ORDER_TYPE.get(value, value)
    else:
        native = value
    native = validate_native_optype(native, account_type)
    side = {
        23: "BUY",
        24: "SELL",
        33: "BUY",
        34: "SELL",
        27: "BUY",
        28: "SELL",
        29: "BUY",
        30: "SELL",
        31: "SELL",
        70: "BUY",
        71: "SELL",
        72: "BUY",
        73: "SELL",
        74: "SELL",
    }.get(native)
    side = side or passthrough_action_of(native)
    if side and action and side != str(action).upper():
        raise ValueError("action conflicts with order_type")
    return native, side or "SELL"


PRICE_TYPE_ALIASES = {
    "LIMIT": 11,
    "FIX_PRICE": 11,
    "LATEST_PRICE": 5,
    "MARKET_PEER_PRICE_FIRST": 44,
    "MARKET_SH_CONVERT_5_LIMIT": 43,
    "MARKET_SZ_CONVERT_5_CANCEL": 47,
}
_XC = _xtconstant
CREDIT_OPTYPE_BY_ORDER_TYPE = {
    _XC.CREDIT_FIN_BUY: 27,
    _XC.CREDIT_SLO_SELL: 28,
    _XC.CREDIT_BUY_SECU_REPAY: 29,
    _XC.CREDIT_DIRECT_SECU_REPAY: 30,
    _XC.CREDIT_SELL_SECU_REPAY: 31,
    _XC.CREDIT_DIRECT_CASH_REPAY: 32,
    _XC.CREDIT_FIN_BUY_SPECIAL: 70,
    _XC.CREDIT_SLO_SELL_SPECIAL: 71,
    _XC.CREDIT_BUY_SECU_REPAY_SPECIAL: 72,
    _XC.CREDIT_DIRECT_SECU_REPAY_SPECIAL: 73,
    _XC.CREDIT_SELL_SECU_REPAY_SPECIAL: 74,
    _XC.CREDIT_DIRECT_CASH_REPAY_SPECIAL: 75,
}
_CREDIT_BUY_SIDE = frozenset(
    {_XC.CREDIT_FIN_BUY, _XC.CREDIT_BUY_SECU_REPAY, _XC.CREDIT_FIN_BUY_SPECIAL, _XC.CREDIT_BUY_SECU_REPAY_SPECIAL}
)
_CREDIT_SELL_SIDE = frozenset(
    {
        _XC.CREDIT_SLO_SELL,
        _XC.CREDIT_SELL_SECU_REPAY,
        _XC.CREDIT_DIRECT_SECU_REPAY,
        _XC.CREDIT_SLO_SELL_SPECIAL,
        _XC.CREDIT_SELL_SECU_REPAY_SPECIAL,
        _XC.CREDIT_DIRECT_SECU_REPAY_SPECIAL,
    }
)
FUTURE_OP_TYPES = frozenset(range(0, 16))
ETF_OPTION_OP_TYPES = frozenset(range(50, 60))
PASSTHROUGH_OP_TYPES = FUTURE_OP_TYPES | ETF_OPTION_OP_TYPES
_FUTURE_BUY_SIDE = frozenset({0, 4, 5, 8, 9, 12, 13, 14})
_FUTURE_SELL_SIDE = frozenset({1, 2, 3, 6, 7, 10, 11, 15})
_ETF_OPTION_BUY_SIDE = frozenset({50, 53, 55})
_ETF_OPTION_SELL_SIDE = frozenset({51, 52, 54})
SIDELESS_ORDER_TYPES = frozenset(
    {_XC.CREDIT_DIRECT_CASH_REPAY, _XC.CREDIT_DIRECT_CASH_REPAY_SPECIAL, 56, 57, 58, 59, 80, 81, 82, 83}
)
CONVERTIBLE_CONVERT_STOCK = 80
CONVERTIBLE_SELL_BACK_STOCK = 81
CONVERTIBLE_CONVERT_CREDIT = 82
CONVERTIBLE_SELL_BACK_CREDIT = 83
CONVERTIBLE_OP_TYPES = frozenset({80, 81, 82, 83})
SIDELESS_DEFAULT_ACTION = "SELL"
PASSTHROUGH_ACCOUNT_TYPES = frozenset({"FUTURE", "STOCK_OPTION"})
_ORDER_DATE_FIELDS = ("m_strInsertDate", "m_strOrderDate", "insert_date", "order_date")
_ORDER_TIME_FIELDS = ("m_strInsertTime", "m_strOrderTime", "insert_time", "order_time")
_missing_order_time_reported = []


def _account_type_codes():
    """Name -> xtconstant account-type code."""
    codes = {}
    table = getattr(_xtconstant, "ACCOUNT_TYPE_DICT", None)
    if isinstance(table, dict):
        for code, name in table.items():
            try:
                codes[str(name).strip().upper()] = int(code)
            except (TypeError, ValueError):
                continue
    for attribute in dir(_xtconstant):
        if not attribute.endswith("_ACCOUNT"):
            continue
        value = getattr(_xtconstant, attribute)
        if isinstance(value, int) and (not isinstance(value, bool)):
            codes.setdefault(attribute[: -len("_ACCOUNT")], value)
    security = getattr(_xtconstant, "SECURITY_ACCOUNT", 2)
    codes.setdefault("STOCK", security)
    codes.setdefault("SECURITY", security)
    return codes


def convertible_optype_of(order_type):
    """可转债转股/回售的 passorder opType，不是则 None。"""
    try:
        value = int(order_type)
    except (TypeError, ValueError):
        return None
    return value if value in CONVERTIBLE_OP_TYPES else None


def convertible_optype_for(action, account_type):
    """opType for ``action`` ("convert" / "sell_back") on an account type."""
    credit = str(account_type or "").strip().upper() == "CREDIT"
    if str(action or "").strip().lower() in ("convert", "转股"):
        return CONVERTIBLE_CONVERT_CREDIT if credit else CONVERTIBLE_CONVERT_STOCK
    if str(action or "").strip().lower() in ("sell_back", "sellback", "回售"):
        return CONVERTIBLE_SELL_BACK_CREDIT if credit else CONVERTIBLE_SELL_BACK_STOCK
    raise ValueError("convertible action must be 'convert' or 'sell_back', got %r" % (action,))


def is_sideless_order_type(order_type):
    """True for order_types that have no buy/sell side (直接还款, 行权, 锁定/解锁)."""
    try:
        return int(order_type) in SIDELESS_ORDER_TYPES
    except (TypeError, ValueError):
        return False


def passthrough_optype_of(order_type):
    """原样送进 passorder 的期货/期权 opType，不是则 None。"""
    try:
        value = int(order_type)
    except (TypeError, ValueError):
        return None
    return value if value in PASSTHROUGH_OP_TYPES else None


def passthrough_action_of(order_type):
    """期货/期权 opType 的买卖方向；没有方向（行权、锁定）则 None。"""
    try:
        value = int(order_type)
    except (TypeError, ValueError):
        return None
    if value in _FUTURE_BUY_SIDE or value in _ETF_OPTION_BUY_SIDE:
        return "BUY"
    if value in _FUTURE_SELL_SIDE or value in _ETF_OPTION_SELL_SIDE:
        return "SELL"
    return None


def credit_action_of(order_type):
    """BUY / SELL for a credit order_type, or None if it is not one."""
    try:
        value = int(order_type)
    except (TypeError, ValueError):
        return None
    if value in _CREDIT_BUY_SIDE:
        return "BUY"
    if value in _CREDIT_SELL_SIDE:
        return "SELL"
    return None


def credit_optype_of(order_type):
    """passorder opType for a MiniQMT credit order_type, or None."""
    try:
        return CREDIT_OPTYPE_BY_ORDER_TYPE.get(int(order_type))
    except (TypeError, ValueError):
        return None


def _action_from_offset_flag(offset_flag, op_type=None, account_type=None, direction=None):
    """BUY/SELL for a normalized query row, from m_nOffsetFlag or m_nOpType."""
    if account_type and str(account_type).upper() in PASSTHROUGH_ACCOUNT_TYPES:
        if str(direction) in {"48", "49"}:
            return "BUY" if str(direction) == "48" else "SELL"
        action = passthrough_action_of(op_type)
        if action is not None:
            return action
        return ""
    return "BUY" if int(offset_flag or 0) == 48 else "SELL"


def _price_type_value(value, default):
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        text = str(value).strip().upper()
        return int(PRICE_TYPE_ALIASES.get(text, default))
