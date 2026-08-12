"""Simple in-memory rate limiter for dangerous API endpoints."""

import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_calls: int = 10, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window = window_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str = "global") -> bool:
        now = time.monotonic()
        calls = self._calls[key]
        # Remove expired entries
        self._calls[key] = [t for t in calls if now - t < self.window]
        if len(self._calls[key]) >= self.max_calls:
            return False
        self._calls[key].append(now)
        return True


_limiters: dict[str, RateLimiter] = {}


def get_limiter(name: str, max_calls: int = 10, window: int = 60) -> RateLimiter:
    if name not in _limiters:
        _limiters[name] = RateLimiter(max_calls, window)
    return _limiters[name]
