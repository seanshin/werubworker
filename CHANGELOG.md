# Changelog

## [Unreleased]

### Fixed — `MonitoringView`를 번역 키로 이전
- **`useTranslation`을 전혀 쓰지 않고 한국어를 하드코딩하고 있었다**: 영어로 전환해도 모니터링 화면만 한국어로 남았다. `common:monitoring.*`에 번역 뼈대가 이미 있었는데도 배선이 없었다
- **하드코딩 문자열 68곳 → 0곳**: 탭 라벨, 카드 제목, 테이블 헤더, 빈 상태 문구, 버튼, 배지(`활성`/`비활성`), 임계값·에스컬레이션·이상 건수 같은 보간 문자열까지. 6개 컴포넌트(`MonitoringView`·`OverviewPanel`·`AlertsPanel`·`IncidentsPanel`·`HealthChecksPanel`·`AuditPanel`)에 `useTranslation` 배선
- **`relativeTime()`이 `t`를 인자로 받는다**: `"3분 전"`을 만들던 순수 함수라 번역이 필요한데, 호출부 9곳이 모두 `t`를 가진 컴포넌트 안이다. i18n 싱글턴을 끌어오는 것보다 명시적으로 넘기는 편이 테스트하기 쉽다
- **`toLocaleTimeString("ko-KR")` 하드코딩 제거**: 마지막 갱신 시각이 언어와 무관하게 항상 한국 형식이었다 → `i18n.language`를 따른다
- 기존 `common:monitoring.*` 뼈대를 확장해 en/ko 각 83개 키로 맞췄다. 컴포넌트가 참조하는 71개 키가 양쪽 로케일에 모두 존재하는 것을 확인
- **테스트 2개 추가** (`MonitoringView.i18n.test.tsx`): 영어에서 한글이 새어 나오지 않는지(`not.toMatch(/[가-힣]/)`), 한국어로 전환하면 실제로 한국어가 나오는지. 하나를 하드코딩으로 되돌리면 실패하는 것을 확인

### Fixed — `ModelsTab`이 번역을 쓰지 않던 문제
- **번역은 이미 있는데 컴포넌트가 하드코딩된 영문을 쓰고 있었다** (`ManageTabs.tsx`의 `ModelsTab`): 7곳 — 섹션 제목 `Models`/`Included models`, 두 설명 문단, `Remove key…` 버튼과 그 확인 대화상자, `OPENAI_API_KEY` 환경변수 안내. 영문/한국어 번역이 `manageTabs.*`에 모두 준비돼 있었고 배선만 빠져 있었다. 한국어로 전환해도 이 문단들만 영어로 남았다
- `envNote`는 `<code>` 태그를 품고 있어 `dangerouslySetInnerHTML`로 렌더한다 — `AccessSection`·`AutomationQuickstart`와 같은 관용구이고, 내용은 사용자 입력이 아니라 자체 번역 번들이다
- **테스트 2개 추가** (`ManageTabs.i18n.test.tsx`): 영어 문구 유지 확인과, **한국어로 전환했을 때 실제로 번역되는지**. 후자가 핵심 — 영어에서는 하드코딩이든 아니든 문구가 같아서 어떤 테스트도 이 결함을 잡지 못했다. 하나를 하드코딩으로 되돌리면 실패하는 것을 확인
- 이 저장소는 testing-library auto-cleanup이 꺼져 있어, 언어 전환 테스트는 `cleanup()`이 필요하다(이전 테스트의 트리가 남아 함께 다시 렌더되며 중복 매치를 만든다)

### Changed — 인용 표시·아포스트로피를 곡선으로 통일
- `131d056`(OpenWorker → WeruBWorker 재빌드)이 인용 표시를 곡선(`“ ”`)에서 직선(`"`)으로 바꿔 놓은 곳을 되돌리고, 남아 있던 직선 따옴표까지 함께 통일했다. 코드 주석이 "the cozy inline quote"라 부르는 타이포그래피가 재빌드에서 조용히 사라진 게 발단이었다
- **재빌드가 평평하게 만든 곳**: `ApprovalCard.tsx`의 인라인 메시지 인용과 standing approval 툴팁, `GithubDetail.tsx`의 인용 스팬(바로 옆 `SlackDetail.tsx`는 곡선을 유지하고 있어 둘이 어긋나 있었다), 영문 로케일 3곳(`ocw-agent` 라벨 / `Show archived` / 스킬 빈 상태 예시)
- **원래부터 직선이던 곳**: `session.json`의 `noSearchResults`, `settings.json`의 `sidebarDesc`. 이 둘은 회귀가 아니라 새로운 타이포그래피 결정이지만, 섞여 있으면 영문 UI에 두 가지 인용 표시가 공존하므로 함께 곡선으로 맞췄다
- **바꾸지 않은 것**: `settings.json`의 `` `{ "<name>": { … } }` ``는 JSON 코드 예시다 — 곡선으로 바꾸면 붙여넣을 수 없는 예시가 된다. 이제 영문 로케일에서 직선 따옴표가 남은 곳은 여기 하나뿐이다
- **아포스트로피도 곡선(`’`)으로 통일**: 영문 로케일 41곳(축약형·소유격)과 `ManageTabs.tsx`에 하드코딩된 렌더 텍스트 2곳. 코드 예시나 CLI 문법 안의 `'`는 없어서 전부 안전하게 변환됐다
- **표기 방식 정리**: 로케일 파일은 `—`·`…`을 리터럴 문자로 저장하는데 앞서 넣은 곡선 따옴표만 `\u201C` 이스케이프였다. 파일 관행에 맞춰 리터럴 문자로 통일(10곳)
- 한국어 로케일은 곡선 따옴표·아포스트로피를 전혀 쓰지 않으므로 그대로 뒀다
- 코드 주석의 직선 아포스트로피는 코드이므로 대상이 아니다

