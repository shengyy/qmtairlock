"""Credit contracts and rate-limited counter callback snapshots."""

import math
import threading
import time

from .rpc_codec import _normalize_detail_rows

CREDIT_ACCOUNT_DEFAULT_WAIT_SECONDS = 0.0


class CreditHandlers:
    def __init__(self, native):
        self.native = native
        self.binding = native.binding
        self.qmt_api = native.qmt_api
        self.market_data = native
        self._credit_account_lock = threading.Lock()
        self._credit_account_rows = []
        self._credit_account_seq = 0
        self._credit_account_stamp = 0.0
        self._credit_account_asked = 0.0
        self._credit_account_inflight = False
        self._credit_account_error = ""
        self._credit_account_callbacks = 0
        self._credit_account_callback_thread = ""
        self._credit_pending_seq = None
        self.credit_account_min_interval_seconds = 30.0
        self.credit_account_max_wait_seconds = 10.0
        self.credit_account_max_age_seconds = 120.0

    def note_credit_account(self, seq, result):
        """credit_account_callback 的落点。"""
        with self._credit_account_lock:
            if self._credit_pending_seq is None or seq != self._credit_pending_seq:
                return False
        try:
            rows = _normalize_detail_rows([result] if result is not None else [])
        except Exception as exc:
            with self._credit_account_lock:
                self._credit_account_callbacks += 1
                self._credit_account_inflight = False
                self._credit_account_error = "%s: %s" % (exc.__class__.__name__, exc)
            return False
        try:
            thread_name = threading.current_thread().name
        except Exception:
            thread_name = "?"
        with self._credit_account_lock:
            if self._credit_pending_seq is None or seq != self._credit_pending_seq:
                return False
            self._credit_account_callbacks += 1
            self._credit_account_callback_thread = thread_name
            self._credit_account_rows = rows
            self._credit_account_stamp = time.time()
            self._credit_account_inflight = False
            self._credit_account_error = ""
            self._credit_pending_seq = None
            try:
                self._credit_account_seq = int(seq)
            except Exception:
                pass
        return True

    def _issue_credit_account_query(self, account_id):
        """Fire query_credit_account once, honouring the counter's rate limit."""
        func = self.qmt_api.get("query_credit_account")
        if not callable(func):
            return (False, "query_credit_account is not bound in this deployment")
        context_info = getattr(self.market_data, "context_info", None)
        if context_info is None:
            return (False, "no ContextInfo available")
        now = time.time()
        with self._credit_account_lock:
            if self._credit_account_inflight:
                stuck_for = now - self._credit_account_asked
                if stuck_for < self.credit_account_min_interval_seconds:
                    return (False, "a query is already in flight (%.1fs)" % stuck_for)
                self._credit_account_inflight = False
            since = now - self._credit_account_asked
            if self._credit_account_asked and since < self.credit_account_min_interval_seconds:
                return (
                    False,
                    "rate limited: %.1fs since the last query, minimum %.1fs"
                    % (since, self.credit_account_min_interval_seconds),
                )
            self._credit_account_inflight = True
            self._credit_account_asked = now
            seq = int(now)
            self._credit_pending_seq = seq
        try:
            func(account_id, seq, context_info)
        except Exception as exc:
            with self._credit_account_lock:
                self._credit_account_inflight = False
                self._credit_account_error = "%s: %s" % (exc.__class__.__name__, exc)
            return (False, self._credit_account_error)
        return (True, "")

    def _handle_query_credit_account(self, params):
        """信用账户明细，查柜台的那条路（官方参考 6.13）。"""
        account_id = self.binding.account_id_for(params)
        wait_seconds = params.get("wait_seconds")
        if wait_seconds is None:
            wait_seconds = CREDIT_ACCOUNT_DEFAULT_WAIT_SECONDS
        wait_seconds = float(wait_seconds)
        if not math.isfinite(wait_seconds) or wait_seconds < 0:
            raise ValueError("wait_seconds must be finite and nonnegative")
        wait_seconds = min(self.credit_account_max_wait_seconds, wait_seconds)
        max_age_seconds = params.get("max_age_seconds")
        if max_age_seconds is None:
            max_age_seconds = self.credit_account_max_age_seconds
        max_age_seconds = float(max_age_seconds)
        if not math.isfinite(max_age_seconds) or not 0 < max_age_seconds <= self.credit_account_max_age_seconds:
            raise ValueError("max_age_seconds must be positive and at most 120")
        with self._credit_account_lock:
            stamp_before = self._credit_account_stamp
        # Account RPCs run on adjust. Waiting here can prevent the same-thread
        # native callback and every queued cancellation from making progress.
        wait_pointless = wait_seconds > 0
        issued, reason = self._issue_credit_account_query(account_id)
        with self._credit_account_lock:
            rows = list(self._credit_account_rows)
            stamp = self._credit_account_stamp
            error = self._credit_account_error
            seq = self._credit_account_seq
            callbacks = self._credit_account_callbacks
        age = round(time.time() - stamp, 3) if stamp else None
        dropped_stale = False
        stale_reason = ""
        if rows and max_age_seconds > 0 and (age is not None) and (age > max_age_seconds):
            dropped_stale = True
            stale_reason = (
                "缓存已 %.1f 秒未更新，超过 max_age_seconds=%.0f，不再交出 —— 这条通道的缓存不会自己刷新。查询已发出，稍后再调一次即可拿到新的；要实时数据请用 query_credit_detail。"
                % (age, max_age_seconds)
            )
            rows = []
        return {
            "rows": rows,
            "count": len(rows),
            "query_issued": issued,
            "not_issued_reason": "" if issued else reason,
            "fresh": bool(stamp and stamp > stamp_before),
            "stale": bool(rows and (not (stamp and stamp > stamp_before))),
            "age_seconds": age,
            "max_age_seconds": max_age_seconds,
            "dropped_stale": dropped_stale,
            "dropped_stale_reason": stale_reason,
            "seq": seq,
            "error": error,
            "callback_bound": callable(self.qmt_api.get("query_credit_account")),
            "callbacks_seen": callbacks,
            "waited_seconds": 0.0,
            "callback_thread": self._credit_account_callback_thread,
            "wait_skipped_main_thread": wait_pointless,
            "note": "Counter query is asynchronous; read the callback snapshot on a later request.",
        }

    def _handle_query_credit_detail(self, params):
        return self.native.detail(params, "ACCOUNT", account_type="CREDIT")

    def _handle_query_stk_compacts(self, params):
        return self.native.rows(
            "get_unclosed_compacts",
            self.binding.account_id_for(params),
            self.native.account_type(self.binding.account_id_for(params)),
        )

    def _handle_query_credit_subjects(self, params):
        return self.native.rows("get_assure_contract", self.binding.account_id_for(params))

    def _handle_query_credit_slo_code(self, params):
        return self.native.rows("get_enable_short_contract", self.binding.account_id_for(params))

    def _handle_query_credit_assure(self, params):
        return self.native.rows("get_assure_contract", self.binding.account_id_for(params))

    def _handle_get_assure_contract(self, params):
        return self.native.rows("get_assure_contract", self.binding.account_id_for(params))

    def _handle_get_enable_short_contract(self, params):
        return self.native.rows("get_enable_short_contract", self.binding.account_id_for(params))

    def _handle_get_unclosed_compacts(self, params):
        return self.native.rows(
            "get_unclosed_compacts",
            self.binding.account_id_for(params),
            self.native.account_type(self.binding.account_id_for(params)),
        )

    def _handle_get_closed_compacts(self, params):
        return self.native.rows(
            "get_closed_compacts",
            self.binding.account_id_for(params),
            self.native.account_type(self.binding.account_id_for(params)),
        )

    def _handle_get_debt_contract(self, params):
        return self.native.rows("get_debt_contract", self.binding.account_id_for(params))
