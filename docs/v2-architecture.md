# WeruBWorker v2.0 아키텍처

> 최종 갱신: 2026-08-13 | 대상 릴리즈: v2.0.0

---

## 1. 시스템 전체 구조

```
                          ┌─────────────────────────────────────────┐
                          │            FastAPI (app.py)             │
                          │  CORS · Origin Gate · Token Auth · WS   │
                          └──────────────┬──────────────────────────┘
                                         │
                          ┌──────────────▼──────────────────────────┐
                          │         SessionManager (7 Mixin)        │
                          │                                         │
                          │  AutomationMixin   ConnectorMixin       │
                          │  DashboardMixin    InboxMixin           │
                          │  ProviderMixin     SettingsMixin        │
                          │  SkillsMixin                            │
                          └──────────────┬──────────────────────────┘
                                         │
                          ┌──────────────▼──────────────────────────┐
                          │          TurnEngine (engine.py)         │
                          │                                         │
                          │  Provider ↔ ToolRegistry ↔ Permissions  │
                          │  Approver (Inbox) · Compaction          │
                          └──────┬───────────────┬──────────────────┘
                                 │               │
                    ┌────────────▼───┐   ┌───────▼──────────────┐
                    │  21 Capability │   │   WikiAutoSync Hook  │
                    │  (catalog.py)  │   │   (wiki/sync.py)     │
                    │  100+ 도구     │   │                      │
                    └────────────────┘   │  도구 실행 결과 →     │
                                         │  Wiki structured_data│
                                         │  자동 업데이트        │
                                         └──────────────────────┘
                                                    │
              ┌─────────────────────────────────────▼────────────────┐
              │               모니터링 서브시스템 (monitoring/)       │
              │                                                      │
              │  MetricCollector → TimeSeriesStore (raw→5m→1h→1d)    │
              │  HealthCheckManager · AlertEngine · IncidentManager  │
              │  RemediationEngine · LogAggregator · OpsAuditStore   │
              └──────────────────────────────────────────────────────┘
```

### 핵심 흐름

1. **FastAPI** 가 HTTP/WS 요청을 수신하고 인증·CORS를 검증한다.
2. **SessionManager** 가 세션별 TurnEngine을 생성·관리하며, 7개 Mixin이 REST API를 확장한다.
3. **TurnEngine** 이 모델(Provider)과 도구(ToolRegistry) 사이의 반복 루프를 실행한다.
4. **Catalog** 의 21 Capability가 페르소나의 `tools:` 목록을 실제 도구 함수로 전개(expand)한다.
5. **WikiAutoSync** 가 도구 실행 결과를 후킹하여 Wiki의 `structured_data`를 자동 갱신한다.
6. **모니터링 서브시스템** 이 시계열 메트릭, 헬스체크, 알림, 인시던트, 자동 복구, 감사 로그를 관리한다.

---

## 2. 모니터링 서브시스템 아키텍처

```
MetricCollector (collector.py)
        │
        │  수집: SSH/API/에이전트 → raw 메트릭
        ▼
TimeSeriesStore (timeseries.py)
        │
        │  metrics_raw (1분) ─→ metrics_5m ─→ metrics_1h ─→ metrics_1d
        │  보존: raw 7일 / 5m 30일 / 1h 90일 / 1d 365일
        │  SQLite WAL 모드 · 자동 다운샘플링
        ▼
HealthCheckManager (healthcheck.py)
        │
        │  주기적 헬스체크 · 상태 이력
        ▼
AlertEngine (alerting.py)
        │
        │  규칙 평가 → 조건 충족 시 알림 발송
        │  활성 알림 / 해제 이력 관리
        ▼
IncidentManager (incidents.py)
        │
        │  인시던트 타임라인 · 사후분석(Post-mortem)
        │  active / resolved 상태 관리
        ▼
RemediationEngine (remediation.py)
        │
        │  자동 복구 액션 → Inbox 승인 연동
        │  복구 실행 이력 추적
        ▼
LogAggregator (log_aggregator.py)
        │
        │  멀티서버 로그 수집 · 검색
        ▼
OpsAuditStore (audit_ops.py)
        │
        │  운영 변경사항 감사 로그
        │  최근 이력 조회
```

