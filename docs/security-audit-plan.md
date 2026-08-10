# WeruBWorker 보안 점검 보고서 및 보완 계획

## 1. 점검 결과 요약

| 영역 | 현재 상태 | 위험도 | 조치 필요 |
|------|----------|--------|----------|
| 파일 퍼미션 | ⚠️ DB/JSON 파일 644 (그룹/기타 읽기 가능) | 중간 | ✅ |
| 마스터 비밀번호 | ❌ 미설정 상태 | 높음 | ✅ |
| 암호화 볼트 | ❌ vault.json 미생성 | 중간 | ✅ |
| 환경변수 노출 | ⚠️ OPENAI_API_KEY, ANTHROPIC_API_KEY 환경에 노출 | 중간 | ✅ |
| secrets.json 암호화 | ❌ 평문 저장 (퍼미션 600으로만 보호) | 높음 | ✅ |
| CORS 설정 | ✅ localhost/tauri만 허용 | 양호 | - |
| sidecar 토큰 | ✅ 서버 시작마다 갱신, 0600 퍼미션 | 양호 | - |
| WebSocket 보안 | ✅ 프레임 16MB 제한, subprotocol 인증 | 양호 | - |
| SSRF 가드 | ✅ 내부 IP/메타데이터 차단 | 양호 | - |
| SQL Injection | ⚠️ db_mgmt.py에 f-string 쿼리 존재 | 중간 | ✅ |
| DB 비밀번호 노출 | ⚠️ mysql 명령줄에 --password=값 노출 | 중간 | ✅ |
| HTTPS 강제 | ❌ HTTP 허용 (로컬 전용이므로 낮은 위험) | 낮음 | ⚠️ |

---

## 2. 상세 점검 결과

### 2.1 🔴 높은 위험

#### A. 마스터 비밀번호 미설정

```
현재: auth.json 없음 → 모든 API 요청이 인증 없이 통과
위험: 같은 네트워크의 누구나 8765 포트에 접근하여 secrets 조회 가능
```

**보완:**
- 서비스 시작 시 마스터 비밀번호 설정 강제 (또는 강력 권고)
- 미설정 시 localhost (127.0.0.1)에서만 접근 허용
- 외부 접근 시 인증 필수

#### B. secrets.json 평문 저장

```
현재: API 키, 토큰이 JSON 평문으로 저장 (파일 퍼미션 0600으로만 보호)
위험: 디스크 접근 시 모든 자격증명 노출
  secrets.json 내용:
    provider:openai → api_key (Ollama 서버 키)
```

**보완:**
- vault.py의 Fernet 암호화를 secrets.json에도 적용
- 마스터 비밀번호 설정 시 기존 secrets를 암호화 마이그레이션
- OS 키체인(macOS Keychain, Windows Credential Manager) 연동 검토

### 2.2 🟡 중간 위험

#### C. DB/JSON 파일 퍼미션 (644)

```
현재:
  -rw-r--r--  coworker.db          ← 다른 사용자 읽기 가능
  -rw-r--r--  wiki.db              ← 다른 사용자 읽기 가능
  -rw-r--r--  automation.db        ← 다른 사용자 읽기 가능
  -rw-r--r--  inbox.json           ← 다른 사용자 읽기 가능
  -rw-r--r--  prefs.json           ← 다른 사용자 읽기 가능
  -rw-------  secrets.json         ← OK (0600)
  -rw-------  sidecar-8765.token   ← OK (0600)
```

**보완:**
- 모든 데이터 파일을 0600으로 생성
- `state_dir()` 자체를 0700으로 유지 (현재 OK: `drwx------`)
- 파일 생성 시 `os.chmod(path, 0o600)` 일괄 적용

#### D. 환경변수 API 키 노출

```
현재:
  OPENAI_API_KEY=sk-proj-***  (셸 환경에 노출)
  ANTHROPIC_API_KEY=sk-ant-*** (셸 환경에 노출)

위험: 
  - 셸 히스토리에 기록 가능
  - 하위 프로세스에 상속
  - custom endpoint 사용 시 잘못된 키 전송 가능 (이미 수정됨)
```

**보완:**
- 환경변수 대신 secrets.json에서만 키 관리 권장
- `.env` 파일 사용 시 `.gitignore`에 포함 확인
- 프로세스 시작 시 불필요한 환경변수 제거 검토

#### E. SQL Injection 위험

```python
# coworker/tools/db_mgmt.py
f"SELECT count(*) AS row_count FROM \"{tname}\";"  # tname은 DB에서 읽은 값
# coworker/wiki/store.py
f"SELECT ... WHERE page_id = ?"  # OK: 파라미터화 쿼리 사용
```

**현재 방어:**
- `db_query()`: readonly 모드에서 SELECT/SHOW/DESCRIBE/EXPLAIN만 허용
- wiki store: SQLite 파라미터화 쿼리 (`?`) 사용

**보완:**
- `db_mgmt.py`의 테이블명을 쿼테이션 대신 허용 목록으로 검증
- 사용자 입력이 직접 쿼리에 포함되는 경로 제거
- readonly 검증을 파서 기반으로 강화 (세미콜론 분리 공격 방지)

#### F. DB 비밀번호 명령줄 노출

```python
# coworker/tools/db_mgmt.py line 235
f"--password={cfg.get('password', '')}"  # ps 명령으로 볼 수 있음
```

**보완:**
- MySQL: `MYSQL_PWD` 환경변수 또는 `~/.my.cnf` 임시 파일 사용
- PostgreSQL: `PGPASSWORD` 환경변수 사용 (이미 일부 적용)
- 명령줄에 비밀번호 직접 포함 제거

### 2.3 🟢 양호

