"""LRU + TTL cache for TurnEngine instances.

Drop-in replacement for ``dict[str, TurnEngine]`` — supports ``get``, ``[]``,
``pop``, ``values()``, ``__contains__``, and ``__setitem__``.  Eviction runs on
every write (amortised O(1)); idle entries older than *ttl* seconds or entries
beyond *max_size* are removed oldest-access-first.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, Iterator, Optional, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class EngineCache(Generic[K, V]):
    def __init__(self, *, max_size: int = 50, ttl: int = 3600) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._data: OrderedDict[K, V] = OrderedDict()
        self._access: dict[K, float] = {}

    # -- dict-compatible interface ------------------------------------------------

    def __setitem__(self, key: K, value: V) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        self._access[key] = time.monotonic()
        self._evict()

    def __getitem__(self, key: K) -> V:
        value = self._data[key]
        self._data.move_to_end(key)
        self._access[key] = time.monotonic()
        return value

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        if key not in self._data:
            return default
        self._data.move_to_end(key)
        self._access[key] = time.monotonic()
        return self._data[key]

    def pop(self, key: K, *args: V) -> V:
        self._access.pop(key, None)
        return self._data.pop(key, *args)

    def values(self) -> Iterator[V]:
        return iter(self._data.values())

    def items(self):
        return self._data.items()

    def keys(self):
        return self._data.keys()

    def __len__(self) -> int:
        return len(self._data)

    # -- eviction -----------------------------------------------------------------

    def _evict(self) -> None:
        now = time.monotonic()
        # 1) TTL expiry
        expired = [k for k, t in self._access.items() if now - t > self._ttl]
        for k in expired:
            self._data.pop(k, None)
            self._access.pop(k, None)
        # 2) LRU size cap
        while len(self._data) > self._max_size:
            oldest_key, _ = self._data.popitem(last=False)
            self._access.pop(oldest_key, None)
