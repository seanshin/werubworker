# Changelog

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
