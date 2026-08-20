# WeruBWorker 성능 개선 기획서 v2

> **버전**: v2.0 (2026-08-20)
> **대상**: WeruBWorker v2.3.3+
> **목표**: 대규모 운영 환경(200+ 서버, 50+ 동시 사용자)에서의 응답성·처리량·안정성 확보

---

## 1. 현황 분석

### 1.1 이전 성능 개선 (v0.2.0 ~ v0.3.0) 성과

| 영역 | 개선 전 | 개선 후 | 감소율 |
|------|---------|---------|--------|
| 메인 JS 번들 | 734 KB | 361 KB | -50.8% |
| 빌드 산출물 | ~2.9 MB | ~1.1 MB | -62% |
| Python 테스트 | 38초 | 19초 | -50% |
| 메트릭 쓰기 (100서버) | - | < 1초 | 기준 확보 |
| 알림 평가 (50규칙×100서버) | - | < 1초 | 기준 확보 |

### 1.2 현재 병목 지점

| 병목 | 현상 | 원인 | 영향도 |
|------|------|------|--------|
| **SQLite 단일 Writer** | 쓰기 경합 시 대기 | WAL 모드도 쓰기는 직렬 | 높음 |
| **해시체인 쓰기 비용** | append마다 SELECT+INSERT 2회 | 이전 hash 조회 필요 | 중간 |
| **메트릭 수집 직렬화** | SSH 수집 세마포어 10개 제한 | `asyncio.Semaphore(10)` | 중간 |
| **도구 실행 스레드 풀** | 동시 8개 제한 | `ThreadPoolExecutor(8)` | 중간 |
| **다운샘플링 풀 스캔** | 대량 raw 데이터 집계 | 전체 미집계 구간 스캔 | 낮음 |
| **MCP 도구 지연 초기화** | 첫 호출 시 0.5~1초 지연 | 지연 싱글톤 패턴 | 낮음 |
| **보안 필터 정규식** | 매 audit record마다 14패턴 | 순차 매칭 | 낮음 |

---

## 2. 개선 계획

### Phase 1: 쓰기 경합 해소 — SQLite 최적화

> **목표**: 쓰기 처리량 3배 향상 (100/초 → 300/초)

#### 1-1. 배치 쓰기 (Write Batching)

**대상 파일**: `coworker/monitoring/timeseries.py`, `coworker/audit.py`, `coworker/monitoring/audit_ops.py`

| 작업 | 설명 |
|------|------|
| 쓰기 버퍼 도입 | 메트릭/감사 이벤트를 메모리 큐에 수집, 100ms 또는 50건 단위로 일괄 INSERT |
| `executemany()` 활용 | 단건 `execute()` → `executemany()`로 변경, WAL 트랜잭션 1회로 통합 |
| 해시체인 배치 | 버퍼 내 이벤트를 연쇄 해시 계산 후 일괄 INSERT (SELECT 1회로 감소) |

```python
# 배치 쓰기 패턴
class BatchWriter:
    def __init__(self, flush_interval=0.1, flush_size=50):
        self._buffer = []
        self._timer = None

    def enqueue(self, record):
        self._buffer.append(record)
        if len(self._buffer) >= self._flush_size:
            self._flush()

    def _flush(self):
        with self._lock:
            conn.executemany(INSERT_SQL, self._buffer)
            self._buffer.clear()
```

#### 1-2. WAL 체크포인트 제어

**대상 파일**: `coworker/monitoring/timeseries.py`

| 작업 | 설명 |
|------|------|
| 자동 체크포인트 임계값 조정 | `PRAGMA wal_autocheckpoint=1000` (기본 1000 → 유지 또는 2000) |
| 수동 체크포인트 스케줄 | 유휴 시간에 `PRAGMA wal_checkpoint(TRUNCATE)` 실행 |
| 페이지 크기 최적화 | `PRAGMA page_size=8192` (기본 4096, 시계열 데이터에 유리) |

#### 1-3. 커넥션 풀링

**대상 파일**: `coworker/monitoring/audit_ops.py`

| 현재 | 개선 |
|------|------|
| 매 호출마다 `sqlite3.connect()` | 스레드 로컬 커넥션 풀 (최대 4개) 재사용 |
| 커넥션 생성 오버헤드 | `_connect()` 호출 횟수 90% 감소 |

