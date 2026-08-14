# WeruBWorker v2.2

**AI 에이전트 기반 통합 클라우드·서버 관리 및 운영 모니터링 플랫폼**

서비스 위키를 중앙 설정 리포지토리로 활용하여 서버·DB·서비스 설정 정보를 세션에서 저장·분석하고, 실 서비스 연동 시 자동으로 참조하는 로컬 우선 운영 플랫폼입니다.

[![Version](https://img.shields.io/badge/version-2.2.0-blue)]()
[![Tests](https://img.shields.io/badge/tests-1%2C232%20passed-brightgreen)]()
[![Tools](https://img.shields.io/badge/tools-100%2B-orange)]()
[![Capabilities](https://img.shields.io/badge/capabilities-23-purple)]()
[![MCP](https://img.shields.io/badge/MCP-12%20tools-blueviolet)]()

> 📌 [OpenWorker](https://github.com/andrewyng/openworker) (MIT License) 기반으로 독립 개발

---

## 📋 목차

- [서비스 비전](#-서비스-비전)
- [주요 기능](#-주요-기능)
- [아키텍처](#-아키텍처)
- [서비스 위키 리포지토리](#-서비스-위키--설정-리포지토리)
- [에이전트](#-에이전트)
- [도구 (54개+)](#-도구-54개)
- [확장 로드맵](#-확장-로드맵)
- [개발팀 구성](#-개발팀-구성)
- [빠른 시작](#-빠른-시작)
- [GUI 페이지](#-gui-페이지)
- [보안](#-보안)
- [테스트](#-테스트)
- [문서](#-문서)
- [라이선스](#-라이선스)

---

## 🎯 서비스 비전

**WeruBWorker Ops Platform** — AI 에이전트가 인프라를 관리하고, 서비스 위키가 모든 설정의 단일 진실 소스(Single Source of Truth)가 되는 통합 운영 플랫폼

### 핵심 설계 철학

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

### 5대 핵심 영역

| 영역 | 설명 | 상태 |
|------|------|------|
| **통합 모니터링** | 멀티 서버 메트릭 수집, 시계열 DB, 헬스체크, 로그 집계 | ✅ 구현 완료 |
| **실시간 대시보드** | REST API 12개 엔드포인트, 인프라 토폴로지 맵, Wiki API | ✅ 구현 완료 |
| **알림 & 인시던트** | 규칙 기반 알림, 에스컬레이션, 인시던트 타임라인, 자동 복구 | ✅ 구현 완료 |
| **인프라 자동화** | Terraform/Ansible IaC, 서비스 설정 생성, 서버 온보딩 워크플로우 | ✅ 구현 완료 |
| **보안 & 컴플라이언스** | 포트/SSL 스캔, 취약점 검사, 접근 감사, 인증서 관리 | ✅ 구현 완료 |
| **멀티 클라우드** | AWS + Cloudflare + Wasabi + GCP + Azure (선택적 SDK) | ✅ 구현 완료 |

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
| 📋 **서비스 위키 리포지토리** | 서버/DB/서비스 설정의 중앙 저장소, 자동 문서화, 서비스 연동 허브 |
| 🔔 **알림 & 인시던트** | 임계값 기반 알림, 에스컬레이션, 자동 복구, AI 사후분석 (확장 중) |
| 🏗 **서버 온보딩** | SSH 연결 테스트 → 정보 수집 → Wiki 자동 생성 워크플로우 |
| ⚙️ **설정 자동 생성** | Nginx, systemd, Docker Compose 설정 생성 및 버전 관리 (확장 중) |

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
│  │  │           도구 카탈로그 (100+, 21 Capability)        │   │    │
│  │  ├──────┬──────┬──────┬──────┬──────┬──────┬────────┤   │    │
│  │  │서버  │SSH   │Docker│ K8s  │  DB  │클라우드│CI/CD  │   │    │
│  │  │모니터│원격  │컨테이너│클러스터│쿼리  │AWS/GCP│빌드   │   │    │
│  │  │(8)  │(7)   │(11)  │(11)  │(4)   │(18)  │(5)    │   │    │
│  │  ├──────┼──────┼──────┼──────┼──────┼──────┼────────┤   │    │
│  │  │모니터│보안  │네트워│인증서 │IaC   │서버  │서비스  │   │    │
│  │  │링   │스캔  │크진단│관리  │TF/AN │온보딩│설정   │   │    │
│  │  │(10) │(5)   │(5)   │(3)   │(5)   │(4)  │(5)    │   │    │
│  │  ├──────┴──────┴──────┴──────┴──────┴──────┴────────┤   │    │
│  │  │코드리뷰(3) │ 위키(13) │ 개발환경(3) │ 기타       │   │    │
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
│   ├── monitoring/                # 모니터링 서브시스템 (v2.0)
│   │   ├── timeseries.py         #   시계열 저장소 (4단계 다운샘플링)
│   │   ├── collector.py          #   멀티 서버 메트릭 수집기
│   │   ├── healthcheck.py        #   8종 헬스체크 매니저
│   │   ├── alerting.py           #   규칙 기반 알림 엔진
│   │   ├── incidents.py          #   인시던트 관리 + 타임라인
│   │   ├── remediation.py        #   자동 복구 엔진 (7 기본 액션)
│   │   ├── log_aggregator.py     #   다중 서버 로그 집계
│   │   └── audit_ops.py          #   운영 감사 로그
│   ├── agents/                    # 에이전트 정의 (11개 페르소나)
│   │   ├── code.py / cowork.py / chat.py / ops.py / dev.py
│   │   └── sre.py                #   SRE (21 capability, 100+ 도구)
│   ├── tools/                     # 도구 모듈 (100+)
│   │   ├── server_monitor.py     #   서버 모니터링 (8)
│   │   ├── docker_mgmt.py        #   Docker 관리 (11)
│   │   ├── k8s_mgmt.py           #   Kubernetes (11)
│   │   ├── db_mgmt.py            #   데이터베이스 (4)
│   │   ├── cloud_infra.py        #   클라우드 인프라 (18 + GCP/Azure)
│   │   ├── monitoring_tools.py   #   모니터링 도구 (10)
│   │   ├── server_setup.py       #   서버 온보딩 (4)
│   │   ├── service_config.py     #   서비스 설정 (5)
│   │   ├── security_scan.py      #   보안 스캔 (5)
│   │   ├── network_diag.py       #   네트워크 진단 (5)
│   │   ├── iac.py                #   IaC - Terraform/Ansible (5)
│   │   ├── cert_mgmt.py          #   인증서 관리 (3)
│   │   ├── dev_setup.py          #   개발 환경 (3)
│   │   ├── ci_cd.py / code_review.py / shell.py / files.py
│   │   └── ...
│   ├── connectors/                # 외부 서비스 연동 (25+)
│   │   ├── ssh/                  #   SSH 커넥터 (7 도구 + 터널링)
│   │   ├── cloud/gcp.py          #   GCP (Compute, GKE)
│   │   ├── cloud/azure.py        #   Azure (VM, AKS)
│   │   ├── tools/                #   커넥터별 도구 모듈 (29파일)
│   │   └── ...
│   ├── wiki/                      # 서비스 위키 (설정 리포지토리)
│   │   ├── store.py              #   SQLite 저장소 (15 카테고리)
│   │   ├── vault.py              #   암호화 볼트 (AES-256)
│   │   ├── analyzer.py           #   AI 문서 분석기
│   │   ├── sync.py               #   WikiAutoSync (도구→Wiki 동기화)
│   │   ├── resolver.py           #   ServiceResolver (자연어 해석)
│   │   └── tools.py              #   에이전트 도구 (13)
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
│   ├── catalog.py                 # 도구 카탈로그 (23 Capability)
│   ├── engine.py                  # 에이전트 턴 엔진 (+WikiAutoSync hook)
│   ├── registry.py                # ServiceRegistry (서비스 참조 해석)
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
├── tests/                         # 테스트 (1,226 passed)
│   ├── test_timeseries.py        #   시계열 저장소 (11)
│   ├── test_collector.py         #   메트릭 수집기 (7)
│   ├── test_healthcheck_mgr.py   #   헬스체크 매니저 (12)
│   ├── test_alerting.py          #   알림 엔진 (11)
│   ├── test_incidents.py         #   인시던트 관리 (9)
│   ├── test_remediation.py       #   자동 복구 (7)
│   ├── test_audit_ops.py         #   운영 감사 (5)
│   ├── test_wiki_resolver.py     #   서비스 리졸버 (6)
│   └── ... (기존 93 + 신규 8 테스트 파일)
│
├── start.sh                       # 서비스 시작/중지/재시작 스크립트
│
└── docs/                          # 문서
    ├── v2-architecture.md        #   v2.0 아키텍처
    ├── v2-api-reference.md       #   v2.0 API 레퍼런스
    ├── cloud-server-ops-expansion-design.md  #   확장 설계서
    ├── dev-team/                 #   개발팀 조율 가이드
    └── ... (기존 문서)
```

---

## 📚 서비스 위키 = 설정 리포지토리

서비스 위키의 핵심 목적은 단순 문서가 아니라, 모든 인프라·서비스 설정 정보를 **세션에서 저장하고, 분석하고, 실 서비스 연동 시 활용하는 중앙 리포지토리**입니다.

### 3대 핵심 역할

| 역할 | 설명 | 기반 기술 |
|------|------|----------|
| **저장 (Store)** | 서버/DB/서비스/API 키/인증서/배포 설정을 `structured_data` JSON으로 구조화 저장 | SQLite + FTS5 + Vault |
| **분석 (Analyze)** | 의존관계 분석, 변경 추적, 만료 감지, 스키마 비교, 보안 감사 | ServiceRegistry + WikiAutoSync |
| **연동 (Connect)** | SSH 접속/DB 연결/배포 시 Wiki에서 설정 자동 로드, 자연어 서비스 참조 해석 | ServiceResolver + linked_service |

### Wiki 카테고리 체계

| 카테고리 | 용도 | 자동 생성 |
|---------|------|----------|
| `server` | 서버 연결 정보, OS, 실행 서비스 | `register_server()` 시 |
| `database` | DB 설정, 스키마, ERD, 백업 정책 | `register_database()` 시 |
| `service` | 서비스 설정, 헬스체크, 의존관계 | `register_service()` 시 |
| `config` | Nginx/systemd/Compose 설정 파일 (버전 관리) | 설정 생성 시 |
| `runbook` | 배포/장애 대응 런북 (단계별 실행 추적) | `setup_deployment()` 시 |
| `development` | 개발 환경, 기술 스택, Git 연동 | `create_dev_wiki()` 시 |
| `cloud` | 클라우드 제공자 계정, 리전, 서비스 | 수동 |
| `api_doc` | API 문서, 엔드포인트, 인증 | 수동 |
| `incident` | 인시던트 보고서, 타임라인, RCA | AI 자동 생성 |
| `architecture` | 시스템 아키텍처, 컴포넌트, 데이터 흐름 | 수동 |

---

## 📈 확장 로드맵

### Phase 1: 기반 강화 ✅

| 모듈 | 파일 | 설명 |
|------|------|------|
| 시계열 저장소 | `monitoring/timeseries.py` | SQLite 기반 다운샘플링 (1m→5m→1h→1d) |
| 메트릭 수집기 | `monitoring/collector.py` | SSH 병렬 수집, asyncio |
| 알림 엔진 | `monitoring/alerting.py` | 규칙 평가 + Slack/Telegram 발송 |
| 헬스체크 매니저 | `monitoring/healthcheck.py` | HTTP/TCP/DNS/SSL/Docker/K8s 체크 |
| 서버 모니터 확장 | `tools/server_monitor.py` | 원격 서버 + GPU + 네트워크 통계 |

### Phase 2: 운영 자동화 ✅

| 모듈 | 파일 | 설명 |
|------|------|------|
| 인시던트 관리 | `monitoring/incidents.py` | 타임라인 + 에스컬레이션 + AI 사후분석 |
| 자동 복구 | `monitoring/remediation.py` | 디스크 정리, 서비스 재시작, Pod 삭제 |
| 로그 집계 | `monitoring/log_aggregator.py` | 다중 서버 패턴 매칭 + 이상 탐지 |
| 서버 온보딩 | `tools/server_setup.py` | 등록 → 테스트 → Wiki 자동 생성 |
| 서비스 설정 | `tools/service_config.py` | Nginx/systemd/Compose 생성 + 의존관계 맵 |
| Wiki 동기화 | `wiki/sync.py` | 도구 실행 결과 → Wiki 자동 업데이트 |

### Phase 3: 대시보드 & 확장 ✅

| 모듈 | 파일 | 설명 |
|------|------|------|
| 대시보드 API | `server/dashboard_mixin.py` | REST + WebSocket 실시간 스트리밍 |
| 보안 스캔 | `tools/security_scan.py` | 포트 스캔, SSL 검증, 취약점 검사 |
| Docker 확장 | `tools/docker_mgmt.py` | inspect, networks, volumes, prune |
| K8s 확장 | `tools/k8s_mgmt.py` | nodes, top, ingress, HPA, 멀티클러스터 |

### Phase 4: 멀티 클라우드 & IaC ✅

| 모듈 | 파일 | 설명 |
|------|------|------|
| GCP 연동 | `connectors/cloud/gcp.py` | Compute Engine, GKE (SDK 또는 REST fallback) |
| Azure 연동 | `connectors/cloud/azure.py` | VM, AKS (SDK 또는 REST fallback) |
| IaC 도구 | `tools/iac.py` | Terraform plan/state/output, Ansible inventory/playbook |
| 인증서 관리 | `tools/cert_mgmt.py` | SSL 모니터링, 만료 알림, Let's Encrypt 갱신 |
| SSH 터널링 | `connectors/ssh/tunnel.py` | 포트 포워딩 (TunnelManager) |

> 상세 설계: [cloud-server-ops-expansion-design.md](docs/cloud-server-ops-expansion-design.md)

---

## 👥 개발팀 구성

병렬 개발을 위한 에이전트 기반 개발팀 페르소나:

| 역할 | 페르소나 ID | 담당 영역 |
|------|-----------|----------|
| **개발팀장** | `tech-lead` | 아키텍처, catalog.py, agents/sre.py, 코드 리뷰, 인터페이스 정의 |
| **백엔드 개발자** | `backend-dev` | monitoring/, tools/ 핵심 로직, 시계열 DB, 알림 엔진 |
| **UI 개발자** | `ui-dev` | dashboard_mixin.py, REST API, WebSocket 스트리밍 |
| **QA 엔지니어** | `qa-engineer` | pytest 테스트, mock 전략, 커버리지 |
| **기획자** | `planner` | 기획서, Wiki 카테고리/템플릿, 사용자 시나리오 |

> 상세 조율 가이드: [docs/dev-team/TEAM-COORDINATION.md](docs/dev-team/TEAM-COORDINATION.md)

---

## 🤖 에이전트

### 운영 에이전트

| 에이전트 | 용도 | 도구 | 특징 |
|----------|------|------|------|
| **Ops** | 서버 운영, 인프라 관리 | 모니터링, SSH, Docker, K8s, DB, 클라우드 (30개) | 승인 기반 실행 |
| **SRE** | 통합 모니터링, 인시던트 대응, 자동 복구 | Ops 전체 + 모니터링 + 인시던트 + 보안 (확장 중) | 사전 예방적 |

### 개발 에이전트

| 에이전트 | 용도 | 도구 | 특징 |
|----------|------|------|------|
| **Code** | 코딩, 디버깅, 리팩토링 | 파일, Git, 검색, 셸, 투두 | explorer 서브에이전트 |
| **Dev** | 개발 관리, CI/CD | 파일, Git, CI/CD, 코드 리뷰 (8개) | PR 분석, 보안 스캔 |
| **Tech Lead** | 아키텍처, 코드 리뷰, 팀 조율 | 전체 도구 (14개 capability) | 병렬 개발 조율 |
| **Backend Dev** | 백엔드 핵심 로직 구현 | 파일, Git, DB, Docker, K8s, SSH (12개) | 도구 패턴 준수 |

### 기본 에이전트

| 에이전트 | 용도 | 도구 | 특징 |
|----------|------|------|------|
| **Cowork** | 지식작업, 분석, 보고서 | 파일, 검색, 셸, 투두 | 다중 루트 워크스페이스 |
| **Chat** | 단순 대화, 질문 답변 | 없음 | 도구 없이 대화만 |

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
# 통합 시작 (백엔드 + 프론트엔드)
./start.sh

# 또는 개별 실행:
# API 서버 (터미널 1)
.venv/bin/python -m coworker.server.run --host 0.0.0.0 --port 8765

# GUI 서버 (터미널 2)
TOKEN=$(cat ~/.config/werubworker/sidecar-8765.token | tr -d '\n')
cd surfaces/gui && VITE_COWORKER_API_TOKEN="$TOKEN" npx vite --host 0.0.0.0
```

### 서비스 관리

```bash
./start.sh              # 시작 (백엔드 + 프론트엔드)
./start.sh --stop       # 중지
./start.sh --restart    # 재시작
./start.sh --status     # 상태 확인
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
| **모니터링** | 🛡 | 대시보드 (서버 현황, 알림, 인시던트, 헬스체크, 감사 로그) |
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

### v2.0 문서

| 문서 | 설명 |
|------|------|
| [**v2.0 아키텍처**](docs/v2-architecture.md) | 전체 시스템 구조, 모니터링/위키/도구 아키텍처, 데이터 저장소 |
| [**v2.0 API 레퍼런스**](docs/v2-api-reference.md) | 대시보드/인프라/Wiki API 엔드포인트 전체 명세 |
| [**CHANGELOG**](CHANGELOG.md) | v2.0.0 릴리즈 변경 이력 |
| [**확장 설계서**](docs/cloud-server-ops-expansion-design.md) | 통합 모니터링, 알림, 인시던트, 서비스 위키 리포지토리 설계 |
| [**개발팀 조율 가이드**](docs/dev-team/TEAM-COORDINATION.md) | 병렬 개발 규칙, 작업 분배, 충돌 방지 |

### 기존 문서

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
