"""Native account and execution snapshots, with no persistent ledger."""


class PositionSnapshot:
    def __init__(
        self,
        stock_code,
        volume,
        available,
        cost=0.0,
        stock_name="",
        market_value=None,
        price=None,
        open_price=None,
        frozen_volume=0,
        on_road_volume=0,
        yesterday_volume=None,
        direction=48,
    ):
        self.stock_code = stock_code
        self.volume = volume
        self.available = available
        self.cost = cost
        self.stock_name = stock_name
        self.market_value = market_value
        self.price = price
        self.open_price = open_price
        self.frozen_volume = frozen_volume
        self.on_road_volume = on_road_volume
        self.yesterday_volume = yesterday_volume
        self.direction = direction


class PositionStatisticsSnapshot:
    """One position-statistics row, i.e. ``get_trade_detail_data(..., "POSITION_STATISTICS")``."""

    def __init__(
        self,
        account_id="",
        exchange_id="",
        exchange_name="",
        product_id="",
        instrument_id="",
        instrument_name="",
        stock_code="",
        direction=0,
        hedge_flag=0,
        position=0,
        yesterday_position=0,
        today_position=0,
        can_close_vol=0,
        position_cost=None,
        avg_price=None,
        position_profit=None,
        float_profit=None,
        open_price=None,
        used_margin=None,
        used_commission=None,
        frozen_margin=None,
        frozen_commission=None,
        instrument_value=None,
        open_times=0,
        open_volume=0,
        cancel_times=0,
        last_price=None,
        rise_ratio=None,
        product_name="",
        royalty=None,
        expire_date="",
        assest_weight=None,
        increase_by_settlement=None,
        margin_ratio=None,
        float_profit_divide_by_used_margin=None,
        float_profit_divide_by_balance=None,
        today_profit_loss=None,
        yesterday_init_position=0,
        frozen_royalty=None,
        today_close_profit_loss=None,
        close_profit=None,
        ft_product_name="",
        open_cost=None,
    ):
        self.account_id = account_id
        self.exchange_id = exchange_id
        self.exchange_name = exchange_name
        self.product_id = product_id
        self.instrument_id = instrument_id
        self.instrument_name = instrument_name
        self.stock_code = stock_code
        self.direction = direction
        self.hedge_flag = hedge_flag
        self.position = position
        self.yesterday_position = yesterday_position
        self.today_position = today_position
        self.can_close_vol = can_close_vol
        self.position_cost = position_cost
        self.avg_price = avg_price
        self.position_profit = position_profit
        self.float_profit = float_profit
        self.open_price = open_price
        self.used_margin = used_margin
        self.used_commission = used_commission
        self.frozen_margin = frozen_margin
        self.frozen_commission = frozen_commission
        self.instrument_value = instrument_value
        self.open_times = open_times
        self.open_volume = open_volume
        self.cancel_times = cancel_times
        self.last_price = last_price
        self.rise_ratio = rise_ratio
        self.product_name = product_name
        self.royalty = royalty
        self.expire_date = expire_date
        self.assest_weight = assest_weight
        self.increase_by_settlement = increase_by_settlement
        self.margin_ratio = margin_ratio
        self.float_profit_divide_by_used_margin = float_profit_divide_by_used_margin
        self.float_profit_divide_by_balance = float_profit_divide_by_balance
        self.today_profit_loss = today_profit_loss
        self.yesterday_init_position = yesterday_init_position
        self.frozen_royalty = frozen_royalty
        self.today_close_profit_loss = today_close_profit_loss
        self.close_profit = close_profit
        self.ft_product_name = ft_product_name
        self.open_cost = open_cost


class AssetSnapshot:
    """Account funds, mirroring MiniQMT's ``XtAsset``."""

    def __init__(
        self, account_id, cash=None, total_asset=None, frozen_cash=None, market_value=None, fetch_balance=None
    ):
        self.account_id = account_id
        self.cash = cash
        self.fetch_balance = fetch_balance
        self.total_asset = total_asset
        self.frozen_cash = frozen_cash
        self.market_value = market_value


class OrderRequest:
    def __init__(
        self,
        signal_id,
        account_id,
        action,
        stock_code,
        volume,
        price,
        price_type,
        strategy_name,
        remark="",
        order_type=None,
        account_type=None,
    ):
        self.order_type = order_type
        self.account_type = account_type
        self.signal_id = signal_id
        self.account_id = account_id
        self.action = action
        self.stock_code = stock_code
        self.volume = volume
        self.price = price
        self.price_type = price_type
        self.strategy_name = strategy_name
        self.remark = remark


class OrderSubmitResult:
    def __init__(self, status, user_order_id, order_sys_id=None, message=""):
        self.status = status
        self.user_order_id = user_order_id
        self.order_sys_id = order_sys_id
        self.message = message


class OrderSnapshot:
    def __init__(
        self,
        order_sys_id,
        user_order_id,
        stock_code,
        action,
        volume,
        traded_volume,
        status,
        price=0.0,
        strategy_name="",
        remark="",
        order_time=0,
        status_msg="",
        traded_price=0.0,
        price_type=None,
        account_type=0,
        instrument_name="",
        secu_account="",
        offset_flag=None,
        direction=None,
        trade_amount=0.0,
        op_type=None,
        entrust_type=None,
        opt_name="",
    ):
        self.order_sys_id = order_sys_id
        self.user_order_id = user_order_id
        self.stock_code = stock_code
        self.action = action
        self.volume = volume
        self.traded_volume = traded_volume
        self.status = status
        self.price = price
        self.traded_price = traded_price
        self.op_type = op_type
        self.entrust_type = entrust_type
        self.opt_name = opt_name
        self.strategy_name = strategy_name
        self.remark = remark
        self.order_time = order_time
        self.status_msg = status_msg
        self.price_type = price_type
        self.account_type = account_type
        self.instrument_name = instrument_name
        self.secu_account = secu_account
        self.offset_flag = offset_flag
        self.direction = direction
        self.trade_amount = trade_amount


class TradeSnapshot:
    def __init__(
        self,
        trade_id,
        order_sys_id,
        stock_code,
        action,
        volume,
        price,
        traded_at="",
        user_order_id="",
        amount=0.0,
        strategy_name="",
        traded_time=0,
        account_type=0,
        instrument_name="",
        secu_account="",
        commission=0.0,
        offset_flag=None,
        direction=None,
        op_type=None,
        entrust_type=None,
        opt_name="",
    ):
        self.trade_id = trade_id
        self.order_sys_id = order_sys_id
        self.stock_code = stock_code
        self.action = action
        self.volume = volume
        self.price = price
        self.traded_at = traded_at
        self.user_order_id = user_order_id
        self.amount = amount
        self.strategy_name = strategy_name
        self.traded_time = traded_time
        self.account_type = account_type
        self.instrument_name = instrument_name
        self.secu_account = secu_account
        self.commission = commission
        self.offset_flag = offset_flag
        self.direction = direction
        self.op_type = op_type
        self.entrust_type = entrust_type
        self.opt_name = opt_name


class OrderRef:
    def __init__(self, order_sys_id, user_order_id=""):
        self.order_sys_id = order_sys_id
        self.user_order_id = user_order_id


class CancelResult:
    def __init__(self, success, message=""):
        self.success = success
        self.message = message
