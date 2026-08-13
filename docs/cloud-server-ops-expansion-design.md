# OpenWorker 클라우드 & 서버 관리/운영 모니터링 서비스 확장 설계서

> **작성일**: 2026-08-13  
> **대상 프로젝트**: WeruBWorker (OpenWorker / coworker 패키지)  
> **목적**: 현재 구조를 분석하고, 클라우드·서버 관리 및 운영 모니터링 전용 서비스로 확장하기 위한 상세 설계

---

## 1. 현재 아키텍처 분석

### 1.1 시스템 전체 구조

```
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI (server/app.py)                    │
│  WebSocket 세션 · REST API · OpenAI 호환 프록시               │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│              SessionManager (server/manager.py)               │
│  엔진 캐시 · 저장소 · 프로바이더 · 커넥터 · 자동화 · Inbox     │
└──┬──────────┬──────────┬──────────┬──────────┬───────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌──────────┐ ┌───────┐ ┌──────────┐
│Engine│ │Tools │ │Automation│ │Connec.│ │Providers │
│      │ │      │ │Scheduler │ │ tors  │ │ Router   │
└──────┘ └──────┘ └──────────┘ └───────┘ └──────────┘
```

### 1.2 현재 운영 관련 모듈 현황

| 모듈 | 파일 | 도구 수 | 현재 상태 | 한계 |
|------|------|---------|----------|------|
| **서버 모니터링** | `tools/server_monitor.py` | 8개 | 로컬 전용 | 원격 서버 시계열 미지원, 알림 없음 |
| **SSH** | `connectors/ssh/` | 7개 | 원격 명령 실행 | 세션 재사용 없음 (매번 새 연결), 터널링 미지원 |
| **Docker** | `tools/docker_mgmt.py` | 7개 | 로컬+SSH | Docker API 미사용 (CLI 파싱), Swarm 미지원 |
| **Kubernetes** | `tools/k8s_mgmt.py` | 6개 | kubectl CLI | 멀티 클러스터 미지원, CRD 미지원, 메트릭 서버 미연동 |
| **DB 관리** | `tools/db_mgmt.py` | 4개 | PG/MySQL/SQLite | 슬로우 쿼리 분석 없음, 레플리케이션 미지원 |
| **CI/CD** | `tools/ci_cd.py` | 5개 | GitHub Actions | GitLab CI/Jenkins 미지원, 배포 파이프라인 미연동 |
| **클라우드** | `tools/cloud_infra.py` | 11개 | AWS/CF/Wasabi | GCP/Azure 미지원, IAM 관리 없음, 비용 알림 없음 |
| **Ops 에이전트** | `agents/ops.py` | 11개 capability | SRE 역할 | 반응형만 (사전 예방 없음), 대시보드 없음 |

### 1.3 현재 강점

- **모듈식 카탈로그**: `catalog.py`의 `Capability` 시스템으로 도구 조합이 유연
- **권한 엔진**: 읽기/쓰기/실행 도구별 승인 정책이 잘 분리됨
- **자동화 스케줄러**: cron 기반 작업 + 자가 웨이크(selfwake)로 주기적 모니터링 가능
- **멀티 프로바이더**: 12개+ LLM 프로바이더 지원으로 비용·성능 최적화 가능
- **메시징 커넥터**: Slack/Telegram 알림 채널 이미 구축됨
- **Wiki**: 운영 런북·문서 저장소 내장
- **SecretStore/Vault**: 자격증명 암호화 관리 체계

### 1.4 현재 구조적 한계 (확장 시 해결 필요)

| 영역 | 한계 | 영향도 |
|------|------|--------|
| 시계열 데이터 | `MetricsStore`가 SQLite 단일 파일, 7일 자동 프루닝 | 장기 트렌드 분석 불가 |
| 알림 체계 | 임계값 체크(`_check_thresholds`) 존재하지만 알림 파이프라인 없음 | 장애 대응 지연 |
| 다중 서버 | SSH 도구가 1:1 명령 실행만, 병렬 수집 미지원 | 대규모 인프라 관리 불가 |
| 대시보드 | WebSocket 이벤트 스트림만 (구조화된 대시보드 API 없음) | 현황 파악 어려움 |
| 인시던트 관리 | 에이전트가 탐지→분석까지만, 티켓 생성·에스컬레이션 없음 | 운영 워크플로우 미완성 |
| 멀티 클라우드 | AWS만 실제 구현, GCP/Azure 스텁 없음 | 하이브리드 클라우드 미지원 |

---

## 2. 확장 목표

### 2.1 서비스 비전

> **WeruBWorker Ops Platform**: AI 에이전트 기반 통합 클라우드·서버 관리 및 운영 모니터링 서비스

### 2.2 핵심 확장 영역

```
┌─────────────────────────────────────────────────────────────────┐
│                     WeruBWorker Ops Platform                     │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│ 1.통합   │ 2.실시간 │ 3.알림 & │ 4.인프라 │ 5.보안 &            │
│ 모니터링 │ 대시보드 │ 인시던트 │ 자동화   │ 컴플라이언스         │
├──────────┼──────────┼──────────┼──────────┼─────────────────────┤
│·멀티서버 │·메트릭   │·임계값   │·프로비저 │·보안 스캔           │
│·시계열DB │ 시각화   │ 알림    │ 닝      │·접근 감사           │
│·APM 연동 │·로그뷰어 │·인시던트 │·IaC 연동│·인증서 관리         │
│·헬스체크 │·토폴로지 │ 타임라인│·자동 복구│·취약점 알림         │
│·로그집계 │·비용분석 │·에스컬레│·CI/CD   │·비밀번호 회전       │
│          │          │ 이션   │ 확장    │                     │
└──────────┴──────────┴──────────┴──────────┴─────────────────────┘
```

---

## 3. 상세 확장 설계

### 3.1 통합 모니터링 시스템

#### 3.1.1 멀티 서버 메트릭 수집기

현재 `server_monitor.py`의 `MetricsStore`를 확장하여 다중 서버 시계열 데이터를 수집합니다.

**새 모듈**: `coworker/monitoring/collector.py`

```python
@dataclass
class MetricPoint:
    server_id: str           # "web-01", "db-master"
    timestamp: float
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_rx_bytes: int
    network_tx_bytes: int
    load_avg_1m: float
    custom: dict[str, float]  # 서비스별 커스텀 메트릭

@dataclass  
class CollectorConfig:
    interval_seconds: int = 60        # 수집 주기
    retention_days: int = 90          # 보관 기간
    parallel_workers: int = 10        # 병렬 수집 워커
    aggregation_intervals: list = ("1m", "5m", "1h", "1d")  # 다운샘플링
```

**수집 흐름**:
```
┌──────────┐     ┌──────────────┐     ┌───────────────┐
│ SSH 서버 │────→│              │────→│               │
│ (원격)   │     │  Collector   │     │  TimeSeriesDB │
├──────────┤     │  (비동기     │     │  (SQLite +    │
│ 로컬호스트│────→│   병렬수집)  │     │   다운샘플링) │
├──────────┤     │              │     │               │
│ SNMP     │────→│              │────→│               │
│ (네트워크)│     └──────────────┘     └───────────────┘
└──────────┘             │
                         ▼
                 ┌──────────────┐
                 │ AlertEngine  │
                 │ (임계값 평가) │
                 └──────────────┘
```

**구현 방식**:
- 기존 `SSHClient.execute()`를 활용하여 원격 서버 메트릭 수집
- `asyncio.gather()`로 병렬 수집 (최대 parallel_workers 동시)
- SQLite WAL 모드 + 다운샘플링 테이블로 장기 보관
- 기존 `scheduler.py`의 tick 루프에 수집기 연동

#### 3.1.2 서비스 헬스체크 확장

현재 `HealthChecker` 클래스를 상시 운영 모드로 확장합니다.

**새 파일**: `coworker/monitoring/healthcheck.py`

```python
@dataclass
class HealthCheckRule:
    id: str
    name: str
    type: str              # "http", "tcp", "dns", "ping", "ssl_cert", "docker", "k8s_pod"
    target: str            # URL, host:port, 도메인
    interval_seconds: int  # 체크 주기
    timeout_seconds: int
    retries: int           # 실패 전 재시도 횟수
    alert_channels: list[str]  # ["slack:C01234", "telegram:456"]
    escalation_after: int  # N회 연속 실패 시 에스컬레이션
    metadata: dict         # 커스텀 메타 (예: expected_status_code)

class HealthCheckManager:
    """상시 헬스체크 매니저 - 스케줄러 tick에 통합"""
    
    async def add_check(rule: HealthCheckRule) -> str
    async def remove_check(check_id: str) -> bool
    async def run_checks() -> list[CheckResult]
    async def get_history(check_id: str, hours: int = 24) -> list[CheckResult]
    def uptime_percentage(check_id: str, days: int = 30) -> float
```

**추가 체크 유형**:

| 유형 | 설명 | 현재 | 확장 |
|------|------|------|------|
| HTTP/HTTPS | 응답 코드 + 응답 시간 | O | 본문 패턴 매칭, SSL 인증서 만료 |
| TCP | 포트 접근성 | O | 배너 체크 |
| DNS | 레코드 해석 | O | 전파 시간 |
| Ping | ICMP 도달성 | O | 패킷 손실률 |
| SSL 인증서 | 만료일 체크 | X | **신규** — 30/14/7일 전 알림 |
| Docker | 컨테이너 상태 | X | **신규** — 재시작 루프 탐지 |
| K8s Pod | Pod readiness | X | **신규** — CrashLoopBackOff 탐지 |
| 프로세스 | 특정 프로세스 존재 여부 | X | **신규** — 좀비/OOM 탐지 |
| 디스크 I/O | iowait 임계값 | X | **신규** |

#### 3.1.3 로그 집계 시스템

**새 모듈**: `coworker/monitoring/log_aggregator.py`

```python
@dataclass
class LogSource:
    server_id: str
    type: str           # "file", "journalctl", "docker", "k8s"
    path: str           # 로그 경로 또는 서비스명
    patterns: list[str] # 관심 패턴 (정규식)
    severity_filter: str  # "error", "warning", "all"

class LogAggregator:
    """다중 서버 로그 수집 및 패턴 분석"""
    
    async def add_source(source: LogSource) -> None
    async def tail(server_id: str, source: str, lines: int) -> list[LogEntry]
    async def search(pattern: str, servers: list[str], hours: int) -> list[LogEntry]
    async def anomaly_detect(server_id: str, baseline_hours: int) -> list[Anomaly]
```

**로그 처리 파이프라인**:
```
서버 로그 → SSH tail -f → 패턴 매칭 → 심각도 분류 → 저장/알림
                                          │
                                          ▼
                                   AI 이상 탐지
                                   (에이전트 분석)
```

### 3.2 실시간 대시보드 API

#### 3.2.1 대시보드 REST/WebSocket 엔드포인트

**새 모듈**: `coworker/server/dashboard_mixin.py`

기존 `server/app.py`의 mixin 패턴을 따라 대시보드 전용 API를 추가합니다.

```python
class DashboardMixin:
    """SessionManager에 대시보드 기능 추가"""
    
    # REST 엔드포인트
    async def dashboard_overview() -> DashboardData
    async def server_metrics(server_id: str, range: str) -> TimeSeriesData
    async def infrastructure_map() -> TopologyData
    async def cost_summary(period: str) -> CostData
    async def alert_feed(limit: int) -> list[Alert]
    
    # WebSocket 실시간 스트림
    async def ws_metrics_stream(server_ids: list[str])  # 실시간 메트릭
    async def ws_alert_stream()                          # 실시간 알림
    async def ws_log_stream(sources: list[str])          # 실시간 로그
```

**대시보드 데이터 구조**:

```python
@dataclass
class DashboardData:
    servers: list[ServerSummary]          # 서버 목록 + 상태
    alerts: list[Alert]                   # 활성 알림
    health_checks: list[HealthStatus]     # 헬스체크 현황
    resource_usage: ResourceSummary       # 전체 리소스 사용량
    recent_incidents: list[Incident]      # 최근 인시던트
    cost_trend: CostTrend                 # 비용 추이
    deployment_status: list[Deployment]   # 최근 배포

@dataclass
class ServerSummary:
    server_id: str
    hostname: str
    status: str              # "healthy", "warning", "critical", "unreachable"
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime_seconds: int
    last_check: float        # epoch
    tags: list[str]
    services: list[ServiceStatus]
```

#### 3.2.2 인프라 토폴로지 맵

