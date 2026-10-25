"""Polling execution callbacks with a silent baseline and serialized delivery."""

import queue
import threading

from .logging_setup import get_logger

log = get_logger("callbacks")


class ExecutionCallbacks:
    def __init__(self, trader, account, poll_interval=0.5):
        self.trader = trader
        self.account = account
        self.poll_interval = float(poll_interval)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._delivery = queue.Queue()
        self._orders = None
        self._trades = set()
        self._barriers = {}
        self._held = {}
        self._poller = None
        self._dispatcher = None

    def start(self):
        if self._poller is not None:
            return
        self._dispatcher = threading.Thread(target=self._dispatch, name="qmtairlock-callbacks", daemon=True)
        self._poller = threading.Thread(target=self._poll, name="qmtairlock-execution-poll", daemon=True)
        self._dispatcher.start()
        self._poller.start()

    def stop(self):
        self._stop.set()
        self._delivery.put(None)
        for thread in (self._poller, self._dispatcher):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1)

    def begin_async(self, seq, identity):
        with self._lock:
            self._barriers[seq] = dict(identity)
            self._held[seq] = []

    def finish_async(self, seq, callback_name, response):
        # Only this request's events wait for its response.
        with self._lock:
            self._delivery.put((callback_name, response))
            self._barriers.pop(seq, None)
            for event in self._held.pop(seq, []):
                self._delivery.put(event)

    @staticmethod
    def _matches(identity, row):
        if row.account_id != identity["account_id"] or row.account_type != identity["account_type"]:
            return False
        if identity.get("order_sysid"):
            return row.order_sysid == identity["order_sysid"]
        return (
            bool(identity.get("remark"))
            and row.order_remark == identity["remark"]
            and row.stock_code == identity.get("stock_code")
        )

    @staticmethod
    def _order_key(row):
        return (row.account_id, row.account_type, row.stock_code, row.order_sysid, getattr(row, "order_time", 0))

    @staticmethod
    def _trade_key(row):
        return (row.account_id, row.account_type, row.stock_code, row.traded_id, getattr(row, "traded_time", 0))

    def poll_once(self):
        snapshot = self.trader.query_execution_snapshot(self.account)
        orders = {self._order_key(row): row for row in snapshot["orders"] if row.order_sysid}
        trades = {self._trade_key(row): row for row in snapshot["trades"] if row.traded_id}
        with self._lock:
            if self._orders is None:
                self._orders = {key: vars(row).copy() for key, row in orders.items()}
                self._trades = set(trades)
                return
            events = []
            for key, row in orders.items():
                if self._orders.get(key) != vars(row):
                    events.append(("on_stock_order", row))
            for key, row in trades.items():
                if key not in self._trades:
                    events.append(("on_stock_trade", row))
            self._orders.update({key: vars(row).copy() for key, row in orders.items()})
            self._trades.update(trades)
            for event in events:
                owner = next(
                    (seq for seq, identity in self._barriers.items() if self._matches(identity, event[1])), None
                )
                if owner is None:
                    self._delivery.put(event)
                else:
                    self._held[owner].append(event)

    def _poll(self):
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                # A failed query is not an empty snapshot or a new baseline.
                log.warning("execution poll failed: %s", type(exc).__name__)
            self._stop.wait(self.poll_interval)

    def _dispatch(self):
        while not self._stop.is_set():
            event = self._delivery.get()
            if event is None:
                break
            name, value = event
            callback = getattr(self.trader.callback, name, None)
            if callable(callback):
                try:
                    callback(value)
                except Exception as exc:
                    log.warning("%s failed: %s", name, type(exc).__name__)
