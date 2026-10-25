"""Native account queries and shape conversion; failures remain errors."""

from .account_scope import account_type_for
from .rpc_codec import _normalize_detail_rows, _normalize_mapping_value


class NativeQueries:
    def __init__(self, binding, context_info, qmt_api=None):
        self.binding = binding
        self.context_info = context_info
        self.qmt_api = dict(qmt_api or {})

    def call(self, name, *args, **kwargs):
        function = self.qmt_api.get(name)
        if not callable(function):
            raise NotImplementedError("QMT global %s is not bound" % name)
        return function(*args, **kwargs)

    def account_type(self, account_id=None):
        return account_type_for(account_id, self.binding.account_types[0])

    def detail(self, params, detail_type, strategy_name="", account_type=None):
        account_id = self.binding.account_id_for(params)
        kind = account_type or self.account_type(account_id)
        if kind not in self.binding.account_types:
            raise ValueError("account type is not enabled for the bound account")
        return _normalize_detail_rows(self.call("get_trade_detail_data", account_id, kind, detail_type, strategy_name))

    def rows(self, name, *args, **kwargs):
        return _normalize_detail_rows(self.call(name, *args, **kwargs))

    def scalar(self, name, *args, **kwargs):
        return _normalize_mapping_value(self.call(name, *args, **kwargs))

    def mapping(self, name, *args, **kwargs):
        raw = self.call(name, *args, **kwargs)
        return _normalize_mapping_value(raw) if isinstance(raw, dict) else _normalize_detail_rows(raw)

    def object(self, name, *args, **kwargs):
        raw = self.call(name, *args, **kwargs)
        if raw is None:
            return {}
        rows = _normalize_detail_rows(raw if isinstance(raw, (list, tuple)) else [raw])
        return rows[0] if rows else {}
