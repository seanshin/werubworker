# WeruBWorker 서비스 위키 & 자격증명 관리 시스템 계획

## 1. 개요

서비스 설정 정보(토큰, ID/PW, API 키, 서버 접속 정보 등)를 **위키 형태의 문서**로 관리하고,
이 문서에서 직접 서비스에 연결하여 활용할 수 있는 통합 시스템을 구축합니다.

### 핵심 가치
- **문서 = 설정**: 위키 문서에 작성한 자격증명이 실제 서비스 연결에 사용됨
- **팀 공유**: 서비스 접속 정보를 팀원과 안전하게 공유
- **이력 관리**: 변경 이력 추적, 만료일 관리, 로테이션 알림
- **검색 가능**: 모든 서비스 정보를 한 곳에서 검색

---

## 2. 전체 구조

```
┌──────────────────────────────────────────────────────────────┐
│                    WeruBWorker Wiki                           │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ 문서 에디터   │  │ 자격증명 볼트  │  │ 서비스 연결기     │    │
│  │ (Markdown)  │  │ (암호화 저장) │  │ (토큰 → 실행)    │    │
│  └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘    │
│         │               │                    │               │
│         └───────────────┼────────────────────┘               │
│                         │                                    │
│              ┌──────────▼──────────┐                         │
│              │   secrets.json      │                         │
│              │   wiki.db (SQLite)  │                         │
│              └─────────────────────┘                         │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 위키 문서 구조

### 3.1 문서 형식 (Markdown + YAML 프론트매터)

```markdown
---
type: service
name: Production DB
category: database
tags: [production, postgresql, critical]
credentials:
  - key: db_host
    label: 호스트
    value: db.production.internal
    secret: false
  - key: db_port
    label: 포트
    value: "5432"
    secret: false
  - key: db_user
    label: 사용자
    value: app_user
    secret: false
  - key: db_password
    label: 비밀번호
    value: "{{vault:prod-db-password}}"
    secret: true
    expires: 2026-12-31
    rotate_days: 90
linked_service: database:production
updated_at: 2026-08-07
updated_by: admin
---

# Production Database

## 접속 정보

| 항목 | 값 |
|------|-----|
| 호스트 | `db.production.internal` |
| 포트 | `5432` |
| 데이터베이스 | `app_production` |
| 사용자 | `app_user` |
| 비밀번호 | 🔒 (볼트 저장) |

## 용도
- 메인 서비스의 프로덕션 데이터베이스
- 읽기 전용 레플리카: `db-replica.production.internal`

## 백업 정책
- 매일 03:00 자동 백업 (Wasabi S3)
- 30일 보관
- 복원 테스트: 매월 1일

## 담당자
- DBA: 김철수 (slack: @chulsoo)
- 백업: 자동화 #daily-db-backup

## 변경 이력
| 날짜 | 변경 | 담당 |
|------|------|------|
| 2026-08-01 | 비밀번호 로테이션 | admin |
| 2026-06-15 | 레플리카 추가 | chulsoo |
| 2026-03-01 | 최초 생성 | admin |
```

### 3.2 자격증명 참조 문법

문서 내에서 자격증명을 안전하게 참조하는 문법:

```
{{vault:키이름}}          → 볼트에서 값 조회 (표시 시 마스킹)
{{secret:db_password}}   → 같은 문서의 credentials에서 조회
{{ref:문서이름/키이름}}   → 다른 문서의 자격증명 참조
```

**표시 규칙:**
- 위키 보기 모드: `••••••••` (마스킹)
- 복사 버튼: 클릭 시 클립보드에 실제 값 복사 (3초 후 자동 삭제)
- 서비스 연결: 자동으로 실제 값 사용

### 3.3 카테고리

```
서비스 위키
├── 🖥 서버 (SSH)
│   ├── web-01.md
│   ├── web-02.md
│   └── db-01.md
├── 🗄 데이터베이스
│   ├── production-db.md
│   ├── staging-db.md
│   └── analytics-db.md
├── ☁️ 클라우드
│   ├── aws-main.md
│   ├── cloudflare.md
│   └── wasabi-backup.md
├── 🔗 SaaS
│   ├── slack-workspace.md
│   ├── github-org.md
│   ├── jira-project.md
│   └── hubspot-portal.md
├── 🤖 AI 모델
│   ├── ollama-server.md
│   ├── openai-api.md
│   └── anthropic-api.md
├── 🔐 인증/보안
│   ├── ssl-certificates.md
│   ├── oauth-credentials.md
│   └── api-keys-inventory.md
└── 📋 운영 매뉴얼
    ├── deployment-guide.md
    ├── incident-response.md
    └── onboarding-checklist.md
