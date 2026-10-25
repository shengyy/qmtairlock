"""Native option chain, historical chain and contract metadata queries."""

from ..logging_setup import get_logger

log = get_logger("market_options")


class MarketOptions:
    def __init__(self, native):
        self.native = native
        self.context_info = native.context_info
        self.qmt_api = native.qmt_api

    def get_option_list(self, undl_code, dedate, opttype="", isavailavle=False):
        return self.native.call("get_option_list", undl_code, dedate, opttype, isavailavle)

    def get_his_option_list(self, undl_code, dedate):
        return self.native.call("get_his_option_list", undl_code, dedate)

    def get_his_option_list_batch(self, undl_code, start_time="", end_time=""):
        return self.native.call("get_his_option_list_batch", undl_code, start_time, end_time)

    def get_option_iv(self, opt_code):
        return self.native.call("get_option_iv", opt_code)

    def get_option_detail_data(self, stockcode):
        raw = self.native.call("get_option_detail_data", stockcode)
        if not raw:
            return raw
        detail = dict(raw)
        if not detail.get("InstrumentName"):
            try:
                instrument = self.native.metadata.get_instrument(stockcode)
            except Exception:
                instrument = {}
            name = instrument.get("InstrumentName") if instrument else None
            if name:
                detail["InstrumentName"] = name
        underlying_code = detail.get("OptUndlCode")
        underlying_market = detail.get("OptUndlMarket")
        if not detail.get("OptUndlCodeFull") and underlying_code and underlying_market:
            detail["OptUndlCodeFull"] = "%s.%s" % (underlying_code, str(underlying_market).upper())
        if not detail.get("ProductCode"):
            product_id = str(detail.get("ProductID") or "")
            exchange_id = str(detail.get("ExchangeID") or "").upper()
            if product_id.endswith("_o") and underlying_market:
                detail["ProductCode"] = "%s.%s" % (product_id[:-2], str(underlying_market).upper())
            elif exchange_id in ("ZF", "CZCE") and product_id and underlying_market:
                detail["ProductCode"] = "%s.%s" % (product_id[:-1], str(underlying_market).upper())
            elif detail.get("OptUndlCodeFull"):
                detail["ProductCode"] = detail["OptUndlCodeFull"]
        return detail

    def get_option_detail_data_batch(self, stockcodes):
        """Return option details for many contracts in one bridge request."""
        if isinstance(stockcodes, (str, bytes)) or not isinstance(stockcodes, (list, tuple)):
            raise ValueError("stockcodes must be a list or tuple")
        details = {}
        for value in stockcodes:
            code = str(value or "").strip()
            if not code or code in details:
                continue
            try:
                details[code] = self.get_option_detail_data(code) or {}
            except Exception as exc:
                log.warning("get_option_detail_data failed for %s: %s", code, exc)
                details[code] = {}
        return details

    def get_option_undl_data(self, undl_code_ref=""):
        return self.native.call("get_option_undl_data", undl_code_ref)

    def get_option_undl(self, opt_code):
        return self.native.call("get_option_undl", opt_code)
