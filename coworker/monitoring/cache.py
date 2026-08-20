"""MetricsCache — 시계열 조회 결과 캐시 (성능개선 기획서 v2 Phase 3-1).

두 종류의 캐시를 담는다.

**latest 캐시** — ``query_latest()`` 결과를 짧은 TTL로 보관한다. 대시보드
새로고침과 30초 주기 알림 평가가 같은 질의를 반복하기 때문이다. 쓰기가
발생하면 해당 서버의 항목만 무효화하므로 같은 인스턴스 안에서는 최신
값이 보장된다.

TTL 상한이 ``MAX_LATEST_TTL``로 고정돼 있는 이유는 이 질의가 알림 평가
경로에 있기 때문이다. TTL이 스케줄러 틱 주기(30초)에 가까워지면 알림이
낡은 메트릭으로 평가될 수 있다.

**range 캐시** — 집계 테이블(5m/1h/1d)의 닫힌 구간은 다시 계산되지 않으므로
LRU로 보관한다. 형성 중인 버킷은 담지 않으며, 다운샘플링/정리처럼 과거
구간을 바꿀 수 있는 작업이 실행되면 전부 비운다.

캐시는 인스턴스 로컬이다. 다른 프로세스가 쓴 값은 TTL이 지나야 보이므로,
쓰기 즉시 반영이 필요한 경로에서는 ``invalidate_all()``을 호출해야 한다.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Iterable

# 전체 서버 조회(server_id 미지정)를 가리키는 키
ALL_SERVERS = ""

# latest TTL 상한 — 알림 평가가 이 질의를 쓰기 때문에 넘기면 안 된다
MAX_LATEST_TTL = 10.0


class MetricsCache:
    """시계열 조회 결과 캐시 (스레드 안전)."""

    def __init__(self, latest_ttl: float = MAX_LATEST_TTL, max_range_entries: int = 200):
        self._latest_ttl = min(latest_ttl, MAX_LATEST_TTL)
        self._max_range_entries = max_range_entries
        self._latest: dict[str, tuple[float, list[dict]]] = {}
        self._ranges: OrderedDict[tuple, list[dict]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------------
    # latest 캐시
    # ------------------------------------------------------------------

    def get_latest(self, key: str) -> list[dict] | None:
        """유효한 캐시가 있으면 복사본을, 없으면 None을 반환."""
        now = time.time()
        with self._lock:
            entry = self._latest.get(key)
            if entry is not None and now - entry[0] < self._latest_ttl:
                self.hits += 1
                return [dict(r) for r in entry[1]]
            self.misses += 1
            return None

    def set_latest(self, key: str, rows: list[dict]) -> None:
        with self._lock:
            self._latest[key] = (time.time(), [dict(r) for r in rows])

    def invalidate_latest(self, server_ids: Iterable[str]) -> None:
        """쓰기가 발생한 서버의 latest 항목과 전체 조회 항목을 무효화."""
        with self._lock:
            for server_id in server_ids:
                self._latest.pop(server_id, None)
            self._latest.pop(ALL_SERVERS, None)

    # ------------------------------------------------------------------
    # range 캐시
    # ------------------------------------------------------------------

    def get_range(self, key: tuple) -> list[dict] | None:
        with self._lock:
            rows = self._ranges.get(key)
            if rows is None:
                self.misses += 1
                return None
            self._ranges.move_to_end(key)
            self.hits += 1
            return [dict(r) for r in rows]

    def set_range(self, key: tuple, rows: list[dict]) -> None:
        with self._lock:
            self._ranges[key] = [dict(r) for r in rows]
            self._ranges.move_to_end(key)
            while len(self._ranges) > self._max_range_entries:
                self._ranges.popitem(last=False)

    def invalidate_ranges(self) -> None:
        """과거 구간을 바꿀 수 있는 작업(다운샘플링/정리) 후 호출."""
        with self._lock:
            self._ranges.clear()

    # ------------------------------------------------------------------
    # 전체 / 상태
    # ------------------------------------------------------------------

    def invalidate_all(self) -> None:
        with self._lock:
            self._latest.clear()
            self._ranges.clear()

    def stats(self) -> dict[str, Any]:
        """히트율과 캐시 크기 — 운영 중 캐시 효율 확인용."""
        with self._lock:
            total = self.hits + self.misses
            return {
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else 0.0,
                "latest_entries": len(self._latest),
                "range_entries": len(self._ranges),
                "latest_ttl": self._latest_ttl,
            }
