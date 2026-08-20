# WeruBWorker × Sign 보안 강화 기획서

> **버전**: v1.0 (2026-08-19)
> **대상**: WeruBWorker v2.3.x + Sign v1.29.0
> **목표**: Sign 전자서명 인프라를 도입하여 WeruBWorker의 로그 무결성·데이터 보안·인증 체계를 전면 강화

---

## 1. 현황 분석

### 1.1 WeruBWorker 현재 보안 상태

| 영역 | 현재 | 문제점 |
|------|------|--------|
| **감사 로그** | SQLite append-only (`audit.py`, `audit_ops.py`) | 해시체인 없음 — DB 접근 시 이력 삭제·변조 가능 |
| **민감정보 필터** | `_SECRET_KEYS` 키워드 매칭으로 `[redacted]` | SSH 명령·OpsAudit의 `command` 필드는 필터 미적용 |
| **인증** | PBKDF2-SHA256 마스터 비밀번호 + 세션 토큰 | 2FA 없음, 비밀번호 미설정 시 무인증 |
| **비밀 저장** | secrets.json 평문 (0600 퍼미션 보호만) | 디스크 접근 시 전체 자격증명 노출 |
| **API 통신** | HTTP (로컬), HMAC 없음 | MCP 도구 호출·Webhook 서명 검증 없음 |
| **로그 무결성** | 없음 | 내부자가 로그 삭제/변조해도 탐지 불가 |

### 1.2 Sign이 제공하는 보안 인프라

| 역량 | 설명 |
|------|------|
| **PKI (2단 CA)** | Root CA → Issuing CA → 말단 인증서. HSM 앵커 키 수탁 |
| **감사 해시체인** | append-only + 항목별 `prevHash` 연결 + TSA 앵커 |
| **RFC3161 타임스탬프** | 자체 TSA + 외부 TSA 이중 앵커 (운영자 독립 증거) |
| **CMS/PAdES 서명** | 문서 전자서명 + 장기 검증 (LTA) |
| **본인확인** | PASS·SSO·TOTP 등 다중 인증 바인딩 |
| **Webhook HMAC** | 이벤트별 HMAC 서명 + 멱등 + 소비자별 시크릿 격리 |
| **API 인증 4경로** | 기계키·SSO·포털토큰·세션 — 스코프 기반 RBAC |

---

## 2. 통합 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                   WeruBWorker v2.4                   │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ AuditStore│  │OpsAudit  │  │ MCP 도구 실행     │  │
│  │ (기존)    │  │Store     │  │ (37도구)          │  │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘  │
│       │              │                 │             │
│       └──────────┬───┘─────────────────┘             │
│                  ▼                                   │
│  ┌─────────────────────────────────────────────┐     │
│  │         sign-bridge (신규 모듈)              │     │
│  │  - 해시체인 클라이언트                       │     │
│  │  - API 호출 서명/검증                        │     │
│  │  - 비밀 볼트 암호화 (Sign PKI 기반)          │     │
│  │  - 인증 강화 (2FA/SSO 연동)                  │     │
│  └──────────────────┬──────────────────────────┘     │
│                     │ REST API (x-api-key)           │
└─────────────────────┼───────────────────────────────┘
                      ▼
          ┌───────────────────────┐
          │   Sign v1.29.0        │
          │   http://127.0.0.1:4100/v1  │
          │                       │
          │  - PKI / CA           │
          │  - 감사 해시체인       │
          │  - TSA (자체+외부)    │
          │  - Webhook HMAC       │
          └───────────────────────┘
```

---

## 3. 구현 계획

### Phase 1: 감사 로그 무결성 (해시체인 도입)

> **목표**: 모든 감사 로그에 해시체인을 적용하여 변조 탐지 가능하게 한다

#### 1-1. 로컬 해시체인 계층 추가

**파일**: `coworker/security/hash_chain.py` (신규)

```
각 감사 이벤트 저장 시:
  entry.hash = SHA-256(prevHash + timestamp + action + target + command + result)
  entry.prevHash = 직전 항목의 hash
