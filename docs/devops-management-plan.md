# WeruBWorker 개발관리 및 서버관리 강화 기획서

## 1. 개요

WeruBWorker를 개발팀과 운영팀이 일상적으로 사용하는 **통합 개발/운영 관리 플랫폼**으로 확장합니다.
AI 에이전트가 개발 파이프라인과 서버 인프라를 직접 관리하며, 외부 SaaS와 연동합니다.

---

## 2. 전체 비전

```
┌─────────────────────────────────────────────────────────────────┐
│                    WeruBWorker 통합 관리 플랫폼                    │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Dev Agent │  │ Ops Agent│  │Code Agent│  │Chat Agent│        │
│  │ 개발관리  │  │ 서버관리  │  │ 코딩     │  │ 대화      │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │             │             │             │                │
│  ┌────▼─────────────▼─────────────▼─────────────▼────┐          │
│  │              통합 도구 레이어                        │          │
│  ├──────────────────────────────────────────────────────┤          │
│  │ SSH  │ Git  │ CI/CD │ Docker │ K8s │ 모니터링 │ DB  │          │
│  └──────┴──────┴───────┴────────┴─────┴──────────┴────┘          │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────┐          │
│  │              외부 SaaS 연동                          │          │
│  ├──────┬──────┬──────┬──────┬──────┬──────┬──────────┤          │
│  │GitHub│GitLab│Jira  │Slack │AWS   │GCP   │CF/Wasabi │          │
│  └──────┴──────┴──────┴──────┴──────┴──────┴──────────┘          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 개발관리 (Dev Agent) 기능

### 3.1 Dev 에이전트

```python
# coworker/agents/dev.py
DEV_CAPABILITIES = [
    "code_files", "git", "search", "shell", "todo",
    "ci_cd",            # CI/CD 파이프라인 관리
    "code_review",      # 코드 리뷰 자동화
    "project_mgmt",     # 프로젝트 관리 (Jira/Linear)
]
```

### 3.2 CI/CD 파이프라인 관리

| 도구 | 기능 | 연동 서비스 |
|------|------|-----------|
| `ci_status` | 파이프라인 상태 조회 | GitHub Actions, GitLab CI |
| `ci_trigger` | 빌드/배포 트리거 | GitHub Actions, GitLab CI |
| `ci_logs` | 빌드 로그 조회 | GitHub Actions, GitLab CI |
| `ci_artifacts` | 빌드 산출물 다운로드 | GitHub Actions |
| `deploy_status` | 배포 상태 확인 | Vercel, Netlify, AWS |
| `deploy_rollback` | 이전 버전 롤백 | Vercel, AWS |

```python
# coworker/tools/ci_cd.py

def ci_status(repo: str = "", branch: str = "main") -> dict:
    """CI/CD 파이프라인 최신 상태 조회
    - GitHub Actions: workflow runs
    - GitLab CI: pipelines
    """

def ci_trigger(repo: str, workflow: str = "", branch: str = "main") -> dict:
    """빌드/배포 파이프라인 수동 실행 (승인 필요)"""

def ci_logs(repo: str, run_id: str = "") -> dict:
    """빌드 로그 조회 (최신 또는 특정 run)"""

def deploy_status(service: str = "") -> dict:
    """배포 서비스 상태 (Vercel, AWS ECS, K8s 등)"""

def deploy_rollback(service: str, version: str = "") -> dict:
    """이전 버전으로 롤백 (승인 필요)"""
```

### 3.3 코드 리뷰 자동화

| 도구 | 기능 |
|------|------|
| `review_pr` | PR 코드 변경 분석 및 리뷰 코멘트 생성 |
| `review_security` | 보안 취약점 스캔 (OWASP Top 10) |
| `review_performance` | 성능 영향 분석 |
| `review_test_coverage` | 테스트 커버리지 확인 |

```python
# coworker/tools/code_review.py