### 시계열 테이블 구조

| 테이블 | 해상도 | 보존 기간 | 용도 |
|--------|--------|-----------|------|
| `metrics_raw` | 1분 | 7일 | 실시간 상세 분석 |
| `metrics_5m` | 5분 | 30일 | 단기 트렌드 |
| `metrics_1h` | 1시간 | 90일 | 주간/월간 분석 |
| `metrics_1d` | 1일 | 365일 | 장기 용량 계획 |

쿼리 시 `auto_select_table(range_secs)` 가 요청 범위에 맞는 최적 테이블을 자동 선택한다.

---

## 3. 서비스 위키 리포지토리 아키텍처

### 3계층 구조

```
┌─────────────────────────────────────────────────┐
│  연동(Connect) 계층                              │
│                                                  │
│  ServiceResolver: 자연어 → Wiki 페이지 → 설정    │
│  WikiAutoSync:    도구 실행 → structured_data     │
│  WikiSync:        secrets.json ↔ Wiki 양방향     │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│  분석(Analyze) 계층                              │
│                                                  │
│  FTS5 전문 검색 · 카테고리 필터링                 │
│  프롬프트 A/B 테스트 · 벤치마크 · 런북 실행       │
│  비용 계산 · 요약 생성                            │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│  저장(Store) 계층                                │
│                                                  │
│  WikiStore: SQLite + FTS5 (wiki.db)              │
│  Vault: AES-256 암호화 자격증명 (vault.json)     │
│  버전 이력: 모든 편집 기록 보존                   │
│  카테고리별 템플릿 (model, prompt, service, ...)  │
└──────────────────────────────────────────────────┘
```

### WikiAutoSync 동작 원리

TurnEngine에서 도구가 실행될 때마다 `on_tool_result()` 훅이 호출된다.
등록된 핸들러가 결과를 파싱하여 관련 Wiki 페이지의 `structured_data`를 자동 업데이트한다.

| 도구 이름 | 대상 Wiki 페이지 | 업데이트 내용 |
|-----------|-----------------|---------------|
| `ssh_server_status` | `server-{id}` | CPU, 메모리, 디스크, 업타임 |
| `ssh_execute` | `server-{id}` | 마지막 접근 시각, 실행 명령 |
| `db_status` | `database-{name}` | 버전, 활성 연결 수, 용량 |
| `db_query` | `database-{name}` | 마지막 접근 시각, 쿼리 유형 |
| `docker_ps` | `server-{id}` | 컨테이너 목록 (최대 50개) |
| `k8s_pods` | `server-k8s-{cluster}` | Pod 수, Running/Failed 카운트 |
| `server_status` | `server-__local__` | CPU, 메모리, 디스크, 로드 |

### ServiceResolver 흐름

```
자연어 질의 ("production DB")
        │
        ▼
FTS5 검색 (최대 10건)
        │
        ▼
linked_service 매칭 → SecretStore 조회
        │
        ▼
민감 정보 필터링 후 설정 반환
```

---

## 4. 도구 카탈로그 구조

### 21개 Capability 전체 목록

