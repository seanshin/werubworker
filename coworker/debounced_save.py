"""Coalescing file writer for JSON stores.

Batches rapid writes into a single disk flush. When ``trigger()`` is called
multiple times within the coalesce window, only one actual write runs — at the
**end** of the window.  The first ``trigger()`` schedules the write; subsequent
calls within the window are no-ops (the scheduled write will capture the latest
state).

Unlike a "trailing debounce" this guarantees the data reaches disk within
``delay`` seconds of the first mutation, so a process crash loses at most one
window's worth of changes.

Thread-safe.
"""

from __future__ import annotations

import threading
from typing import Callable

_DELAY = 0.15  # seconds — short enough for crash safety, long enough to batch


class DebouncedSaver:
    """Wraps a ``save_fn`` so rapid-fire calls result in one actual write.

    Usage::

        saver = DebouncedSaver(self._do_save)
        # In every mutating method:
        saver.trigger()
        # On shutdown / when data must be on disk right now:
        saver.flush()
    """

    def __init__(self, save_fn: Callable[[], None], delay: float = _DELAY) -> None:
        self._save_fn = save_fn
        self._delay = delay
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def trigger(self) -> None:
        """Schedule a save after the coalesce delay (if not already scheduled)."""
        with self._lock:
            if self._timer is not None:
                return  # write already scheduled — it'll pick up latest state
            self._timer = threading.Timer(self._delay, self._run)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """Cancel any pending timer and save immediately (synchronous)."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._run()

    def _run(self) -> None:
        with self._lock:
            self._timer = None
        try:
            self._save_fn()
        except Exception:
            pass  # best-effort persistence
