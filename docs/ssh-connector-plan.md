# SSH 터미널 접근 모듈 기획서

## 1. 개요

커넥터와 유사한 구조로 SSH를 통한 원격 서버 접근, 터미널 명령 실행, sudo 권한 관리를
지원하는 모듈을 구축합니다.

### 목표
- 등록된 서버에 SSH로 접근하여 명령 실행
- sudo 지원 (비밀번호 안전 관리)
- 서버 연결 정보를 커넥터와 동일한 `secrets.json`에 암호화 저장
- 승인 기반 실행 (위험 명령은 사용자 확인)
- 다중 서버 관리 (프로덕션/스테이징/개발)

---

## 2. 기존 커넥터 패턴 분석

### 커넥터 저장 구조 (secrets.json)

```json
{
  "slack:default": {
    "token": "xoxb-****",
    "managed": true,
    "account": "workspace-name"
  },
  "gmail:account:user@example.com": {
    "access_token": "ya29.****",
    "refresh_token": "1//****",
    "managed": true
  }
}
```

### SSH 모듈도 동일 패턴 적용

```json
{
  "ssh:server:web-01": {
    "host": "192.168.1.10",
    "port": 22,
    "username": "deploy",
    "auth_method": "key",
    "key_path": "~/.ssh/id_ed25519",
    "sudo_password": "****",
    "tags": ["web", "production"],
    "label": "웹 서버 01",
    "added_at": "2026-08-06"
  },
  "ssh:server:db-01": {
    "host": "192.168.1.20",
    "port": 22,
    "username": "admin",
    "auth_method": "key",
    "sudo_password": "****",
    "tags": ["database", "production"],
    "label": "DB 서버 01",
    "added_at": "2026-08-06"
  }
}
```

---

## 3. 모듈 구조

### 3.1 파일 레이아웃

```
coworker/
├── connectors/
│   ├── ssh/
│   │   ├── __init__.py          # SSH 커넥터 등록
│   │   ├── client.py            # SSHClient 래퍼 (paramiko)
│   │   ├── tools.py             # SSH 도구 함수 (에이전트용)
│   │   ├── accounts.py          # 서버 등록/조회/삭제
│   │   └── descriptor.py        # UI 필드 정의
│   └── ...
├── tools/
│   └── ssh_executor.py          # ShellExecutor의 SSH 변형

surfaces/gui/src/
├── components/
│   └── connectors/
│       └── SSHDetail.tsx         # SSH 서버 관리 UI
```

### 3.2 핵심 클래스

```python
# coworker/connectors/ssh/client.py

import paramiko
from dataclasses import dataclass
from typing import Optional

@dataclass
class SSHServer:
    """등록된 SSH 서버 정보"""
    server_id: str          # "web-01"
    host: str               # "192.168.1.10"
    port: int = 22
    username: str = "deploy"
    auth_method: str = "key"  # "key" | "password" | "agent"
    key_path: Optional[str] = None
    sudo_password: Optional[str] = None
    tags: list[str] = None
    label: str = ""

class SSHClient:
    """원격 서버 SSH 연결 관리"""
    
    def __init__(self, server: SSHServer):
        self.server = server
        self._client: Optional[paramiko.SSHClient] = None
    
    def connect(self) -> dict:
        """SSH 연결 수립"""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        connect_kwargs = {
            "hostname": self.server.host,
            "port": self.server.port,
            "username": self.server.username,
        }
        
        if self.server.auth_method == "key":
            if self.server.key_path:
                connect_kwargs["key_filename"] = os.path.expanduser(self.server.key_path)
            # else: SSH agent 자동 사용
        elif self.server.auth_method == "password":
            connect_kwargs["password"] = self.server.sudo_password
        # "agent": paramiko가 SSH agent 자동 탐색
        
        client.connect(**connect_kwargs)
        self._client = client
        return {"ok": True, "host": self.server.host}
    
    def execute(self, command: str, *, sudo: bool = False, timeout: int = 30) -> dict:
        """명령 실행 (sudo 지원)"""
        if not self._client:
            self.connect()
        
        if sudo:
            if not self.server.sudo_password:
                return {"error": "sudo 비밀번호가 설정되지 않았습니다"}
            command = f"echo '{self.server.sudo_password}' | sudo -S {command}"
        
        stdin, stdout, stderr = self._client.exec_command(
            command, timeout=timeout
        )
        
        exit_code = stdout.channel.recv_exit_status()
        return {
            "ok": exit_code == 0,
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
            "exit_code": exit_code,
            "host": self.server.host,
        }
    
    def close(self):
        if self._client:
            self._client.close()
            self._client = None
```

---

## 4. 에이전트 도구 (Tools)

### 4.1 도구 목록