| # | id | name | requires | risk | 도구 예시 |
|---|-----|------|----------|------|-----------|
| 1 | `code_files` | Code files | workspace | READ, WRITE_LOCAL | read_file, write_file, list_dir |
| 2 | `files` | Files | workspace | READ, WRITE_LOCAL | multi-root read/write |
| 3 | `git` | Git | workspace | READ | git_status, git_diff, git_log |
| 4 | `search` | Search | workspace | READ | grep (ripgrep) |
| 5 | `shell` | Shell | executor | EXEC | run_shell, background tasks |
| 6 | `todo` | Task list | todo | READ | todo_write |
| 7 | `server_monitor` | Server monitoring | - | READ | server_status, service_status, check_ports |
| 8 | `ci_cd` | CI/CD pipelines | - | EXEC | ci_status, ci_trigger, ci_logs, deploy_rollback |
| 9 | `cloud_infra` | Cloud infrastructure | secrets | READ, EXTERNAL | aws_ec2_list, cf_dns_list, wasabi_list (+GCP, Azure) |
| 10 | `database` | Database management | secrets | EXEC | db_query, db_status, db_tables, db_backup |
| 11 | `code_review` | Code review | - | READ | review_pr, review_security, review_test_coverage |
| 12 | `docker` | Docker management | - | EXEC | docker_ps, docker_logs, docker_restart |
| 13 | `k8s` | Kubernetes management | - | EXEC | k8s_pods, k8s_logs, k8s_describe, k8s_scale |
| 14 | `ssh` | SSH remote access | secrets | EXEC | ssh_tools (시스템 SSH 기반) |
| 15 | `wiki` | Service Wiki | secrets | READ | wiki_search, wiki_get, wiki_update |
| 16 | `monitoring` | Infrastructure monitoring | secrets | READ, EXTERNAL | metrics_latest, metrics_query, healthcheck_list |
| 17 | `server_setup` | Server onboarding | secrets | EXEC, EXTERNAL | 서버 등록, 연결 테스트, Wiki 자동 문서화 |
| 18 | `service_config` | Service configuration | secrets | EXEC | nginx/systemd/compose 설정, 의존관계 매핑 |
| 19 | `dev_setup` | Development environment | workspace, secrets | READ, WRITE_LOCAL | 프로젝트 스캔, Git 연동, 개발환경 문서 |
| 20 | `security_scan` | Security scanning | secrets | READ, EXTERNAL | 포트 스캔, SSL 검증, auth 로그 분석 |
| 21 | `network_diag` | Network diagnostics | - | READ | traceroute, MTR, DNS 조회, 대역폭 테스트 |
| - | `iac` | Infrastructure as Code | workspace, executor | EXEC | Terraform plan/state, Ansible playbook |
| - | `cert_mgmt` | Certificate management | secrets | EXEC | SSL/TLS 만료 모니터링, 갱신 트리거 |

> 총 23개 Capability 등록 (catalog.py `_CAPS` 리스트 기준).
> 페르소나별로 필요한 capability만 선택하여 사용.

### 도구 정의 패턴

각 도구 모듈은 `tools/` 디렉토리에 위치하며, 팩토리 패턴을 따른다:

```python
# tools/xxx.py — 도구 팩토리 패턴
def xxx_tools(context: AgentContext) -> list:
    """AgentContext를 받아 도구 함수 리스트를 반환."""

    def tool_action(param: str) -> dict:
        """도구 함수 — _attach/_meta/_schema 데코레이터로 메타데이터 부착."""
        ...
        return {"ok": True, "result": ...}

    # 메타데이터 부착
    tool_action._meta = {"name": "tool_action", "description": "..."}
    tool_action._schema = {"param": {"type": "string", "description": "..."}}

    return [tool_action]
```

### Capability 전개 흐름

```
페르소나 manifest (tools: [shell, docker, k8s, ...])
        │
        ▼
catalog.expand(ids, context)
        │
        ├── capability.available(context) → requires 검증
        │   (workspace? executor? secrets? todo?)
        │
        ├── capability.build(context) → 도구 함수 리스트 반환
        │
        └── 불충족 capability는 조용히 스킵
        │
        ▼
ToolRegistry에 등록 → TurnEngine에서 사용
```

---

## 5. 데이터 저장소 구조

```
~/.config/werubworker/
├── coworker.db           # 세션 인덱스, 메모리, 설정
│                         # SQLite WAL 모드
│
├── wiki.db               # 서비스 위키 (FTS5 전문 검색)
│                         # 페이지, 버전 이력, 카테고리, 태그
│
├── monitoring.db          # 시계열 메트릭 (4단계 해상도)
│                         # 헬스체크, 알림, 인시던트, 복구, 감사
│
├── automation.db          # 스케줄 작업, 실행 이력 (TaskStore)
│
├── secrets.json           # API 키, SSH 프로필 (파일 권한 0600)
│                         # SecretStore 관리
│
├── vault.json             # 암호화 자격증명 (AES-256-GCM)
│                         # 마스터 비밀번호로 복호화
│                         # 키 회전, 만료 관리, 감사 로그
│
└── conversations/         # 대화 기록 (세션별 .jsonl 파일)
                          # append-only, 컴팩션 지원
```