### Fixed — 프론트엔드 테스트 40건 실패 정리
- **i18next가 테스트에서 초기화되지 않던 문제 (36건)**: `useTranslation`이 키 자체(`"settings:modelChecklist.modelFamily"`)를 반환해서, 실제 UI 텍스트를 찾는 테스트가 전부 실패했다. 텍스트가 없는 게 아니라 **해석되지 않은 상태**였다. `src/test-setup.ts`에서 앱의 i18n 모듈을 로드해 해결
- **언어를 `en`으로 고정한 뒤 로드**: i18n 모듈은 import 시점에 저장된 언어를 읽고, `en`이 아니면 한국어 번들을 비동기로 불러와 **테스트 도중에** 언어를 바꾼다. jsdom은 localStorage가 비어 있어 기본값이 `ko`라 이 고정이 없으면 영어 기준 단언이 깨진다
- **이름 변경 낙진 4건**: `131d056`(OpenWorker → WeruBWorker 재빌드)에서 코드만 바뀌고 테스트가 따라오지 않은 것들 — 인증 헤더 `X-OpenWorker-Token` → `X-WeruBWorker-Token`, WebSocket 서브프로토콜 `openworker` → `werubworker`, 스킬 메뉴 라벨 `Create with OpenWorker` → `Create with WeruBWorker`, 파킹된 승인 버튼 `Approve` → `Allow`. 승인 카드의 따옴표는 반대로 **컴포넌트 쪽을 되돌렸다**(위 항목)
- **`eventHandlers.ts` 타입 오류**: `p[i].kind === "user"`로 좁힌 타입이 두 번째 `p[i]` 접근에 이어지지 않아(반복 변수 인덱스라 narrowing이 유지되지 않음) `.text` 읽기가 미검사 상태였다. 지역 변수로 묶어 해결
- **결과**: 40 failed / 69 passed → **115 passed (20 파일)**, `tsc --noEmit` 오류 0. README에 프론트엔드 테스트 명령 추가

---

## [2.3.6] - 2026-08-25

> 성능개선 기획서 v2의 마지막 세 항목(2-3, 6-1, 5-1)을 마무리해 §3 우선순위 표 12개 항목이
> 전부 완료됐다. 세 항목 모두 **착수 전 실측에서 기획과 현실이 어긋났고**, 그 차이가 이
> 릴리즈의 실제 내용이다 — 이미 되어 있던 것(WebSocket 압축), 기획서가 지목하지 않은 곳에
> 있던 진짜 누수(백그라운드 셸 버퍼), 그리고 성능이 아니라 도달 불가 문제였던 것(인시던트).
> 실측으로 기각한 항목(델타 전송)의 근거도 기획서에 남겼다.

### Performance — 대시보드 가상 스크롤 (성능개선 기획서 v2 Phase 5-1)
- **로그 뷰어 가상화** (`LogView.tsx`): `limit=500`을 가져와 10초마다 통째로 다시 렌더하고 있었다 — 행당 5노드씩 **2,501노드가 매 갱신마다 헐리고 다시 만들어짐**. `react-window`로 가상화해 **78노드**로 축소. 기획서가 지목한 감사 로그(150건)보다 이쪽이 훨씬 컸다
- **동적 행 높이 사용**: 로그 줄은 `whitespace-pre-wrap`으로 감싸지므로 스택 트레이스는 한 줄 항목의 몇 배 높이다. 고정 행 높이는 긴 줄을 자르거나 짧은 줄 뒤에 빈 공간을 남기므로 `useDynamicRowHeight`로 측정해 기존 표시 동작을 유지
- **자동 스크롤 경로 수정**: 가상 목록은 자체 스크롤 컨테이너를 가지므로 바깥 div의 `scrollTop`을 조작하던 기존 코드는 아무 일도 하지 않는다. `listRef.scrollToRow()`로 전환
- **행 컴포넌트를 가상/평면 경로가 공유**: 둘이 갈라지면 임계값(60건)을 넘겨야만 드러나는 차이가 된다
- **감사 로그 목록 가상화** (`AuditView.tsx`): 40건 초과 시 가상 스크롤. 카드 높이가 제각각(resource·args·reason이 선택적)이라 여기도 동적 높이

