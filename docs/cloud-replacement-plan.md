# OpenWorker Cloud 제거 및 자체 서비스 대체 계획

## 1. 개요

OpenWorker Cloud 의존성을 완전 제거하고, 필요한 기능만 자체 구축 또는 직접 연동으로 대체합니다.

---

## 2. 현재 Cloud 기능 분석

| 기능 | Cloud 역할 | 코드 참조 수 | 필수 여부 |
|------|-----------|------------|----------|
| **OAuth 브로커** | Slack/GitHub/Gmail 등 OAuth 중개 | 170 | ❌ 수동 연결로 대체 가능 |
| **릴레이 WebSocket** | Slack/GitHub 인바운드 메시지 중계 | 151 | ❌ Socket Mode로 대체 |
| **페르소나 갤러리** | 큐레이션 페르소나 목록 | 29 | ❌ 로컬/Git 설치로 대체 |
| **텔레메트리** | 사용 통계 수집 | 20 | ❌ 제거 |
| **Cloud 로그인/상태** | Auth0 인증 | 12 | ❌ 제거 |
| **자동 업데이트** | 업데이트 매니페스트 | 별도 | ⚠️ 자체 서버 필요 |

### 총 영향 범위
- Python 파일: 16개
- GUI 파일: 27개
- 총 참조: ~380건

---

## 3. 대체 전략

### 3.1 OAuth → 직접 연결 (수동 토큰)

**현재**: Cloud가 OAuth 플로우를 중개 → 토큰을 로컬에 저장
**대체**: 사용자가 직접 각 서비스의 개발자 콘솔에서 토큰/키를 생성하여 입력

| 서비스 | 수동 연결 방법 | 이미 지원? |
|--------|--------------|----------|
| Slack | Bot Token + App Token → Socket Mode | ✅ 지원됨 |
| GitHub | Personal Access Token (PAT) | ✅ 지원됨 |
| Gmail | OAuth Client ID/Secret → 로컬 OAuth 플로우 | ⚠️ 자체 OAuth 필요 |
| Google Calendar | OAuth Client ID/Secret | ⚠️ 자체 OAuth 필요 |
| HubSpot | Private App Token | ✅ 지원됨 |
| Linear | API Key | ✅ 지원됨 |
| Jira | API Token + Email | ✅ 지원됨 |
| 기타 20+ | API Key/Token 직접 입력 | ✅ 지원됨 |

**Google OAuth 자체 구현 필요:**
Gmail과 Calendar만 OAuth가 필수입니다. 자체 OAuth 플로우를 구현합니다:

```python
# coworker/connectors/local_oauth.py

class LocalOAuthFlow:
    """로컬 OAuth 플로우 — Cloud 없이 직접 Google OAuth 처리.
    
    1. 사용자가 Google Cloud Console에서 OAuth Client ID 생성
    2. 로컬 서버에서 redirect_uri (localhost) 수신
    3. 토큰을 secrets.json에 저장
    """
    
    def start(self, client_id: str, client_secret: str, scopes: list[str]) -> str:
        """브라우저 열기 URL 반환"""
    
    def handle_callback(self, code: str) -> dict:
        """Authorization code → access_token + refresh_token"""
    
    def refresh(self, refresh_token: str) -> dict:
        """토큰 갱신"""
```

### 3.2 릴레이 WebSocket → Slack Socket Mode 직접 연결

**현재**: Cloud 릴레이 서버 → WebSocket → 로컬 서버로 메시지 전달
**대체**: Slack Socket Mode로 직접 연결 (이미 지원됨)

```
현재: Slack → Cloud Relay → WebSocket → 로컬 서버
대체: Slack → Socket Mode → 로컬 서버 (직접)
```

GitHub Webhooks는 공인 IP가 필요하므로:
- **옵션 A**: GitHub Polling (주기적 API 호출) — 간단
- **옵션 B**: ngrok/Cloudflare Tunnel — 실시간
- **옵션 C**: GitHub App + Webhook → 자체 서버

### 3.3 페르소나 갤러리 → 로컬/Git 기반

**현재**: Cloud 갤러리 API → 큐레이션 목록 표시
**대체**: 

