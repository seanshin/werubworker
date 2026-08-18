# WeruBWorker v2.3 기능 확장 기획서 (최종)

> **작성일**: 2026-08-18  
> **구현 완료일**: 2026-08-18  
> **버전**: v2.2.2 → v2.3.0  
> **플랫폼**: AI 에이전트 기반 통합 운영 모니터링 플랫폼  
> **인프라**: iMac (Apple M1) — Gitea + WeruBWorker + MCP 통합 운영

---

## 1. v2.3.0 구현 결과 요약

| 항목 | v2.2.2 | v2.3.0 | 변화 |
|------|--------|--------|------|
| Capability | 23개 | 28개 | +5 |
| 도구 함수 | 244개 | 300+개 | +56 |
| REST API | 160+ | 210+개 | +50 |
| MCP 도구 | 12개 | 27개 | +15 |
| GUI View | 10개 (5개 미완) | 16개 (완성) | +6 |
| 모니터링 모듈 | 8개 | 12개 | +4 |
| Connector | 29개 | 32개 | +3 |
| 사이드바 메뉴 | 10개 | 14개 | +4 |
| Git 리포지토리 | GitHub 단일 | Gitea(기본) + GitHub(백업) | 이관 |

### 생성/수정된 파일 총계

| 구분 | 파일 수 |
|------|--------|
| 신규 백엔드 모듈 | 9개 |
| 수정된 백엔드 파일 | 9개 |
| 신규 프론트엔드 컴포넌트 | 4개 |
| 수정된 프론트엔드 파일 | 10개 |
| 인프라 설정 | 2개 |
| **합계** | **34개** |

---

## 2. 통합 아키텍처

```
┌─ iMac (Apple M1, 16GB, macOS 26.5) ──────────────────────────────┐
│                                                                    │
│  ┌── Gitea (:3000) ──┐      ┌── WeruBWorker (:8765) ──┐          │
│  │  SQLite DB         │◄────►│  FastAPI 백엔드           │          │
│  │  Git 리포지토리     │ hook │  210+ REST API           │          │
│  │  Webhook 발신      │─────►│  Webhook 수신/처리        │          │
│  └────────────────────┘      │  WebSocket /ws/metrics   │          │
│                               │  WebSocket /ws/events    │          │
│  ┌── MCP Servers ────┐      │                           │          │
│  │  monitoring (12)   │◄────►│  모니터링/알림/인시던트     │          │
│  │  itms (15)         │◄────►│  보안/백업/워크플로우/배치  │          │
│  └────────────────────┘      └───────────────────────────┘          │
│                                          │                          │
│                               ┌── GUI (:1420) ──┐                  │
│                               │  React 18 + Vite │                  │
│                               │  16개 View        │                  │
│                               │  14개 사이드바 메뉴│                  │
│                               └──────────────────┘                  │
│                                                                    │
│  ┌── 기타 서비스 ────────────────────────────────────────┐          │
│  │  Ollama (:11434) · ComfyUI (:8188) · Cloudflare Tunnel │         │
│  └───────────────────────────────────────────────────────┘          │
└────────────────────────────────────────────────────────────────────┘
         │
         └── git push all → Gitea(기본) + GitHub(백업) 동시 push
```

### 서비스 시작

```bash
cd /Users/seanshin/ai/agent/openworker
./start.sh              # Gitea(3000) + 백엔드(8765) + 프론트엔드(1420) 통합 시작
./start.sh --stop       # 전체 중지
./start.sh --restart    # 재시작
./start.sh --status     # 상태 확인
```

### Git 운영

```bash
git push all main --tags   # Gitea + GitHub 동시 push (기본)
git push gitea main        # Gitea만
git push origin main       # GitHub만 (백업)
```

---

## 3. Phase별 구현 완료 내역

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

#### 2.2 로그 뷰어 ✅
- [x] `LogView.tsx` 신규 생성
- [x] 서버/심각도/패턴 필터, 10초 자동 갱신
- [x] 심각도별 색상 보더, 자동 스크롤 토글
- [x] REST API 3개 + 사이드바 "로그" 메뉴

#### 2.3 DatabaseView 강화 ✅
- [x] 컬럼 헤더 클릭 정렬 + CSV 다운로드 + 실행 시간 표시