---

### Phase 2: 비동기 처리 강화

> **목표**: 200서버 동시 수집 시간 50% 단축

#### 2-1. 수집 병렬도 확대

**대상 파일**: `coworker/monitoring/collector.py`

| 현재 | 개선 |
|------|------|
| `Semaphore(10)` | 설정 가능: `CollectorConfig.parallel_workers` (기본 20, 최대 50) |
| SSH 타임아웃 15초 | 서버별 적응형 타임아웃 (성공 이력 기반, 5~30초) |

#### 2-2. 도구 실행 풀 확대

**대상 파일**: `coworker/server/run.py`

| 현재 | 개선 |
|------|------|
| `ThreadPoolExecutor(8)` | CPU 코어 기반 동적 조정: `min(32, os.cpu_count() * 4)` |
| 모든 도구 동일 풀 | 위험도별 분리: 일반 풀 + 위험 작업 전용 풀 (승인 대기 블로킹 방지) |

#### 2-3. WebSocket 메시지 압축

**대상 파일**: `coworker/server/app.py`

| 작업 | 설명 |
|------|------|
| per-message deflate | WebSocket 압축 활성화 (대형 메트릭 응답 60% 감소) |
| 델타 전송 | 대시보드 갱신 시 변경분만 전송 (전체 → diff) |

---

### Phase 3: 캐싱 계층 강화

> **목표**: 반복 조회 응답 시간 80% 단축

#### 3-1. 메트릭 조회 캐시

**신규 파일**: `coworker/monitoring/cache.py`

| 작업 | 설명 |
|------|------|
| 최신 메트릭 캐시 | `query_latest()` 결과를 TTL 10초로 캐시 (대시보드 새로고침 최적화) |
| 시간 범위 캐시 | 완료된 집계 구간(5m/1h/1d)은 불변 → 영구 캐시 |
| 캐시 무효화 | `record()`/`record_batch()` 호출 시 관련 서버의 latest 캐시만 무효화 |

```python
class MetricsCache:
    def __init__(self, ttl_latest=10, max_range_entries=200):
        self._latest: dict[str, tuple[float, Any]] = {}  # server_id → (ts, data)
        self._ranges: OrderedDict = OrderedDict()         # (sid, start, end, table) → data
```

#### 3-2. 알림 규칙 인메모리 캐시

**대상 파일**: `coworker/monitoring/alerting.py`

| 현재 | 개선 |
|------|------|
| 매 `evaluate()` 시 `list_rules()` SQL 조회 | 규칙을 메모리에 캐시, 변경 시만 리로드 |
| 규칙 변경 빈도 낮음 (시간 단위) | 캐시 히트율 99%+ 예상 |

#### 3-3. MCP 도구 사전 초기화

**대상 파일**: `coworker/mcp/monitoring_server.py`

| 현재 | 개선 |
|------|------|
| 지연 싱글톤 (첫 호출 0.5초) | 서버 시작 시 백그라운드 워밍업 (`asyncio.create_task`) |
| 각 `_get_*()` 독립 호출 | 병렬 초기화 (`asyncio.gather`) |

---

### Phase 4: 감사 로그 성능 최적화

> **목표**: 해시체인 오버헤드 50% 감소

#### 4-1. 해시체인 메모리 캐시

**대상 파일**: `coworker/audit.py`, `coworker/monitoring/audit_ops.py`

| 현재 | 개선 |
|------|------|
| 매 `append()` 시 `SELECT hash ORDER BY id DESC LIMIT 1` | 마지막 해시를 인스턴스 변수로 유지 |
| SELECT + INSERT = 2회 I/O | INSERT만 1회 I/O |

```python
class AuditStore:
    def __init__(self, ...):
        ...
        self._last_hash = self._load_last_hash()

    def append(self, event):
        ...
        current_hash = HashChain.compute_hash(self._last_hash, ...)
        # INSERT만 실행 (SELECT 생략)
        self._last_hash = current_hash
```

#### 4-2. 민감정보 필터 최적화

**대상 파일**: `coworker/security/sensitive_filter.py`