```

---

## 4. 볼트 (자격증명 암호화 저장)

### 4.1 저장 구조

```json
// ~/.config/werubworker/vault.json (AES-256 암호화, 0600)
{
  "master_key_hash": "pbkdf2_hash...",
  "entries": {
    "prod-db-password": {
      "value": "AES256_ENCRYPTED_VALUE",
      "created_at": "2026-08-01",
      "expires": "2026-12-31",
      "rotate_days": 90,
      "last_rotated": "2026-08-01",
      "linked_docs": ["production-db"],
      "linked_services": ["database:production"]
    },
    "aws-access-key": {
      "value": "AES256_ENCRYPTED_VALUE",
      "created_at": "2026-07-15",
      "linked_docs": ["aws-main"],
      "linked_services": ["aws:default"]
    }
  }
}
```

### 4.2 암호화 방식

```python
# coworker/wiki/vault.py

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64, hashlib, os

class Vault:
    """마스터 패스워드 기반 자격증명 암호화 저장소.
    기존 auth.py의 마스터 패스워드를 키 파생에 재사용."""
    
    def __init__(self, data_dir: Path, master_password: str):
        # PBKDF2로 마스터 패스워드 → AES 키 파생
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                         salt=self._load_salt(), iterations=100000)
        key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
        self._fernet = Fernet(key)
    
    def store(self, key: str, value: str, **metadata) -> None:
        """자격증명 암호화 저장"""
    
    def retrieve(self, key: str) -> str:
        """자격증명 복호화 조회"""
    
    def list_entries(self) -> list[dict]:
        """메타데이터만 반환 (값 제외)"""
    
    def check_expiring(self, days: int = 30) -> list[dict]:
        """만료 임박 자격증명 목록"""
    
    def rotate(self, key: str, new_value: str) -> None:
        """자격증명 로테이션 (이전 값 이력 보관)"""
```

---

## 5. 서비스 연결기 (문서 → 실행)

### 5.1 linked_service 매핑

위키 문서의 `linked_service` 필드가 실제 서비스 설정과 연결됩니다:

```yaml
linked_service: database:production  → secrets.json의 database:production
linked_service: ssh:server:web-01    → secrets.json의 ssh:server:web-01
linked_service: aws:default          → secrets.json의 aws:default
```

### 5.2 동기화 흐름

```
위키 문서 편집
  ↓ 저장
credentials 파싱
  ↓
vault에 secret 값 암호화 저장
  ↓
linked_service 확인
  ↓ (변경 감지)
secrets.json 자동 업데이트
  ↓