```python
@dataclass
class InfraNode:
    id: str
    type: str       # "server", "container", "database", "load_balancer", "cdn"
    label: str
    status: str
    metadata: dict  # 서버 스펙, IP, 리전 등
    
@dataclass
class InfraEdge:
    source: str     # 노드 ID
    target: str
    type: str       # "network", "depends_on", "replicates_to"
    metadata: dict  # 포트, 프로토콜 등

@dataclass
class TopologyData:
    nodes: list[InfraNode]
    edges: list[InfraEdge]
```

### 3.3 알림 및 인시던트 관리

#### 3.3.1 알림 엔진

**새 모듈**: `coworker/monitoring/alerting.py`

```python
@dataclass
class AlertRule:
    id: str
    name: str
    condition: str          # "cpu > 90", "disk > 85", "health_check_fail"
    duration: int           # 조건 지속 시간 (초)
    severity: str           # "info", "warning", "critical"
    channels: list[str]     # 알림 채널 ["slack:C01234", "telegram:789"]
    cooldown: int           # 재알림 대기 (초)
    auto_remediation: str   # 자동 복구 작업 ID (선택)
    enabled: bool
    
@dataclass
class Alert:
    id: str
    rule_id: str
    server_id: str
    severity: str
    title: str
    description: str
    fired_at: float
    resolved_at: Optional[float]
    acknowledged_by: Optional[str]
    state: str              # "firing", "acknowledged", "resolved"

class AlertEngine:
    """메트릭/헬스체크 결과 기반 알림 평가 및 발송"""
    
    async def evaluate(metrics: list[MetricPoint]) -> list[Alert]
    async def send_alert(alert: Alert) -> None
    async def acknowledge(alert_id: str, user: str) -> None
    async def resolve(alert_id: str) -> None
    async def escalate(alert_id: str) -> None
```

**알림 흐름**:
```
메트릭/헬스체크 → AlertEngine.evaluate()
                      │
                      ├─ 조건 충족 + duration 초과
                      │      │
                      │      ▼
                      │  Alert 생성 → 채널 발송
                      │      │         ├─ Slack
                      │      │         ├─ Telegram
                      │      │         └─ Email (확장)
                      │      │
                      │      ├─ cooldown 내 → 스킵
                      │      │
                      │      └─ auto_remediation 있으면
                      │              → 자동 복구 작업 실행
                      │
                      └─ 조건 미충족 → 기존 Alert 자동 해제
```

**기존 모듈 연동**:
- `connectors/senders.py`의 `send_message()`를 활용하여 Slack/Telegram 알림
- `automation/scheduler.py`에 알림 평가를 extra_tick으로 연결
- `selfwake.py`의 이벤트 웨이크로 알림 해제 시 에이전트 재개

#### 3.3.2 인시던트 타임라인

**새 모듈**: `coworker/monitoring/incidents.py`

```python
@dataclass
class Incident:
    id: str
    title: str
    severity: str               # P1~P4
    status: str                 # "investigating", "identified", "monitoring", "resolved"
    created_at: float
    resolved_at: Optional[float]
    affected_services: list[str]
    timeline: list[TimelineEntry]
    related_alerts: list[str]    # Alert ID
    assignee: Optional[str]
    postmortem: Optional[str]    # Wiki 페이지 ID

@dataclass
class TimelineEntry:
    timestamp: float
    type: str           # "alert", "action", "note", "status_change"
    author: str         # "system" 또는 사용자명
    content: str
    metadata: dict

class IncidentManager:
    """인시던트 생성·추적·에스컬레이션·사후분석"""
    
    async def create(title: str, severity: str, alerts: list[str]) -> Incident
    async def update_status(incident_id: str, status: str, note: str) -> None
    async def add_timeline(incident_id: str, entry: TimelineEntry) -> None
    async def assign(incident_id: str, user: str) -> None
    async def resolve(incident_id: str, resolution: str) -> None
    async def generate_postmortem(incident_id: str) -> str  # AI 자동 생성
```

**에스컬레이션 정책**:
```python
ESCALATION_POLICY = {
    "P1": {  # 긴급
        0:  ["slack:ops-channel", "telegram:oncall"],
        5:  ["slack:team-leads"],       # 5분 무응답
        15: ["slack:engineering-all"],   # 15분 무응답
    },
    "P2": {  # 높음
        0:  ["slack:ops-channel"],
        15: ["telegram:oncall"],
        60: ["slack:team-leads"],
    },
    "P3": {  # 보통
        0:  ["slack:ops-channel"],
    },
    "P4": {  # 낮음
        0:  [],  # 대시보드에만 표시
    },
}
```

### 3.4 인프라 자동화

#### 3.4.1 자동 복구 (Auto-Remediation)

**새 모듈**: `coworker/monitoring/remediation.py`

```python
@dataclass
class RemediationAction:
    id: str
    name: str
    trigger: str              # "disk_full", "service_down", "oom", "high_cpu"
    steps: list[RemediationStep]
    max_retries: int
    requires_approval: bool   # True → Inbox로 라우팅
    
@dataclass
class RemediationStep:
    type: str       # "ssh_command", "docker_restart", "k8s_scale", "notify"
    target: str     # server_id, container_id, deployment
    command: str    # 실행할 명령 또는 액션
    timeout: int
    
class RemediationEngine:
    """알림 기반 자동 복구 실행"""
    
    async def register(action: RemediationAction) -> None
    async def execute(action_id: str, context: dict) -> RemediationResult
    async def rollback(execution_id: str) -> bool
```

**기본 제공 복구 액션**:

| 트리거 | 자동 복구 | 승인 필요 |
|--------|----------|----------|
| 디스크 85%+ | 로그 압축 + 오래된 로그 삭제 | 아니오 |
| 디스크 95%+ | 임시 파일 정리 + 알림 | 예 |
| 서비스 다운 | systemctl restart | 아니오 (3회 제한) |
| Docker OOM | 컨테이너 재시작 | 아니오 |
| K8s CrashLoop | Pod 삭제 (ReplicaSet이 재생성) | 예 |
| 메모리 95%+ | 캐시 드랍 + top 프로세스 식별 | 예 |
| SSL 인증서 7일 | Let's Encrypt 갱신 | 예 |

#### 3.4.2 IaC(Infrastructure as Code) 연동

**새 capability**: `coworker/tools/iac.py`

```python
def iac_tools(context: AgentContext) -> list:
    """Terraform/Ansible/Docker Compose 관리 도구"""
    
    # Terraform
    def terraform_plan(path: str, workspace: str) -> dict      # plan 실행
    def terraform_state(path: str) -> dict                      # 현재 상태
    def terraform_output(path: str) -> dict                     # 출력 변수
    
    # Ansible
    def ansible_inventory(path: str) -> dict                    # 인벤토리 조회
    def ansible_playbook(path: str, playbook: str, 
                         check: bool = True) -> dict             # 실행 (check=dry-run)
    
    # Docker Compose (기존 docker_mgmt.py 확장)
    def compose_config(path: str) -> dict                       # 설정 검증
    def compose_diff(path: str) -> dict                         # 변경점 비교
```

### 3.5 보안 및 컴플라이언스

#### 3.5.1 보안 스캔 도구

**새 capability**: `coworker/tools/security_scan.py`

```python
def security_tools(context: AgentContext) -> list:
    
    # 포트 스캔 (방화벽 검증)
    def port_scan(server: str, range: str = "1-1024") -> dict
    
    # SSL/TLS 검증
    def ssl_check(domain: str) -> dict  # 인증서 상세, 만료일, 체인 검증
    
    # 로그 기반 보안 이벤트
    def auth_log_analysis(server: str, hours: int = 24) -> dict  # 실패한 로그인 분석
    
    # 패키지 취약점 (OS 레벨)
    def vulnerability_check(server: str) -> dict  # apt/yum 보안 업데이트
    
    # 파일 무결성
    def file_integrity(server: str, paths: list[str]) -> dict  # 변경 감지
```

#### 3.5.2 접근 감사 로그

**새 모듈**: `coworker/monitoring/audit_ops.py`

```python
@dataclass
class OpsAuditEntry:
    timestamp: float
    user: str           # 실행한 사용자/에이전트
    action: str         # "ssh_execute", "docker_restart", "k8s_scale"
    target: str         # 대상 서버/서비스
    command: str        # 실행된 명령
    result: str         # "success", "failed", "denied"
    session_id: str
    approval_id: str    # Inbox 승인 ID (있을 경우)

class OpsAuditStore:
    """모든 운영 행위 기록 — 컴플라이언스 및 사후 분석용"""
    
    def record(entry: OpsAuditEntry) -> None
    def query(server: str, action: str, since: float) -> list[OpsAuditEntry]
    def export(format: str = "csv") -> bytes
```

---

## 4. 모듈 구조 확장 계획

### 4.1 새 디렉토리 구조

```
coworker/
├── monitoring/                    ← 신규 패키지
│   ├── __init__.py
│   ├── collector.py              # 멀티 서버 메트릭 수집기
│   ├── timeseries.py             # 시계열 저장소 (SQLite 확장)
│   ├── healthcheck.py            # 상시 헬스체크 매니저
│   ├── alerting.py               # 알림 엔진 + 규칙 평가
│   ├── incidents.py              # 인시던트 관리 + 타임라인
│   ├── log_aggregator.py         # 멀티 서버 로그 집계
│   ├── remediation.py            # 자동 복구 엔진
│   ├── audit_ops.py              # 운영 감사 로그
│   └── uptime.py                 # SLA/업타임 계산
│
├── tools/
│   ├── ... (기존 유지)
│   ├── security_scan.py          ← 신규: 보안 스캔
│   ├── iac.py                    ← 신규: IaC 도구
│   ├── network_diag.py           ← 신규: 네트워크 진단
│   └── cert_mgmt.py              ← 신규: 인증서 관리
│
├── server/
│   ├── ... (기존 유지)
│   └── dashboard_mixin.py        ← 신규: 대시보드 API
│
├── connectors/
│   ├── ssh/
│   │   ├── ... (기존 유지)
│   │   └── tunnel.py             ← 신규: SSH 터널링
│   └── cloud/
│       ├── __init__.py (기존 확장)
│       ├── gcp.py                ← 신규: GCP 지원
│       └── azure.py              ← 신규: Azure 지원
│
└── agents/
    ├── ops.py (기존 확장)
    └── sre.py                    ← 신규: SRE 전용 에이전트
```

### 4.2 카탈로그 확장

`catalog.py`에 추가할 새 Capability 항목:

```python
# 신규 Capability 추가
_CAPS_EXTENDED = [
    Capability(
        id="monitoring",
        name="Infrastructure monitoring",
        description="Multi-server metrics collection, health checks, and alerting.",
        build=_monitoring,
        requires=("secrets",),
        risk=(RiskClass.READ, RiskClass.EXTERNAL),
    ),
    Capability(
        id="incidents",
        name="Incident management",
        description="Create, track, and resolve incidents with timeline and postmortem.",
        build=_incidents,
        requires=("secrets",),
        risk=(RiskClass.READ, RiskClass.WRITE_LOCAL),
    ),
    Capability(
        id="security_scan",
        name="Security scanning",
        description="Port scanning, SSL verification, vulnerability checks, auth log analysis.",
        build=_security_scan,
        requires=("secrets",),
        risk=(RiskClass.READ, RiskClass.EXTERNAL),
    ),
    Capability(
        id="iac",
        name="Infrastructure as Code",
        description="Terraform plan/state, Ansible playbooks, Compose config management.",
        build=_iac,
        requires=("workspace", "executor"),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="cert_mgmt",
        name="Certificate management",
        description="SSL/TLS certificate monitoring, renewal, and deployment.",
        build=_cert_mgmt,
        requires=("secrets",),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="network_diag",
        name="Network diagnostics",
        description="Traceroute, MTR, DNS propagation, bandwidth testing.",
        build=_network_diag,
        requires=(),
        risk=(RiskClass.READ,),
    ),
]
```

### 4.3 SRE 에이전트 설계

**새 파일**: `coworker/agents/sre.py`

```python
SRE_CAPABILITIES = [
    # 기존 Ops 능력 전부
    *OPS_CAPABILITIES,
    # 신규 확장
    "monitoring",        # 통합 모니터링
    "incidents",         # 인시던트 관리
    "security_scan",     # 보안 스캐닝
    "iac",              # IaC 관리
    "cert_mgmt",        # 인증서 관리
    "network_diag",     # 네트워크 진단
    "ci_cd",            # CI/CD 파이프라인
]

SRE_INSTRUCTIONS = """
You are an SRE agent — a senior Site Reliability Engineer responsible for 
system availability, performance, and security. You proactively monitor 
infrastructure, respond to incidents, and automate operational tasks.

## Proactive Monitoring
- Regularly check server health across all registered servers
- Monitor resource trends and predict capacity issues
- Track SSL certificate expiration dates
- Review security logs for anomalies

## Incident Response Protocol
1. Acknowledge alert
2. Assess impact and severity
3. Create incident timeline
4. Investigate root cause
5. Apply remediation (with approval for destructive actions)
6. Verify resolution
7. Generate postmortem

## Automation
- Execute registered auto-remediation actions
- Update runbooks based on incident learnings
- Maintain health check configurations
- Manage alert rules and escalation policies
"""
```

