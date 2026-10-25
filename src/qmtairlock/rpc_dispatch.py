"""RPC routing, bound-account checks and hard main-thread method boundaries."""

from .account_scope import AccountBinding, request_account_type
from .rpc_account_handlers import AccountHandlers
from .rpc_credit import CreditHandlers
from .rpc_native import NativeQueries
from .rpc_trade_handlers import TradeHandlers
from .version import __version__

ORDER_METHODS = frozenset({"submit_order", "submit_orders_batch", "cancel_order", "cancel_orders_batch", "passorder"})
TRADE_READ_METHODS = frozenset(
    {
        "query_stock_positions",
        "get_positions",
        "query_stock_position",
        "get_position_statistics",
        "get_asset",
        "query_orders",
        "query_trades",
        "query_execution_snapshot",
        "describe_trade_detail_fields",
    }
)
METHOD_ALIASES = {
    "get_full_tick": "get_ticks",
    "get_instrument_detail": "get_instrument",
    "get_instrumentdetail": "get_instrument",
    "getDividFactors": "get_divid_factors",
    "query_stock_asset": "get_asset",
    "query_position_statistics": "get_position_statistics",
    "query_stock_orders": "query_orders",
    "query_stock_trades": "query_trades",
    "order_stock": "submit_order",
    "order_stock_async": "submit_order",
    "order_stock_batch": "submit_orders_batch",
    "cancel_order_stock": "cancel_order",
    "cancel_order_stock_sysid": "cancel_order",
    "cancel_order_stock_batch": "cancel_orders_batch",
}


def canonical_method(method):
    return METHOD_ALIASES.get(method, method)


def native_routes(owner):
    return {name[len("_handle_") :]: getattr(owner, name) for name in dir(type(owner)) if name.startswith("_handle_")}


LISTENER_DEFERRED_METHODS = frozenset(
    TRADE_READ_METHODS
    | ORDER_METHODS
    | {
        name[len("_handle_") :]
        for cls in (AccountHandlers, CreditHandlers)
        for name in dir(cls)
        if name.startswith("_handle_")
    }
)


class BigQmtRpcHandlers:
    def __init__(
        self,
        account_id,
        market_data=None,
        position_provider=None,
        order_gateway=None,
        order_queries=None,
        allow_order_methods=False,
        qmt_api=None,
        account_types=("STOCK",),
        order_settle_timeout_seconds=3.0,
        default_strategy_name="qmtairlock",
    ):
        self.binding = AccountBinding(account_id, account_types)
        self.account_id = self.binding.account_id
        if type(allow_order_methods) is not bool:
            raise ValueError("allow_order_methods must be a boolean")
        self.allow_order_methods = allow_order_methods
        self.market_data = market_data
        self.order_queries = order_queries
        context = getattr(market_data, "context_info", None)
        api = dict(qmt_api or {})
        if order_gateway is not None and "get_trade_detail_data" not in api:
            api["get_trade_detail_data"] = order_gateway.get_trade_detail_data
        self.native = NativeQueries(self.binding, context, api)
        self.credit = CreditHandlers(self.native)
        self.accounts = AccountHandlers(self.native)
        self.trade = TradeHandlers(
            self.binding,
            order_gateway,
            order_queries,
            position_provider,
            order_settle_timeout_seconds,
            default_strategy_name,
        )
        self.routes = native_routes(self.credit)
        self.routes.update(native_routes(self.accounts))
        self.routes.update({name: getattr(self.trade, name) for name in TRADE_READ_METHODS | ORDER_METHODS})
        if market_data is not None:
            self.routes.update(market_data.routes)
        self.routes["ping"] = self.ping

    @staticmethod
    def _canonical_method(method):
        return canonical_method(method)

    def ping(self, params):
        return {
            "pong": True,
            "account_id": self.account_id,
            "account_type": self.binding.account_types[0],
            "account_types": list(self.binding.account_types),
            "version": __version__,
            "allow_order_methods": self.allow_order_methods,
            "rpc_revision": "qmtairlock-v1",
        }

    def handle(self, method, params=None):
        name = canonical_method(str(method))
        params = dict(params or {})
        if name in native_routes(self.credit):
            params.setdefault("account_type", "CREDIT")
        kind = self.binding.validate(params)
        if name in ORDER_METHODS and not self.allow_order_methods:
            raise PermissionError("order RPC methods are disabled")
        handler = self.routes.get(name)
        if handler is None:
            raise ValueError("unsupported RPC method: %s" % name)
        with request_account_type(kind):
            return handler(params)