### 저장소 설계 원칙

- **SQLite WAL 모드**: 동시 읽기/쓰기 성능 보장, 크래시 복구 안정성
- **FTS5**: Wiki 전문 검색 인덱스 (한국어 포함)
- **JSONL**: 대화 기록은 append-only로 기록, 컴팩션으로 크기 관리
- **파일 권한 0600**: secrets.json은 소유자만 읽기/쓰기 가능

---

## 6. 에이전트/페르소나 구조

### 에이전트 레지스트리

기본 제공 에이전트 (`coworker/agents/`):

| 에이전트 | 모듈 | 역할 |
|---------|------|------|
| cowork | `cowork.py` | 범용 지식 업무 (기본) |
| code | `code.py` | 코드 편집, 디버깅, 리팩토링 |
| chat | `chat.py` | 자유 대화 |
| ops | `ops.py` | 서버 운영, 인프라 관리 |
| dev | `dev.py` | 개발 환경 셋업 |
| sre | `sre.py` | SRE (Site Reliability Engineering) |

### 11개 빌트인 페르소나

`coworker/personas/builtin/` 디렉토리에 YAML frontmatter + 마크다운 형식으로 정의:

| 페르소나 | family | 특화 영역 |
|---------|--------|----------|
| cowork | knowledge | 범용 지식 업무 |
| code | - | 코드 작성, 리뷰 |
| chat | - | 일반 대화 |
| ops | knowledge | 서버 운영 |
| dev | knowledge | 개발 환경 |
| sre | knowledge | 인프라 신뢰성 |
| tech-lead | knowledge | 기술 리드 |
| backend-dev | knowledge | 백엔드 개발 |
| ui-dev | knowledge | UI/프론트엔드 개발 |
| qa-engineer | knowledge | QA/테스트 |
| planner | knowledge | 프로젝트 계획 |

### SRE 페르소나 상세

SRE는 가장 많은 capability를 사용하는 페르소나로, 19개 capability (100+ 도구)를 로드한다:

```yaml
tools:
  - files          - search        - shell
  - todo           - server_monitor - ssh
  - docker         - k8s           - database
  - cloud_infra    - wiki          - monitoring
  - ci_cd          - server_setup  - service_config
  - security_scan  - network_diag  - iac
  - cert_mgmt
```

### 페르소나 Manifest YAML 형식

```yaml
---
id: <고유 ID>
name: <표시 이름>
icon: <아이콘>
tagline: <한 줄 설명>
family: knowledge | code | chat
tools: [capability_id, ...]
messaging: true | false        # 메시징 커넥터 활성화
connectors: true | false       # 외부 연동 활성화
recommended_models: [provider:model, ...]
default_permission_mode: interactive | auto | plan
description: <상세 설명>
recommends:
  - connector: <커넥터명>
    reason: <추천 이유>
    tier: core | optional
---
<시스템 프롬프트 (마크다운)>
```

---

## 7. API 엔드포인트 맵

### 인증 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/auth/status` | 인증 상태 확인 |
| POST | `/v1/auth/setup` | 초기 마스터 비밀번호 설정 |
| POST | `/v1/auth/login` | 로그인 (토큰 발급) |
| POST | `/v1/auth/logout` | 로그아웃 |
| POST | `/v1/auth/change-password` | 비밀번호 변경 |

### 세션 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/sessions` | 세션 목록 |
| GET | `/v1/sessions/{id}/messages` | 세션 메시지 조회 |
| PATCH | `/v1/sessions/{id}` | 세션 메타 수정 (제목, 고정, 아카이브) |
| DELETE | `/v1/sessions/{id}` | 세션 삭제 |
| GET/POST | `/v1/sessions/{id}/roots` | 작업 디렉토리 관리 |
| GET/POST | `/v1/sessions/{id}/skills` | 세션 스킬 관리 |
| GET/POST | `/v1/sessions/{id}/connections` | 세션 커넥터 관리 |
| GET/POST | `/v1/sessions/{id}/unattended` | 무인 모드 관리 |