---

## 5. 데이터 저장소 설계

### 5.1 시계열 데이터베이스 (SQLite 확장)

**새 파일**: `coworker/monitoring/timeseries.py`

```sql
-- 원시 메트릭 (1분 간격, 7일 보관)
CREATE TABLE metrics_raw (
    server_id  TEXT NOT NULL,
    ts         INTEGER NOT NULL,  -- epoch seconds
    cpu        REAL,
    memory     REAL,
    disk       REAL,
    net_rx     INTEGER,
    net_tx     INTEGER,
    load_1m    REAL,
    custom     TEXT,  -- JSON
    PRIMARY KEY (server_id, ts)
) WITHOUT ROWID;

-- 5분 집계 (30일 보관)
CREATE TABLE metrics_5m (
    server_id  TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    cpu_avg    REAL, cpu_max  REAL,
    mem_avg    REAL, mem_max  REAL,
    disk_avg   REAL, disk_max REAL,
    net_rx_sum INTEGER, net_tx_sum INTEGER,
    load_avg   REAL,
    PRIMARY KEY (server_id, ts)
) WITHOUT ROWID;

-- 1시간 집계 (90일 보관)
CREATE TABLE metrics_1h ( ... );

-- 1일 집계 (365일 보관)
CREATE TABLE metrics_1d ( ... );

-- 알림
CREATE TABLE alerts (
    id          TEXT PRIMARY KEY,
    rule_id     TEXT NOT NULL,
    server_id   TEXT NOT NULL,
    severity    TEXT NOT NULL,
    state       TEXT NOT NULL,  -- firing, acknowledged, resolved
    title       TEXT,
    fired_at    REAL,
    resolved_at REAL,
    ack_by      TEXT
);

-- 인시던트
CREATE TABLE incidents (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    severity    TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  REAL,
    resolved_at REAL,
    assignee    TEXT,
    postmortem  TEXT
);

-- 인시던트 타임라인
CREATE TABLE incident_timeline (
    incident_id TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    timestamp   REAL,
    type        TEXT,
    author      TEXT,
    content     TEXT,
    metadata    TEXT,  -- JSON
    PRIMARY KEY (incident_id, seq)
);

-- 헬스체크 규칙
CREATE TABLE health_checks (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    type            TEXT,
    target          TEXT,
    interval_sec    INTEGER,
    timeout_sec     INTEGER,
    retries         INTEGER,
    alert_channels  TEXT,  -- JSON
    enabled         INTEGER DEFAULT 1
);

-- 헬스체크 결과 (24시간 보관)
CREATE TABLE health_results (
    check_id    TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    status      TEXT,  -- ok, fail, warn
    latency_ms  REAL,
    error       TEXT,
    PRIMARY KEY (check_id, ts)
) WITHOUT ROWID;

-- 운영 감사 로그
CREATE TABLE ops_audit (
    ts          REAL NOT NULL,
    user        TEXT,
    action      TEXT,
    target      TEXT,
    command     TEXT,
    result      TEXT,
    session_id  TEXT,
    approval_id TEXT
);
```

### 5.2 다운샘플링 정책

```python
RETENTION_POLICY = {
    "metrics_raw":    7,    # 7일
    "metrics_5m":     30,   # 30일
    "metrics_1h":     90,   # 90일
    "metrics_1d":     365,  # 1년
    "health_results": 1,    # 1일 (상세), 집계는 별도
    "alerts":         180,  # 6개월
    "ops_audit":      365,  # 1년 (컴플라이언스)
}
```

---

## 6. 기존 모듈 확장 상세

### 6.1 `server_monitor.py` 확장

| 현재 도구 | 확장 내용 |
|-----------|----------|
| `server_status` | 원격 서버 지원 (server_id 파라미터 추가) |
| `check_ports` | 결과를 헬스체크 이력에 자동 저장 |
| `process_list` | OOM 킬러 점수 + cgroup 메모리 제한 포함 |
| `system_logs` | 로그 집계기와 연동, 패턴 알림 지원 |
| `disk_usage` | I/O 통계 (iowait, read/write IOPS) 추가 |
| **신규** `network_stats_extended` | 인터페이스별 대역폭, 에러율, 드롭 |
| **신규** `gpu_status` | NVIDIA GPU 모니터링 (nvidia-smi) |

### 6.2 `docker_mgmt.py` 확장

| 현재 도구 | 확장 내용 |
|-----------|----------|
| `docker_ps` | 헬스체크 상태, 재시작 횟수, 생성 시간 포함 |
| `docker_stats` | 시계열 저장 연동 |
| **신규** `docker_inspect` | 컨테이너 상세 설정 (네트워크, 볼륨, 환경변수) |
| **신규** `docker_networks` | 네트워크 목록 및 연결된 컨테이너 |
| **신규** `docker_volumes` | 볼륨 목록, 사용량, 고아 볼륨 탐지 |
| **신규** `docker_prune` | 미사용 리소스 정리 (승인 필요) |

### 6.3 `k8s_mgmt.py` 확장

| 현재 도구 | 확장 내용 |
|-----------|----------|
| `k8s_pods` | 리소스 사용량 (metrics-server), QoS 클래스 |
| `k8s_describe` | ConfigMap, Secret, Ingress 추가 |
| **신규** `k8s_nodes` | 노드 상태, 리소스 할당량 |
| **신규** `k8s_top` | kubectl top pods/nodes (메트릭 서버) |
| **신규** `k8s_ingress` | Ingress 규칙 및 TLS 상태 |
| **신규** `k8s_hpa` | HPA 상태 및 스케일링 이력 |
| **신규** `k8s_contexts` | 멀티 클러스터 컨텍스트 전환 |

### 6.4 `cloud_infra.py` 확장

| 현재 도구 | 확장 내용 |
|-----------|----------|
| `aws_ec2_list` | 태그 필터링, Auto Scaling Group 포함 |
| `aws_cloudwatch_metrics` | 커스텀 메트릭, 알람 상태 조회 |
| `aws_cost_explorer` | 비용 예측, 예산 알림 |
| **신규** `aws_rds_status` | RDS 인스턴스 상태, 레플리카 지연 |
| **신규** `aws_elb_status` | 로드밸런서 상태, 타겟 그룹 헬스 |
| **신규** `aws_route53` | DNS 레코드 관리 (Route53) |
| **신규** `aws_iam_audit` | IAM 사용자/역할 감사 |
| **신규** `gcp_compute_list` | GCE 인스턴스 목록 |
| **신규** `gcp_gke_clusters` | GKE 클러스터 상태 |
| **신규** `azure_vm_list` | Azure VM 목록 |

### 6.5 `ci_cd.py` 확장

| 현재 도구 | 확장 내용 |
|-----------|----------|
| `ci_status` | 실패율 통계, 평균 빌드 시간 |
| **신규** `ci_gitlab` | GitLab CI 파이프라인 지원 |
| **신규** `deploy_history` | 배포 이력 (날짜, 커밋, 롤백 여부) |
| **신규** `deploy_canary` | 카나리 배포 상태 (트래픽 비율) |

---

## 7. 구현 우선순위 및 로드맵

### Phase 1: 기반 강화 (필수)

| 순서 | 작업 | 예상 복잡도 | 의존성 |
|------|------|-----------|--------|
| 1-1 | `monitoring/timeseries.py` — 시계열 저장소 | 중 | 없음 |
| 1-2 | `monitoring/collector.py` — 멀티 서버 수집기 | 중 | 1-1, SSH |
| 1-3 | `monitoring/alerting.py` — 알림 엔진 | 중 | 1-2, Connectors |
| 1-4 | `monitoring/healthcheck.py` — 상시 헬스체크 | 중 | 1-1 |
| 1-5 | 기존 `server_monitor.py` 원격 서버 확장 | 하 | SSH |

### Phase 2: 운영 자동화

| 순서 | 작업 | 예상 복잡도 | 의존성 |
|------|------|-----------|--------|
| 2-1 | `monitoring/incidents.py` — 인시던트 관리 | 중 | Phase 1 |
| 2-2 | `monitoring/remediation.py` — 자동 복구 | 상 | 1-3 |
| 2-3 | `monitoring/log_aggregator.py` — 로그 집계 | 중 | SSH |
| 2-4 | `agents/sre.py` — SRE 에이전트 | 하 | Phase 1 |

### Phase 3: 대시보드 & 확장

| 순서 | 작업 | 예상 복잡도 | 의존성 |
|------|------|-----------|--------|
| 3-1 | `server/dashboard_mixin.py` — 대시보드 API | 중 | Phase 1 |
| 3-2 | Docker/K8s 도구 확장 | 하 | 없음 |
| 3-3 | 클라우드 도구 확장 (AWS RDS/ELB) | 중 | 없음 |
| 3-4 | `tools/security_scan.py` — 보안 스캔 | 중 | SSH |

### Phase 4: 멀티 클라우드 & IaC

| 순서 | 작업 | 예상 복잡도 | 의존성 |
|------|------|-----------|--------|
| 4-1 | `connectors/cloud/gcp.py` — GCP 연동 | 상 | 없음 |
| 4-2 | `connectors/cloud/azure.py` — Azure 연동 | 상 | 없음 |
| 4-3 | `tools/iac.py` — Terraform/Ansible | 상 | Executor |
| 4-4 | `tools/cert_mgmt.py` — 인증서 관리 | 중 | SSH |

---

## 8. 기존 모듈과의 통합 포인트

### 8.1 스케줄러 통합

```python
# manager.py 확장
class SessionManager:
    def __init__(self, ...):
        # 기존 초기화 유지
        self.scheduler = Scheduler(
            store=self.task_store,
            runner=self._run_scheduled_task,
            tick_seconds=30.0,
            extra_tick=self._monitoring_tick,  # ← 모니터링 통합
        )
        
    async def _monitoring_tick(self):
        """스케줄러 tick마다 실행"""
        await self.collector.collect_all()      # 메트릭 수집
        await self.health_manager.run_checks()  # 헬스체크
        await self.alert_engine.evaluate()      # 알림 평가
        await self.resume_due_wakes()           # 웨이크 재개
```

### 8.2 메시징 커넥터 통합

```python
# alerting.py → connectors 연동
async def send_alert(alert: Alert):
    for channel in alert.rule.channels:
        platform, chat_id = parse_target(channel)
        adapter = gateway.get_adapter(platform)
        
        text = format_alert_message(alert)
        buttons = [
            {"text": "확인", "value": f"ack:{alert.id}"},
            {"text": "해제", "value": f"resolve:{alert.id}"},
        ]
        await adapter.send_interactive(chat_id, text, buttons)
```

### 8.3 Wiki 통합

```python
# incidents.py → wiki 연동
async def generate_postmortem(incident_id: str) -> str:
    """AI가 인시던트 타임라인으로 사후분석 문서 자동 생성"""
    incident = await self.get(incident_id)
    
    # 에이전트에게 타임라인 분석 요청
    prompt = f"""다음 인시던트의 사후분석(Postmortem) 문서를 작성하세요:
    - 제목: {incident.title}
    - 심각도: {incident.severity}
    - 타임라인: {json.dumps(incident.timeline)}
    
    포함 항목: 요약, 영향 범위, 근본 원인, 조치 내역, 재발 방지 대책"""
    
    # Wiki에 저장
    page_id = await wiki_store.create(
        title=f"Postmortem: {incident.title}",
        category="postmortem",
        content=postmortem_text,
    )
    return page_id
```

### 8.4 Inbox/권한 통합

```python
# 자동 복구 시 승인이 필요한 경우 Inbox로 라우팅
async def request_remediation_approval(action: RemediationAction, context: dict):
    """Inbox에 복구 승인 요청 생성"""
    item = InboxItem(
        kind="remediation_approval",
        title=f"자동 복구 승인: {action.name}",
        body=f"서버 {context['server_id']}에서 {action.trigger} 감지.\n"
             f"실행 예정: {action.steps}",
        choices=["승인", "거부"],
        expires_at=time.time() + 300,  # 5분 타임아웃
    )
    await inbox.put(item)
```

---

## 9. 외부 연동 확장 가능성

### 9.1 APM/관측 도구 연동 (선택)

