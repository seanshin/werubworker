# WeruBWorker v2.3 기능 확장 기획서

> **작성일**: 2026-08-18  
> **구현 완료일**: 2026-08-18  
> **버전**: v2.2.2 → v2.3.0  
> **플랫폼**: AI 에이전트 기반 통합 운영 모니터링 플랫폼

---

## 1. v2.3.0 구현 결과 요약

| 항목 | v2.2.2 | v2.3.0 | 변화 |
|------|--------|--------|------|
| Capability | 23개 | 28개 | +5 |
| 도구 함수 | 244개 | 300+개 | +56 |
| REST API | 160+ | 210+개 | +50 |
| GUI View | 10개 (5개 미완) | 16개 (완성) | +6 |
| 모니터링 모듈 | 8개 | 12개 | +4 |
| Connector | 29개 | 32개 | +3 |
| 사이드바 메뉴 | 10개 | 14개 | +4 |

### 생성/수정된 파일 총계

| 구분 | 파일 수 |
|------|--------|
| 신규 백엔드 모듈 | 7개 |
| 수정된 백엔드 파일 | 8개 |
| 신규 프론트엔드 컴포넌트 | 4개 |
| 수정된 프론트엔드 파일 | 10개 |
| **합계** | **29개** |

---

## 2. Phase별 구현 완료 내역

### Phase 1: 모니터링 고도화 ✅

#### 1.1 실시간 메트릭 스트리밍 ✅
- [x] WebSocket `/ws/metrics` 엔드포인트 (app.py)
- [x] MetricCollector에 `on_collect` 콜백 (collector.py)
- [x] `broadcast_metrics` — 실시간 메트릭 push (manager.py)
- [x] `connectMetrics()` 프론트엔드 WebSocket 클라이언트 (api.ts)
- [x] MonitoringView 120포인트 버퍼 실시간 업데이트

#### 1.2 알림 에스컬레이션 정책 ✅
- [x] `EscalationPolicy`, `EscalationLevel` 모델 (alerting.py)
- [x] `check_escalations()` 단계별 자동 에스컬레이션 (alerting.py)
- [x] REST API 3개: CRUD `/v1/dashboard/escalation-policies`
- [x] GUI 에스컬레이션 정책 목록 (MonitoringView 알림 탭)

#### 1.3 AI 기반 이상 탐지 ✅
- [x] `anomaly.py` — Z-score + 이동평균 기반 탐지 (신규)
- [x] `AnomalyDetector.detect()` / `detect_all_servers()`
- [x] LLM 기반 원인 분석 (`analyze_with_llm`)
- [x] REST API 2개: GET anomalies, POST analyze
- [x] GUI 이상 배지 + AI 분석 버튼 (MonitoringView)

#### 1.4 인시던트 사후분석 자동화 ✅
- [x] `postmortem.py` — 컨텍스트 수집 + LLM 보고서 생성 (신규)
- [x] 템플릿 기반 + LLM 기반 이중 생성 모드
- [x] Wiki postmortem 페이지 자동 저장
- [x] REST API 2개: POST generate, POST save
- [x] GUI 사후분석 생성/AI 분석 버튼 (인시던트 탭)

---

### Phase 2: GUI 강화 ✅

#### 2.1 MonitoringView 대시보드 확장 ✅
- [x] "대시보드" 탭 추가 (기본 탭으로 설정)
- [x] `GaugeWidget` — SVG 원형 게이지 (CPU/MEM/DISK %)
- [x] 서버별 시계열 MiniChart + 활성 알림 요약
- [x] CSS Grid 기반 위젯 레이아웃

#### 2.2 로그 뷰어 ✅
- [x] `LogView.tsx` 신규 생성
- [x] 서버/심각도/패턴 필터, 10초 자동 갱신
- [x] 심각도별 색상 보더, 자동 스크롤 토글
- [x] REST API 3개: logs, sources, servers
- [x] 사이드바 "로그" 메뉴 추가

#### 2.3 DatabaseView 강화 ✅
- [x] 컬럼 헤더 클릭 정렬 (오름차순/내림차순)
- [x] CSV 다운로드 버튼
- [x] 쿼리 실행 시간(ms) 표시

