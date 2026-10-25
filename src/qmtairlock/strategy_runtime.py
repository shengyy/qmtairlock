"""QMT lifecycle: native account work on callbacks, heavy market reads on one worker."""

import datetime
import sys

from .adapters.order_gateway import BigQmtOrderGateway
from .adapters.order_queries import OrderQueries
from .adapters.position_bigqmt import BigQmtPositionProvider
from .exec_events import event_account_id, normalize_order_event
from .order_watch import OrderWatchTable
from .rpc_dispatch import BigQmtRpcHandlers
from .rpc_market_handlers import MarketHandlers
from .rpc_service import RpcService
from .transports.pipe_server import NamedPipeServer


class StrategyRuntime:
    def __init__(self, context, account_id, config, qmt_api, transport=None):
        self.context = context
        self.config = dict(config)
        self.account_id = str(account_id or "").strip()
        if not self.account_id:
            raise ValueError("QMT_ACCOUNT_ID must be configured")
        allowed = {
            "account_types",
            "pipe",
            "allow_order_methods",
            "schedule_adjust_interval",
            "max_requests_per_tick",
            "drain_budget_seconds",
            "heavy_codes_threshold",
            "order_settle_timeout_seconds",
            "default_strategy_name",
            "gil_switch_interval_seconds",
        }
        unknown = set(config) - allowed
        if unknown:
            raise ValueError("unknown strategy settings: %s" % sorted(unknown))
        self.market = MarketHandlers(context, qmt_api)
        types = config.get("account_types", ["STOCK"])
        if isinstance(types, str):
            types = [types]
        primary = types[0] if types else "STOCK"
        detail = qmt_api.get("get_trade_detail_data")
        self.queries = OrderQueries(context, detail, self.account_id)
        self.queries.account_type = primary
        gateway = BigQmtOrderGateway(
            context, self.account_id, qmt_api.get("passorder"), qmt_api.get("cancel"), detail, account_type=primary
        )
        positions = BigQmtPositionProvider(detail, account_type=primary)
        self.handlers = BigQmtRpcHandlers(
            self.account_id,
            self.market,
            positions,
            gateway,
            self.queries,
            allow_order_methods=config.get("allow_order_methods", False),
            qmt_api=qmt_api,
            account_types=types,
            order_settle_timeout_seconds=config.get("order_settle_timeout_seconds", 3),
            default_strategy_name=config.get("default_strategy_name", "qmtairlock"),
        )
        # Callback objects may omit the account type. In that case use native
        # ORDER reads rather than mixing ledgers in a multi-type configuration.
        self.watch = OrderWatchTable() if len(self.handlers.binding.account_types) == 1 else None
        transport = transport or NamedPipeServer(account_id=self.account_id, **dict(config.get("pipe") or {}))
        self.service = RpcService(
            self.handlers,
            self.account_id,
            transport,
            heavy_codes_threshold=config.get("heavy_codes_threshold", 64),
            order_watch=self.watch,
        )
        self.running = False

    def start(self):
        self.service._assert_main()
        if self.running:
            return
        switch = float(self.config.get("gil_switch_interval_seconds", 0.001))
        if not 0 < switch <= 0.1:
            raise ValueError("gil_switch_interval_seconds must be in (0, 0.1]")
        sys.setswitchinterval(switch)
        if hasattr(self.context, "set_account"):
            self.context.set_account(self.account_id)
        self.service.start()
        try:
            interval = self.config.get("schedule_adjust_interval", "100nMilliSecond")
            self.context.run_time("adjust", interval, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            self.service.stop()
            raise
        self.running = True

    def adjust(self):
        if not self.running:
            return 0
        count = int(self.config.get("max_requests_per_tick", 64))
        self.service.drain_request_queue(count)
        return self.service.drain_pending(count, float(self.config.get("drain_budget_seconds", 0.05)))

    def stop(self):
        self.running = False
        self.service.stop()
        self.market.close()

    def order_callback(self, order):
        try:
            if self.watch is not None and event_account_id(order) == self.account_id:
                self.watch.note(normalize_order_event(order, self.account_id, self.handlers.binding.account_types[0]))
        except Exception:
            return False
        return True

    def credit_account_callback(self, seq, result):
        return self.handlers.credit.note_credit_account(seq, result)
