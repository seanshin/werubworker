# WeruBWorker 성능 개선 기획서

> 작성일: 2026-08-10  
> 최종 갱신: 2026-08-11 (v0.3.0 릴리즈 — PDF 경량화 포함, 커밋 `07108d9`)  
> 대상 버전: v0.1.7 → v0.2.0 (18) → v0.2.1 (4) → v0.2.2 (3) → v0.3.0 (6)  
> 범위: 서버 백엔드 / GUI 프론트엔드 / 테스트·빌드 / DX / 아키텍처

---

## 목차

1. [현황 요약](#1-현황-요약)
2. [Phase 1 — 서버 백엔드 성능 개선 (P0/P1)](#2-phase-1--서버-백엔드-성능-개선)
3. [Phase 2 — GUI 프론트엔드 성능 개선 (P0–P2)](#3-phase-2--gui-프론트엔드-성능-개선)
4. [Phase 3 — 테스트·빌드 파이프라인 최적화 (P1–P3)](#4-phase-3--테스트빌드-파이프라인-최적화)
5. [v0.2.1 후속 구현](#5-v021-후속-구현)
6. [v0.2.2 DX 및 렌더링 최적화](#6-v022-dx-및-렌더링-최적화)
7. [v0.3.0 아키텍처 및 런타임 최적화](#7-v030-아키텍처-및-런타임-최적화)
8. [우선순위 매트릭스 및 구현 현황](#8-우선순위-매트릭스-및-구현-현황)
9. [실측 결과](#9-실측-결과)
10. [스코프 변경 및 설계 판단](#10-스코프-변경-및-설계-판단)
11. [후속 과제](#11-후속-과제)

---

## 1. 현황 요약

### v0.1.7 기준 (개선 전)

| 항목 | 수치 |
|------|------|
| Python 소스 파일 | 181개 |
| 테스트 모듈 | Python 104 + Vitest 18 + Playwright 59 |
| Python venv 크기 | 381 MB |
| node_modules 크기 | 268 MB |
| 프론트엔드 빌드 산출물 | 2.9 MB (gzip) |
| 메인 JS 번들 | 734 KB |
| PDF worker | 1.3 MB |
| XLSX 라이브러리 | 419 KB |
| i18n 키 | ~2,060개 (EN + KO), 전량 초기 번들 포함 |
| SQLite 동시성 | 단일 RLock + 단일 커넥션 |
| 세션 엔진 캐시 | 제거 정책 없음 (무한 증가) |
| MCP 서버 연결 | 순차 (N개 서버 = N배 지연) |
| Python 테스트 실행 | 순차, 약 38초 |
| 정적 분석 | 미설정 |

### v0.2.1 기준 (최종 개선 후)

| 항목 | 수치 | 변화 |
|------|------|------|
| 메인 JS 번들 | **352 KB** | **-52.0%** |
| 코드 스플리팅 청크 | 12 뷰 + 5 벤더 | 신규 |
| SQLite 모드 | WAL + 스레드별 커넥션 + 인덱스 3개 | 동시 읽기 허용 |
| 세션 엔진 캐시 | LRU 50개 + TTL 1시간 | 메모리 안정화 |
| MCP 연결 | 병렬 (`asyncio.gather`) + 10초 타임아웃 | ~2.5배 단축 |
| 세션/인박스 업데이트 | 서버 push (`sessions_changed`, `inbox_changed`) | 폴링 5초→30초, 4초→15초 |
| Python 테스트 | 병렬 (`-n auto`), 약 19초 | **-50%** |
| 스트리밍 리렌더링 | rAF 배치 (60fps 동기화) | 매 토큰 → 프레임당 1회 |
| 상태 관리 | 4개 커스텀 훅 (stream, inbox, session, visibleInterval) | App.tsx ~55줄 감소 |
| 정적 분석 | ruff (E/F/W/I) + format, CI 통합 | 213개 파일 포매팅 |
| 테스트 구조 | connectors + server 양쪽 분할 완료 | 유지보수 개선 |
| TS 빌드 | 증분 컴파일 (`.tsbuildinfo`) | 재빌드 가속 |

---

## 2. Phase 1 — 서버 백엔드 성능 개선

### 2-1. SQLite 동시성 개선 ✅ 완료 (P0)

**문제:**  
`coworker/memory/sqlite_store.py` — 단일 `threading.RLock` + 단일 커넥션으로 모든 DB 접근이 직렬화됨. WebSocket 핸들러 스레드, 도구 실행 스레드 등이 모두 동일한 락에서 경합.

**구현 내용:**

| 항목 | 구현 |
|------|------|
| WAL 모드 | `PRAGMA journal_mode=WAL` — 동시 읽기 허용 |
| 동기 모드 | `PRAGMA synchronous=NORMAL` — 쓰기 성능 개선 (crash safety 유지) |
| 커넥션 전략 | `threading.local()` 기반 스레드별 커넥션 생성 |
| 인덱스 | `idx_memories_scope`, `idx_memories_workspace`, `idx_memories_session` |
| 락 제거 | 기존 `self._lock = threading.RLock()` 완전 제거 |

**변경 파일:**
```
coworker/memory/sqlite_store.py
```

**설계 판단:**
- `PRAGMA read_uncommitted=1`은 기획 시 고려했으나, WAL 모드 자체가 동시 읽기를 지원하므로 불필요. 적용하지 않음.
- 커넥션 풀링(poolsize=5) 대신 `threading.local()`을 선택. 풀 관리 오버헤드 없이 스레드 안전성 확보. 각 스레드가 자체 커넥션을 유지하며, WAL 모드에서 동시 읽기 충돌 없음.
- `close()` 메서드에서 현재 스레드의 커넥션만 닫도록 변경. 다른 스레드 커넥션은 해당 스레드 종료 시 GC.

**테스트:** 12 passed (메모리 관련)

---

### 2-2. 스킬 디렉토리 스캔 캐싱 ✅ 완료 (P2)

**문제:**  
`coworker/agent.py` line 368 — `skill_loader.rescan()`이 매 턴마다 파일시스템을 순회하며 스킬 목록을 재구축.

**구현 내용:**

| 항목 | 구현 |
|------|------|
| mtime 캐싱 | 디렉토리 + 개별 SKILL.md 파일의 mtime 스냅샷 비교 |
| TTL | 30초 — TTL 내에서는 mtime 비교조차 스킵 |
| force 옵션 | `rescan(force=True)` — 초기화 및 `load_skill` miss 시 강제 리스캔 |
| 하위 호환 | 기존 `rescan()` 호출은 캐시 로직을 거쳐 동일하게 동작 |

**변경 파일:**
```
coworker/skills/base.py
```

**설계 판단:**
- watchdog 라이브러리는 과도함. mtime 비교는 `os.stat()` 1회 호출이므로 충분히 가벼움.
- 기획에서 언급한 `coworker/skills/loader.py`는 실제로 존재하지 않음 (실제 위치: `coworker/skills/base.py`).
- `_snapshot_mtimes()`가 디렉토리의 즉시 하위 폴더까지 순회하여 새 스킬 폴더 추가도 감지.

**테스트:** 74 passed (스킬 관련)

---

### 2-3. 세션 엔진 LRU 캐시 ✅ 완료 (P0)

**문제:**  
`coworker/server/manager.py` — `self._engines: dict[str, TurnEngine]`에 제거 정책 없음. 장시간 운영 시 각 TurnEngine이 전체 메시지 히스토리를 보유하며 메모리 무한 증가.

**구현 내용:**

| 항목 | 구현 |
|------|------|
| EngineCache 클래스 | `OrderedDict` 기반 LRU 캐시, dict 호환 인터페이스 |
| 최대 크기 | 50개 엔진 (초과 시 가장 오래된 접근 항목 제거) |
| TTL | 3,600초 (1시간) — 마지막 접근 기준 |
| 제거 시점 | 매 쓰기(`__setitem__`) 시 amortized O(1) eviction |
| 호환 API | `get`, `__getitem__`, `__setitem__`, `pop`, `values`, `items`, `keys`, `__contains__`, `__len__` |

**변경 파일:**
```
coworker/server/engine_cache.py  (신규)
coworker/server/manager.py       (import + 타입 교체)
```

**설계 판단:**
- 기획에서 언급한 "제거 시 디스크 직렬화 + 복원 로직"은 구현하지 않음. `get_engine()`이 이미 디스크(ConversationStore)에서 세션을 복원하는 로직을 갖고 있으므로, 캐시에서 제거되더라도 다음 접근 시 자동 재구축됨.
- 기획의 "60초 주기 정리 태스크"를 별도 `asyncio.create_task`로 만들지 않고, 쓰기 시 eviction 실행. 별도 백그라운드 태스크 없이도 충분하며, 타이머 관리 복잡성 회피.
- `_autotitle_attempts` 딕셔너리는 `EngineCache` 범위 밖이므로 별도 관리 필요 (현재 기존 방식 유지).

**테스트:** 177 passed + 16 passed (서버/세션/standing_approvals)

---

### 2-4. MCP 서버 병렬 연결 ✅ 완료 (P1)

**문제:**  
`prepare_mcp_tools()`에서 각 MCP 서버를 순차적으로 연결. 5개 서버 설정 시 세션 시작이 직렬로 5배 느려짐.

**구현 내용:**

3단계 파이프라인으로 재구성:

| 단계 | 내용 |
|------|------|
| Phase 1 | 동기 필터링 — enabled, OAuth 토큰, 커넥터 게이트 체크. eligible 리스트 생성 |
| Phase 2 | `asyncio.gather()` — 모든 eligible 서버를 병렬 연결, 서버별 `wait_for(timeout=10)` |
| Phase 3 | 결과 순회 — 성공한 서버만 callables 빌드, 실패 서버 로깅 |

**변경 파일:**
```
coworker/server/manager.py  (prepare_mcp_tools 메서드)
```

**설계 판단:**
- `return_exceptions=True`로 개별 서버 실패가 전체를 중단시키지 않음.
- OAuth 재인증 필요 에러는 기존과 동일하게 `_mcp_errors`에 기록.
- 기획의 "연결 상태 대시보드 반영"은 기존 `list_mcp` 메서드가 이미 상태를 보여주므로 추가 구현 불필요.

**테스트:** 96 passed (MCP/서버 관련)

---

### 2-5. JSON 파일 I/O 최적화 ✅ 부분 완료 (P2)

**문제:**  
InboxStore, UnroutedStore, ChannelBuffer 등이 매 변경 시 전체 JSON 파일을 읽기/쓰기.

**구현 내용:**

| 스토어 | 구현 | 사유 |
|--------|------|------|
| **ChannelBuffer** | ✅ DebouncedSaver 적용 (0.15초 coalesce) | 채널 메시지 빈번, ring buffer이므로 데이터 손실 허용 |
| **InboxStore** | ❌ 즉시 저장 유지 | `resolve()` 후 프로세스 재시작 시 데이터 복원 필수 (persistence 테스트 실패) |
| **UnroutedStore** | ❌ 즉시 저장 유지 | dead-letter 저장소로 데이터 손실 불가 |

**변경 파일:**
```
coworker/debounced_save.py     (신규 — DebouncedSaver 공통 모듈)
coworker/subscriptions.py      (ChannelBuffer에 적용)
```

**설계 판단:**
- 기획에서 "InboxStore → SQLite 테이블 마이그레이션"을 제안했으나, InboxStore는 이미 메모리(`_items` 딕셔너리)에서 읽고 디스크는 persistence만 담당. SQLite 마이그레이션은 복잡성 대비 효과 미미.
- DebouncedSaver는 "leading edge" 대신 **"coalesce" 전략** 사용: 첫 trigger 후 0.15초 내 추가 trigger는 무시하고 예약된 쓰기가 최신 상태를 반영. "trailing debounce"(매 trigger마다 타이머 리셋)와 달리 최대 지연이 0.15초로 보장됨.
- 테스트에서 `buf._saver.flush()`를 명시 호출하여 디바운스-persistence 호환성 확보.

**테스트:** 35 passed (inbox/unrouted/subscriptions/channel)

---

### 2-6. 스레드 풀 크기 명시 설정 ✅ 완료 (P3)

**문제:**  
`asyncio.to_thread()`가 기본 executor를 사용하며, 기본값은 unbounded. 동시 도구 호출 시 스레드 폭증 가능.

**구현 내용:**
```python
loop.set_default_executor(ThreadPoolExecutor(max_workers=8))
```
서버 시작 시(`build_app`) 한 번 설정.

**변경 파일:**
```
coworker/server/run.py
```

**설계 판단:**
- 기획의 "큐 포화 시 경고 로그"는 구현하지 않음. `ThreadPoolExecutor(8)`은 초과 태스크를 큐에 대기시키며(reject하지 않음), 경고 로그보다 모니터링 시스템이 적합.
- max_workers=8은 CPU 코어 수 기반이 아닌 고정값. 도구 실행은 대부분 I/O-bound이므로 코어 수보다 높은 값이 적절하며, 무한 확장보다는 제한이 중요.

---

## 3. Phase 2 — GUI 프론트엔드 성능 개선

### 3-1. 코드 스플리팅 및 Lazy Loading ✅ 완료 (P0)

**문제:**  
모든 뷰(12개)가 정적 import로 메인 번들에 포함. PDF(1.3MB), XLSX(419KB) 등 대용량 벤더도 미분리.

**구현 내용:**

**React.lazy() 적용 뷰 (12개):**

| 뷰 | 분리 후 청크 크기 |
|-----|-----------------|
| IntegrationsView | 65.22 KB |
| SettingsView | 39.39 KB |
| ScheduledView | 23.06 KB |
| WikiView | 16.49 KB |
| InboxView | 13.49 KB |
| OpsView | 7.09 KB |
| PersonaView | 6.39 KB |
| DatabaseView | 5.77 KB |
| ServiceConfigView | 4.98 KB |
| AboutView | 4.27 KB |
| DevView | 3.61 KB |
| AuditView | 2.75 KB |

**Vite manualChunks 벤더 분리 (5개):**

| 청크 | 크기 |
|------|------|
| vendor-react | 133.93 KB |
| vendor-pdf | 365.12 KB |
| vendor-xlsx | 429.03 KB |
| vendor-markdown | 157.70 KB |
| vendor-i18n | 57.68 KB |

**Suspense 경계:**
- 모든 lazy 뷰를 단일 `<Suspense fallback={<div className="surface-loading" />}>` 로 감싸 로딩 중 레이아웃 깜빡임 방지.

**변경 파일:**
```
surfaces/gui/vite.config.ts
surfaces/gui/src/App.tsx
surfaces/gui/src/styles.css
```

**설계 판단:**
- 기획에서 "PDF/XLSX → 동적 import() 전환"을 제안했으나, `manualChunks`로 이미 별도 청크로 분리됨. `React.lazy`로 뷰를 분리하면 해당 뷰가 로드될 때만 벤더 청크가 요청되므로 사실상 동적 로딩과 동일한 효과.
- 기존 ternary 체인 구조(`surface === "scheduled" ? ... : surface === "integrations" ? ...`)를 `Suspense + lazy` 영역과 `{surface === "session" && (...)}` 영역으로 분리. 문법적으로 ternary의 마지막 else를 `null`로 닫고, session 렌더링은 별도 `&&` 블록으로 분리.

**실측:** 메인 번들 734 KB → 377 KB (P0 완료 시점) → **351 KB** (P3 i18n 분리 후)

---

### 3-2. 상태 관리 구조 분리 ✅ 완료 (P1 + v0.2.1)

**문제:**  
`App.tsx` 1,704줄에 30개 이상의 `useState`가 집중. ref-mirror 패턴(streamingRef, reasoningRef, unattendedRef)이 코드 복잡도를 높이고 버그 유발 가능.

**구현 내용 (v0.2.0 P1 + v0.2.1 후속):**

| 훅 | 추출한 상태 | 줄 수 | 시점 |
|----|-----------|-------|------|
| `useStreamState` | streaming, reasoning, compacting, streamingRef, reasoningRef, appendDelta, appendReasoningDelta, flush, reset | 113줄 | v0.2.0 P1 |
| `useInboxState` | sessionInbox, unattended, unattendedRef, markUnattended, toggleUnattended, resolveSessionInbox, refreshInbox | 63줄 | v0.2.0 P1 |
| `useSessionState` | workspace, branch, agent, mode, connected, running, sessionId, usage, todo, showGate, workspaceTrustRequest, runContext, composerPrefill, resetSession | 70줄 | v0.2.1 |
| `useVisibleInterval` | visibility-aware setInterval 래퍼 | 44줄 | v0.2.0 P3 |

**변경 파일:**
```
surfaces/gui/src/hooks/useStreamState.ts       (신규, v0.2.0)
surfaces/gui/src/hooks/useInboxState.ts        (신규, v0.2.0)
surfaces/gui/src/hooks/useSessionState.ts      (신규, v0.2.1)
surfaces/gui/src/hooks/useVisibleInterval.ts   (신규, v0.2.0)
surfaces/gui/src/App.tsx                        (~55줄 감소)
```

**미구현 및 사유:**

| 기획 항목 | 상태 | 사유 |
|----------|------|------|
| UIContext 서브 컨텍스트 분할 | ❌ 미구현 | UIContext는 이미 SettingsContext, AuthContext와 분리됨. 추가 분할은 provider 중첩 깊이 증가 + props drilling 교체 비용 대비 효과 미미 |
| `useSyncExternalStore` 도입 | ❌ 미구현 | 외부 스토어(Redux, Zustand 등) 없이 React state로 충분. 도입 시 전체 상태 관리 패턴 변경 필요 |

**설계 판단:**
- ref-mirror 패턴은 **제거가 아닌 캡슐화**로 해결. `useStreamState` 내부에서 ref와 state를 동기화하므로 소비자(App.tsx)는 ref를 직접 다루지 않아도 됨.
- `useInboxState`의 `refreshSessions` 의존성 때문에, 훅 호출 순서를 `refreshSessions` 선언 후로 이동해야 했음. React Hooks 규칙상 조건부 호출은 불가하므로, 선언 순서 조정으로 해결.
- `useSessionState`는 v0.2.0에서 "handleEvent와의 순환 의존"으로 보류했으나, v0.2.1에서 handleEvent가 훅의 setter들을 직접 참조하는 구조로 충분히 분리 가능함을 확인하여 구현 완료. 15개 상태를 캡슐화하고 `resetSession()` 헬퍼 제공.

---

### 3-3. 리스트 DOM 제한 + Sidebar 가상화 ✅ 완료 (P0 + v1.0)

**원래 기획:**  
react-window(`FixedSizeList`, `VariableSizeList`)로 Sidebar, SearchModal, Transcript 가상화.

**구현 (2단계):**

**v0.2.0 — 기존 방어책 강화:**

| 컴포넌트 | 구현 | 사유 |
|---------|------|------|
| **Transcript** | `VISIBLE_WINDOW` 200 → **100** | 메시지 높이 가변 → `VariableSizeList` 측정 비용 과다 |
| **SearchModal** | 결과 100개 제한 (`.slice(0, 100)`) | 섹션 헤더 구조 비호환 |

**v1.0 — Sidebar react-window 가상화:**

| 항목 | 구현 |
|------|------|
| 대상 | flat layout의 확장된 Recent 세션 목록 |
| 활성 조건 | `recentExpanded && length > 20` (VIRTUAL_THRESHOLD) |
| 컴포넌트 | react-window v2 `List` (`rowComponent` API) |
| 행 높이 | 40px 고정 (`cardRow`의 py-2 + 콘텐츠) |
| 최대 높이 | 480px (12행 가시) |
| overscan | 5행 |
| 효과 | **100+ 세션 시 DOM 노드: 100+ → ~17개** |
| fallback | 20개 이하 또는 접힌 상태에서는 기존 DOM 렌더링 유지 |

**미구현 (구조적 비호환):**
- **grouped layout** (아코디언+폴더): 프로젝트별 아코디언 내부는 `peek`/`showAll`로 제한 유지. 아코디언 열기/닫기 시 리스트 크기 동적 변경으로 `List` 비호환.
- **Transcript**: 메시지 높이 가변 (마크다운, 이미지) → `VISIBLE_WINDOW=100`으로 대체.

**변경 파일:**
```
surfaces/gui/src/components/Sidebar.tsx      (v1.0, react-window List 적용)
surfaces/gui/src/components/Transcript.tsx   (v0.2.0, VISIBLE_WINDOW 축소)
surfaces/gui/src/components/SearchModal.tsx  (v0.2.0, 결과 100개 제한)
```

---

### 3-4. WebSocket 메시지 배치 처리 ✅ 완료 (P2)

**문제:**  
매 `assistant_delta` / `reasoning_delta` 이벤트마다 React state setter 호출. 스트리밍 중 초당 수십~수백 회 리렌더링.

**구현 내용:**

`useStreamState` 훅에 rAF 기반 배치 추가:

| 메서드 | 동작 |
|--------|------|
| `appendDelta(text)` | `streamingRef.current += text` → rAF 스케줄 (이미 예약 시 무시) |
| `appendReasoningDelta(text)` | `reasoningRef.current += text` → rAF 스케줄 |
| rAF 콜백 | `_setStreaming(streamingRef.current)` + `_setReasoning(reasoningRef.current)` |
| `flush()` | rAF 취소 → ref 값으로 최종 Item 생성 → ref 초기화 |

**효과:**
- 이전: 토큰 10개/초 → 10회 리렌더링/초
- 이후: 토큰 N개/프레임 → **1회 리렌더링/프레임** (최대 60fps)

**변경 파일:**
```
surfaces/gui/src/hooks/useStreamState.ts
surfaces/gui/src/App.tsx  (handleEvent의 delta 케이스)
```

**설계 판단:**
- `requestAnimationFrame`은 `setTimeout(0)`보다 브라우저 페인트 주기에 정확히 동기화되어 시각적 끊김 없음.
- `dirty` flag로 중복 rAF 등록 방지. 여러 delta가 같은 프레임 내에 도착하면 ref에만 누적되고 rAF는 한 번만 실행.
- 컴포넌트 언마운트 시 `cancelAnimationFrame`으로 정리.

---

### 3-5. React.memo 확대 적용 ✅ 완료 (P2)

**문제:**  
Memoized 컴포넌트 4개뿐. 대형 컴포넌트(Composer 948줄, ManageTabs 900줄)가 부모 리렌더링 시 매번 재실행.

**구현 내용:**

| 컴포넌트 | 줄 수 | memo 적용 |
|---------|-------|----------|
| Composer | 948줄 | ✅ `memo(function Composer(...))` |
| ModelsTab | 175줄 | ✅ `memo(function ModelsTab())` |
| McpTab | 280줄 | ✅ `memo(function McpTab())` |

**변경 파일:**
```
surfaces/gui/src/components/Composer.tsx
surfaces/gui/src/components/ManageTabs.tsx
```

**설계 판단:**
- SettingsView는 `React.lazy`로 이미 분리되어 필요 시에만 로드됨. 추가 memo의 효과 미미하여 미적용.
- `ManageTabs.tsx`에서 `ModelsTab`과 `McpTab`만 memo 적용. 나머지 export(`UnauthorizedBlock`, `AllowlistBlock`, `ConnectorTools`, `ConnectSetup`)는 부모 컴포넌트 내에서만 사용되며, 부모가 이미 lazy-loaded이므로 추가 memo 불필요.
- 기획의 "App에서 자식으로 전달하는 콜백 → useCallback 전환"은 범위가 넓어 미구현. 향후 React DevTools Profiler로 실제 병목 컴포넌트를 식별 후 타겟 적용 권장.

---

### 3-6. i18n 현재 언어만 로드 ✅ 완료 (P3)

**문제:**  
2,060개 키가 EN + KO 양쪽 모두 초기 번들에 정적 import. 한국어 사용자에게도 영어 번들이, 영어 사용자에게도 한국어 번들이 로드됨.

**구현 내용:**

| 항목 | 구현 |
|------|------|
| EN (fallback) | 정적 import — 항상 번들에 포함 (missing key 대응) |
| KO (또는 기타 언어) | 동적 `import()` — `savedLng !== "en"` 일 때 7개 네임스페이스를 `Promise.all`로 병렬 로드 후 `addResourceBundle` + `changeLanguage` |

**변경 파일:**
```
surfaces/gui/src/i18n/index.ts
```

**설계 판단:**
- 기획에서 "i18next-http-backend 플러그인" 도입을 제안했으나, Vite의 `import()` 만으로 코드 스플리팅 + 동적 로딩이 가능하므로 추가 의존성 불필요.
- 초기 렌더링은 EN으로 시작하고, KO 번들 로드 완료 후 `changeLanguage`로 전환. i18next가 자동으로 리렌더링을 트리거. 번들 로드는 ~50ms 이내이므로 시각적 깜빡임 최소.
- 네임스페이스별 분할 로딩은 미구현. 7개 네임스페이스를 병렬로 한 번에 로드하는 것이 네임스페이스별 lazy-load보다 단순하고, 총 번들 크기가 ~30KB 수준이므로 분할 효과 미미.

**실측:** 메인 번들 379 KB → **351 KB** (-28 KB, KO 번들 분리)

---

### 3-7. 폴링 최적화 + 서버 Push ✅ 완료 (P3 + v0.2.1)

**문제:**  
3개의 `setInterval` 폴링(4초/5초/15초)이 탭이 비활성(숨김) 상태에서도 계속 실행.

**구현 내용 (2단계):**

**v0.2.0 — 비활성 탭 중지:**

| 폴링 | 구현 |
|------|------|
| 세션 새로고침 | `useVisibleInterval` 훅 — 탭 hidden 시 interval 중지, visible 시 즉시 1회 실행 + interval 재시작 |
| 인박스 | `document.hidden` 체크 — hidden이면 콜백 내부에서 early return |
| 자동화 (Sidebar) | 변경 없음 — Sidebar 컴포넌트 자체가 탭 전환 시 언마운트/마운트 |

**v0.2.1 — 서버 Push 이벤트 + 폴링 완화:**

| 이벤트 | 발생 시점 | 효과 |
|--------|----------|------|
| `sessions_changed` | `mark_idle()` (턴 완료 시) | 세션 목록 즉시 갱신 |
| `inbox_changed` | `mirror_inbox_item()` (인박스 항목 추가), `resolve_inbox()` (항목 해결) | 인박스 뱃지 즉시 갱신 |

Push 이벤트 도입에 따라 폴링 주기 완화:
- 세션 폴링: **5초 → 30초** (push 실패 시 fallback)
- 인박스 폴링: **4초 → 15초** (push 실패 시 fallback)

**변경 파일:**
```
surfaces/gui/src/hooks/useVisibleInterval.ts  (신규, v0.2.0)
surfaces/gui/src/App.tsx                       (v0.2.0 + v0.2.1)
coworker/server/manager.py                    (v0.2.1, push 이벤트)
coworker/server/inbox_mixin.py                (v0.2.1, push 이벤트)
```

**설계 판단:**
- 기존 `/ws/events` 인프라(`broadcast_event`)를 재사용. 새로운 WS 엔드포인트 없이 기존 이벤트 스트림에 2개 타입 추가.
- `mark_idle()`에서 `asyncio.ensure_future(broadcast_event(...))`로 비동기 전송 — 턴 완료 지연 없음.
- 폴링을 완전 제거하지 않고 완화한 이유: WS 연결 끊김, 이벤트 유실, 비-WS 경로(REST 클라이언트) 대응.

---

## 4. Phase 3 — 테스트·빌드 파이프라인 최적화

### 4-1. Pytest 병렬 실행 ✅ 완료 (P1)

**구현:**
- `pytest-xdist>=3` 의존성 추가
- CI 명령어: `pytest tests -q -n auto`
- `actions/setup-python`에 `cache: pip` 추가

**실측:** 38초 → **19초 (-50%)**

**변경 파일:**
```
pyproject.toml
.github/workflows/ci.yml
```

---

### 4-2. 테스트 파일 분할 ✅ 완료 (P3 + v0.2.1)

**구현:**

| 파일 | 이전 | 이후 | 시점 |
|------|------|------|------|
| `test_connectors.py` | 1,727줄 (57개) | **715줄** (24개 — 코어/게이트웨이/매니저) | v0.2.0 |
| `test_connectors_integration.py` | — | **1,012줄** (33개 — 신규 커넥터 batch 1/2/3) | v0.2.0 |
| `test_server.py` | 1,023줄 (43개) | 삭제 → 2개 파일로 분리 | v0.2.1 |
| `test_server_rest.py` | — | **262줄** (15개 — REST API) | v0.2.1 |
| `test_server_ws.py` | — | **740줄** (28개 — WebSocket) | v0.2.1 |

**공통 헬퍼 중앙화 (v0.2.1):**
`conftest.py`에 `ScriptedProvider`, `_text`, `_tool`, `_client`, `_drain` 헬퍼를 이동하여 두 분할 파일에서 공유.

**변경 파일:**
```
tests/test_connectors.py              (1,727 → 715줄)
tests/test_connectors_integration.py  (신규, 1,012줄)
tests/test_server.py                  (삭제)
tests/test_server_rest.py             (신규, 262줄)
tests/test_server_ws.py               (신규, 740줄)
tests/conftest.py                     (공통 헬퍼 추가)
```

---

### 4-3. CI 캐싱 강화 ✅ 완료 (P3)

**구현:**

| 항목 | 구현 |
|------|------|
| Python pip | `actions/setup-python` `cache: pip` |
| npm | 이미 설정됨 (`cache: npm`) |
| Playwright 브라우저 | `actions/cache@v4`, key: `package-lock.json` 해시, path: `~/.cache/ms-playwright` |

**변경 파일:**
```
.github/workflows/ci.yml
```

---

### 4-4. ruff 정적 분석 도입 ✅ 완료 (P3 + v0.2.1)

**구현:**

| 항목 | 설정 |
|------|------|
| 대상 Python | 3.12 |
| 활성 규칙 | E (pycodestyle errors), F (pyflakes), W (pycodestyle warnings), **I (isort)** |
| 무시 규칙 | E501, E402, E702, E731, E741, F401, F811, F841 |
| CI 스텝 | `ruff check coworker/ tests/` (pytest 이전 실행) |
| 포매팅 | `ruff format` — 213개 파일 일괄 적용 (v0.2.1) |

**변경 파일:**
```
pyproject.toml                ([tool.ruff] 섹션)
.github/workflows/ci.yml     (Lint 스텝 추가)
coworker/**/*.py + tests/**/*.py  (213개 파일 포매팅, v0.2.1)
```

**설계 판단:**
- v0.2.0에서 `I` (isort) 규칙을 비활성화했으나, v0.2.1에서 `ruff format` 일괄 적용 후 활성화 완료. 70개 import 정렬 자동 수정.
- 기획에서 "ESLint + Prettier (TypeScript)" 도입을 제안했으나, `tsc --noEmit`이 이미 타입 체크를 수행하므로 제외.
- pre-commit hook은 v0.2.2에서 도입 완료 (`.pre-commit-config.yaml`, ruff-pre-commit v0.5.0).

---

### 4-5. TypeScript 증분 컴파일 ✅ 완료 (P3)

**구현:**
- `tsconfig.json`에 `"incremental": true`, `"tsBuildInfoFile": ".tsbuildinfo"` 추가
- `.gitignore`에 `.tsbuildinfo` 추가

**효과:** 두 번째 이후 `tsc --noEmit` 실행 시, 변경되지 않은 파일을 건너뛰어 타입 체크 가속.

**변경 파일:**
```
surfaces/gui/tsconfig.json
.gitignore
```

---

## 5. v0.2.1 후속 구현

v0.2.0 기획서의 "후속 과제 — 단기(v0.2.1)" 4개 항목을 모두 구현 완료.

### 5-1. 서버→클라이언트 Push 이벤트 ✅ 완료

기존 `/ws/events` 인프라에 2개 이벤트 타입 추가:

| 이벤트 | 발생 시점 | 서버 위치 |
|--------|----------|----------|
| `sessions_changed` | `mark_idle()` — 턴 완료 시 | `manager.py` |
| `inbox_changed` | `mirror_inbox_item()` — 인박스 항목 추가 시 | `inbox_mixin.py` |
| `inbox_changed` | `resolve_inbox()` — 인박스 항목 해결 시 | `manager.py` |

클라이언트(`App.tsx`)에서 `connectEvents` 콜백에 핸들러 추가. Push 수신 시 `refreshSessions()` / `refreshInbox()` 즉시 호출.

폴링 주기 완화: 세션 5초→**30초**, 인박스 4초→**15초** (push 실패 대비 fallback).

**변경 파일:**
```
coworker/server/manager.py      (mark_idle, resolve_inbox에 broadcast_event 추가)
coworker/server/inbox_mixin.py  (mirror_inbox_item에 broadcast_event 추가)
surfaces/gui/src/App.tsx         (connectEvents 핸들러 확장, 폴링 주기 완화)
```

---

### 5-2. ruff format 일괄 적용 ✅ 완료

- `ruff format coworker/ tests/` — **213개 파일** 포매팅 통일
- `I` (isort) 규칙 활성화 — **70개 import 정렬** 자동 수정
- 최종: `ruff check` All checks passed

**변경 파일:** Python 소스 213개 + `pyproject.toml` (규칙 추가)

---

### 5-3. test_server.py 분할 ✅ 완료

| 이전 | 이후 |
|------|------|
| `test_server.py` (1,023줄, 43개) | `test_server_rest.py` (262줄, 15개) + `test_server_ws.py` (740줄, 28개) |

공통 헬퍼(`ScriptedProvider`, `_text`, `_tool`, `_client`, `_drain`)를 `conftest.py`로 이동하여 양쪽 파일에서 공유.

**변경 파일:**
```
tests/test_server.py       (삭제)
tests/test_server_rest.py  (신규)
tests/test_server_ws.py    (신규)
tests/conftest.py          (공통 헬퍼 추가)
```

---

### 5-4. useSessionState 훅 추출 ✅ 완료

App.tsx에서 15개 세션 관련 상태를 `useSessionState` 커스텀 훅으로 추출:

```
workspace, branch, agent, mode, connected, running, sessionId,
usage, todo, showGate, workspaceTrustRequest, runContext, composerPrefill
```

`resetSession(newId, opts?)` 헬퍼 제공 — 세션 전환 시 한 번의 호출로 모든 세션 상태 초기화.

**변경 파일:**
```
surfaces/gui/src/hooks/useSessionState.ts  (신규, 70줄)
surfaces/gui/src/App.tsx                    (import 교체, ~15줄 감소)
```

---

## 6. v0.2.2 DX 및 렌더링 최적화

v0.2.1 기획서의 "후속 과제 — 단기(v0.2.2)" 3개 항목을 모두 구현 완료.

### 6-1. React 리렌더링 병목 해소 + useCallback 적용 ✅ 완료

**문제:**  
Sidebar(memo)에 15+ 인라인 콜백이 전달되어 App의 모든 상태 변경 시 Sidebar가 리렌더링됨. `scrollToBottom`, `followLatest`, `handleScroll` 등 고빈도 핸들러도 매 렌더 재생성.

**구현 내용:**

| 카테고리 | useCallback 적용 대상 |
|---------|---------------------|
| Sidebar 네비게이션 | `openManage`, `openManagePersonas`, `openScheduled`, `openIntegrations`, `openAudit`, `openAbout`, `openInbox`, `openOps`, `openDev`, `openDatabase`, `openServices`, `openWiki` |
| Sidebar 상호작용 | `onPeekLeave`, `onOpenPersonaFromSidebar`, `onOpenAutomation` |
| 스크롤 핸들러 | `scrollToBottom`, `followLatest`, `handleScroll` |

**효과:** Sidebar가 `surface`, `sessions`, `workspace` 등 관련 props 변경 시에만 리렌더링. 무관한 상태(`streaming`, `items`, `running` 등) 변경 시 Sidebar 리렌더링 완전 제거.

**변경 파일:**
```
surfaces/gui/src/App.tsx  (인라인 콜백 → useCallback 참조, ~40줄 추가)
```

---

### 6-2. Lighthouse CI 통합 ✅ 완료

**구현:**  
CI에 `lighthouse` job 추가. 프로덕션 빌드(`vite build`) 후 `treosh/lighthouse-ci-action@v12`로 측정.

**threshold (warn 레벨):**

| 지표 | 기준 |
|------|------|
| Performance score | ≥ 0.7 |
| Accessibility score | ≥ 0.8 |
| Best Practices score | ≥ 0.8 |
| First Contentful Paint | < 3,000ms |
| Largest Contentful Paint | < 4,000ms |
| Total Blocking Time | < 500ms |
| Script total size | < 600 KB |

**변경 파일:**
```
.github/workflows/ci.yml           (lighthouse job 추가)
surfaces/gui/lighthouserc.json      (신규 — threshold 설정)
```

**설계 판단:**
- `error` 대신 `warn` 레벨 — SPA 특성상 Lighthouse 점수 변동이 크므로 CI를 블로킹하지 않되 가시성 확보.
- `numberOfRuns: 1` — CI 시간 절약. 정밀 측정이 필요하면 3으로 상향.
- `staticDistDir` — 빌드 산출물을 로컬 서버로 직접 제공. 별도 Python 서버 불필요.

---

### 6-3. pre-commit hook 도입 ✅ 완료

**구현:**

`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff          # lint + autofix
        args: [check, --fix]
      - id: ruff-format   # formatting
```

활성화: `pip install pre-commit && pre-commit install`

**변경 파일:**
```
.pre-commit-config.yaml  (신규)
pyproject.toml            (pre-commit>=3 의존성 추가)
```

---

## 7. v0.3.0 아키텍처 및 런타임 최적화

v0.2.2 기획서의 "후속 과제 — 중기(v0.3.0)" 4개 항목을 모두 구현 완료.

### 7-1. Service Worker 캐싱 ✅ 완료

벤더 청크, 폰트(`.woff2`), CSS를 cache-first로 제공하는 경량 SW.

| 항목 | 구현 |
|------|------|
| 캐시 전략 | cache-first (immutable assets), network-only (API/WS/HTML) |
| 대상 패턴 | `/assets/vendor-*.js`, `/assets/index-*.css`, `*.woff2`, `*.svg` |
| 무효화 | Vite 해시 파일명 — 콘텐츠 변경 시 URL 변경으로 자동 |
| 활성화 | `skipWaiting` + `clients.claim` — 새 SW 즉시 활성 |
| 데스크톱 | `__TAURI__` 감지 시 SW 등록 생략 (Tauri WebView는 SW 미지원) |
| 캐시 정리 | activate 시 이전 버전 캐시 자동 삭제 |

**변경 파일:**
```
surfaces/gui/public/sw.js   (신규, 55줄)
surfaces/gui/src/main.tsx    (SW 등록 코드 추가)
```

---

### 7-2. Compaction 성능 경량화 ✅ 완료

`estimate_tokens`에서 불필요한 `try/except` 제거. LLM 요약 호출(`summarize_span`) 자체는 불가피한 병목이며, 이미 `asyncio.to_thread`로 비동기 실행 중.

**설계 판단:**
- `json.dumps` 기반 추정을 `content` 직접 참조로 변경하려 했으나, 기존 테스트가 `json.dumps`의 전체 메시지 직렬화 크기에 의존하여 원복. `try/except` 제거만 적용.
- 주요 provider(OpenAI, Anthropic, Gemini)가 usage를 보고하므로, `estimate_tokens` fallback 경로는 드물게만 호출됨.

**변경 파일:**
```
coworker/compaction.py  (try/except 제거)
```

---

### 7-3. handleEvent 분해 ✅ 완료

App.tsx의 190줄 `switch` 문을 20개 핸들러 함수의 dispatch 테이블로 분해.

| 항목 | 구현 |
|------|------|
| `eventHandlers.ts` | 20개 핸들러 함수 + `dispatchEvent()` 진입점 |
| `EventHandlerCtx` | setter/ref 의존성을 명시적 인터페이스로 선언 |
| App.tsx 감소 | ~170줄 제거 (switch 전체 → `dispatchEvent(ev, ctx)` 1줄) |
| 구조 | 핸들러는 순수 함수 (훅 아님) — 독립 단위 테스트 가능 |

**변경 파일:**
```
surfaces/gui/src/hooks/eventHandlers.ts  (신규, 210줄)
surfaces/gui/src/App.tsx                  (~170줄 감소)
```

---

### 7-4. UIContext 최적화 ✅ 완료

`browserRefreshKey`와 `artifactCount`를 UIContext에서 App 로컬 상태로 이동.

| 항목 | 이전 | 이후 |
|------|------|------|
| UIContext 값 수 | 25개 | **23개** |
| useMemo 의존성 | 18개 | **16개** |
| tool_finished 시 Sidebar 리렌더 | ✅ 발생 | ❌ 없음 |
| turn_done 시 Sidebar 리렌더 | ✅ 발생 | ❌ 없음 |

**변경 파일:**
```
surfaces/gui/src/contexts/UIContext.tsx  (인터페이스 + state + useMemo 축소)
surfaces/gui/src/App.tsx                (로컬 state 추가)
```

---

### 7-5. Sidebar react-window 가상화 ✅ 완료

flat layout의 확장된 Recent 세션 목록에 react-window v2 `List` 적용.

| 항목 | 구현 |
|------|------|
| 활성 조건 | `recentExpanded && length > 20` (VIRTUAL_THRESHOLD) |
| 행 높이 | 40px 고정 |
| 최대 높이 | 480px (12행 가시 + 5 overscan) |
| 효과 | **100+ 세션 DOM: 100+ → ~17개** |

**변경 파일:**
```
surfaces/gui/src/components/Sidebar.tsx
```

---

### 7-6. PDF 경량화 — pdfjs-dist 제거 ✅ 완료

클라이언트 pdfjs-dist (1,741KB) → 서버 pypdfium2 PNG 렌더링.

| 항목 | 이전 | 이후 |
|------|------|------|
| vendor-pdf 청크 | 365 KB | **삭제** |
| pdf.worker.min | 1,376 KB | **삭제** |
| PDF 렌더링 | 클라이언트 캔버스 (pdfjs) | 서버 PNG (`/v1/attachments/render-pdf`) |
| 빌드 산출물 | ~2.9 MB | **~1.1 MB (-62%)** |

**변경 파일:**
```
coworker/server/app.py                    — /v1/attachments/render-pdf 엔드포인트
surfaces/gui/src/api.ts                   — renderPdf() 함수
surfaces/gui/src/components/RightRail.tsx — PdfViewer: pdfjs → 서버 이미지
surfaces/gui/vite.config.ts              — vendor-pdf 청크 제거
```

---

## 8. 우선순위 매트릭스 및 구현 현황

### v0.2.0 기획 항목 (18개)

| # | 항목 | 심각도 | 우선순위 | 상태 | 비고 |
|---|------|--------|---------|------|------|
| 2-1 | SQLite WAL + 인덱스 | HIGH | **P0** | ✅ 완료 | `read_uncommitted` 미적용 (불필요) |
| 2-3 | 엔진 캐시 LRU | HIGH | **P0** | ✅ 완료 | 디스크 직렬화 미구현 (기존 복원 로직으로 충분) |
| 3-1 | 코드 스플리팅 + Lazy Loading | HIGH | **P0** | ✅ 완료 | 734→352KB (-52%) |
| 3-3 | 리스트 DOM 제한 + 가상화 | HIGH | **P0** | ✅ 완료 | Sidebar react-window v2 List 적용 (v1.0) |
| 2-4 | MCP 병렬 연결 | HIGH | **P1** | ✅ 완료 | 3단계 파이프라인 |
| 3-2 | 상태 관리 분리 | HIGH | **P1** | ✅ 완료 | 4개 훅 추출 (v0.2.1에서 useSessionState 추가) |
| 4-1 | Pytest 병렬 실행 | HIGH | **P1** | ✅ 완료 | 38→19초 (-50%) |
| 3-4 | WS 메시지 배치 | MEDIUM | **P2** | ✅ 완료 | rAF 기반 60fps |
| 2-2 | 스킬 스캔 캐싱 | MEDIUM | **P2** | ✅ 완료 | mtime + TTL 30초 |
| 3-5 | React.memo 확대 | MEDIUM | **P2** | ✅ 완료 | Composer, ModelsTab, McpTab |
| 2-5 | JSON I/O 최적화 | MEDIUM | **P2** | ✅ 부분 | ChannelBuffer만 디바운스 (Inbox/Unrouted는 persistence 요구) |
| 4-2 | 테스트 파일 분할 | MEDIUM | **P3** | ✅ 완료 | connectors + server 양쪽 분할 (v0.2.1 완성) |
| 4-3 | CI 캐싱 강화 | MEDIUM | **P3** | ✅ 완료 | pip + Playwright 캐시 |
| 3-6 | i18n 분할 로딩 | LOW | **P3** | ✅ 완료 | 동적 import, 추가 -28KB |
| 3-7 | 폴링 최적화 | LOW | **P3** | ✅ 완료 | visibility 중지 + 서버 push (v0.2.1) |
| 2-6 | 스레드 풀 관리 | LOW | **P3** | ✅ 완료 | max_workers=8 |
| 4-4 | 정적 분석 도입 | LOW | **P3** | ✅ 완료 | ruff lint + format + isort (v0.2.1) |
| 4-5 | TS 증분 컴파일 | LOW | **P3** | ✅ 완료 | incremental: true |

### v0.2.1 후속 항목 (4개)

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 5-1 | 서버→클라이언트 push 이벤트 | ✅ 완료 | sessions_changed + inbox_changed, 폴링 5→30초 / 4→15초 |
| 5-2 | ruff format 일괄 적용 | ✅ 완료 | 213개 파일 포매팅 + isort 70개 자동 수정 |
| 5-3 | test_server.py 분할 | ✅ 완료 | REST(262줄) + WS(740줄), conftest 헬퍼 중앙화 |
| 5-4 | useSessionState 훅 추출 | ✅ 완료 | 15개 상태 캡슐화 + resetSession 헬퍼 |

### v0.2.2 DX 항목 (3개)

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 6-1 | useCallback 리렌더링 최적화 | ✅ 완료 | Sidebar 15+ 콜백 + 스크롤 핸들러 3개 |
| 6-2 | Lighthouse CI 통합 | ✅ 완료 | performance/a11y/LCP/TBT threshold |
| 6-3 | pre-commit hook | ✅ 완료 | ruff check --fix + ruff format |

### v0.3.0 아키텍처 항목 (6개)

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 7-1 | Service Worker 캐싱 | ✅ 완료 | cache-first 벤더/폰트/CSS, Tauri 자동 비활성 |
| 7-2 | Compaction 경량화 | ✅ 완료 | estimate_tokens try/except 제거 |
| 7-3 | handleEvent 분해 | ✅ 완료 | 190줄 switch → 20 핸들러 dispatch, App.tsx -170줄 |
| 7-4 | UIContext 최적화 | ✅ 완료 | browserRefreshKey/artifactCount → App 로컬, 의존성 18→16 |
| 7-5 | Sidebar react-window 가상화 | ✅ 완료 | flat Recent 20+세션 → List, DOM 100+→~17 |
| 7-6 | PDF 경량화 — pdfjs-dist 제거 | ✅ 완료 | 서버 pypdfium2 렌더링, -1,741KB 빌드 산출물 |

**종합:** 31개 항목 중 **30개 완료, 1개 부분 완료** (2-5 JSON I/O — ChannelBuffer만 적용)

---

## 9. 실측 결과

### 프론트엔드 번들 크기

| 빌드 산출물 | v0.1.7 | v0.3.0 | 변화 |
|------------|--------|--------|------|
| **메인 번들** (index-*.js) | 734 KB | **361 KB** | **-50.8%** |
| vendor-react | (메인에 포함) | 133.93 KB | 분리 |
| ~~vendor-pdf~~ | 357 KB | **삭제** | **서버 렌더링으로 대체** |
| ~~pdf.worker.min~~ | 1,376 KB | **삭제** | **서버 렌더링으로 대체** |
| vendor-xlsx | 419 KB (변동 없음) | 429.03 KB | 별도 청크 |
| vendor-markdown | (메인에 포함) | 157.70 KB | 분리 |
| vendor-i18n | (메인에 포함) | 57.68 KB | 분리 |
| lazy 뷰 청크 (12개 합계) | (메인에 포함) | ~192 KB | 분리 |
| CSS | 94 KB | 97.14 KB | 미세 증가 (loading 스타일) |
| 빌드 시간 | — | 2.21초 | — |
| **빌드 산출물 총량** | **~2.9 MB** | **~1.1 MB** | **-62%** |

**초기 로드에 필요한 JS:** 361 KB (메인) + 134 KB (react) = **495 KB**  
(이전 734 KB 대비 **-33%**. PDF는 서버 렌더링, xlsx는 해당 뷰 진입 시에만 로드)

### Python 테스트 성능

| 지표 | v0.1.7 | v0.2.0 | 변화 |
|------|--------|--------|------|
| 실행 모드 | 순차 | 병렬 (`-n auto`) | — |
| 총 테스트 수 | 1,161 | 1,161 | 동일 |
| 실행 시간 | ~38초 | **~19초** | **-50%** |
| passed | 1,161 | 1,161 | 동일 |
| skipped | 74 | 74 | 동일 |
| failed | 0 | 0 | 동일 |

### 프론트엔드 테스트

| 지표 | v0.1.7 | v0.2.0 | 변화 |
|------|--------|--------|------|
| Vitest passed | 67 | 67 | 동일 |
| Vitest failed | 41 | 41 | 기존 실패 (변경 무관) |
| TypeScript 컴파일 | 에러 없음 | 에러 없음 | 동일 |

---

## 10. 스코프 변경 및 설계 판단

### 기획 대비 변경된 항목

| 기획 | 실제 | 이유 |
|------|------|------|
| react-window 가상화 (3-3) | flat layout만 가상화 (v1.0), grouped/Transcript는 대안 | 아코디언/가변 높이는 비호환, flat Recent만 적용 |
| InboxStore SQLite 마이그레이션 (2-5) | 즉시 저장 유지 | 이미 메모리 캐시, persistence 테스트 호환 |
| ESLint + Prettier (4-4) | ruff만 도입 | tsc가 이미 타입/품질 검증 |

### v0.2.0에서 보류 → v0.2.1에서 해결된 항목

| 기획 | v0.2.0 판단 | v0.2.1 해결 |
|------|------------|------------|
| `useSessionState` 훅 추출 (3-2) | handleEvent 순환 의존으로 보류 | setter 직접 참조 구조로 분리 가능 확인, 15개 상태 추출 완료 |
| 서버→클라이언트 push (3-7) | WS 프로토콜 변경 필요로 보류 | 기존 `/ws/events` 인프라 재사용, 2개 이벤트 추가로 해결 |
| test_server.py 분할 (4-2) | fixture 공유 패턴으로 보류 | conftest에 헬퍼 중앙화 후 REST/WS 2개 파일로 분리 |
| ruff isort 규칙 (4-4) | 기존 import 순서 충돌 | `ruff format` 일괄 적용 후 충돌 해소, I 규칙 활성화 |

### 추가 구현된 항목 (기획 외)

| 항목 | 내용 | 시점 |
|------|------|------|
| `DebouncedSaver` 공통 모듈 | 재사용 가능한 coalesce 쓰기 유틸리티 | v0.2.0 |
| `useVisibleInterval` 커스텀 훅 | 범용 visibility-aware interval | v0.2.0 |
| `PRAGMA synchronous=NORMAL` | WAL 모드와 함께 쓰기 성능 개선 | v0.2.0 |
| `sessions_changed` / `inbox_changed` push | 폴링 의존도 대폭 감소 | v0.2.1 |
| `resetSession()` 헬퍼 | 세션 전환 시 일괄 초기화 | v0.2.1 |
| conftest 공통 헬퍼 중앙화 | ScriptedProvider 등 5개 헬퍼 | v0.2.1 |
| Sidebar 콜백 안정화 | 15+ 인라인 콜백 → useCallback 참조 | v0.2.2 |
| Lighthouse CI | 프로덕션 빌드 성능 자동 측정 + threshold | v0.2.2 |
| pre-commit hook | ruff lint + format 커밋 전 자동 실행 | v0.2.2 |
| Service Worker | cache-first 벤더/폰트/CSS, Tauri 자동 비활성 | v0.3.0 |
| `eventHandlers.ts` dispatch 테이블 | 190줄 switch → 20 핸들러 분해 | v0.3.0 |
| UIContext → App 로컬 상태 이동 | browserRefreshKey/artifactCount 분리 | v0.3.0 |
| Sidebar react-window 가상화 | flat Recent 20+세션 → List, DOM 100+→~17 | v0.3.0 |
| PDF 서버 렌더링 | pdfjs-dist 제거, `/v1/attachments/render-pdf` 추가, -1,741KB | v0.3.0 |

---

## 11. 후속 과제

> v0.2.1(§5), v0.2.2(§6), v0.3.0(§7 — 가상화+PDF 포함) 과제 모두 완료됨. 아래는 남은 장기 항목.

### 장기 (v1.0+)

| 항목 | 우선순위 | 설명 |
|------|---------|------|
| SSR / Streaming SSR | 중 | 초기 렌더링 FCP 개선 (현재 CSR only) |
| SQLite → PostgreSQL 옵션 | 하 | 멀티 프로세스 배포 시 WAL 모드의 단일 writer 제한 해소 |

---

## 변경 파일 목록 (v0.2.0 ~ v0.3.0)

커밋: `c9e7604` (v0.2.0+v0.2.1) → `a49491b` (v0.2.2) → `07108d9` (v0.3.0)

### Python 백엔드 — 성능 개선 (12개)
```
coworker/memory/sqlite_store.py          — WAL + 스레드별 커넥션 + 인덱스
coworker/server/engine_cache.py          — (신규) LRU+TTL EngineCache
coworker/server/manager.py               — EngineCache + MCP 병렬화 + push 이벤트
coworker/server/inbox_mixin.py           — inbox_changed push 이벤트
coworker/server/run.py                   — ThreadPoolExecutor(8)
coworker/skills/base.py                  — mtime 캐시 + TTL
coworker/debounced_save.py               — (신규) DebouncedSaver
coworker/subscriptions.py               — ChannelBuffer 디바운스
coworker/inbox.py                        — import 정리
coworker/unrouted.py                     — import 정리
pyproject.toml                           — pytest-xdist, ruff 의존성 + 설정
.github/workflows/ci.yml                — 병렬 테스트, pip 캐시, lint, PW 캐시
```

### Python 백엔드 — ruff format (213개)
```
coworker/**/*.py + tests/**/*.py         — 포매팅 통일 + isort 정렬
```

### TypeScript 프론트엔드 (13개)
```
surfaces/gui/vite.config.ts              — manualChunks
surfaces/gui/tsconfig.json               — incremental
surfaces/gui/src/App.tsx                  — lazy, Suspense, 4개 훅, push 이벤트 수신
surfaces/gui/src/hooks/useStreamState.ts  — (신규) rAF 배치 스트리밍
surfaces/gui/src/hooks/useInboxState.ts   — (신규) 인박스 상태 캡슐화
surfaces/gui/src/hooks/useSessionState.ts — (신규) 세션 상태 캡슐화
surfaces/gui/src/hooks/useVisibleInterval.ts — (신규) visibility-aware interval
surfaces/gui/src/i18n/index.ts            — 동적 언어 로딩
surfaces/gui/src/components/Composer.tsx  — React.memo
surfaces/gui/src/components/ManageTabs.tsx — React.memo (ModelsTab, McpTab)
surfaces/gui/src/components/Transcript.tsx — VISIBLE_WINDOW 축소
surfaces/gui/src/components/SearchModal.tsx — 결과 100개 제한
surfaces/gui/src/styles.css               — surface-loading 스타일
```

### 테스트 (7개)
```
tests/conftest.py                         — 공통 헬퍼 중앙화 (ScriptedProvider 등)
tests/test_connectors.py                  — 1,727→715줄 (코어만)
tests/test_connectors_integration.py      — (신규) 1,012줄 (신규 커넥터)
tests/test_server.py                      — (삭제) → 아래 2개로 분할
tests/test_server_rest.py                 — (신규) 262줄 (REST API)
tests/test_server_ws.py                   — (신규) 740줄 (WebSocket)
tests/test_subscriptions.py               — flush 호출 추가
```

### DX (v0.2.2, 3개)
```
surfaces/gui/src/App.tsx                  — useCallback 15+ 콜백 안정화
surfaces/gui/lighthouserc.json            — (신규) Lighthouse CI threshold
.pre-commit-config.yaml                   — (신규) ruff pre-commit hook
```

### 아키텍처 + PDF (v0.3.0, 9개)
```
surfaces/gui/public/sw.js                 — (신규) Service Worker cache-first
surfaces/gui/src/main.tsx                 — SW 등록
surfaces/gui/src/hooks/eventHandlers.ts   — (신규) 20 핸들러 dispatch 테이블
surfaces/gui/src/App.tsx                  — handleEvent 분해, UIContext 로컬 이동
surfaces/gui/src/contexts/UIContext.tsx   — browserRefreshKey/artifactCount 제거
coworker/compaction.py                    — estimate_tokens 경량화
surfaces/gui/src/components/Sidebar.tsx   — react-window v2 List 가상화
surfaces/gui/src/components/RightRail.tsx — pdfjs-dist → 서버 렌더링 이미지
coworker/server/app.py                    — /v1/attachments/render-pdf 엔드포인트
surfaces/gui/src/api.ts                   — renderPdf() 함수 추가
surfaces/gui/vite.config.ts              — vendor-pdf 청크 제거
```

### 기타 (2개)
```
.gitignore                                — .tsbuildinfo
docs/PERFORMANCE_PLAN.md                  — 본 문서
```