| 현재 | 개선 |
|------|------|
| 14개 패턴 순차 매칭 | 합성 정규식 (`|` 결합)으로 1회 매칭 |
| 짧은 문자열에도 전체 스캔 | 길이 임계값(20자 미만) 이하 스킵 |

```python
# 합성 패턴 — 1회 매칭으로 14패턴 커버
_COMBINED = re.compile("|".join(p.pattern for p, _ in _PATTERNS))

def sanitize_text(text):
    if len(text) < 20:
        return text  # 키/토큰은 최소 20자
    if not _COMBINED.search(text):
        return text  # 빠른 불일치 탈출
    # 개별 패턴 적용 (매칭된 경우만)
    ...
```

#### 4-3. 체인 검증 스트리밍

**대상 파일**: `coworker/security/hash_chain.py`

| 현재 | 개선 |
|------|------|
| `verify_chain()` 전체 로드 | 커서 기반 스트리밍 검증 (메모리 O(1)) |
| 100만 건 시 OOM 위험 | 청크 단위 검증 (1000건씩) |

---

### Phase 5: 프론트엔드 추가 최적화

> **목표**: 대시보드 FCP 1초 이내, 실시간 갱신 지연 < 500ms

#### 5-1. 대시보드 가상 스크롤

**대상 파일**: `surfaces/react/src/views/MonitoringView.tsx`

| 작업 | 설명 |
|------|------|
| 감사 로그 테이블 | 가상 스크롤 적용 (react-window), DOM 노드 50개 고정 |
| 인시던트 목록 | 무한 스크롤 + 페이지네이션 API |

#### 5-2. 실시간 갱신 최적화

| 현재 | 개선 |
|------|------|
| 폴링 30초/15초 | WebSocket push 이벤트로 즉시 갱신 (이미 인프라 존재) |
| 전체 데이터 재조회 | 델타 이벤트 (`metric_updated`, `alert_fired`) 수신 시 상태 패치 |

#### 5-3. 청크 로딩

| 작업 | 설명 |
|------|------|
| 보안 뷰 lazy load | 보안 대시보드를 `React.lazy()`로 분리 (초기 번들에서 제외) |
| 차트 라이브러리 동적 import | 차트가 보이는 시점에 로드 |

---

### Phase 6: 운영 안정성

> **목표**: 장기 운영(30일+) 시 메모리/디스크 안정성 보장

#### 6-1. 메모리 누수 방지

| 작업 | 설명 |
|------|------|
| 엔진 캐시 모니터링 | LRU 캐시(50개) 크기 + 히트율 메트릭 노출 |
| 수집기 실패 맵 정리 | `_failures` dict에 TTL 추가 (1시간 후 자동 제거) |
| WebSocket 연결 추적 | 좀비 연결 감지 + 강제 종료 (ping/pong 60초) |

#### 6-2. 디스크 관리 자동화

| 작업 | 설명 |
|------|------|
| 다운샘플링 + 정리 스케줄 | 일 1회 자동: downsample → prune → WAL checkpoint |
| 감사 로그 보관 정책 | ops_audit 365일, audit_events 90일 자동 정리 |
| 백업 자동 정리 | `backup.prune()` 주기 실행 (30일/50건 초과 삭제) |

#### 6-3. 헬스 셀프체크

| 작업 | 설명 |
|------|------|
| DB 무결성 | 일 1회 `PRAGMA integrity_check` 실행 |
| 해시체인 검증 | 일 1회 `verify_chain()` 자동 실행, 실패 시 알림 |
| 디스크 사용량 알림 | monitoring.db 1GB 초과 시 경고 |

---

## 3. 구현 우선순위

