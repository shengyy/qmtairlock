"""Main-thread RPC drain, heavy-read worker, write deduplication and expiry."""

import collections
import datetime
import math
import queue
import threading
import time

from .account_scope import dispatch_deadline
from .rpc_codec import to_jsonable
from .rpc_dispatch import LISTENER_DEFERRED_METHODS, ORDER_METHODS, canonical_method
from .rpc_download import DownloadIncomplete, PendingDownload
from .rpc_settlement import PendingSettlement, SettlementManager

# Same-host wall clocks (Windows and WSL) may differ slightly; never refuse before this margin.
CLIENT_DEADLINE_TOLERANCE_SECONDS = 1.0


def request_deadline(request):
    """The earliest of the server receive deadline and the client's own deadline, or None.

    A request can sit unread in the pipe while the callback thread is busy; its
    receive time is then late, but the client's ``deadline_at`` still says when
    nobody is waiting for it any more.
    """
    timeout = float(request.get("timeout_seconds", 0))
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("timeout_seconds must be finite and nonnegative")
    deadlines = []
    received = request.get("_received_at")
    if received is not None and timeout > 0:
        deadlines.append(received + timeout - min(0.05, timeout * 0.25))
    client = request.get("deadline_at")
    if client is not None:
        client = float(client)
        if not math.isfinite(client):
            raise ValueError("deadline_at must be finite")
        deadlines.append(client + CLIENT_DEADLINE_TOLERANCE_SECONDS)
    return min(deadlines) if deadlines else None


