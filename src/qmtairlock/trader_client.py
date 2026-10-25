"""Trading API: native facts, one-shot writes and composed callback/async ownership."""

import threading
import uuid
from collections import OrderedDict

from .client import BigQmtRpcClient
from .client_objects import (
    CompatObject,
    _account_id,
    _account_type_code,
    _account_type_name,
    _account_type_param,
    _action_to_order_type,
    _as_compat_row,
    _as_list,
    _credit_order_type_for_row,
    _full_a_share_code,
    _safe_float,
    _safe_int,
    _to_unix_seconds,
    _with_account_type,
)
from .constants import FIX_PRICE, ORDER_UNKNOWN, STOCK_BUY
from .credit_client import CreditClient
from .logging_setup import get_logger
from .option_order_type import option_order_type
from .order_id import OrderId, order_sys_id_of

log = get_logger("trader_client")
_ORDER_ID_MEMORY = 4096


class BigQmtXtTrader:
    def __init__(self, account_id, config=None, timeout_seconds=6):
        self.client = BigQmtRpcClient(account_id, config, timeout_seconds)
        self._order_sys_ids = OrderedDict()
        self._server_account_type = "STOCK"
        self._server_account_types = ["STOCK"]
        self.credit = CreditClient(self.client)
        self.callback = None
        self._callbacks = None
        self._callback_scope = None
        self._async = None
        self._lifecycle_lock = threading.RLock()
        self._stopped = False

    def register_callback(self, callback):
        self.callback = callback

    def start(self):
        return 0

    def connect(self):
        reply = self.client.call("ping", {})
        if not isinstance(reply, dict) or reply.get("pong") is not True:
            raise RuntimeError("invalid QMT ping reply")
        self._server_account_type = reply["account_type"]
        self._server_account_types = reply["account_types"]
        return 0

    def subscribe(self, account=None):
        from .client_callbacks import ExecutionCallbacks

        with self._lifecycle_lock:
            if self._stopped:
                raise RuntimeError("trader is closed")
            account = account or self.client.account_id
            scope = (
                _account_id(account, self.client.account_id),
                _account_type_param(account) or self._server_account_type,
            )
            if scope[0] != self.client.account_id:
                raise ValueError("client is bound to another account")
            if self._callback_scope is not None and self._callback_scope != scope:
                raise ValueError("use a separate trader for each callback account type")
            if self._callbacks is None:
                callbacks = ExecutionCallbacks(self, account or self.client.account_id)
                callbacks.poll_once()
                callbacks.start()
                self._callbacks = callbacks
                self._callback_scope = scope
        return 0

    def stop(self):
        with self._lifecycle_lock:
            self._stopped = True
            asynchronous, callbacks = self._async, self._callbacks
        self.client.close()
        if asynchronous is not None:
            asynchronous.close()
        if callbacks is not None:
            callbacks.stop()

    def query_execution_snapshot(self, account, order_strategy_name="", trade_strategy_name=""):
        account_id = _account_id(account, self.client.account_id)
        data = self.client.call(
            "query_execution_snapshot",
            _with_account_type(
                dict(
                    account_id=account_id,
                    order_strategy_name=order_strategy_name,
                    trade_strategy_name=trade_strategy_name,
                ),
                account,
            ),
            account_id=account_id,
        )
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("orders"), list)
            or (not isinstance(data.get("trades"), list))
        ):
            raise ValueError("invalid execution snapshot")
        result = dict(data)
        result["orders"] = [self._order_from_dict(account_id, row) for row in data["orders"]]
        result["trades"] = [self._trade_from_dict(account_id, row) for row in data["trades"]]
        return result

    def query_stock_orders(self, account, cancelable_only=False, strategy_name=""):
        aid = _account_id(account, self.client.account_id)
        data = self.client.call(
            "query_orders",
            _with_account_type(
                dict(account_id=aid, cancelable_only=cancelable_only, strategy_name=strategy_name), account
            ),
            account_id=aid,
        )
        return [self._order_from_dict(aid, row) for row in data]

    def query_stock_order(self, account, order_id):
        return next(
            (
                row
                for row in self.query_stock_orders(account)
                if row.order_sysid == self._resolve_order_sys_id(order_id)
            ),
            None,
        )

    def query_stock_trades(self, account):
        aid = _account_id(account, self.client.account_id)
        data = self.client.call("query_trades", _with_account_type(dict(account_id=aid), account), account_id=aid)
        return [self._trade_from_dict(aid, row) for row in data]

    def query_stock_positions(self, account):
        aid = _account_id(account, self.client.account_id)
        data = self.client.call(
            "query_stock_positions", _with_account_type(dict(account_id=aid), account), account_id=aid
        )
        return [self._position_object(aid, row) for row in data]

    def query_stock_position(self, account, stock_code):
        return next((row for row in self.query_stock_positions(account) if row.stock_code == stock_code), None)

    def query_position_statistics(self, account):
        aid = _account_id(account, self.client.account_id)
        data = self.client.call(
            "get_position_statistics", _with_account_type(dict(account_id=aid), account), account_id=aid
        )
        return [self._position_statistics_object(aid, row) for row in data]

    def query_stock_asset(self, account):
        aid = _account_id(account, self.client.account_id)
        row = self.client.call("get_asset", _with_account_type(dict(account_id=aid), account), account_id=aid)
        if not isinstance(row, dict):
            raise ValueError("invalid asset response")
        return CompatObject(**dict(row, account_id=aid, account_type=_account_type_param(account) or 2))

    def order_stock_result(
        self, account, stock_code, order_type, order_volume, price_type, price, strategy_name="", order_remark=""
    ):
        aid = _account_id(account, self.client.account_id)
        params = _with_account_type(
            dict(
                account_id=aid,
                stock_code=stock_code,
                order_type=order_type,
                order_volume=order_volume,
                price_type=price_type,
                price=price,
                strategy_name=strategy_name,
                order_remark=order_remark,
            ),
            account,
        )
        return self.client.call("submit_order", params, account_id=aid)

    def order_stock(
        self, account, stock_code, order_type, order_volume, price_type, price, strategy_name="", order_remark=""
    ):
        result = self.order_stock_result(
            account, stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark
        )
        return self._order_id(result.get("order_sys_id"))

    def order_stock_batch(self, account, orders, strategy_name="", idempotent=True):
        aid = _account_id(account, self.client.account_id)
        return self.client.call(
            "submit_orders_batch",
            _with_account_type(
                dict(account_id=aid, orders=list(orders), strategy_name=strategy_name, idempotent=idempotent), account
            ),
            account_id=aid,
        )

    def cancel_order_stock_batch(self, account, orders):
        aid = _account_id(account, self.client.account_id)
        items = [item if isinstance(item, dict) else {"order_sysid": str(item)} for item in orders]
        return self.client.call(
            "cancel_orders_batch", _with_account_type(dict(account_id=aid, items=items), account), account_id=aid
        )

    def _async_call(self, kind, function, account, identity):
        from .client_async import AsyncOperations

        with self._lifecycle_lock:
            if self._stopped:
                raise RuntimeError("trader is closed")
            self.subscribe(account)
            if self._async is None:
                self._async = AsyncOperations(self)
            identity = dict(
                identity,
                account_id=_account_id(account, self.client.account_id),
                account_type=_account_type_code(_account_type_param(account) or self._server_account_type),
            )
            return self._async.submit(kind, function, identity)

    def order_stock_async(
        self, account, stock_code, order_type, order_volume, price_type, price, strategy_name="", order_remark=""
    ):
        order_remark = order_remark or "qmt-" + uuid.uuid4().hex
        return self._async_call(
            "order",
            lambda: self.order_stock_result(
                account, stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark
            ),
            account,
            {"remark": order_remark, "stock_code": _full_a_share_code(stock_code)},
        )

    def cancel_order_stock_sysid_async(self, account, market, order_sysid):
        return self._async_call(
            "cancel",
            lambda: self.cancel_order_stock_sysid(account, market, order_sysid),
            account,
            {"order_sysid": self._resolve_order_sys_id(order_sysid)},
        )

    def cancel_order_stock_async(self, account, order_id):
        return self.cancel_order_stock_sysid_async(account, "", order_id)

    def _position_object(self, account_id, item):
        volume = _safe_int(item.get("volume"))
        available = _safe_int(item.get("available", item.get("can_use_volume")))
        cost = _safe_float(item.get("cost", item.get("avg_price")))
        price = _safe_float(item.get("price", item.get("last_price")), cost)
        stock_code = str(item.get("stock_code") or "")
        stock_name = str(item.get("stock_name") or "")
        market_value = item.get("market_value")
        if market_value is None:
            market_value = price * volume
        return CompatObject(
            account_type=self._account_type_value(item),
            account_id=account_id,
            stock_code=stock_code,
            stock_name=stock_name,
            volume=volume,
            can_use_volume=available,
            enable_amount=available,
            available_amount=available,
            avg_price=cost,
            price=price,
            open_price=_safe_float(item.get("open_price"), cost),
            cost_price=cost,
            market_value=_safe_float(market_value, 0.0),
            frozen_volume=_safe_int(item.get("frozen_volume")),
            on_road_volume=_safe_int(item.get("on_road_volume")),
            yesterday_volume=_safe_int(item.get("yesterday_volume"), volume),
            direction=_safe_int(item.get("direction"), 48),
            m_strAccountID=account_id,
            m_strStockCode=stock_code,
            m_strStockName=stock_name,
            m_nVolume=volume,
            m_nCanUseVolume=available,
            m_nCanUseVol=available,
            m_nEnableAmount=available,
            m_dOpenPrice=_safe_float(item.get("open_price"), cost),
            m_dAvgPrice=cost,
            m_dLastPrice=price,
            m_dMarketValue=_safe_float(market_value, 0.0),
            m_nFrozenVolume=_safe_int(item.get("frozen_volume")),
            m_nOnRoadVolume=_safe_int(item.get("on_road_volume")),
            m_nYesterdayVolume=_safe_int(item.get("yesterday_volume"), volume),
            m_nDirection=_safe_int(item.get("direction"), 48),
        )

    @staticmethod
    def _position_items(data):
        if isinstance(data, dict):
            return list(data.values())
        return _as_list(data)

    def _position_statistics_object(self, account_id, item):
        return CompatObject(
            account_id=account_id,
            exchange_id=str(item.get("exchange_id") or ""),
            exchange_name=str(item.get("exchange_name") or ""),
            product_id=str(item.get("product_id") or ""),
            instrument_id=str(item.get("instrument_id") or ""),
            instrument_name=str(item.get("instrument_name") or ""),
            stock_code=str(item.get("stock_code") or ""),
            direction=_safe_int(item.get("direction"), 0),
            hedge_flag=_safe_int(item.get("hedge_flag"), 0),
            position=_safe_int(item.get("position"), 0),
            yesterday_position=_safe_int(item.get("yesterday_position"), 0),
            today_position=_safe_int(item.get("today_position"), 0),
            can_close_vol=_safe_int(item.get("can_close_vol"), 0),
            position_cost=_safe_float(item.get("position_cost"), None),
            avg_price=_safe_float(item.get("avg_price"), None),
            position_profit=_safe_float(item.get("position_profit"), None),
            float_profit=_safe_float(item.get("float_profit"), None),
            open_price=_safe_float(item.get("open_price"), None),
            used_margin=_safe_float(item.get("used_margin"), None),
            used_commission=_safe_float(item.get("used_commission"), None),
            frozen_margin=_safe_float(item.get("frozen_margin"), None),
            frozen_commission=_safe_float(item.get("frozen_commission"), None),
            instrument_value=_safe_float(item.get("instrument_value"), None),
            open_times=_safe_int(item.get("open_times"), 0),
            open_volume=_safe_int(item.get("open_volume"), 0),
            cancel_times=_safe_int(item.get("cancel_times"), 0),
            last_price=_safe_float(item.get("last_price"), None),
            rise_ratio=_safe_float(item.get("rise_ratio"), None),
            product_name=str(item.get("product_name") or ""),
            royalty=_safe_float(item.get("royalty"), None),
            expire_date=str(item.get("expire_date") or ""),
            assest_weight=_safe_float(item.get("assest_weight"), None),
            increase_by_settlement=_safe_float(item.get("increase_by_settlement"), None),
            margin_ratio=_safe_float(item.get("margin_ratio"), None),
            float_profit_divide_by_used_margin=_safe_float(item.get("float_profit_divide_by_used_margin"), None),
            float_profit_divide_by_balance=_safe_float(item.get("float_profit_divide_by_balance"), None),
            today_profit_loss=_safe_float(item.get("today_profit_loss"), None),
            yesterday_init_position=_safe_int(item.get("yesterday_init_position"), 0),
            frozen_royalty=_safe_float(item.get("frozen_royalty"), None),
            today_close_profit_loss=_safe_float(item.get("today_close_profit_loss"), None),
            close_profit=_safe_float(item.get("close_profit"), None),
            ft_product_name=str(item.get("ft_product_name") or ""),
            open_cost=_safe_float(item.get("open_cost"), None),
            m_strAccountID=account_id,
            m_strStockCode=str(item.get("stock_code") or ""),
            m_strExchangeID=str(item.get("exchange_id") or ""),
            m_strExchangeName=str(item.get("exchange_name") or ""),
            m_strProductID=str(item.get("product_id") or ""),
            m_strInstrumentID=str(item.get("instrument_id") or ""),
            m_strInstrumentName=str(item.get("instrument_name") or ""),
            m_nDirection=_safe_int(item.get("direction"), 0),
            m_nHedgeFlag=_safe_int(item.get("hedge_flag"), 0),
            m_nPosition=_safe_int(item.get("position"), 0),
            m_nYestodayPosition=_safe_int(item.get("yesterday_position"), 0),
            m_nTodayPosition=_safe_int(item.get("today_position"), 0),
            m_nCanCloseVol=_safe_int(item.get("can_close_vol"), 0),
            m_dPositionCost=_safe_float(item.get("position_cost"), None),
            m_dAvgPrice=_safe_float(item.get("avg_price"), None),
            m_dPositionProfit=_safe_float(item.get("position_profit"), None),
            m_dFloatProfit=_safe_float(item.get("float_profit"), None),
            m_dOpenPrice=_safe_float(item.get("open_price"), None),
            m_dUsedMargin=_safe_float(item.get("used_margin"), None),
            m_dUsedCommission=_safe_float(item.get("used_commission"), None),
            m_dFrozenMargin=_safe_float(item.get("frozen_margin"), None),
            m_dFrozenCommission=_safe_float(item.get("frozen_commission"), None),
            m_dInstrumentValue=_safe_float(item.get("instrument_value"), None),
            m_nOpenTimes=_safe_int(item.get("open_times"), 0),
            m_nOpenVolume=_safe_int(item.get("open_volume"), 0),
            m_nCancelTimes=_safe_int(item.get("cancel_times"), 0),
            m_dLastPrice=_safe_float(item.get("last_price"), None),
            m_dRiseRatio=_safe_float(item.get("rise_ratio"), None),
            m_strProductName=str(item.get("product_name") or ""),
            m_dRoyalty=_safe_float(item.get("royalty"), None),
            m_strExpireDate=str(item.get("expire_date") or ""),
            m_dAssestWeight=_safe_float(item.get("assest_weight"), None),
            m_dIncreaseBySettlement=_safe_float(item.get("increase_by_settlement"), None),
            m_dMarginRatio=_safe_float(item.get("margin_ratio"), None),
            m_dFloatProfitDivideByUsedMargin=_safe_float(item.get("float_profit_divide_by_used_margin"), None),
            m_dFloatProfitDivideByBalance=_safe_float(item.get("float_profit_divide_by_balance"), None),
            m_dTodayProfitLoss=_safe_float(item.get("today_profit_loss"), None),
            m_nYestodayInitPosition=_safe_int(item.get("yesterday_init_position"), 0),
            m_dFrozenRoyalty=_safe_float(item.get("frozen_royalty"), None),
            m_dTodayCloseProfitLoss=_safe_float(item.get("today_close_profit_loss"), None),
            m_dCloseProfit=_safe_float(item.get("close_profit"), None),
            m_strFtProductName=str(item.get("ft_product_name") or ""),
            m_dOpenCost=_safe_float(item.get("open_cost"), None),
        )

    def _order_id(self, order_sys_id):
        """MiniQMT's return contract: a positive int, or -1 on failure."""
        text = str(order_sys_id or "").strip()
        if not text or text == "-1":
            return -1
        order_id = OrderId(text)
        self._remember_order_id(order_id)
        return order_id

    def _order_object_id(self, order_sys_id):
        """``order_id`` for an XtOrder / XtTrade: int, empty stays empty."""
        text = str(order_sys_id or "").strip()
        if not text:
            return OrderId("")
        order_id = OrderId(text)
        self._remember_order_id(order_id)
        return order_id

    def _remember_order_id(self, order_id):
        """Keep int -> 合同编号 so a cancel still works after a round trip."""
        sys_id = getattr(order_id, "order_sys_id", "")
        if not sys_id or str(int(order_id)) == sys_id:
            return
        table = self._order_sys_ids
        table[int(order_id)] = sys_id
        while len(table) > _ORDER_ID_MEMORY:
            table.popitem(last=False)

    def _resolve_order_sys_id(self, value):
        """The broker string for whatever a caller passed to a cancel."""
        carried = getattr(value, "order_sys_id", None)
        if carried:
            return str(carried)
        if isinstance(value, int) and (not isinstance(value, bool)):
            remembered = self._order_sys_ids.get(int(value))
            if remembered:
                return remembered
        return order_sys_id_of(value)

    def _account_type_value(self, item=None):
        """account_type for an XtOrder / XtTrade / XtPosition, as an int."""
        code = _account_type_code((item or {}).get("account_type"))
        if code:
            return code
        code = _account_type_code(self._server_account_type)
        if code:
            return code
        try:
            from .constants import SECURITY_ACCOUNT

            return int(SECURITY_ACCOUNT)
        except Exception:
            return 2

    def _order_from_dict(self, account_id, item):
        action = item.get("action")
        order_type = (
            option_order_type(item.get("direction"), item.get("offset_flag"), action)
            if self._account_type_value(item) == 6
            else _action_to_order_type(action)
        )
        order_type = _credit_order_type_for_row(item, order_type)
        order_sysid = str(item.get("order_sys_id") or item.get("order_sysid") or item.get("order_id") or "")
        return CompatObject(
            account_id=account_id,
            stock_code=_full_a_share_code(item.get("stock_code")),
            order_type=order_type,
            order_status=_safe_int(item.get("status", item.get("order_status")), ORDER_UNKNOWN),
            order_volume=_safe_int(item.get("volume", item.get("order_volume"))),
            traded_volume=_safe_int(item.get("traded_volume")),
            price=_safe_float(item.get("price")),
            traded_price=_safe_float(
                item.get("traded_price", item.get("avg_traded_price", item.get("m_dTradedPrice")))
            ),
            trade_amount=_safe_float(item.get("trade_amount", item.get("m_dTradeAmount"))),
            order_sysid=order_sysid,
            order_id=self._order_object_id(order_sysid or str(item.get("user_order_id") or "")),
            strategy_name=str(item.get("strategy_name") or ""),
            order_remark=str(item.get("remark") or item.get("user_order_id") or ""),
            order_time=_safe_int(item.get("order_time") or item.get("created_at_ts"), 0),
            status_msg=str(item.get("status_msg") or ""),
            price_type=item.get("price_type"),
            account_type=self._account_type_value(item),
            instrument_name=str(item.get("instrument_name") or ""),
            secu_account=str(item.get("secu_account") or ""),
            offset_flag=item.get("offset_flag"),
            direction=item.get("direction"),
        )

    def _trade_from_dict(self, account_id, item):
        action = item.get("action")
        order_type = (
            option_order_type(item.get("direction"), item.get("offset_flag"), action)
            if self._account_type_value(item) == 6
            else _action_to_order_type(action)
        )
        order_type = _credit_order_type_for_row(item, order_type)
        order_sysid = str(item.get("order_sys_id") or item.get("order_sysid") or "")
        trade_id = str(item.get("trade_id") or "")
        traded_volume = _safe_int(item.get("volume", item.get("traded_volume")))
        traded_price = _safe_float(item.get("price", item.get("traded_price")))
        amount = item.get("amount")
        if not amount:
            amount = traded_price * traded_volume
        return CompatObject(
            account_id=account_id,
            stock_code=_full_a_share_code(item.get("stock_code")),
            order_type=order_type,
            order_sysid=order_sysid,
            order_id=self._order_object_id(order_sysid),
            trade_id=trade_id,
            traded_id=trade_id,
            traded_volume=traded_volume,
            traded_price=traded_price,
            traded_time=_to_unix_seconds(item.get("traded_time") or item.get("created_at_ts") or item.get("traded_at")),
            traded_amount=_safe_float(amount, 0.0),
            traded_at=str(item.get("traded_at") or ""),
            strategy_name=str(item.get("strategy_name") or ""),
            order_remark=str(item.get("user_order_id") or item.get("remark") or ""),
            account_type=self._account_type_value(item),
            instrument_name=str(item.get("instrument_name") or ""),
            secu_account=str(item.get("secu_account") or ""),
            commission=_safe_float(item.get("commission"), 0.0),
            offset_flag=item.get("offset_flag"),
            direction=item.get("direction"),
        )

    def passorder(
        self,
        op_type,
        order_type,
        account,
        order_code,
        price_type,
        price,
        volume,
        strategy_name="",
        quick_trade=None,
        user_order_id="",
        dry_run=False,
    ):
        """Call QMT's native passorder straight through (route 2)."""
        account_id = _account_id(account, self.client.account_id)
        params = _with_account_type(
            {
                "account_id": account_id,
                "op_type": op_type,
                "order_code": order_code,
                "price_type": price_type,
                "price": price,
                "volume": volume,
                "strategy_name": strategy_name,
                "user_order_id": user_order_id,
            },
            account,
        )
        if order_type is not None:
            params["order_type"] = order_type
        if quick_trade is not None:
            params["quick_trade"] = quick_trade
        if dry_run:
            params["dry_run"] = True
        return self.client.call("passorder", params, account_id=account_id)

    def cancel_order_stock_sysid(self, account, market, order_sysid):
        """MiniQMT contract: 0 on success, -1 on failure."""
        account_id = _account_id(account, self.client.account_id)
        data = (
            self.client.call(
                "cancel_order_stock_sysid",
                _with_account_type(
                    {
                        "account_id": account_id,
                        "market": market,
                        "order_sysid": self._resolve_order_sys_id(order_sysid),
                    },
                    account,
                ),
                account_id=account_id,
            )
            or {}
        )
        return 0 if isinstance(data, dict) and data.get("success") is True else -1

    def cancel_order_stock(self, account, order_id):
        return self.cancel_order_stock_sysid(account, "", order_id)

    def query_account_infos(self, account=None):
        return self._query_account_list(account, "query_account_infos")

    def query_account_status(self, account=None):
        return self._query_account_list(account, "query_account_status")

    def _query_account_list(self, account, method):
        account_id = _account_id(account, self.client.account_id)
        rows = self.client.call(method, _with_account_type({"account_id": account_id}, account), account_id=account_id)
        return [_as_compat_row(row) for row in rows] if isinstance(rows, list) else _as_compat_row(rows)

    def query_ipo_data(self, account=None, stock_type=""):
        account_id = _account_id(account, self.client.account_id)
        data = self.client.call("get_ipo_data", {"type": stock_type}, account_id=account_id)
        if not isinstance(data, dict):
            raise ValueError("invalid IPO data response")
        return data

    def query_new_purchase_limit(self, account):
        account_id = _account_id(account, self.client.account_id)
        data = self.client.call(
            "get_new_purchase_limit", _with_account_type({"account_id": account_id}, account), account_id=account_id
        )
        if not isinstance(data, dict):
            raise ValueError("invalid IPO limit response")
        return data

    def ipo_subscribe(self, account, stock_code, volume, price, strategy_name="ipo", order_remark="ipo_sub"):
        """新股申购 (打新). 复用现有 order_stock RPC (passorder opType=23 指定价)."""
        return self.order_stock_result(
            account, stock_code, STOCK_BUY, int(volume), FIX_PRICE, float(price), strategy_name, order_remark
        )

    def convert_bond(self, account, stock_code, volume, strategy_name="", order_remark=""):
        """可转债转股：把 ``volume`` 张转债转成正股（大 QMT passorder opType 80 / 82）。"""
        return self._convertible_op("convert", account, stock_code, volume, strategy_name, order_remark)

    def sell_back_bond(self, account, stock_code, volume, strategy_name="", order_remark=""):
        """可转债回售：把 ``volume`` 张转债按回售条款卖回发行人（opType 81 / 83）。"""
        return self._convertible_op("sell_back", account, stock_code, volume, strategy_name, order_remark)

    def _convertible_op(self, action, account, stock_code, volume, strategy_name, order_remark):
        from .adapters.order_types import convertible_optype_for

        account_type = (
            _account_type_name(getattr(account, "account_type", None))
            or getattr(self, "_declared_account_type", "")
            or "STOCK"
        )
        op_type = convertible_optype_for(action, account_type)
        data = self.order_stock_result(account, stock_code, op_type, int(volume), 11, 0.0, strategy_name, order_remark)
        return self._order_id(data.get("order_sys_id"))
