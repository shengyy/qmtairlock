"""Native quote snapshots and bounded warmup subscription ownership."""

import time

from ..code_utils import EXCHANGE_TOKENS, normalize_stock_code
from ..logging_setup import get_logger

log = get_logger("market_ticks")


MARKET_CODES = {"SH", "SZ", "BJ", "HK"}
STOCK_SECTOR_BY_MARKET = {"SH": "上证A股", "SZ": "深证A股", "BJ": "京市A股"}
DEFAULT_TICK_TYPES = ("all",)
SECTOR_BY_TYPE = {
    "stock": "沪深京A股",
    "fund": "沪深基金",
    "etf": "沪深ETF",
    "index": "沪深指数",
    "convertible": "沪深转债",
    "cbond": "沪深转债",
    "cb": "沪深转债",
    "convertible_bond": "沪深转债",
}


def _ignore_tick_push(data):
    """Callback for the warm-up subscriptions: the snapshot is read back"""
    return None


def normalize_market_or_stock_code(code):
    """Market token, or a normalised instrument code."""
    text = str(code or "").strip()
    if text.upper() in EXCHANGE_TOKENS:
        return text.upper()
    return normalize_stock_code(text)


class MarketTicks:
    def __init__(self, native):
        self.native = native
        self.context_info = native.context_info
        self.qmt_api = native.qmt_api

    TICK_SUBSCRIBE_WAIT_SECONDS = 0.0
    TICK_SUBSCRIBE_POLL_SECONDS = 0.1
    TICK_SUBSCRIBE_IDLE_SECONDS = 300.0

    def _sector_codes(self, sector):
        """Cached sector listing. Membership does not change intraday and the"""
        cache = getattr(self, "_sector_cache", None)
        if cache is None:
            cache = self._sector_cache = {}
        if sector not in cache:
            try:
                cache[sector] = list(self.native.metadata.get_stock_list_in_sector(sector) or [])
            except Exception:
                cache[sector] = []
        return cache[sector]

    def _expand_market_token(self, market, types):
        """Codes of the requested types on one exchange, or None to give up."""
        collected = []
        for kind in types:
            kind = str(kind or "").strip().lower()
            sector = None
            if kind == "stock":
                sector = STOCK_SECTOR_BY_MARKET.get(market)
            if sector is None:
                sector = SECTOR_BY_TYPE.get(kind)
            if sector is None:
                return None
            listing = self._sector_codes(sector)
            if not listing:
                return None
            suffix = "." + market
            collected.extend((c for c in listing if str(c).upper().endswith(suffix)))
        seen, unique = (set(), [])
        for code in collected:
            if code not in seen:
                seen.add(code)
                unique.append(code)
        return unique or None

    def _notice_narrowed(self, market, kept, total_hint):
        """Say once per process that a market token was narrowed."""
        seen = getattr(self, "_narrow_notified", None)
        if seen is None:
            seen = self._narrow_notified = set()
        if market in seen:
            return
        seen.add(market)
        try:
            print(
                "[bigqmt_market] %s narrowed to %d %s; pass types=['all'] for every instrument the exchange lists"
                % (market, kept, total_hint)
            )
        except Exception:
            pass

    def _tick_subscription_state(self):
        state = getattr(self, "_tick_subscription_state_dict", None)
        if state is None:
            import threading

            state = self._tick_subscription_state_dict = {"lock": threading.RLock(), "groups": [], "by_code": {}}
        return state

    @staticmethod
    def _tick_unanswered(targets, data):
        """Requested codes the snapshot has no entry for. A market token counts"""
        answered = {str(key).upper() for key in data or {}}
        missing = []
        for code in targets:
            text = str(code)
            if text in EXCHANGE_TOKENS:
                suffix = "." + text
                if not any((key.endswith(suffix) for key in answered)):
                    missing.append(text)
            elif text.upper() not in answered:
                missing.append(text)
        return missing

    def tick_subscription_status(self):
        """Read-only view of the warm-up subscriptions, for diagnostics."""
        state = self._tick_subscription_state()
        now = time.monotonic()
        with state["lock"]:
            return [
                {"handle": handle, "codes": sorted(codes), "idle_seconds": round(now - last_used, 1)}
                for handle, codes, last_used in state["groups"]
            ]

    def prune_tick_subscriptions(self, now=None):
        """Unsubscribe warm-up groups idle longer than TICK_SUBSCRIBE_IDLE_SECONDS."""
        state = getattr(self, "_tick_subscription_state_dict", None)
        if state is None:
            return 0
        now = time.monotonic() if now is None else now
        idle = float(self.TICK_SUBSCRIBE_IDLE_SECONDS)
        expired = []
        with state["lock"]:
            keep = []
            for group in state["groups"]:
                if now - group[2] > idle:
                    expired.append(group)
                    for code in group[1]:
                        state["by_code"].pop(code, None)
                else:
                    keep.append(group)
            state["groups"] = keep
        unsubscribe = getattr(self.context_info, "unsubscribe_quote", None)
        for handle, codes, _last_used in expired:
            try:
                if callable(unsubscribe):
                    unsubscribe(handle)
            except Exception as exc:
                log.warning("full tick warm-up unsubscribe(%s) failed for %s: %s", handle, sorted(codes), exc)
        return len(expired)

    def _recover_unsubscribed_ticks(self, targets, query_codes, data):
        """Subscribe the requested codes the snapshot left unanswered, then"""
        subscribe = getattr(self.context_info, "subscribe_whole_quote", None)
        if not callable(subscribe):
            return data
        missing = self._tick_unanswered(targets, data)
        state = self._tick_subscription_state()
        now = time.monotonic()
        self.prune_tick_subscriptions(now)
        with state["lock"]:
            by_code = state["by_code"]
            for code in targets:
                group = by_code.get(str(code))
                if group is not None:
                    group[2] = now
            fresh = [code for code in missing if code not in by_code]
        if not fresh:
            return data
        try:
            handle = subscribe(list(fresh), callback=_ignore_tick_push)
            value = int(handle)
        except Exception as exc:
            value = -1
            handle = exc
        if value <= 0:
            if not getattr(self, "_tick_subscribe_warned", False):
                self._tick_subscribe_warned = True
                log.warning("full tick warm-up subscribe_whole_quote(%s) failed: %r", fresh, handle)
            return data
        with state["lock"]:
            group = [value, set(fresh), now]
            state["groups"].append(group)
            for code in fresh:
                state["by_code"][code] = group
        wait = self.full_tick_warmup_wait_seconds
        if wait == 0:
            return data
        deadline = now + wait
        poll = float(self.TICK_SUBSCRIBE_POLL_SECONDS)
        while True:
            time.sleep(poll)
            retry = self.context_info.get_full_tick(query_codes) or {}
            if isinstance(retry, dict) and retry:
                merged = dict(data)
                merged.update(retry)
                data = merged
                if not self._tick_unanswered(fresh, data):
                    break
            if time.monotonic() >= deadline:
                break
        still_missing = self._tick_unanswered(fresh, data)
        log.info(
            "full tick warm-up: subscribed %s (handle %s), %s after %.1fs",
            fresh,
            value,
            "all answered" if not still_missing else "still empty: %s" % still_missing,
            time.monotonic() - now,
        )
        return data

    @property
    def full_tick_warmup_wait_seconds(self):
        return getattr(self, "_full_tick_warmup_wait_seconds", self.TICK_SUBSCRIBE_WAIT_SECONDS)

    @full_tick_warmup_wait_seconds.setter
    def full_tick_warmup_wait_seconds(self, value):
        import math

        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("full_tick_warmup_wait_seconds must be finite and non-negative")
        self._full_tick_warmup_wait_seconds = value

    def get_ticks(self, codes, types=None):
        requested = [normalize_market_or_stock_code(code) for code in codes or []]
        wanted = list(types or DEFAULT_TICK_TYPES)
        expanded = []
        for code in requested:
            members = self._expand_market_token(code, wanted) if code in MARKET_CODES and "all" not in wanted else None
            expanded.extend([code] if members is None else members)
        data = self.context_info.get_full_tick(expanded)
        if not isinstance(data, dict):
            raise ValueError("get_full_tick did not return a mapping")
        return self._recover_unsubscribed_ticks(requested, expanded, data)

    def close(self):
        state = getattr(self, "_tick_subscription_state_dict", None)
        if state:
            with state["lock"]:
                for group in state["groups"]:
                    group[2] = float("-inf")
            self.prune_tick_subscriptions()
