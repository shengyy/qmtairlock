"""Market RPC client and client-only Parquet cache coordination."""

from .data_frames import _divid_factors_frame, _normalize_market_data_frame, _normalize_market_data_result
from .local_cache import LocalMarketCache
from .logging_setup import get_logger

log = get_logger("data_client")


class BigQmtXtData:
    CONTRACT_MULTIPLIER_SENTINEL = 2147483647

    def __init__(self, client):
        self.client = client
        self._cache = None
        from .option_analytics_client import OptionsClient

        self.options = OptionsClient(self)

    def _local_cache(self):
        config = self.client.local_cache_config
        if not config.get("enabled"):
            return None
        if self._cache is None:
            self._cache = LocalMarketCache(config["dir"], fmt=config["format"])
        return self._cache

    def _call(self, method, **params):
        return self.client.call(method, params)

    def get_full_tick(self, code_list, timeout_seconds=None, types=None):
        if not code_list:
            return {}
        params = {"codes": list(code_list)}
        if types is not None:
            params["types"] = list(types)
        return self.client.call("get_full_tick", params, timeout_seconds=timeout_seconds)

    def get_market_data_ex(
        self,
        field_list=None,
        stock_list=None,
        period="1d",
        start_time="",
        end_time="",
        count=-1,
        dividend_type="none",
        fill_data=True,
        chunk_size=100,
        timeout_seconds=None,
        subscribe=False,
    ):
        codes = list(stock_list or [])
        if not codes:
            return {}
        step = int(chunk_size) if chunk_size else len(codes)
        if step < 1:
            raise ValueError("chunk_size must be positive or zero")
        params = dict(
            field_list=list(field_list or []),
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            fill_data=fill_data,
            subscribe=subscribe,
        )
        data, failures = ({}, [])
        for index in range(0, len(codes), step):
            batch = codes[index : index + step]
            try:
                raw = self.client.call(
                    "get_market_data_ex", dict(params, stock_list=batch), timeout_seconds=timeout_seconds
                )
                if not isinstance(raw, dict):
                    raise ValueError("market data must be a code-to-frame mapping")
                data.update(_normalize_market_data_result(raw, field_list=field_list, period=period))
            except Exception as exc:
                failures.append(exc)
                log.warning("market data batch failed: %s", type(exc).__name__)
        if failures and (not data):
            raise failures[0]
        cache = self._local_cache()
        if cache is not None:
            for code, frame in data.items():
                try:
                    cache.write(code, period, frame, dividend_type=dividend_type)
                except Exception as exc:
                    log.warning("Parquet write failed: %s", type(exc).__name__)
        return data

    def get_local_data(
        self,
        field_list=None,
        stock_list=None,
        period="1d",
        start_time="",
        end_time="",
        count=-1,
        dividend_type="none",
        fill_data=True,
    ):
        cache = self._local_cache()
        if cache is None:
            raise ValueError("get_local_data requires an enabled local Parquet cache")
        result = {}
        for code in stock_list or []:
            frame = cache.read(code, period, start_time, end_time, count, dividend_type)
            if frame is not None and len(frame):
                frame = _normalize_market_data_frame(frame, field_list=field_list)
                result[code] = frame[[name for name in field_list if name in frame.columns]] if field_list else frame
        return result

    def download_history_data2(self, stock_list, period, start_time="", end_time="", incrementally=None):
        params = dict(stock_list=list(stock_list), period=period, start_time=start_time, end_time=end_time)
        if incrementally is not None:
            params["incrementally"] = incrementally
        return self.client.call("download_history_data2", params)

    def download_history_data(self, stock_code, period, start_time="", end_time="", incrementally=None):
        return self.download_history_data2([stock_code], period, start_time, end_time, incrementally)

    def get_divid_factors(self, stock_code, start_time="", end_time=""):
        return _divid_factors_frame(
            self._call("get_divid_factors", stock_code=stock_code, start_time=start_time, end_time=end_time)
        )

    def local_cache_stats(self):
        cache = self._local_cache()
        return cache.stats() if cache is not None else {}

    def get_instrument_detail(self, stock_code):
        return self.client.call("get_instrument_detail", {"code": stock_code}) or {}

    def get_instrumentdetail(self, stock_code):
        return self.get_instrument_detail(stock_code)

    def get_instrument_type(self, stock_code, variety_list=None):
        return self._call("get_instrument_type", code=stock_code, variety_list=variety_list)

    def get_stock_type(self, stock_code, variety_list=None):
        return self._call("get_stock_type", stock_code=stock_code, variety_list=variety_list)

    def get_stock_list_in_sector(self, sector_name, real_timetag=-1):
        return self._call("get_stock_list_in_sector", sector_name=sector_name, real_timetag=real_timetag)

    def get_trading_dates(self, market, start_time="", end_time="", count=-1):
        return self._call("get_trading_dates", market=market, start_time=start_time, end_time=end_time, count=count)

    def get_holidays(self):
        return self._call("get_holidays")

    def download_holiday_data(self, incrementally=True):
        return self._call("download_holiday_data", incrementally=incrementally)

    def download_his_st_data(self, incrementally=True):
        return self._call("download_his_st_data", incrementally=incrementally)

    def get_ipo_info(self, start_time="", end_time=""):
        return self._call("get_ipo_info", start_time=start_time, end_time=end_time)

    def get_etf_info(self):
        return self._call("get_etf_info")

    def download_etf_info(self):
        return self._call("download_etf_info")

    def download_sector_data(self):
        return self._call("download_sector_data")

    def download_cb_data(self):
        return self._call("download_cb_data")

    def download_index_weight(self):
        return self._call("download_index_weight")

    def download_history_contracts(self, incrementally=True):
        return self._call("download_history_contracts")

    def get_option_list(self, undl_code, dedate, opttype="", isavailavle=None, available=None):
        if available is not None and isavailavle is not None and (bool(isavailavle) != bool(available)):
            raise ValueError("isavailavle and available must not conflict")
        selected_available = (
            bool(available) if available is not None else bool(isavailavle) if isavailavle is not None else False
        )
        return self._call(
            "get_option_list", undl_code=undl_code, dedate=dedate, opttype=opttype, isavailavle=selected_available
        )

    def get_his_option_list(self, undl_code, dedate):
        return self._call("get_his_option_list", undl_code=undl_code, dedate=dedate)

    def get_his_option_list_batch(self, undl_code, start_time="", end_time=""):
        return self._call("get_his_option_list_batch", undl_code=undl_code, start_time=start_time, end_time=end_time)

    def get_financial_data(self, stock_list, table_list=None, start_time="", end_time="", report_type="report_time"):
        return self._call(
            "get_financial_data",
            stock_list=list(stock_list or []),
            table_list=list(table_list or []),
            start_time=start_time,
            end_time=end_time,
            report_type=report_type,
        )

    def download_financial_data(self, stock_list, table_list=None, start_time="", end_time="", incrementally=None):
        return self._call(
            "download_financial_data",
            stock_list=list(stock_list or []),
            table_list=list(table_list or []),
            start_time=start_time,
            end_time=end_time,
            incrementally=incrementally,
        )

    def download_financial_data2(self, stock_list, table_list=None, start_time="", end_time="", callback=None):
        result = self._call(
            "download_financial_data2",
            stock_list=list(stock_list or []),
            table_list=list(table_list or []),
            start_time=start_time,
            end_time=end_time,
        )
        if callback is not None:
            callback(result)
        return result

    def get_sector_list(self):
        """Sector names, or an error saying the terminal cannot list them."""
        return self._call("get_sector_list")

    def get_sector_info(self, sector_name=""):
        return self._call("get_sector_info", sector_name=sector_name)

    def get_markets(self):
        return self._call("get_markets")

    def get_market_last_trade_date(self, market):
        return self._call("get_market_last_trade_date", market=market)

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
        return self._call(
            "call_formula",
            formula_name=formula_name,
            stock_code=stock_code,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            extend_param=extend_param or {},
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
        callback=None,
    ):
        result = self._call(
            "subscribe_formula",
            formula_name=formula_name,
            stock_code=stock_code,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            extend_param=extend_param or {},
        )
        if callback is not None:
            callback(result)
        return result

    def unsubscribe_formula(self, request_id):
        return self._call("unsubscribe_formula", request_id=request_id)

    def get_formula_result(self, request_id, start_time="", end_time="", count=-1, timeout_second=-1):
        return self._call(
            "get_formula_result",
            request_id=request_id,
            start_time=start_time,
            end_time=end_time,
            count=count,
            timeout_second=timeout_second,
        )

    def gen_factor_index(
        self, data_name, formula_name, vars, sector_list, start_time="", end_time="", period="1d", dividend_type="none"
    ):
        return self._call(
            "gen_factor_index",
            data_name=data_name,
            formula_name=formula_name,
            vars=vars,
            sector_list=list(sector_list or []),
            start_time=start_time,
            end_time=end_time,
            period=period,
            dividend_type=dividend_type,
        )

    def get_longhubang(self, stock_list=None, start_time="", end_time="", count=-1):
        return self._call(
            "get_longhubang", stock_list=list(stock_list or []), start_time=start_time, end_time=end_time, count=count
        )

    def get_top10_share_holder(self, stock_list, data_name, start_time, end_time, report_type="report_time"):
        return self._call(
            "get_top10_share_holder",
            stock_list=list(stock_list or []),
            data_name=data_name,
            start_time=start_time,
            end_time=end_time,
            report_type=report_type,
        )

    def get_holder_num(self, stock_list=None, start_time="", end_time="", report_type="report_time"):
        return self._call(
            "get_holder_num",
            stock_list=list(stock_list or []),
            start_time=start_time,
            end_time=end_time,
            report_type=report_type,
        )

    def get_turnover_rate(self, stock_code=None, start_time="19720101", end_time="22010101"):
        return self._call(
            "get_turnover_rate", stock_code=list(stock_code or []), start_time=start_time, end_time=end_time
        )

    def get_industry(self, industry_name):
        return self._call("get_industry", industry_name=industry_name)

    def get_option_iv(self, opt_code):
        return self._call("get_option_iv", opt_code=opt_code)

    def get_option_detail_data(self, stockcode):
        return self._call("get_option_detail_data", stockcode=stockcode)

    def get_option_detail_data_batch(self, stockcodes, timeout_seconds=300.0):
        """Fetch many option details in one RPC; QMT loops over the codes."""
        return (
            self.client.call(
                "get_option_detail_data_batch", {"stockcodes": list(stockcodes)}, timeout_seconds=timeout_seconds
            )
            or {}
        )

    def get_option_undl_data(self, undl_code_ref=""):
        return self._call("get_option_undl_data", undl_code_ref=undl_code_ref)

    def get_option_undl(self, opt_code):
        return self._call("get_option_undl", opt_code=opt_code)

    def get_raw_financial_data(
        self, field_list, stock_list, start_time, end_time, report_type="report_time", data_type="dict"
    ):
        return self._call(
            "get_raw_financial_data",
            field_list=list(field_list or []),
            stock_list=list(stock_list or []),
            start_time=start_time,
            end_time=end_time,
            report_type=report_type,
            data_type=data_type,
        )

    def get_factor_data(self, field_list, stock_list, start_date, end_date):
        return self._call(
            "get_factor_data",
            field_list=list(field_list or []),
            stock_list=list(stock_list or []),
            start_date=start_date,
            end_date=end_date,
        )

    def get_north_finance_change(self, period):
        return self._call("get_north_finance_change", period=period)

    def get_hkt_statistics(self, stock_code):
        return self._call("get_hkt_statistics", stock_code=stock_code)

    def get_hkt_details(self, stock_code):
        return self._call("get_hkt_details", stock_code=stock_code)

    def get_stock_name(self, stock):
        return self._call("get_stock_name", stock=stock)

    def get_instrument(self, stock_code):
        """RPC 侧的方法名。`get_instrument_detail` / `get_instrumentdetail`"""
        return self.get_instrument_detail(stock_code)

    def get_ticks(self, code_list, timeout_seconds=None, types=None):
        """RPC 侧的方法名；MiniQMT 那边叫 `get_full_tick`，二者等价。"""
        return self.get_full_tick(code_list, timeout_seconds=timeout_seconds, types=types)

    def get_last_close(self, stock):
        """Native previous close."""
        return self._call("get_last_close", stock=stock)

    def get_last_volume(self, stock):
        """最新**流通股本**，不是「昨天的成交量」。"""
        return self._call("get_last_volume", stock=stock)

    def get_open_date(self, stock):
        """上市日期，int yyyymmdd。"""
        return self._call("get_open_date", stock=stock)

    def get_contract_expire_date(self, stock):
        """到期日。**返回字符串**，不是 int。"""
        return self._call("get_contract_expire_date", stock=stock)

    def get_float_caps(self, stockcode):
        """流通**股本**（股数），不是流通市值。"""
        return self._call("get_float_caps", stockcode=stockcode)

    def get_total_share(self, stockcode):
        """Native total shares."""
        return self._call("get_total_share", stockcode=stockcode)

    def get_weight_in_index(self, mtkindexcode, stockcode):
        """某只股票在某指数中的绝对权重，**单位是 %**。"""
        return self._call("get_weight_in_index", mtkindexcode=mtkindexcode, stockcode=stockcode)

    def get_risk_free_rate(self, index=-1):
        """无风险利率（官方说是十年期国债收益率 CGB10Y），单位 %。"""
        return self._call("get_risk_free_rate", index=index)

    def get_svol(self, stock):
        """内盘成交量 —— **盘中窗口量，不是当日累计内盘**。"""
        return self._call("get_svol", stock=stock)

    def get_bvol(self, stock):
        """Native external volume; preserves the terminal sampling window."""
        return self._call("get_bvol", stock=stock)

    def get_turn_over_rate(self, stockcode):
        return self._call("get_turn_over_rate", stockcode=stockcode)

    def get_contract_multiplier(self, stockcode):
        """合约乘数。**答案是哨兵值时报错，不往外递。**"""
        answer = self._call("get_contract_multiplier", stockcode=stockcode)
        try:
            is_sentinel = int(answer) == self.CONTRACT_MULTIPLIER_SENTINEL
        except (TypeError, ValueError):
            is_sentinel = False
        if is_sentinel:
            raise NotImplementedError(
                "get_contract_multiplier(%r) returned the unavailable sentinel %s"
                % (stockcode, self.CONTRACT_MULTIPLIER_SENTINEL)
            )
        return answer

    def get_close_price(self, market, stock_code, real_timetag, period=86400000, divid_type=0):
        return self._call(
            "get_close_price",
            market=market,
            stock_code=stock_code,
            real_timetag=real_timetag,
            period=period,
            divid_type=divid_type,
        )

    def get_main_contract(self, code_market):
        return self._call("get_main_contract", code_market=code_market)

    def get_his_contract_list(self, market):
        return self._call("get_his_contract_list", market=market)

    def get_date_location(self, date):
        return self._call("get_date_location", date=date)

    def get_his_st_data(self, stock_code):
        return self._call("get_his_st_data", stock_code=stock_code)

    def get_his_index_data(self, stock_code):
        return self._call("get_his_index_data", stock_code=stock_code)

    def get_l2_quote(self, field_list=None, stock_code="", start_time="", end_time="", count=-1):
        return self._call(
            "get_l2_quote",
            field_list=list(field_list or []),
            stock_code=stock_code,
            start_time=start_time,
            end_time=end_time,
            count=count,
        )

    def get_l2_order(self, field_list=None, stock_code="", start_time="", end_time="", count=-1):
        return self._call(
            "get_l2_order",
            field_list=list(field_list or []),
            stock_code=stock_code,
            start_time=start_time,
            end_time=end_time,
            count=count,
        )

    def get_l2_transaction(self, field_list=None, stock_code="", start_time="", end_time="", count=-1):
        return self._call(
            "get_l2_transaction",
            field_list=list(field_list or []),
            stock_code=stock_code,
            start_time=start_time,
            end_time=end_time,
            count=count,
        )

    def get_index_weight(self, index_code):
        return self._call("get_index_weight", index_code=index_code)

    def get_trading_calendar(self, market, start_time="", end_time="", tradetimes=False):
        return self._call(
            "get_trading_calendar", market=market, start_time=start_time, end_time=end_time, tradetimes=tradetimes
        )

    def get_trade_times(self, stockcode):
        return self._call("get_trade_times", stockcode=stockcode)

    def get_cb_info(self, stockcode):
        return self._call("get_cb_info", stockcode=stockcode)

    def is_stock_type(self, stock, tag):
        return self._call("is_stock_type", stock=stock, tag=tag)

    @staticmethod
    def datetime_to_timetag(datetime_str, format="%Y%m%d%H%M%S"):
        import datetime as _dt

        try:
            return int(_dt.datetime.strptime(str(datetime_str), format).timestamp() * 1000)
        except Exception:
            return 0

    @staticmethod
    def timetag_to_datetime(timetag, format):
        import datetime as _dt

        try:
            return _dt.datetime.fromtimestamp(int(timetag) / 1000.0).strftime(format)
        except Exception:
            return ""

    @staticmethod
    def timetagToDateTime(timetag, format):
        return BigQmtXtData.timetag_to_datetime(timetag, format)