class RpcService:
    def __init__(
        self,
        handlers,
        account_id,
        transport,
        process_in_listener=True,
        listener_methods=("*",),
        heavy_codes_threshold=64,
        pending_limit=4096,
        heavy_limit=512,
        order_watch=None,
    ):
        self.handlers = handlers
        self.account_id = str(account_id)
        self._transport = transport
        self.process_in_listener = bool(process_in_listener)
        self.listener_methods = frozenset(canonical_method(name) for name in listener_methods)
        self.heavy_codes_threshold = int(heavy_codes_threshold)
        if self.heavy_codes_threshold < 1:
            raise ValueError("heavy_codes_threshold must be positive")
        self.pending = queue.Queue(maxsize=pending_limit)
        self._heavy_queue = queue.Queue(maxsize=heavy_limit)
        self._heavy_replies = queue.Queue(maxsize=heavy_limit)
        self._pending_settlements = []
        self._pending_downloads = []
        self.settlement = SettlementManager(getattr(handlers, "order_queries", None), order_watch)
        self._order_requests = collections.OrderedDict()
        self._order_lock = threading.RLock()
        self._running = False
        self._heavy_thread = None
        self._stop = threading.Event()
        self._main_ident = threading.get_ident()

    def start(self):
        if self._running:
            return
        self._main_ident = threading.get_ident()
        self._running = True
        self._stop.clear()
        self._heavy_thread = threading.Thread(target=self._heavy_loop, name="qmtairlock-heavy", daemon=True)
        self._heavy_thread.start()
        try:
            self._transport.start_receiving(self.enqueue_payload, background_threads=False)
        except Exception:
            self.stop()
            raise

    def stop(self):
        self._running = False
        self._stop.set()
        self._transport.stop()
        if self._heavy_thread is not None and self._heavy_thread is not threading.current_thread():
            self._heavy_thread.join(timeout=2)
        # Native calls cannot be killed. No new runtime may replace a live worker.
        if self._heavy_thread is not None and self._heavy_thread.is_alive():
            raise RuntimeError("native heavy read is still running; restart must wait")

    def _assert_main(self):
        if threading.get_ident() != self._main_ident:
            raise RuntimeError("account, trade and settlement work requires the strategy thread")

    def is_heavy_read(self, request):
        method = canonical_method(request.get("method", ""))
        if method in LISTENER_DEFERRED_METHODS:
            return False
        if method in {
            "get_financial_data",
            "download_financial_data",
            "download_financial_data2",
            "get_his_option_list_batch",
        }:
            return True
        if method in {"get_formula_result", "call_formula", "gen_factor_index"}:
            return True
        if method == "get_divid_factors":
            params = request.get("params") or {}
            start = str(params.get("start_time") or "").strip()
            end = str(params.get("end_time") or "").strip()
            return bool(start and end and start != end)
        if method not in {"get_ticks", "get_market_data", "get_market_data_ex", "get_local_data"}:
            return False
        params = request.get("params") or {}
        codes = params.get("codes", params.get("stock_list", []))
        if isinstance(codes, str):
            codes = [codes]
        if len(codes) > self.heavy_codes_threshold or any("." not in str(code) for code in codes):
            return True
        if method == "get_ticks":
            return bool(params.get("types"))
        return (
            str(params.get("period", "")) in {"tick", "l2quote", "l2order", "l2transaction"}
            or int(params.get("count", -1)) < 0
            and bool(params.get("start_time") or params.get("end_time"))
        )

    def _inline(self, request):
        method = canonical_method(request.get("method", ""))
        return (
            self.process_in_listener
            and method not in LISTENER_DEFERRED_METHODS
            and ("*" in self.listener_methods or method in self.listener_methods)
        )

    def enqueue_payload(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("request must be a JSON object")
        request = dict(payload)
        request["_received_at"] = time.time()
        try:
            if self.is_heavy_read(request):
                self._heavy_queue.put_nowait(request)
            elif self._inline(request):
                self.process_request(request)
            else:
                self.pending.put_nowait(request)
        except queue.Full:
            self._publish_response(request, self._error(request, "Overloaded: request was not dispatched"))
        except Exception as exc:
            self._publish_response(request, self._error(request, "%s: %s" % (type(exc).__name__, exc)))

    def _heavy_loop(self):
        while not self._stop.is_set():
            try:
                request = self._heavy_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            response = self.process_request(request, publish=False)
            while not self._stop.is_set():
                try:
                    self._heavy_replies.put((request, response), timeout=0.1)
                    break
                except queue.Full:
                    continue

    def heavy_queue_depth(self):
        return self._heavy_queue.qsize()

    def flush_heavy_replies(self, max_items=100):
        self._assert_main()
        sent = 0
        for _ in range(max_items):
            try:
                request, response = self._heavy_replies.get_nowait()
            except queue.Empty:
                break
            self._publish_response(request, response)
            sent += 1
        return sent

    def drain_request_queue(self, max_items=20):
        self._assert_main()
        return self._transport.drain_request_queue(max_items=max_items)

    def drain_pending(self, max_items=20, budget_seconds=None):
        self._assert_main()
        self.flush_heavy_replies()
        self.settle_pending_orders()
        started = time.monotonic()
        processed = 0
        for _ in range(max_items):
            if processed and budget_seconds is not None and time.monotonic() - started >= budget_seconds:
                break
            try:
                request = self.pending.get_nowait()
            except queue.Empty:
                break
            self.process_request(request)
            processed += 1
            self.settle_pending_orders()
        if self.pending.empty():
            # A chunk blocks this thread; requests already read wait for at most one, never one per tick.
            self.step_download()
        return processed

    def step_download(self):
        """Run at most one native download chunk, after this tick's other requests."""
        self._assert_main()
        if not self._pending_downloads:
            return
        pending = self._pending_downloads[0]
        response = pending.response
        try:
            if not pending.step():
                return
            response["data"] = True
        except DownloadIncomplete as exc:
            response.update(ok=False, error=str(exc), data=to_jsonable(exc.progress))
        except Exception as exc:
            response.update(ok=False, error="%s: %s" % (type(exc).__name__, exc), data=to_jsonable(pending.progress()))
        self._pending_downloads.pop(0)
        response["handled_at"] = datetime.datetime.now().isoformat()
        self._publish_response(pending.request, response)

    def settle_pending_orders(self):
        self._assert_main()
        remaining, cache = [], {}
        for pending in self._pending_settlements:
            if not self.settlement.step(pending, cache):
                remaining.append(pending)
                continue
            response = pending.response
            response["data"] = to_jsonable(pending.result)
            if pending.error and pending.kind != "cancel":
                response["server_error"] = pending.error
            response["handled_at"] = datetime.datetime.now().isoformat()
            key = (self.account_id, pending.request["request_id"])
            self._remember(key, response, "settled")
            self._publish_response(pending.request, response)
        self._pending_settlements = remaining

    @staticmethod
    def _response(request):
        return {
            "schema_version": 1,
            "request_id": str(request.get("request_id") or ""),
            "account_id": str(request.get("account_id") or ""),
            "method": str(request.get("method") or ""),
            "ok": True,
            "data": None,
            "error": "",
            "handled_at": datetime.datetime.now().isoformat(),
        }

    def _error(self, request, message):
        response = self._response(request)
        response.update(ok=False, error=message)
        return response

    def _remember(self, key, response, state):
        with self._order_lock:
            self._order_requests[key].update(response=response, state=state)

    def _claim(self, key):
        with self._order_lock:
            entry = self._order_requests.get(key)
            if entry is not None:
                return entry
            # Never evict an unknown dispatched write to make space for another.
            if len(self._order_requests) >= 65536:
                raise RuntimeError("write deduplication capacity reached; restart only after reconciliation")
            self._order_requests[key] = {"state": "dispatching", "response": None}
            return None

    def _outcome(self, request):
        key = (self.account_id, str((request.get("params") or {}).get("request_id") or ""))
        with self._order_lock:
            entry = self._order_requests.get(key)
            return dict(entry) if entry else {"state": "unknown", "response": None}

    def process_request(self, request, publish=True):
        method = canonical_method(str(request.get("method") or ""))
        response = self._response(request)
        key = (self.account_id, str(request.get("request_id") or ""))
        claimed = False
        state = "settled"
        try:
            if not key[1] or str(request.get("account_id") or "") != self.account_id:
                raise ValueError("request_id and bound account_id are required")
            params = request.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            if method in LISTENER_DEFERRED_METHODS:
                self._assert_main()
            if method in ORDER_METHODS:
                existing = self._claim(key)
                if existing is not None:
                    response = existing["response"] or self._error(
                        request, "RequestInFlight: outcome unknown; do not resubmit"
                    )
                    if publish:
                        self._publish_response(request, response)
                    return response
                claimed = True
            deadline = request_deadline(request)
            if (
                method not in {"cancel_order", "cancel_orders_batch"}
                and deadline is not None
                and time.time() >= deadline
            ):
                state = "refused"
                raise TimeoutError("RequestExpired: not dispatched")
            if method == "get_request_outcome":
                result = self._outcome(request)
            else:
                with dispatch_deadline(deadline):
                    result = self.handlers.handle(method, params)
            if isinstance(result, PendingDownload):
                result.request, result.response, result.deadline = request, response, deadline
                self._pending_downloads.append(result)
                return None
            if isinstance(result, PendingSettlement):
                result.request, result.response = request, response
                self._pending_settlements.append(result)
                self._remember(key, None, "dispatched")
                return None
            response["data"] = to_jsonable(result)
        except Exception as exc:
            if isinstance(exc, TimeoutError) and str(exc) == "RequestExpired: not dispatched":
                state = "refused"
                response["data"] = {
                    "server_now": time.time(),
                    "received_at": request.get("_received_at"),
                    "deadline_at": request.get("deadline_at"),
                    "timeout_seconds": request.get("timeout_seconds"),
                }
            response.update(ok=False, error="%s: %s" % (type(exc).__name__, exc))
        if claimed:
            self._remember(key, response, state)
        if publish:
            self._publish_response(request, response)
        return response

    def _publish_response(self, request, response):
        self._transport.send_response(request, response)