```
방법 1: Git 저장소 기반 갤러리
  - GitHub/GitLab 저장소에 페르소나 목록 JSON 게시
  - 앱에서 raw URL로 fetch
  - 설치는 기존 Git URL 방식 그대로

방법 2: 로컬 번들 갤러리
  - 앱에 기본 페르소나 세트 번들
  - 추가 페르소나는 Git URL로 설치

방법 3: 자체 API 서버 (선택)
  - 간단한 FastAPI 서버에 갤러리 호스팅
  - 팀 내부 공유용
```

### 3.4 텔레메트리 → 완전 제거

Cloud 텔레메트리 코드를 전부 삭제합니다. 필요 시 나중에 자체 수집 도구를 구축합니다.

### 3.5 자동 업데이트 → 자체 서버 또는 GitHub Releases

```
현재: download.openworker.com/latest.json
대체:
  옵션 A: GitHub Releases API (public repo)
  옵션 B: 자체 서버에 latest.json 호스팅
  옵션 C: 업데이트 비활성화 (수동 업데이트)
```

---

## 4. 구현 계획

### Phase 1: Cloud 코드 제거 (안전 정리)

| # | 작업 | 파일 |
|---|------|------|
| 1 | `cloud.py`에서 텔레메트리 함수 제거 | cloud.py |
| 2 | `config.py`에서 Cloud 설정 제거 (이미 빈 값) | config.py |
| 3 | 릴레이 클라이언트 비활성화 | connectors/relay_client.py |
| 4 | Gallery API 엔드포인트 제거 | server/app.py |
| 5 | Cloud 로그인/로그아웃 엔드포인트 제거 | server/app.py |
| 6 | Cloud 상태 API 단순화 | server/app.py |
| 7 | `ensure_fresh_connector_token` Cloud 경로 제거 | cloud.py |

### Phase 2: GUI Cloud UI 제거/수정

| # | 작업 | 파일 |
|---|------|------|
| 8 | Sidebar "Sign in to Cloud" 섹션 제거 | Sidebar.tsx |
| 9 | GalleryModal → 로컬/Git 갤러리로 전환 | GalleryModal.tsx |
| 10 | CloudSignIn.tsx 제거 또는 비활성화 | CloudSignIn.tsx |
| 11 | 온보딩 Cloud 로그인 단계 제거 | Onboarding.tsx |
| 12 | 커넥터 "원클릭 연결" → "수동 연결"으로 통일 | AddConnectionModal.tsx |
| 13 | AutomationQuickstart Cloud 로그인 패널 제거 | AutomationQuickstart.tsx |

### Phase 3: 자체 OAuth 구현 (Gmail/Calendar용)

| # | 작업 | 파일 |
|---|------|------|
| 14 | `local_oauth.py` 생성 (Google OAuth 로컬 플로우) | connectors/local_oauth.py |
| 15 | Gmail 연결을 자체 OAuth로 전환 | connectors/gmail_accounts.py |
| 16 | Calendar 연결을 자체 OAuth로 전환 | connectors/gcal_accounts.py |
| 17 | 설정 UI에 OAuth Client ID/Secret 입력 필드 추가 | SettingsView.tsx |

### Phase 4: 대체 갤러리 구축 (선택)

| # | 작업 | 설명 |
|---|------|------|
| 18 | 기본 페르소나 번들 (builtin/) 확장 | 로컬 갤러리 |
| 19 | Git 저장소 기반 갤러리 fetch 구현 | 원격 갤러리 |
| 20 | 갤러리 UI를 로컬/Git 소스로 전환 | GalleryModal.tsx |

### Phase 5: 자동 업데이트 대체 (선택)

| # | 작업 | 설명 |
|---|------|------|
| 21 | Tauri 업데이트 엔드포인트를 GitHub Releases로 변경 | tauri.conf.json |
| 22 | 또는 업데이트 기능 비활성화 | UpdateBanner.tsx |

---

## 5. 자체 서비스 아키텍처 (Phase 3-4 상세)

### 5.1 자체 OAuth 서버 (Gmail/Calendar)

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  브라우저     │───▶│ Google OAuth │───▶│ 로컬 콜백    │
│  (사용자)    │    │ 동의 화면     │    │ localhost   │
└─────────────┘    └──────────────┘    └──────┬──────┘
                                              │
                                      ┌───────▼───────┐
                                      │ secrets.json  │
                                      │ (토큰 저장)    │
                                      └───────────────┘
