"""Bounded, process-local memoization. Failed computations are never retained."""

from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
from threading import RLock
from time import monotonic


class ResultCache:
    def __init__(self, max_entries=256, ttl_seconds=900):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries = OrderedDict()
        self._lock = RLock()
        self._pending = {}

    def compute(self, key, factory):
        with self._lock:
            now = monotonic()
            expired = [k for k, (deadline, _) in self._entries.items() if deadline <= now]
            for expired_key in expired:
                del self._entries[expired_key]
            if key in self._entries:
                self._entries.move_to_end(key)
                return deepcopy(self._entries[key][1])
            owner = key not in self._pending
            if owner:
                self._pending[key] = Future()
            pending = self._pending[key]
        if not owner:
            return deepcopy(pending.result())
        try:
            value = factory()
            with self._lock:
                if self.max_entries > 0 and self.ttl_seconds > 0:
                    self._entries[key] = (monotonic() + self.ttl_seconds, deepcopy(value))
                    while len(self._entries) > self.max_entries:
                        self._entries.popitem(last=False)
                pending.set_result(deepcopy(value))
            return value
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self._lock:
                del self._pending[key]