| 도구 | 연동 방식 | 용도 |
|------|----------|------|
| Prometheus | HTTP API 조회 | 기존 메트릭 활용 |
| Grafana | API로 대시보드 링크 삽입 | 시각화 위임 |
| Datadog | REST API | 기존 모니터링 보완 |
| PagerDuty | Webhook | 외부 에스컬레이션 |
| OpsGenie | REST API | 온콜 관리 |

### 9.2 ITMS 연동 (Gitea 기반)

기존 메모리의 `itms.weve.io.kr` Gitea 연동과 결합:
- 인시던트 → Gitea Issue 자동 생성
- 배포 이력 → Gitea Release 연동
- 런북 → Gitea Wiki 동기화

---

## 10. 보안 고려사항

### 10.1 접근 제어

| 계층 | 현재 | 확장 |
|------|------|------|
| API 인증 | 토큰 기반 | RBAC (읽기전용/운영자/관리자) |
| 도구 권한 | Mode + requires_approval | 역할별 도구 제한 |
| SSH 접근 | key_path 검증 | SSH 키 회전 + 감사 로그 |
| 비밀번호 | Vault (Argon2/PBKDF2) | 자동 회전 정책 |

### 10.2 네트워크 보안

- 모니터링 수집: SSH 터널 또는 VPN 경유만 허용
- 대시보드 API: 기존 CORS 정책 유지 (localhost만)
- 알림 발송: TLS 필수, Webhook 서명 검증

---

## 11. 세션 기반 서비스 구성 및 위키 관리 시스템

### 11.1 개요

현재 세션(`SessionRecord`)은 대화 이력과 권한만 관리합니다. 이를 확장하여 세션 내에서 **서버 등록**, **개발 환경 설정**, **데이터베이스 프로필 구성**, **서비스 설정**, **위키 문서 작성**을 통합적으로 수행할 수 있는 구조를 설계합니다.

### 11.2 세션 기반 서버 구성 관리

#### 11.2.1 현재 구조

```
secrets.json
  └─ ssh:server:<id> → {host, port, username, key_path, label, tags}
  └─ database:<name> → {type, host, port, name, user, password}
  └─ cloud:provider:<name> → {provider, api_key, api_secret, region}
```

현재는 `ssh/accounts.py`의 `add_server()`, `db_mgmt.py`의 `_add_database()`, `cloud/__init__.py`의 `add_provider()`가 각각 독립적으로 동작합니다.

#### 11.2.2 통합 서버 온보딩 워크플로우

**새 모듈**: `coworker/tools/server_setup.py`

세션 내에서 대화형으로 서버를 등록하고, 연결 테스트 후 Wiki 페이지를 자동 생성하는 통합 워크플로우입니다.

```python
def server_setup_tools(context: AgentContext) -> list:
    """서버 온보딩 통합 도구"""
    
    # 1. 서버 등록 + 연결 테스트 + Wiki 자동 생성
    def register_server(
        server_id: str,
        host: str,
        port: int = 22,
        username: str = "deploy",
        key_path: str = "",
        label: str = "",
        tags: list[str] = [],
        create_wiki: bool = True,
    ) -> dict:
        """서버 등록, 연결 테스트, Wiki 문서 자동 생성을 한 번에 수행"""
        # Step 1: SSH 서버 등록
        add_result = ssh_accounts.add_server(secrets, server_id, host, port, username, key_path, label, tags)
        if not add_result.get("ok"):
            return add_result
            
        # Step 2: 연결 테스트
        client = SSHClient(SSHServer(server_id, host, port, username, key_path))
        test = client.test_connection()
        
        # Step 3: 서버 정보 자동 수집
        if test["ok"]:
            info = client.execute("uname -a && cat /etc/os-release 2>/dev/null | head -5")
            disk = client.execute("df -h / | tail -1")
            mem = client.execute("free -h | head -2")
            services = client.execute("systemctl list-units --type=service --state=running --no-pager | head -20")
        
        # Step 4: Wiki 페이지 자동 생성
        if create_wiki:
            wiki_content = _generate_server_wiki(server_id, host, port, username, info, disk, mem, services)
            wiki_store.create_page(
                page_id=f"server-{server_id}",
                name=f"서버: {label or server_id}",
                category="server",
                content=wiki_content,
                linked_service=f"ssh:server:{server_id}",
                tags=tags,
                structured_data={
                    "host": host, "port": port, "user": username,
                    "os": info.get("stdout", "")[:100],
                    "services": [],
                },
            )
        
        return {
            "ok": True,
            "server_id": server_id,
            "connection_test": test,
            "wiki_page": f"server-{server_id}" if create_wiki else None,
        }
    
    # 2. 서버 목록 + 상태 통합 조회
    def list_infrastructure() -> dict:
        """등록된 모든 인프라 (서버, DB, 클라우드) 통합 조회"""
        registry = ServiceRegistry(wiki_store, secrets, vault)
        services = registry.list_services()
        
        # 카테고리별 분류
        result = {
            "servers": [s for s in services if s["type"] == "ssh"],
            "databases": [s for s in services if s["type"] == "database"],
            "cloud_providers": [s for s in services if s["type"] == "cloud"],
            "other": [s for s in services if s["type"] not in ("ssh", "database", "cloud")],
            "total": len(services),
        }
        return {"ok": True, **result}
    
    # 3. 서버 정보 갱신
    def refresh_server_info(server_id: str) -> dict:
        """SSH로 서버 정보를 다시 수집하고 Wiki 페이지를 업데이트"""
        client = _resolve_ssh_client(server_id)
        info = _collect_server_info(client)
        
        # Wiki 페이지 업데이트
        page_id = f"server-{server_id}"
        wiki_content = _generate_server_wiki_from_info(server_id, info)
        wiki_store.update_page(page_id, content=wiki_content, change_note="서버 정보 자동 갱신")
        
        return {"ok": True, "server_id": server_id, "info": info}
    
    # 4. 서버 제거 (Wiki 포함)
    def decommission_server(server_id: str, archive_wiki: bool = True) -> dict:
        """서버 등록 해제 + Wiki 아카이브"""
        ssh_accounts.remove_server(secrets, server_id)
        if archive_wiki:
            wiki_store.update_page(
                f"server-{server_id}",
                tags=["decommissioned"],
                change_note=f"서버 {server_id} 퇴역",
            )
        return {"ok": True, "server_id": server_id}
```

**서버 Wiki 자동 생성 템플릿**:

```markdown
# 서버: {label} ({server_id})

## 연결 정보
- **호스트**: {host}
- **포트**: {port}
- **사용자**: {username}
- **등록일**: {registered_at}

## 시스템 정보
- **OS**: {os_info}
- **커널**: {kernel}
- **CPU**: {cpu_info}
- **메모리**: {memory_total}
- **디스크**: {disk_info}

## 실행 중인 서비스
{services_list}

## 모니터링 설정
- 헬스체크: {health_check_status}
- 알림 규칙: {alert_rules}

## 접근 이력
| 날짜 | 사용자 | 작업 | 결과 |
|------|--------|------|------|

## 메모
```

### 11.3 세션 기반 개발 환경 설정

#### 11.3.1 개발 환경 프로필 관리

**새 모듈**: `coworker/tools/dev_setup.py`

세션 내에서 개발 환경(Git, CI/CD, 패키지 매니저 등)을 구성하고 Wiki에 문서화합니다.

```python
def dev_setup_tools(context: AgentContext) -> list:
    """개발 환경 구성 도구"""
    
    # 1. 프로젝트 환경 스캔 및 등록
    def scan_project(path: str) -> dict:
        """프로젝트 디렉토리를 분석하여 개발 환경 정보 추출"""
        result = {
            "language": _detect_language(path),        # Python, Node, Go, etc.
            "framework": _detect_framework(path),      # FastAPI, Django, Next.js, etc.
            "package_manager": _detect_package_manager(path),  # pip, npm, yarn, etc.
            "build_tool": _detect_build_tool(path),    # make, gradle, etc.
            "ci_config": _detect_ci_config(path),      # .github/workflows, .gitlab-ci.yml
            "docker": _detect_docker(path),            # Dockerfile, docker-compose.yml
            "env_files": _detect_env_files(path),      # .env, .env.example
            "test_framework": _detect_test_framework(path),  # pytest, jest, etc.
            "linter": _detect_linter(path),            # ruff, eslint, etc.
        }
        return {"ok": True, "project": result}
    
    # 2. 개발 환경 Wiki 페이지 생성
    def create_dev_wiki(
        project_name: str,
        repo_url: str = "",
        description: str = "",
        scan_path: str = "",
    ) -> dict:
        """프로젝트 스캔 결과를 기반으로 개발 환경 Wiki 문서 생성"""
        scan = scan_project(scan_path) if scan_path else {}
        
        wiki_store.create_page(
            page_id=f"dev-{project_name}",
            name=f"개발 환경: {project_name}",
            category="development",
            content=_generate_dev_wiki(project_name, repo_url, description, scan),
            tags=["development", scan.get("language", "")],
            structured_data={
                "repo_url": repo_url,
                "language": scan.get("language", ""),
                "framework": scan.get("framework", ""),
                "ci": scan.get("ci_config", ""),
            },
        )
        return {"ok": True, "page_id": f"dev-{project_name}"}
    
    # 3. Git 저장소 연동 설정
    def setup_git_integration(
        project_name: str,
        platform: str,      # "github", "gitea", "gitlab"
        repo: str,          # "owner/repo"
        token_key: str = "",  # secrets 키
    ) -> dict:
        """Git 플랫폼 연동 설정 및 Wiki 업데이트"""
        # 토큰 설정
        if token_key:
            secrets.set(f"git:{platform}:{project_name}", {"token": token_key, "repo": repo})
        
        # Wiki 업데이트
        wiki_store.update_page(
            f"dev-{project_name}",
            change_note=f"{platform} 저장소 연동: {repo}",
        )
        
        return {"ok": True, "platform": platform, "repo": repo}
    
    # 4. 환경 변수 템플릿 관리
    def manage_env_template(
        project_name: str,
        action: str = "get",       # "get", "set", "diff"
        variables: dict = {},
    ) -> dict:
        """.env 템플릿 관리 (실제 값은 Vault에 저장)"""
        page_id = f"dev-{project_name}"
        
        if action == "get":
            page = wiki_store.get_page(page_id)
            return {"ok": True, "env_template": page.get("structured_data", {}).get("env_vars", {})}
        elif action == "set":
            # 키만 Wiki에, 값은 Vault에
            for key, value in variables.items():
                vault.store(f"{page_id}:env:{key}", value)
            return {"ok": True, "keys_stored": list(variables.keys())}
        elif action == "diff":
            # 서버의 실제 환경 변수와 템플릿 비교
            return _compare_env(project_name, variables)
    
    # 5. 배포 설정 관리
    def setup_deployment(
        project_name: str,
        target_server: str,    # server_id
        deploy_path: str,      # /opt/app/
        deploy_method: str,    # "git_pull", "docker", "rsync"
        pre_deploy: str = "",  # 배포 전 명령
        post_deploy: str = "", # 배포 후 명령
    ) -> dict:
        """배포 설정을 Wiki에 저장"""
        deploy_config = {
            "server": target_server,
            "path": deploy_path,
            "method": deploy_method,
            "pre_deploy": pre_deploy,
            "post_deploy": post_deploy,
        }
        
        # Wiki에 배포 런북 생성
        wiki_store.create_page(
            page_id=f"deploy-{project_name}",
            name=f"배포 런북: {project_name}",
            category="runbook",
            content=_generate_deploy_runbook(project_name, deploy_config),
            linked_service=f"ssh:server:{target_server}",
            tags=["deployment", project_name],
            structured_data=deploy_config,
        )
        
        return {"ok": True, "page_id": f"deploy-{project_name}"}
```

**개발 환경 Wiki 자동 생성 템플릿**:

```markdown
# 프로젝트: {project_name}

## 개요
{description}

## 저장소
- **URL**: {repo_url}
- **플랫폼**: {platform}
- **기본 브랜치**: main

## 기술 스택
- **언어**: {language} {version}
- **프레임워크**: {framework}
- **패키지 매니저**: {package_manager}
- **빌드 도구**: {build_tool}

## 개발 환경 설정
```bash
# 의존성 설치
{install_command}

# 개발 서버 실행
{run_command}

# 테스트 실행  
{test_command}
```

## CI/CD
- **파이프라인**: {ci_config}
- **배포 대상**: [[서버: {target_server}]]

## 환경 변수
| 변수명 | 설명 | 필수 | 기본값 |
|--------|------|------|--------|
{env_vars_table}

## 배포 절차
→ [[배포 런북: {project_name}]]

## 관련 서비스
- DB: [[DB: {db_name}]]
- 캐시: [[Redis: {redis_name}]]
```

