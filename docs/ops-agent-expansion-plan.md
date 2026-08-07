# WeruBWorker 서버 관리/운영 에이전트 확장 계획서

## 1. 개요

### 배경
현재 WeruBWorker는 코딩(Code), 지식작업(Cowork), 대화(Chat) 에이전트를 제공합니다.
이를 확장하여 **서버 관리 및 운영(Ops)** 업무를 수행하는 에이전트를 추가하고,
설정/보안 정보를 관리하며 외부 웹 화면을 호출할 수 있는 기능을 구축합니다.

### 목표
1. **Ops 에이전트**: 서버 모니터링, 배포, 로그 분석, 인프라 관리 업무 수행
2. **설정/보안 대시보드**: 서버 설정, API 키, 인증 정보를 안전하게 관리하는 UI
3. **웹 화면 호출**: 외부 관리 도구(Grafana, AWS Console, 모니터링 등)를 에이전트 내에서 연동
4. **자동화 확장**: 서버 헬스체크, 알림, 자동 복구 등 운영 자동화

---

## 2. 현재 아키텍처 분석

### 2.1 에이전트 체계

```
Agent (base.py)
├── Code    — 코딩 전용, workspace 필수, git 연동
├── Cowork  — 지식작업, 파일/셸/검색/투두
├── Chat    — 대화 전용, 도구 없음
└── MyHelper — 개인 어시스턴트 (Cowork 도구 공유)
```

각 에이전트는:
- `name`, `title`, `system_prompt` — 정체성
- `tool_factory(context)` — 사용 가능한 도구 목록
- `family` — "code" 또는 "knowledge"
- `needs_workspace` — 워크스페이스 필요 여부

### 2.2 도구(Tool) 카탈로그

```
catalog.py → Capability 정의
├── code_files — 파일 읽기/쓰기 (단일 루트)
├── files      — 파일 읽기/쓰기 (다중 루트)
├── git        — git log/diff/blame
├── search     — 웹 검색 (DuckDuckGo/Tavily/Brave)
├── shell      — 셸 명령 실행 (persistent)
└── todo       — 작업 목록 관리
```

### 2.3 커넥터 체계

```
connectors/
├── Slack       — 메시지 수신/발신, 채널 관리
├── GitHub      — 이슈/PR 알림, 코드 리뷰
├── Gmail       — 이메일 읽기/발신
├── Calendar    — 일정 조회/생성
├── HubSpot     — CRM 연동
└── (확장 가능)
```

### 2.4 확장 포인트

| 계층 | 확장 방식 | 난이도 |
|------|-----------|--------|
| 에이전트 추가 | `agents/` 에 새 파일 + registry 등록 | **낮음** |
| 도구 추가 | `tools/` 에 새 파일 + `catalog.py`에 Capability 등록 | **낮음** |
| 커넥터 추가 | `connectors/` 에 어댑터 + `descriptors.py`에 등록 | **중간** |
| GUI 페이지 추가 | `surfaces/gui/src/` 에 컴포넌트 + App.tsx에 라우팅 | **중간** |
| API 엔드포인트 추가 | `server/app.py` 또는 `server/manager.py`에 추가 | **중간** |

---

## 3. Ops 에이전트 설계

### 3.1 에이전트 정의

```python
# coworker/agents/ops.py

OPS_CAPABILITIES = [
    "files",           # 설정 파일 읽기/편집
    "shell",           # 서버 명령 실행 (systemctl, docker, kubectl 등)
    "search",          # 문서/에러 검색
    "todo",            # 작업 추적
    "server_monitor",  # [신규] 서버 상태 모니터링
    "web_fetch",       # [신규] 외부 웹 API/대시보드 호출
    "secrets_manage",  # [신규] 설정/보안 정보 관리
]

OPS_INSTRUCTIONS = """
You are an Ops agent — a skilled DevOps/SRE engineer managing servers and infrastructure.

Core responsibilities:
- Server monitoring: check health, resource usage, service status
- Deployment: manage deployments, rollbacks, version control
- Log analysis: search and analyze application/system logs
- Configuration: manage server configs, environment variables, secrets
- Troubleshooting: diagnose issues, suggest fixes, execute remediation
- Security: audit access, check certificates, review firewall rules

Safety rules:
- ALWAYS explain what a command will do before running destructive operations
- For production systems, require explicit confirmation for: restart, deploy, scale, delete
- Never expose secrets in plain text — use masked display (*****)
- Log all operations for audit trail
- Prefer read-only operations first, then suggest changes
"""
```

### 3.2 신규 도구 (Tools)

