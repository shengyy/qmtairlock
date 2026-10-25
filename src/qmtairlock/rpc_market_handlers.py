"""Compose native market domains into the explicit RPC read surface."""

from .adapters.market_bars import MarketBars
from .adapters.market_context import MarketContext
from .adapters.market_dividends import MarketDividends
from .adapters.market_financial import MarketFinancial
from .adapters.market_formulas import MarketFormulas
from .adapters.market_meta import MarketMetadata
from .adapters.market_options import MarketOptions
from .adapters.market_ticks import MarketTicks


class MarketHandlers:
    def __init__(self, context_info, qmt_api=None, full_tick_warmup_wait_seconds=0):
        self.context_info = context_info
        native = MarketContext(context_info, qmt_api)
        self.bars = MarketBars(native)
        native.bars = self.bars
        self.metadata = MarketMetadata(native)
        native.metadata = self.metadata
        self.ticks = MarketTicks(native)
        self.ticks.full_tick_warmup_wait_seconds = full_tick_warmup_wait_seconds
        self.dividends = MarketDividends(native)
        self.financial = MarketFinancial(native)
        self.options = MarketOptions(native)
        self.formulas = MarketFormulas(native)
        self.routes = {}
        for owner in (
            self.bars,
            self.metadata,
            self.ticks,
            self.dividends,
            self.financial,
            self.options,
            self.formulas,
        ):
            for name in vars(type(owner)):
                if name.startswith(
                    (
                        "get_",
                        "download_",
                        "call_",
                        "subscribe_formula",
                        "unsubscribe_formula",
                        "gen_factor_index",
                        "is_stock_type",
                    )
                ):
                    self.routes[name] = self._handler(name, getattr(owner, name))

    @staticmethod
    def _handler(name, function):
        def call(params):
            arguments = {
                key: value for key, value in params.items() if key not in {"account_id", "account", "account_type"}
            }
            if name == "get_ticks" and "codes" not in arguments:
                arguments["codes"] = arguments.pop("stock_list", [])
            result = function(**arguments)
            if name.startswith("download_") and result is None:
                return True
            return result

        return call

    def close(self):
        self.ticks.close()
