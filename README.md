# WeruBWorker

**로컬 우선 AI 에이전트 플랫폼** — 서버 관리, 개발 관리, 인프라 운영을 위한 통합 도구

> 📌 [OpenWorker](https://github.com/andrewyng/openworker) (MIT License) 기반으로 독립 개발

---

## 📋 목차

- [주요 기능](#-주요-기능)
- [아키텍처](#-아키텍처)
- [에이전트](#-에이전트)
- [도구 (54개)](#-도구-54개)
- [빠른 시작](#-빠른-시작)
- [GUI 페이지](#-gui-페이지)
- [보안](#-보안)
- [테스트](#-테스트)
- [문서](#-문서)
- [라이선스](#-라이선스)

---

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| 🤖 **다중 모델 지원** | Ollama, OpenAI 호환 서버, 자체 AI 서버 연동. 모델별 역할 라벨 자동 표시 |
| 🖥 **서버 관리** | SSH 원격 접속, Docker 컨테이너, Kubernetes 클러스터, 시스템 모니터링 |
| 🔧 **개발 관리** | GitHub Actions CI/CD, PR 코드 리뷰, 보안 스캔, 테스트 커버리지 분석 |
| 🗄 **데이터베이스** | PostgreSQL / MySQL / SQLite 쿼리 실행, 상태 확인, 자동 백업 |
| ☁️ **클라우드 인프라** | AWS (EC2, S3, CloudWatch, 비용), Cloudflare (DNS, 캐시), Wasabi 스토리지 |
| 📚 **서비스 위키** | 자격증명 문서화, AI 자동 추출, AES-256 암호화 볼트, 만료 알림 |
| 🔐 **보안** | 마스터 비밀번호 로그인, 암호화 저장, 감사 로그, 권한 계층 |
| 🌐 **한국어 지원** | 전체 UI 한국어/영어 전환 (1,100+ 번역 키), 에이전트 한국어 응답 |
| 📊 **실시간 모니터링** | CPU/메모리/디스크 차트, 10초 자동 폴링, 스파크라인 그래프 |
| 🔗 **25+ 서비스 연동** | Slack, GitHub, Gmail, Jira, HubSpot, Notion, Linear 등 |

---

## 🏗 아키텍처

### 전체 시스템 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                        WeruBWorker                              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    GUI (React + Vite)                     │    │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │    │
│  │  │Sidebar  │ │Transcript│ │Composer  │ │ RightRail  │  │    │
│  │  │Sessions │ │Messages  │ │Input     │ │ Progress   │  │    │
│  │  │Nav      │ │Tools     │ │Attach    │ │ Artifacts  │  │    │
│  │  └─────────┘ └──────────┘ └──────────┘ └────────────┘  │    │
│  │  ┌──────────────────────────────────────────────────┐   │    │
│  │  │ 관리 페이지: Ops | Dev | DB | ServiceConfig | Wiki│   │    │
│  │  └──────────────────────────────────────────────────┘   │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │ WebSocket + REST API                │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │                FastAPI 서버 (Python)                      │    │
│  │                                                          │    │
│  │  ┌──────────┐  ┌───────────┐  ┌─────────────────────┐  │    │
│  │  │ Session  │  │ Turn      │  │ Permission          │  │    │
│  │  │ Manager  │  │ Engine    │  │ Engine              │  │    │
│  │  │ (6 Mixin)│  │ (비동기)   │  │ (승인/거부/자동허용) │  │    │
│  │  └────┬─────┘  └─────┬─────┘  └─────────────────────┘  │    │
│  │       │              │                                   │    │
│  │  ┌────▼──────────────▼──────────────────────────────┐   │    │
│  │  │              도구 카탈로그 (54개)                   │   │    │
│  │  ├──────┬──────┬──────┬──────┬──────┬──────┬────────┤   │    │
│  │  │서버  │SSH   │Docker│ K8s  │  DB  │클라우드│CI/CD  │   │    │
│  │  │모니터│원격  │컨테이너│클러스터│쿼리  │AWS/CF │빌드   │   │    │
│  │  │(6)  │(7)   │(7)   │(6)   │(4)   │(10)  │(5)    │   │    │
│  │  ├──────┴──────┴──────┴──────┴──────┴──────┴────────┤   │    │
│  │  │코드리뷰(3) │ 위키(6)  │ 파일/셸/검색/Git/투두     │   │    │
│  │  └──────────────────────────────────────────────────┘   │    │
│  │                                                          │    │
│  │  ┌──────────────────────────────────────────────────┐   │    │
│  │  │              저장소                                │   │    │
│  │  │  secrets.json │ vault.json │ wiki.db │ coworker.db│   │    │
│  │  │  (API 키)     │ (암호화)   │ (문서)  │ (세션)     │   │    │
│  │  └──────────────────────────────────────────────────┘   │    │
│  └──────────────────────────────────────────────────────────┘    │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │              외부 서비스 연동                             │    │
│  │  Ollama │ Slack │ GitHub │ Gmail │ AWS │ Cloudflare │...│    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 기술 스택

| 계층 | 기술 |
|------|------|
| **프론트엔드** | React 18, TypeScript, Vite, Tailwind CSS |
| **백엔드** | Python 3.10+, FastAPI, uvicorn, asyncio |
| **데스크톱** | Tauri (Rust) |
| **음성 인식** | Whisper-rs (Rust, 로컬 오프라인) |
| **데이터베이스** | SQLite (세션, 위키, 자동화) + JSONL (대화 기록) |
| **인증** | PBKDF2-SHA256 (마스터 비밀번호) + Fernet AES-256 (볼트) |
| **i18n** | react-i18next (7 네임스페이스, 1,100+ 키) |

### 데이터 흐름

```
사용자 입력 (GUI)
  → WebSocket → FastAPI 서버
    → SessionManager → TurnEngine
      → ProviderRouter → AI 모델 (Ollama 등)
        ← 스트리밍 응답
      → ToolRegistry → 도구 실행 (승인 확인)
        ← 결과
    ← WebSocket 이벤트 (23종)
  ← GUI 실시간 렌더링
```

### 디렉토리 구조

```
werubworker/
├── coworker/                      # Python 백엔드
│   ├── agents/                    # 에이전트 정의
│   │   ├── code.py               #   Code (코딩)
│   │   ├── cowork.py             #   Cowork (지식작업)
│   │   ├── chat.py               #   Chat (대화)
│   │   ├── ops.py                #   Ops (서버 운영)
│   │   └── dev.py                #   Dev (개발 관리)
│   ├── tools/                     # 도구 모듈 (54개)
│   │   ├── server_monitor.py     #   서버 모니터링 (6)
│   │   ├── docker_mgmt.py        #   Docker 관리 (7)
│   │   ├── k8s_mgmt.py           #   Kubernetes (6)
│   │   ├── db_mgmt.py            #   데이터베이스 (4)
│   │   ├── cloud_infra.py        #   클라우드 인프라 (10)
│   │   ├── ci_cd.py              #   CI/CD (5)
│   │   ├── code_review.py        #   코드 리뷰 (3)
│   │   ├── shell.py              #   셸 명령
│   │   ├── files.py              #   파일 읽기/쓰기
│   │   └── ...
│   ├── connectors/                # 외부 서비스 연동 (25+)
│   │   ├── ssh/                  #   SSH 커넥터 (7 도구 + API)
│   │   ├── tools/                #   커넥터별 도구 모듈 (29파일)
│   │   └── ...
│   ├── wiki/                      # 서비스 위키
│   │   ├── store.py              #   SQLite 저장소
│   │   ├── vault.py              #   암호화 볼트 (AES-256)
│   │   ├── analyzer.py           #   AI 문서 분석기
│   │   ├── sync.py               #   secrets.json 동기화
│   │   └── tools.py              #   에이전트 도구 (6)
│   ├── server/                    # FastAPI 서버
│   │   ├── app.py                #   API 엔드포인트
│   │   ├── manager.py            #   세션 관리 (코어)
│   │   ├── settings_mixin.py     #   설정 관리
│   │   ├── connector_mixin.py    #   커넥터 관리
│   │   ├── automation_mixin.py   #   자동화 관리
│   │   ├── inbox_mixin.py        #   인박스 관리
│   │   ├── skills_mixin.py       #   스킬 관리
│   │   └── cloud_manager.py      #   (비활성화)
│   ├── providers/                 # AI 모델 프로바이더
│   │   ├── openai_provider.py    #   OpenAI 호환 (Ollama 포함)
│   │   ├── anthropic_provider.py #   Claude
│   │   ├── gemini_provider.py    #   Gemini
│   │   └── ...
│   ├── auth.py                    # 로그인/인증
│   ├── catalog.py                 # 도구 카탈로그 (Capability 등록)
│   ├── engine.py                  # 에이전트 턴 엔진
│   └── agent.py                   # 엔진 조립 + 언어 지시
│
├── surfaces/gui/                  # React 프론트엔드
│   ├── src/
│   │   ├── App.tsx               #   메인 앱 (AuthGate → AppInner)
│   │   ├── contexts/             #   React Context
│   │   │   ├── AuthContext.tsx   #     인증 상태
│   │   │   ├── SettingsContext.tsx#    설정 상태
│   │   │   └── UIContext.tsx     #     UI 상태
│   │   ├── components/           #   UI 컴포넌트
│   │   │   ├── OpsView.tsx       #     서버 모니터링 (실시간 차트)
│   │   │   ├── DevView.tsx       #     개발 대시보드
│   │   │   ├── DatabaseView.tsx  #     DB 관리 (쿼리 실행기)
│   │   │   ├── ServiceConfigView.tsx # 서비스 설정
│   │   │   ├── WikiView.tsx      #     서비스 위키
│   │   │   ├── AboutView.tsx     #     정보/릴리스
│   │   │   ├── LoginView.tsx     #     로그인
│   │   │   ├── MiniChart.tsx     #     SVG 스파크라인
│   │   │   ├── ProgressBar.tsx   #     진행 바
│   │   │   ├── ErrorBoundary.tsx #     에러 보호
│   │   │   └── ...
│   │   ├── i18n/                 #   다국어 (한국어/영어)
│   │   │   └── locales/
│   │   │       ├── en/ (7 파일)  #     영어
│   │   │       └── ko/ (7 파일)  #     한국어
│   │   └── api.ts                #   REST/WebSocket API
│   └── src-tauri/                #   Tauri 데스크톱 셸
│
├── tests/                         # 테스트 (1,161 passed)
│   ├── test_auth.py              #   인증 (14)
│   ├── test_wiki.py              #   위키 + 볼트 + 분석기 (24)
│   ├── test_server_monitor.py    #   서버 모니터링 (12)
│   ├── test_docker_tools.py      #   Docker (10)
│   ├── test_k8s_tools.py         #   Kubernetes (12)
│   ├── test_db_tools.py          #   데이터베이스 (9)
│   ├── test_cloud_infra.py       #   클라우드 (7)
│   ├── test_ci_cd.py             #   CI/CD (10)
│   ├── test_code_review.py       #   코드 리뷰 (6)
│   ├── test_ssh_connector.py     #   SSH (10)
│   ├── test_ops_agent.py         #   Ops 에이전트 (4)
│   ├── test_dev_agent.py         #   Dev 에이전트 (4)
│   └── ... (기존 93 테스트 파일)
│
└── docs/                          # 문서 (11종)
    ├── user-guide.md             #   사용자 가이드
    ├── architecture-analysis.md  #   아키텍처 분석
    ├── implementation-roadmap.md #   구현 로드맵
    └── ...
```

---

## 🤖 에이전트

### 5개 에이전트

| 에이전트 | 용도 | 도구 | 특징 |
|----------|------|------|------|
| **Cowork** | 지식작업, 분석, 보고서 | 파일, 검색, 셸, 투두 | 다중 루트 워크스페이스 |
| **Code** | 코딩, 디버깅, 리팩토링 | 파일, Git, 검색, 셸, 투두 | explorer 서브에이전트 |
| **Chat** | 단순 대화, 질문 답변 | 없음 | 도구 없이 대화만 |
| **Ops** | 서버 운영, 인프라 관리 | 모니터링, SSH, Docker, K8s, DB, 클라우드 (30개) | 승인 기반 실행 |
| **Dev** | 개발 관리, CI/CD | 파일, Git, CI/CD, 코드 리뷰 (8개) | PR 분석, 보안 스캔 |

모든 에이전트는 한국어로 응답합니다.

---

## 🔧 도구 (54개)

### 서버 모니터링 (6개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `server_status` | CPU, 메모리, 디스크 사용량, 업타임 | - |
| `service_status` | systemd/launchctl 서비스 상태 | - |
| `check_ports` | 포트 접근성 검사 | - |
| `process_list` | 실행 중인 프로세스 목록 | - |
| `disk_usage` | 상세 디스크 사용량 | - |
| `system_logs` | 시스템/서비스 로그 | - |

### SSH 원격 접속 (7개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `ssh_list_servers` | 등록된 서버 목록 | - |
| `ssh_execute` | 원격 명령 실행 | ✅ |
| `ssh_server_status` | 원격 서버 상태 | - |
| `ssh_service_status` | 원격 서비스 상태 | - |
| `ssh_read_file` | 원격 파일 읽기 | - |
| `ssh_tail_log` | 원격 로그 tail | - |
| `ssh_check_port` | 원격 포트 검사 | - |

### Docker 컨테이너 (7개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `docker_ps` | 컨테이너 목록 | - |
| `docker_logs` | 컨테이너 로그 | - |
| `docker_restart` | 컨테이너 재시작 | ✅ |
| `docker_compose_status` | Compose 서비스 상태 | - |
| `docker_compose_up` | Compose 시작 | ✅ |
| `docker_stats` | 리소스 사용량 | - |
| `docker_images` | 이미지 목록 | - |

### Kubernetes 클러스터 (6개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `k8s_pods` | Pod 목록 및 상태 | - |
| `k8s_logs` | Pod 로그 | - |
| `k8s_describe` | 리소스 상세 정보 | - |
| `k8s_restart` | Deployment 롤링 재시작 | ✅ |
| `k8s_scale` | Deployment 스케일링 | ✅ |
| `k8s_events` | 클러스터 이벤트 | - |

### 데이터베이스 (4개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `db_query` | SQL 쿼리 실행 (SELECT 자동, 쓰기는 승인) | 조건부 |
| `db_status` | DB 상태 (연결 수, 크기) | - |
| `db_tables` | 테이블 목록 + 레코드 수 | - |
| `db_backup` | 백업 생성 (pg_dump/mysqldump) | ✅ |

### 클라우드 인프라 (10개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `aws_ec2_list` | EC2 인스턴스 목록 | - |
| `aws_s3_list` | S3 버킷/객체 | - |
| `aws_cloudwatch_metrics` | CloudWatch 메트릭 | - |
| `aws_cost_explorer` | 비용 분석 | - |
| `cf_dns_list` | Cloudflare DNS 레코드 | - |
| `cf_dns_update` | DNS 변경 | ✅ |
| `cf_analytics` | 트래픽 분석 | - |
| `cf_cache_purge` | 캐시 퍼지 | ✅ |
| `wasabi_list` | Wasabi 객체 목록 | - |
| `wasabi_upload` | 파일 업로드 | ✅ |

### CI/CD 파이프라인 (5개)

| 도구 | 설명 | 승인 |
|------|------|------|
| `ci_status` | GitHub Actions 워크플로우 상태 | - |
| `ci_trigger` | 빌드 트리거 | ✅ |
| `ci_logs` | 빌드 로그 | - |
| `deploy_status` | 배포 상태 | - |
| `deploy_rollback` | 롤백 | ✅ |

### 코드 리뷰 (3개)

| 도구 | 설명 |
|------|------|
| `review_pr` | PR 코드 변경사항 분석 및 리뷰 |
| `review_security` | 보안 취약점 스캔 (하드코딩된 키, SQL injection) |
| `review_test_coverage` | 테스트 커버리지 분석 |

### 서비스 위키 (6개)

| 도구 | 설명 |
|------|------|
| `wiki_search` | 서비스 정보 검색 |
| `wiki_get` | 문서 조회 (자격증명 마스킹) |
| `wiki_get_credential` | 자격증명 값 조회 (서비스 연결용) |
| `wiki_update` | 문서 수정 |
| `wiki_check_alerts` | 만료 임박 자격증명 알림 |
| `wiki_analyze` | AI 문서 분석 (호스트/비밀번호/토큰 자동 추출) |

---

## 🚀 빠른 시작

### 요구사항

- Python 3.10+
- Node.js 20+
- Ollama 또는 OpenAI 호환 AI 서버

### 설치

```bash
# 1. 클론
git clone https://github.com/seanshin/werubworker.git
cd werubworker

# 2. Python 가상환경
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,messaging,browser,bedrock]"

# 3. GUI 의존성
cd surfaces/gui && npm install && cd ../..
```

### 실행

```bash
# API 서버 (터미널 1)
.venv/bin/python -m coworker.server.run --host 0.0.0.0 --port 8765

# GUI 서버 (터미널 2)
TOKEN=$(cat ~/.config/werubworker/sidecar-8765.token | tr -d '\n')
cd surfaces/gui && VITE_COWORKER_API_TOKEN="$TOKEN" npx vite --host 0.0.0.0
```

### 접속

브라우저에서 **http://localhost:1420** 접속

### AI 모델 설정

1. 설정 → 모델 → OpenAI 프로바이더 클릭
2. Custom endpoint에 Ollama 서버 URL 입력 (예: `https://your-server/ollama/v1`)
3. API Key 입력 → 테스트 및 저장

---

## 📱 GUI 페이지

| 페이지 | 아이콘 | 설명 |
|--------|--------|------|
| **서버** | 🔧 | CPU/메모리/디스크 실시간 차트, SSH 서버 목록, Docker 컨테이너 |
| **개발** | 💻 | GitHub 상태, CI/CD 파이프라인, PR 목록 |
| **데이터베이스** | 🗄 | SQL 쿼리 실행기, 테이블 목록, 백업 |
| **서비스 설정** | ⚙️ | SSH/DB/클라우드 자격증명 통합 관리 |
| **서비스 위키** | 📚 | 서비스 문서화, AI 자격증명 추출, 만료 알림 |
| **정보** | ℹ️ | 버전, 릴리스 노트, 기술 스택, 라이선스 |
| **자동화** | ⏰ | 스케줄 작업, 템플릿, 실행 이력 |

---

## 🔐 보안

| 계층 | 방식 |
|------|------|
| **앱 인증** | 마스터 비밀번호 (PBKDF2-SHA256, 30분 자동 잠금) |
| **자격증명 저장** | AES-256 암호화 볼트 (`vault.json`) |
| **API 인증** | Sidecar 토큰 (`X-WeruBWorker-Token` 헤더) |
| **도구 권한** | 읽기(자동) → 실행(승인) → 변경(확인) → 삭제(이중 확인) |
| **데이터 보호** | 모든 데이터 로컬 저장, 텔레메트리 없음 |

### 데이터 저장 위치

```
~/.config/werubworker/
├── auth.json          # 비밀번호 해시 (0600)
├── secrets.json       # API 키, 토큰 (0600)
├── vault.json         # 위키 자격증명 (AES-256)
├── wiki.db            # 위키 문서 (SQLite)
├── coworker.db        # 세션 데이터
├── automation.db      # 자동화 설정
├── prefs.json         # 사용자 환경설정
└── conversations/     # 대화 기록 (JSONL)
```

---

## 🧪 테스트

```bash
# 전체 테스트 실행
.venv/bin/pytest tests/ -q
# 1,161 passed, 74 skipped

# TypeScript 검증
cd surfaces/gui && npx tsc --noEmit
```

| 테스트 파일 | 테스트 수 | 대상 |
|------------|-----------|------|
| test_auth.py | 14 | 로그인/인증 |
| test_wiki.py | 24 | 위키 + 볼트 + AI 분석기 |
| test_server_monitor.py | 12 | 서버 모니터링 |
| test_docker_tools.py | 10 | Docker |
| test_k8s_tools.py | 12 | Kubernetes |
| test_db_tools.py | 9 | 데이터베이스 |
| test_cloud_infra.py | 7 | AWS/CF/Wasabi |
| test_ci_cd.py | 10 | CI/CD |
| test_code_review.py | 6 | 코드 리뷰 |
| test_ssh_connector.py | 10 | SSH |
| test_ops_agent.py | 4 | Ops 에이전트 |
| test_dev_agent.py | 4 | Dev 에이전트 |
| 기존 테스트 | 1,039 | 코어 기능 |

---

## 📖 문서

| 문서 | 설명 |
|------|------|
| [사용자 가이드](docs/user-guide.md) | 설치, 사용법, 도구 레퍼런스, 문제 해결 |
| [아키텍처 분석](docs/architecture-analysis.md) | 전체 시스템 구조, 코드 분석 |
| [구현 로드맵](docs/implementation-roadmap.md) | 개발 계획, Batch 구조 |
| [Ops 에이전트](docs/ops-agent-expansion-plan.md) | 서버 관리 에이전트 설계 |
| [SSH 커넥터](docs/ssh-connector-plan.md) | SSH 모듈 설계 |
| [개발/서버관리](docs/devops-management-plan.md) | DevOps 도구 확장 |
| [서비스 위키](docs/wiki-credentials-plan.md) | 위키 + 자격증명 관리 |
| [로그인/인증](docs/auth-login-plan.md) | 보안 인증 설계 |
| [Cloud 대체](docs/cloud-replacement-plan.md) | Cloud 독립 운영 |
| [기업 서비스](docs/enterprise-service-plan.md) | WeruB Service 계획 |
| [한국어 i18n](docs/i18n-korean-plan.md) | 다국어 지원 설계 |

---

## 📄 라이선스

MIT License

[OpenWorker](https://github.com/andrewyng/openworker) 기반으로 독립적으로 수정 및 확장되었습니다.
