"""Account snapshots and single/batch execution, without a local account ledger."""

import datetime
import math
import time
import uuid

from .account_scope import account_type_for
from .adapters.order_types import _price_type_value, resolve_order_type
from .models import OrderRef, OrderRequest
from .rpc_settlement import PendingSettlement


class TradeHandlers:
    def __init__(self, binding, gateway, queries, positions, settle_timeout=3.0, strategy_name="qmtairlock"):
        self.binding = binding
        self.gateway = gateway
        self.queries = queries
        self.positions = positions
        self.settle_timeout = float(settle_timeout)
        if not math.isfinite(self.settle_timeout) or self.settle_timeout <= 0:
            raise ValueError("settlement timeout must be finite and positive")
        self.strategy_name = str(strategy_name)
        self._batch_journal = {}

    def account_type(self):
        return account_type_for(self.binding.account_id, self.binding.account_types[0])

    def query_stock_positions(self, params):
        return self.positions.list_positions(self.binding.account_id_for(params))

    def get_positions(self, params):
        return self.positions.get_positions(self.binding.account_id_for(params))

    def get_position_statistics(self, params):
        return self.positions.get_position_statistics(self.binding.account_id_for(params))

    def get_asset(self, params):
        return self.positions.get_asset(self.binding.account_id_for(params))

    def query_stock_position(self, params):
        from .code_utils import normalize_stock_code

        code = normalize_stock_code(params["stock_code"])
        return self.get_positions(params).get(code)

    def query_orders(self, params):
        rows = self.queries.query_orders_strict(
            self.binding.account_id_for(params), str(params.get("strategy_name") or "")
        )
        if params.get("cancelable_only"):
            rows = [row for row in rows if str(row.status) in {"48", "49", "50", "55"}]
        return rows

    def query_trades(self, params):
        return self.queries.query_trades_strict(
            self.binding.account_id_for(params), str(params.get("strategy_name") or "")
        )

    def query_execution_snapshot(self, params):
        account = self.binding.account_id_for(params)
        orders = self.queries.query_orders_strict(account, str(params.get("order_strategy_name", "")))
        trades = self.queries.query_trades_strict(account, str(params.get("trade_strategy_name", "")))
        return {
            "account_id": account,
            "server_time": datetime.datetime.now(),
            "rpc_revision": "qmtairlock-v1",
            "orders": orders,
            "trades": trades,
        }

    def describe_trade_detail_fields(self, params):
        return self.queries.describe_detail_fields(
            self.binding.account_id_for(params),
            **{key: params[key] for key in ("detail_types", "shape_fields") if key in params},
        )

    def prepare_order(self, params):
        account = self.binding.account_id_for(params)
        order_type = params.get("order_type")
        _, action = resolve_order_type(order_type, params.get("action"), self.account_type())
        code = str(params.get("stock_code") or "")
        volume = params.get("volume", params.get("order_volume", 0))
        if isinstance(volume, bool) or int(volume) != float(volume) or int(volume) <= 0 or not code:
            raise ValueError("stock_code and positive integral volume are required")
        price = float(params.get("price", 0))
        if not math.isfinite(price):
            raise ValueError("price must be finite")
        tag = str(params.get("remark") or params.get("order_remark") or "qmt-" + uuid.uuid4().hex)
        return OrderRequest(
            signal_id=str(params.get("signal_id") or uuid.uuid4().hex),
            account_id=account,
            action=action,
            stock_code=code,
            volume=int(volume),
            price=price,
            price_type=params.get("price_type", "LIMIT"),
            strategy_name=params.get("strategy_name", self.strategy_name),
            remark=tag,
            order_type=order_type,
            account_type=self.account_type(),
        )

    def submit_order(self, params):
        order = self.prepare_order(params)
        baseline = set()
        if params.get("wait_settlement", True) is not False:
            baseline = {str(row.order_sys_id) for row in self.queries.query_orders_strict(order.account_id, "")}
        submitted_at = time.time()
        result = self.gateway.submit(order)
        if params.get("wait_settlement", True) is False:
            return result
        pending = PendingSettlement(
            "order", result, order.account_id, order.account_type, time.monotonic() + self.settle_timeout, order=order
        )
        pending.submitted_at = submitted_at
        pending.excluded_sysids = baseline
        return pending

    def passorder(self, params):
        def pick(*names, **defaults):
            return next((params[name] for name in names if params.get(name) is not None), defaults.get("default"))

        account = self.binding.account_id_for(params)
        return self.gateway.passorder_passthrough(
            op_type=pick("op_type", "opType"),
            order_type=pick("order_type", "orderType", default=self.gateway.combo_type),
            account_id=account,
            order_code=pick("order_code", "orderCode", "stock_code"),
            price_type=pick("price_type", "prType", default=self.gateway.price_type),
            price=pick("price", default=-1),
            volume=pick("volume", "order_volume"),
            strategy_name=pick("strategy_name", "strategyName", default=self.strategy_name),
            quick_trade=pick("quick_trade", "quickTrade", default=self.gateway.quick_trade),
            user_order_id=pick("user_order_id", "userOrderId", "order_remark", default=""),
            dry_run=pick("dry_run", default=False) is True,
        )

    def cancel_order(self, params):
        account = self.binding.account_id_for(params)
        sysid = str(params.get("order_sys_id") or params.get("order_sysid") or params.get("order_id") or "").strip()
        if not sysid:
            raise ValueError("order_sys_id is required")
        result = self.gateway.cancel(OrderRef(sysid), account)
        return PendingSettlement(
            "cancel", result, account, self.account_type(), time.monotonic() + self.settle_timeout, order_sys_id=sysid
        )

    @staticmethod
    def batch_items(params, name):
        items = params.get(name)
        if (
            not isinstance(items, list)
            or not 1 <= len(items) <= 500
            or any(not isinstance(item, dict) for item in items)
        ):
            raise ValueError("%s must contain 1 to 500 objects" % name)
        return items

    def submit_orders_batch(self, params):
        items = self.batch_items(params, "orders")
        for item in items:
            if self.binding.validate(dict(params, **item)) != self.account_type():
                raise ValueError("a batch must use one account type")
        results = []
        for index, item in enumerate(items):
            entry = {"index": index, "accepted": False, "confirmed": False, "success": False}
            merged = dict(params, **item)
            idempotent = params.get("idempotent", True) is True
            if idempotent and not str(merged.get("remark") or merged.get("order_remark") or "").strip():
                entry.update(error="idempotent batch items require order_remark", explicit_failure=True)
                results.append(entry)
                continue
            try:
                order = self.prepare_order(merged)
            except Exception as exc:
                entry.update(error=str(exc), explicit_failure=True)
                results.append(entry)
                continue
            key = (order.account_id, order.account_type, order.strategy_name, order.remark)
            signature = (
                order.stock_code,
                order.action,
                order.volume,
                order.price,
                _price_type_value(order.price_type, self.gateway.price_type),
                order.order_type,
            )
            if idempotent and key in self._batch_journal:
                previous_signature, previous = self._batch_journal[key]
                if previous_signature != signature:
                    entry.update(error="IDEMPOTENCY_KEY_CONFLICT", explicit_failure=True)
                    results.append(entry)
                else:
                    results.append(dict(previous, index=index, idempotent=True))
                continue
            if merged.get("require_idempotency_check"):
                try:
                    orders, trades = self.queries.query_submission_identities_strict(
                        order.account_id, order.strategy_name
                    )
                    known = next(
                        (row for row in list(orders) + list(trades) if row.user_order_id == order.remark), None
                    )
                except Exception:
                    entry.update(error="IDEMPOTENCY_CHECK_UNAVAILABLE", explicit_failure=False)
                    results.append(entry)
                    continue
                if known is not None:
                    if (
                        known.stock_code != order.stock_code
                        or known.action != order.action
                        or known not in orders
                        or known.volume != order.volume
                        or known.price != order.price
                    ):
                        entry.update(
                            error="IDEMPOTENCY_KEY_CONFLICT_OR_UNVERIFIABLE",
                            explicit_failure=False,
                            order_sys_id=str(known.order_sys_id),
                        )
                        results.append(entry)
                        continue
                    entry.update(
                        accepted=True,
                        confirmed=True,
                        success=True,
                        order_sys_id=str(known.order_sys_id),
                        idempotent=True,
                    )
                    results.append(entry)
                    continue
            entry.update(user_order_id=order.remark, explicit_failure=False)
            if idempotent:
                if len(self._batch_journal) >= 65536:
                    entry.update(error="batch deduplication capacity reached", explicit_failure=True)
                    results.append(entry)
                    continue
                self._batch_journal[key] = (signature, entry)
            try:
                result = self.gateway.submit(order)
                entry.update(accepted=True, success=True, order_sys_id=str(result.order_sys_id or ""))
            except Exception as exc:
                entry.update(error="native dispatch failed; outcome unknown: %s" % type(exc).__name__)
            results.append(dict(entry))
        return results

    def cancel_orders_batch(self, params):
        items = self.batch_items(params, "items")
        for item in items:
            if self.binding.validate(dict(params, **item)) != self.account_type():
                raise ValueError("a batch must use one account type")
        results = []
        for index, item in enumerate(items):
            entry = {"index": index, "accepted": False, "confirmed": False, "success": False}
            try:
                pending = self.cancel_order(dict(params, **item))
                entry.update(accepted=True, success=bool(pending.result.success), message=pending.result.message)
            except Exception as exc:
                entry.update(error="cancel dispatch failed; outcome unknown: %s" % type(exc).__name__)
            results.append(entry)
        return results
