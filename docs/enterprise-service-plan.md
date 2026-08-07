# WeruBWorker 기업 내부 서비스 구축 계획

## 1. 개요

OpenWorker Cloud를 제거하고, 기업 내부에 자체 서비스 인프라를 구축합니다.
주요 외부 SaaS 서비스와 직접 연동하여 독립적인 운영 환경을 확보합니다.

---

## 2. 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    기업 내부 네트워크                          │
│                                                              │
│  ┌──────────────┐    ┌──────────────────┐                   │
│  │ WeruBWorker  │    │ WeruB Service    │                   │
│  │ Desktop App  │───▶│ (자체 서버)       │                   │
│  │ (각 직원 PC) │    │ FastAPI + Redis  │                   │
│  └──────────────┘    └────────┬─────────┘                   │
│                               │                              │
│  ┌──────────────┐    ┌────────▼─────────┐                   │
│  │ Ollama       │    │ WeruB Auth       │                   │
│  │ AI Server    │    │ (Keycloak/자체)  │                   │
│  │ (GPU 서버)   │    │ LDAP/SSO 연동   │                   │
│  └──────────────┘    └──────────────────┘                   │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │ (외부 SaaS 연동)
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │  Slack   │    │  GitHub  │    │  Google  │
    │Enterprise│    │Enterprise│    │Workspace │
    └──────────┘    └──────────┘    └──────────┘
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │  Jira    │    │ Notion   │    │ HubSpot  │
    │  Cloud   │    │  API     │    │  CRM     │
    └──────────┘    └──────────┘    └──────────┘
```

---

## 3. 자체 서비스 구성요소

### 3.1 WeruB Service (중앙 서버)

OpenWorker Cloud를 대체하는 기업 내부 서버입니다.

```python
# werub-service/ (별도 프로젝트)

werub-service/
├── app/
│   ├── main.py              # FastAPI 앱
│   ├── auth/
│   │   ├── oauth_broker.py  # OAuth 중개 (Slack, Google 등)
│   │   ├── sso.py           # 기업 SSO (SAML/OIDC)
│   │   └── ldap.py          # LDAP/AD 연동
│   ├── connectors/
│   │   ├── slack_app.py     # Slack App 관리
│   │   ├── google_oauth.py  # Google OAuth 중개
│   │   └── github_app.py    # GitHub App 관리
│   ├── gallery/
│   │   ├── store.py         # 페르소나 갤러리 저장
│   │   └── api.py           # 갤러리 API
│   ├── relay/
│   │   ├── websocket.py     # WebSocket 릴레이
│   │   └── webhook.py       # Webhook 수신기
│   ├── update/
│   │   └── manifest.py      # 자동 업데이트 매니페스트
│   └── admin/
│       ├── dashboard.py     # 관리자 대시보드
│       └── audit.py         # 사용 감사 로그
├── config.yaml              # 서비스 설정
├── docker-compose.yml       # 배포 구성
└── requirements.txt
```

### 3.2 WeruB Auth (인증 서비스)

| 옵션 | 설명 | 추천 |
|------|------|------|
| **Keycloak** | 오픈소스 IAM, SAML/OIDC/LDAP 지원 | ✅ 기업용 추천 |
| **Authentik** | 경량 오픈소스 IdP | 중소규모 |
| **자체 구현** | FastAPI + JWT | 소규모 |

```yaml
# docker-compose.yml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:latest
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: ${KC_PASSWORD}
    ports:
      - "8080:8080"
    volumes:
      - keycloak_data:/opt/keycloak/data

  werub-service:
    build: .
    environment:
      AUTH_PROVIDER: keycloak
      AUTH_URL: http://keycloak:8080
      AUTH_REALM: werubworker
    ports:
      - "9000:9000"
    depends_on:
      - keycloak
      - redis

  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
```

---

## 4. 외부 SaaS 연동 계획

### 4.1 Slack Enterprise

| 항목 | 설정 |
|------|------|
| 연동 방식 | Slack App (자체 앱 생성) |
| 인증 | OAuth 2.0 (Bot Token + User Token) |
| 인바운드 | Socket Mode (방화벽 내부, 공인 IP 불필요) |
| 아웃바운드 | Web API (chat.postMessage 등) |
| 권한 스코프 | `chat:write`, `channels:history`, `users:read`, `files:read` |

**설정 방법:**
1. api.slack.com → 앱 생성 (기업 워크스페이스)
2. Bot Token Scopes 설정
3. Socket Mode 활성화 → App-Level Token 생성
4. WeruB Service에 토큰 등록

```python
# werub-service/app/connectors/slack_app.py
class SlackAppManager:
    """기업 Slack 앱 관리 — 여러 워크스페이스 지원"""
    
    async def register_workspace(self, bot_token: str, app_token: str) -> dict:
        """워크스페이스 등록 및 Socket Mode 시작"""
    
    async def relay_to_worker(self, event: dict) -> dict:
        """Slack 이벤트를 WeruBWorker 데스크톱으로 중계"""
