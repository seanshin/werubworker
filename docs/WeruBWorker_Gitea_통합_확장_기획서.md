# WeruBWorker × Gitea 통합 확장 기획서

> **작성일**: 2026-08-18  
> **현재 상태**: Gitea 1.27.2 설치, 기본 Webhook 연동 완료  
> **목표**: Gitea를 WeruBWorker의 핵심 인프라로 완전 통합하여 에이전트 주도 개발·배포·운영 플랫폼 구축

---

## 1. 비전

```
┌─────────────────────────────────────────────────────────────────────┐
│                WeruBWorker × Gitea 통합 플랫폼                       │
│                                                                      │
│   "AI 에이전트가 코드를 리뷰하고, 배포하고, 운영하고, 장애에 대응한다"    │
│                                                                      │
│   개발자 → Gitea(push) → WeruBWorker(자동 리뷰/빌드/배포/모니터링)     │
│                              ↕                                       │
│                    AI 에이전트 (분석/판단/실행)                         │
│                              ↕                                       │
│              Slack/GUI (알림/승인/대시보드)                             │
└─────────────────────────────────────────────────────────────────────┘
```

현재는 Webhook 수신 + 이벤트 기록 수준이지만, Gitea의 풍부한 API를 활용하여 **개발→리뷰→빌드→배포→모니터링→장애 대응**의 전체 수명주기를 AI 에이전트가 관리하는 플랫폼으로 확장한다.

---

## 2. 현재 상태 (v2.3.0)

| 기능 | 상태 | 설명 |
|------|------|------|
| Gitea 설치 | ✅ | brew, SQLite, :3000 |
| 소스 이관 | ✅ | 전체 히스토리 + 태그 17개 |
| Webhook 수신 | ✅ | push/PR/이슈/릴리스 이벤트 기록 |
| start.sh 통합 | ✅ | Gitea + 백엔드 + 프론트엔드 일괄 관리 |
| DevView Webhooks 탭 | ✅ | 이벤트 이력 표시 |
| GitHub 백업 | ✅ | dual-push (`git push all`) |
| MCP gitea_repos | ✅ | 리포 목록 조회 |
| MCP gitea_webhook_events | ✅ | 이벤트 이력 조회 |

---

## 3. 확장 영역

### Phase A: Gitea API 완전 연동 (코드 관리)

#### A.1 리포지토리 관리
- [ ] 리포 생성/삭제/설정 변경 (API + GUI)
- [ ] 브랜치 보호 규칙 자동 설정 (main 보호, 리뷰 필수)
- [ ] 리포 미러링 관리 (GitHub ↔ Gitea 자동 동기화 설정)
- [ ] 리포 통계 대시보드 (커밋 빈도, 기여자, 언어 비율)
- [ ] 리포 템플릿 — 프로젝트 초기화 자동화 (.gitignore, CI, README)

#### A.2 브랜치 & 태그 관리
- [ ] 브랜치 목록/생성/삭제 (API + GUI)
- [ ] 태그 & 릴리즈 자동 생성 (시맨틱 버전, CHANGELOG 자동 생성)
- [ ] 브랜치 비교 (diff 통계, 머지 가능 여부)
- [ ] 릴리즈 노트 AI 자동 생성 (커밋 메시지 기반 LLM 요약)

#### A.3 파일 & 콘텐츠 API
- [ ] 파일 읽기/쓰기/삭제 (Gitea Contents API)
- [ ] 설정 파일 원격 수정 (에이전트가 직접 config 수정 + 커밋)
- [ ] `.gitea/workflows` YAML 자동 생성
- [ ] README 자동 갱신 (프로젝트 상태 배지 업데이트)

---

### Phase B: AI 코드 리뷰 & PR 자동화

#### B.1 자동 코드 리뷰
- [ ] PR 생성 시 자동 트리거 (Webhook `pull_request.opened`)
- [ ] diff 분석 → LLM 코드 리뷰 (보안, 성능, 코드 품질)
- [ ] 리뷰 코멘트 자동 작성 (Gitea Review API)
- [ ] 심각도별 분류 (critical → request changes, minor → comment)
- [ ] 리뷰 이력 학습 — 반복 지적 패턴 자동 감지

#### B.2 PR 워크플로우 자동화
- [ ] PR 라벨 자동 부착 (파일 패턴 기반: frontend, backend, docs 등)
- [ ] PR 템플릿 자동 생성 (변경 요약, 테스트 체크리스트)
- [ ] 의존성 업데이트 PR 자동 생성 (npm/pip outdated 감지)
- [ ] 머지 전 체크리스트 자동 검증 (테스트 통과, 리뷰 승인, 충돌 없음)
- [ ] 자동 머지 (조건 충족 시 squash merge)
- [ ] 머지 후 브랜치 자동 삭제