### 11.4 세션 기반 데이터베이스 프로필 구성

#### 11.4.1 DB 프로필 통합 관리

**확장 대상**: `coworker/tools/db_mgmt.py`

현재 `_add_database()`와 `_remove_database()`를 확장하여 세션 내에서 대화형으로 DB를 구성하고 Wiki에 문서화합니다.

```python
# db_mgmt.py 확장 도구

def db_setup_tools(context: AgentContext) -> list:
    """DB 프로필 구성 및 문서화 도구"""
    
    # 1. DB 프로필 등록 + 연결 테스트 + Wiki 생성
    def register_database(
        name: str,
        db_type: str,          # "postgresql", "mysql", "sqlite"
        host: str = "",
        port: int = 0,
        database: str = "",
        user: str = "",
        password: str = "",
        path: str = "",        # SQLite 전용
        create_wiki: bool = True,
        tags: list[str] = [],
    ) -> dict:
        """DB 프로필 등록, 연결 테스트, 스키마 자동 문서화"""
        
        # Step 1: 프로필 등록 (비밀번호는 Vault에)
        cfg = {"type": db_type, "host": host, "port": port or _default_port(db_type),
               "name": database, "user": user}
        secrets.set(f"database:{name}", cfg)
        if password:
            vault.store(f"database:{name}:password", password)
        
        # Step 2: 연결 테스트
        test_result = _test_connection(cfg, password)
        
        # Step 3: 스키마 자동 수집
        schema_info = {}
        if test_result["ok"]:
            schema_info = {
                "tables": _get_tables(cfg),
                "version": _get_status(cfg).get("version", ""),
                "size": _get_status(cfg).get("database_size", ""),
            }
        
        # Step 4: Wiki 페이지 생성
        if create_wiki:
            wiki_store.create_page(
                page_id=f"db-{name}",
                name=f"DB: {name} ({db_type})",
                category="database",
                content=_generate_db_wiki(name, db_type, host, port, database, user, schema_info),
                credentials=[
                    {"key": "password", "type": "password", "rotation": "90d"},
                ],
                linked_service=f"database:{name}",
                tags=["database", db_type, *tags],
                structured_data={
                    "type": db_type, "host": host,
                    "port": port, "database": database, "user": user,
                    "backup_schedule": "",
                    "tables_count": len(schema_info.get("tables", [])),
                },
            )
        
        return {
            "ok": True,
            "name": name,
            "connection_test": test_result,
            "schema": schema_info,
            "wiki_page": f"db-{name}" if create_wiki else None,
        }
    
    # 2. 스키마 변경 추적
    def track_schema_changes(name: str) -> dict:
        """현재 스키마와 Wiki에 기록된 스키마를 비교"""
        cfg = _resolve_config(context, name)
        current_tables = _get_tables(cfg)
        
        page = wiki_store.get_page(f"db-{name}")
        if not page:
            return {"ok": False, "error": "Wiki 페이지 없음"}
        
        recorded_count = page.get("structured_data", {}).get("tables_count", 0)
        
        return {
            "ok": True,
            "current_tables": len(current_tables),
            "recorded_tables": recorded_count,
            "changed": len(current_tables) != recorded_count,
            "tables": current_tables,
        }
    
    # 3. ERD 다이어그램 + Wiki 업데이트
    def update_db_documentation(name: str) -> dict:
        """ERD 다이어그램 생성 + Wiki 페이지 업데이트"""
        cfg = _resolve_config(context, name)
        erd = _generate_erd_mermaid(cfg)
        tables = _get_tables(cfg)
        status = _get_status(cfg)
        
        wiki_content = _generate_db_wiki_full(name, cfg, tables, status, erd)
        wiki_store.update_page(
            f"db-{name}",
            content=wiki_content,
            change_note="스키마 및 상태 정보 자동 갱신",
        )
        
        return {"ok": True, "tables": len(tables), "erd_generated": bool(erd)}
    
    # 4. 백업 스케줄 설정
    def setup_backup_schedule(
        name: str,
        schedule: str,         # "0 2 * * *" (매일 2시)
        output_path: str,      # "/backup/db/"
        retention_days: int = 30,
        notify_channel: str = "",  # "slack:C01234"
    ) -> dict:
        """DB 백업 자동화 작업 생성"""
        task = ScheduledTask(
            title=f"DB 백업: {name}",
            instructions=f"db_backup 도구로 {name} 데이터베이스를 {output_path}에 백업하세요. "
                        f"{retention_days}일 이전 백업은 삭제하세요.",
            schedule=Schedule(kind="cron", cron=schedule),
            workspace=str(context.workspace),
            notify_target=notify_channel,
        )
        
        # Wiki에 백업 정보 기록
        wiki_store.update_page(
            f"db-{name}",
            change_note=f"백업 스케줄 설정: {schedule}",
        )
        
        return {"ok": True, "task_id": task.id, "schedule": schedule}
```

**DB Wiki 자동 생성 템플릿**:

```markdown
# DB: {name} ({db_type})

## 연결 정보
- **호스트**: {host}
- **포트**: {port}
- **데이터베이스**: {database}
- **사용자**: {user}
- **비밀번호**: 🔒 Vault에 저장

## 상태
- **버전**: {version}
- **크기**: {size}
- **연결 수**: {connections}
- **마지막 테스트**: {last_test}

## 스키마 ({tables_count}개 테이블)

### 테이블 목록
| 테이블명 | 행 수 | 설명 |
|---------|-------|------|
{tables_list}

### ERD 다이어그램
```mermaid
{erd_mermaid}
```

## 백업
- **스케줄**: {backup_schedule}
- **경로**: {backup_path}
- **보관기간**: {retention_days}일
- **마지막 백업**: {last_backup}

## 마이그레이션 이력
{migration_history}

## 접근 정책
- 읽기: {read_users}
- 쓰기: {write_users}
- 관리: {admin_users}

## 메모
```

### 11.5 세션 기반 서비스 설정 관리

#### 11.5.1 서비스 구성 통합 도구

**새 모듈**: `coworker/tools/service_config.py`

서비스(웹 애플리케이션, API, 마이크로서비스 등)의 설정을 구성하고 관리합니다.

```python
def service_config_tools(context: AgentContext) -> list:
    """서비스 설정 구성 및 관리 도구"""
    
    # 1. 서비스 등록
    def register_service(
        service_id: str,
        name: str,
        service_type: str,      # "web", "api", "worker", "cron", "microservice"
        server_id: str = "",    # 호스팅 서버
        port: int = 0,
        health_url: str = "",   # 헬스체크 URL
        repo: str = "",         # Git 저장소
        dependencies: list[str] = [],  # 의존 서비스 ["database:prod", "redis:main"]
        create_wiki: bool = True,
    ) -> dict:
        """서비스 등록 + 의존관계 매핑 + Wiki 문서 생성"""
        
        # 서비스 프로필 저장
        profile = {
            "name": name,
            "type": service_type,
            "server": server_id,
            "port": port,
            "health_url": health_url,
            "repo": repo,
            "dependencies": dependencies,
        }
        secrets.set(f"service:{service_id}", profile)
        
        # 헬스체크 자동 등록
        if health_url:
            health_manager.add_check(HealthCheckRule(
                id=f"svc-{service_id}",
                name=f"서비스: {name}",
                type="http",
                target=health_url,
                interval_seconds=60,
                timeout_seconds=10,
                retries=3,
            ))
        
        # Wiki 페이지 생성
        if create_wiki:
            wiki_store.create_page(
                page_id=f"svc-{service_id}",
                name=f"서비스: {name}",
                category="service",
                content=_generate_service_wiki(service_id, name, service_type, profile),
                linked_service=f"service:{service_id}",
                tags=["service", service_type],
                structured_data=profile,
            )
        
        return {"ok": True, "service_id": service_id}
    
    # 2. 서비스 의존관계 맵
    def service_dependency_map(service_id: str = "") -> dict:
        """서비스 의존관계 토폴로지 생성"""
        services = _load_all_services()
        
        if service_id:
            # 특정 서비스의 의존 트리
            tree = _build_dependency_tree(service_id, services)
            return {"ok": True, "service": service_id, "tree": tree}
        
        # 전체 의존관계 맵 (Mermaid 다이어그램)
        mermaid = _generate_dependency_mermaid(services)
        return {"ok": True, "total_services": len(services), "mermaid": mermaid}
    
    # 3. 서비스 설정 파일 관리
    def manage_config_file(
        service_id: str,
        action: str,         # "get", "set", "diff", "history"
        config_type: str = "",  # "nginx", "systemd", "docker-compose", "env"
        content: str = "",
        server_id: str = "",
    ) -> dict:
        """서비스 설정 파일 버전 관리"""
        
        if action == "get":
            # 서버에서 현재 설정 읽기
            if server_id:
                path = _config_path(config_type, service_id)
                client = _resolve_ssh_client(server_id)
                result = client.execute(f"cat {path}")
                return {"ok": True, "content": result["stdout"], "path": path}
            # Wiki에서 읽기
            page = wiki_store.get_page(f"config-{service_id}-{config_type}")
            return {"ok": True, "content": page.get("content", "") if page else ""}
            
        elif action == "set":
            # 설정을 Wiki에 버전 관리하며 저장
            page_id = f"config-{service_id}-{config_type}"
            existing = wiki_store.get_page(page_id)
            if existing:
                wiki_store.update_page(page_id, content=content, change_note="설정 업데이트")
            else:
                wiki_store.create_page(
                    page_id=page_id,
                    name=f"설정: {service_id} ({config_type})",
                    category="config",
                    content=content,
                    linked_service=f"service:{service_id}",
                    tags=["config", config_type],
                )
            return {"ok": True, "page_id": page_id}
            
        elif action == "diff":
            # 서버 현재 설정과 Wiki 저장 설정 비교
            return _diff_config(service_id, config_type, server_id)
            
        elif action == "history":
            # 설정 변경 이력
            history = wiki_store.get_history(f"config-{service_id}-{config_type}")
            return {"ok": True, "history": history}
    
    # 4. Nginx/Apache 설정 생성
    def generate_web_config(
        service_id: str,
        domain: str,
        upstream_port: int,
        ssl: bool = True,
        config_type: str = "nginx",   # "nginx", "apache", "caddy"
    ) -> dict:
        """웹 서버 설정 자동 생성"""
        if config_type == "nginx":
            config = _generate_nginx_config(domain, upstream_port, ssl)
        elif config_type == "apache":
            config = _generate_apache_config(domain, upstream_port, ssl)
        elif config_type == "caddy":
            config = _generate_caddy_config(domain, upstream_port)
        
        # Wiki에 저장
        manage_config_file(service_id, "set", config_type, config)
        
        return {"ok": True, "config_type": config_type, "domain": domain, "content": config}
    
    # 5. systemd 서비스 파일 생성
    def generate_systemd_unit(
        service_id: str,
        exec_start: str,
        working_directory: str = "",
        user: str = "",
        environment: dict = {},
        restart: str = "always",
    ) -> dict:
        """systemd 유닛 파일 자동 생성"""
        unit_content = _generate_systemd_unit(
            service_id, exec_start, working_directory, user, environment, restart
        )
        manage_config_file(service_id, "set", "systemd", unit_content)
        
        return {"ok": True, "content": unit_content}
    
    # 6. Docker Compose 설정 생성
    def generate_compose(
        service_id: str,
        services: list[dict],   # [{name, image, ports, env, volumes}]
        networks: list[str] = [],
    ) -> dict:
        """docker-compose.yml 자동 생성"""
        compose = _generate_docker_compose(services, networks)
        manage_config_file(service_id, "set", "docker-compose", compose)
        
        return {"ok": True, "content": compose}
```

**서비스 Wiki 자동 생성 템플릿**:

```markdown
# 서비스: {name}

## 개요
- **유형**: {service_type}
- **서버**: [[서버: {server_id}]]
- **포트**: {port}
- **저장소**: {repo}

## 상태
- **헬스체크**: {health_url}
- **마지막 상태**: {last_status}
- **업타임**: {uptime}

## 의존 서비스
{dependencies_with_wiki_links}

```mermaid
graph LR
  {dependency_graph}
```

## 설정 파일
- [[설정: {service_id} (nginx)]]
- [[설정: {service_id} (systemd)]]
- [[설정: {service_id} (env)]]

## 배포
→ [[배포 런북: {project_name}]]

## 로그
- 경로: {log_path}
- 로테이션: {log_rotation}

## 모니터링
- 알림 규칙: {alert_rules}
- 대시보드: {dashboard_url}

## 메모
```