#### 3.2.1 서버 모니터링 도구 (`tools/server_monitor.py`)

```python
# 제공 함수:
def server_status(host: str) -> dict:
    """서버 기본 상태 (CPU, 메모리, 디스크, 네트워크)"""

def service_status(service: str) -> dict:
    """시스템 서비스 상태 확인 (systemctl/docker)"""

def check_ports(host: str, ports: list[int]) -> dict:
    """포트 접근성 검사"""

def check_ssl_cert(domain: str) -> dict:
    """SSL 인증서 만료일 확인"""

def docker_status() -> dict:
    """Docker 컨테이너 상태 목록"""

def process_list(filter: str = "") -> dict:
    """프로세스 목록 (필터링 가능)"""

def disk_usage(path: str = "/") -> dict:
    """디스크 사용량 상세"""

def network_connections(port: int = None) -> dict:
    """네트워크 연결 상태"""

def system_logs(service: str, lines: int = 50) -> str:
    """시스템 로그 조회 (journalctl/docker logs)"""

def resource_history(metric: str, period: str = "1h") -> dict:
    """리소스 사용 이력 (간이 모니터링)"""
```

#### 3.2.2 웹 호출 도구 (`tools/web_dashboard.py`)

```python
def web_fetch_api(url: str, method: str = "GET", headers: dict = None, body: str = None) -> dict:
    """외부 API 호출 (REST)"""

def web_screenshot(url: str) -> str:
    """웹 페이지 스크린샷 캡처 (Playwright 활용)"""

def grafana_query(dashboard_id: str, panel_id: str, time_range: str = "1h") -> dict:
    """Grafana 대시보드 데이터 조회"""

def cloud_status(provider: str, service: str) -> dict:
    """클라우드 서비스 상태 (AWS/GCP/Azure)"""
```

#### 3.2.3 설정/보안 관리 도구 (`tools/secrets_manage.py`)

```python
def list_configs(scope: str = "global") -> dict:
    """설정 항목 목록 (값은 마스킹)"""

def get_config(key: str, unmask: bool = False) -> dict:
    """설정값 조회 (기본 마스킹)"""

def set_config(key: str, value: str, scope: str = "global") -> dict:
    """설정값 변경 (감사 로깅 포함)"""

def rotate_secret(key: str) -> dict:
    """시크릿 로테이션"""

def audit_log(limit: int = 50) -> list:
    """설정 변경 감사 로그 조회"""

def check_expiring_secrets(days: int = 30) -> list:
    """만료 임박 시크릿/인증서 목록"""
```

### 3.3 카탈로그 등록

```python
# catalog.py에 추가

Capability(
    id="server_monitor",
    name="Server monitoring",
    description="Check server health, resource usage, service status, and logs",
    build=lambda ctx: server_monitor_tools(ctx),
    requires=("executor",),
    risk=(RiskClass.READ,),
),
Capability(
    id="web_fetch",
    name="Web dashboard access",
    description="Fetch data from external APIs and dashboards",
    build=lambda ctx: web_dashboard_tools(ctx),
    requires=(),
    risk=(RiskClass.NETWORK,),
),
Capability(
    id="secrets_manage",
    name="Configuration & secrets management",
    description="View and manage server configuration and secrets",
    build=lambda ctx: secrets_manage_tools(ctx),
    requires=(),
    risk=(RiskClass.WRITE, RiskClass.SENSITIVE),
),
```

---

## 4. 설정/보안 대시보드 UI

### 4.1 신규 GUI 페이지: OpsView

```
surfaces/gui/src/components/
├── OpsView.tsx          # Ops 메인 페이지
├── OpsServerPanel.tsx   # 서버 상태 패널
├── OpsConfigPanel.tsx   # 설정/보안 관리 패널
├── OpsLogViewer.tsx     # 로그 뷰어
└── OpsWebEmbed.tsx      # 외부 웹 화면 임베드
```

### 4.2 페이지 구조

```
┌─────────────────────────────────────────────────┐
│  WeruBWorker  [Ops]                              │
├──────────┬──────────────────────────────────────┤
│          │  ┌─ 서버 상태 ────────────────────┐  │
│ 서버 목록 │  │ CPU: ████████░░ 78%           │  │
│          │  │ MEM: ██████░░░░ 62%           │  │
│ ● web-01 │  │ DISK: █████░░░░░ 48%          │  │
│ ● web-02 │  │ Uptime: 45d 3h               │  │
│ ○ db-01  │  └──────────────────────────────┘  │
│ ● worker │                                     │
│          │  ┌─ 서비스 ──────────────────────┐  │
│ ─────── │  │ nginx    ● running  (PID 1234)│  │
│ 설정     │  │ postgres ● running  (PID 5678)│  │
│ 보안     │  │ redis    ● running  (PID 9012)│  │
│ 로그     │  │ worker   ○ stopped            │  │
│ 대시보드  │  └──────────────────────────────┘  │
│          │                                     │
│          │  ┌─ 최근 알림 ───────────────────┐  │
│          │  │ ⚠ db-01 CPU > 90% (5분 전)    │  │
│          │  │ ✓ SSL 갱신 완료 (1시간 전)     │  │
│          │  └──────────────────────────────┘  │
└──────────┴──────────────────────────────────────┘
```