```python
# coworker/connectors/ssh/tools.py

def ssh_list_servers() -> dict:
    """등록된 SSH 서버 목록 조회"""

def ssh_execute(server: str, command: str, sudo: bool = False, timeout: int = 30) -> dict:
    """원격 서버에서 명령 실행
    
    Args:
        server: 서버 ID (예: "web-01")
        command: 실행할 명령
        sudo: sudo 권한으로 실행 여부
        timeout: 타임아웃 (초)
    """

def ssh_upload_file(server: str, local_path: str, remote_path: str) -> dict:
    """로컬 파일을 원격 서버로 업로드 (SFTP)"""

def ssh_download_file(server: str, remote_path: str, local_path: str) -> dict:
    """원격 서버 파일을 로컬로 다운로드 (SFTP)"""

def ssh_read_file(server: str, path: str, max_lines: int = 200) -> dict:
    """원격 서버 파일 내용 읽기"""

def ssh_server_status(server: str) -> dict:
    """서버 기본 상태 조회 (uptime, CPU, 메모리, 디스크)"""

def ssh_service_status(server: str, service: str) -> dict:
    """시스템 서비스 상태 확인 (systemctl status)"""

def ssh_service_control(server: str, service: str, action: str) -> dict:
    """서비스 제어 (start/stop/restart) — sudo 필요, 승인 필수"""

def ssh_tail_log(server: str, log_path: str, lines: int = 50) -> dict:
    """원격 로그 파일 tail"""

def ssh_check_port(server: str, port: int) -> dict:
    """포트 접근성 검사"""
```

### 4.2 리스크 분류

| 도구 | 리스크 | 승인 필요 |
|------|--------|-----------|
| `ssh_list_servers` | LOW | 아니오 |
| `ssh_execute` (일반) | EXEC | **예** |
| `ssh_execute` (sudo) | EXEC + ELEVATED | **예 (강화)** |
| `ssh_server_status` | LOW | 아니오 |
| `ssh_read_file` | LOW | 아니오 |
| `ssh_service_status` | LOW | 아니오 |
| `ssh_service_control` | EXEC + ELEVATED | **예 (강화)** |
| `ssh_upload_file` | WRITE | **예** |
| `ssh_download_file` | READ | 아니오 |
| `ssh_tail_log` | LOW | 아니오 |
| `ssh_check_port` | LOW | 아니오 |

### 4.3 sudo 승인 강화

sudo 명령은 일반 승인 외에 추가 확인:

```
┌──────────────────────────────────────────────┐
│  🔐 sudo 권한 명령 실행 요청                  │
│                                              │
│  서버: web-01 (192.168.1.10)                 │
│  명령: systemctl restart nginx               │
│  권한: sudo (root)                           │
│                                              │
│  [허용]  [거부]  [항상 허용 (이 서버)]         │
└──────────────────────────────────────────────┘
```

---

## 5. 서버 등록 UI

### 5.1 Settings > Connectors > SSH

```
┌─ SSH 서버 관리 ─────────────────────────────┐
│                                              │
│  [+ 서버 추가]                                │
│                                              │
│  ┌─────────────────────────────────────────┐ │
│  │ ● web-01  웹 서버 01                    │ │
│  │   192.168.1.10  ·  deploy  ·  production│ │
│  │   [테스트]  [편집]  [삭제]                │ │
│  ├─────────────────────────────────────────┤ │
│  │ ● db-01   DB 서버 01                    │ │
│  │   192.168.1.20  ·  admin   ·  production│ │
│  │   [테스트]  [편집]  [삭제]                │ │
│  ├─────────────────────────────────────────┤ │
│  │ ○ staging  스테이징 서버                  │ │
│  │   staging.example.com · deploy · staging│ │
│  │   연결 실패: Connection refused          │ │
│  └─────────────────────────────────────────┘ │
│                                              │
└──────────────────────────────────────────────┘
```

### 5.2 서버 추가 폼

```
┌─ SSH 서버 추가 ─────────────────────────────┐
│                                              │
│  서버 ID:     [web-02               ]        │
│  라벨:        [웹 서버 02             ]       │
│  호스트:      [192.168.1.11          ]        │
│  포트:        [22                    ]        │
│  사용자:      [deploy                ]        │
│                                              │
│  인증 방식:                                   │
│    ● SSH 키 (기본)                            │
│      키 경로: [~/.ssh/id_ed25519   ]          │
│    ○ SSH 에이전트                              │
│    ○ 비밀번호                                 │
│                                              │
│  ☐ sudo 비밀번호 설정                         │
│    [••••••••••                     ]          │
│                                              │
│  태그:        [production, web      ]         │
│                                              │
│  [연결 테스트]              [저장]  [취소]     │
│                                              │
└──────────────────────────────────────────────┘
```

---

## 6. 보안 설계

### 6.1 비밀번호/키 보호

| 항목 | 방식 |
|------|------|
| SSH 키 | 사용자의 기존 SSH 키 참조 (경로만 저장, 키 자체 복사 안 함) |
| sudo 비밀번호 | `secrets.json`에 저장 (0600 퍼미션), UI에서 마스킹 |
| SSH 에이전트 | `paramiko.Agent()` 자동 탐색 |
| known_hosts | `~/.ssh/known_hosts` 활용 (AutoAddPolicy는 최초 연결 시만) |

### 6.2 명령 실행 제한

