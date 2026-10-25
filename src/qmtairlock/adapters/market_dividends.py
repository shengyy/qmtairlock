"""Dividend factors, including range expansion from native daily prices."""

import time

from .market_frames import _float_or_none, _frame_rows, _row_day


class MarketDividends:
    _DIVID_MAX_PROBES = 40
    _DIVID_PRICE_EPSILON = 1e-4

    def __init__(self, native):
        self.native = native
        self.context_info = native.context_info
        self.qmt_api = native.qmt_api
        self.bars = native.bars

    def get_divid_factors(self, stock_code, start_time="", end_time=""):
        """Dividend factors over a RANGE, not just one day."""
        start = str(start_time or "").strip()
        end = str(end_time or "").strip()
        if not start and (not end):
            return self.native.call("get_divid_factors", stock_code)
        if not start or not end or start == end:
            return self.native.call("get_divid_factors", stock_code, end or start)
        for shape in (lambda: self.native.call("get_divid_factors", stock_code, start, end),):
            try:
                answer = shape()
            except Exception:
                continue
            if answer:
                return dict(answer)
        return self._expand_divid_factors(stock_code, start, end)

    def _download_daily_window(self, stock_code, start_time, end_time):
        """One terminal-side daily-bars download for a window that scanned"""
        download = self.qmt_api.get("download_history_data") or self.qmt_api.get("down_history_data")
        if not callable(download):
            return False
        try:
            download(stock_code, "1d", start_time, end_time)
        except Exception:
            return False
        return True

    def _divid_candidate_days(self, stock_code, start_time, end_time):
        """Days in the window that look like ex-dividend days."""
        frame = (
            self.bars.get_market_data_ex(
                field_list=["close", "preClose", "stime"],
                stock_list=[stock_code],
                period="1d",
                start_time=start_time,
                end_time=end_time,
                dividend_type="none",
                fill_data=False,
            )
            or {}
        ).get(stock_code)
        rows = _frame_rows(frame)
        self._divid_scan_rows = len(rows)
        candidates = []
        previous_close = None
        for row in rows:
            close = _float_or_none(row.get("close"))
            pre_close = _float_or_none(row.get("preClose"))
            day = _row_day(row)
            if day and pre_close:
                if previous_close is None:
                    candidates.append(day)
                elif abs(pre_close - previous_close) > self._DIVID_PRICE_EPSILON:
                    candidates.append(day)
            if close:
                previous_close = close
        return candidates

    def _expand_divid_factors(self, stock_code, start_time, end_time):
        """Aggregate single-day lookups over the candidate days."""
        self._divid_scan_rows = 0
        self._divid_download_note = (
            ". Download the daily history first (download_history_data), or ask one date at a time"
        )
        try:
            candidates = self._divid_candidate_days(stock_code, start_time, end_time)
        except Exception:
            candidates = []
        if self._divid_scan_rows < 2 and self._download_daily_window(stock_code, start_time, end_time):
            self._divid_download_note = ". The bridge downloaded the daily window itself (download_history_data) and the terminal still returned %d daily bar(s)"
            for _attempt in range(3):
                try:
                    candidates = self._divid_candidate_days(stock_code, start_time, end_time)
                except Exception:
                    candidates = []
                if self._divid_scan_rows >= 2:
                    break
                time.sleep(1.0)
            self._divid_download_note %= self._divid_scan_rows
        if self._divid_scan_rows < 2:
            raise RuntimeError(
                "get_divid_factors(%r, %s, %s) cannot answer a range here: big QMT's ContextInfo takes only (code, single date), so the range is expanded by scanning daily bars for ex-dividend days -- and this terminal returned %d daily bar(s) for that window, too few to compare even one preClose against the previous close%s. Returning {} would have been indistinguishable from 'no dividends in this range'."
                % (stock_code, start_time, end_time, self._divid_scan_rows, self._divid_download_note)
            )
        merged = {}
        merged = {}
        for day in candidates[: self._DIVID_MAX_PROBES]:
            try:
                answer = self.native.call("get_divid_factors", stock_code, day)
            except Exception:
                continue
            if answer:
                merged.update(answer)
        return merged