```

**사전 요구사항:** 사용자가 Google Cloud Console에서:
1. 프로젝트 생성
2. Gmail API + Calendar API 활성화
3. OAuth 클라이언트 ID 생성 (데스크톱 앱 유형)
4. Client ID와 Secret을 설정에 입력

**설정 UI:**
```
┌─ Google OAuth 설정 ──────────────────────────┐
│                                               │
│  Client ID:    [your-client-id.apps...  ]     │
│  Client Secret: [GOCSPX-***             ]     │
│                                               │
│  [Gmail 연결]  [Calendar 연결]                 │
│                                               │
│  ℹ Google Cloud Console에서 OAuth 클라이언트를  │
│    생성하세요. 데스크톱 앱 유형을 선택합니다.    │
│                                               │
└───────────────────────────────────────────────┘
```

### 5.2 커넥터별 설정 가이드

Cloud 없이 각 서비스를 연결하는 방법을 UI에 안내합니다:

| 서비스 | 설정 안내 |
|--------|---------|
| Slack | api.slack.com → 앱 생성 → Bot Token + App Token 복사 |
| GitHub | github.com/settings/tokens → PAT 생성 |
| Gmail | Google Cloud Console → OAuth → Client ID/Secret |
| HubSpot | app.hubspot.com → Private App → Access Token |
| Linear | linear.app/settings → API Key |
| Jira | id.atlassian.com → API Token |

### 5.3 Git 기반 갤러리

```yaml
# gallery.yaml (Git 저장소에 호스팅)
personas:
  - name: "주간 보고서 작성기"
    slug: "weekly-reporter"
    description: "매주 GitHub/Slack 활동을 요약하여 보고서를 생성합니다"
    git_url: "https://github.com/your-org/personas/tree/main/weekly-reporter"
    tags: ["보고서", "자동화"]
    
  - name: "코드 리뷰어"
    slug: "code-reviewer"
    description: "PR을 분석하고 코드 리뷰 의견을 제시합니다"
    git_url: "https://github.com/your-org/personas/tree/main/code-reviewer"
    tags: ["개발", "리뷰"]
```

앱 설정에서 갤러리 소스 URL을 지정:
```toml
# config.toml
[gallery]
source = "https://raw.githubusercontent.com/your-org/personas/main/gallery.yaml"
```

---

## 6. 삭제 대상 파일/코드

### 삭제할 파일
| 파일 | 사유 |
|------|------|
| `coworker/cloud.py` | Cloud 클라이언트 전체 (OAuth 브로커, 텔레메트리, 갤러리) |
| `coworker/connectors/relay_client.py` | Cloud 릴레이 WebSocket |
| `surfaces/gui/src/components/connectors/CloudSignIn.tsx` | Cloud 로그인 UI |

### 대폭 수정할 파일
| 파일 | 수정 내용 |
|------|----------|
| `server/app.py` | Cloud 엔드포인트 제거 (login, logout, gallery, status) |
| `Sidebar.tsx` | Cloud 로그인 섹션 제거 |
| `GalleryModal.tsx` | Cloud 갤러리 → Git 갤러리로 전환 |
| `Onboarding.tsx` | Cloud 로그인 단계 제거 |
| `AutomationQuickstart.tsx` | Cloud 로그인 패널 제거 |
| `AddConnectionModal.tsx` | "원클릭 연결" 탭 제거, 수동 연결만 |
| `connectors/setup.py` | managed OAuth 경로 제거 |
| `connectors/descriptors.py` | managed/managed_paused 플래그 제거 |

---

## 7. 로드맵

| Phase | 작업 | 예상 |
|-------|------|------|
| **Phase 1** | Cloud 코드 제거 (Python + GUI) | 1일 |
| **Phase 2** | 커넥터 UI "수동 연결" 통일 | 0.5일 |
| **Phase 3** | Google 자체 OAuth 구현 | 1일 |
| **Phase 4** | Git 기반 갤러리 (선택) | 0.5일 |
| **Phase 5** | 업데이트 서버 대체 (선택) | 0.5일 |

---

## 8. 리스크

| 리스크 | 대응 |
|--------|------|
| Gmail/Calendar 연결이 복잡해짐 | 설정 가이드 UI + 단계별 안내 |
| 갤러리 없어짐 | builtin 페르소나 확충 + Git URL 설치 |
| 인바운드 GitHub 메시지 불가 | GitHub Polling 또는 Webhook 대체 |
| 사용자 경험 저하 (원클릭 → 수동) | 각 서비스별 명확한 설정 안내 |

---

*작성일: 2026-08-07*
*프로젝트: WeruBWorker Cloud 대체 계획*