#### B.3 이슈 & 프로젝트 관리
- [ ] 이슈 자동 분류 (버그/기능/개선 라벨 AI 분류)
- [ ] 이슈 → PR 연결 자동화 (`Fixes #123` 파싱)
- [ ] 마일스톤 진행률 대시보드
- [ ] 이슈 SLA 추적 (생성~해결 시간)
- [ ] 인시던트 → Gitea 이슈 자동 생성

---

### Phase C: CI/CD 파이프라인 (Gitea Actions)

#### C.1 빌드 & 테스트
- [ ] Gitea Actions 러너 설정 (로컬 act_runner)
- [ ] push 시 자동 빌드/테스트 워크플로우
- [ ] 테스트 결과 → PR 코멘트 자동 작성
- [ ] 커버리지 리포트 → PR 상태 체크
- [ ] 빌드 캐시 최적화 (node_modules, pip cache)

#### C.2 배포 파이프라인
- [ ] main 머지 → 자동 배포 (WeruBWorker 재시작)
- [ ] 스테이징 → 프로덕션 단계별 배포
- [ ] 롤백 자동화 (이전 태그로 복원)
- [ ] 배포 알림 (Slack + GUI + 위키)
- [ ] 배포 이력 추적 (누가, 언제, 어떤 커밋)

#### C.3 릴리즈 자동화
- [ ] 태그 push → 릴리즈 자동 생성
- [ ] CHANGELOG 자동 생성 (Conventional Commits 기반)
- [ ] 릴리즈 에셋 자동 첨부 (빌드 아티팩트)
- [ ] 릴리즈 알림 (Slack + GUI)

---

### Phase D: Gitea ↔ WeruBWorker 심층 통합

#### D.1 에이전트 주도 Git 작업
- [ ] 에이전트가 직접 브랜치 생성 → 코드 수정 → PR 생성
- [ ] 자동 핫픽스 — 장애 감지 시 설정 파일 수정 + PR
- [ ] 스케줄 기반 코드 정리 (lint, format, 미사용 import 제거)
- [ ] 문서 자동 갱신 (API 변경 시 docs 업데이트)

#### D.2 Gitea 대시보드 (GUI 통합)
- [ ] DevView에 Gitea 전용 대시보드 탭
  - 리포 목록 + 브랜치 + 커밋 히트맵
  - PR 큐 (대기 중 리뷰, 머지 가능, 충돌)
  - CI/CD 파이프라인 상태 (실시간)
  - 릴리즈 타임라인
- [ ] 코드 브라우저 (Gitea raw API로 파일 트리 + 내용 표시)
- [ ] diff 뷰어 (PR 변경 내용 인라인 표시)
- [ ] 커밋 검색 (메시지, 작성자, 날짜 필터)

#### D.3 Wiki ↔ Gitea 동기화
- [ ] Gitea Wiki ↔ WeruBWorker Wiki 양방향 동기화
- [ ] 리포별 Wiki 자동 생성 (README 기반)
- [ ] API 문서 자동 생성 (코드 분석 → Wiki 페이지)
- [ ] 운영 런북 → Gitea Wiki 미러링

#### D.4 알림 & 모니터링 연동
- [ ] Gitea 이벤트 → WeruBWorker 알림 규칙 연동
  - 실패한 CI → Alert 발생
  - 장기 미리뷰 PR → 알림
  - 보안 취약점 PR → Critical 알림
- [ ] Gitea 서비스 헬스체크 (`:3000` 상태 모니터링)
- [ ] Gitea DB 자동 백업 (BackupManager에 gitea.db 추가)

---

### Phase E: 멀티 리포 & 팀 관리

#### E.1 멀티 리포 관리
- [ ] 조직(Organization) 생성/관리
- [ ] 팀별 리포 접근 권한 관리
- [ ] 크로스 리포 이슈 추적 (의존성 관계)
- [ ] 모노레포 vs 멀티레포 관리 도구

#### E.2 사용자 & 팀 관리
- [ ] Gitea 사용자 CRUD (API)
- [ ] 팀별 리뷰어 자동 할당
- [ ] 기여 통계 대시보드 (커밋, PR, 리뷰 횟수)
- [ ] 코드 오너 (CODEOWNERS) 자동 생성

#### E.3 보안 & 컴플라이언스
- [ ] 커밋 서명 검증 (GPG/SSH 서명)
- [ ] 시크릿 스캔 (커밋 내 API 키, 비밀번호 감지)
- [ ] 라이선스 준수 검사 (의존성 라이선스 분석)
- [ ] 접근 로그 감사 (Gitea 로그 → WeruBWorker 감사)

---

### Phase F: MCP 도구 확장

#### F.1 기존 ITMS MCP에 Gitea 도구 추가 (15 → 25개)