```

| 작업 | 대상 파일 | 설명 |
|------|-----------|------|
| 해시체인 엔진 구현 | `security/hash_chain.py` | SHA-256 체인 생성·검증 로직 |
| AuditStore 통합 | `audit.py` | `append()` 시 해시 계산, DB 컬럼 추가 (`prev_hash`, `hash`) |
| OpsAuditStore 통합 | `monitoring/audit_ops.py` | 동일 해시체인 적용 |
| 체인 검증 API | `server/routes/security.py` | `GET /api/audit/verify-chain` — 체인 무결성 검증 |
| 체인 검증 MCP 도구 | `mcp/monitoring_server.py` | `audit_chain_verify` 도구 추가 |

#### 1-2. Sign 연동 — TSA 앵커링

**파일**: `coworker/security/sign_bridge.py` (신규)

```
주기적 (configurable, 기본 6시간):
  1. 현재 체인 head hash 수집
  2. POST /v1/audit-events → Sign 해시체인에 봉인
  3. Sign이 TSA 토큰(자체+외부) 발급
  4. 앵커 토큰을 로컬 DB에 저장
```

| 작업 | 설명 |
|------|------|
| Sign API 클라이언트 | `sign_bridge.py` — 기계키 인증, 감사 이벤트 제출 |
| 앵커링 스케줄러 | 주기적 head hash → Sign `/v1/audit-events` POST |
| 앵커 검증 | `GET /api/audit/verify-anchor` — Sign 앵커와 로컬 체인 교차 검증 |
| 앵커 실패 내성 | Sign 미응답 시 로컬 체인은 계속 동작, 다음 주기에 보충 |

---

### Phase 2: 민감정보 보호 강화

> **목표**: 로그·저장소에서 민감정보 노출을 원천 차단

#### 2-1. 로그 민감정보 필터 확장

**파일**: `coworker/audit.py`, `coworker/monitoring/audit_ops.py`

| 작업 | 현재 | 개선 |
|------|------|------|
| OpsAudit `command` 필터 | 필터 없음 (명령 원문 저장) | 패턴 매칭으로 비밀번호·토큰·키 마스킹 |
| SSH 명령 내 비밀 | 그대로 기록 | `password=`, `token=`, `-p ` 등 정규식 탐지 → `***` |
| 로그 레벨 분리 | 모든 로그 동일 처리 | 민감 등급 태그 (`SENSITIVE`, `PII`, `CREDENTIAL`) |
| 환경변수 로그 차단 | 부분 적용 | `_SECRET_KEYS` 확장 + 정규식 패턴 (`sk-`, `ghp_`, `xoxb-`) |

```python
# 추가할 민감 패턴 (정규식)
_SENSITIVE_PATTERNS = [
    r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+",
    r"(?i)(api[_-]?key|secret[_-]?key)\s*[=:]\s*\S+",
    r"sk-[a-zA-Z0-9]{20,}",      # OpenAI
    r"sk-ant-[a-zA-Z0-9]{20,}",  # Anthropic
    r"ghp_[a-zA-Z0-9]{36,}",     # GitHub PAT
    r"xoxb-[a-zA-Z0-9-]+",       # Slack Bot
    r"Bearer\s+[a-zA-Z0-9._-]+", # JWT/Bearer 토큰
]
```

#### 2-2. 비밀 저장소 암호화 (Sign PKI 연동)

**파일**: `coworker/secrets.py`

| 작업 | 현재 | 개선 |
|------|------|------|
| secrets.json | 평문 JSON (0600 퍼미션만) | Sign 발급 인증서로 봉투 암호화 (envelope encryption) |
| 키 관리 | 마스터 비밀번호 기반 Fernet | Sign CA 발급 키페어 + 로컬 KEK 이중 보호 |
| 키 회전 | 수동 | Sign 인증서 만료 전 자동 재발급 + secrets 재암호화 |

```
봉투 암호화 흐름:
  1. Sign에서 WeruBWorker 전용 인증서 발급 (SYSTEM 타입)
  2. 랜덤 DEK (Data Encryption Key) 생성 → secrets 암호화
  3. DEK를 Sign 공개키로 암호화 → secrets.json.enc 에 저장
  4. 복호화: Sign 개인키로 DEK 복원 → secrets 복호화