#### 2.4 DevView 개선 ✅
- [x] 커밋 그래프 시각화 (세로 라인 + accent 점)

#### 2.5 네트워크 토폴로지 맵 ✅
- [x] `TopologyView.tsx` 신규 생성
- [x] SVG 기반 노드/에지 시각화 (local=중심, server=내부링, service=외부링)
- [x] 노드 클릭 시 상세 패널, 상태 인디케이터, 범례
- [x] REST API: GET `/v1/dashboard/topology`
- [x] 사이드바 "토폴로지" 메뉴 추가

---

### Phase 3: 자동화 고도화 ✅

#### 3.1 자동 복구 → 알림 연쇄 ✅
- [x] `AlertRule`에 `remediation_action_id`, `auto_remediate` 필드
- [x] `execute_and_verify()` — 복구→5초 대기→헬스체크→resolve/에스컬레이션
- [x] `_fire_alert()`에서 자동 복구 asyncio task 트리거
- [x] AlertEngine ↔ RemediationEngine 연결 (`set_remediation_engine`)
- [x] REST API 4개: actions CRUD, execute, executions

#### 3.2 조건부 자동화 워크플로우 ✅
- [x] `workflow.py` 신규 — WorkflowEngine, WorkflowStep, WorkflowCondition
- [x] 조건 평가: metric, time, result, always 타입
- [x] 단계 실행: shell, ssh, notify, check 액션
- [x] if/then/else 분기 (on_success/on_failure), 50단계 무한루프 방지
- [x] REST API 6개: CRUD + execute + executions

#### 3.3 멀티 서버 일괄 명령 ✅
- [x] `batch.py` 신규 — BatchSSH (병렬/롤링 실행)
- [x] 태그 기반 서버 그룹 필터링, semaphore 동시성 제한
- [x] 롤링 모드: 순차 실행 + 실패 시 중단 + 서버 간 지연
- [x] REST API 2개: tags, batch execute
- [x] OpsView에 일괄 명령 UI 카드

---

### Phase 4: 보안 및 운영 강화 ✅

#### 4.1 보안 스캔 고도화 ✅
- [x] `container_scan()` — Trivy CLI 연동 (로컬/SSH 원격)
- [x] `dependency_audit()` — npm audit / pip-audit 자동 감지
- [x] `firewall_check()` — iptables/ufw/nftables 규칙 검증
- [x] `security_score()` — 종합 보안 등급 A~D (SSL+포트+방화벽+인증)
- [x] `SecurityView.tsx` 신규 — 등급 게이지, 항목별 바, 컨테이너 스캔 UI
- [x] REST API 4개
- [x] 사이드바 "보안" 메뉴 추가

#### 4.2 백업/복원 시스템 ✅
- [x] `backup.py` 신규 — BackupManager (VACUUM INTO 안전 백업)
- [x] 8개 DB 대상 지원, S3 업로드, 보존 정책 pruning
- [x] 복원 시 pre_restore 자동 백업
- [x] `BackupView.tsx` 신규 — 대상 선택, 생성/복원/삭제 UI
- [x] REST API 6개
- [x] 사이드바 "백업" 메뉴 추가

#### 4.3 감사 대시보드 강화 ✅
- [x] `stats_by_period()` — 일별 감사 통계
- [x] `stats_by_user()` — 사용자별 활동 통계
- [x] `flagged_actions()` — 위험 행동 자동 플래깅
- [x] `export_csv()` — CSV 내보내기
- [x] MonitoringView 감사 탭: 일별 차트, 사용자 바, 위험 목록, CSV 링크
- [x] REST API 4개

---

### Phase 5: 외부 연동 확장 ✅

#### 5.1 Slack Bot 양방향 연동 ✅
- [x] `slack_bot.py` 신규 — SlackBot 클래스
- [x] 슬래시 명령어 8종: status, alerts, incidents, health, deploy, backup, score, help
- [x] 대화형 버튼 승인/거부 (`handle_interaction`)
- [x] 인시던트 스레드 생성 (`create_incident_thread`)
- [x] 채널↔세션 매핑 (`map_channel`, `list_mappings`)
- [x] REST API 4개: command, interaction, mappings CRUD