| # | 도구 | 설명 |
|---|------|------|
| 16 | `gitea_create_repo` | 리포 생성 |
| 17 | `gitea_branches` | 브랜치 목록/생성/삭제 |
| 18 | `gitea_pull_requests` | PR 목록/생성/머지 |
| 19 | `gitea_pr_review` | AI 코드 리뷰 실행 |
| 20 | `gitea_issues` | 이슈 CRUD |
| 21 | `gitea_releases` | 릴리즈 생성/목록 |
| 22 | `gitea_file_read` | 파일 내용 읽기 |
| 23 | `gitea_file_write` | 파일 수정 + 커밋 |
| 24 | `gitea_ci_status` | CI/CD 파이프라인 상태 |
| 25 | `gitea_deploy` | 배포 트리거 (main 기반) |

---

## 4. 우선순위 로드맵

```
Phase A (1주)  ─── Gitea API 완전 연동: 리포/브랜치/태그/파일 관리
    │
Phase B (2주)  ─── AI 코드 리뷰 + PR 자동화: 자동 리뷰, 라벨, 머지
    │
Phase C (1주)  ─── CI/CD: Gitea Actions 러너, 자동 빌드/배포/릴리즈
    │
Phase D (2주)  ─── 심층 통합: 에이전트 Git 작업, GUI 대시보드, Wiki 동기화
    │
Phase E (1주)  ─── 멀티 리포 & 팀: 조직, 권한, 기여 통계, 보안
    │
Phase F (1주)  ─── MCP 확장: 10개 Gitea 도구 추가 (25개 총)
```

---

## 5. 기술 구현 포인트

### Gitea API 연동 모듈 구조

```
coworker/connectors/gitea/
├── __init__.py
├── client.py              # Gitea REST API 클라이언트 (httpx 기반)
│   ├── GiteaClient
│   │   ├── repos.*()      # 리포 CRUD
│   │   ├── branches.*()   # 브랜치 관리
│   │   ├── pulls.*()      # PR 관리
│   │   ├── issues.*()     # 이슈 관리
│   │   ├── releases.*()   # 릴리즈 관리
│   │   ├── contents.*()   # 파일 읽기/쓰기
│   │   └── orgs.*()       # 조직/팀 관리
├── reviewer.py            # AI 코드 리뷰어
│   ├── CodeReviewer
│   │   ├── review_pr()    # PR diff → LLM 리뷰
│   │   ├── post_review()  # 리뷰 코멘트 작성
│   │   └── auto_label()   # 자동 라벨링
├── pipeline.py            # CI/CD 파이프라인 관리
│   ├── PipelineManager
│   │   ├── trigger_build()
│   │   ├── deploy()
│   │   └── rollback()
├── webhook.py             # (기존 gitea_webhook.py 이관)
└── sync.py                # Wiki/설정 동기화
```

### GUI 확장 포인트

```
surfaces/gui/src/components/
├── DevView.tsx            # 기존 — Gitea 대시보드 탭 확장
│   ├── GiteaDashboard     # 리포/PR/CI 통합 대시보드
│   ├── CodeBrowser        # 파일 트리 + 코드 뷰어
│   ├── DiffViewer         # PR diff 인라인 표시
│   └── PipelineView       # CI/CD 파이프라인 시각화
```

### Gitea API 인증

```python
# 로컬 Gitea — 토큰 기반 인증
GITEA_URL = "http://localhost:3000"
GITEA_TOKEN = secrets.get("gitea", {}).get("token", "")

# httpx 클라이언트
client = httpx.AsyncClient(
    base_url=GITEA_URL,
    headers={"Authorization": f"token {GITEA_TOKEN}"},
)
```

---

## 6. 성공 지표

| 지표 | 현재 | 목표 |
|------|------|------|
| Gitea API 연동 도구 | 2개 | 25+개 |
| PR 자동 리뷰율 | 0% | 100% (모든 PR) |
| 배포 자동화 | 수동 | main 머지 → 자동 배포 |
| 릴리즈 자동화 | 수동 태그 | 태그 → 릴리즈+CHANGELOG 자동 |
| 코드 품질 게이트 | 없음 | 테스트+리뷰 통과 필수 |
| MCP Gitea 도구 | 2개 | 12+개 |
| 에이전트 Git 작업 | 수동 | 핫픽스/문서/정리 자동 |

---

## 7. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| Gitea Actions 러너 리소스 | 중간 | 로컬 러너 1개, 동시 실행 제한 |
| AI 코드 리뷰 정확도 | 중간 | LLM 리뷰는 참고용, 사람 리뷰 병행 |
| 자동 머지 사고 | 높음 | main 브랜치 보호, 승인 필수 |
| Gitea DB 증가 | 낮음 | BackupManager 통합, 자동 pruning |
| API 토큰 보안 | 중간 | Vault 암호화 저장, 최소 권한 |