### Fixed — 인시던트 51번째 이후에 도달할 수 없던 문제 (Phase 5-1)
- **`list_incidents`가 원래부터 50건에서 잘렸는데 offset이 없었다**: 화면에 안 보이는 게 아니라 **API로도 꺼낼 수 없었다**. `limit`/`offset` 추가, `count_incidents()` 신규
- **`/v1/dashboard/incidents`가 `total`·`has_more` 반환**: UI가 "잘렸다"는 사실을 표시하고 이어서 가져올 수 있다. `limit`은 200에서 클램프
- **"이전 인시던트 N건 더 보기"** (`MonitoringView.tsx`): 이어붙일 때 id로 중복을 걸러 10초 갱신이 중간에 끼어들어도 행이 겹치지 않게 함

### Added
- 프론트엔드 테스트 6개 (`LogView.test.tsx`, `AuditView.test.tsx`): 500건에서 DOM 노드가 결과 크기가 아니라 뷰포트를 따르는지, 가상/평면 경로가 같은 마크업을 내는지, 긴 줄의 줄바꿈이 유지되는지. 가상화를 끄면 실패하는 것을 확인
- 인시던트 페이지네이션 테스트 3개 (`tests/test_incidents.py`): 페이지 경계에서 누락·중복 없음, status 필터별 카운트, `has_more` 보고
- **`src/test-setup.ts`**: jsdom에 없는 `ResizeObserver` 스텁. 이게 없으면 react-window가 마운트에서 터져 테스트가 비가상 경로만 검증하게 된다

### Fixed — 백그라운드 셸 출력 버퍼 무제한 증가 (성능개선 기획서 v2 Phase 6-1)
- **`_BackgroundTask`의 출력 버퍼가 상한 없이 자라던 누수** (`tools/shell.py`): 리더 스레드가 자식 프로세스의 stdout을 프로세스 수명 내내 `list`에 append하는데 `read_new()`는 커서만 옮기고 버퍼를 비우지 않았다. `background_output`은 마지막 20,000자만 반환하므로 나머지는 아무도 읽지 않는 채로 남는다. **200,000줄을 내는 명령 1개가 15.8 MB를 영구 점유** — `tail -f`나 개발 서버처럼 계속 출력하는 명령이면 상한이 없다
- **링버퍼로 전환** (줄 2,000 / 문자 256,000 상한): 15.8 MB → **0.2 MB**, 반환되는 출력은 20,000자로 동일
- **읽기 커서를 절대 줄 번호로 변경**: deque 인덱스 커서는 축출이 시작되면 조용히 같은 줄을 다시 읽거나 건너뛴다 — 줄을 버리는 것보다 나쁜 실패다(있지도 않았던 그럴듯한 출력을 보여주게 됨)
- **버려진 줄은 `dropped_lines`로 보고**: 구멍을 연속된 출력처럼 보이지 않게 한다
- **종료된 태스크 회수**: 최근 10개만 남기고 버퍼·stdout 파이프 해제. **실행 중인 태스크는 건드리지 않는다** — 메모리를 아끼려고 사용자의 개발 서버를 죽이는 건 누수보다 나쁘다

### Added — 메모리 관측 (Phase 6-1)
- **`EngineCache.stats()`**: 크기·히트율과 함께 **축출을 원인별로 분리**(LRU/TTL). LRU 축출은 `max_size`가 동시 세션 수에 비해 작다는 신호이고, TTL 축출은 유휴 세션이 늙어 빠지는 정상 동작이라 뜻이 다르다
- **`GET /v1/diagnostics/memory`**: 프로세스 수명 내내 사는 레지스트리 크기 — 엔진 캐시, WebSocket 소켓 수, 실행 중 세션, 수집기 추적 서버 수, 메트릭 캐시. 누수는 여기서 한 방향으로만 올라가는 숫자로 드러난다. 지연 초기화된 하위 시스템은 이미 만들어진 경우에만 보고한다(조회가 저장소를 만들어내면 숫자가 조회의 부작용이 된다)
- **WebSocket ping 설정 명시화** (`ws_ping_interval`/`ws_ping_timeout` 20초): 좀비 소켓이 브로드캐스트 레지스트리에 쌓이는 것을 막는 장치라 라이브러리 기본값에 맡기지 않는다. 죽은 피어는 최대 40초 안에 끊기고 엔드포인트의 `finally`가 등록을 해제한다

### Verified — 기획서 6-1의 나머지 두 항목은 이미 해결돼 있었다
- **수집기 실패 맵 TTL**: 2-1의 `TimeoutTracker._prune()`(`_HISTORY_TTL = 3600`)에 선반영됨
- **WebSocket 좀비 연결**: uvicorn ping 기본값(20+20초)이 기획서가 요구한 60초보다 촘촘하게 이미 동작 중. 명시화만 함
- **엔진 캐시**: 이미 LRU 50 + TTL 1시간으로 유계였고 빠져 있던 건 관측 수단뿐

