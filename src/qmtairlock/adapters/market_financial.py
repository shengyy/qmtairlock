"""Financial table and field translation through QMT's own context."""

_NATIVE_XTDATA = None
_NATIVE_XTDATA_UNAVAILABLE = object()
_FINANCIAL_TABLE_MAP = {
    "Balance": "ASHAREBALANCESHEET",
    "Income": "ASHAREINCOME",
    "CashFlow": "ASHARECASHFLOW",
    "Capital": "CAPITALSTRUCTURE",
    "PershareIndex": "PERSHAREINDEX",
    "Top10Holder": "TOP10HOLDER",
    "Top10FlowHolder": "TOP10FLOWHOLDER",
    "HolderNum": "SHAREHOLDER",
}
_FINANCIAL_TABLE_FIELDS = {
    "ASHAREBALANCESHEET": [
        "m_timetag",
        "m_anntime",
        "cash_equivalents",
        "bill_receivable",
        "account_receivable",
        "advance_payment",
        "other_receivable",
        "other_current_assets",
        "total_current_assets",
        "inventories",
        "constru_in_process",
        "construction_materials",
        "long_deferred_expense",
        "total_non_current_assets",
        "int_rcv",
        "fin_assets_avail_for_sale",
        "held_to_mty_invest",
        "long_term_eqy_invest",
        "fix_assets",
        "intang_assets",
        "deferred_tax_assets",
        "tot_assets",
        "goodwill",
        "shortterm_loan",
        "dividend_payable",
        "other_payable",
        "non_current_liability_in_one_year",
        "other_current_liability",
        "longterm_account_payable",
        "accounts_payable",
        "advance_peceipts",
        "total_current_liability",
        "notes_payable",
        "long_term_loans",
        "grants_received",
        "other_non_current_liabilities",
        "non_current_liabilities",
        "specific_reserves",
        "tradable_fin_liab",
        "empl_ben_payable",
        "taxes_surcharges_payable",
        "int_payable",
        "bonds_payable",
        "deferred_tax_liab",
        "tot_liab",
        "cap_stk",
        "cap_rsrv",
        "surplus_rsrv",
        "undistributed_profit",
        "tot_shrhldr_eqy_excl_min_int",
        "minority_int",
        "tot_liab_shrhldr_eqy",
        "total_equity",
    ],
    "ASHAREINCOME": [
        "m_timetag",
        "m_anntime",
        "revenue",
        "total_operating_cost",
        "revenue_inc",
        "total_expense",
        "less_taxes_surcharges_ops",
        "sale_expense",
        "less_gerl_admin_exp",
        "financial_expense",
        "less_impair_loss_assets",
        "change_income_fair_value",
        "plus_net_invest_inc",
        "incl_inc_invest_assoc_jv_entp",
        "oper_profit",
        "plus_non_oper_rev",
        "less_non_oper_exp",
        "tot_profit",
        "inc_tax",
        "net_profit_incl_min_int_inc",
        "net_profit_excl_min_int_inc",
        "total_income",
        "total_income_minority",
        "earned_premium",
    ],
    "ASHARECASHFLOW": [
        "m_timetag",
        "m_anntime",
        "goods_sale_and_service_render_cash",
        "tax_levy_refund",
        "other_cash_recp_ral_oper_act",
        "stot_cash_inflows_oper_act",
        "goods_and_services_cash_paid",
        "cash_pay_beh_empl",
        "pay_all_typ_tax",
        "other_cash_pay_ral_oper_act",
        "stot_cash_outflows_oper_act",
        "net_cash_flows_oper_act",
        "cash_recp_return_invest",
        "net_cash_recp_disp_fiolta",
        "stot_cash_inflows_inv_act",
        "cash_paid_invest",
        "cash_pay_acq_const_fiolta",
        "other_cash_pay_ral_inv_act",
        "stot_cash_outflows_inv_act",
        "net_cash_flows_inv_act",
        "cash_recp_cap_contrib",
        "cash_recp_borrow",
        "other_cash_recp_ral_fnc_act",
        "stot_cash_inflows_fnc_act",
        "cash_prepay_amt_borr",
        "cash_pay_dist_dpcp_int_exp",
        "other_cash_pay_ral_fnc_act",
        "stot_cash_outflows_fnc_act",
        "net_cash_flows_fnc_act",
        "eff_fx_flu_cash",
        "net_incr_cash_cash_equ",
        "net_cash_deal_subcompany",
        "cash_from_mino_s_invest_sub",
        "fix_intan_other_asset_dispo_cash_payment",
    ],
    "CAPITALSTRUCTURE": [
        "m_timetag",
        "m_anntime",
        "total_capital",
        "circulating_capital",
        "free_float_capital",
        "restrict_circulating_capital",
    ],
    "PERSHAREINDEX": [
        "m_timetag",
        "m_anntime",
        "m_quarter",
        "s_fa_ocfps",
        "s_fa_bps",
        "s_fa_eps_basic",
        "s_fa_eps_diluted",
        "s_fa_undistributedps",
        "s_fa_surpluscapitalps",
        "adjusted_earnings_per_share",
        "du_return_on_equity",
        "sales_gross_profit",
        "inc_revenue_rate",
        "du_profit_rate",
        "inc_net_profit_rate",
        "adjusted_net_profit_rate",
        "inc_total_revenue_annual",
        "inc_net_profit_to_shareholders_annual",
        "adjusted_profit_to_profit_annual",
        "equity_roe",
        "net_roe",
        "total_roe",
        "gross_profit",
        "net_profit",
        "actual_tax_rate",
        "pre_pay_operate_income",
        "sales_cash_flow",
        "gear_ratio",
        "inventory_turnover",
        "s_fa_fcfeps",
        "s_fa_retainedps",
        "s_fa_fcffps",
        "s_fa_ebitps",
        "s_fa_cfps",
        "s_fa_grps",
        "s_fa_surplusreserveps",
        "s_fa_orps",
        "inc_revenue",
        "inc_gross_profit",
        "inc_profit_before_tax",
        "du_profit",
        "inc_net_profit",
        "adjusted_net_profit",
    ],
    "TOP10HOLDER": ["declareDate", "endDate", "name", "type", "quantity", "reason", "ratio", "nature", "rank"],
    "TOP10FLOWHOLDER": ["declareDate", "endDate", "name", "type", "quantity", "reason", "ratio", "nature", "rank"],
    "SHAREHOLDER": [
        "declareDate",
        "endDate",
        "shareholder",
        "shareholderA",
        "shareholderB",
        "shareholderH",
        "shareholderFloat",
        "shareholderOther",
    ],
}


