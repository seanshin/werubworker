# 개발팀 병렬 개발 조율 가이드

## 1. 팀 구성

### 1.1 개발팀장 (tech-lead)
- 역할: 아키텍처 의사결정, 코드 리뷰, 모듈 간 인터페이스 정의
- 담당 파일: catalog.py, agents/sre.py, agents/registry.py, server/manager.py 확장
- 권한: 모든 파일 변경 가능, PR 승인 권한

### 1.2 백엔드 개발자 1 (backend-dev-1)
- 역할: 모니터링 코어, 데이터 수집, 인시던트 관리
- 담당 파일: monitoring/timeseries.py, monitoring/collector.py, monitoring/incidents.py, monitoring/log_aggregator.py, tools/server_setup.py, tools/dev_setup.py, wiki/resolver.py
- 의존성: SSH 모듈(기존), WikiStore(기존)

### 1.3 백엔드 개발자 2 (backend-dev-2)
- 역할: 알림, 헬스체크, 자동 복구, 도구 확장
- 담당 파일: monitoring/healthcheck.py, monitoring/alerting.py, monitoring/remediation.py, monitoring/audit_ops.py, tools/service_config.py, wiki/sync.py, wiki/tools.py 확장
- 의존성: Connectors(기존), Scheduler(기존)

### 1.4 UI 개발자 (ui-dev)
- 역할: 대시보드 API, REST 엔드포인트, WebSocket 스트리밍
- 담당 파일: server/dashboard_mixin.py, server/app.py 확장
- 의존성: Phase 1 백엔드 모듈

### 1.5 QA 엔지니어 (qa-engineer)
- 역할: 테스트 작성, CI 파이프라인, 코드 품질
- 담당 파일: tests/test_*.py (신규 모듈 전체)
- 의존성: 각 모듈 구현 완료 후

### 1.6 기획자 (planner)
- 역할: 기획서 보완, Wiki 카테고리/템플릿 정의, 사용자 시나리오
- 담당 파일: docs/, wiki/store.py WIKI_TEMPLATES 확장
- 의존성: 없음

## 2. 병렬 개발 규칙

### 2.1 동시 작업 가능한 조합
```
Phase 1 (동시 진행 가능):
  백엔드-1: timeseries.py + collector.py (직렬)
  백엔드-2: healthcheck.py + alerting.py (직렬)
  기획자: Wiki 카테고리/템플릿 정의 + 시나리오 문서
  
Phase 1 완료 후:
  UI 개발: dashboard_mixin.py (백엔드 모듈 의존)
  QA: Phase 1 테스트 작성
  개발팀장: catalog.py 확장 + SRE 에이전트

Phase 2 (동시 진행 가능):
  백엔드-1: incidents.py + log_aggregator.py + server_setup.py + dev_setup.py + wiki/resolver.py
  백엔드-2: remediation.py + audit_ops.py + service_config.py + wiki/sync.py + wiki/tools.py
  QA: Phase 2 테스트 (모듈 완료 순)
  
Phase 3 (동시 진행 가능):
  백엔드-1: k8s 확장 + cloud 확장 + security_scan.py
  백엔드-2: docker 확장 + ci_cd 확장 + network_diag.py
  UI 개발: Wiki/서비스/인프라 REST API
  QA: Phase 3 테스트
```

### 2.2 충돌 방지 규칙
- catalog.py: 개발팀장만 수정, 다른 개발자는 새 도구 모듈만 생성
- server/manager.py: 개발팀장만 수정 (mixin 추가 등)
- server/app.py: UI 개발자만 수정 (라우트 추가)
- wiki/store.py: WIKI_TEMPLATES 확장은 기획자, 스키마 변경은 개발팀장
- 각 도구 모듈 (tools/*.py, monitoring/*.py): 담당 개발자만 수정

### 2.3 인터페이스 계약
각 모듈 간 인터페이스는 개발팀장이 먼저 정의:
- TimeSeriesStore: record(), query(), downsample(), prune() 시그니처
- AlertEngine: evaluate(), send_alert() 시그니처
- HealthCheckManager: add_check(), run_checks() 시그니처
- IncidentManager: create(), update_status() 시그니처
- WikiAutoSync: on_tool_result() 시그니처
- DashboardMixin: 메서드 시그니처 + Pydantic 모델

## 3. 코드 스타일 규칙

### 3.1 프로젝트 기존 패턴 (반드시 준수)
- 도구 정의: `_attach(fn, schema, approval, caps)` 패턴
- 메타데이터: `_meta(name, approval, capabilities)` 패턴
- 스키마: `_schema(name, description, properties, required)` 패턴
- 도구 팩토리: `def xxx_tools(context: AgentContext) -> list` 패턴
- 데이터클래스: `@dataclass` + `to_dict()` / `from_dict()` 패턴
- SQLite: `threading.Lock` + `_connect()` + WAL 모드
- 에러 반환: `{"ok": False, "error": "message"}` 패턴
- 성공 반환: `{"ok": True, ...}` 패턴

### 3.2 린터/포맷터
- ruff (target-version = py312, line-length = 100)
- ignore: E501, E402, E702, E731, E741, F401, F811, F841

## 4. 커밋 및 브랜치 전략

### 4.1 브랜치 명명
- feature/phase1-timeseries
- feature/phase1-collector
- feature/phase1-healthcheck
- feature/phase1-alerting
- feature/phase2-incidents
- feature/phase2-remediation
- etc.

### 4.2 커밋 메시지
```
feat(monitoring): add TimeSeriesStore with downsampling
fix(alerting): handle cooldown edge case
test(healthcheck): add HTTP/TCP check tests
docs(wiki): add new category templates
```

### 4.3 PR 규칙
- 개발팀장 코드 리뷰 필수
- 테스트 통과 필수 (pytest)
- ruff 검사 통과 필수

## 5. 에이전트 실행 방법

각 에이전트는 WeruBWorker의 페르소나 시스템으로 실행됩니다:
```bash
# 세션에서 페르소나 선택
werubworker --model anthropic:claude-opus-4-8

# 또는 서버 모드에서 세션 생성 시 agent 파라미터
# POST /v1/sessions {"agent": "tech-lead"}
# POST /v1/sessions {"agent": "backend-dev"}
```

## 6. 의사소통 채널
- 작업 배분: 세션 내 todo_write 도구로 진행 추적
- 인터페이스 정의: Wiki 페이지에 기록 (category: architecture)
- 코드 리뷰: git diff + code_review 도구
- 이슈 트래킹: Gitea (itms.weve.io.kr) 연동 예정