### 11.6 서비스 위키 = 설정 정보 리포지토리 (핵심 설계)

서비스 위키의 **주요 목적**은 단순한 문서가 아니라, 모든 인프라·서비스 설정 정보를 **세션에서 저장하고, 분석하고, 실 서비스 연동 시 활용하는 중앙 리포지토리** 역할을 수행하는 것입니다.

```
┌─────────────────────────────────────────────────────────────────┐
│                  서비스 위키 = 설정 리포지토리                    │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  저장 계층   │  │  분석 계층   │  │  연동 계층              │ │
│  │             │  │             │  │                         │ │
│  │ ·서버 정보  │  │ ·설정 검증  │  │ ·SSH 접속 시 자동 참조  │ │
│  │ ·DB 설정   │  │ ·의존관계   │  │ ·DB 연결 시 프로필 로드 │ │
│  │ ·서비스 설정│  │  분석      │  │ ·배포 시 런북 실행      │ │
│  │ ·API 키    │  │ ·변경 추적  │  │ ·클라우드 API 인증      │ │
│  │ ·인증서    │  │ ·만료 감지  │  │ ·헬스체크 설정 적용     │ │
│  │ ·배포 설정  │  │ ·스키마 비교│  │ ·알림 채널 라우팅       │ │
│  │ ·환경 변수  │  │ ·보안 감사  │  │ ·인시던트 컨텍스트      │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Vault (암호화)  │  FTS5 검색  │  버전 이력  │  [[링크]] │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

#### 11.6.0 위키 리포지토리 3대 핵심 역할

**역할 1: 설정 정보 저장소 (Store)**

세션에서 수집·입력된 모든 설정 정보를 구조화하여 저장합니다. 단순 텍스트가 아니라 `structured_data` JSON 필드를 통해 프로그래밍적으로 접근 가능한 형태로 보관합니다.

```python
# 예: 서버 등록 시 자동 저장되는 structured_data
{
    "host": "10.0.1.13",
    "port": 22,
    "user": "deploy",
    "os": "Ubuntu 22.04.3 LTS",
    "services": ["nginx", "postgresql", "redis"],
    "cpu_cores": 4,
    "memory_gb": 16,
    "disk_gb": 100,
    "network": {"private_ip": "10.0.1.13", "public_ip": "203.0.113.13"},
    "tags": ["production", "web"],
}
```

**역할 2: 분석 엔진 (Analyze)**

저장된 설정 정보를 기반으로 의존관계 분석, 변경 추적, 만료 감지, 보안 검증을 수행합니다.

```python
# ServiceRegistry.resolve()가 Wiki를 참조하여 서비스 컨텍스트를 조합
resolve("database:production")
→ {
    "config": {"type": "postgresql", "host": "10.0.1.10", ...},  # secrets에서
    "wiki_pages": [                                                # Wiki에서
        {"page_id": "db-production", "name": "DB: production"},
        {"page_id": "deploy-api", "name": "배포 런북: API"},      # 의존하는 서비스 문서
    ],
    "credentials": ["password"],      # Vault 키 목록
    "health_status": "healthy",       # 헬스체크 결과
    "last_backup": "2026-08-13T02:00", # 자동화 기록
}
```

**역할 3: 실 서비스 연동 허브 (Connect)**

에이전트가 실제 서비스에 접근할 때 Wiki 리포지토리를 참조하여 필요한 정보를 자동으로 가져옵니다.

```python
# 에이전트가 "prod DB 상태 확인해줘" 요청 시:
# 1. Wiki에서 DB 설정 정보 조회
page = wiki_store.get_page("db-production")
config = page["structured_data"]  # host, port, database, user

# 2. Vault에서 비밀번호 로드
password = vault.retrieve("db-production:password")

# 3. 실제 DB 연결 및 상태 확인
status = db_tools.db_status(config, password)

# 4. Wiki 페이지에 최신 상태 기록
wiki_store.update_page("db-production", 
    structured_data={**config, "last_check": now, "status": status})
```

#### 11.6.0.1 세션 → 위키 자동 동기화 메커니즘

세션에서 도구를 실행할 때마다 관련 Wiki 페이지가 자동으로 업데이트되는 구조입니다.

```python
# 새 모듈: coworker/wiki/sync.py (확장)

class WikiAutoSync:
    """도구 실행 결과를 Wiki에 자동 동기화"""
    
    def __init__(self, wiki_store: WikiStore, vault: Vault):
        self._wiki = wiki_store
        self._vault = vault
        # 도구명 → 동기화 핸들러 매핑
        self._handlers = {
            "ssh_server_status": self._sync_server_status,
            "ssh_execute": self._sync_server_activity,
            "db_query": self._sync_db_activity,
            "db_status": self._sync_db_status,
            "docker_ps": self._sync_docker_status,
            "k8s_pods": self._sync_k8s_status,
            "aws_ec2_list": self._sync_cloud_inventory,
        }
    
    async def on_tool_result(self, tool_name: str, args: dict, result: dict):
        """TurnEngine에서 도구 실행 후 호출"""
        handler = self._handlers.get(tool_name)
        if handler and result.get("ok"):
            await handler(args, result)
    
    async def _sync_server_status(self, args: dict, result: dict):
        """SSH 서버 상태 → Wiki 자동 업데이트"""
        server_id = args.get("server")
        page_id = f"server-{server_id}"
        page = self._wiki.get_page(page_id)
        if page:
            sd = page.get("structured_data", {})
            sd.update({
                "last_check": time.time(),
                "cpu_percent": result.get("cpu_percent"),
                "memory_percent": result.get("memory", {}).get("percent"),
                "disk_percent": result.get("disk_root", {}).get("percent"),
                "uptime": result.get("uptime"),
                "status": "healthy" if result.get("cpu_percent", 0) < 90 else "warning",
            })
            self._wiki.update_page(page_id, structured_data=sd)
    
    async def _sync_db_status(self, args: dict, result: dict):
        """DB 상태 → Wiki 자동 업데이트"""
        db_name = args.get("database")
        page_id = f"db-{db_name}"
        page = self._wiki.get_page(page_id)
        if page:
            sd = page.get("structured_data", {})
            sd.update({
                "last_check": time.time(),
                "version": result.get("version"),
                "connections": result.get("active_connections"),
                "database_size": result.get("database_size"),
                "status": "healthy",
            })
            self._wiki.update_page(page_id, structured_data=sd)
```

#### 11.6.0.2 Wiki 기반 서비스 자동 연결

에이전트가 자연어로 서비스를 언급하면 Wiki에서 자동으로 설정을 찾아 연결합니다.

```python
# 새 모듈: coworker/wiki/resolver.py

class ServiceResolver:
    """자연어 서비스 참조를 Wiki 기반으로 자동 해석"""
    
    def resolve_natural(self, query: str) -> dict:
        """
        "production DB" → database:production Wiki 페이지 + 설정 + 자격증명
        "web-03 서버"   → server-web-03 Wiki 페이지 + SSH 프로필
        "API 서비스"    → svc-prod-api Wiki 페이지 + 서비스 설정
        """
        # 1. FTS5 검색으로 관련 페이지 찾기
        pages = self._wiki.search_fts(query)
        
        # 2. linked_service로 실제 설정 연결
        for page in pages:
            linked = page.get("linked_service", "")
            if linked:
                config = self._secrets.get(linked)
                if config:
                    return {
                        "page": page,
                        "config": config,
                        "credentials": self._vault.list_keys(page["page_id"]),
                    }
        
        return {"page": pages[0] if pages else None, "config": None}
    
    def get_connection_context(self, page_id: str) -> dict:
        """Wiki 페이지에서 서비스 연결에 필요한 모든 정보를 추출"""
        page = self._wiki.get_page(page_id)
        if not page:
            return {"ok": False}
        
        context = {
            "page": page,
            "structured_data": page.get("structured_data", {}),
            "linked_service": page.get("linked_service", ""),
            "credentials": {},
            "related_pages": [],
            "runbooks": [],
        }
        
        # Vault에서 자격증명 키 목록
        for cred in page.get("credentials", []):
            context["credentials"][cred["key"]] = {
                "type": cred.get("type"),
                "expires_at": cred.get("expires_at"),
                "vault_key": f"{page_id}:{cred['key']}",
            }
        
        # 관련 페이지 (같은 linked_service 또는 의존관계)
        if page.get("linked_service"):
            all_pages = self._wiki.list_pages()
            for p in all_pages:
                if p.get("linked_service") == page["linked_service"] and p["page_id"] != page_id:
                    context["related_pages"].append(p)
                if p.get("category") == "runbook":
                    sd = p.get("structured_data", {})
                    if page.get("linked_service") in str(sd):
                        context["runbooks"].append(p)
        
        return {"ok": True, **context}
```

#### 11.6.1 현재 Wiki 구조 분석

현재 `WikiStore`는 이미 강력한 기반을 가지고 있습니다:
- **카테고리**: model, prompt, runbook, service, database, server, cloud, api_doc, benchmark, architecture
- **FTS5 전문 검색**: 한국어/CJK LIKE 폴백 포함
- **버전 이력**: 모든 변경 자동 기록
- **자격증명**: Vault 연동 (키만 Wiki, 값은 암호화)
- **위키 링크**: `[[페이지명]]` 내부 링크 지원
- **런북 실행 추적**: `wiki_runbook_executions` 테이블

#### 11.6.2 Wiki 확장 도구

**확장 대상**: `coworker/wiki/tools.py`

```python
# 기존 wiki_tools()에 추가할 새 도구들

# 1. Wiki 페이지 생성 (카테고리별 템플릿 기반)
def wiki_create(
    name: str,
    category: str,
    content: str = "",
    linked_service: str = "",
    tags: list[str] = [],
    credentials: list[dict] = [],
    use_template: bool = True,
) -> dict:
    """카테고리 템플릿 기반 Wiki 페이지 생성"""
    page_id = f"{category}-{_slugify(name)}"
    
    if use_template and not content:
        template = WIKI_TEMPLATES.get(category, WIKI_TEMPLATES["service"])
        content = template["content"].replace("{{" + category + "_name}}", name)
        structured_data = template.get("structured_data", {})
    else:
        structured_data = {}
    
    # 자격증명은 Vault에 저장
    for cred in credentials:
        if "value" in cred:
            vault.store(f"{page_id}:{cred['key']}", cred.pop("value"))
    
    return wiki_store.create_page(
        page_id=page_id, name=name, category=category,
        content=content, credentials=credentials,
        linked_service=linked_service, tags=tags,
        structured_data=structured_data,
    )

# 2. Wiki 페이지 삭제 (소프트 삭제)
def wiki_delete(page_id: str) -> dict:
    """Wiki 페이지 소프트 삭제"""
    return wiki_store.delete_page(page_id)

# 3. Wiki 이력 조회
def wiki_history(page_id: str) -> dict:
    """페이지 변경 이력 조회"""
    history = wiki_store.get_history(page_id)
    return {"ok": True, "page_id": page_id, "history": history}

# 4. Wiki 카테고리 목록
def wiki_categories() -> dict:
    """카테고리별 페이지 수 조회"""
    return {"ok": True, "categories": wiki_store.categories()}

# 5. Wiki 최근 변경
def wiki_recent(limit: int = 20) -> dict:
    """최근 수정된 페이지 목록"""
    return {"ok": True, "pages": wiki_store.recent(limit)}

# 6. Wiki 내보내기/가져오기
def wiki_export(format: str = "json") -> dict:
    """전체 Wiki 내보내기"""
    pages = wiki_store.export_all()
    return {"ok": True, "format": format, "count": len(pages), "pages": pages}

def wiki_import(data: str) -> dict:
    """Wiki 데이터 가져오기 (JSON)"""
    import json
    pages = json.loads(data)
    return wiki_store.import_pages(pages)

# 7. 런북 실행 도구
def wiki_run_runbook(page_id: str) -> dict:
    """런북 페이지의 단계별 실행 시작"""
    page = wiki_store.get_page(page_id)
    if not page or page.get("category") != "runbook":
        return {"ok": False, "error": "런북 페이지가 아닙니다"}
    
    steps = page.get("structured_data", {}).get("steps", [])
    execution_id = str(uuid.uuid4())[:8]
    
    wiki_store.record_runbook_execution(
        execution_id=execution_id,
        page_id=page_id,
        steps_total=len(steps),
    )
    
    return {
        "ok": True,
        "execution_id": execution_id,
        "steps": steps,
        "instruction": "각 단계를 순서대로 실행하고 update_runbook_execution으로 진행상황을 기록하세요.",
    }

