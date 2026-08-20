# Changelog

## [Unreleased]

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