def review_pr(repo: str, pr_number: int) -> dict:
    """PR 코드 변경사항 분석 및 리뷰
    - 변경 파일 목록 및 diff 조회
    - 코드 품질, 보안, 성능 관점에서 분석
    - 리뷰 코멘트 생성 (GitHub/GitLab API)
    """

def review_security(path: str = ".") -> dict:
    """보안 취약점 스캔
    - 하드코딩된 시크릿 탐지
    - SQL injection, XSS 패턴 검사
    - 의존성 취약점 확인 (npm audit, pip audit)
    """

def review_test_coverage(path: str = ".") -> dict:
    """테스트 커버리지 분석
    - 커버리지 리포트 생성/파싱
    - 미테스트 영역 식별
    """
```

### 3.4 프로젝트 관리 연동

| 도구 | 기능 | 연동 |
|------|------|------|
| `list_tasks` | 할당된 작업 목록 | Jira, Linear, GitHub Issues |
| `update_task` | 작업 상태 변경 | Jira, Linear |
| `create_task` | 새 작업 생성 | Jira, Linear |
| `sprint_status` | 스프린트 현황 | Jira |
| `standup_report` | 일일 스탠드업 보고서 | Jira + GitHub |

---

## 4. 서버관리 (Ops Agent) 기능 강화

### 4.1 기존 Ops 도구 (구현 완료)

- `server_status` — CPU, 메모리, 디스크, 업타임
- `service_status` — systemd/launchctl 서비스 상태
- `check_ports` — 포트 접근성
- `process_list` — 프로세스 목록
- `disk_usage` — 디스크 사용량
- `system_logs` — 시스템/서비스 로그

### 4.2 SSH 도구 (구현 완료)

- `ssh_execute` — 원격 명령 실행
- `ssh_server_status` — 원격 서버 상태
- `ssh_service_status` — 원격 서비스 상태
- `ssh_read_file` / `ssh_tail_log` — 원격 파일/로그

### 4.3 신규: Docker/컨테이너 관리

```python
# coworker/tools/docker_mgmt.py

def docker_ps(server: str = "local", filter: str = "") -> dict:
    """실행 중인 컨테이너 목록"""

def docker_logs(container: str, lines: int = 50, server: str = "local") -> dict:
    """컨테이너 로그 조회"""

def docker_restart(container: str, server: str = "local") -> dict:
    """컨테이너 재시작 (승인 필요)"""

def docker_compose_status(path: str = ".", server: str = "local") -> dict:
    """docker-compose 서비스 상태"""

def docker_compose_up(path: str = ".", service: str = "", server: str = "local") -> dict:
    """docker-compose 서비스 시작 (승인 필요)"""

def docker_stats(server: str = "local") -> dict:
    """컨테이너별 리소스 사용량 (CPU, MEM, NET)"""

def docker_images(server: str = "local") -> dict:
    """이미지 목록 및 사이즈"""
```

### 4.4 신규: 데이터베이스 관리

```python
# coworker/tools/db_mgmt.py

def db_query(query: str, database: str = "default", readonly: bool = True) -> dict:
    """데이터베이스 쿼리 실행
    - readonly=True: SELECT만 허용
    - readonly=False: 승인 필요
    """

def db_status(database: str = "default") -> dict:
    """데이터베이스 상태 (연결 수, 크기, 슬로우 쿼리)"""

def db_tables(database: str = "default") -> dict:
    """테이블 목록 및 레코드 수"""

def db_backup(database: str = "default") -> dict:
    """데이터베이스 백업 실행 (승인 필요)"""
```

**지원 DB**: PostgreSQL, MySQL, SQLite (연결 정보는 secrets.json에 저장)

### 4.5 신규: Kubernetes 관리

```python
# coworker/tools/k8s_mgmt.py

def k8s_pods(namespace: str = "default") -> dict:
    """Pod 목록 및 상태"""

def k8s_logs(pod: str, namespace: str = "default", lines: int = 50) -> dict:
    """Pod 로그"""

def k8s_describe(resource: str, name: str, namespace: str = "default") -> dict:
    """리소스 상세 정보"""