```python
# 금지 명령 패턴 (기본)
BLOCKED_COMMANDS = [
    r"rm\s+-rf\s+/[^/]",     # rm -rf / 방지
    r"mkfs\.",                 # 파일시스템 포맷
    r"dd\s+.*of=/dev/",       # 디스크 덮어쓰기
    r":(){ :\|:& };:",        # 포크 폭탄
    r">\s*/dev/sd",            # 디스크 직접 쓰기
]

# sudo 명령은 항상 승인 필요 (auto 모드에서도)
ALWAYS_APPROVE_SUDO = True
```

### 6.3 감사 로그

모든 SSH 명령은 audit_store에 기록:

```json
{
  "tool": "ssh_execute",
  "server": "web-01",
  "command": "systemctl restart nginx",
  "sudo": true,
  "exit_code": 0,
  "timestamp": "2026-08-06T14:30:00Z",
  "session_id": "abc123",
  "approved_by": "user"
}
```

---

## 7. Catalog 등록

```python
# catalog.py에 추가

Capability(
    id="ssh",
    name="SSH remote access",
    description="Execute commands on registered remote servers via SSH",
    build=lambda ctx: ssh_tools(ctx),
    requires=("executor",),
    risk=(RiskClass.EXEC, RiskClass.NETWORK),
),
```

### Ops 에이전트 연동

```python
# agents/ops.py
OPS_CAPABILITIES = [
    "files", "shell", "search", "todo",
    "ssh",              # SSH 원격 접근
    "server_monitor",   # 서버 모니터링
]
```

---

## 8. 커넥터 디스크립터

```python
# connectors/ssh/descriptor.py

SSH_DESCRIPTOR = ConnectorDescriptor(
    name="ssh",
    title="SSH 서버",
    category="infrastructure",
    needs_key=True,
    multi_account=True,  # 다중 서버 지원
    fields=[
        Field("host", "호스트", required=True, placeholder="192.168.1.10"),
        Field("port", "포트", required=False, default="22"),
        Field("username", "사용자", required=True, placeholder="deploy"),
        Field("auth_method", "인증 방식", choices=[
            {"value": "key", "label": "SSH 키"},
            {"value": "agent", "label": "SSH 에이전트"},
            {"value": "password", "label": "비밀번호"},
        ]),
        Field("key_path", "SSH 키 경로", required=False,
              placeholder="~/.ssh/id_ed25519",
              show_when={"auth_method": "key"}),
        Field("sudo_password", "sudo 비밀번호", secret=True, required=False),
        Field("tags", "태그", required=False, placeholder="production, web"),
        Field("label", "라벨", required=False, placeholder="웹 서버 01"),
    ],
    tools=[
        ToolDef("ssh_list_servers", "서버 목록", kind="read"),
        ToolDef("ssh_execute", "명령 실행", kind="write"),
        ToolDef("ssh_server_status", "서버 상태", kind="read"),
        ToolDef("ssh_service_status", "서비스 상태", kind="read"),
        ToolDef("ssh_service_control", "서비스 제어", kind="write"),
        ToolDef("ssh_read_file", "파일 읽기", kind="read"),
        ToolDef("ssh_upload_file", "파일 업로드", kind="write"),
        ToolDef("ssh_download_file", "파일 다운로드", kind="read"),
        ToolDef("ssh_tail_log", "로그 보기", kind="read"),
        ToolDef("ssh_check_port", "포트 검사", kind="read"),
    ],
)
```

---

## 9. 구현 로드맵

| Phase | 작업 | 예상 |
|-------|------|------|
| 1 | `paramiko` 설치, `ssh/client.py` 기본 구현 | 1일 |
| 2 | `ssh/tools.py` 도구 함수 10개 구현 | 1일 |
| 3 | `ssh/accounts.py` 서버 등록/조회/삭제 | 0.5일 |
| 4 | `ssh/descriptor.py` + `catalog.py` 등록 | 0.5일 |
| 5 | `SSHDetail.tsx` 서버 관리 UI | 1일 |
| 6 | sudo 승인 강화 + 감사 로그 | 0.5일 |
| 7 | Ops 에이전트 연동 + 테스트 | 1일 |

### 필요 패키지

```bash
pip install paramiko
```

(이미 `cryptography`는 설치되어 있으므로 추가 의존성 최소)

---

## 10. 사용 예시

### 에이전트 대화

```
사용자: web-01 서버의 nginx 상태 확인해줘

에이전트: web-01 서버 상태를 확인합니다.
  [ssh_server_status] web-01
    CPU: 45%  MEM: 62%  DISK: 38%  Uptime: 45d 3h
  
  [ssh_service_status] web-01, nginx
    nginx.service - A high performance web server
    Active: active (running) since Mon 2026-07-22 09:15:03 KST

  nginx가 정상 실행 중입니다.

사용자: nginx 재시작해줘

에이전트: 🔐 sudo 권한 명령을 실행합니다.
  서버: web-01 (192.168.1.10)
  명령: systemctl restart nginx
  [승인 필요]

사용자: [허용]

에이전트: [ssh_service_control] web-01, nginx, restart (sudo)
  ✓ nginx.service 재시작 완료
```

---

*작성일: 2026-08-06*
*프로젝트: OpenWorker SSH Connector Module*