### 4.3 설정/보안 관리 화면

```
┌─ 설정 관리 ─────────────────────────────────────┐
│                                                  │
│  [환경변수]  [API 키]  [인증서]  [감사 로그]      │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │ KEY                 VALUE        SCOPE      │ │
│  │─────────────────────────────────────────────│ │
│  │ OPENAI_API_KEY      sk-proj-**** global  ✏ │ │
│  │ OLLAMA_BASE_URL     https://w*** global  ✏ │ │
│  │ DATABASE_URL        postgres:*** project ✏ │ │
│  │ SLACK_BOT_TOKEN     xoxb-****   global  ✏ │ │
│  │ AWS_ACCESS_KEY_ID   AKIA****    global  ✏ │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  [+ 추가]  [내보내기 (마스킹)]  [만료 점검]       │
│                                                  │
│  ⚠ 2개 시크릿이 30일 내 만료 예정                 │
│                                                  │
└──────────────────────────────────────────────────┘
```

### 4.4 감사 로그

```
┌─ 감사 로그 ─────────────────────────────────────┐
│                                                  │
│  2026-08-06 10:30  OPENAI_API_KEY 변경  (user)   │
│  2026-08-06 09:15  SSL 인증서 갱신     (auto)    │
│  2026-08-05 23:00  서버 재시작 (web-01) (ops)    │
│  2026-08-05 18:45  DATABASE_URL 변경   (user)    │
│                                                  │
└──────────────────────────────────────────────────┘
```

---

## 5. 외부 웹 화면 호출 기능

### 5.1 개념

Ops 에이전트가 외부 관리 도구(Grafana, AWS Console, 모니터링 대시보드 등)를
WeruBWorker 내에서 직접 열어볼 수 있는 기능.

### 5.2 구현 방식

#### 방식 A: iframe 임베드 (권장)

```tsx
// OpsWebEmbed.tsx
function OpsWebEmbed({ url, title }: { url: string; title: string }) {
  return (
    <div className="ops-embed">
      <div className="ops-embed-header">
        <span>{title}</span>
        <a href={url} target="_blank">외부에서 열기 ↗</a>
      </div>
      <iframe
        src={url}
        sandbox="allow-scripts allow-same-origin"
        className="ops-embed-frame"
      />
    </div>
  );
}
```

- 장점: 사용자 인증 세션 유지, 실시간 데이터
- 제약: X-Frame-Options 차단하는 사이트 불가 (AWS Console 등)

#### 방식 B: API 프록시 + 자체 렌더링

```
[Ops Agent] → web_fetch_api() → [서버 프록시] → [외부 API]
                                      ↓
                               JSON 데이터 반환
                                      ↓
                              [GUI에서 차트 렌더링]
```

- 장점: 모든 API 접근 가능, 통합 UI
- 구현: 서버에 프록시 엔드포인트 추가

#### 방식 C: 스크린샷 캡처

```python
# Playwright로 외부 페이지 캡처
async def capture_dashboard(url: str) -> str:
    """외부 대시보드 스크린샷 → 이미지 파일 경로 반환"""
```

- 장점: 어떤 사이트든 가능
- 제약: 정적 이미지, 인터랙션 불가

### 5.3 등록 가능한 외부 도구

서버 설정에 외부 대시보드 URL을 등록하는 구조:

```toml
# config.toml
[ops.dashboards]
grafana = { url = "https://grafana.internal/d/main", title = "Grafana 모니터링" }
portainer = { url = "https://portainer.local:9443", title = "Docker 관리" }
aws_console = { url = "https://console.aws.amazon.com", title = "AWS Console", mode = "external" }
kibana = { url = "https://kibana.internal:5601", title = "로그 분석" }

[ops.servers]
web-01 = { host = "192.168.1.10", ssh_user = "deploy", tags = ["web", "production"] }
web-02 = { host = "192.168.1.11", ssh_user = "deploy", tags = ["web", "production"] }
db-01 = { host = "192.168.1.20", ssh_user = "admin", tags = ["database", "production"] }
```