### 에이전트/페르소나 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/agents` | 에이전트 목록 |
| GET | `/v1/personas` | 페르소나 목록 |
| POST | `/v1/personas/install` | 페르소나 설치 |
| GET/POST/DELETE | `/v1/personas/{id}` | 페르소나 CRUD |
| POST | `/v1/personas/{id}/enable` | 페르소나 활성화 |
| POST | `/v1/personas/{id}/connections` | 페르소나 커넥터 설정 |

### Inbox/구독 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/inbox` | Inbox 항목 목록 |
| POST | `/v1/inbox/{id}/resolve` | Inbox 항목 승인/거부 |
| GET | `/v1/inbox/reconcile` | Inbox 정합성 확인 |
| GET/POST | `/v1/inbox/routing` | Inbox 라우팅 규칙 |
| GET/POST | `/v1/subscriptions` | 채널 구독 관리 |

### 자동화 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET/POST | `/v1/automations` | 스케줄 작업 목록/생성 |
| GET/PATCH/DELETE | `/v1/automations/{id}` | 작업 상세/수정/삭제 |
| POST | `/v1/automations/{id}/run` | 작업 수동 실행 |

### 대시보드 API (신규)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/dashboard/overview` | 인프라 전체 현황 (서버, 알림, 헬스체크, 인시던트) |
| GET | `/v1/dashboard/servers/{id}/metrics` | 서버별 시계열 메트릭 (범위: 15m~30d) |
| GET | `/v1/dashboard/alerts` | 알림 피드 (활성 + 이력) |
| GET | `/v1/dashboard/incidents` | 인시던트 목록 (상태 필터) |
| GET | `/v1/dashboard/audit` | 운영 감사 로그 |

### 인프라 API (신규)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/infrastructure/servers` | 전체 서버 현황 + 최신 메트릭 |
| GET | `/v1/infrastructure/topology` | 서비스 의존관계 맵 (Wiki 기반) |
| GET | `/v1/services` | 서비스 목록 |
| GET | `/v1/services/{ref}` | 서비스 상세 (ServiceResolver) |

### Wiki API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/wiki` | 페이지 목록 (카테고리/검색 필터) |
| GET | `/v1/wiki/categories` | 카테고리 목록 |
| GET | `/v1/wiki/search` | FTS5 전문 검색 |
| GET | `/v1/wiki/alerts` | Wiki 알림 |
| GET | `/v1/wiki/{id}` | 페이지 상세 |
| POST | `/v1/wiki` | 페이지 생성 |
| PUT | `/v1/wiki/{id}` | 페이지 수정 |
| DELETE | `/v1/wiki/{id}` | 페이지 삭제 |
| GET | `/v1/wiki/{id}/history` | 편집 이력 |
| POST | `/v1/wiki/{id}/restore` | 버전 복원 |
| POST | `/v1/wiki/{id}/sync` | secrets.json 동기화 |
| POST | `/v1/wiki/import-secrets` | 전체 시크릿 임포트 |
| POST | `/v1/wiki/analyze` | Wiki 분석 |
| POST | `/v1/wiki/export` | Wiki 내보내기 |
| POST | `/v1/wiki/import` | Wiki 가져오기 |
| GET | `/v1/wiki/prompts` | 프롬프트 목록 |
| POST | `/v1/wiki/prompts/{id}/test` | 프롬프트 테스트 |
| POST | `/v1/wiki/prompts/{id}/ab-test` | A/B 테스트 |
| GET | `/v1/wiki/benchmarks` | 벤치마크 목록 |
| GET | `/v1/wiki/runbooks` | 런북 목록 |
| POST | `/v1/wiki/runbooks/{id}/execute` | 런북 실행 |
| GET | `/v1/wiki/templates` | 템플릿 목록 |

