"""Credit-account reads and counter-query freshness metadata."""

from .client_objects import _account_id, _as_compat_row, _with_account_type


class CreditClient:
    def __init__(self, client):
        self.client = client

    def _query_account_list(self, account, method):
        account_id = _account_id(account, self.client.account_id)
        params = _with_account_type({"account_id": account_id, "account_type": "CREDIT"}, account)
        rows = self.client.call(method, params, account_id=account_id)
        if not isinstance(rows, list):
            raise ValueError("credit query must return a list")
        return [_as_compat_row(row) for row in rows]

    def query_credit_detail(self, account):
        """信用账户明细，读终端缓存的信用账号对象（同步）。"""
        return self._query_account_list(account, "query_credit_detail")

    def query_credit_account(self, account=None, wait_seconds=None, max_age_seconds=None):
        """信用账户明细，查柜台的那一份（官方参考 6.13）。"""
        account_id = _account_id(account, self.client.account_id)
        params = _with_account_type({"account_id": account_id}, account)
        if wait_seconds is not None:
            params["wait_seconds"] = float(wait_seconds)
        if max_age_seconds is not None:
            params["max_age_seconds"] = float(max_age_seconds)
        answer = self.client.call("query_credit_account", params, account_id=account_id)
        if isinstance(answer, dict) and isinstance(answer.get("rows"), list):
            answer = dict(answer)
            answer["rows"] = [_as_compat_row(row) for row in answer["rows"]]
        return answer

    def query_stk_compacts(self, account):
        return self._query_account_list(account, "query_stk_compacts")

    def query_credit_subjects(self, account):
        return self._query_account_list(account, "query_credit_subjects")

    def query_credit_slo_code(self, account):
        return self._query_account_list(account, "query_credit_slo_code")

    def query_credit_assure(self, account):
        return self._query_account_list(account, "query_credit_assure")