### Performance — WebSocket 압축 (성능개선 기획서 v2 Phase 2-3)
- **`ws_per_message_deflate` 명시화** (`server/run.py`): permessage-deflate는 uvicorn 기본값이라 이미 켜져 있었으나, 그 사실이 코드 어디에도 없어 라이브러리 기본값에 암묵적으로 의존하고 있었다. 기본값이 바뀌어도 스트림은 계속 동작하되 조용히 커지기만 해서 아무도 눈치채지 못하므로 값을 명시적으로 전달한다
- **`COWORKER_WS_COMPRESSION=0`**: 압축을 끄는 탈출구. 스트림을 실측하거나 패킷 캡처로 프레임을 읽을 때만 쓴다
- **회귀 테스트 3종** (`tests/test_server_ws.py`): uvicorn에 플래그가 전달되는지, 환경변수 opt-out이 동작하는지, 그리고 **실제 서버에서 확장이 협상되는지**. 마지막 것이 핵심 — `TestClient`의 WebSocket은 uvicorn을 거치지 않으므로 설정값만 검증하면 실제 협상 여부는 확인되지 않는다
- **측정** (200서버 `metrics_update` 10틱, TCP 레벨): 218,714 B → 20,615 B (**-90.6%**). 기획서 목표(60% 절감)를 이미 넘고 있었음

### Rejected — 델타 전송 (기획서 2-3의 나머지 절반)
- 기획서의 "대시보드 갱신 시 변경분만 전송"은 **실측 후 구현하지 않기로 했다.** 실제 수집 데이터(`metrics_raw` 7,316행)에서 연속 틱 쌍의 **100.0%**가 최소 한 필드 이상 변한다 — `net_rx`/`net_tx`가 스냅샷이 아니라 누적 카운터이고 수집 간격이 60초라, 수집기 자신의 SSH 접속만으로도 카운터가 움직인다. "변한 서버만 전송"이 곧 "전부 전송"이라 절감폭이 0%다
- 추가로 `MonitoringView.tsx`가 수신 포인트를 서버별 링버퍼에 append해 차트를 그리므로, 델타로 빠진 서버는 시계열에 구멍이 생긴다. 클라이언트가 carry-forward를 합성해야 하고 그만큼 desync 버그 부류가 생긴다
- 판단 근거는 기획서 §2-3에 측정치와 함께 기록했다

### Fixed
- `tests/test_server_ws.py`의 WebSocket 엔드포인트 애노테이션 함정: 이 파일은 `from __future__ import annotations`를 쓰므로 FastAPI가 문자열 애노테이션을 **엔드포인트 모듈의 전역**에서 해석한다. `WebSocket`을 함수 안에서 import하면 해석에 실패해 FastAPI가 `ws`를 조용히 쿼리 파라미터로 강등시키고, 핸드셰이크가 읽을 수 없는 403으로 실패한다. 모듈 레벨 import로 고정하고 주석으로 남김

---

## [2.3.5] - 2026-08-24

### Performance — 배치 쓰기 (성능개선 기획서 v2 Phase 1-1)
- **`BatchWriter`** (신규 `monitoring/batch_writer.py`): 쓰기 레코드를 메모리 버퍼에 모아 일괄 처리. `flush_size`(기본 50) 또는 `flush_interval`(기본 0.1초) 중 먼저 도달한 조건에서 플러시, 데몬 타이머로 유휴 시에도 상한 보장. 플러시 실패 시 배치 폐기 + `dropped` 누적 (버퍼 무한 증가 방지)
- **`TimeSeriesStore` 커넥션 재사용**: 매 호출 `sqlite3.connect()` → 스레드 로컬 커넥션. 기존 코드는 커넥션을 닫지 않아 호출마다 새로 만들고 GC에 맡기던 구조였음
- **`TimeSeriesStore` PRAGMA 튜닝**: `synchronous=NORMAL` (WAL에서 커밋마다 fsync 제거), 신규 DB에 한해 `page_size=8192`
- **`record_batch()` executemany**: 건별 `execute()` 루프 → 파라미터 튜플 조립 후 `executemany()` 1회. 잘못된 포인트는 기존대로 `errors`로 보고
- **`TimeSeriesStore(batch_writes=True)`**: `record()` 단건 호출을 버퍼링하는 선택적 모드. 조회·유지보수 메서드는 진입 시 자동 플러시하여 같은 인스턴스의 read-after-write 일관성 유지. 기본값은 False
- **해시체인 배치 기록**: `AuditStore.append_many()`, `OpsAuditStore.record_many()` 추가 — 해시를 메모리에서 연쇄 계산한 뒤 `executemany`로 한 트랜잭션에 기록. 단건 경로와 섞어 써도 체인이 이어짐

### Measured (best of 5, 로컬 SQLite)
| 작업 | 이전 | 이후 | 배수 |
|------|------|------|------|
| `record()` × 1,000 (단건) | 181.8 ms | 23.8 ms | 7.6× |
| `record()` × 1,000 (버퍼 모드) | 181.8 ms | 3.3 ms | 55× |
| `record_batch()` 100서버 | 0.5 ms | 0.2 ms | 2.5× |
| `record_batch()` 300서버 | 1.0 ms | 0.7 ms | 1.4× |
| 감사 로그 1,000건 | 64.2 ms (단건) | 5.5 ms (`record_many`) | 11.7× |

