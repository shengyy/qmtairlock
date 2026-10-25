"""Client return objects and account/order-type conversions."""

import time

from .constants import (
    CREDIT_BUY,
    CREDIT_BUY_SECU_REPAY,
    CREDIT_FIN_BUY,
    CREDIT_SELL,
    CREDIT_SELL_SECU_REPAY,
    CREDIT_SLO_SELL,
    STOCK_BUY,
    STOCK_SELL,
)

_CREDIT_ORDER_TYPE_BY_OP = {
    27: 27,
    28: 28,
    29: 29,
    30: 30,
    31: 31,
    32: 32,
    33: 23,
    34: 24,
    70: 40,
    71: 41,
    72: 42,
    73: 43,
    74: 44,
    75: 45,
    80: 80,
    81: 81,
    82: 82,
    83: 83,
}
_CREDIT_ORDER_TYPE_BY_ENTRUST = {
    (54, True): 27,
    (54, False): 31,
    (55, True): 29,
    (55, False): 28,
    (57, True): 23,
    (57, False): 24,
}
_CREDIT_SPECIAL_UPGRADE = {27: 40, 28: 41, 29: 42, 31: 44, 32: 45}
PARTIAL_MARKER_ATTR = "bigqmt_partial"
_partial_warned = set()


class CompatObject:
    """Small attribute object matching xtquant's object-style returns."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        items = ", ".join(("%s=%r" % (key, value) for key, value in sorted(self.__dict__.items())))
        return "%s(%s)" % (self.__class__.__name__, items)


class CompatRow(dict):
    """A dict that also answers attribute access, keys untouched."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _as_compat_row(row):
    """Wrap a native-field dict for attribute access; pass anything else through."""
    return CompatRow(row) if isinstance(row, dict) else row


def _market_of(stock_code):
    """``XtCancelError.market`` -- xtconstant SH_MARKET (0) / SZ_MARKET (1)."""
    suffix = str(stock_code or "").rsplit(".", 1)[-1].upper()
    if suffix == "SH":
        return 0
    if suffix == "SZ":
        return 1
    return -1


def _account_type_param(account):
    """The type name a StockAccount declares, "" for a bare id string."""
    if account is None or isinstance(account, (str, dict)):
        return ""
    return _account_type_name(getattr(account, "account_type", None))


def _with_account_type(params, account):
    """``params`` plus the account's declared type, when it declares one."""
    name = _account_type_param(account)
    if name:
        params["account_type"] = name
    return params


def _account_id(account, fallback=""):
    if account is None:
        return str(fallback or "")
    if isinstance(account, str):
        return account
    for name in ("account_id", "m_strAccountID", "id"):
        value = getattr(account, name, None)
        if value:
            return str(value)
    if isinstance(account, dict):
        return str(account.get("account_id") or account.get("id") or fallback or "")
    return str(fallback or "")


def _action_to_order_type(action):
    text = str(action or "").upper()
    if text in ("BUY", str(STOCK_BUY)):
        return STOCK_BUY
    if text in ("SELL", str(STOCK_SELL)):
        return STOCK_SELL
    return 0


def _action_of_row(row):
    """BUY/SELL string for a queried order/trade object (轮询事件用)."""
    offset = _safe_int(getattr(row, "offset_flag", None), -1)
    if offset == 48:
        return "BUY"
    if offset == 49:
        return "SELL"
    order_type = _safe_int(getattr(row, "order_type", None), 0)
    if order_type in (STOCK_BUY, CREDIT_BUY, CREDIT_FIN_BUY, CREDIT_BUY_SECU_REPAY):
        return "BUY"
    if order_type in (STOCK_SELL, CREDIT_SELL, CREDIT_SLO_SELL, CREDIT_SELL_SECU_REPAY):
        return "SELL"
    return ""


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_unix_seconds(value, default=0):
    """Normalize a trade/order time into Unix seconds (MiniQMT semantics)."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y%m%d%H%M%S"):
        try:
            return int(time.mktime(time.strptime(text, fmt)))
        except ValueError:
            continue
    return default


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _credit_order_type_from_op(op_type, fallback):
    """The MiniQMT order_type for a row's native opType, else ``fallback``."""
    try:
        value = int(op_type)
    except (TypeError, ValueError):
        return fallback
    return _CREDIT_ORDER_TYPE_BY_OP.get(value, fallback)


