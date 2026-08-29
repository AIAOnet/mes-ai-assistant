from __future__ import annotations
import threading
import time
from assistant.models import ModelMessage

class ConversationStore:
    def __init__(self, max_messages: int = 20, ttl_seconds: int = 3600) -> None:
        self.max_messages, self.ttl_seconds = max_messages, ttl_seconds
        self._items: dict[str, tuple[float, list[ModelMessage]]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> list[ModelMessage]:
        with self._lock:
            self._remove_expired()
            record = self._items.get(key)
            return list(record[1]) if record else []

    def replace(self, key: str, messages: list[ModelMessage]) -> None:
        with self._lock:
            self._remove_expired()
            self._items[key] = (time.time(), list(messages[-self.max_messages:]))

    def clear(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def _remove_expired(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        for key in [key for key, value in self._items.items() if value[0] < cutoff]:
            self._items.pop(key, None)
