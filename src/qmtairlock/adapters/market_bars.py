"""Historical and current native QMT bars, frame shaping and downloads."""

import time

from ..logging_setup import get_logger
from .market_frames import (
    _as_list,
    _bool_flag,
    _float_or_none,
    _frame_rows,
    _int_or_default,
    _market_data_answer_empty,
    _raw_market_data_payload,
)

log = get_logger("market_bars")
_SYNTH_RESCUE_SERVED_FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _single_code_frame(answer, code):
    """The one code's bar frame out of whatever ContextInfo answered."""
    if answer is None:
        return None
    if isinstance(answer, dict):
        if answer.get("__bigqmt_type__") == "DataFrame":
            return answer
        text = str(code)
        for key, value in answer.items():
            if str(key) == text:
                return value
        if len(answer) == 1:
            return list(answer.values())[0]
        return None
    if hasattr(answer, "columns") and hasattr(answer, "index"):
        return answer
    try:
        return answer[code]
    except Exception:
        return None


def _frame_axis_rows(frame):
    """``[(axis label, row dict), ...]`` for a market-data frame."""
    if frame is None:
        return []
    if isinstance(frame, dict) and frame.get("__bigqmt_type__") == "DataFrame":
        columns = [str(name) for name in frame.get("columns") or []]
        out = []
        for record in frame.get("records") or []:
            if isinstance(record, dict):
                row = dict(record)
            elif isinstance(record, (list, tuple)) and columns:
                row = dict(zip(columns, record))
            else:
                continue
            out.append((row.get("stime"), row))
        return out
    if hasattr(frame, "columns") and hasattr(frame, "index"):
        try:
            columns = [name for name in frame.columns]
            labels = list(frame.index)
            series = dict(((name, list(frame[name])) for name in columns))
            return [(labels[i], dict(((str(name), series[name][i]) for name in columns))) for i in range(len(labels))]
        except Exception:
            return []
    return [(row.get("stime") or row.get("index") or row.get("time"), row) for row in _frame_rows(frame)]


def _bar_axis_label(label, row):
    """The bar's ``stime`` spelling, or None when there is no usable one."""
    for candidate in (row.get("stime"), label, row.get("time")):
        text = str(candidate if candidate is not None else "")
        digits = "".join((ch for ch in text if ch.isdigit()))
        if len(digits) >= 8:
            return text
    return None


def _leading_synthetic_bars(rows):
    """How many leading rows are QMT's count-padding rather than real bars."""
    count = 0
    for row in rows:
        volume = _float_or_none(row.get("volume"))
        amount = _float_or_none(row.get("amount"))
        open_ = _float_or_none(row.get("open"))
        high = _float_or_none(row.get("high"))
        low = _float_or_none(row.get("low"))
        close = _float_or_none(row.get("close"))
        if None in (volume, amount, open_, high, low, close):
            break
        if volume != 0 or amount != 0:
            break
        if not open_ == high == low == close:
            break
        count += 1
    return count