### Performance — 메트릭 조회 캐시 (성능개선 기획서 v2 Phase 3-1)
- **`MetricsCache`** (신규 `monitoring/cache.py`): latest 캐시(TTL)와 range 캐시(LRU)를 함께 제공. 히트율·크기를 `stats()`로 노출
- **latest 캐시**: `query_latest()` 결과를 TTL 10초로 보관. 쓰기 시 해당 server_id와 전체 조회 키만 무효화하므로 같은 인스턴스의 read-after-write 일관성 유지
- **TTL 상한 고정** (`MAX_LATEST_TTL = 10.0`): 이 질의가 30초 주기 알림 평가 경로에 있어, TTL이 틱 주기에 가까워지면 낡은 메트릭으로 알림이 평가된다. 생성자 인자로 올려도 상한에서 잘린다
- **range 캐시**: 닫힌 집계 구간(5m/1h/1d)만 LRU 200개까지 보관. 형성 중인 버킷과 raw 테이블은 대상 제외, 다운샘플링·정리 실행 시 무효화
- **`TimeSeriesStore(cache_enabled=…)`** 및 `cache_stats()` / `invalidate_cache()` 추가. 캐시는 인스턴스 로컬이라 다른 프로세스의 쓰기는 최대 TTL만큼 늦게 보인다

| 작업 | 캐시 미스 | 캐시 히트 | 배수 |
|------|-----------|-----------|------|
| `query_latest()` 200서버 / 2,016,000행 (7일치 raw) | 138.3 ms | 0.02 ms | 7,864× |
| `query_latest()` 200서버 / 2,000행 | 0.52 ms | 0.01 ms | 52× |

### Performance — 수집 병렬도 확대 (성능개선 기획서 v2 Phase 2-1)
- **`parallel_workers` 기본 10 → 20**, 상한 `MAX_PARALLEL_WORKERS = 50`으로 클램프 (SSH 세션 수·파일 디스크립터 안전선). 하한 1
- **`TimeoutTracker`** (신규, `collector.py`): 서버별 SSH 응답 시간 EWMA(α=0.3)로 타임아웃을 조정. 빠른 서버는 하한(5초)까지 줄여 장애 시 빨리 포기하고, 느린 서버는 상한(30초)까지 늘려 정상 응답이 잘리지 않게 함. 여유 배수 3배
- **실패 서버 처리**: 직전 실패한 서버는 다음 시도에서 상한 타임아웃 — 느려서 잘린 경우 회복 기회를 준다. 성공하면 다시 적응형으로 복귀
- **이력 TTL 1시간**: 한 시간 동안 수집되지 않은 서버 이력은 자동 제거 (장기 운영 시 맵 무한 증가 방지 — Phase 6-1 선반영)
- `CollectorConfig.adaptive_timeout=False`로 기존 고정 타임아웃 동작 유지 가능. `MetricCollector.timeout_stats()`로 서버별 현황 조회

| 200서버 수집 (서버당 SSH 0.5초 시뮬레이션) | 시간 |
|---|---|
| `parallel_workers=10` (이전 기본) | 10.03 s |
| `parallel_workers=20` (신규 기본) | 5.02 s (2.0×) |
| `parallel_workers=50` (상한) | 2.01 s |

### Fixed — 보관정책 정리가 해시체인을 끊던 문제
- **`OpsAuditStore.prune()`이 `verify_chain()`을 영구 실패시키던 버그**: 오래된 기록을 삭제하면 남은 첫 기록이 연결하던 앞 기록이 사라져 검증이 인덱스 0에서 실패했다(`(False, 0)`). 자동 정리를 도입하면 변조 탐지가 상시 오탐이 되므로 먼저 수정
- **체인 앵커 도입**: 정리 시 남은 첫 기록의 `prev_hash`를 메타 테이블(`ops_audit_meta` / `audit_meta`)에 저장하고, 검증은 GENESIS 대신 이 앵커에서 시작. 전부 삭제된 경우 현재 head를 앵커로 삼아 이후 기록과 이어짐. 재기동 후에도 유지
- `HashChain.verify_chain_streaming(start_hash=…)` 파라미터 추가 (기본값은 기존 GENESIS라 호출부 호환)
- `chain_anchor()` 접근자 추가 (`AuditStore`, `OpsAuditStore`)