### 5.4 대시보드 탭 UI

```
┌─ 대시보드 ──────────────────────────────────────┐
│                                                  │
│  [Grafana]  [Portainer]  [Kibana]  [+ 추가]      │
│                                                  │
│  ┌──────────────────────────────────────────────┐│
│  │                                              ││
│  │         (iframe: Grafana 대시보드)            ││
│  │                                              ││
│  │                                              ││
│  │                                              ││
│  └──────────────────────────────────────────────┘│
│                                                  │
│  에이전트에게: "CPU 사용량이 80% 넘은 시간대 분석해줘" │
│                                                  │
└──────────────────────────────────────────────────┘
```

---

## 6. 보안 설계

### 6.1 권한 모델

```
┌─ 권한 계층 ────────────────────────────────────┐
│                                                 │
│  Level 0: 읽기 전용                              │
│    서버 상태 조회, 로그 보기, 설정 목록 (마스킹)   │
│                                                 │
│  Level 1: 제한적 실행 (승인 필요)                 │
│    서비스 재시작, 설정 변경, 로그 삭제             │
│                                                 │
│  Level 2: 전체 접근 (명시적 확인)                 │
│    배포, 스케일링, 시크릿 로테이션, 서버 재부팅    │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 6.2 시크릿 보호

| 항목 | 방식 |
|------|------|
| 저장 | `secrets.json` 암호화 (AES-256, 마스터키는 OS keychain) |
| 표시 | 기본 마스킹 (`sk-proj-****`), 명시적 unmask 요청 시만 노출 |
| 전송 | HTTPS only, 로컬 API는 sidecar 토큰 인증 |
| 감사 | 모든 시크릿 접근/변경을 감사 로그에 기록 |
| 로테이션 | 만료 임박 알림 + 자동 로테이션 지원 (지원하는 서비스) |

### 6.3 SSH 접근 보안

```python
# SSH 연결은 사용자의 기존 SSH 키/에이전트를 활용
# 비밀번호 인증은 지원하지 않음
# 모든 SSH 명령은 승인 프롬프트를 거침 (Level 1+)

class SSHExecutor:
    """원격 서버 명령 실행"""
    def __init__(self, host: str, user: str):
        # 기존 SSH 설정(~/.ssh/config) 활용
        pass
    
    async def run(self, command: str, *, approval_required: bool = True) -> str:
        """명령 실행 (승인 필요)"""
        pass
```

---

## 7. 자동화 확장

### 7.1 Ops 자동화 예시

기존 Automation 시스템(`automation.db`, `ScheduledView`)을 활용:

```yaml
# 헬스체크 자동화 (매 5분)
name: "서버 헬스체크"
schedule: "*/5 * * * *"
agent: ops
instructions: |
  모든 등록된 서버의 상태를 확인하고,
  CPU > 90% 또는 디스크 > 85%이면 Slack #ops-alerts에 알림 전송.

# SSL 만료 점검 (매일)
name: "SSL 인증서 만료 점검"
schedule: "0 9 * * *"
agent: ops
instructions: |
  모든 도메인의 SSL 인증서 만료일을 확인하고,
  30일 이내 만료 예정인 것이 있으면 보고.

# 일일 운영 보고서 (매일 오전 9시)
name: "일일 운영 보고서"
schedule: "0 9 * * *"
agent: ops
instructions: |
  지난 24시간 서버 상태 요약:
  - 평균/최대 리소스 사용량
  - 에러 로그 카운트
  - 배포 이력
  결과를 Slack #daily-ops에 전송.
