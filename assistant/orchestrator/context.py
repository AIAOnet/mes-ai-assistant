from __future__ import annotations
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class PageContext:
    page: str
    machine_id: str | None = None
    alarm_id: str | None = None
    production_order_id: str | None = None

    def as_dict(self) -> dict:
        return {key: value for key, value in {
            "page": self.page, "machine_id": self.machine_id, "alarm_id": self.alarm_id,
            "production_order_id": self.production_order_id,
        }.items() if value is not None}


class ConversationContextStore:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, tuple[float, PageContext]] = {}
        self._lock = threading.Lock()

    def merge(self, key: str, context: PageContext) -> PageContext:
        with self._lock:
            self._expire()
            previous = self._items.get(key)
            old = previous[1] if previous else PageContext(page=context.page)
            same_page = context.page == old.page
            merged = PageContext(
                page=context.page or old.page,
                machine_id=context.machine_id or old.machine_id,
                alarm_id=context.alarm_id or (old.alarm_id if same_page else None),
                production_order_id=context.production_order_id or (
                    old.production_order_id if same_page else None
                ),
            )
            self._items[key] = (time.time(), merged)
            return merged

    def clear(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def current(self, key: str) -> PageContext | None:
        with self._lock:
            self._expire()
            item = self._items.get(key)
            if item is None:
                return None
            self._items[key] = (time.time(), item[1])
            return item[1]

    def _expire(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        for key in [key for key, item in self._items.items() if item[0] < cutoff]:
            self._items.pop(key, None)