### Fixed — 서비스 기동 스크립트 (`start.sh`)
- **`--stop`이 무관한 프로세스를 종료하던 버그**: `lsof -ti :PORT`는 해당 포트를 LISTEN 중인 서버뿐 아니라 그 포트에 *접속한* 클라이언트(대시보드를 열어 둔 브라우저 등)의 PID까지 반환한다. 그대로 `kill -TERM`으로 넘기고 있어 서비스 중지 시 사용자 프로세스가 함께 죽을 수 있었다. `_port_pid()` 헬퍼로 `lsof -nP -tiTCP:PORT -sTCP:LISTEN`을 사용해 LISTEN 소켓만 대상으로 삼는다 (`_status`/`_stop`/`_start`의 모든 조회 경로에 적용)
- **로그인 시 자동 시작이 조용히 실패하던 문제**: launchd는 최소 PATH(`/usr/bin:/bin:/usr/sbin:/sbin`)로 실행하므로 `brew`·`gitea-runner`·`npx`를 찾지 못한다. 스크립트 진입 시 Homebrew 경로(`/opt/homebrew/{bin,sbin}`, `/usr/local/bin`)를 PATH에 보강
- **콜드 스타트를 기동 실패로 오판하던 문제**: 고정 `sleep 2/3/4` 후 포트를 1회 확인하던 방식 → `_wait_port()` 폴링(Gitea 15초, 백엔드·프론트엔드 각 30초 상한). 로그인 직후처럼 느린 환경에서 정상 기동을 실패로 보고하지 않으면서, 빠른 환경에서는 대기 시간이 오히려 줄어든다

### Performance — 디스크 관리 자동화 (성능개선 기획서 v2 Phase 6-2, 1-2 잔여)
- **`DiskMaintenance`** (신규 `monitoring/maintenance.py`): 일 1회 주기를 스스로 판단해 다운샘플링 → 보관정책 정리 → 백업 정리 → WAL 체크포인트를 순서대로 실행. 각 단계는 독립 예외 처리라 저장소 하나가 실패해도 나머지가 진행되고, 실패는 `errors`에 모임
- **실행 순서 근거**: 정리로 지워질 raw 데이터를 먼저 집계하고, 삭제로 생긴 공간을 마지막 체크포인트에서 회수
- **`AuditStore.prune(retention_days=90)`** 신규, `OpsAuditStore.prune()`은 기본 365일 유지 — 기획서 6-2의 보관정책 수치
- **`TimeSeriesStore.checkpoint()`**: `PRAGMA wal_checkpoint(TRUNCATE)`로 WAL 파일 회수 (기획서 1-2의 수동 체크포인트 스케줄)
- **`TimeSeriesStore.db_size_bytes()`**: DB+WAL+SHM 합계. 1GB 초과 시 경고 (기획서 6-3 디스크 사용량 알림)
- 스케줄러 틱(`manager.py`)에 연결 — 매 틱 호출하되 주기가 안 되면 즉시 skip

### Added
- 디스크 관리·체인 앵커 테스트 23개 (`tests/test_maintenance.py`): 정리 후 체인 검증, 앵커 재기동 유지, 전체 삭제 시 head 앵커, WAL 절단, 단계 순서, 단일 저장소 실패 격리, 보관 기간 전달, 스케줄러 배선 이름 고정
- 수집 병렬도·타임아웃 테스트 14개 (`tests/test_collector_timeout.py`): 병렬도 클램프 3종, 동시 실행 상한 준수, 적응형 타임아웃 7종, 이력 TTL 정리, 통계 노출
- 배치 쓰기 테스트 19개 (`tests/test_batch_writer.py`): 플러시 트리거 4종, 실패 시 폐기, 배치 모드 read-after-write, 해시체인 무결성(배치·혼합), 20스레드 동시 쓰기 2종
- 캐시 테스트 16개 (`tests/test_metrics_cache.py`): TTL 만료·상한, 무효화 범위, 결과 복사본 반환, LRU 축출, 닫힌 구간만 캐시, 유지보수 무효화
- 성능 테스트 6개 (`tests/test_performance_v2.py`): 100서버 < 0.3초, 300서버 < 1초, 버퍼 모드 우위, 감사 1,000건 배치 < 0.3초, 캐시 히트 < 5ms, 캐시 우위

### Stats
- 테스트: 1,430 passed, 74 skipped (+78)

---

## [2.3.4] - 2026-08-20

### Performance — 감사 로그·알림 최적화 (성능개선 기획서 v2 Phase 1·3·4)
- **해시체인 메모리 캐시** (`audit.py`, `audit_ops.py`): 마지막 해시를 인스턴스 변수(`_last_hash`)로 유지 — append마다 실행되던 `SELECT hash ORDER BY id DESC LIMIT 1` 제거 (I/O 2회 → 1회)
- **스레드 로컬 커넥션 풀링** (`audit_ops.py`): 매 호출 `sqlite3.connect()` → 스레드별 커넥션 재사용 (생성 90% 감소)
- **민감정보 필터 빠른 탈출** (`sensitive_filter.py`): 합성 pre-check 정규식(`_QUICK_CHECK`, `_CMD_QUICK_CHECK`)으로 1회 스캔 — 민감정보 없는 텍스트는 14패턴 순회 없이 즉시 반환, 4자 미만 스킵
- **알림 규칙 인메모리 캐시** (`alerting.py`): `list_rules(enabled_only=True)` TTL 5초 캐시, `add_rule()`/`remove_rule()` 시 자동 무효화
- **해시체인 스트리밍 검증** (`hash_chain.py`): `verify_chain_streaming()` 커서 기반 O(1) 메모리 검증 추가, `AuditStore.verify_chain()`이 이를 사용하도록 전환 (100K+ 레코드 OOM 방지)