def k8s_restart(deployment: str, namespace: str = "default") -> dict:
    """Deployment 롤링 재시작 (승인 필요)"""

def k8s_scale(deployment: str, replicas: int, namespace: str = "default") -> dict:
    """Deployment 스케일링 (승인 필요)"""

def k8s_events(namespace: str = "default") -> dict:
    """최근 이벤트 (Warning 중심)"""
```

### 4.6 신규: 클라우드 인프라 관리

```python
# coworker/tools/cloud_infra.py

# AWS
def aws_ec2_list(region: str = "") -> dict:
    """EC2 인스턴스 목록"""

def aws_s3_list(bucket: str = "") -> dict:
    """S3 버킷/객체 목록"""

def aws_cloudwatch_metrics(service: str, metric: str, period: str = "1h") -> dict:
    """CloudWatch 메트릭 조회"""

def aws_cost_explorer(period: str = "7d") -> dict:
    """비용 분석"""

# Cloudflare
def cf_dns_list(zone: str = "") -> dict:
    """DNS 레코드 목록"""

def cf_dns_update(zone: str, record: str, value: str) -> dict:
    """DNS 레코드 변경 (승인 필요)"""

def cf_analytics(zone: str = "", period: str = "24h") -> dict:
    """트래픽 분석"""

def cf_cache_purge(zone: str, urls: list = None) -> dict:
    """캐시 퍼지 (승인 필요)"""

# Wasabi (S3 호환)
def wasabi_list(bucket: str = "") -> dict:
    """Wasabi 버킷/객체 목록"""

def wasabi_upload(local_path: str, bucket: str, key: str) -> dict:
    """파일 업로드 (승인 필요)"""

def wasabi_download(bucket: str, key: str, local_path: str) -> dict:
    """파일 다운로드"""
```

---

## 5. 외부 SaaS 토큰/설정 관리

### 5.1 통합 설정 페이지

```
┌─ 서비스 설정 ──────────────────────────────────────┐
│                                                     │
│  [개발 도구]  [인프라]  [클라우드]  [스토리지]        │
│                                                     │
│  ── 개발 도구 ──                                    │
│  GitHub     PAT: ghp_****     ✓ 연결됨    [편집]    │
│  GitLab     Token: glpat-**** ✓ 연결됨    [편집]    │
│  Jira       Token: ****       ○ 미연결    [설정]    │
│  Linear     Key: lin_****     ✓ 연결됨    [편집]    │
│                                                     │
│  ── 인프라 ──                                       │
│  AWS        Key: AKIA****     ✓ 연결됨    [편집]    │
│  Cloudflare Token: ****       ✓ 연결됨    [편집]    │
│  DigitalOcean Token: ****     ○ 미연결    [설정]    │
│                                                     │
│  ── 클라우드/스토리지 ──                             │
│  Wasabi     Key: ****         ✓ 연결됨    [편집]    │
│  Backblaze  Key: ****         ○ 미연결    [설정]    │
│                                                     │
│  ── SSH 서버 ──                                     │
│  web-01     192.168.1.10      ✓ 연결됨    [편집]    │
│  db-01      192.168.1.20      ✓ 연결됨    [편집]    │
│                                                     │
│  ── 데이터베이스 ──                                  │
│  production PostgreSQL        ✓ 연결됨    [편집]    │
│  staging    MySQL             ○ 미연결    [설정]    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 5.2 secrets.json 구조 확장

```json
{
  "provider:openai": { "api_key": "...", "base_url": "..." },
  
  "github:default": { "token": "ghp_...", "type": "pat" },
  "gitlab:default": { "url": "https://gitlab.com", "token": "glpat-..." },
  "jira:default": { "url": "https://xxx.atlassian.net", "email": "...", "token": "..." },
  
  "aws:default": { "access_key_id": "AKIA...", "secret_access_key": "...", "region": "ap-northeast-2" },
  "cloudflare:default": { "api_token": "...", "zone_id": "..." },
  "wasabi:default": { "access_key": "...", "secret_key": "...", "endpoint": "https://s3.ap-northeast-1.wasabisys.com" },
  
  "ssh:server:web-01": { "host": "...", "username": "...", "key_path": "..." },
  
  "database:production": { "type": "postgresql", "host": "...", "port": 5432, "name": "...", "user": "...", "password": "..." },
  "database:staging": { "type": "mysql", "host": "...", "port": 3306, "name": "...", "user": "...", "password": "..." }
}
```

