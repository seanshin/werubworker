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
        # Counters for `stats()`. A miss here is not free: it means rebuilding a TurnEngine,
        # so a low hit rate is the signal that `max_size`/`ttl` are too tight for how many
        # sessions are actually in flight.
        self._hits = 0
        self._misses = 0
        self._evicted_lru = 0
        self._evicted_ttl = 0

    # -- dict-compatible interface ------------------------------------------------

    def __setitem__(self, key: K, value: V) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        self._access[key] = time.monotonic()
        self._evict()

    def __getitem__(self, key: K) -> V:
        if key in self._data:
            self._hits += 1
        else:
            self._misses += 1
        value = self._data[key]
        self._data.move_to_end(key)
        self._access[key] = time.monotonic()
        return value

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        if key not in self._data:
            self._misses += 1
            return default
        self._hits += 1
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
            self._evicted_ttl += 1
        # 2) LRU size cap
        while len(self._data) > self._max_size:
            oldest_key, _ = self._data.popitem(last=False)
            self._access.pop(oldest_key, None)
            self._evicted_lru += 1

    # -- observability ------------------------------------------------------------

    def stats(self) -> dict[str, object]:
        """Size and hit rate. Eviction is split by cause because the two mean different
        things: LRU evictions say `max_size` is too small for the concurrent session count,
        TTL evictions are just idle sessions aging out and are expected."""
        looked_up = self._hits + self._misses
        return {
            "size": len(self._data),
            "max_size": self._max_size,
            "ttl_seconds": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / looked_up, 4) if looked_up else None,
            "evicted_lru": self._evicted_lru,
            "evicted_ttl": self._evicted_ttl,
        }