```

---

### Phase 3: API 통신 보안

> **목표**: WeruBWorker ↔ 외부 시스템 간 통신 무결성·인증 보장

#### 3-1. Webhook 발신 HMAC 서명

**파일**: `coworker/security/hmac_signer.py` (신규)

| 작업 | 설명 |
|------|------|
| 발신 HMAC | WeruBWorker가 Gitea·외부에 보내는 webhook에 `X-Signature-256` 헤더 추가 |
| 수신 검증 | Gitea·Sign에서 오는 webhook의 HMAC 서명 검증 |
| 시크릿 관리 | 소비자(수신자)별 시크릿 격리, Sign 모델 차용 |
| 재시도 멱등 | `X-Event-Id` 헤더로 중복 처리 방지 |

#### 3-2. MCP 도구 호출 서명

**파일**: `coworker/mcp/security.py` (신규)

| 작업 | 설명 |
|------|------|
| 도구 호출 서명 | 위험 도구(`risk_level=high`) 호출 시 요청 해시에 Sign CMS 서명 첨부 |
| 서명 검증 로그 | 감사 로그에 서명값·검증 결과 기록 |
| 부인 방지 | 누가 언제 어떤 도구를 호출했는지 Sign이 증명 |

---

### Phase 4: 인증 체계 강화

> **목표**: 관리자 인증을 다중 인증(MFA)으로 격상

#### 4-1. TOTP 2차 인증

**파일**: `coworker/auth.py`

| 작업 | 현재 | 개선 |
|------|------|------|
| 로그인 | 마스터 비밀번호 1단계 | 비밀번호 + TOTP (RFC 6238) 2단계 |
| TOTP 등록 | 없음 | QR 코드 생성 → 인증 앱(Google Authenticator 등) 등록 |
| 백업 코드 | 없음 | 1회용 복구 코드 10개 발급 (Sign 봉인 보관) |
| 세션 강화 | 30분 자동 잠금 | 위험 작업 시 재인증 (step-up) |

#### 4-2. Sign SSO 연동 (선택적)

| 작업 | 설명 |
|------|------|
| staff-token 발급 | WeruBWorker 사용자에게 Sign SSO 토큰 발급 |
| 서명 바인딩 | 위험 작업(서버 재시작, DB 변경) 시 Sign 본인확인 결합 |
| 인증 로그 봉인 | 로그인·로그아웃·권한 변경을 Sign 해시체인에 기록 |

---

### Phase 5: 보안 모니터링 MCP 도구 확장

> **목표**: Sign 보안 기능을 MCP 도구로 노출하여 AI 에이전트가 보안 점검 자동화

**파일**: `coworker/mcp/monitoring_server.py` (기존 확장)

| 도구명 | 설명 |
|--------|------|
| `audit_chain_verify` | 로컬 해시체인 무결성 검증 |
| `audit_anchor_status` | Sign TSA 앵커링 현황 (마지막 앵커 시각, 미앵커 구간) |
| `secrets_rotation_check` | 비밀 키 만료·회전 현황 점검 |
| `sign_cert_status` | Sign 발급 인증서 상태 (유효기간, 폐기 여부) |
| `security_score_enhanced` | 기존 `security_score` + 해시체인·앵커·인증 점수 통합 |
| `log_sensitive_scan` | 로그에 민감정보 잔존 여부 스캔 |

---

### Phase 6: 데이터 무결성·백업 보안

> **목표**: 백업 데이터의 변조 방지 + 복원 시 무결성 검증

| 작업 | 설명 |
|------|------|
| 백업 서명 | 백업 생성 시 전체 해시 → Sign CMS 서명 첨부 |
| 복원 검증 | 복원 전 서명 검증 통과 필수 |
| 감사 기록 | 백업 생성·복원·삭제 모두 Sign 해시체인에 기록 |
| 설정 변경 봉인 | `config.toml` 변경 이력을 해시체인으로 추적 |

---

## 4. 파일 구조 (신규/변경)

```
coworker/
├── security/                    # [신규 패키지]
│   ├── __init__.py
│   ├── hash_chain.py            # 해시체인 엔진
│   ├── sign_bridge.py           # Sign API 클라이언트 + 앵커링
│   ├── hmac_signer.py           # Webhook HMAC 서명/검증
│   ├── sensitive_filter.py      # 민감정보 필터 (정규식 기반)
│   └── totp.py                  # TOTP 2FA 구현
├── audit.py                     # [변경] 해시체인 통합
├── auth.py                      # [변경] 2FA 추가
├── secrets.py                   # [변경] 봉투 암호화
├── monitoring/
│   ├── audit_ops.py             # [변경] 해시체인 통합 + 명령 필터
│   └── monitoring_server.py     # [변경] 보안 MCP 도구 추가
├── mcp/
│   └── security.py              # [신규] 도구 호출 서명
└── server/
    └── routes/
        └── security.py          # [신규] 보안 API 엔드포인트
