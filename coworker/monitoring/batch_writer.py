"""BatchWriter — 버퍼링 후 일괄 INSERT를 수행하는 쓰기 버퍼.

단건 INSERT는 매번 트랜잭션 커밋 비용(WAL fsync 포함)을 지불한다.
레코드를 메모리 큐에 모아 ``executemany()`` 한 번으로 처리하면 그 비용이
버퍼 전체에 분산된다.

플러시 조건은 두 가지이며 먼저 도달한 쪽이 적용된다.

- 버퍼 길이가 ``flush_size``에 도달
- 첫 레코드가 들어온 뒤 ``flush_interval``초 경과 (데몬 타이머)

플러시 실패 시 해당 배치는 폐기하고 ``dropped``에 누적한다. 재버퍼링하면
실패가 반복될 때 버퍼가 무한히 커지므로, 메트릭처럼 유실이 허용되는
데이터를 전제로 한 선택이다. 감사 로그처럼 유실이 허용되지 않는 경로는
배치를 켜지 말고 단건 경로를 쓰거나 ``flush()``로 즉시 반영을 보장해야
한다.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)


class BatchWriter:
    """쓰기 레코드를 모아 ``flush_fn``으로 일괄 전달하는 버퍼."""

    def __init__(
        self,
        flush_fn: Callable[[list[Any]], None],
        flush_size: int = 50,
        flush_interval: float = 0.1,
    ) -> None:
        if flush_size < 1:
            raise ValueError("flush_size must be >= 1")
        self._flush_fn = flush_fn
        self._flush_size = flush_size
        self._flush_interval = flush_interval
        self._buffer: list[Any] = []
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._closed = False
        self.dropped = 0

    # ------------------------------------------------------------------
    # 쓰기
    # ------------------------------------------------------------------

    def enqueue(self, record: Any) -> None:
        """레코드 1건을 버퍼에 넣는다. 임계값 도달 시 즉시 플러시."""
        with self._lock:
            if self._closed:
                raise RuntimeError("BatchWriter is closed")
            self._buffer.append(record)
            self._after_append()

    def enqueue_many(self, records: Iterable[Any]) -> None:
        """레코드 여러 건을 한 번에 버퍼에 넣는다."""
        with self._lock:
            if self._closed:
                raise RuntimeError("BatchWriter is closed")
            self._buffer.extend(records)
            self._after_append()

    def _after_append(self) -> None:
        """버퍼 추가 직후의 플러시/타이머 결정 (락 보유 상태에서 호출)."""
        if len(self._buffer) >= self._flush_size:
            self._flush_locked()
        elif self._timer is None and self._flush_interval > 0:
            self._start_timer()

    # ------------------------------------------------------------------
    # 플러시
    # ------------------------------------------------------------------

    def flush(self) -> int:
        """버퍼를 즉시 비운다. 반환값은 실제로 기록된 건수."""
        with self._lock:
            return self._flush_locked()

    def _flush_locked(self) -> int:
        self._cancel_timer()
        if not self._buffer:
            return 0
        batch = self._buffer
        self._buffer = []
        try:
            self._flush_fn(batch)
        except Exception:
            self.dropped += len(batch)
            log.exception("batch flush failed — %d record(s) dropped", len(batch))
            return 0
        return len(batch)

    def _start_timer(self) -> None:
        timer = threading.Timer(self._flush_interval, self._on_timer)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _on_timer(self) -> None:
        with self._lock:
            self._timer = None
            self._flush_locked()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # ------------------------------------------------------------------
    # 상태 / 수명주기
    # ------------------------------------------------------------------

    @property
    def pending(self) -> int:
        """아직 플러시되지 않은 레코드 수."""
        with self._lock:
            return len(self._buffer)

    def close(self) -> None:
        """남은 버퍼를 플러시하고 더 이상 받지 않는다."""
        with self._lock:
            self._flush_locked()
            self._cancel_timer()
            self._closed = True

    def __enter__(self) -> BatchWriter:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
