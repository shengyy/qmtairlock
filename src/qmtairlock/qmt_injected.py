"""Capture the terminal globals from the mounted entry namespace."""

_EXTRA_QMT_GLOBAL_FUNCS = (
    "get_history_trade_detail_data",
    "get_value_by_order_id",
    "get_last_order_id",
    "get_ipo_data",
    "get_new_purchase_limit",
    "get_assure_contract",
    "get_enable_short_contract",
    "get_unclosed_compacts",
    "get_closed_compacts",
    "get_debt_contract",
    "query_credit_account",
    "get_option_subject_position",
    "get_comb_option",
    "get_hkt_exchange_rate",
    "download_history_data",
    "download_history_data2",
    "down_history_data",
    "call_formula",
    "subscribe_formula",
    "unsubscribe_formula",
    "get_formula_result",
    "gen_factor_index",
)
_QMT_INJECTED_GLOBAL_FUNCS = ("passorder", "cancel", "get_trade_detail_data") + _EXTRA_QMT_GLOBAL_FUNCS


def capture_qmt_injected_funcs(namespace):
    """Capture QMT-injected global funcs from a mounted entry's exec namespace."""
    captured = {}
    for name in _QMT_INJECTED_GLOBAL_FUNCS:
        func = (namespace or {}).get(name)
        if callable(func):
            captured[name] = func
    return captured