#### 2.4 DevView 개선 ✅
- [x] 커밋 그래프 시각화 (세로 라인 + accent 점)

#### 2.5 네트워크 토폴로지 맵 ✅
- [x] `TopologyView.tsx` 신규 — SVG 노드/에지, 상세 패널, 범례
- [x] REST API + 사이드바 "토폴로지" 메뉴

---

### Phase 3: 자동화 고도화 ✅

#### 3.1 자동 복구 → 알림 연쇄 ✅
- [x] `AlertRule`에 `remediation_action_id`, `auto_remediate` 필드
- [x] `execute_and_verify()` — 복구→대기→헬스체크→resolve/에스컬레이션
- [x] `_fire_alert()`에서 자동 복구 asyncio task 트리거
- [x] REST API 4개: actions CRUD, execute, executions

#### 3.2 조건부 자동화 워크플로우 ✅
- [x] `workflow.py` 신규 — metric/time/result/always 조건, shell/ssh/notify 액션
- [x] if/then/else 분기 (on_success/on_failure), 50단계 무한루프 방지
- [x] REST API 6개: CRUD + execute + executions

#### 3.3 멀티 서버 일괄 명령 ✅
- [x] `batch.py` 신규 — 병렬/롤링 실행, 태그 필터, semaphore 동시성
- [x] REST API 2개 + OpsView 일괄 명령 UI

---

### Phase 4: 보안 및 운영 강화 ✅

#### 4.1 보안 스캔 고도화 ✅
- [x] `container_scan()` (Trivy), `dependency_audit()` (npm/pip), `firewall_check()`, `security_score()` (A~D 등급)
- [x] `SecurityView.tsx` 신규 — 등급 게이지, 항목별 바, 컨테이너 스캔 UI
- [x] REST API 4개 + 사이드바 "보안" 메뉴

#### 4.2 백업/복원 시스템 ✅
- [x] `backup.py` 신규 — VACUUM INTO 안전 백업, 8개 DB, S3 지원, pruning
- [x] `BackupView.tsx` 신규 — 대상 선택, 생성/복원/삭제 UI
- [x] REST API 6개 + 사이드바 "백업" 메뉴

#### 4.3 감사 대시보드 강화 ✅
- [x] 일별/사용자별 통계, 위험 행동 플래깅, CSV 내보내기
- [x] MonitoringView 감사 탭: 일별 차트, 사용자 바, 위험 목록
- [x] REST API 4개

---

### Phase 5: 외부 연동 확장 ✅

#### 5.1 Slack Bot 양방향 연동 ✅
- [x] `slack_bot.py` 신규 — 슬래시 명령어 8종, 버튼 승인/거부, 인시던트 스레드, 채널-세션 매핑
- [x] REST API 4개

#### 5.2 원격 SSH 서버 온보딩 ✅
- [x] `onboarding.py` 신규 — 5단계 자동화 (연결→정보수집→프로필→Wiki→헬스체크)
- [x] OpsView 온보딩 폼 UI + REST API

#### 5.3 Gitea Webhook 연동 ✅
- [x] `gitea_webhook.py` 신규 — push/PR/이슈/릴리스 처리, HMAC 검증
- [x] DevView "Webhooks" 탭 + REST API 3개

---

### Phase 6: Gitea 통합 + ITMS MCP ✅

#### 6.1 로컬 Gitea 설치 및 통합 ✅
- [x] Gitea 1.27.2 설치 (brew, SQLite 모드, :3000)
- [x] `start.sh`에 Gitea 통합 (시작/중지/상태)
- [x] GitHub → Gitea 전체 히스토리 + 태그 17개 이관
- [x] Gitea Webhook → WeruBWorker 자동 연동
- [x] dual-push remote (`all`): Gitea + GitHub 동시 push
- [x] GitHub는 백업 미러로 활성 유지
- [x] 원격 Gitea(gitea.weve.io.kr) 의존 제거

#### 6.2 ITMS MCP 서버 ✅
- [x] `itms_server.py` 신규 — 15개 ITMS 도구 (MCP stdio)
- [x] `.mcp.json`에 `werubworker-itms` 등록
- [x] 원격 ITMS(itms.weve.io.kr) 의존 제거, 로컬 통합