def _credit_order_type_from_entrust(entrust_type, offset_flag, opt_name, fallback):
    """The MiniQMT order_type from m_eEntrustType + side, else ``fallback``."""
    try:
        entrust = int(entrust_type)
    except (TypeError, ValueError):
        return fallback
    try:
        side = int(offset_flag)
    except (TypeError, ValueError):
        return fallback
    if side == 48:
        is_buy = True
    elif side == 49:
        is_buy = False
    else:
        return fallback
    mapped = _CREDIT_ORDER_TYPE_BY_ENTRUST.get((entrust, is_buy))
    if mapped is None:
        return fallback
    if "专项" in str(opt_name or ""):
        mapped = _CREDIT_SPECIAL_UPGRADE.get(mapped, mapped)
    return mapped


def _credit_order_type_for_row(item, fallback):
    """Credit order_type for a snapshot dict: entrust first, op second."""
    order_type = _credit_order_type_from_entrust(
        item.get("entrust_type"), item.get("offset_flag", item.get("direction")), item.get("opt_name"), None
    )
    if order_type is not None:
        return order_type
    return _credit_order_type_from_op(item.get("op_type"), fallback)


def _account_type_name(value):
    """The NAME of an account type, whatever form it arrives in."""
    text = str("" if value is None else value).strip()
    if not text:
        return ""
    if text.isdigit():
        try:
            from .constants import ACCOUNT_TYPE_DICT

            return str(ACCOUNT_TYPE_DICT.get(int(text), "")).strip().upper()
        except Exception:
            return ""
    return text.upper()


def _account_type_code(value):
    """The xtconstant NUMBER for an account type, whatever form it arrives in."""
    text = str("" if value is None else value).strip()
    if not text:
        return 0
    try:
        return int(text)
    except (TypeError, ValueError):
        pass
    upper = text.upper()
    try:
        from . import constants as xtconstant
    except Exception:
        return 0
    table = getattr(xtconstant, "ACCOUNT_TYPE_DICT", None)
    if isinstance(table, dict):
        for code, name in table.items():
            if str(name).strip().upper() == upper:
                try:
                    return int(code)
                except (TypeError, ValueError):
                    break
    for attribute in ("%s_ACCOUNT" % upper, "SECURITY_ACCOUNT" if upper == "STOCK" else ""):
        if not attribute:
            continue
        code = getattr(xtconstant, attribute, None)
        if isinstance(code, int) and (not isinstance(code, bool)):
            return int(code)
    return 0


def _normalize_code_for_filter(code):
    text = str(code or "").strip().upper()
    if "." not in text:
        return text
    return text.split(".", 1)[0]


def _is_hs_a_share(code):
    text = str(code or "").strip().upper()
    pure = _normalize_code_for_filter(text)
    if not (len(pure) == 6 and pure.isdigit()):
        return False
    if text.endswith(".SH"):
        return pure.startswith(("600", "601", "603", "605", "688", "689"))
    if text.endswith(".SZ"):
        return pure.startswith(("000", "001", "002", "003", "300", "301"))
    return pure.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689"))


def _full_a_share_code(code):
    """Ensure a callback stock_code carries its exchange suffix."""
    text = str(code or "").strip().upper()
    if "." in text or not (len(text) == 6 and text.isdigit()):
        return text
    if text.startswith(("600", "601", "603", "605", "688", "689")):
        return text + ".SH"
    if text.startswith(("000", "001", "002", "003", "300", "301")):
        return text + ".SZ"
    return text
