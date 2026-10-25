"""One-shot asynchronous trading requests; no automatic retries."""

import itertools
import queue
import threading

from .client_objects import CompatObject


class AsyncOperations:
    def __init__(self, trader):
        self.trader = trader
        self._sequence = itertools.count(1)
        self._jobs = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._worker = threading.Thread(target=self._run, name="qmtairlock-async", daemon=True)
        self._worker.start()

    def submit(self, kind, function, identity):
        with self._lock:
            if self._closed:
                raise RuntimeError("trader is closed")
            seq = next(self._sequence)
            self.trader._callbacks.begin_async(seq, identity)
            self._jobs.put((seq, kind, function))
            return seq

    def close(self):
        with self._lock:
            self._closed = True
        self._jobs.put(None)
        if self._worker is not threading.current_thread():
            self._worker.join(timeout=1)

    def _run(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            seq, kind, function = job
            response = CompatObject(
                seq=seq,
                account_id=self.trader.client.account_id,
                order_id=-1,
                order_sysid="",
                cancel_result=-1,
                error_id=0,
                error_msg="",
            )
            try:
                if self._closed:
                    raise RuntimeError("request cancelled before dispatch: trader is closed")
                result = function()
                if kind == "order":
                    response.order_sysid = str(result.get("order_sys_id") or "")
                    response.order_id = self.trader._order_id(response.order_sysid)
                    response.order_remark = str(result.get("user_order_id") or "")
                    response.result = result
                else:
                    response.cancel_result = result
            except Exception as exc:
                response.error_id = -1
                response.error_msg = str(exc)
                response.request_id = getattr(exc, "request_id", "")
            name = "on_order_stock_async_response" if kind == "order" else "on_cancel_order_stock_async_response"
            self.trader._callbacks.finish_async(seq, name, response)