---

## 6. 자동화 시나리오

### 6.1 개발 자동화

```yaml
# 매일 아침 개발 현황 보고
name: "일일 개발 현황"
schedule: "0 9 * * 1-5"
agent: dev
instructions: |
  1. GitHub에서 어제 병합된 PR 목록 조회
  2. Jira에서 진행 중인 스프린트 상태 확인
  3. CI/CD 빌드 성공/실패 현황 집계
  4. Slack #dev-daily에 요약 보고서 전송

# PR 자동 리뷰
name: "PR 자동 리뷰"
trigger: "github:pull_request:opened"
agent: dev
instructions: |
  새 PR이 열리면:
  1. 코드 변경사항 분석
  2. 보안 취약점 스캔
  3. 테스트 커버리지 확인
  4. 리뷰 코멘트를 GitHub PR에 작성
```

### 6.2 서버 운영 자동화

```yaml
# 서버 헬스체크 (5분마다)
name: "서버 헬스체크"
schedule: "*/5 * * * *"
agent: ops
instructions: |
  등록된 모든 SSH 서버의 상태를 확인하고:
  - CPU > 90% 또는 메모리 > 85% 시 Slack #ops-alerts 알림
  - 디스크 > 90% 시 긴급 알림
  - 다운된 서비스가 있으면 자동 재시작 시도 (승인 불필요)

# 일일 백업 (매일 새벽 3시)
name: "일일 DB 백업"
schedule: "0 3 * * *"
agent: ops
instructions: |
  1. production DB 백업 생성
  2. Wasabi S3에 업로드 (30일 보관)
  3. 30일 이전 백업 자동 삭제
  4. 결과를 Slack #ops-backup에 보고

# SSL 인증서 만료 점검 (매일)
name: "SSL 만료 점검"
schedule: "0 10 * * *"
agent: ops
instructions: |
  등록된 도메인의 SSL 인증서를 확인하고:
  - 30일 이내 만료 시 Slack #ops-alerts 알림
  - 7일 이내 만료 시 긴급 알림
```

---

## 7. Catalog 등록 계획

```python
# catalog.py에 추가할 Capability

# 개발관리 도구
Capability(id="ci_cd", name="CI/CD Pipeline", ...)
Capability(id="code_review", name="Code Review", ...)
Capability(id="project_mgmt", name="Project Management", ...)

# 서버관리 도구 (기존 + 신규)
Capability(id="server_monitor", ...)  # ✅ 구현 완료
Capability(id="ssh", ...)             # ✅ 구현 완료
Capability(id="docker", name="Docker Management", ...)
Capability(id="k8s", name="Kubernetes Management", ...)
Capability(id="cloud_infra", name="Cloud Infrastructure", ...)
Capability(id="database", name="Database Management", ...)
```

---

## 8. GUI 확장

### 8.1 신규 페이지

| 페이지 | 설명 |
|--------|------|
| **DevView** | 개발 현황 대시보드 (CI/CD, PR, 이슈) |
| **OpsView** | 서버 모니터링 대시보드 |
| **ServiceConfigView** | 서비스 설정/토큰 관리 |
| **DatabaseView** | DB 관리 (쿼리, 상태, 백업) |

### 8.2 Sidebar 네비게이션 확장

```
┌──────────────┐
│ + 새 세션     │
│              │
│ 🔍 검색      │
│ ⏰ 자동화    │
│              │
│ ── 관리 ──   │
│ 🖥 서버      │  ← OpsView
│ 🔧 개발      │  ← DevView
│ 🗄 데이터베이스│  ← DatabaseView
│ ⚙ 서비스 설정 │  ← ServiceConfigView
│              │
│ ── 기존 ──   │
│ 🔌 커넥터    │
│ 📋 활동      │
│ 📥 인박스    │
│ ⚙ 설정      │
│ ℹ 정보      │
└──────────────┘
```