### Vault API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/v1/vault/rotate/{key}` | 키 회전 |
| GET | `/v1/vault/audit` | Vault 감사 로그 |
| GET | `/v1/vault/expiring` | 만료 예정 자격증명 |

### 기타 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/health` | 헬스체크 |
| POST | `/v1/chat/completions` | OpenAI 호환 프록시 |
| GET/POST | `/v1/mcp` | MCP 서버 관리 |
| GET/POST | `/v1/skills` | 스킬 관리 |
| GET/POST | `/v1/memory` | 메모리 관리 |
| POST | `/v1/security/filter-test` | 보안 필터 테스트 |

---

## 8. 보안 아키텍처

### 인증 계층

```
┌─────────────────────────────────────────────┐
│  1단계: 마스터 비밀번호 (LocalAuth)          │
│  - 초기 설정 시 해시 저장                     │
│  - 로그인 시 세션 토큰 발급                   │
├─────────────────────────────────────────────┤
│  2단계: API 토큰 인증                        │
│  - 모든 API 요청에 Bearer 토큰 필수          │
│  - 인증 면제 경로: /v1/health, /v1/auth/*    │
├─────────────────────────────────────────────┤
│  3단계: CORS Origin 검증                     │
│  - 허용 Origin: tauri://localhost,           │
│    http(s)://localhost, 127.0.0.1            │
│  - Origin 없는 요청 (curl, 네이티브) 허용     │
│  - 브라우저 CSRF 공격 방어                    │
├─────────────────────────────────────────────┤
│  4단계: WebSocket 보호                       │
│  - 프레임 크기 제한: 16 MiB                   │
│  - 요청 속도 제한: 30회/10초                  │
│  - 메시지 텍스트 제한: 200,000자              │
│  - 첨부파일 크기 제한: 15 MB                  │
└─────────────────────────────────────────────┘
```

### 권한 엔진 (PermissionEngine)

```
도구 호출 요청
        │
        ▼
PermissionEngine.check()
        │
        ├── Mode 확인
        │   ├── DISCUSS / PLAN → 읽기 전용 (쓰기/실행 거부)
        │   ├── INTERACTIVE → 읽기 자동 허용, 쓰기/실행은 사용자 승인
        │   ├── AUTO → 전체 허용 (경로 범위 내)
        │   └── CUSTOM → interactive + auto_allow 도구 자동 허용
        │
        ├── RiskClass 분류
        │   ├── READ → 자동 허용
        │   ├── WRITE_LOCAL → 경로 검증 후 허용/승인 요청
        │   ├── EXEC → 명령어 패턴 검증 → 셸 메타문자 검출 시 승인 필수
        │   └── EXTERNAL → 외부 API 호출, 승인 필요
        │
        └── 결과: allow / deny / needs_user
                                │
                                ▼
                        TurnEngine → Approver (Inbox)
                                │
                                ├── ONCE: 이번 한 번만 허용
                                ├── ALWAYS_TOOL: 이 도구 항상 허용 (세션 범위)
                                ├── ALWAYS_COMMAND: 이 명령 항상 허용 (세션 범위)
                                └── DENY: 거부
```

### 데이터 보호

| 보호 대상 | 메커니즘 | 상세 |
|-----------|---------|------|
| API 키, SSH 프로필 | `secrets.json` (0600) | 파일 시스템 권한으로 소유자만 접근 |
| 자격증명 값 | `vault.json` (AES-256-GCM) | 마스터 비밀번호 기반 암호화, 키 회전 지원 |
| Wiki 자격증명 | Vault 참조 | Wiki에는 키 이름만, 실제 값은 Vault에 저장 |
| 데이터베이스 | SQLite WAL 모드 | 크래시 복구 안정성, 무결성 보장 |
| 셸 명령 | 메타문자 탐지 | `;`, `&`, `|`, `>`, `` ` ``, `$(` 포함 시 승인 필수 |
| 응답 필터링 | `response_filter.py` | 민감 정보 출력 방지 |
| 요청 속도 | `rate_limiter.py` | API 요청 속도 제한 |
| 감사 추적 | `AuditStore` + `OpsAuditStore` | 모든 운영 변경사항 기록 |