```

---

## 5. 설정

### 5.1 Sign 연동 설정 (`config.toml`)

```toml
[security.sign]
enabled = true
base_url = "http://127.0.0.1:4100/v1"
api_key = "${SIGN_API_KEY}"               # secrets.json 참조
consumer_name = "werubworker"
anchor_interval_hours = 6                 # TSA 앵커링 주기
cert_type = "SYSTEM"                      # WeruBWorker 전용 인증서 타입

[security.hash_chain]
enabled = true
algorithm = "sha256"
anchor_on_sign = true                     # Sign TSA 앵커링 사용

[security.sensitive_filter]
extra_patterns = []                       # 추가 민감 패턴 (정규식)
log_level = "WARN"                        # 민감정보 탐지 시 로그 레벨

[security.totp]
enabled = false                           # 2FA 활성화 (기본 비활성)
issuer = "WeruBWorker"
step_up_actions = ["ssh_execute", "docker_restart", "db_write", "secret_access"]
```

### 5.2 Sign 소비자 등록

```bash
# Sign 콘솔에서 WeruBWorker 소비자 등록
# 필요 스코프: requests:write (감사 이벤트 기록용)
POST /v1/admin/consumers
{
  "name": "werubworker",
  "scopes": ["requests:write", "documents:read"]
}
```

---

## 6. 구현 우선순위 및 일정

| 순서 | Phase | 핵심 산출물 | 의존성 |
|------|-------|------------|--------|
| **1** | Phase 2-1: 민감정보 필터 강화 | `sensitive_filter.py`, `audit.py` 패치 | 없음 (독립 작업) |
| **2** | Phase 1-1: 로컬 해시체인 | `hash_chain.py`, DB 마이그레이션 | 없음 |
| **3** | Phase 1-2: Sign TSA 앵커링 | `sign_bridge.py`, 스케줄러 | Sign 서버 가동 + 소비자 등록 |
| **4** | Phase 3-1: Webhook HMAC | `hmac_signer.py` | 해시체인 완료 |
| **5** | Phase 4-1: TOTP 2FA | `totp.py`, `auth.py` 패치 | 없음 |
| **6** | Phase 2-2: 비밀 볼트 암호화 | `secrets.py` 패치 | Sign 인증서 발급 |
| **7** | Phase 5: MCP 도구 확장 | `monitoring_server.py` 확장 | Phase 1~4 완료 |
| **8** | Phase 3-2: 도구 호출 서명 | `mcp/security.py` | Sign 인증서 |
| **9** | Phase 6: 백업 서명 | ITMS 백업 연동 | Sign CMS 서명 |
| **10** | Phase 4-2: Sign SSO | staff-token 연동 | Sign SSO 설정 |

---

## 7. 보안 위협 모델 (Sign 도입 전후)

| 위협 | 현재 (Sign 없음) | Sign 도입 후 |
|------|------------------|-------------|
| **T1. 감사 로그 변조** | DB 접근으로 삭제·수정 가능 | 해시체인 → 1건 변조 시 이후 전체 깨짐 |
| **T2. 운영자 로그 재계산** | 탐지 불가 | TSA 앵커 → 외부 타임스탬프와 불일치 탐지 |
| **T3. 민감정보 로그 노출** | 키워드 기반 부분 필터 | 정규식 패턴 + 민감 등급 태그 + 잔존 스캔 |
| **T4. secrets 평문 노출** | 파일 퍼미션 0600만 | 봉투 암호화 (Sign 인증서 기반) |
| **T5. API 위변조** | 인증 없는 HTTP | HMAC 서명 + 멱등 + Sign CMS 서명 |
| **T6. 관리자 계정 탈취** | 비밀번호 1단계 | TOTP 2FA + 위험 작업 step-up |
| **T7. 부인 (행위 부정)** | 시스템 주장뿐 | Sign 전자서명 → 암호학적 부인 방지 |
| **T8. 백업 변조** | 해시 검증 없음 | CMS 서명 → 복원 전 검증 필수 |

---

## 8. 기존 보안 점검 보완 연계

`security-audit-plan.md`의 미완료 항목과 본 기획의 매핑:

| 기존 계획 항목 | 본 기획 Phase | 비고 |
|---------------|-------------|------|
| #5 secrets.json 암호화 | Phase 2-2 | Sign PKI 기반 봉투 암호화로 상위 호환 |
| #6 기존 secrets 마이그레이션 | Phase 2-2 | 인증서 발급 후 자동 재암호화 |
| #11 자격증명 접근 감사 | Phase 1-1 | 해시체인에 자격증명 접근 기록 |
| #12 로그인 실패 잠금 | Phase 4-1 | TOTP 2FA로 근본 해결 |
| Phase 4: 감사 강화 전체 | Phase 1 + 5 | 해시체인 + TSA 앵커로 대체 |

---

## 9. 검증 계획

| 검증 항목 | 방법 |
|-----------|------|
| 해시체인 무결성 | 체인 중간 레코드 삭제 후 `audit_chain_verify` 탐지 확인 |
| TSA 앵커 교차검증 | Sign 앵커와 로컬 head hash 불일치 시 경고 발생 확인 |
| 민감정보 필터 | 알려진 패턴 (API 키, 비밀번호) 주입 후 로그 확인 |
| 봉투 암호화 | secrets.json.enc 파일 직접 읽기 → 복호 불가 확인 |
| HMAC 서명 | 변조된 webhook → 검증 실패 + 거부 로그 확인 |
| TOTP 2FA | 잘못된 OTP → 로그인 거부, 올바른 OTP → 성공 |
| 백업 서명 | 백업 파일 1바이트 변경 → 복원 시 서명 검증 실패 |

---

## 10. 버전 태깅

본 기획의 완료 시 **WeruBWorker v2.4.0** 으로 릴리즈한다.
Phase 단위로 패치 릴리즈 가능 (v2.3.3 ~ v2.3.9).

| 태그 | 포함 Phase |
|------|-----------|
| v2.3.3 | Phase 2-1 (민감정보 필터 강화) |
| v2.3.4 | Phase 1-1 (로컬 해시체인) |
| v2.3.5 | Phase 1-2 + 3-1 (Sign 앵커링 + HMAC) |
| v2.3.6 | Phase 4-1 (TOTP 2FA) |
| v2.3.7 | Phase 2-2 (비밀 볼트 암호화) |
| v2.3.8 | Phase 5 (MCP 도구 확장) |
| v2.3.9 | Phase 3-2 + 6 (도구 서명 + 백업) |
| **v2.4.0** | Phase 4-2 (SSO) + 통합 검증 완료 |

---

## 11. 구현 완료 현황 (2026-08-20)

### 완료된 Phase

| Phase | 내용 | 핵심 파일 | 테스트 |
|-------|------|-----------|--------|
| **2-1** | 민감정보 필터 강화 | `security/sensitive_filter.py` | 18개 |
| **1-1** | 해시체인 (변조 탐지) | `security/hash_chain.py`, `audit.py`, `audit_ops.py` | 12개 |
| **1-2** | Sign 브릿지 (TSA 앵커링) | `security/sign_bridge.py`, `monitoring_server.py` | 9개 |
| **3-1** | Webhook HMAC 서명 | `security/hmac_signer.py` | 14개 |
| **4-1** | TOTP 2FA + step-up | `security/totp.py`, `auth.py` | 19개 |
| **2-2** | 비밀 볼트 봉투 암호화 | `security/envelope_crypto.py`, `secrets.py` | 11개 |
| **3-2** | MCP 도구 호출 서명 | `security/tool_signer.py` | 5개 |
| **5** | 보안 MCP 도구 확장 | `monitoring_server.py` (+3 도구) | 통합 |
| **6** | 백업 서명 | `monitoring/backup.py` (manifest) | 통합 |

### 신규 파일

```
coworker/security/
├── sensitive_filter.py    # 감사 로그 민감정보 마스킹 (14 패턴)
├── hash_chain.py          # SHA-256 해시체인 엔진
├── sign_bridge.py         # Sign REST API 클라이언트
├── hmac_signer.py         # Webhook HMAC 서명/검증
├── totp.py                # RFC 6238 TOTP 2FA
├── envelope_crypto.py     # AES-256-GCM 봉투 암호화
└── tool_signer.py         # 위험 도구 호출 서명
```

### 테스트 결과
- **전체**: 1343 passed, 0 failed, 74 skipped
- **신규 보안 테스트**: 88개

---

*작성: 2026-08-19 · 구현 완료: 2026-08-20 · WeruBWorker × Sign 보안 강화 프로젝트*