```

### 4.2 GitHub Enterprise

| 항목 | 설정 |
|------|------|
| 연동 방식 | GitHub App (Organization 레벨) |
| 인증 | Installation Token (자동 갱신) |
| 인바운드 | Webhook → WeruB Service |
| 아웃바운드 | REST API v3 / GraphQL v4 |
| 권한 | `issues:write`, `pull_requests:write`, `contents:read` |

**설정 방법:**
1. github.com/organizations/{org}/settings/apps → App 생성
2. Webhook URL: `https://werub-service.internal/webhook/github`
3. Installation 승인 → Installation Token 자동 발급
4. WeruB Service가 토큰 관리 및 갱신

### 4.3 Google Workspace (Gmail + Calendar + Drive)

| 항목 | 설정 |
|------|------|
| 연동 방식 | Google Cloud 프로젝트 + OAuth 2.0 |
| 인증 | Service Account (도메인 전체 위임) 또는 OAuth |
| API | Gmail API, Calendar API, Drive API |

**옵션 A: Service Account (도메인 전체 위임) — 관리자용**
```
1. Google Cloud Console → 프로젝트 생성
2. Service Account 생성 → JSON 키 다운로드
3. Google Admin Console → 도메인 전체 위임 설정
4. WeruB Service에 Service Account 키 등록
→ 개별 사용자 OAuth 불필요, 관리자가 한 번만 설정
```

**옵션 B: OAuth Consent Screen — 사용자별**
```
1. Google Cloud Console → OAuth Consent Screen 설정 (내부 앱)
2. OAuth Client ID 생성 (웹 애플리케이션)
3. Redirect URI: https://werub-service.internal/oauth/google/callback
4. 각 사용자가 Google 로그인으로 권한 부여
→ WeruB Service가 OAuth 토큰 중개
```

### 4.4 Jira / Confluence (Atlassian)

| 항목 | 설정 |
|------|------|
| 연동 방식 | Atlassian API Token |
| 인증 | Email + API Token (Basic Auth) |
| API | REST API v3 |

**설정:** 각 사용자가 id.atlassian.com → API Token 생성 → WeruB Service에 등록

### 4.5 Notion

| 항목 | 설정 |
|------|------|
| 연동 방식 | Internal Integration |
| 인증 | Integration Token |
| API | Notion API v1 |

**설정:** notion.so/my-integrations → 통합 생성 → 토큰 복사

### 4.6 HubSpot CRM

| 항목 | 설정 |
|------|------|
| 연동 방식 | Private App |
| 인증 | Access Token |
| API | CRM API v3 |

**설정:** app.hubspot.com → Settings → Integrations → Private Apps → 토큰 생성

### 4.7 기타 SaaS

| 서비스 | 연동 방식 | 인증 |
|--------|----------|------|
| Linear | API Key | Bearer Token |
| Zendesk | API Token | Email + Token |
| Stripe | API Key | Secret Key |
| Dropbox | OAuth / Access Token | Bearer Token |
| Box | OAuth / Developer Token | Bearer Token |
| ClickUp | API Key | Bearer Token |
| Asana | Personal Access Token | Bearer Token |
| Figma | Personal Access Token | Bearer Token |

---

## 5. WeruB Service API 설계

### 5.1 인증 API

```
POST /auth/login              # SSO/LDAP 로그인
POST /auth/logout             # 로그아웃
GET  /auth/me                 # 현재 사용자 정보
POST /auth/refresh            # 토큰 갱신
```

### 5.2 커넥터 OAuth 중개 API

```
GET  /oauth/{provider}/start   # OAuth 플로우 시작 (브라우저 리다이렉트)
GET  /oauth/{provider}/callback # OAuth 콜백 처리
POST /oauth/{provider}/refresh  # 토큰 갱신
DELETE /oauth/{provider}        # 연결 해제
```

### 5.3 갤러리 API

```
GET  /gallery                   # 페르소나 목록
GET  /gallery/{slug}            # 페르소나 상세
POST /gallery/{slug}/install    # 설치 (manifest 다운로드)
POST /gallery/publish           # 관리자: 페르소나 게시
```

### 5.4 릴레이 API

```
WS   /relay/connect             # WebSocket 릴레이 (Slack/GitHub 인바운드)
POST /webhook/{provider}        # Webhook 수신 (GitHub, etc.)
```

### 5.5 업데이트 API

```
GET  /update/latest.json        # Tauri 자동 업데이트 매니페스트
GET  /update/download/{platform} # 바이너리 다운로드
```