| 순서 | Phase | 핵심 효과 | 난이도 | 상태 |
|------|-------|----------|--------|------|
| **1** | 4-1 해시체인 메모리 캐시 | SELECT 제거, 쓰기 50% 가속 | 낮음 | ✅ v2.3.4 |
| **2** | 1-1 배치 쓰기 | 쓰기 처리량 3배 | 중간 | ✅ 완료 (단건 7.6×, 버퍼 55×) |
| **3** | 3-2 알림 규칙 캐시 | 평가 속도 10배 | 낮음 | ✅ v2.3.4 |
| **4** | 4-2 민감정보 필터 최적화 | 패턴 매칭 5배 가속 | 낮음 | ✅ v2.3.4 |
| **5** | 2-1 수집 병렬도 확대 | 200서버 수집 50% 단축 | 낮음 | ✅ 완료 (기본 20, 적응형 타임아웃) |
| **6** | 3-1 메트릭 조회 캐시 | 대시보드 응답 80% 단축 | 중간 | ✅ 완료 (2M행 기준 138ms→0.02ms) |
| **7** | 1-3 커넥션 풀링 | 커넥션 생성 90% 감소 | 중간 | ✅ 완료 (audit_ops v2.3.4, timeseries 1-1과 함께) |
| **8** | 6-2 디스크 관리 자동화 | 장기 안정성 | 낮음 | ⬜ 미착수 |
| **9** | 2-3 WebSocket 압축 | 네트워크 60% 절감 | 낮음 | ⬜ 미착수 |
| **10** | 5-1 가상 스크롤 | 대규모 로그 렌더링 | 중간 | ⬜ 미착수 |
| **11** | 6-1 메모리 누수 방지 | 장기 안정성 | 중간 | ⬜ 미착수 |
| **12** | 4-3 체인 검증 스트리밍 | 대규모 DB 검증 | 중간 | ✅ v2.3.4 |

> 1-2 WAL 체크포인트 제어 중 `synchronous=NORMAL`·`page_size=8192`는 1-1과 함께 적용됨.
> 수동 체크포인트 스케줄은 6-2 디스크 관리 자동화와 함께 처리 예정.

---

## 4. 성능 목표 수치

| 지표 | 현재 | 목표 | 비고 |
|------|------|------|------|
| 메트릭 쓰기 (100서버) | < 1초 | < 0.3초 | 배치 쓰기 |
| 메트릭 쓰기 (300서버) | 미측정 | < 1초 | 배치 + 풀링 |
| 알림 평가 (50규칙×200서버) | 미측정 | < 1초 | 규칙 캐시 |
| 대시보드 latest 조회 | ~200ms | < 50ms | 메트릭 캐시 |
| 감사 로그 append | ~2ms | < 1ms | 해시 캐시 + 배치 |
| SSH 수집 (200서버) | ~120초 | < 60초 | 병렬 20→ |
| 해시체인 검증 (100만 건) | OOM 위험 | < 30초, O(1) 메모리 | 스트리밍 |
| FCP (대시보드) | ~1.5초 | < 1초 | lazy load |

---

## 5. 검증 계획

### 성능 테스트 추가 항목

```python
# tests/test_performance_v2.py

def test_batch_write_300_servers():
    """300서버 배치 쓰기 < 1초."""

def test_audit_append_with_cache():
    """해시체인 캐시 적용 후 1000건 append < 1초."""

def test_alert_eval_200_servers():
    """50규칙 × 200서버 평가 < 1초."""

def test_metrics_cache_hit():
    """캐시 히트 시 latest 조회 < 5ms."""

def test_chain_verify_streaming_1m():
    """100만 건 체인 스트리밍 검증 — 메모리 < 50MB."""

def test_concurrent_writes_20_threads():
    """20스레드 동시 쓰기 안정성 (배치 모드)."""
```

### 프로파일링 도구

| 도구 | 용도 |
|------|------|
| `cProfile` + `snakeviz` | Python 함수 호출 프로파일링 |
| `memory_profiler` | 메모리 사용량 추적 |
| `sqlite3_analyzer` | SQLite 페이지/인덱스 효율 분석 |
| Lighthouse CI | 프론트엔드 FCP/LCP/CLS |

---

## 6. 버전 태깅

| 태그 | 포함 Phase |
|------|-----------|
| v2.3.4 | Phase 4 (감사 로그 최적화) |
| v2.3.5 | Phase 1 (SQLite 배치 쓰기) + Phase 3 (캐싱) |
| v2.3.6 | Phase 2 (비동기 강화) + Phase 6 (안정성) |
| v2.3.7 | Phase 5 (프론트엔드) |

---

*작성: 2026-08-20 · WeruBWorker 성능 개선 기획서 v2*