#### G. CORS

```python
# 허용 Origin: tauri://localhost, localhost, 127.0.0.1만
_ALLOWED_ORIGIN_RE = re.compile(
    r"^(tauri://localhost|https?://localhost(:\d+)?|https?://127\.0\.0\.1(:\d+)?|https?://tauri\.localhost)$"
)
```
외부 사이트에서의 크로스오리진 요청 차단.

#### H. Sidecar 토큰

- 서버 시작마다 `secrets.token_hex(32)` 생성
- 파일 퍼미션 0600
- WebSocket subprotocol로도 전달

#### I. SSRF 가드

- 내부 IP (10.x, 172.16-31.x, 192.168.x), 링크로컬, 메타데이터 엔드포인트 차단
- 모델이 제공하는 URL은 address-checked 모드로 리다이렉트 추적

#### J. WebSocket 제한

- 프레임: 16MB
- 메시지 텍스트: 200KB
- 첨부파일: 15MB
- 연결당 요청률: 30req/10sec

---

## 3. 보완 계획

### Phase 1: 즉시 조치 (파일 퍼미션 + 인증 강화)

| # | 작업 | 파일 | 위험도 |
|---|------|------|--------|
| 1 | 모든 데이터 파일 0600 퍼미션 적용 | `secrets.py`, `wiki/store.py`, 각 저장소 | 🔴 |
| 2 | 비밀번호 미설정 시 localhost 전용 바인딩 | `server/run.py` | 🔴 |
| 3 | MySQL 비밀번호 명령줄 노출 제거 | `tools/db_mgmt.py` | 🟡 |
| 4 | SQL 테이블명 검증 강화 | `tools/db_mgmt.py` | 🟡 |

### Phase 2: 암호화 강화

| # | 작업 | 파일 |
|---|------|------|
| 5 | secrets.json 암호화 옵션 (vault 기반) | `secrets.py`, `auth.py` |
| 6 | 비밀번호 설정 시 기존 secrets 자동 암호화 마이그레이션 | `auth.py` |
| 7 | OS 키체인 연동 (macOS Keychain) | `secrets.py` |

### Phase 3: 네트워크 보안

| # | 작업 | 파일 |
|---|------|------|
| 8 | TLS/HTTPS 옵션 (자체 서명 인증서) | `server/run.py` |
| 9 | IP 화이트리스트 (config.toml 설정) | `server/app.py` |
| 10 | 요청률 제한 강화 (API 엔드포인트별) | `server/app.py` |

### Phase 4: 감사 강화

| # | 작업 | 파일 |
|---|------|------|
| 11 | 자격증명 접근 감사 로그 (누가, 언제, 어떤 키) | `wiki/vault.py`, `secrets.py` |
| 12 | 로그인 실패 기록 + 잠금 (5회 실패 → 5분 잠금) | `auth.py` |
| 13 | 세션 타임아웃 설정 (config.toml) | `auth.py` |

### Phase 5: 도구 보안

| # | 작업 | 파일 |
|---|------|------|
| 14 | SSH sudo 명령 이중 확인 (auto 모드에서도) | `connectors/ssh/tools.py` |
| 15 | 위험 명령 차단 목록 (rm -rf /, mkfs 등) | `tools/shell.py` |
| 16 | DB 쓰기 쿼리 감사 로그 | `tools/db_mgmt.py` |
| 17 | 클라우드 변경 작업 감사 로그 | `tools/cloud_infra.py` |

---

## 4. 보안 체크리스트 (서비스 배포 전)

### 필수 (서비스 시작 전)

- [ ] 마스터 비밀번호 설정
- [ ] secrets.json 퍼미션 0600 확인
- [ ] 상태 디렉토리 퍼미션 0700 확인
- [ ] 불필요한 환경변수 API 키 제거
- [ ] 서버 바인딩 주소 확인 (0.0.0.0 vs 127.0.0.1)
- [ ] 방화벽: 8765 포트 외부 차단 (로컬 전용)

### 권장 (운영 중)

- [ ] 자격증명 만료일 설정 + 로테이션 알림 (위키)
- [ ] SSH 키 비밀번호 보호 확인
- [ ] DB 접속 계정 최소 권한 원칙 (SELECT만 허용하는 읽기 전용 계정)
- [ ] AWS IAM 최소 권한 (필요한 API만)
- [ ] Cloudflare API 토큰 범위 제한 (Zone별)
- [ ] 정기 보안 점검 자동화 (월 1회)

### 선택 (강화)

- [ ] TLS 인증서 설정 (자체 서명 또는 Let's Encrypt)
- [ ] IP 화이트리스트 (config.toml)
- [ ] 로그인 실패 잠금 (5회/5분)
- [ ] OS 키체인 연동

---

## 5. 현재 보안 강점

| 강점 | 설명 |
|------|------|
| **로컬 우선** | 모든 데이터가 로컬에 저장, 외부 전송 없음 |
| **텔레메트리 없음** | Cloud 제거로 사용 데이터 수집 없음 |
| **승인 기반 실행** | 위험 도구는 사용자 명시적 승인 필요 |
| **SSRF 방어** | 내부 IP/메타데이터 엔드포인트 차단 |
| **CORS 제한** | localhost/tauri만 허용 |
| **토큰 갱신** | 서버 시작마다 새 sidecar 토큰 생성 |
| **암호화 볼트** | 위키 자격증명 AES-256 암호화 지원 |
| **감사 로그** | 도구 실행 기록 (audit_store) |

---

*점검일: 2026-08-10*
*프로젝트: WeruBWorker v0.1.7*
*점검 범위: 파일 시스템, 네트워크, 인증, 데이터 저장, 도구 보안*