### 5.6 관리 API

```
GET  /admin/users               # 사용자 목록
GET  /admin/audit               # 감사 로그
GET  /admin/connectors          # 전체 커넥터 상태
POST /admin/connectors/{name}/config # 기업 레벨 커넥터 설정
GET  /admin/dashboard           # 대시보드 데이터
```

---

## 6. WeruBWorker Desktop 변경사항

### config.toml 변경

```toml
# 기업 내부 WeruB Service 설정
[service]
base_url = "https://werub-service.internal:9000"
auth_provider = "keycloak"  # keycloak | ldap | local
auth_url = "https://keycloak.internal:8080"
auth_realm = "werubworker"

# 릴레이 (Slack/GitHub 인바운드 — 직접 연결이면 비워둠)
relay_ws_url = "wss://werub-service.internal:9000/relay/connect"

# 갤러리 (Git 기반이면 git_url, 서비스 기반이면 api_url)
[gallery]
source = "api"  # api | git | local
api_url = "https://werub-service.internal:9000/gallery"
# git_url = "https://github.com/your-org/personas/gallery.yaml"

# 자동 업데이트
[update]
endpoint = "https://werub-service.internal:9000/update/latest.json"
```

### Desktop → Service 연동

```
┌──────────────────┐                ┌──────────────────┐
│ WeruBWorker      │                │ WeruB Service    │
│ Desktop          │                │ (기업 서버)       │
│                  │                │                  │
│ [로그인]─────────────▶ /auth/login (SSO)              │
│                  │                │                  │
│ [Slack 연결]─────────▶ /oauth/slack/start             │
│                  │      ◀────────── /oauth/callback   │
│                  │                │                  │
│ [갤러리]─────────────▶ /gallery                       │
│                  │                │                  │
│ [인바운드]◀──────────── WS /relay/connect              │
│                  │                │                  │
│ [업데이트]────────────▶ /update/latest.json            │
└──────────────────┘                └──────────────────┘
```

---

## 7. 배포 구성

### Docker Compose (기본)

```yaml
version: "3.8"
services:
  werub-service:
    build: ./werub-service
    ports:
      - "9000:9000"
    environment:
      DATABASE_URL: postgresql://werub:pass@postgres/werub
      REDIS_URL: redis://redis:6379
      AUTH_PROVIDER: keycloak
      AUTH_URL: http://keycloak:8080
      AUTH_REALM: werubworker
      SLACK_APP_TOKEN: ${SLACK_APP_TOKEN}
      GITHUB_APP_PRIVATE_KEY: ${GITHUB_APP_KEY}
      GOOGLE_SERVICE_ACCOUNT: ${GOOGLE_SA_JSON}
    volumes:
      - ./data:/app/data
    depends_on:
      - postgres
      - redis
      - keycloak

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: werub
      POSTGRES_USER: werub
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

  keycloak:
    image: quay.io/keycloak/keycloak:latest
    command: start-dev
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: ${KC_PASSWORD}
    ports:
      - "8080:8080"

  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

volumes:
  pgdata:
  ollama_data:
```

### Kubernetes (확장)

```yaml
# 대규모 배포 시
apiVersion: apps/v1
kind: Deployment
metadata:
  name: werub-service
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: werub-service
          image: registry.internal/werub-service:latest
          ports:
            - containerPort: 9000
          envFrom:
            - secretRef:
                name: werub-secrets
```

---

## 8. 로드맵

| Phase | 작업 | 예상 |
|-------|------|------|
| **1** | WeruB Service 기본 서버 (FastAPI + 인증) | 2일 |
| **2** | OAuth 중개 (Slack, Google) | 2일 |
| **3** | 릴레이 WebSocket (Slack Socket Mode 중계) | 1일 |
| **4** | 갤러리 API + 관리 대시보드 | 1일 |
| **5** | Desktop 앱 연동 (config 변경, UI 수정) | 1일 |
| **6** | Docker Compose 배포 구성 | 0.5일 |
| **7** | 문서화 + 사용자 가이드 | 0.5일 |

---

## 9. 보안 고려사항

| 항목 | 방안 |
|------|------|
| 서비스 인증 | Keycloak SSO + LDAP 연동 |
| 토큰 저장 | PostgreSQL (암호화) + Redis (캐시) |
| 통신 | TLS (내부 CA 또는 Let's Encrypt) |
| API 접근 | JWT + Rate Limiting |
| 감사 | 모든 OAuth 토큰 발급/사용 로깅 |
| 네트워크 | 내부 VPN/VLAN 격리 |
| 시크릿 관리 | HashiCorp Vault 또는 K8s Secrets |

---

*작성일: 2026-08-07*
*프로젝트: WeruBWorker Enterprise Service*