서비스 연결 갱신 (provider invalidate)
```

### 5.3 원클릭 액션

위키 문서에서 직접 실행 가능한 액션:

```
┌─ Production DB ──────────────────────────┐
│                                           │
│  호스트: db.production.internal            │
│  비밀번호: •••••••• [📋 복사] [👁 보기]    │
│                                           │
│  [🔗 DB에 연결]  [🔄 비밀번호 로테이션]     │
│  [📊 상태 확인]  [💾 백업 실행]             │
│                                           │
│  ⚠️ 비밀번호 만료: 2026-12-31 (146일 남음)  │
│                                           │
└───────────────────────────────────────────┘
```

| 버튼 | 동작 |
|------|------|
| 📋 복사 | 클립보드에 실제 값 복사 (3초 후 자동 삭제) |
| 👁 보기 | 5초간 실제 값 표시 후 다시 마스킹 |
| 🔗 DB에 연결 | `database:production` 설정으로 DB 도구 활성화 |
| 🔄 로테이션 | 새 비밀번호 생성 → 볼트 업데이트 → 서비스 갱신 |
| 📊 상태 확인 | `db_status("production")` 도구 실행 |
| 💾 백업 실행 | `db_backup("production")` 도구 실행 (승인 필요) |

---

## 6. GUI 설계

### 6.1 위키 메인 페이지

```
┌─ 서비스 위키 ────────────────────────────────────────────┐
│                                                           │
│  [🔍 검색...]                    [+ 새 문서]  [📥 가져오기]│
│                                                           │
│  ── 카테고리 ──                                           │
│  🖥 서버 (3)        🗄 데이터베이스 (3)    ☁️ 클라우드 (3) │
│  🔗 SaaS (4)       🤖 AI 모델 (3)         🔐 보안 (3)    │
│  📋 운영 매뉴얼 (3)                                       │
│                                                           │
│  ── 최근 수정 ──                                          │
│  📄 production-db.md      2시간 전    admin               │
│  📄 aws-main.md           어제        admin               │
│  📄 ssl-certificates.md   3일 전      admin               │
│                                                           │
│  ── ⚠️ 주의 필요 ──                                      │
│  🔴 SSL 인증서 (example.com) — 15일 후 만료               │
│  🟡 Production DB 비밀번호 — 30일 후 로테이션 예정         │
│  🟡 AWS Access Key — 60일 후 만료                         │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

### 6.2 문서 보기/편집

```
┌─ 📄 Production DB ─────────────────────────────────────┐
│                                                         │
│  [편집]  [이력]  [삭제]                  카테고리: 데이터베이스│
│                                                         │
│  ┌─ 자격증명 ─────────────────────────────────────┐     │
│  │ 호스트      db.production.internal               │     │
│  │ 포트        5432                                 │     │
│  │ 사용자      app_user                             │     │
│  │ 비밀번호    •••••••• [📋] [👁]                   │     │
│  │                                                  │     │
│  │ [🔗 연결] [📊 상태] [💾 백업] [🔄 로테이션]      │     │
│  └──────────────────────────────────────────────────┘     │
│                                                         │
│  ── 문서 내용 (Markdown) ──                              │
│                                                         │
│  ## 용도                                                │
│  메인 서비스의 프로덕션 데이터베이스                      │
│  읽기 전용 레플리카: db-replica.production.internal      │
│                                                         │
│  ## 백업 정책                                            │
│  - 매일 03:00 자동 백업 (Wasabi S3)                     │
│  - 30일 보관                                            │
│                                                         │
│  ## 변경 이력                                            │
│  | 날짜 | 변경 | 담당 |                                  │
│  |------|------|------|                                  │
│  | 2026-08-01 | 비밀번호 로테이션 | admin |              │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 6.3 편집 모드

```
┌─ ✏️ Production DB 편집 ────────────────────────────────┐
│                                                         │
│  이름: [Production DB                ]                  │
│  카테고리: [데이터베이스 ▼]                               │
│  태그: [production, postgresql, critical]                │
│  연결 서비스: [database:production ▼]                    │
│                                                         │
│  ── 자격증명 ──                                         │
│  + 항목 추가                                            │
│  ┌────────────────────────────────────────────┐         │
│  │ 키: [db_host    ] 라벨: [호스트     ]       │         │
│  │ 값: [db.production.internal         ]       │         │
│  │ ☐ 비밀값  만료일: [          ]              │         │
│  ├────────────────────────────────────────────┤         │
│  │ 키: [db_password] 라벨: [비밀번호   ]       │         │
│  │ 값: [••••••••                       ]       │         │
│  │ ☑ 비밀값  만료일: [2026-12-31]              │         │
│  │ 로테이션: [90]일마다                        │         │
│  └────────────────────────────────────────────┘         │
│                                                         │
│  ── 문서 내용 (Markdown 에디터) ──                       │
│  ┌────────────────────────────────────────────┐         │
│  │ ## 용도                                    │         │
│  │ 메인 서비스의 프로덕션 데이터베이스          │         │
│  │ ...                                        │         │
│  └────────────────────────────────────────────┘         │
│                                                         │
│  [저장]  [취소]                                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 7. 백엔드 설계