---

## 4. MCP 서버 구성

| 서버 | 도구 수 | 영역 |
|------|--------|------|
| **werubworker-monitoring** | 12개 | 메트릭, 헬스체크, 알림, 인시던트, 감사, 대시보드, 웹훅 |
| **werubworker-itms** | 15개 | 보안(4), 백업(3), 이상탐지(1), 사후분석(1), 워크플로우(2), 배치SSH(2), Gitea(2) |
| **합계** | **27개** | |

### ITMS MCP 도구 목록

| # | 도구 | 설명 |
|---|------|------|
| 1 | `security_score` | 종합 보안 등급 (A~D) |
| 2 | `container_scan` | 컨테이너 취약점 (Trivy) |
| 3 | `dependency_audit` | 의존성 취약점 (npm/pip) |
| 4 | `firewall_check` | 방화벽 규칙 검증 |
| 5 | `backup_create` | 데이터 백업 생성 |
| 6 | `backup_list` | 백업 이력 조회 |
| 7 | `backup_restore` | 데이터 복원 |
| 8 | `anomaly_detect` | 이상 탐지 (Z-score) |
| 9 | `postmortem_generate` | 사후분석 보고서 생성 |
| 10 | `workflow_list` | 워크플로우 목록 |
| 11 | `workflow_execute` | 워크플로우 실행 |
| 12 | `batch_execute` | 멀티서버 일괄 명령 |
| 13 | `batch_servers` | 서버/태그 목록 |
| 14 | `gitea_repos` | Gitea 리포 목록 |
| 15 | `gitea_webhook_events` | Webhook 이벤트 이력 |

---

## 5. 신규 생성 파일 목록

### 백엔드 (9개)

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
| `coworker/mcp/itms_server.py` | ITMS MCP 서버 (15 tools) |

### 프론트엔드 (4개)

| 파일 | 기능 |
|------|------|
| `surfaces/gui/src/components/LogView.tsx` | 로그 뷰어 |
| `surfaces/gui/src/components/TopologyView.tsx` | 네트워크 토폴로지 맵 |
| `surfaces/gui/src/components/SecurityView.tsx` | 보안 대시보드 |
| `surfaces/gui/src/components/BackupView.tsx` | 백업/복원 UI |

---

## 6. 신규 사이드바 메뉴

| 메뉴 | Surface | 컴포넌트 |
|------|---------|---------|
| 로그 | `logs` | LogView |
| 토폴로지 | `topology` | TopologyView |
| 보안 | `security` | SecurityView |
| 백업 | `backup` | BackupView |

---

## 7. 신규 REST API (50+개)

| Phase | 엔드포인트 수 | 주요 경로 |
|-------|-------------|----------|
| Phase 1 | 8개 | `/ws/metrics`, anomalies, escalation-policies, postmortem |
| Phase 2 | 4개 | logs, topology |
| Phase 3 | 12개 | remediation, workflows, batch |
| Phase 4 | 14개 | security, backups, audit stats/export |
| Phase 5 | 8개 | slack, servers/onboard, webhooks/gitea |
| Phase 6 | 4개 | (MCP stdio + Gitea webhook 기등록) |

---

## 8. 리스크 및 대응

| 리스크 | 영향 | 대응 | 상태 |
|--------|------|------|------|
| Gitea 이관 시 데이터 손실 | 높음 | GitHub 백업 미러 활성 유지 | ✅ 해소 |
| 실시간 스트리밍 성능 | 중간 | 다운샘플링, 구독 필터 | ✅ 구현 |
| 멀티서버 SSH 보안 | 높음 | 키 기반 인증, sudo 샌드박싱 | ✅ 구현 |
| LLM 비용 증가 | 중간 | 로컬 Ollama 우선, 명시적 요청 시만 LLM 호출 | ✅ 구현 |
| GUI 복잡도 증가 | 중간 | 점진적 공개, 역할별 뷰 | ✅ 구현 |
| 단일 장애점 (iMac) | 중간 | GitHub 백업 + 로컬 백업 시스템 | ✅ 해소 |
| 원격 서비스 의존 | 중간 | 원격 Gitea/ITMS 제거, 전부 로컬화 | ✅ 해소 |