### Added
- 성능 테스트 9개 (`tests/test_performance_v2.py`): 1K append < 1초, 민감정보 포함 1K < 1.5초, 10K 스트리밍 검증 < 3초, `chain_head()` 무조회 반환, 클린 텍스트 10K 필터 < 0.1초, 혼합 10K < 0.5초, 명령어 10K < 0.3초, 50규칙 × 200서버 평가 < 1초, 해시 계산 100K < 1초
- 성능 개선 기획서 v2 (`docs/WeruBWorker_성능개선_기획서_v2.md`): 6 Phase, 우선순위 12항목, 성능 목표 수치표

### Stats
- 테스트: 1,352 passed, 74 skipped (성능 +9)
- 잔여 계획: Phase 1-1 배치 쓰기, 2-1 수집 병렬도 확대, 3-1 메트릭 조회 캐시, 6-2 디스크 관리 자동화 등 (기획서 §3 구현 우선순위 참조)

---

## [2.3.3] - 2026-08-20

### Added — Sign 연동 보안 강화 (Phase 1~6)
- **민감정보 필터** (`security/sensitive_filter.py`): 감사 로그 전용 정규식 14패턴 (API키, Bearer, 비밀번호, 주민번호, 전화번호, DB URI, SSH/DB 명령)
- **해시체인** (`security/hash_chain.py`): SHA-256 해시체인으로 감사 로그 변조 탐지 — `audit.py`, `audit_ops.py` 통합
- **Sign 브릿지** (`security/sign_bridge.py`): Sign 전자서명 서비스 REST API 클라이언트, TSA 앵커링 (RFC 3161)
- **Webhook HMAC** (`security/hmac_signer.py`): HMAC-SHA256 서명/검증 + 리플레이 방지 + 멱등 이벤트 ID
- **TOTP 2FA** (`security/totp.py`): RFC 6238 TOTP 생성/검증, QR 등록, 백업 코드 10개, step-up 재인증
- **봉투 암호화** (`security/envelope_crypto.py`): AES-256-GCM 봉투 암호화 — `secrets.py` 통합, 평문→암호화 자동 마이그레이션
- **도구 호출 서명** (`security/tool_signer.py`): 위험 도구(SSH, Docker, DB 등) 호출 시 HMAC 서명 기록 (부인 방지)
- **백업 매니페스트 서명** (`backup.py`): 백업 생성 시 SHA-256 해시 + HMAC 서명, 복원 시 무결성 검증
- **MCP 보안 도구 5개**: `audit_chain_verify`, `audit_anchor_status`, `security_score_enhanced`, `log_sensitive_scan`, `secrets_rotation_check`
- **auth.py 2FA 통합**: `setup_totp()`, `verify_totp()`, `disable_totp()`, `verify_step_up()`, `step_up()`

### Changed
- `audit.py`: `_sanitize_args()` 값 정규식 스캔 추가, 해시체인 컬럼 자동 마이그레이션
- `audit_ops.py`: `record()` 시 command 필드 민감정보 마스킹, 해시체인 적용
- `secrets.py`: `SecretStore`에 `encryption_password` 옵션, `enable_encryption()`, `is_encrypted()` 추가
- `monitoring_server.py`: MCP 도구 12→17개

### Stats
- 신규 파일: 7개 (security 모듈) + 7개 (테스트)
- 테스트: 1,343 passed (보안 +88)
- 기획서: `docs/WeruBWorker_Sign_보안강화_기획서.md`

---

## [2.2.2] - 2026-08-14

### Added
- 성능 부하 테스트 11개 (100서버 쓰기, 1000포인트, 50규칙×100서버 평가, 5스레드 동시 쓰기 등)
- Sidebar 모니터링 버튼 i18n 적용

### Stats
- 테스트: 1,243 passed (성능 +11)

---

## [2.2.1] - 2026-08-14

### Added
- MonitoringView i18n: 한국어/영어 번역 키 추가 (50+ 키)
- README v2.2 기준 최종 갱신 (배지, GUI 페이지, MCP)

---

## [2.2.0] - 2026-08-14

### Added
- GUI 모니터링 전용 대시보드 페이지 (MonitoringView.tsx, 809줄)
  - Overview: 서버 현황 카드, CPU/메모리/디스크 프로그레스바
  - Alerts: 활성 알림, 규칙 목록, Webhook 설정
  - Incidents: 인시던트 목록 + 타임라인 펼침
  - Health Checks: 5개 체크 상태 + 즉시 실행
  - Audit: 운영 감사 로그 테이블
- 사이드바 모니터링 네비게이션 추가 (shield 아이콘)

---

## [2.1.1] - 2026-08-14