# 8. 자격증명 추가/갱신
def wiki_set_credential(
    page_id: str,
    key: str,
    value: str,
    credential_type: str = "password",  # "password", "token", "api_key", "ssh_key"
    expires_at: str = "",               # ISO datetime
) -> dict:
    """자격증명을 Vault에 저장하고 Wiki 메타데이터 업데이트"""
    vault.store(f"{page_id}:{key}", value)
    
    # Wiki 자격증명 메타데이터 업데이트
    page = wiki_store.get_page(page_id)
    if page:
        creds = page.get("credentials", [])
        # 기존 키 업데이트 또는 추가
        found = False
        for c in creds:
            if c.get("key") == key:
                c["type"] = credential_type
                c["updated_at"] = time.time()
                if expires_at:
                    c["expires_at"] = expires_at
                found = True
                break
        if not found:
            creds.append({
                "key": key,
                "type": credential_type,
                "updated_at": time.time(),
                **({"expires_at": expires_at} if expires_at else {}),
            })
        wiki_store.update_page(page_id, credentials=creds, change_note=f"자격증명 '{key}' 갱신")
    
    # 만료 알림 설정
    if expires_at:
        wiki_store.add_alert(page_id, key, "expiring", expires_at)
    
    return {"ok": True, "page_id": page_id, "key": key}
```

#### 11.6.3 Wiki 카테고리 확장

기존 `WIKI_TEMPLATES`에 추가할 새 카테고리:

```python
WIKI_TEMPLATES_EXTENDED = {
    # 기존 카테고리 유지: model, prompt, runbook, service, database, server, cloud, api_doc, benchmark, architecture
    
    "development": {
        "name": "Development Environment",
        "content": "# {{project_name}}\n\n## 기술 스택\n\n## 개발 환경 설정\n\n## 빌드 & 테스트\n\n## 배포\n\n## 메모\n",
        "structured_data": {"repo_url": "", "language": "", "framework": "", "ci": ""},
    },
    "config": {
        "name": "Configuration File",
        "content": "# {{config_name}}\n\n## 설정 내용\n\n```\n{{config_content}}\n```\n\n## 변경 이력\n",
        "structured_data": {"config_type": "", "service": "", "server": ""},
    },
    "incident": {
        "name": "Incident Report",
        "content": "# 인시던트: {{title}}\n\n## 요약\n\n## 영향 범위\n\n## 타임라인\n\n## 근본 원인\n\n## 조치 내역\n\n## 재발 방지\n",
        "structured_data": {"severity": "", "status": "", "affected_services": [], "rca": ""},
    },
    "onboarding": {
        "name": "Onboarding Checklist",
        "content": "# 온보딩: {{service_name}}\n\n## 사전 요구사항\n\n## 설정 단계\n\n- [ ] 1단계\n- [ ] 2단계\n\n## 검증\n\n## 문제 해결\n",
        "structured_data": {"steps": [], "prerequisites": []},
    },
    "network": {
        "name": "Network Configuration",
        "content": "# 네트워크: {{network_name}}\n\n## 구성\n- CIDR: \n- Gateway: \n- DNS: \n\n## 방화벽 규칙\n\n## VPN\n\n## 메모\n",
        "structured_data": {"cidr": "", "gateway": "", "dns": [], "firewall_rules": []},
    },
    "backup": {
        "name": "Backup Configuration",
        "content": "# 백업: {{target_name}}\n\n## 대상\n\n## 스케줄\n\n## 보관 정책\n\n## 복원 절차\n\n## 마지막 검증\n",
        "structured_data": {"schedule": "", "retention_days": 0, "target": "", "method": ""},
    },
}
```

### 11.7 세션-위키-서비스 통합 흐름

#### 11.7.1 전체 통합 아키텍처

```
┌───────────────────────────────────────────────────────────────────┐
│                        세션 (Session)                             │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  사용자: "웹서버를 등록하고 Nginx 설정을 만들어줘"           │ │
│  └─────────────┬───────────────────────────────────────────────┘ │
│                │                                                  │
│  ┌─────────────▼───────────────────────────────────────────────┐ │
│  │  Ops/SRE 에이전트                                          │ │
│  │  1. register_server() → SSH 연결 테스트 → Wiki 자동 생성    │ │
│  │  2. register_service() → 헬스체크 등록 → Wiki 자동 생성     │ │
│  │  3. generate_web_config() → Nginx 설정 → Wiki에 저장        │ │
│  │  4. generate_systemd_unit() → systemd 유닛 → Wiki에 저장    │ │
│  │  5. setup_deployment() → 배포 런북 → Wiki에 저장            │ │
│  └─────────────┬───────────────────────────────────────────────┘ │
│                │                                                  │
├────────────────┼──────────────────────────────────────────────────┤
│                ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              서비스 레지스트리 (ServiceRegistry)              │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │ │
│  │  │SSH 서버  │  │DB 프로필 │  │클라우드   │  │서비스    │   │ │
│  │  │accounts  │  │secrets   │  │providers │  │profiles  │   │ │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │ │
│  │       │             │             │             │           │ │
│  │       └─────────────┴─────────────┴─────────────┘           │ │
│  │                          │                                   │ │
│  └──────────────────────────┼───────────────────────────────────┘ │
│                             ▼                                     │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Wiki Store (SQLite)                       │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────────┐  │ │
│  │  │ server  │ │database │ │ service │ │ config/runbook  │  │ │
│  │  │ pages   │ │ pages   │ │ pages   │ │ pages           │  │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────────────┘  │ │
│  │  ┌─────────────────────┐  ┌─────────────────────────────┐  │ │
│  │  │  Version History    │  │  Vault (암호화 자격증명)     │  │ │
│  │  └─────────────────────┘  └─────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

#### 11.7.2 사용 시나리오

**시나리오 1: 새 서버 온보딩**
```
사용자: "web-03 서버를 등록해줘. IP는 10.0.1.13이고 deploy 계정으로 접속해"

에이전트 실행 흐름:
1. register_server("web-03", "10.0.1.13", username="deploy")
   → SSH 연결 테스트 ✓
   → 서버 정보 자동 수집 (OS, CPU, 메모리, 디스크, 실행 서비스)
   → Wiki 페이지 "server-web-03" 자동 생성
   
2. 에이전트 보고:
   "web-03 서버를 등록했습니다.
    - Ubuntu 22.04, 4코어 CPU, 16GB RAM, 100GB 디스크
    - 실행 서비스: nginx, postgresql, redis
    - Wiki 페이지: server-web-03"
```

**시나리오 2: 서비스 전체 구성**
```
사용자: "production API 서비스를 구성해줘. web-03 서버에 FastAPI 앱이 8000 포트로 돌아가고, 
        Nginx 리버스 프록시가 필요해. DB는 이미 등록된 prod-db를 사용해"

에이전트 실행 흐름:
1. register_service("prod-api", "Production API", "api", server_id="web-03", port=8000)
   → 헬스체크 자동 등록 (http://10.0.1.13:8000/health)
   → Wiki 페이지 "svc-prod-api" 자동 생성
   → 의존관계 매핑: database:prod-db

2. generate_web_config("prod-api", "api.example.com", 8000, ssl=True)
   → Nginx 설정 자동 생성
   → Wiki 페이지 "config-prod-api-nginx" 생성

3. generate_systemd_unit("prod-api", "uvicorn main:app --port 8000", 
                          working_directory="/opt/api", user="deploy")
   → systemd 유닛 파일 생성
   → Wiki 페이지 "config-prod-api-systemd" 생성

4. setup_deployment("prod-api", "web-03", "/opt/api", "git_pull",
                     post_deploy="systemctl restart prod-api")
   → 배포 런북 "deploy-prod-api" 생성

5. 에이전트 보고:
   "Production API 서비스 구성을 완료했습니다.
    생성된 문서:
    - 서비스: svc-prod-api
    - Nginx 설정: config-prod-api-nginx
    - systemd 유닛: config-prod-api-systemd
    - 배포 런북: deploy-prod-api
    
    다음 단계:
    1. Nginx 설정을 서버에 배포 (ssh_execute 승인 필요)
    2. SSL 인증서 설정
    3. 배포 테스트"
```

**시나리오 3: DB 등록 및 문서화**
```
사용자: "production PostgreSQL DB를 등록해줘"

에이전트 실행 흐름:
1. register_database("prod-db", "postgresql", host="10.0.1.10", port=5432,
                      database="myapp", user="app", password="...")
   → 연결 테스트 ✓
   → 스키마 자동 수집 (32개 테이블)
   → ERD 다이어그램 생성
   → Wiki 페이지 "db-prod-db" 자동 생성
   → Vault에 비밀번호 저장

2. setup_backup_schedule("prod-db", "0 2 * * *", "/backup/postgresql/", 
                          notify_channel="slack:ops")
   → 자동화 백업 작업 생성
   → Wiki에 백업 정보 기록
```

### 11.8 카탈로그 및 에이전트 통합

#### 11.8.1 새 Capability 등록

```python
# catalog.py 에 추가
_CAPS_SESSION_MGMT = [
    Capability(
        id="server_setup",
        name="Server onboarding",
        description="Register servers with connection testing and auto Wiki documentation.",
        build=_server_setup,
        requires=("secrets",),
        risk=(RiskClass.EXEC, RiskClass.EXTERNAL),
    ),
    Capability(
        id="dev_setup",
        name="Development environment",
        description="Scan projects, manage Git integration, env templates, and deployment configs.",
        build=_dev_setup,
        requires=("workspace", "secrets"),
        risk=(RiskClass.READ, RiskClass.WRITE_LOCAL),
    ),
    Capability(
        id="db_setup",
        name="Database setup",
        description="Register databases with connection testing, schema docs, and backup scheduling.",
        build=_db_setup,
        requires=("secrets",),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="service_config",
        name="Service configuration",
        description="Register services, manage configs (nginx/systemd/compose), and dependency mapping.",
        build=_service_config,
        requires=("secrets",),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="wiki_extended",
        name="Extended Wiki management",
        description="Create, delete, version, export/import Wiki pages with template support.",
        build=_wiki_extended,
        requires=("secrets",),
        risk=(RiskClass.READ, RiskClass.WRITE_LOCAL),
    ),
]
```

#### 11.8.2 SRE 에이전트 확장

```python
# agents/sre.py 확장
SRE_CAPABILITIES = [
    *OPS_CAPABILITIES,
    # 기존 모니터링 확장
    "monitoring", "incidents", "security_scan", "iac", "cert_mgmt", "network_diag",
    # 세션 기반 구성 관리 (신규)
    "server_setup",      # 서버 온보딩
    "dev_setup",         # 개발 환경 구성
    "db_setup",          # DB 프로필 구성
    "service_config",    # 서비스 설정 관리
    "wiki_extended",     # Wiki 고급 관리
    "ci_cd",             # CI/CD 파이프라인
]
```

### 11.9 REST API 엔드포인트

`server/app.py`에 추가할 관리 API:

```python
# 서비스 레지스트리 API
GET  /v1/services                     # 모든 서비스 목록
GET  /v1/services/{ref}               # 서비스 상세
POST /v1/services                     # 서비스 등록
PUT  /v1/services/{ref}               # 서비스 업데이트

# Wiki 관리 API  
GET  /v1/wiki/pages                   # 페이지 목록 (카테고리/태그 필터)
GET  /v1/wiki/pages/{page_id}         # 페이지 상세
POST /v1/wiki/pages                   # 페이지 생성
PUT  /v1/wiki/pages/{page_id}         # 페이지 업데이트
DELETE /v1/wiki/pages/{page_id}       # 페이지 삭제 (소프트)
GET  /v1/wiki/pages/{page_id}/history # 변경 이력
GET  /v1/wiki/categories              # 카테고리 목록
GET  /v1/wiki/recent                  # 최근 변경
GET  /v1/wiki/search?q=...            # 전문 검색
POST /v1/wiki/export                  # 내보내기
POST /v1/wiki/import                  # 가져오기

# 인프라 토폴로지 API
GET  /v1/infrastructure/topology      # 서비스 의존관계 맵
GET  /v1/infrastructure/servers       # 서버 목록 + 상태
GET  /v1/infrastructure/databases     # DB 목록 + 상태

# 설정 관리 API
GET  /v1/configs/{service_id}         # 서비스 설정 파일 목록
GET  /v1/configs/{service_id}/{type}  # 특정 설정 파일
PUT  /v1/configs/{service_id}/{type}  # 설정 업데이트
GET  /v1/configs/{service_id}/{type}/history  # 설정 변경 이력
POST /v1/configs/{service_id}/{type}/deploy   # 서버에 배포 (승인 필요)
```

---

## 12. 요약

### 현재 → 확장 비교