```

### 7.2 알림 연동

```
[Ops Agent] → 이상 감지 → [Slack #ops-alerts]
                        → [이메일 알림]
                        → [Inbox (WeruBWorker 내)]
```

기존 커넥터(Slack, Gmail)를 활용하여 알림 발송.

---

## 8. 구현 로드맵

### Phase 1: Ops 에이전트 기반 (1주)

| # | 작업 | 산출물 |
|---|------|--------|
| 1 | `agents/ops.py` 생성 | Ops 에이전트 정의 |
| 2 | `tools/server_monitor.py` 생성 | 서버 모니터링 도구 (로컬) |
| 3 | `catalog.py`에 `server_monitor` Capability 등록 | — |
| 4 | 페르소나 레지스트리에 Ops 등록 | Sidebar에 표시 |
| 5 | 기본 동작 테스트 (로컬 서버 상태 조회) | — |

### Phase 2: 설정/보안 관리 (1주)

| # | 작업 | 산출물 |
|---|------|--------|
| 6 | `tools/secrets_manage.py` 생성 | 설정/보안 도구 |
| 7 | 감사 로그 DB 스키마 추가 | `ops_audit.db` |
| 8 | 시크릿 마스킹/unmask 로직 | — |
| 9 | `server/app.py`에 Ops API 엔드포인트 추가 | REST API |
| 10 | 설정 관리 GUI (`OpsConfigPanel.tsx`) | — |

### Phase 3: 웹 대시보드 연동 (1주)

| # | 작업 | 산출물 |
|---|------|--------|
| 11 | `tools/web_dashboard.py` 생성 | 웹 호출 도구 |
| 12 | config.toml에 대시보드 등록 구조 추가 | — |
| 13 | `OpsWebEmbed.tsx` iframe 임베드 컴포넌트 | — |
| 14 | API 프록시 엔드포인트 (CORS 우회) | — |
| 15 | 대시보드 관리 UI | — |

### Phase 4: 서버 모니터링 UI (1주)

| # | 작업 | 산출물 |
|---|------|--------|
| 16 | `OpsView.tsx` 메인 페이지 | — |
| 17 | `OpsServerPanel.tsx` 서버 상태 패널 | — |
| 18 | `OpsLogViewer.tsx` 로그 뷰어 | — |
| 19 | App.tsx에 Ops 페이지 라우팅 추가 | — |
| 20 | Sidebar에 Ops 네비게이션 추가 | — |

### Phase 5: 자동화 및 알림 (1주)

| # | 작업 | 산출물 |
|---|------|--------|
| 21 | Ops 자동화 템플릿 (헬스체크, SSL, 보고서) | — |
| 22 | 알림 연동 (Slack, Inbox) | — |
| 23 | 원격 서버 SSH 연결 (`SSHExecutor`) | — |
| 24 | 전체 통합 테스트 | — |
| 25 | 문서화 | — |

---

## 9. 파일 구조 (최종)

```
coworker/
├── agents/
│   ├── ops.py                    # [신규] Ops 에이전트
│   └── ...
├── tools/
│   ├── server_monitor.py         # [신규] 서버 모니터링
│   ├── web_dashboard.py          # [신규] 웹 대시보드 호출
│   ├── secrets_manage.py         # [신규] 설정/보안 관리
│   ├── ssh_executor.py           # [신규] SSH 원격 실행
│   └── ...
├── catalog.py                    # [수정] 신규 Capability 등록
├── config.py                     # [수정] ops 설정 추가
├── server/
│   ├── app.py                    # [수정] Ops API 엔드포인트
│   └── manager.py                # [수정] Ops 세션 관리
└── ...

surfaces/gui/src/
├── components/
│   ├── OpsView.tsx               # [신규] Ops 메인 페이지
│   ├── OpsServerPanel.tsx        # [신규] 서버 상태 패널
│   ├── OpsConfigPanel.tsx        # [신규] 설정/보안 관리
│   ├── OpsLogViewer.tsx          # [신규] 로그 뷰어
│   ├── OpsWebEmbed.tsx           # [신규] 웹 임베드
│   └── ...
├── App.tsx                       # [수정] Ops 페이지 라우팅
└── api.ts                        # [수정] Ops API 함수
```

---

## 10. 기술 스택 추가

### Python (백엔드)

| 패키지 | 용도 | 필요 여부 |
|--------|------|-----------|
| `psutil` | 시스템 리소스 모니터링 | 필수 |
| `paramiko` | SSH 원격 접속 | Phase 5 |
| `cryptography` | 시크릿 암호화 (이미 설치됨) | 기존 |
| `playwright` | 웹 스크린샷 (이미 설치됨) | 기존 |

### GUI (프론트엔드)

| 패키지 | 용도 | 필요 여부 |
|--------|------|-----------|
| (없음) | iframe 기반이므로 추가 패키지 불필요 | — |
| `chart.js` 또는 `recharts` | 리소스 차트 (선택) | Phase 4 |

---

## 11. 리스크 및 고려사항

| 리스크 | 대응 |
|--------|------|
| SSH 키 노출 | OS SSH 에이전트만 사용, 키 직접 처리 안 함 |
| 프로덕션 실수 | 위험 명령은 반드시 승인 프롬프트 |
| 외부 사이트 iframe 차단 | API 프록시 + 자체 렌더링 폴백 |
| 시크릿 유출 | 기본 마스킹 + 감사 로그 |
| 원격 서버 접근 범위 | config.toml에 등록된 서버만 접근 허용 |

---

*작성일: 2026-08-06*
*프로젝트: WeruBWorker Ops Agent Expansion*
