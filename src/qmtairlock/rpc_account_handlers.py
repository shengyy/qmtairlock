"""Account status, native execution lookup, IPO, options and HK account queries."""

from .account_scope import ACCOUNT_TYPE_CODES
from .rpc_codec import _normalize_grouped_detail_rows


class AccountHandlers:
    def __init__(self, native):
        self.native = native
        self.binding = native.binding
        self.account_id = native.binding.account_id
        self.qmt_api = native.qmt_api

    def _reported_account_type(self):
        return ACCOUNT_TYPE_CODES[self.native.account_type()]

    def _handle_query_account_infos(self, params):
        return self.native.detail(params, "ACCOUNT")

    def _handle_query_account_status(self, params):
        rows = self.native.detail(params, "ACCOUNT")
        account_id = self.binding.account_id_for(params)
        account_type = self._reported_account_type()
        out = []
        for row in rows or []:
            if isinstance(row, dict):
                enabled = row.get("m_Enable")
                row_account = row.get("m_strAccountID")
            else:
                enabled = getattr(row, "m_Enable", None)
                row_account = getattr(row, "m_strAccountID", None)
            out.append(
                {
                    "account_id": str(row_account or account_id),
                    "account_type": account_type,
                    "status": 0 if enabled else 3,
                    "status_msg": "" if enabled else "account disabled (m_Enable=False)",
                }
            )
        return out

    def _handle_get_value_by_order_id(self, params):
        order_id = str(params.get("order_id") or params.get("order_sysid") or "")
        if not order_id:
            raise ValueError("order_id is required")
        account_id = self.binding.account_id_for(params)
        detail_type = str(params.get("detail_type") or params.get("datatype") or "ORDER").strip().upper()
        return self.native.object(
            "get_value_by_order_id", order_id, account_id, self.native.account_type(account_id), detail_type
        )

    def _handle_get_last_order_id(self, params):
        account_id = self.binding.account_id_for(params)
        detail_type = str(params.get("detail_type") or params.get("datatype") or "ORDER").strip().upper()
        strategy_name = params.get("strategy_name")
        if strategy_name is None:
            strategy_name = ""
        strategy_name = str(strategy_name or "")
        args = [account_id, self.native.account_type(account_id), detail_type]
        if strategy_name:
            args.append(strategy_name)
        return self.native.scalar("get_last_order_id", *args)

    def _handle_get_ipo_data(self, params):
        return self.native.mapping("get_ipo_data", str(params.get("type") or params.get("stock_type") or ""))

    def _handle_get_new_purchase_limit(self, params):
        return self.native.mapping("get_new_purchase_limit", self.binding.account_id_for(params))

    def _handle_get_history_trade_detail_data(self, params):
        account_id = self.binding.account_id_for(params)
        detail_type = str(params.get("detail_type") or params.get("datatype") or "DEAL")
        start_date = str(params.get("start_date") or params.get("start_time") or "")
        end_date = str(params.get("end_date") or params.get("end_time") or "")
        func = self.qmt_api.get("get_history_trade_detail_data")
        if func is None:
            raise RuntimeError("get_history_trade_detail_data is not bound on this terminal")
        raw = func(account_id, self.native.account_type(account_id), detail_type, start_date, end_date)
        return _normalize_grouped_detail_rows(raw)

    def _handle_get_option_subject_position(self, params):
        return self.native.rows("get_option_subject_position", self.binding.account_id_for(params))

    def _handle_get_comb_option(self, params):
        return self.native.rows("get_comb_option", self.binding.account_id_for(params))

    def _handle_get_hkt_exchange_rate(self, params):
        account_type = str(params.get("account_type") or params.get("accountType") or "HUGANGTONG").strip().upper()
        return self.native.mapping("get_hkt_exchange_rate", self.binding.account_id_for(params), account_type)
