"""Instrument, sector, calendar, ETF and exchange metadata through ContextInfo."""

import datetime as _dt

from ..code_utils import normalize_stock_code
from ..logging_setup import get_logger

log = get_logger("market_meta")
MARKET_CODES = {"SH", "SZ", "BJ", "HK"}


class MarketMetadata:
    def __init__(self, native):
        self.native = native
        self.context_info = native.context_info
        self.qmt_api = native.qmt_api

    def get_instrument(self, code):
        return self.native.call("get_instrumentdetail", normalize_stock_code(code)) or {}

    def get_instrument_type(self, code, variety_list=None):
        return self.native.call("get_instrument_type", code, variety_list)

    def get_stock_type(self, stock_code, variety_list=None):
        return self.native.first_supported(
            [("get_stock_type", (stock_code, variety_list), {}), ("get_stock_type", (stock_code,), {})]
        )

    def get_stock_list_in_sector(self, sector_name, real_timetag=-1):
        shapes = [
            ("get_stock_list_in_sector", (sector_name, real_timetag), {}),
            ("get_stock_list_in_sector", (sector_name,), {}),
        ]
        data = self.native.first_supported(shapes)
        return data or []

    def get_trading_dates(self, market, start_time="", end_time="", count=-1):
        context_stock = {"SH": "000001.SH", "SZ": "399001.SZ"}.get(str(market).upper(), market)
        return self.native.call("get_trading_dates", context_stock, start_time, end_time, count)

    def get_holidays(self):
        return self.native.call("get_holidays")

    def download_holiday_data(self, incrementally=True):
        return self.native.first_supported(
            [("download_holiday_data", (incrementally,), {}), ("download_holiday_data", (), {})]
        )

    def get_ipo_info(self, start_time="", end_time=""):
        return self.native.call("get_ipo_info", start_time, end_time)

    def get_etf_info(self):
        return self.native.call("get_etf_info")

    def download_etf_info(self):
        return self.native.call("download_etf_info")

    def get_sector_list(self):
        return self.native.call("get_sector_list")

    def get_sector_info(self, sector_name=""):
        return self.native.call("get_sector_info", sector_name)

    def get_markets(self):
        return list(MARKET_CODES)

    def get_market_last_trade_date(self, market):
        dates = self.get_trading_dates(market, "", "", 1)
        return dates[-1] if dates else None

    def get_longhubang(self, stock_list=None, start_time="", end_time="", count=-1):
        return self.native.call("get_longhubang", list(stock_list or []), start_time, end_time, count)

    def get_top10_share_holder(self, stock_list, data_name, start_time, end_time, report_type="report_time"):
        return self.native.call("get_top10_share_holder", stock_list, data_name, start_time, end_time, report_type)

    def get_holder_num(self, stock_list=None, start_time="", end_time="", report_type="report_time"):
        return self.native.call("get_holder_num", list(stock_list or []), start_time, end_time, report_type)

    def get_turnover_rate(self, stock_code=None, start_time="19720101", end_time="22010101"):
        return self.native.call("get_turnover_rate", list(stock_code or []), start_time, end_time)

    def get_industry(self, industry_name):
        return self.native.call("get_industry", industry_name, -1)

    def get_close_price(self, market, stock_code, real_timetag, period=86400000, divid_type=0):
        return self.native.call("get_close_price", market, stock_code, real_timetag, period, divid_type)

    def get_factor_data(self, field_list, stock_list, start_date, end_date):
        return self.native.call("get_factor_data", field_list, stock_list, start_date, end_date)

    def get_his_st_data(self, stock_code):
        return self.native.call("get_his_st_data", stock_code)

    def get_his_index_data(self, stock_code):
        return self.native.call("get_his_index_data", stock_code)

    def get_main_contract(self, code_market):
        return self.native.call("get_main_contract", code_market)

    def get_his_contract_list(self, market):
        return self.native.call("get_his_contract_list", market)

    def get_date_location(self, date):
        return self.native.call("get_date_location", date)

    def get_ETF_list(self, market, stock_code, type_list=None):
        return self.native.call("get_ETF_list", market, stock_code, list(type_list or []))

    def get_north_finance_change(self, period):
        return self.native.call("get_north_finance_change", period)

    def get_hkt_statistics(self, stock_code):
        return self.native.call("get_hkt_statistics", stock_code)

    def get_hkt_details(self, stock_code):
        return self.native.call("get_hkt_details", stock_code)

    def get_stock_name(self, stock):
        return self.native.call("get_stock_name", stock)

    def get_last_close(self, stock):
        return self.native.call("get_last_close", stock)

    def get_last_volume(self, stock):
        return self.native.call("get_last_volume", stock)

    def get_open_date(self, stock):
        return self.native.call("get_open_date", stock)

    def get_contract_expire_date(self, stock):
        return self.native.call("get_contract_expire_date", stock)

    def get_contract_multiplier(self, stockcode):
        return self.native.call("get_contract_multiplier", stockcode)

    def get_float_caps(self, stockcode):
        return self.native.call("get_float_caps", stockcode)

    def get_total_share(self, stockcode):
        return self.native.call("get_total_share", stockcode)

    def get_turn_over_rate(self, stockcode):
        return self.native.call("get_turn_over_rate", stockcode)

    def get_weight_in_index(self, mtkindexcode, stockcode):
        return self.native.call("get_weight_in_index", mtkindexcode, stockcode)

    def get_svol(self, stock):
        return self.native.call("get_svol", stock)

    def get_bvol(self, stock):
        return self.native.call("get_bvol", stock)

    def get_risk_free_rate(self, index=-1):
        return self.native.call("get_risk_free_rate", index)

    def get_l2_quote(self, field_list=None, stock_code="", start_time="", end_time="", count=-1):
        return self.native.call("get_l2_quote", field_list or [], stock_code, start_time, end_time, count)

    def get_l2_order(self, field_list=None, stock_code="", start_time="", end_time="", count=-1):
        return self.native.call("get_l2_order", field_list or [], stock_code, start_time, end_time, count)

    def get_l2_transaction(self, field_list=None, stock_code="", start_time="", end_time="", count=-1):
        return self.native.call("get_l2_transaction", field_list or [], stock_code, start_time, end_time, count)

    def get_index_weight(self, index_code):
        return self.native.call("get_index_weight", index_code)

    def get_trading_calendar(self, market, start_time="", end_time="", tradetimes=False):
        return self.native.call("get_trading_calendar", market, start_time, end_time, tradetimes)

    def get_trade_times(self, stockcode):
        return self.native.call("get_trade_times", stockcode)

    def get_cb_info(self, stockcode):
        return self.native.call("get_cb_info", stockcode)

    def is_stock_type(self, stock, tag):
        return self.native.call("is_stock_type", stock, tag)

    def download_cb_data(self):
        return self.native.call("download_cb_data")

    def download_history_contracts(self):
        return self.native.call("download_history_contracts")

    def download_index_weight(self):
        return self.native.call("download_index_weight")

    def download_sector_data(self):
        return self.native.call("download_sector_data")

    def download_his_st_data(self, incrementally=True):
        return self.native.call("download_his_st_data", incrementally)

    @staticmethod
    def datetime_to_timetag(datetime_str, format="%Y%m%d%H%M%S"):
        try:
            dt = _dt.datetime.strptime(str(datetime_str), format)
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

    @staticmethod
    def timetag_to_datetime(timetag, format):
        try:
            dt = _dt.datetime.fromtimestamp(int(timetag) / 1000.0)
            return dt.strftime(format)
        except Exception:
            return ""