#### 5.2 원격 SSH 서버 온보딩 ✅
- [x] `onboarding.py` 신규 — ServerOnboarding 5단계 자동화
- [x] SSH 연결 테스트 → 시스템 정보 수집 → 프로필 저장 → Wiki 생성 → 헬스체크 설정
- [x] OpsView에 온보딩 폼 UI (7개 입력 필드 + 결과 표시)
- [x] REST API: POST `/v1/dashboard/servers/onboard`

#### 5.3 Gitea Webhook 연동 ✅
- [x] `gitea_webhook.py` 신규 — GiteaWebhookHandler
- [x] push, pull_request, issues, release, create, delete 이벤트 처리
- [x] HMAC-SHA256 서명 검증
- [x] SQLite 이벤트 기록 + 통계
- [x] DevView에 "Webhooks" 탭 추가
- [x] REST API 3개: webhook 수신, events, stats

---

### Phase 6: 이관 및 통합 ⏳ (추후 진행)

#### 6.1 GitHub → Gitea 이관
- [ ] Gitea 리포지토리 생성 및 미러 설정
- [ ] CI/CD 파이프라인 Gitea Actions로 마이그레이션
- [ ] GitHub 리포를 archive 처리
- [ ] Wiki/이슈/릴리즈 이관

#### 6.2 ITMS MCP 서버 연동
- [ ] .mcp.json에 ITMS MCP 서버 등록
- [ ] ITMS_API_KEY 환경변수 설정
- [ ] ITMS 도구 15개 WeruBWorker 카탈로그에 통합
- [ ] ITMS 대시보드 데이터 MonitoringView 연동

---

## 3. 신규 생성 파일 목록

### 백엔드 (7개)
| 파일 | 기능 |
|------|------|
| `coworker/monitoring/anomaly.py` | AI 이상 탐지 (Z-score + LLM) |
| `coworker/monitoring/postmortem.py` | 인시던트 사후분석 자동 생성 |
| `coworker/monitoring/backup.py` | 백업/복원 시스템 |
| `coworker/automation/workflow.py` | 조건부 워크플로우 엔진 |
| `coworker/connectors/ssh/batch.py` | 멀티 서버 병렬/롤링 SSH |
| `coworker/connectors/ssh/onboarding.py` | SSH 서버 온보딩 자동화 |
| `coworker/connectors/slack_bot.py` | Slack Bot 양방향 연동 |
| `coworker/connectors/gitea_webhook.py` | Gitea Webhook 이벤트 처리 |

### 프론트엔드 (4개)
| 파일 | 기능 |
|------|------|
| `surfaces/gui/src/components/LogView.tsx` | 로그 뷰어 |
| `surfaces/gui/src/components/TopologyView.tsx` | 네트워크 토폴로지 맵 |
| `surfaces/gui/src/components/SecurityView.tsx` | 보안 대시보드 |
| `surfaces/gui/src/components/BackupView.tsx` | 백업/복원 UI |

---

## 4. 신규 사이드바 메뉴

| 메뉴 | Surface | 컴포넌트 |
|------|---------|---------|
| 로그 | `logs` | LogView |
| 토폴로지 | `topology` | TopologyView |
| 보안 | `security` | SecurityView |
| 백업 | `backup` | BackupView |

---

## 5. 신규 REST API (50+개)

| Phase | 엔드포인트 수 | 주요 경로 |
|-------|-------------|----------|
| Phase 1 | 8개 | `/ws/metrics`, anomalies, escalation-policies, postmortem |
| Phase 2 | 4개 | logs, topology |
| Phase 3 | 12개 | remediation, workflows, batch |
| Phase 4 | 14개 | security, backups, audit stats/export |
| Phase 5 | 8개 | slack, servers/onboard, webhooks/gitea |

---

## 6. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| Gitea 이관 시 데이터 손실 | 높음 | GitHub 미러 유지, 단계적 이관 |
| 실시간 스트리밍 성능 | 중간 | 다운샘플링, 구독 필터 |
| 멀티서버 SSH 보안 | 높음 | 키 기반 인증만, sudo 샌드박싱 |
| LLM 비용 증가 (이상 탐지) | 중간 | 로컬 Ollama 우선, 클라우드 LLM 폴백 |
| GUI 복잡도 증가 | 중간 | 점진적 공개, 역할별 기본 뷰 |