---

## 9. 구현 로드맵

### Phase 1: 기반 (완료)
- ✅ Ops 에이전트 (6개 도구)
- ✅ SSH 커넥터 (7개 도구, 4개 API)

### Phase 2: Docker/DB (1주)
| # | 작업 | 예상 |
|---|------|------|
| 1 | `docker_mgmt.py` 7개 도구 | 1일 |
| 2 | `db_mgmt.py` 4개 도구 | 1일 |
| 3 | DB 연결 설정 UI (secrets 관리) | 1일 |
| 4 | catalog.py 등록 + Ops 에이전트 연동 | 0.5일 |
| 5 | 테스트 | 0.5일 |

### Phase 3: 클라우드 인프라 (1주)
| # | 작업 | 예상 |
|---|------|------|
| 6 | `cloud_infra.py` — AWS (EC2, S3, CloudWatch, Cost) | 1일 |
| 7 | `cloud_infra.py` — Cloudflare (DNS, Analytics, Cache) | 1일 |
| 8 | `cloud_infra.py` — Wasabi (S3 호환 스토리지) | 0.5일 |
| 9 | 서비스 설정 UI (ServiceConfigView) | 1일 |
| 10 | catalog.py 등록 | 0.5일 |

### Phase 4: 개발관리 (1주)
| # | 작업 | 예상 |
|---|------|------|
| 11 | `ci_cd.py` — GitHub Actions 연동 | 1일 |
| 12 | `code_review.py` — PR 리뷰 도구 | 1일 |
| 13 | `project_mgmt.py` — Jira/Linear 연동 | 1일 |
| 14 | Dev 에이전트 정의 | 0.5일 |
| 15 | DevView UI | 0.5일 |

### Phase 5: Kubernetes + 모니터링 (1주)
| # | 작업 | 예상 |
|---|------|------|
| 16 | `k8s_mgmt.py` — kubectl 래퍼 | 1일 |
| 17 | OpsView UI (서버 대시보드) | 1.5일 |
| 18 | DatabaseView UI | 1일 |
| 19 | 자동화 템플릿 (헬스체크, 백업, SSL) | 0.5일 |

---

## 10. 필요 패키지

### Python (선택적, 미설치 시 subprocess 폴백)

| 패키지 | 용도 | 필수 |
|--------|------|------|
| `psutil` | 시스템 모니터링 | 선택 |
| `boto3` | AWS SDK | AWS 사용 시 |
| `psycopg2-binary` | PostgreSQL | DB 사용 시 |
| `pymysql` | MySQL | DB 사용 시 |
| `kubernetes` | K8s Python 클라이언트 | K8s 사용 시 |

### 외부 CLI (시스템에 설치)

| CLI | 용도 |
|-----|------|
| `docker` | 컨테이너 관리 |
| `kubectl` | Kubernetes 관리 |
| `aws` | AWS CLI |
| `gh` | GitHub CLI |

---

## 11. 보안 체계

### 권한 계층 (도구별)

| 레벨 | 도구 | 승인 |
|------|------|------|
| **읽기** | 상태 조회, 로그, 목록 | 불필요 |
| **실행** | 명령 실행, 쿼리, 빌드 트리거 | 승인 필요 |
| **변경** | 재시작, 스케일링, DNS 변경, 배포 | 승인 필요 + 확인 |
| **삭제** | 리소스 삭제, 데이터 삭제 | 이중 확인 |

### 감사 로그

모든 인프라 작업은 `audit_store`에 기록:
```json
{
  "tool": "docker_restart",
  "target": "nginx",
  "server": "web-01",
  "user": "admin",
  "result": "ok",
  "timestamp": "2026-08-07T09:30:00Z"
}
```

---

*작성일: 2026-08-07*
*프로젝트: WeruBWorker 개발관리/서버관리 강화*
