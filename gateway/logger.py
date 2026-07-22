"""Compact bounded in-memory gateway log."""

from config import LOG_CAPACITY
from utils import iso_time


class GatewayLogger:
    def __init__(self, capacity=LOG_CAPACITY):
        self.capacity = capacity
        self._items = []
        self._next = 0

    def _add(self, level, message):
        entry = (iso_time(), level, str(message))
        if len(self._items) < self.capacity:
            self._items.append(entry)
        else:
            self._items[self._next] = entry
            self._next = (self._next + 1) % self.capacity
        print("[%s] %s" % (level, message))

    def info(self, message):
        self._add("INFO", message)

    def warning(self, message):
        self._add("WARNING", message)

    def error(self, message):
        self._add("ERROR", message)

    def entries(self, limit=50):
        """Materialize dictionaries only when an API consumer requests logs."""
        count = min(max(0, limit), len(self._items))
        if not count:
            return []
        total = len(self._items)
        start = self._next if total == self.capacity else 0
        start = (start + total - count) % total
        result = []
        for offset in range(count):
            item = self._items[(start + offset) % total]
            result.append({"timestamp": item[0], "level": item[1],
                           "message": item[2]})
        return result

    def trim(self, keep=50):
        """Release old records during critical heap pressure."""
        count = min(max(0, keep), len(self._items))
        if count == len(self._items):
            return
        total = len(self._items)
        start = self._next if total == self.capacity else 0
        start = (start + total - count) % total if total else 0
        retained = []
        for offset in range(count):
            retained.append(self._items[(start + offset) % total])
        self._items = retained
        self._next = 0

