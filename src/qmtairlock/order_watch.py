"""Bounded in-memory order callbacks; native timestamps govern identity matching."""

import collections
import threading
import time


class OrderWatchTable:
    MAX_ENTRIES = 5000
    TTL_SECONDS = 86400.0

    def __init__(self):
        self._lock = threading.Lock()
        self._by_remark = collections.OrderedDict()
        self._status_by_sysid = collections.OrderedDict()

    def note(self, event):
        try:
            sysid = str(event.get("order_sys_id") or "").strip()
            if not sysid:
                return
            remark = str(event.get("user_order_id") or event.get("remark") or "").strip()
            status = str(event.get("status") or "").strip()
            code = str(event.get("stock_code") or "").upper()
            action = str(event.get("action") or "").upper()
            native_time = float(event.get("order_time") or 0)
            received = time.monotonic()
            with self._lock:
                if remark:
                    self._by_remark[remark] = (received, sysid, code, action, native_time)
                    self._by_remark.move_to_end(remark)
                if status:
                    self._status_by_sysid[sysid] = (received, status)
                    self._status_by_sysid.move_to_end(sysid)
                for table in (self._by_remark, self._status_by_sysid):
                    while len(table) > self.MAX_ENTRIES:
                        table.popitem(last=False)
        except Exception:
            return

    def sysid_for_remark(self, remark, stock_code=None, action=None, not_before=None):
        with self._lock:
            entry = self._by_remark.get(str(remark or ""))
        if entry is None or time.monotonic() - entry[0] > self.TTL_SECONDS:
            return None
        _, sysid, code, side, native_time = entry
        if not_before is not None and (not native_time or native_time < int(not_before)):
            return None
        if stock_code and code != str(stock_code).upper():
            return None
        if action and side != str(action).upper():
            return None
        return sysid

    def status_for_sysid(self, order_sys_id):
        with self._lock:
            entry = self._status_by_sysid.get(str(order_sys_id))
        if entry is None or time.monotonic() - entry[0] > self.TTL_SECONDS:
            return None
        return entry[1]

    def stats(self):
        with self._lock:
            return {
                "remarks": len(self._by_remark),
                "statuses": len(self._status_by_sysid),
                "max_entries": self.MAX_ENTRIES,
                "ttl_seconds": self.TTL_SECONDS,
            }