### 7.1 파일 구조

```
coworker/
├── wiki/
│   ├── __init__.py
│   ├── store.py          # WikiStore (SQLite)
│   ├── vault.py          # 자격증명 암호화 볼트
│   ├── parser.py         # Markdown + YAML 파서
│   ├── sync.py           # 문서 ↔ secrets.json 동기화
│   └── tools.py          # 에이전트용 위키 도구
```

### 7.2 데이터베이스 (wiki.db)

```sql
CREATE TABLE wiki_pages (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    tags TEXT DEFAULT '[]',          -- JSON array
    content TEXT NOT NULL,           -- Markdown 본문
    credentials TEXT DEFAULT '[]',   -- JSON array (값은 vault 참조)
    linked_service TEXT,             -- secrets.json 키
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT DEFAULT 'system',
    version INTEGER DEFAULT 1
);

CREATE TABLE wiki_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    credentials TEXT,
    changed_by TEXT,
    changed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    change_note TEXT,
    FOREIGN KEY (page_id) REFERENCES wiki_pages(id)
);

CREATE TABLE wiki_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id TEXT NOT NULL,
    credential_key TEXT NOT NULL,
    alert_type TEXT NOT NULL,         -- 'expiring', 'expired', 'rotation_due'
    alert_date TEXT NOT NULL,
    acknowledged INTEGER DEFAULT 0,
    FOREIGN KEY (page_id) REFERENCES wiki_pages(id)
);
```

### 7.3 API 엔드포인트

```
# 위키 CRUD
GET    /v1/wiki                    # 문서 목록 (카테고리/검색/필터)
GET    /v1/wiki/{id}               # 문서 상세
POST   /v1/wiki                    # 문서 생성
PUT    /v1/wiki/{id}               # 문서 수정
DELETE /v1/wiki/{id}               # 문서 삭제

# 이력
GET    /v1/wiki/{id}/history       # 변경 이력
GET    /v1/wiki/{id}/history/{ver} # 특정 버전 조회

# 자격증명
GET    /v1/wiki/{id}/credentials   # 자격증명 메타 (값 마스킹)
POST   /v1/wiki/{id}/credentials/{key}/reveal  # 값 표시 (인증 필요)
POST   /v1/wiki/{id}/credentials/{key}/copy    # 클립보드 복사용 값
POST   /v1/wiki/{id}/credentials/{key}/rotate  # 로테이션

# 서비스 연결
POST   /v1/wiki/{id}/connect       # linked_service 연결 실행
POST   /v1/wiki/{id}/action        # 원클릭 액션 (상태, 백업 등)

# 알림
GET    /v1/wiki/alerts              # 만료/로테이션 알림
POST   /v1/wiki/alerts/{id}/ack    # 알림 확인

# 가져오기/내보내기
POST   /v1/wiki/import             # YAML/JSON 일괄 가져오기
GET    /v1/wiki/export             # 전체 내보내기 (암호화)
```

### 7.4 에이전트 도구

```python
# coworker/wiki/tools.py

def wiki_search(query: str, category: str = "") -> dict:
    """위키에서 서비스 정보 검색"""

def wiki_get(page_id: str) -> dict:
    """위키 문서 조회 (자격증명 마스킹)"""

def wiki_get_credential(page_id: str, key: str) -> dict:
    """특정 자격증명 값 조회 (에이전트가 서비스 연결에 사용)"""

def wiki_update(page_id: str, content: str) -> dict:
    """위키 문서 업데이트 (승인 필요)"""

def wiki_check_alerts() -> dict:
    """만료 임박 자격증명 및 로테이션 알림 확인"""
```

---

## 8. 활용 시나리오

### 8.1 에이전트가 위키를 활용하여 서비스 접속

```
사용자: "프로덕션 DB의 최근 주문 건수를 확인해줘"

에이전트:
  1. wiki_search("프로덕션 DB") → production-db 문서 찾음
  2. wiki_get_credential("production-db", "db_password") → 비밀번호 획득
  3. db_query("SELECT COUNT(*) FROM orders WHERE created_at > NOW() - INTERVAL '24h'",
             database="production") → 결과 반환
  
  "프로덕션 DB에서 최근 24시간 주문 건수: 1,234건입니다."
```

