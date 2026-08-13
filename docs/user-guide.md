# WeruBWorker 사용자 가이드

## 목차
1. [시작하기](#1-시작하기)
2. [기본 사용법](#2-기본-사용법)
3. [에이전트](#3-에이전트)
4. [서비스 설정](#4-서비스-설정)
5. [서비스 위키](#5-서비스-위키)
6. [자동화](#6-자동화)
7. [보안](#7-보안)
8. [관리 페이지](#8-관리-페이지)
9. [도구 레퍼런스](#9-도구-레퍼런스)
10. [문제 해결](#10-문제-해결)

---

## 1. 시작하기

### 1.1 설치

```bash
# 저장소 클론
git clone <repository-url>
cd openworker

# Python 가상환경 설정
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,messaging,browser,bedrock]"

# GUI 의존성 설치
cd surfaces/gui
npm install
```

### 1.2 AI 서버 설정

WeruBWorker는 Ollama 또는 OpenAI 호환 서버를 사용합니다.

**Ollama (로컬):**
```bash
# Ollama 설치 후
ollama pull qwen3:8b
```

**외부 Ollama 서버:**
1. 설정 → 모델 → OpenAI 프로바이더 클릭
2. API Key: 서버 키 입력
3. Custom endpoint: `https://your-server.com/ollama/v1`
4. 테스트 및 저장

### 1.3 서버 실행

```bash
# API 서버 (백엔드)
werubworker-server --host 0.0.0.0 --port 8765

# GUI 개발 서버 (프론트엔드)
cd surfaces/gui
VITE_COWORKER_API_TOKEN="$(cat ~/.config/werubworker/sidecar-8765.token)" npx vite
```

브라우저에서 `http://localhost:1420` 접속

### 1.4 첫 설정

1. 브라우저 접속 → 보안 비밀번호 설정 (선택)
2. 설정 → 모델 → AI 프로바이더 연결
3. 새 세션 시작 → 대화 시작

---

## 2. 기본 사용법

### 2.1 세션

- **새 세션**: 좌측 상단 `+ 새 세션` 버튼
- **세션 전환**: 좌측 사이드바에서 세션 클릭
- **세션 관리**: 우클릭 → 이름 변경, 고정, 보관, 삭제

### 2.2 대화

입력창에 질문이나 지시를 입력합니다:

```
"이 프로젝트의 README를 읽고 5가지 핵심 요약을 알려줘"
"테스트 스위트를 실행하고 실패 항목을 요약해줘"
"nginx 설정 파일을 확인하고 성능 최적화해줘"
```

### 2.3 권한 모드

| 모드 | 설명 |
|------|------|
| **대화** | 대화만 가능 — 파일 편집이나 명령 실행 없음 |
| **승인 요청** | 편집/명령 전에 사용자 승인 필요 (기본값) |
| **전체 접근** | 승인 없이 모든 작업 실행 |

### 2.4 파일 첨부

입력창에 파일을 드롭하거나 📎 버튼으로 첨부:
- 이미지 (PNG, JPG)
- PDF 문서
- 기타 텍스트 파일

### 2.5 언어 설정

설정 → 일반 → 언어 → 한국어 / English 전환

---

## 3. 에이전트

### 3.1 기본 에이전트

| 에이전트 | 용도 | 도구 |
|----------|------|------|
| **Cowork** | 지식작업, 분석, 보고서 | 파일, 검색, 셸, 투두 |
| **Code** | 코딩, 디버깅, 리팩토링 | 파일, Git, 검색, 셸, 투두 |
| **Chat** | 단순 대화 | 없음 (도구 없이 대화만) |
| **Ops** | 서버 운영, 인프라 관리 | 모니터링, SSH, Docker, K8s, DB, 클라우드 |
| **Dev** | 개발 관리, CI/CD | 파일, Git, 검색, CI/CD, 코드 리뷰 |

### 3.2 Ops 에이전트 사용 예시

```
"web-01 서버의 CPU 사용량 확인해줘"
"프로덕션 DB에서 최근 24시간 주문 건수 조회해줘"
"nginx 컨테이너를 재시작해줘"
"Cloudflare DNS에서 api.example.com 레코드 확인"
"Kubernetes에서 Warning 이벤트 확인"
```

### 3.3 Dev 에이전트 사용 예시

```
"GitHub Actions 빌드 상태 확인해줘"
"최신 PR의 코드 변경사항을 리뷰해줘"
"프로젝트의 보안 취약점을 스캔해줘"
"테스트 커버리지를 분석해줘"
```

### 3.4 에이전트 전환

사이드바 상단의 에이전트 이름을 클릭하여 전환합니다.

---

## 4. 서비스 설정

### 4.1 설정 페이지

사이드바 → **⚙ 서비스 설정** 에서 모든 외부 서비스 자격증명을 관리합니다.

### 4.2 SSH 서버

**등록:**
1. 서비스 설정 → SSH 서버 탭
2. `+ 서버 추가`
3. 호스트, 사용자, SSH 키 경로 입력
4. 연결 테스트 → 저장

**사용:**
```
"web-01 서버의 상태를 확인해줘"
"web-01에서 최근 nginx 로그 50줄 보여줘"
```

API:
```
POST /v1/ssh/servers     — 서버 추가
GET  /v1/ssh/servers     — 서버 목록
DELETE /v1/ssh/servers/id — 서버 삭제
POST /v1/ssh/servers/id/test — 연결 테스트
```

### 4.3 데이터베이스

**등록:**
1. 서비스 설정 → 데이터베이스 탭
2. 유형 (PostgreSQL/MySQL/SQLite), 호스트, 포트, 사용자, 비밀번호 입력
3. 저장

**사용:**
```
"프로덕션 DB에서 users 테이블의 레코드 수 확인"
"최근 주문 10건 조회해줘"
"DB 백업 실행해줘"
```

### 4.4 클라우드 (AWS/Cloudflare/Wasabi)

**AWS:**
1. Access Key ID + Secret Access Key + Region 입력
2. EC2 인스턴스, S3 버킷, CloudWatch 메트릭, 비용 분석 사용 가능

**Cloudflare:**
1. API Token + Zone ID 입력
2. DNS 레코드 관리, 트래픽 분석, 캐시 퍼지 사용 가능

**Wasabi:**
1. Access Key + Secret Key + Endpoint 입력
2. S3 호환 스토리지 관리 사용 가능

---

## 5. 서비스 위키

### 5.1 개요

서비스 접속 정보를 **위키 문서 형태**로 관리합니다. 자유롭게 작성하면 AI가 자격증명을 자동 추출합니다.

### 5.2 문서 작성

사이드바 → **📚 서비스 위키** → `+ 새 문서`

자유 형식으로 작성:
```markdown
# 프로덕션 DB 서버

PostgreSQL 데이터베이스입니다.

서버: 192.168.1.20
포트: 5432
사용자: app_user
비밀번호: MySecretPassword123

SSH 접속: deploy@192.168.1.20
```

### 5.3 AI 분석

문서 저장 시 AI가 자동으로 분석합니다:
- **호스트/IP** 감지 → 서버 설정에 연결
- **비밀번호** 감지 → 볼트에 암호화 저장
- **API 키** 감지 (sk-*, ghp-*, xoxb-* 등) → 자동 분류
- **카테고리** 자동 추천 (서버, 데이터베이스, 클라우드 등)
- **서비스 연결** 자동 추천 (database:production, ssh:server:web-01 등)

### 5.4 자격증명 관리

- **마스킹**: 비밀값은 기본적으로 `••••••••`로 표시
- **복사**: 📋 버튼 클릭 → 클립보드에 복사 (3초 후 자동 삭제)
- **보기**: 👁 버튼 클릭 → 5초간 실제 값 표시
- **로테이션**: 만료일 설정 → 자동 알림 → 새 값으로 교체
- **이력**: 모든 변경 이력 추적 (누가, 언제, 무엇을)

### 5.5 서비스 연결

문서의 `연결 서비스` 필드를 설정하면:
1. 문서의 자격증명 → `secrets.json`에 자동 동기화
2. 에이전트 도구가 해당 설정을 사용하여 서비스에 접속
3. 문서에서 원클릭 액션 (연결, 상태 확인, 백업)

### 5.6 만료 알림

위키 메인 페이지에 **⚠️ 주의 필요** 섹션에 표시:
- 🔴 만료됨
- 🟡 30일 이내 만료 예정
- 🟡 로테이션 예정

---

## 6. 자동화

### 6.1 자동화 생성

사이드바 → **⏰ 자동화** → `+ 새 자동화` 또는 템플릿 선택

### 6.2 기본 템플릿

| 템플릿 | 설명 | 주기 |
|--------|------|------|
| GitHub 요약 | PR/커밋 요약 → Slack 전송 | 매주 |
| 파이프라인 요약 | HubSpot 거래 현황 → Slack | 매주 |
| 아침 브리핑 | 캘린더 + 이메일 요약 | 매일 |
| 아침 뉴스 | 기술/세계 뉴스 5가지 요약 | 매일 |
| 인박스 요약 | 읽지 않은 이메일 요약 | 평일 |
| 폴더 정리 | 다운로드 폴더 유형별 정리 | 매주 |

### 6.3 커스텀 자동화

직접 스케줄과 지시를 설정:
```
이름: "서버 헬스체크"
스케줄: 매 5분
지시: "모든 SSH 서버 상태를 확인하고, CPU > 90%이면 Slack에 알림"
```

### 6.4 실행 관리

- **즉시 실행**: `▶ 지금 실행` 버튼
- **실행 이력**: 각 자동화의 실행 결과 확인
- **활성화/비활성화**: 토글로 일시 중지

---

## 7. 보안

### 7.1 마스터 비밀번호

첫 실행 시 마스터 비밀번호를 설정합니다 (선택사항):
- 모든 API 키, 토큰, 비밀번호 보호
- 30분 미사용 시 자동 잠금
- 비밀번호 분실 시: `~/.config/werubworker/auth.json` 삭제 후 재설정

### 7.2 데이터 저장 위치

```
~/.config/werubworker/
├── auth.json          # 비밀번호 해시 (0600)
├── secrets.json       # API 키, 토큰 (0600)
├── vault.json         # 위키 자격증명 암호화 저장
├── wiki.db            # 위키 문서 (SQLite)
├── coworker.db        # 세션 데이터
├── automation.db      # 자동화 설정
└── conversations/     # 대화 기록
```

### 7.3 프라이버시

- 모든 데이터는 로컬에 저장됩니다
- 외부 서비스 연결은 사용자가 명시적으로 설정한 경우에만
- 텔레메트리 없음
- AI 모델 API 호출은 사용자가 설정한 서버로만

### 7.4 권한 체계

| 도구 유형 | 승인 | 설명 |
|----------|------|------|
| 읽기 | 불필요 | 상태 조회, 로그, 파일 읽기 |
| 실행 | 승인 필요 | 명령 실행, 쿼리, 빌드 트리거 |
| 변경 | 승인 + 확인 | 재시작, 스케일링, DNS 변경, 배포 |
| 삭제 | 이중 확인 | 리소스 삭제, 데이터 삭제 |

---

## 8. 관리 페이지

### 8.1 사이드바 네비게이션

```
+ 새 세션
🔍 검색
⏰ 자동화

── 관리 ──
🖥 서버           — 서버 모니터링 대시보드
🔧 개발           — 개발 현황 (CI/CD, PR)
🗄 데이터베이스    — DB 관리 (쿼리, 백업)
⚙ 서비스 설정     — 자격증명 관리
📚 서비스 위키     — 서비스 문서화

── 기타 ──
🔌 커넥터         — 외부 서비스 연동
📋 활동           — 감사 로그
📥 인박스         — 승인 대기 항목
⚙ 설정           — 앱 설정
ℹ 정보           — 버전, 라이선스
```

### 8.2 서버 (OpsView)

- 로컬 서버 상태 (CPU, 메모리, 디스크)
- SSH 등록 서버 목록 및 상태
- Docker 컨테이너 목록
- 시스템 로그

### 8.3 개발 (DevView)

- GitHub 저장소 상태
- CI/CD 파이프라인 현황
- 최근 PR 목록
- Dev 세션 시작 버튼

### 8.4 데이터베이스 (DatabaseView)

- 등록된 DB 목록
- SQL 쿼리 실행기 (Ctrl+Enter)
- 테이블 목록 및 레코드 수
- 백업 실행 버튼

---

## 9. 도구 레퍼런스

### 9.1 서버 모니터링 (6개)

| 도구 | 설명 |
|------|------|
| `server_status` | CPU, 메모리, 디스크 사용량, 업타임 |
| `service_status` | systemd/launchctl 서비스 상태 |
| `check_ports` | 포트 접근성 검사 |
| `process_list` | 실행 중인 프로세스 목록 |
| `disk_usage` | 상세 디스크 사용량 |
| `system_logs` | 시스템/서비스 로그 |

### 9.2 SSH (7개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `ssh_list_servers` | 등록된 서버 목록 | ❌ |
| `ssh_execute` | 원격 명령 실행 | ✅ |
| `ssh_server_status` | 원격 서버 상태 | ❌ |
| `ssh_service_status` | 원격 서비스 상태 | ❌ |
| `ssh_read_file` | 원격 파일 읽기 | ❌ |
| `ssh_tail_log` | 원격 로그 tail | ❌ |
| `ssh_check_port` | 원격 포트 검사 | ❌ |

### 9.3 Docker (7개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `docker_ps` | 컨테이너 목록 | ❌ |
| `docker_logs` | 컨테이너 로그 | ❌ |
| `docker_restart` | 컨테이너 재시작 | ✅ |
| `docker_compose_status` | Compose 상태 | ❌ |
| `docker_compose_up` | Compose 시작 | ✅ |
| `docker_stats` | 리소스 사용량 | ❌ |
| `docker_images` | 이미지 목록 | ❌ |

### 9.4 Kubernetes (6개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `k8s_pods` | Pod 목록 및 상태 | ❌ |
| `k8s_logs` | Pod 로그 | ❌ |
| `k8s_describe` | 리소스 상세 정보 | ❌ |
| `k8s_restart` | Deployment 롤링 재시작 | ✅ |
| `k8s_scale` | Deployment 스케일링 | ✅ |
| `k8s_events` | 클러스터 이벤트 | ❌ |

### 9.5 데이터베이스 (4개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `db_query` | SQL 쿼리 실행 (SELECT는 자동, 쓰기는 승인) | 조건부 |
| `db_status` | DB 상태 (연결 수, 크기) | ❌ |
| `db_tables` | 테이블 목록 + 레코드 수 | ❌ |
| `db_backup` | 백업 생성 | ✅ |

### 9.6 클라우드 인프라 (10개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `aws_ec2_list` | EC2 인스턴스 목록 | ❌ |
| `aws_s3_list` | S3 버킷/객체 | ❌ |
| `aws_cloudwatch_metrics` | CloudWatch 메트릭 | ❌ |
| `aws_cost_explorer` | 비용 분석 | ❌ |
| `cf_dns_list` | DNS 레코드 | ❌ |
| `cf_dns_update` | DNS 변경 | ✅ |
| `cf_analytics` | 트래픽 분석 | ❌ |
| `cf_cache_purge` | 캐시 퍼지 | ✅ |
| `wasabi_list` | 객체 목록 | ❌ |
| `wasabi_upload` | 파일 업로드 | ✅ |

### 9.7 CI/CD (5개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `ci_status` | 파이프라인 상태 | ❌ |
| `ci_trigger` | 빌드 트리거 | ✅ |
| `ci_logs` | 빌드 로그 | ❌ |
| `deploy_status` | 배포 상태 | ❌ |
| `deploy_rollback` | 롤백 | ✅ |

### 9.8 코드 리뷰 (3개)

| 도구 | 설명 |
|------|------|
| `review_pr` | PR 분석 및 리뷰 |
| `review_security` | 보안 취약점 스캔 |
| `review_test_coverage` | 테스트 커버리지 분석 |

### 9.9 위키 (6개)

| 도구 | 설명 |
|------|------|
| `wiki_search` | 서비스 정보 검색 |
| `wiki_get` | 문서 조회 |
| `wiki_get_credential` | 자격증명 조회 (서비스 연결용) |
| `wiki_update` | 문서 수정 |
| `wiki_check_alerts` | 만료 알림 확인 |
| `wiki_analyze` | AI 자격증명 분석 |

---

## 10. 문제 해결

### 10.1 서버가 시작되지 않음

```bash
# 포트 충돌 확인
lsof -i:8765

# 서버 직접 실행
.venv/bin/python -m coworker.server.run --host 0.0.0.0 --port 8765
```

### 10.2 GUI가 표시되지 않음

```bash
# API 서버 확인
curl http://127.0.0.1:8765/v1/health

# 토큰 확인
cat ~/.config/werubworker/sidecar-8765.token

# GUI 재시작
TOKEN=$(cat ~/.config/werubworker/sidecar-8765.token | tr -d '\n')
VITE_COWORKER_API_TOKEN="$TOKEN" npx vite --host 0.0.0.0
```

### 10.3 모델에 연결할 수 없음

1. 설정 → 모델 → 프로바이더 확인
2. API 키 재입력
3. Custom endpoint URL 확인 (Ollama: `https://server/ollama/v1`)

### 10.4 비밀번호를 잊었을 때

```bash
# auth.json 삭제 → 비밀번호 재설정
rm ~/.config/werubworker/auth.json
# 서버 재시작
```

### 10.5 데이터 초기화

```bash
# 전체 초기화 (주의: 모든 데이터 삭제)
rm -rf ~/.config/werubworker/

# 대화 기록만 삭제
rm -rf ~/.config/werubworker/conversations/
rm ~/.config/werubworker/coworker.db
```

---

## 라이선스

MIT License. Based on [OpenWorker](https://github.com/andrewyng/openworker).

---

*WeruBWorker v0.1.7*
*최종 업데이트: 2026-08-07*

---

## v2.0 신규 기능

### 자동 모니터링
서버를 시작하면 30초마다 자동으로:
1. 로컬 서버 메트릭 수집 (CPU, 메모리, 디스크, 네트워크, 로드)
2. 등록된 SSH 서버 메트릭 병렬 수집
3. 헬스체크 실행 (HTTP/TCP/DNS/Ping/SSL/Docker/K8s/Process)
4. 알림 규칙 평가 및 자동 발송

### 대시보드 API
```
GET /v1/dashboard/overview      # 전체 현황
GET /v1/dashboard/servers/{id}/metrics?range=1h  # 시계열
GET /v1/dashboard/alerts        # 알림 피드
GET /v1/dashboard/incidents     # 인시던트 목록
GET /v1/dashboard/audit         # 감사 로그
GET /v1/infrastructure/servers  # 서버 목록
GET /v1/infrastructure/topology # 의존관계 맵
```

### SRE 에이전트 사용법
세션에서 SRE 페르소나를 선택하면 21개 capability(100+ 도구)를 사용할 수 있습니다.
- "서버 상태 확인해줘" → server_status + metrics_latest
- "CPU 90% 이상 알림 설정해줘" → alert_add_rule
- "헬스체크 추가해줘 https://api.example.com/health" → healthcheck_add
- "인시던트 생성해줘" → incidents 도구

### 서비스 시작/관리
```bash
./start.sh              # 시작 (백엔드 + 프론트엔드)
./start.sh --stop       # 중지
./start.sh --restart    # 재시작
./start.sh --status     # 상태 확인
```

### Wiki 리포지토리
서비스 위키는 설정의 중앙 저장소 역할:
- 서버 등록 시 Wiki 페이지 자동 생성 (category: server)
- DB 등록 시 스키마 문서화 + ERD (category: database)
- 서비스 설정 파일 버전 관리 (category: config)
- 도구 실행 결과가 Wiki에 자동 동기화 (WikiAutoSync)

### 멀티 클라우드
- AWS (EC2, S3, CloudWatch, 비용, RDS, ELB, Route53, IAM)
- Cloudflare (DNS, 캐시, 분석)
- GCP (Compute Engine, GKE) — pip install werubworker[gcp]
- Azure (VM, AKS) — pip install werubworker[azure]