class MarketBars:
    _SYNTH_FALLBACK_WARN_INTERVAL_SECONDS = 300.0

    def __init__(self, native):
        self.native = native
        self.context_info = native.context_info
        self.qmt_api = native.qmt_api

    _SYNTH_PERIOD_FIELD_RETRY = ("1w", "1mon", "1q", "1hy", "1y")
    _KLINE_ALL_FIELDS = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "settelementPrice",
        "openInterest",
        "preClose",
        "suspendFlag",
    )
    SYNTH_RESCUE_ONLY_PARAM = "_synth_rescue_only"

    def _market_data_shapes(self, method_name, **params):
        field_list = list(params.get("field_list") or params.get("fields") or [])
        stock_list = _as_list(params.get("stock_list") or params.get("stock_code"))
        period = params.get("period", "1d")
        start_time = params.get("start_time", "")
        end_time = params.get("end_time", "")
        count = params.get("count", -1)
        dividend_type = params.get("dividend_type", "none")
        fill_data = params.get("fill_data", True)
        data_dir = params.get("data_dir")
        mini_kwargs = {
            "field_list": field_list,
            "stock_list": stock_list,
            "period": period,
            "start_time": start_time,
            "end_time": end_time,
            "count": count,
            "dividend_type": dividend_type,
            "fill_data": fill_data,
        }
        big_kwargs = {
            "fields": field_list,
            "stock_code": stock_list,
            "period": period,
            "start_time": start_time,
            "end_time": end_time,
            "count": count,
            "dividend_type": dividend_type,
        }
        if method_name == "get_local_data" and data_dir is not None:
            mini_kwargs["data_dir"] = data_dir
            big_kwargs["data_dir"] = data_dir
        positional_tail_kwargs = {
            "period": period,
            "start_time": start_time,
            "end_time": end_time,
            "count": count,
            "dividend_type": dividend_type,
        }
        if method_name == "get_local_data" and data_dir is not None:
            positional_tail_kwargs["data_dir"] = data_dir
        big_kwargs_filled = dict(big_kwargs, fill_data=fill_data)
        positional_tail_filled = dict(positional_tail_kwargs, fill_data=fill_data)
        subscribe = params.get("subscribe")
        shapes = []
        if subscribe is not None:
            shapes.append((method_name, (), dict(big_kwargs_filled, subscribe=bool(subscribe))))
        shapes.extend(
            [
                (method_name, (), big_kwargs_filled),
                (method_name, (), big_kwargs),
                (method_name, (), mini_kwargs),
                (
                    method_name,
                    (field_list, stock_list, period, start_time, end_time, count, dividend_type, fill_data),
                    {},
                ),
                (method_name, (field_list, stock_list), positional_tail_filled),
                (method_name, (field_list, stock_list), positional_tail_kwargs),
                (
                    method_name,
                    (field_list,),
                    {
                        "stock_code": stock_list,
                        "period": period,
                        "start_time": start_time,
                        "end_time": end_time,
                        "count": count,
                        "dividend_type": dividend_type,
                    },
                ),
                (
                    method_name,
                    (field_list,),
                    {
                        "stock_list": stock_list,
                        "period": period,
                        "start_time": start_time,
                        "end_time": end_time,
                        "count": count,
                        "dividend_type": dividend_type,
                        "fill_data": fill_data,
                    },
                ),
            ]
        )
        return shapes

    def get_market_data(
        self,
        field_list=None,
        stock_list=None,
        period="1d",
        start_time="",
        end_time="",
        count=-1,
        dividend_type="none",
        fill_data=True,
    ):
        return self.native.first_supported(
            self._market_data_shapes(
                "get_market_data",
                field_list=field_list,
                stock_list=stock_list,
                period=period,
                start_time=start_time,
                end_time=end_time,
                count=count,
                dividend_type=dividend_type,
                fill_data=fill_data,
            )
        )

    def get_market_data_ex(self, **kwargs):
        fields = kwargs.get("field_list") or kwargs.get("fields")
        period = str(kwargs.get("period") or "")
        request = dict(kwargs)
        rescue_only = _bool_flag(request.pop(self.SYNTH_RESCUE_ONLY_PARAM, None))
        if rescue_only and period in self._SYNTH_PERIOD_FIELD_RETRY:
            rescued = self._synth_period_rescue(request, fields, period, reason="synth_rescue_only")
            if rescued is not None:
                return rescued
            return _raw_market_data_payload(
                {}, list(fields or _SYNTH_RESCUE_SERVED_FIELDS), request.get("stock_list") or request.get("stock_code")
            )
        answer = self._get_market_data_ex_once(**request)
        if period not in self._SYNTH_PERIOD_FIELD_RETRY or not _market_data_answer_empty(answer):
            return answer
        if not fields:
            retry = dict(request)
            retry.pop("fields", None)
            retry["field_list"] = list(self._KLINE_ALL_FIELDS)
            retried = self._get_market_data_ex_once(**retry)
            if not _market_data_answer_empty(retried):
                return retried
        rescued = self._synth_period_rescue(request, fields, period, reason="synth_period_primary_empty")
        return answer if rescued is None else rescued

    def _synth_period_rescue(self, kwargs, fields, period, reason):
        """Bars for a synthesized period when the primary path has none."""
        requested = [str(field) for field in fields or []]
        if requested:
            served = [field for field in requested if field in _SYNTH_RESCUE_SERVED_FIELDS]
            if not served:
                return None
        else:
            served = list(_SYNTH_RESCUE_SERVED_FIELDS)
        missing = [field for field in requested if field not in served]
        codes = [str(code) for code in _as_list(kwargs.get("stock_list") or kwargs.get("stock_code"))]
        if not codes:
            return None
        count = _int_or_default(kwargs.get("count"), -1)
        base = dict(kwargs)
        base.pop("fields", None)
        base.pop("stock_code", None)
        base["field_list"] = list(_SYNTH_RESCUE_SERVED_FIELDS)
        records = {}
        trimmed = 0
        servant = ""
        fill_data_delivered = True
        for code in codes:
            probe = dict(base)
            probe["stock_list"] = [code]
            try:
                name, args, sent, answer = self.native.first_supported_named(self._local_bar_shapes(**probe))
            except Exception as exc:
                self._warn_synth_fallback(period, "the local-bar path raised: %s: %s" % (type(exc).__name__, exc))
                return None
            servant = name
            if "fill_data" not in sent and len(args) < 8:
                fill_data_delivered = False
            pairs = _frame_axis_rows(_single_code_frame(answer, code))
            window_request = count <= 0 and bool(str(kwargs.get("start_time") or "").strip())
            if count > 0 and len(pairs) >= count or window_request:
                pad = _leading_synthetic_bars([row for _label, row in pairs])
                if pad:
                    trimmed += pad
                    pairs = pairs[pad:]
            rows = []
            for label, row in pairs:
                stime = _bar_axis_label(label, row)
                if stime is None:
                    self._warn_synth_fallback(
                        period,
                        "the local-bar path answered %d row(s) for %s with no usable time axis; keeping the empty answer"
                        % (len(pairs), code),
                    )
                    return None
                rows.append([stime] + [row.get(name) for name in served])
            records[str(code)] = rows
        if not any(records.values()):
            return None
        partial = {
            "reason": reason,
            "period": period,
            "source": "ContextInfo.%s" % servant,
            "requested": list(requested),
            "served": list(served),
            "missing": list(missing),
            "fill_data_dropped": not fill_data_delivered,
            "padding_rows_dropped": trimmed,
        }
        self._warn_synth_fallback(
            period,
            "%s; ContextInfo.%s rescued %d row(s) for %s (columns served: %s; requested: %s; missing: %s; dropped %d count-padding row(s)%s). Known on Guojin terminal build 2.0.8.0 -- check resource/version"
            % (
                "the caller asked for the rescue only"
                if reason == "synth_rescue_only"
                else "primary get_market_data2 path answered 0 rows",
                servant,
                sum((len(rows) for rows in records.values())),
                ",".join(sorted(records)),
                ",".join(served),
                ",".join(requested) if requested else "<all fields>",
                ",".join(missing) if missing else "-",
                trimmed,
                "; fill_data did not reach the terminal, ContextInfo.get_market_data takes skip_paused instead"
                if not fill_data_delivered
                else "",
            ),
        )
        return _raw_market_data_payload(
            records, served, kwargs.get("stock_list") or kwargs.get("stock_code"), partial=partial
        )

    def _warn_synth_fallback(self, period, message):
        seen = getattr(self, "_synth_fallback_warned_at", None)
        if seen is None:
            seen = self._synth_fallback_warned_at = {}
        now = time.time()
        if now - seen.get(period, 0.0) < self._SYNTH_FALLBACK_WARN_INTERVAL_SECONDS:
            return
        seen[period] = now
        log.warning("[bigqmt_synth_fallback] period=%s: %s", period, message)

    def _get_market_data_ex_once(self, **kwargs):
        raw_method = getattr(self.context_info, "get_market_data_ex_ori", None)
        if callable(raw_method):
            raw_data = self.native.first_supported(self._market_data_shapes("get_market_data_ex_ori", **kwargs))
            return _raw_market_data_payload(
                raw_data,
                kwargs.get("field_list") or kwargs.get("fields"),
                kwargs.get("stock_list") or kwargs.get("stock_code"),
            )
        shapes = self._market_data_shapes("get_market_data_ex", **kwargs)
        if hasattr(self.context_info, "get_market_data"):
            shapes.extend(self._market_data_shapes("get_market_data", **kwargs))
        return self.native.first_supported(shapes)

    def _local_bar_shapes(self, **kwargs):
        """Call shapes for "read bars without going through get_market_data2"."""
        shapes = self._market_data_shapes("get_local_data", **kwargs)
        if hasattr(self.context_info, "get_market_data"):
            shapes.extend(self._market_data_shapes("get_market_data", **kwargs))
        return shapes

    def get_local_data(self, **kwargs):
        return self.native.first_supported(self._local_bar_shapes(**kwargs))

    @staticmethod
    def _download_accepted(result, description):
        if result is not None and not result:
            raise RuntimeError("%s: terminal rejected the download (native return %r)" % (description, result))
        return True

    def _download(self, func_name, stock, period, start_time, end_time, incrementally):
        """Select one native download channel and validate every native outcome."""
        args = (stock, str(period or "1d"), str(start_time or ""), str(end_time or ""))
        function = self.qmt_api.get(func_name)
        if callable(function):
            if func_name == "download_history_data2":
                try:
                    result = function(*(args + (lambda data: None,)))
                except TypeError:
                    result = function(*args)
            else:
                result = function(*args)
            return self._download_accepted(result, func_name)

        single = self.qmt_api.get("download_history_data")
        if not callable(single):
            single = self.qmt_api.get("down_history_data")
        if callable(single):
            if func_name == "download_history_data":
                return self._download_accepted(single(*args), func_name)
            errors = []
            first_error = None
            for code in stock:
                try:
                    self._download_accepted(single(code, *args[1:]), "%s code=%s" % (func_name, code))
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
                    errors.append("%s: %s" % (code, exc))
            if errors:
                raise RuntimeError("%s per-code download failed: %s" % (func_name, "; ".join(errors))) from first_error
            return True

        function = getattr(self.context_info, func_name, None)
        if callable(function):
            key = "stock_code" if func_name == "download_history_data" else "stock_list"
            kwargs = {key: args[0], "period": args[1], "start_time": args[2], "end_time": args[3]}
            if incrementally is not None:
                kwargs["incrementally"] = incrementally
            return self._download_accepted(function(**kwargs), func_name)
        raise RuntimeError("%s: no download channel on this terminal" % func_name)

    def download_history_data(self, stock_code, period, start_time="", end_time="", incrementally=None):
        return self._download(
            "download_history_data", str(stock_code or ""), period, start_time, end_time, incrementally
        )

    def download_history_data2(self, stock_list, period, start_time="", end_time="", incrementally=None):
        return self._download(
            "download_history_data2", _as_list(stock_list), period, start_time, end_time, incrementally
        )