### 8.2 자동 만료 알림

```yaml
# 자동화 (매일 09:00)
name: "자격증명 만료 점검"
schedule: "0 9 * * *"
agent: ops
instructions: |
  wiki_check_alerts()를 실행하고:
  - 30일 이내 만료: Slack #ops-alerts에 경고
  - 7일 이내 만료: 긴급 알림
  - 만료됨: 즉시 알림 + 담당자 멘션
```

### 8.3 팀 온보딩

```
신규 팀원이 위키에서:
1. "운영 매뉴얼 > 온보딩 체크리스트" 확인
2. 각 서비스 문서에서 접속 정보 확인
3. 원클릭 연결로 서비스 설정 완료
4. 에이전트에게 "위키 보고 서버 설정해줘" 요청 가능
```

---

## 9. GUI 컴포넌트

```
surfaces/gui/src/
├── components/
│   ├── WikiView.tsx            # 위키 메인 페이지 (목록/검색)
│   ├── WikiPageView.tsx        # 문서 보기
│   ├── WikiPageEditor.tsx      # 문서 편집기
│   ├── WikiCredentialCard.tsx  # 자격증명 카드 (마스킹/복사/보기)
│   ├── WikiAlerts.tsx          # 만료 알림 패널
│   └── WikiImport.tsx          # 가져오기 모달
```

---

## 10. 보안

| 항목 | 방식 |
|------|------|
| 저장 암호화 | AES-256 (마스터 패스워드 기반 키 파생) |
| 전송 | HTTPS + sidecar 토큰 + auth 토큰 |
| 접근 제어 | 로그인 필수, 자격증명 조회 시 추가 인증 |
| 감사 | 모든 자격증명 접근/변경 기록 |
| 클립보드 | 복사 후 3초 자동 삭제 |
| 표시 | 기본 마스킹, 표시 5초 제한 |
| 내보내기 | 암호화된 형태로만 내보내기 |

---

## 11. 구현 로드맵

| Phase | 작업 | 예상 |
|-------|------|------|
| **1** | `wiki/store.py` — SQLite CRUD + 이력 | 1일 |
| **2** | `wiki/vault.py` — 암호화 볼트 | 0.5일 |
| **3** | `wiki/parser.py` — Markdown + YAML 파서 | 0.5일 |
| **4** | `wiki/sync.py` — secrets.json 동기화 | 0.5일 |
| **5** | `wiki/tools.py` — 에이전트 도구 5개 | 0.5일 |
| **6** | API 엔드포인트 15개 | 1일 |
| **7** | WikiView.tsx — 메인 페이지 | 1일 |
| **8** | WikiPageView/Editor — 보기/편집 | 1일 |
| **9** | WikiCredentialCard — 자격증명 UI | 0.5일 |
| **10** | WikiAlerts — 알림 + 자동화 | 0.5일 |
| **11** | 번역 (en/ko) + 검증 | 0.5일 |

---

## 12. 기존 시스템과의 연동

```
┌─────────────────────────────────────────────────┐
│                  Wiki 문서                       │
│  credentials:                                    │
│    db_password: {{vault:prod-db-password}}       │
│  linked_service: database:production             │
└────────────────────┬────────────────────────────┘
                     │ sync
          ┌──────────▼──────────┐
          │    secrets.json     │
          │  database:production│────→ db_tools()
          │  ssh:server:web-01  │────→ ssh_tools()
          │  aws:default        │────→ cloud_infra_tools()
          └─────────────────────┘
                     │
          ┌──────────▼──────────┐
          │    vault.json       │
          │  (AES-256 암호화)   │
          │  prod-db-password   │
          │  aws-access-key     │
          └─────────────────────┘
```

문서를 편집 → 볼트에 암호화 저장 → secrets.json 동기화 → 도구가 실제 값 사용

---

*작성일: 2026-08-07*
*프로젝트: WeruBWorker 서비스 위키 & 자격증명 관리*
