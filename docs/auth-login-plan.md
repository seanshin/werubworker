# WeruBWorker 로그인/인증 기능 계획

## 1. 개요

WeruBWorker에 저장된 민감 정보(API 키, SSH 자격증명, DB 비밀번호 등)를 보호하기 위해
로그인 인증 기능을 추가합니다.

---

## 2. 보호 대상

| 정보 | 저장 위치 | 위험도 |
|------|----------|--------|
| AI 모델 API 키 | secrets.json `provider:*` | 높음 |
| SSH 서버 비밀번호/키 | secrets.json `ssh:server:*` | 높음 |
| DB 접속 정보 | secrets.json `database:*` | 높음 |
| Slack/GitHub 토큰 | secrets.json `slack:*`, `github:*` | 중간 |
| AWS/Cloudflare 키 | secrets.json `aws:*`, `cloudflare:*` | 높음 |
| 대화 기록 | conversations/*.jsonl | 중간 |
| 자동화 설정 | automation.db | 낮음 |

---

## 3. 인증 모드

### 모드 A: 로컬 인증 (기본)
- 앱 자체 비밀번호 (마스터 패스워드)
- 추가 패키지 불필요
- 개인 사용자/소규모 팀용

### 모드 B: 기업 SSO (선택)
- Keycloak/LDAP/SAML/OIDC 연동
- WeruB Service(중앙 서버) 경유
- 대규모 팀/기업용

---

## 4. 로컬 인증 설계 (Mode A)

### 4.1 흐름

```
앱 시작
  ↓
[로그인 화면] ← 비밀번호 입력
  ↓
비밀번호 검증 (bcrypt hash 비교)
  ↓ 성공
[세션 토큰 발급] (JWT, 메모리 내)
  ↓
앱 사용 가능
  ↓ 일정 시간 미사용
[자동 잠금] → 비밀번호 재입력
```

### 4.2 백엔드 구현

```python
# coworker/auth.py

import hashlib
import secrets
import time
from pathlib import Path
from typing import Optional

class LocalAuth:
    """로컬 마스터 패스워드 인증"""
    
    def __init__(self, state_dir: Path):
        self._auth_file = state_dir / "auth.json"
        self._session_token: Optional[str] = None
        self._session_expires: float = 0
        self._lock_timeout = 30 * 60  # 30분 미사용 시 잠금
    
    @property
    def is_configured(self) -> bool:
        """비밀번호가 설정되었는지"""
        return self._auth_file.exists()
    
    def setup(self, password: str) -> dict:
        """최초 비밀번호 설정"""
        salt = secrets.token_hex(16)
        hashed = self._hash(password, salt)
        data = {"salt": salt, "hash": hashed, "created_at": time.time()}
        self._auth_file.write_text(json.dumps(data))
        self._auth_file.chmod(0o600)
        return {"ok": True}
    
    def login(self, password: str) -> dict:
        """비밀번호 검증 + 세션 토큰 발급"""
        if not self.is_configured:
            return {"ok": False, "error": "비밀번호가 설정되지 않았습니다"}
        
        data = json.loads(self._auth_file.read_text())
        if self._hash(password, data["salt"]) != data["hash"]:
            return {"ok": False, "error": "비밀번호가 일치하지 않습니다"}
        
        self._session_token = secrets.token_urlsafe(32)
        self._session_expires = time.time() + self._lock_timeout
        return {"ok": True, "token": self._session_token}
    
    def verify(self, token: str) -> bool:
        """세션 토큰 검증 + 만료 체크"""
        if not self._session_token or token != self._session_token:
            return False
        if time.time() > self._session_expires:
            self._session_token = None
            return False
        # 활동 시 만료 시간 연장
        self._session_expires = time.time() + self._lock_timeout
        return True
    
    def logout(self):
        """세션 종료"""
        self._session_token = None
        self._session_expires = 0
    
    def change_password(self, old_password: str, new_password: str) -> dict:
        """비밀번호 변경"""
        login_result = self.login(old_password)
        if not login_result["ok"]:
            return {"ok": False, "error": "기존 비밀번호가 일치하지 않습니다"}
        return self.setup(new_password)
    
    def _hash(self, password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            'sha256', password.encode(), salt.encode(), 100000
        ).hex()
```

### 4.3 API 엔드포인트

```python
# server/app.py에 추가

# 인증 불필요 엔드포인트 (로그인 전 접근 가능)
@app.post("/v1/auth/setup")
def auth_setup(body: dict):
    """최초 비밀번호 설정"""

@app.post("/v1/auth/login")
def auth_login(body: dict):
    """로그인"""

@app.get("/v1/auth/status")
def auth_status():
    """인증 상태 (설정됨/미설정, 로그인됨/잠김)"""

# 인증 필요 엔드포인트
@app.post("/v1/auth/logout")
def auth_logout():
    """로그아웃"""

@app.post("/v1/auth/change-password")
def auth_change_password(body: dict):
    """비밀번호 변경"""

@app.post("/v1/auth/lock-settings")
def auth_lock_settings(body: dict):
    """잠금 시간 변경"""
```

### 4.4 미들웨어 (기존 sidecar 토큰 + 인증 토큰)

```python
@app.middleware("http")
async def require_auth(request, call_next):
    # 인증 불필요 경로
    if request.url.path in {"/v1/auth/login", "/v1/auth/setup", "/v1/auth/status", "/v1/health"}:
        return await call_next(request)
    
    # 인증이 설정되지 않았으면 통과 (최초 사용)
    if not auth.is_configured:
        return await call_next(request)
    
    # 세션 토큰 검증
    auth_token = request.headers.get("x-werub-auth", "")
    if not auth.verify(auth_token):
        return JSONResponse({"error": "인증이 필요합니다"}, status_code=401)
    
    return await call_next(request)
```

### 4.5 GUI 구현

```
┌─────────────────────────────────────────┐
│                                         │
│         WeruBWorker                     │
│                                         │
│    ┌───────────────────────────┐        │
│    │                           │        │
│    │  🔒 비밀번호를 입력하세요   │        │
│    │                           │        │
│    │  [••••••••••••••       ]  │        │
│    │                           │        │
│    │  ☐ 30분간 유지             │        │
│    │                           │        │
│    │      [ 로그인 ]            │        │
│    │                           │        │
│    └───────────────────────────┘        │
│                                         │
│    비밀번호를 잊었다면 ~/.config/        │
│    werubworker/auth.json을 삭제하세요   │
│                                         │
└─────────────────────────────────────────┘
```

**최초 설정 화면:**
```
┌─────────────────────────────────────────┐
│                                         │
│         WeruBWorker 보안 설정            │
│                                         │
│    API 키와 서버 자격증명을 보호하기      │
│    위해 마스터 비밀번호를 설정하세요.     │
│                                         │
│    비밀번호:   [                    ]    │
│    확인:      [                    ]    │
│                                         │
│    ⚠ 이 비밀번호는 복구할 수 없습니다.   │
│       분실 시 auth.json 삭제 후         │
│       재설정해야 합니다.                 │
│                                         │
│           [ 설정 완료 ]                  │
│           [ 나중에 ]                     │
│                                         │
└─────────────────────────────────────────┘
```

### 4.6 설정 > 보안 탭

```
┌─ 보안 ────────────────────────────────┐
│                                        │
│  마스터 비밀번호                        │
│  ✓ 설정됨                              │
│  [비밀번호 변경]                        │
│                                        │
│  자동 잠금                              │
│  ● 30분 미사용 시                       │
│  ○ 1시간 미사용 시                      │
│  ○ 사용 안 함                           │
│                                        │
│  보호 범위                              │
│  ☑ API 키 및 토큰 (secrets.json)        │
│  ☑ SSH 서버 자격증명                    │
│  ☑ 데이터베이스 비밀번호                 │
│  ☐ 대화 기록 (conversations/)           │
│                                        │
│  세션                                   │
│  [지금 잠금]  [모든 기기에서 로그아웃]    │
│                                        │
└────────────────────────────────────────┘
```

---

## 5. 파일 구조

```
coworker/
├── auth.py                    # [신규] 인증 로직
├── server/
│   ├── app.py                 # [수정] 인증 미들웨어 + 엔드포인트
│   └── auth_mixin.py          # [신규] 인증 관련 Manager 메서드

surfaces/gui/src/
├── components/
│   ├── LoginView.tsx           # [신규] 로그인 화면
│   ├── PasswordSetup.tsx       # [신규] 최초 비밀번호 설정
│   └── SecuritySettings.tsx    # [신규] 보안 설정 탭
├── contexts/
│   └── AuthContext.tsx          # [신규] 인증 상태 관리
├── i18n/locales/
│   ├── en/auth.json            # [신규] 인증 번역 키
│   └── ko/auth.json            # [신규] 인증 번역 키
```

---

## 6. 데이터 저장

```
~/.config/werubworker/
├── auth.json          # 비밀번호 해시 (0600)
│   {
│     "salt": "random_hex",
│     "hash": "pbkdf2_sha256_hash",
│     "lock_timeout": 1800,
│     "created_at": 1723000000
│   }
├── secrets.json       # 기존 (인증 후 접근)
└── ...
```

---

## 7. 구현 로드맵

| # | 작업 | 예상 |
|---|------|------|
| 1 | `auth.py` 핵심 로직 (setup, login, verify) | 0.5일 |
| 2 | `server/app.py` 미들웨어 + 엔드포인트 | 0.5일 |
| 3 | `LoginView.tsx` 로그인 화면 | 0.5일 |
| 4 | `PasswordSetup.tsx` 최초 설정 | 0.5일 |
| 5 | `AuthContext.tsx` 인증 상태 관리 | 0.5일 |
| 6 | 설정 > 보안 탭 | 0.5일 |
| 7 | 번역 키 (auth.json en/ko) | 0.5일 |
| 8 | 자동 잠금 타이머 | 0.5일 |

---

*작성일: 2026-08-07*
*프로젝트: WeruBWorker 로그인/인증*
