"""Built-in QMT formula calls through ContextInfo and captured native functions."""


class MarketFormulas:
    def __init__(self, native):
        self.native = native
        self.context_info = native.context_info
        self.qmt_api = native.qmt_api

    def call_formula(
        self,
        formula_name,
        stock_code,
        period,
        start_time="",
        end_time="",
        count=-1,
        dividend_type=None,
        extend_param=None,
    ):
        return self.native.call_global_first(
            "call_formula",
            formula_name,
            stock_code,
            period,
            start_time,
            end_time,
            count,
            dividend_type,
            extend_param or {},
        )

    def subscribe_formula(
        self,
        formula_name,
        stock_code,
        period,
        start_time="",
        end_time="",
        count=-1,
        dividend_type=None,
        extend_param=None,
    ):
        return self.native.call_global_first(
            "subscribe_formula",
            formula_name,
            stock_code,
            period,
            start_time,
            end_time,
            count,
            dividend_type,
            extend_param or {},
        )

    def unsubscribe_formula(self, request_id):
        return self.native.call_global_first("unsubscribe_formula", request_id)

    def get_formula_result(self, request_id, start_time="", end_time="", count=-1, timeout_second=-1):
        return self.native.call_global_first(
            "get_formula_result", request_id, start_time, end_time, count, timeout_second
        )

    def gen_factor_index(
        self, data_name, formula_name, vars, sector_list, start_time="", end_time="", period="1d", dividend_type="none"
    ):
        return self.native.call_global_first(
            "gen_factor_index", data_name, formula_name, vars, sector_list, start_time, end_time, period, dividend_type
        )
