"""Nonblocking order/cancel reconciliation, exclusively on the strategy thread."""

import time
from collections import OrderedDict

from .account_scope import request_account_type
from .adapters.order_types import is_sideless_order_type
from .code_utils import normalize_stock_code
from .option_order_type import option_native_optype


class PendingSettlement:
    def __init__(self, kind, result, account_id, account_type, deadline, order=None, order_sys_id=""):
        self.kind = kind
        self.result = result
        self.account_id = account_id
        self.account_type = account_type
        self.deadline = deadline
        self.submitted_at = time.time()
        self.order = order
        self.order_sys_id = order_sys_id
        self.request = None
        self.response = None
        self.attempts = 0
        self.error = ""
        self.excluded_sysids = set()


class SettlementManager:
    def __init__(self, queries, watch=None):
        self.queries = queries
        self.watch = watch
        self._claimed_ids = OrderedDict()

    def step(self, pending, orders_cache=None):
        pending.attempts += 1
        final = time.monotonic() >= pending.deadline
        with request_account_type(pending.account_type):
            try:
                if pending.kind == "cancel":
                    return self._cancel(pending, final)
                return self._order(pending, final, orders_cache if orders_cache is not None else {})
            except Exception as exc:
                if not final:
                    return False
                pending.error = "settlement lookup failed; outcome unknown: %s" % type(exc).__name__
                if pending.kind == "cancel":
                    pending.result.success = False
                    pending.result.message = pending.error
                return True

    def _cancel(self, pending, final):
        status = self.watch.status_for_sysid(pending.order_sys_id) if self.watch is not None else None
        if str(status) not in {"53", "54", "56", "57"}:
            rows = self.queries.query_orders_strict(pending.account_id, "")
            matches = [row for row in rows if str(row.order_sys_id) == pending.order_sys_id]
            status = str(matches[0].status) if matches else ""
        status = str(status)
        if status in {"53", "54"}:
            pending.result.success = True
            pending.result.message = "cancel confirmed"
            return True
        if status in {"56", "57"}:
            pending.result.success = False
            pending.result.message = "cancel not confirmed: order is terminal"
            return True
        if not final:
            return False
        pending.result.success = status in {"51", "52"}
        pending.result.message = "cancel accepted; still pending" if pending.result.success else "cancel not confirmed"
        return True

    def _order(self, pending, final, cache):
        order = pending.order
        code = normalize_stock_code(order.stock_code)
        kind = option_native_optype(order.order_type) if pending.account_type == "STOCK_OPTION" else order.order_type
        action = "" if is_sideless_order_type(kind) else str(order.action).upper()
        key = (pending.account_id, pending.account_type)
        claim_scope = key + (order.remark,)
        claimed = self._claimed_ids.get(claim_scope, set()) | pending.excluded_sysids
        sysid = None
        if self.watch is not None:
            sysid = self.watch.sysid_for_remark(
                order.remark, stock_code=code, action=action, not_before=pending.submitted_at
            )
            if sysid in claimed:
                sysid = None
        if not sysid:
            if key not in cache:
                cache[key] = self.queries.query_orders_strict(pending.account_id, "")
            matches = [
                row
                for row in cache[key]
                if str(row.user_order_id) == order.remark
                and normalize_stock_code(row.stock_code) == code
                and (not action or str(row.action).upper() == action)
                and row.order_time
                and float(row.order_time) >= int(pending.submitted_at)
                and str(row.order_sys_id) not in claimed
            ]
            sysid = next((str(row.order_sys_id) for row in matches if row.order_sys_id), None)
        if sysid:
            pending.result.order_sys_id = sysid
            pending.result.message = "order identity confirmed; execution status requires a query"
            claimed.add(sysid)
            self._claimed_ids[claim_scope] = claimed
            self._claimed_ids.move_to_end(claim_scope)
            while len(self._claimed_ids) > 2048:
                self._claimed_ids.popitem(last=False)
            return True
        if not final:
            return False
        pending.result.message = "submitted; identity unconfirmed, do not resubmit"
        return True
