# WeruBWorker 전체 아키텍처 분석 보고서

## 목차
1. [프로젝트 개요](#1-프로젝트-개요)
2. [백엔드 아키텍처](#2-백엔드-아키텍처)
3. [프론트엔드 아키텍처](#3-프론트엔드-아키텍처)
4. [인프라 및 설정](#4-인프라-및-설정)
5. [리팩토링 권장사항](#5-리팩토링-권장사항)

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 버전 | 0.1.7 |
| 라이선스 | MIT |
| 백엔드 | Python 3.10+, FastAPI, aisuite |
| 프론트엔드 | React 18, TypeScript, Vite, Tailwind |
| 데스크톱 셸 | Tauri (Rust) |
| STT | Rust (Whisper-rs, 로컬 오프라인) |
| DB | SQLite + JSONL (append-only) |
| 테스트 | pytest 93파일 + Playwright E2E 63파일 |

### 규모

| 구성요소 | 파일 수 | 코드량 |
|----------|---------|--------|
| Python 백엔드 (`coworker/`) | 126 .py | ~15,000+ lines |
| GUI 프론트엔드 (`surfaces/gui/src/`) | 76 .tsx/.ts | ~8,000+ lines |
| 테스트 | 156 files | ~20,000+ lines |
| 패키징/CI | 6 files | ~1,000 lines |

---

## 2. 백엔드 아키텍처

### 2.1 계층 구조

```
┌─────────────────────────────────────────────────┐
│  FastAPI Server (app.py 600+줄, run.py)         │ ← HTTP/WS API
├─────────────────────────────────────────────────┤
│  SessionManager (manager.py 4,161줄)            │ ← 세션 생명주기
├─────────────────────────────────────────────────┤
│  TurnEngine (engine.py 700+줄)                  │ ← 에이전트 루프
├──────────────┬──────────────┬────────────────────┤
│ ProviderRouter│ ToolRegistry │ PermissionEngine  │ ← 실행 & 접근제어
├──────────────┼──────────────┼────────────────────┤
│ Providers(6) │ Connectors   │ Skills            │ ← 통합
├──────────────┼──────────────┼────────────────────┤
│ SecretStore  │ ConvStore    │ InboxStore         │ ← 영속성
└──────────────┴──────────────┴────────────────────┘
```

### 2.2 핵심 모듈 (대형 파일)

| 파일 | 줄 수 | 역할 | 리팩토링 필요도 |
|------|-------|------|----------------|
| `server/manager.py` | 4,161 | 세션+커넥터+자동화+스킬 관리 (God class) | 🔴 **높음** |
| `engine.py` | 700+ | 에이전트 턴 루프, 승인, 컴팩션 | 🟡 중간 |
| `server/app.py` | 600+ | FastAPI 라우트 전체 | 🟡 중간 |
| `connectors/integration_tools.py` | 4,923 | 25+ 커넥터 도구 정의 | 🔴 **높음** |
| `connectors/descriptors.py` | 1,470 | 커넥터 메타데이터 | 🟡 중간 |
| `providers/registry.py` | 500+ | 프로바이더 팩토리+검증 | 🟢 낮음 |

### 2.3 에이전트 체계

```python
Agent (base.py)
├── Code   — 코딩 전용, git 연동, explorer 서브에이전트
│            capabilities: ["code_files", "git", "search", "shell", "todo"]
├── Cowork — 지식작업, 다중 루트 파일, 자동화
│            capabilities: ["files", "search", "shell", "todo"]
├── Chat   — 대화 전용, 도구 없음, 커넥터 메시징 가능
└── MyHelper — Cowork 도구 공유 개인 어시스턴트
```

각 에이전트는 `catalog.py`의 Capability를 조합하여 도구를 구성.

### 2.4 데이터 흐름: 사용자 메시지 → 응답

```
사용자 메시지
  → FastAPI WS /ws/sessions/{id}
  → SessionManager.get_engine(id) [캐시된 TurnEngine]
  → engine.run(text)
  → engine._loop() [비동기 반복]
     ├→ _outbound_messages() [사이드카 제거, 컨텍스트 주입]
     ├→ asyncio.to_thread(provider.stream()) [프로바이더 호출]
     │   └→ ProviderRouter → 모델 프리픽스별 라우팅
     ├→ ASSISTANT_DELTA 이벤트 (스트리밍)
     ├→ 각 tool_call에 대해:
     │   ├→ permissions.evaluate() → Decision
     │   ├→ 승인 필요 시: PERMISSION_REQUIRED → Inbox 대기
     │   ├→ 허용 시: registry.execute() → TOOL_FINISHED
     │   └→ 거부 시: 에러 결과 반환
     └→ TURN_END 이벤트 → 세션 저장
```

### 2.5 프로바이더 아키텍처 (6+N)

| 프로바이더 | SDK | 와이어 | 특이사항 |
|-----------|-----|--------|---------|
| OpenAI Responses | openai | /v1/responses | GPT-5.6+, 추론+도구 |
| OpenAI Chat | openai | /v1/chat/completions | 커스텀 엔드포인트, Ollama |
| Anthropic | anthropic | /v1/messages | Extended thinking, PDF |
| Gemini | google-genai | generateContent | Thinking (beta) |
| Bedrock | boto3 | AWS API | Claude + Converse |
| Vertex | google-cloud | GCP API | Gemini, Claude MaaS |
| Ollama, DeepSeek, xAI... | openai (호환) | 벤더별 | OpenAI 호환 와이어 |

### 2.6 도구(Tool) 카탈로그

```
catalog.py (Capability 등록)
├── code_files  — 파일 읽기/쓰기 (단일 루트)
├── files       — 파일 읽기/쓰기 (다중 루트)
├── git         — git log/diff/blame/add/commit
├── search      — 파일/심볼 검색, 웹 검색
├── shell       — 셸 명령 실행 (persistent, 백그라운드 지원)
├── todo        — 작업 목록 (Progress 패널 렌더링)
└── (커넥터/스킬/메모리/자동화/MCP 도구는 별도 등록)
```

### 2.7 권한 모델

```
Mode.DISCUSS      → 읽기 전용 (도구 차단)
Mode.PLAN         → 읽기 전용 + propose_plan 워크플로
Mode.INTERACTIVE  → 승인 요청 (기본값)
Mode.AUTO         → 전체 접근
Mode.CUSTOM       → config의 auto_allow 목록 자동 허용

Risk Classification:
  LOW       → 항상 실행 (read_file, find_files, web_search)
  EXTERNAL  → 승인 필요 (send_message, send_file)
  WRITE_LOCAL → 승인 필요 (write_file, replace_in_file)
  EXEC      → 승인 필요 (run_shell)
```

### 2.8 데이터 저장소

```
~/.config/werubworker/
├── coworker.db          # SQLite (sessions, workspaces, memory 테이블)
├── automation.db        # SQLite (tasks, runs 테이블)
├── conversations/       # <session_id>.jsonl (append-only 메시지 로그)
├── config.toml          # 글로벌 설정
├── secrets.json         # API 키, 토큰 (0600 퍼미션)
├── prefs.json           # UI 환경설정
├── workspace_trust.json # 신뢰 워크스페이스 목록
├── skills/              # 글로벌 스킬 디렉토리
└── sidecar-{port}.token # 사이드카 인증 토큰 (임시)
```

---

## 3. 프론트엔드 아키텍처

### 3.1 핵심 파일

| 파일 | 줄 수 | 역할 | 리팩토링 필요도 |
|------|-------|------|----------------|
| `App.tsx` | **1,810** | 모든 상태+라우팅+이벤트 처리 (모놀리식) | 🔴 **높음** |
| `api.ts` | ~1,900 | REST/WS API 레이어 전체 | 🟡 중간 |
| `Sidebar.tsx` | 대형 | 네비게이션, 세션 목록, 메뉴 | 🟡 중간 |
| `Composer.tsx` | 대형 | 입력, 첨부, 스킬, 음성, 모델 선택 | 🟡 중간 |
| `Transcript.tsx` | 대형 | 메시지 렌더링, 스트리밍, 도구 UI | 🟡 중간 |
| `SettingsView.tsx` | 대형 | 5개 탭 설정 페이지 | 🟡 중간 |

### 3.2 컴포넌트 트리

```
App (루트 — 모든 상태 보유)
├── Sidebar (좌측 네비게이션)
│   ├── 세션 목록 (에이전트별)
│   ├── Automations 링크
│   ├── Integrations / Audit / Inbox 링크
│   └── 계정/클라우드 섹션
│
├── 메인 콘텐츠 (surface별 조건부)
│   ├── session → Transcript + Composer + RightRail
│   ├── scheduled → ScheduledView
│   ├── integrations → IntegrationsView
│   ├── settings → SettingsView (5개 탭)
│   ├── audit → AuditView
│   ├── inbox → InboxView
│   └── persona → PersonaView
│
└── 오버레이/모달
    ├── FolderGate (워크스페이스 선택)
    ├── SearchModal (세션 검색)
    ├── Onboarding (최초 실행)
    └── WorkspaceTrustPrompt (권한 요청)
```

### 3.3 상태 관리 (문제점)

**현재: App.tsx에 모든 useState 집중**

```
세션/대화: sessionId, items, streaming, running, todo, usage
워크스페이스: workspace, branch, agent, model, mode
UI: surface, navCollapsed, railHidden, searchOpen
설정: connected, modelReady, models, personas, settings
부팅: booting, uiReady, onboarding
```

**문제점:**
- Context API 미사용 → props drilling 10+ 레벨
- 상태 라이브러리 없음 (Redux/Zustand 없음)
- Error Boundary 없음
- Memoization 최소 (React.memo, useMemo 부재)
- Ref 남용 (state와 ref 이중 관리: streamingRef ↔ streaming)

### 3.4 API 통신 (api.ts)

**REST 엔드포인트** (~50+):
- 세션 CRUD, 설정, 페르소나, 스킬, 커넥터, 자동화, 인박스, 감사
- 모든 요청에 `X-WeruBWorker-Token` 헤더 주입

**WebSocket 2종:**
- `/ws/session/{id}` — 세션별 실시간 턴 이벤트 (23종 이벤트 타입)
- `/ws/events` — 앱 전역 이벤트 (자동화 시작 등)

### 3.5 스타일링

- **Tailwind CSS** — 유틸리티 클래스 기반
- **CSS Custom Properties** — 라이트/다크 테마 (styles.css)
- **CSS-in-JS 없음** — 인라인 스타일 최소
- **테마**: `html[data-theme="dark"]` 선택자, localStorage 저장

### 3.6 성능 병목

| 문제 | 영향 | 해결책 |
|------|------|--------|
| Transcript 가상화 없음 | 1000+ 아이템 시 렌더링 지연 | react-window 적용 |
| 세션 목록 5초 폴링 | 불필요한 리렌더링 | diff 알고리즘, 변경분만 업데이트 |
| Memoization 부재 | 매 상태 변경마다 전체 리렌더 | React.memo, useMemo |
| 코드 스플리팅 최소 | 초기 로딩 750KB JS | 라우트별 lazy loading |

---

## 4. 인프라 및 설정

### 4.1 빌드 & 패키징

| 플랫폼 | 방식 | 도구 |
|--------|------|------|
| macOS (arm64 + Intel) | DMG + 자동 업데이트 | Tauri + PyInstaller |
| Windows | MSI/NSIS 설치 | Tauri + PyInstaller |
| Python 패키지 | pip install -e "." | setuptools |
| GUI 개발 | Vite dev server (1420) | Vite 5.4 |

### 4.2 CI/CD

- **CI** (`ci.yml`): pytest, GUI 유닛 테스트, Playwright E2E (모두 Ubuntu)
- **Release** (`release.yml`): 태그 기반 macOS/Windows 빌드, GitHub Releases

### 4.3 보안 모델

| 계층 | 메커니즘 |
|------|----------|
| API 인증 | `COWORKER_API_TOKEN` (시작 시 생성, 파일 0600) |
| CORS | tauri://localhost, localhost, 127.0.0.1만 허용 |
| 워크스페이스 신뢰 | 명시적 신뢰 → allowed_commands 활성화 |
| 시크릿 | secrets.json (0600), 감사 로그에서 마스킹 |
| WebSocket | 프레임 16MB, 30req/10s, 메시지 200KB 제한 |

### 4.4 설정 계층

```
Built-in defaults (config.py)
  ↓ 오버라이드
~/.config/werubworker/config.toml (글로벌)
  ↓ 오버라이드 (신뢰 워크스페이스만)
<workspace>/.coworker/config.toml (워크스페이스)
```

### 4.5 의존성

**Python 핵심 (37+ 패키지):**
- 모델: openai, anthropic, google-genai, boto3
- 서버: fastapi, uvicorn, websockets, httpx
- 에이전트: aisuite (git-pinned), mcp, docstring_parser
- 미디어: pypdf, pypdfium2
- 검색: ddgs (DuckDuckGo)
- 스케줄: croniter

**npm 핵심 (5 + 11 dev):**
- react, react-dom, react-markdown, pdfjs-dist, xlsx
- vite, typescript, vitest, playwright, tailwindcss

---

## 5. 리팩토링 권장사항

### 5.1 🔴 높은 우선순위

#### 1) App.tsx 분리 (1,810줄 → 5-6개 파일)

```
현재: App.tsx (모든 상태 + 라우팅 + 이벤트)
목표:
├── contexts/SessionContext.tsx    — 세션/대화 상태
├── contexts/UIContext.tsx         — UI 상태 (surface, nav)
├── contexts/SettingsContext.tsx   — 설정/모델/페르소나
├── layouts/MainLayout.tsx         — 그리드 레이아웃
├── views/SessionView.tsx          — 세션 메인 뷰
└── App.tsx                        — Provider 조합 + 부팅
```

#### 2) SessionManager 분리 (4,161줄 → 3-4개 모듈)

```
현재: manager.py (세션+커넥터+자동화+스킬+설정)
목표:
├── managers/session.py      — 세션 CRUD + 엔진 캐시
├── managers/connector.py    — 커넥터 생명주기 + 게이트웨이
├── managers/automation.py   — 스케줄 태스크 + 실행
└── managers/settings.py     — 모델/설정/환경설정
```

#### 3) 커넥터 도구 분리 (4,923줄)

```
현재: integration_tools.py (모든 커넥터 도구 한 파일)
목표:
├── connectors/slack/tools.py
├── connectors/github/tools.py
├── connectors/gmail/tools.py
└── connectors/hubspot/tools.py
```

### 5.2 🟡 중간 우선순위

#### 4) React Error Boundary 추가
- Sidebar, Transcript, RightRail 각각 ErrorBoundary로 래핑
- 에러 토스트 알림 시스템 도입

#### 5) 상태 관리 개선
- Context API 도입 (SessionContext, UIContext)
- props drilling 제거 (10+ 레벨 → 2-3 레벨)
- React.memo + useMemo 적용 (Transcript, Sidebar 세션 목록)

#### 6) Transcript 가상화
- react-window 또는 react-virtualized 적용
- 1000+ 아이템 대화의 렌더링 성능 개선

#### 7) 도구 리스크 분류 통합
- permissions.py, risk.py, connectors/tool_defs.py에 분산된 로직 통합
- ToolMetadata → Decision 단일 파이프라인

#### 8) DB 마이그레이션 체계화
- 현재: `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN` (ad-hoc)
- 목표: Alembic 또는 간이 마이그레이션 매니저

### 5.3 🟢 낮은 우선순위

#### 9) aisuite 의존성 정리
- 현재 git-pinned → PyPI 릴리스 시 전환

#### 10) 시크릿 저장소 암호화
- 현재: 파일 퍼미션(0600)만 의존
- 목표: OS keychain 연동 또는 age 암호화 백엔드

#### 11) 테스트 모듈화
- test_connectors.py (67KB) → 커넥터별 분리
- test_anthropic_provider.py (25KB) → 기능별 분리

#### 12) 문서화 강화
- ADR (Architecture Decision Records) 도입
- 내부 API 문서 자동 생성
- STT 프로토콜 문서화

---

## 부록: 주요 강점

| 영역 | 강점 |
|------|------|
| 프로바이더 추상화 | SDK 변경에 독립적, 6개 네이티브 + N개 호환 |
| 권한 엔진 | 모드별, 세션별, 태스크별 세밀한 제어 |
| 메시지 정규화 | OpenAI 형식 기준 → 저장소와 프로바이더 분리 |
| 이벤트 기반 | TurnEngine 세밀한 이벤트 (23종) → 결정론적 재생 |
| 로컬 퍼스트 | 데이터 외부 전송 없음, 사용자 선택 시만 |
| 테스트 인프라 | 격리된 상태 디렉토리, FakeSlack, 허메틱 E2E |
| 자동 업데이트 | 서명된 바이너리, minisign 검증 |

---

*분석일: 2026-08-06*
*프로젝트: WeruBWorker v0.1.7*
*분석 범위: 백엔드 126 .py + 프론트엔드 76 .tsx/.ts + 인프라/테스트/설정*