def _translate_financial_fields(table_list):
    """Translate MiniQMT table names to Big QMT's dotted fieldList."""
    out = []
    for item in table_list or []:
        name = str(item or "").strip()
        if not name:
            continue
        if "." in name:
            head, _, field = name.partition(".")
            big = _FINANCIAL_TABLE_MAP.get(head, head)
            out.append("%s.%s" % (big, field))
            continue
        big = _FINANCIAL_TABLE_MAP.get(name, name)
        if big in _FINANCIAL_TABLE_FIELDS:
            for field in _FINANCIAL_TABLE_FIELDS[big]:
                out.append("%s.%s" % (big, field))
            continue
        out.append(name)
    return out


class MarketFinancial:
    def __init__(self, native):
        self.native = native
        self.context_info = native.context_info
        self.qmt_api = native.qmt_api

    def get_financial_data(self, stock_list, table_list=None, start_time="", end_time="", report_type="report_time"):
        return self.native.call(
            "get_financial_data", _translate_financial_fields(table_list), stock_list, start_time, end_time, report_type
        )

    def download_financial_data(self, stock_list, table_list=None, start_time="", end_time="", incrementally=None):
        kwargs = {
            "stock_list": stock_list,
            "table_list": table_list or [],
            "start_time": start_time,
            "end_time": end_time,
        }
        if incrementally is not None:
            kwargs["incrementally"] = incrementally

        def _via_context():
            return self.native.call("download_financial_data", **kwargs)

        return _via_context()

    def download_financial_data2(self, stock_list, table_list=None, start_time="", end_time=""):

        def _via_context():
            return self.native.call("download_financial_data2", stock_list, table_list or [], start_time, end_time)

        return _via_context()

    def get_raw_financial_data(
        self, field_list, stock_list, start_time, end_time, report_type="report_time", data_type="dict"
    ):
        return self.native.call(
            "get_raw_financial_data", field_list, stock_list, start_time, end_time, report_type, data_type
        )