### Added
- Webhook 알림 발송: Slack/Discord/Teams/커스텀 URL 자동 POST
- Webhook 관리 REST API: GET/POST/DELETE /v1/dashboard/webhooks
- MCP 서버 도구 2개 추가: webhook_list, webhook_add (총 12개)
- 스케줄러 tick에서 알림 발생 시 Webhook 자동 발송
- Claude Code 프로젝트 MCP 설정 (.mcp.json)

---

## [2.1.0] - 2026-08-14

### Added
- MCP 모니터링 서버: 10개 도구를 외부 AI (Claude Desktop, Cursor, Claude Code)에 노출
  - metrics_latest, metrics_query, healthcheck_list/run, active_alerts, alert_rules
  - incidents_list/get, audit_recent, dashboard_overview
- MCP 설정 가이드 (docs/mcp-setup.md)
- pyproject.toml: werubworker-mcp-monitoring 진입점 추가

---

## [2.0.3] - 2026-08-13

### Added
- E2E 통합 테스트 6개 시나리오 (메트릭→알림→인시던트→해결, 헬스체크 실패 감지, 시계열 라이프사이클, 자동 복구, Wiki 리졸버, 감사 로그)
- 사용자 가이드 v2.0 섹션 추가 (자동 모니터링, 대시보드 API, SRE 에이전트, 멀티 클라우드)

### Stats
- 테스트: 1,232 passed (E2E +6)

---

## [2.0.2] - 2026-08-13

### Added
- 스케줄러 자동 모니터링: 30초마다 메트릭 수집 + 헬스체크 + 알림 평가 자동 실행
- 10분 주기 유지보수: 시계열 다운샘플링 + 보관 정책 자동 적용
- ITMS Gitea 연동: 인시던트 → Gitea Issue 자동 생성 (`sync_to_gitea()`)

---

## [2.0.1] - 2026-08-13

### Fixed
- GUI OpsView 연동: 신규 모니터링 시스템을 기존 `/v1/ops/*` API에 통합
- `/v1/ops/local-status`: TimeSeriesStore에 메트릭 자동 기록 (장기 보관)
- `/v1/ops/healthcheck`: 영속 HealthCheckManager 연동 (SQLite 저장)
- Dashboard Wiki API 중복 라우트 충돌 해소
- 서비스 시작 스크립트 (`start.sh`) 추가

---

## [2.0.0] - 2026-08-13

### Added — 모니터링 서브시스템
- 시계열 저장소 (SQLite, 4단계 다운샘플링)
- 멀티 서버 메트릭 수집기 (SSH 병렬, asyncio)
- 8종 헬스체크 매니저 (HTTP/TCP/DNS/Ping/SSL/Docker/K8s/Process)
- 규칙 기반 알림 엔진 (cooldown, 에스컬레이션)
- 인시던트 관리 (타임라인, 에스컬레이션, 사후분석)
- 자동 복구 엔진 (7개 기본 액션, Inbox 승인)
- 다중 서버 로그 집계 (패턴 매칭, 심각도 분류)
- 운영 감사 로그 (append-only, CSV 내보내기)

### Added — 도구 확장
- 서버 온보딩 (등록→테스트→Wiki 자동 생성)
- 서비스 설정 (Nginx/systemd/Compose 생성, 의존관계 맵)
- 보안 스캔 (포트, SSL, 인증 로그, 취약점, 파일 무결성)
- 네트워크 진단 (traceroute, MTR, DNS, 대역폭)
- IaC (Terraform plan/state, Ansible playbook)
- 인증서 관리 (SSL 모니터링, Let's Encrypt 갱신)
- 개발 환경 (프로젝트 스캔, Git 연동)
- Docker 확장 (+4: inspect, networks, volumes, prune)
- K8s 확장 (+5: nodes, top, ingress, hpa, contexts)
- Cloud 확장 (+4: RDS, ELB, Route53, IAM audit)

### Added — 멀티 클라우드
- GCP 연동 (Compute Engine, GKE)
- Azure 연동 (VM, AKS)

### Added — 플랫폼 통합
- DashboardMixin (12 REST 엔드포인트)
- WikiAutoSync (도구 실행→Wiki 자동 동기화)
- ServiceResolver (자연어 서비스 참조 해석)
- SRE 에이전트 (21 capability, 100+ 도구)
- 개발팀 페르소나 5개 (tech-lead, backend-dev, ui-dev, qa-engineer, planner)
- SSH 터널링 (TunnelManager)
- Wiki 확장 도구 7개 (create, delete, history, categories, recent, credential, runbook)
- Wiki 카테고리 5개 추가 (development, config, incident, network, backup)
- 서비스 시작 스크립트 (start.sh)

### Changed
- catalog.py: 15 → 23 Capability
- SRE 페르소나: 19 capability
- WikiStore.update_page(): structured_data 파라미터 추가

### Stats
- 신규 파일: 51개
- 신규 코드: +13,240줄
- 테스트: 1,226 passed (신규 65개)

## [1.0.0] - 이전 릴리즈
- 초기 버전 (Ops/Dev 에이전트, 54개 도구, GUI)