| 영역 | 현재 | 확장 후 |
|------|------|--------|
| **모니터링** | 로컬 + SSH 단건 조회 | 멀티 서버 자동 수집 + 시계열 |
| **알림** | 없음 | 규칙 기반 + 에스컬레이션 + 자동 복구 |
| **인시던트** | 에이전트 대화로 처리 | 구조화된 관리 + 타임라인 + 사후분석 |
| **대시보드** | WebSocket 이벤트만 | REST/WS 대시보드 API |
| **클라우드** | AWS/Cloudflare/Wasabi | + GCP + Azure |
| **보안** | 도구 권한만 | 포트 스캔 + 취약점 + 감사 |
| **자동화** | cron 작업 | + 조건부 자동 복구 + IaC |
| **서비스 위키** | 문서 저장만 | **설정 리포지토리** (저장·분석·연동) |
| **서버 구성** | SSH 수동 등록 | 온보딩 워크플로우 + Wiki 자동 생성 |
| **DB 관리** | 쿼리 실행만 | 프로필 등록 + 스키마 문서화 + 백업 자동화 |
| **개발 환경** | 없음 | 프로젝트 스캔 + Git 연동 + 배포 런북 |
| **서비스 설정** | 없음 | Nginx/systemd/Compose 생성 + 버전 관리 |

### 핵심 설계 원칙

1. **기존 패턴 준수**: `_attach()` / `_meta()` / `_schema()` 도구 정의 패턴 유지
2. **카탈로그 확장**: 새 기능은 `Capability`로 등록, Ops/SRE 에이전트가 활용
3. **스케줄러 활용**: 수집·헬스체크·알림은 기존 `Scheduler.extra_tick`에 통합
4. **커넥터 재사용**: 알림 발송은 기존 Slack/Telegram 어댑터 활용
5. **Wiki = 설정 리포지토리**: 모든 설정 정보의 중앙 저장소이자 서비스 연동 허브
6. **세션 → Wiki 자동 동기화**: 도구 실행 결과가 Wiki에 자동 반영
7. **Inbox 활용**: 위험한 작업은 Inbox 승인 후 실행
8. **점진적 확장**: Phase 1(기반) → Phase 4(멀티 클라우드)까지 단계적 구현

### 서비스 위키 리포지토리 핵심 요약

```
세션에서 입력/수집 → Wiki에 구조화 저장 → 서비스 연동 시 자동 참조
      │                    │                       │
      │                    │                       ├─ SSH 접속: Wiki에서 호스트/포트/키 로드
      │                    │                       ├─ DB 연결: Wiki에서 설정 + Vault에서 비밀번호
      │                    │                       ├─ 배포: Wiki 런북 단계별 실행
      │                    │                       ├─ 인시던트: Wiki에서 영향 서비스 자동 매핑
      │                    │                       └─ 모니터링: Wiki에서 헬스체크 대상 로드
      │                    │
      │                    ├─ structured_data: 프로그래밍 접근 가능한 JSON
      │                    ├─ credentials: Vault 암호화 연동
      │                    ├─ linked_service: ServiceRegistry 자동 연결
      │                    ├─ version_history: 모든 변경 추적
      │                    └─ FTS5: 자연어 검색 + [[위키링크]]
      │
      ├─ register_server() → server Wiki 자동 생성
      ├─ register_database() → database Wiki 자동 생성
      ├─ register_service() → service Wiki 자동 생성
      ├─ 도구 실행 → WikiAutoSync가 상태 자동 업데이트
      └─ AI 분석 → wiki_analyze()로 자격증명 자동 추출
```

---

## 13. 설계 보완 사항

### 13.1 에러 처리 및 복구 전략
- 각 모듈별 에러 처리 패턴 (SSH 연결 실패, DB 타임아웃, 클라우드 API 한도 초과 등)
- 재시도 정책 (exponential backoff, max_retries)
- 회로 차단기(circuit breaker) 패턴 적용 방안
- 부분 실패 처리 (멀티 서버 수집 중 일부 서버 실패 시)

### 13.2 성능 및 확장성
- SQLite 동시 쓰기 제한 해결 (WAL 모드 + connection pooling)
- 대규모 서버 관리 시 병렬 수집 전략 (asyncio semaphore)
- 메트릭 다운샘플링 배치 처리 주기 및 잠금 전략
- Wiki FTS5 인덱스 성능 (대량 페이지 시)
- WebSocket 대시보드 스트리밍 시 메모리 관리

### 13.3 테스트 전략
- 단위 테스트: 각 신규 모듈별 테스트 파일 매핑
- 통합 테스트: SSH mock, DB mock, Cloud API mock 전략
- E2E 테스트: 시나리오별 (서버 온보딩, 인시던트 흐름, 알림 파이프라인)
- 테스트 데이터: fixtures 설계
- 기존 테스트 패턴 참조: tests/test_cloud_infra.py, tests/test_server_monitor.py, tests/test_ssh_connector.py 등 이미 있음

### 13.4 마이그레이션 계획
- 기존 MetricsStore (server_monitor.py) → 새 timeseries.py 데이터 마이그레이션
- 기존 HealthChecker → 새 HealthCheckManager 전환
- catalog.py 확장 시 하위 호환성 보장
- WikiStore 스키마 마이그레이션 (ALTER TABLE 패턴 이미 사용 중)
- 기존 Ops 에이전트 → SRE 에이전트 전환 (ops.md 페르소나 유지)

### 13.5 의존성 관리
- 신규 Python 패키지: 없음 (기존 의존성만 사용 - boto3, httpx, psutil)
- GCP 확장 시: google-cloud-compute (선택적 의존성)
- Azure 확장 시: azure-mgmt-compute (선택적 의존성)
- pyproject.toml optional-dependencies 그룹 추가 계획

### 13.6 설정 체계 확장
- config.toml에 monitoring 섹션 추가 계획
```toml
[monitoring]
collect_interval = 60
retention_days = 90
alert_cooldown = 300

[monitoring.healthcheck]
default_interval = 60
default_timeout = 10
default_retries = 3

[monitoring.alerting]
default_channels = ["slack:ops"]
escalation_enabled = true
```

### 13.7 로깅 및 관측성
- 각 모듈별 logging.getLogger(__name__) 패턴 (프로젝트 기존 패턴)
- 운영 감사 로그(OpsAuditStore)와 Python logging 분리
- 구조화된 로그 포맷 (JSON, context 포함)

## 14. 개발팀 작업 분배표

### 14.1 Phase 1 작업 분배

| 작업 ID | 파일 | 담당 | 의존성 | 완료 기준 |
|---------|------|------|--------|----------|
| P1-01 | `monitoring/__init__.py` | 백엔드-1 | 없음 | 패키지 초기화 |
| P1-02 | `monitoring/timeseries.py` | 백엔드-1 | 없음 | TimeSeriesStore 클래스 + 다운샘플링 + 보관 정책 + 테스트 |
| P1-03 | `monitoring/collector.py` | 백엔드-1 | P1-02 | MetricCollector 클래스 + SSH 병렬 수집 + 테스트 |
| P1-04 | `monitoring/healthcheck.py` | 백엔드-2 | P1-02 | HealthCheckManager + 8개 체크 유형 + 테스트 |
| P1-05 | `monitoring/alerting.py` | 백엔드-2 | P1-03 | AlertEngine + 규칙 평가 + 커넥터 발송 + 테스트 |
| P1-06 | `tools/server_monitor.py` 확장 | 백엔드-2 | P1-02 | 원격 서버 지원 + network_stats + gpu_status |
| P1-07 | `server/dashboard_mixin.py` | UI 개발 | P1-02, P1-04, P1-05 | REST + WebSocket 대시보드 API |
| P1-08 | `catalog.py` 확장 | 개발팀장 | P1-03, P1-04, P1-05 | monitoring, incidents 등 신규 Capability 등록 |

### 14.2 Phase 2 작업 분배

| 작업 ID | 파일 | 담당 | 의존성 | 완료 기준 |
|---------|------|------|--------|----------|
| P2-01 | `monitoring/incidents.py` | 백엔드-1 | Phase 1 | IncidentManager + 타임라인 + 에스컬레이션 |
| P2-02 | `monitoring/remediation.py` | 백엔드-2 | P1-05 | RemediationEngine + 7개 기본 액션 + Inbox 연동 |
| P2-03 | `monitoring/log_aggregator.py` | 백엔드-1 | SSH | LogAggregator + 패턴 매칭 + 이상 탐지 |
| P2-04 | `agents/sre.py` | 개발팀장 | Phase 1 | SRE 에이전트 + 페르소나 manifest |
| P2-05 | `monitoring/audit_ops.py` | 백엔드-2 | 없음 | OpsAuditStore + TurnEngine hook 연동 |
| P2-06 | `tools/server_setup.py` | 백엔드-1 | Wiki | register_server + 온보딩 워크플로우 |
| P2-07 | `tools/service_config.py` | 백엔드-2 | Wiki | register_service + 설정 생성 |
| P2-08 | `tools/dev_setup.py` | 백엔드-1 | Wiki | 프로젝트 스캔 + Git 연동 |
| P2-09 | `wiki/sync.py` 확장 | 백엔드-2 | Wiki | WikiAutoSync + 도구 결과 동기화 |
| P2-10 | `wiki/resolver.py` | 백엔드-1 | Wiki | ServiceResolver + 자연어 해석 |
| P2-11 | `wiki/tools.py` 확장 | 백엔드-2 | Wiki | wiki_create, wiki_delete, wiki_history 등 |

### 14.3 Phase 3 작업 분배

| 작업 ID | 파일 | 담당 | 의존성 | 완료 기준 |
|---------|------|------|--------|----------|
| P3-01 | `tools/docker_mgmt.py` 확장 | 백엔드-2 | 없음 | docker_inspect, docker_networks, docker_volumes, docker_prune |
| P3-02 | `tools/k8s_mgmt.py` 확장 | 백엔드-1 | 없음 | k8s_nodes, k8s_top, k8s_ingress, k8s_hpa, k8s_contexts |
| P3-03 | `tools/cloud_infra.py` 확장 | 백엔드-1 | 없음 | aws_rds_status, aws_elb_status, aws_route53, aws_iam_audit |
| P3-04 | `tools/ci_cd.py` 확장 | 백엔드-2 | 없음 | ci_gitlab, deploy_history, deploy_canary |
| P3-05 | `tools/security_scan.py` | 백엔드-1 | SSH | port_scan, ssl_check, auth_log_analysis, vulnerability_check |
| P3-06 | `tools/network_diag.py` | 백엔드-2 | 없음 | traceroute, mtr, dns_propagation |
| P3-07 | `server/app.py` API 확장 | UI 개발 | P2-06~P2-11 | Wiki/서비스/인프라 REST API 엔드포인트 |

### 14.4 Phase 4 작업 분배

| 작업 ID | 파일 | 담당 | 의존성 | 완료 기준 |
|---------|------|------|--------|----------|
| P4-01 | `connectors/cloud/gcp.py` | 백엔드-1 | 없음 | GCP Compute/GKE 기본 연동 |
| P4-02 | `connectors/cloud/azure.py` | 백엔드-2 | 없음 | Azure VM/AKS 기본 연동 |
| P4-03 | `tools/iac.py` | 백엔드-1 | Executor | Terraform plan/state + Ansible playbook |
| P4-04 | `tools/cert_mgmt.py` | 백엔드-2 | SSH | SSL 인증서 모니터링 + 갱신 |
| P4-05 | `connectors/ssh/tunnel.py` | 백엔드-1 | SSH | SSH 터널링 지원 |

### 14.5 테스트 작업

| 테스트 파일 | 대상 모듈 | 담당 |
|------------|----------|------|
| `tests/test_timeseries.py` | monitoring/timeseries.py | 테스터 |
| `tests/test_collector.py` | monitoring/collector.py | 테스터 |
| `tests/test_healthcheck_mgr.py` | monitoring/healthcheck.py | 테스터 |
| `tests/test_alerting.py` | monitoring/alerting.py | 테스터 |
| `tests/test_incidents.py` | monitoring/incidents.py | 테스터 |
| `tests/test_remediation.py` | monitoring/remediation.py | 테스터 |
| `tests/test_wiki_sync.py` | wiki/sync.py | 테스터 |
| `tests/test_wiki_resolver.py` | wiki/resolver.py | 테스터 |
| `tests/test_server_setup.py` | tools/server_setup.py | 테스터 |
| `tests/test_service_config.py` | tools/service_config.py | 테스터 |
| `tests/test_dashboard_api.py` | server/dashboard_mixin.py | 테스터 |
| `tests/test_security_scan.py` | tools/security_scan.py | 테스터 |
