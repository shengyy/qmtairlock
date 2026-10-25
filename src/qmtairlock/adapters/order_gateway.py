"""Native passorder and cancellation; snapshot reads are owned by OrderQueries."""

import hashlib

from ..account_scope import account_type_for, ensure_dispatch_timely
from ..code_utils import normalize_stock_code
from ..models import CancelResult, OrderSubmitResult
from .order_types import (
    _price_type_value,
    enum_integer,
    resolve_order_type,
    validate_native_optype,
)


class BigQmtOrderGateway:
    def __init__(
        self,
        context_info,
        account_id="",
        passorder_func=None,
        cancel_func=None,
        get_trade_detail_data_func=None,
        account_type="STOCK",
        combo_type=1101,
        price_type=11,
        quick_trade=2,
    ):
        self.context_info = context_info
        self.account_id = account_id
        self.passorder = passorder_func
        self.cancel_func = cancel_func
        self.get_trade_detail_data = get_trade_detail_data_func
        self.account_type = account_type
        self.combo_type = combo_type
        self.price_type = price_type
        self.quick_trade = quick_trade

    def _resolve_account_type(self, account_id):
        """Per-request account_type: map lookup if configured, else default."""
        return account_type_for(account_id, self.account_type)

    def _require_passorder(self):
        if self.passorder is None:
            raise RuntimeError("passorder is not available in Big QMT runtime")
        return self.passorder

    def _require_cancel(self):
        if self.cancel_func is None:
            raise RuntimeError("cancel is not available in Big QMT runtime")
        return self.cancel_func

    @staticmethod
    def build_user_order_id(signal_id):
        text = str(signal_id or "")
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
        return "bq:%s:%s" % (digest, text[:30])

    def submit(self, request):
        passorder = self._require_passorder()
        op_type, _ = resolve_order_type(
            request.order_type, request.action, self._resolve_account_type(request.account_id or self.account_id)
        )
        user_order_id = str(request.remark or "").strip() or self.build_user_order_id(request.signal_id)
        account_id = request.account_id or self.account_id
        ensure_dispatch_timely()
        passorder(
            op_type,
            self.combo_type,
            account_id,
            normalize_stock_code(request.stock_code),
            _price_type_value(request.price_type, self.price_type),
            float(request.price),
            int(request.volume),
            request.strategy_name,
            self.quick_trade,
            user_order_id,
            self.context_info,
        )
        return OrderSubmitResult(
            status="SUBMITTED", user_order_id=user_order_id, order_sys_id=None, message="passorder submitted"
        )

    def passorder_passthrough(
        self,
        op_type,
        order_type,
        account_id,
        order_code,
        price_type,
        price,
        volume,
        strategy_name,
        quick_trade,
        user_order_id,
        dry_run=False,
    ):
        """Call QMT's native passorder with the 11-arg signature untouched."""
        passorder = self._require_passorder()
        op_type = validate_native_optype(op_type, self._resolve_account_type(account_id))
        order_type = enum_integer(order_type, "order_type")
        args = [
            int(op_type),
            int(order_type),
            str(account_id or self.account_id),
            str(order_code),
            int(price_type),
            float(price),
            int(volume),
            str(strategy_name or ""),
            int(quick_trade),
            str(user_order_id or ""),
        ]
        if dry_run:
            return {
                "dry_run": True,
                "would_call": "passorder",
                "args": list(args),
                "context_info_supplied": self.context_info is not None,
            }
        ensure_dispatch_timely()
        passorder(*args + [self.context_info])
        return {"dry_run": False, "submitted": True, "user_order_id": args[9]}

    def cancel(self, order_ref, account_id=None):
        cancel_func = self._require_cancel()
        aid = account_id or self.account_id
        account_type = self._resolve_account_type(aid)
        ok = cancel_func(order_ref.order_sys_id, aid, account_type, self.context_info)
        return CancelResult(success=bool(ok), message="" if ok else "cancel returned false")
