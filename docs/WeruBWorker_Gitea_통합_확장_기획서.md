# WeruBWorker × Gitea 통합 확장 기획서 (최종)

> **작성일**: 2026-08-18  
> **구현 완료일**: 2026-08-19  
> **버전**: v2.3.0 → v2.3.1  
> **상태**: Phase A~F 전체 구현 완료  
> **목표**: Gitea를 WeruBWorker의 핵심 인프라로 완전 통합 — 에이전트 주도 개발·배포·운영 플랫폼

---

## 1. 비전 (달성)

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

---

## 2. 구현 결과 요약

| 항목 | v2.3.0 (시작) | v2.3.1 (완료) | 변화 |
|------|-------------|-------------|------|
| Gitea 모듈 | 1개 (webhook) | 6개 | +5 |
| Gitea REST API | 3개 | 36개 | +33 |
| MCP 도구 | 27개 | 37개 | +10 |
| 총 REST API | 210+개 | 250+개 | +40 |
| 파일 변경 | — | 26개, +2,727줄 | |
| 커밋 | — | 5개 | |

### Gitea 모듈 구조

```
coworker/connectors/gitea/
├── __init__.py           # GiteaClient export
├── client.py             # Gitea REST API v1 비동기 클라이언트 (9 서브API)
├── reviewer.py           # AI 코드 리뷰어 + PR 자동화
├── pipeline.py           # CI/CD 파이프라인 엔진
├── agent_ops.py          # 에이전트 주도 Git 작업
├── sync.py               # Wiki ↔ Gitea 양방향 동기화
└── teams.py              # 멀티 리포/팀 관리 + 보안 스캐너
```

---

## 3. Phase별 구현 완료 내역

### Phase A: Gitea API 완전 연동 ✅

- [x] `GiteaClient` — httpx 비동기 클라이언트 (9 서브API)
  - repos, branches, tags, pulls, issues, releases, contents, commits, orgs
- [x] REST API 17개: 리포/브랜치/PR/이슈/릴리즈/파일/커밋 CRUD
- [x] MCP 도구 12→25개 (Gitea 도구 13개)
- [x] DevView Repos 탭 (리포 카드 목록)

### Phase B: AI 코드 리뷰 + PR 자동화 ✅

- [x] `CodeReviewer` — LLM/정적 코드 리뷰
  - 보안 패턴 감지 5종 (하드코딩 비밀번호, API키, eval, shell injection, SQL injection)
  - 자동 라벨링 8종 (frontend, backend, docs, tests, ci, monitoring, security, config)
  - 머지 전 체크리스트 (mergeable, 충돌, 리뷰 승인, 제목)
  - 조건부 자동 머지 (squash/merge/rebase)
- [x] Webhook PR opened → 자동 리뷰 트리거
- [x] REST API 3개: review, merge-check, auto-merge
- [x] MCP 도구 25→27개 (gitea_pr_review, gitea_merge_check)
- [x] DevView PR에 AI 리뷰 버튼 + 결과 표시

### Phase C: CI/CD 파이프라인 ✅

- [x] `PipelineManager` — 내장 CI/CD 엔진
  - 3개 기본 파이프라인: test, deploy, release
  - async 서브프로세스 실행, 중복 방지, 타임아웃 처리
  - Webhook push → test+deploy 자동 트리거
  - 태그 push → release 파이프라인 + Gitea 릴리즈 자동 생성
- [x] REST API 4개: pipelines, run, runs, run detail
- [x] MCP 도구 27→29개 (gitea_pipeline_run, gitea_pipeline_status)
- [x] DevView Pipelines 탭 (설정 카드 + 실행 버튼 + 이력)

### Phase D: 심층 통합 ✅

- [x] `AgentGitOps` — 에이전트 주도 Git 작업
  - 핫픽스: 브랜치 생성 → 파일 수정 → PR 자동 생성
  - 문서 자동 갱신: 여러 파일 일괄 수정 + PR
  - 스케줄 정리: 머지된 브랜치 삭제, 오래된 PR 닫기
- [x] `GiteaWikiSync` — Wiki ↔ Gitea 양방향 동기화
  - Wiki → Gitea docs/ 동기화
  - Gitea docs/ → Wiki 가져오기
  - README 기반 리포 자동 문서 생성
- [x] Alert → Gitea 이슈 자동 생성 (`create_alert_issue`)
- [x] BackupManager에 gitea.db + pipelines.db 추가
- [x] REST API 6개: agent(3) + wiki sync(3)
- [x] MCP 도구 29→32개 (gitea_hotfix, gitea_wiki_sync, gitea_cleanup)
- [x] DevView 코드 브라우저 (파일 트리 + 뷰어) + Wiki 동기화 버튼

### Phase E+F: 멀티 리포 & 팀 + 보안 + MCP 최종 ✅

- [x] `TeamsManager` — 조직/팀/기여 관리
  - 조직 현황 (리포/팀/멤버 수)
  - 기여 통계 (커밋/PR 수, 기여자 순위)
  - CODEOWNERS 자동 생성
  - 리포 종합 통계 대시보드
- [x] `SecurityScanner` — 리포 보안 스캐너
  - 시크릿 스캔 7패턴 (API키, 비밀번호, 토큰, AWS키, 개인키, GitHub PAT, OpenAI키)
  - 민감 파일 감지 (.env, credentials.json, .pem, .key)
  - 라이선스 검사 (MIT, Apache, GPL, BSD 감지)
- [x] REST API 6개: orgs, stats, contributors, codeowners, secret-scan, license
- [x] MCP 도구 32→37개 (repo_stats, contributors, secret_scan, license_check, orgs)
- [x] DevView: 통계 패널 + 기여자 차트 + 시크릿 스캔 UI

---

## 4. MCP ITMS 도구 최종 목록 (37개)

### 보안 (4개)
| # | 도구 | 설명 |
|---|------|------|
| 1 | `security_score` | 종합 보안 등급 (A~D) |
| 2 | `container_scan` | 컨테이너 취약점 (Trivy) |
| 3 | `dependency_audit` | 의존성 취약점 (npm/pip) |
| 4 | `firewall_check` | 방화벽 규칙 검증 |

### 백업 (3개)
| 5 | `backup_create` | 데이터 백업 생성 |
| 6 | `backup_list` | 백업 이력 조회 |
| 7 | `backup_restore` | 데이터 복원 |

### 모니터링 (2개)
| 8 | `anomaly_detect` | 이상 탐지 (Z-score) |
| 9 | `postmortem_generate` | 사후분석 보고서 생성 |

### 자동화 (4개)
| 10 | `workflow_list` | 워크플로우 목록 |
| 11 | `workflow_execute` | 워크플로우 실행 |
| 12 | `batch_execute` | 멀티서버 일괄 명령 |
| 13 | `batch_servers` | 서버/태그 목록 |

### Gitea 기본 (12개)
| 14 | `gitea_repos` | 리포 목록 |
| 15 | `gitea_webhook_events` | Webhook 이벤트 이력 |
| 16 | `gitea_repo_detail` | 리포 상세 (언어, 토픽) |
| 17 | `gitea_branches` | 브랜치 목록/생성/삭제 |
| 18 | `gitea_pulls` | PR 목록 |
| 19 | `gitea_create_pr` | PR 생성 |
| 20 | `gitea_issues` | 이슈 목록/생성 |
| 21 | `gitea_releases` | 릴리즈 목록/생성 |
| 22 | `gitea_file_read` | 파일 읽기 |
| 23 | `gitea_file_write` | 파일 수정 + 커밋 |
| 24 | `gitea_commits` | 커밋 이력 |
| 25 | `gitea_file_tree` | 파일 트리 |

### Gitea 고급 (12개)
| 26 | `gitea_pr_review` | AI 코드 리뷰 |
| 27 | `gitea_merge_check` | 머지 전 체크 |
| 28 | `gitea_pipeline_run` | CI/CD 실행 |
| 29 | `gitea_pipeline_status` | CI/CD 이력 |
| 30 | `gitea_hotfix` | 에이전트 핫픽스 PR |
| 31 | `gitea_wiki_sync` | Wiki ↔ Gitea 동기화 |
| 32 | `gitea_cleanup` | 브랜치/PR 자동 정리 |
| 33 | `gitea_repo_stats` | 리포 종합 통계 |
| 34 | `gitea_contributors` | 기여자 통계 |
| 35 | `gitea_secret_scan` | 시크릿 스캔 |
| 36 | `gitea_license_check` | 라이선스 검사 |
| 37 | `gitea_orgs` | 조직 현황 |

---

## 5. Gitea REST API 전체 목록 (36개)

| Phase | 엔드포인트 | 메서드 |
|-------|----------|--------|
| A | `/v1/gitea/repos` | GET, POST |
| A | `/v1/gitea/repos/{owner}/{repo}` | GET |
| A | `/v1/gitea/repos/{owner}/{repo}/languages` | GET |
| A | `/v1/gitea/repos/{owner}/{repo}/branches` | GET, POST |
| A | `/v1/gitea/repos/{owner}/{repo}/branches/{branch}` | DELETE |
| A | `/v1/gitea/repos/{owner}/{repo}/pulls` | GET, POST |
| A | `/v1/gitea/repos/{owner}/{repo}/pulls/{number}/merge` | POST |
| A | `/v1/gitea/repos/{owner}/{repo}/issues` | GET, POST |
| A | `/v1/gitea/repos/{owner}/{repo}/releases` | GET, POST |
| A | `/v1/gitea/repos/{owner}/{repo}/contents/{filepath}` | GET |
| A | `/v1/gitea/repos/{owner}/{repo}/tree` | GET |
| A | `/v1/gitea/repos/{owner}/{repo}/commits` | GET |
| B | `/v1/gitea/repos/{owner}/{repo}/pulls/{number}/review` | POST |
| B | `/v1/gitea/repos/{owner}/{repo}/pulls/{number}/merge-check` | GET |
| B | `/v1/gitea/repos/{owner}/{repo}/pulls/{number}/auto-merge` | POST |
| C | `/v1/gitea/pipelines` | GET |
| C | `/v1/gitea/pipelines/{name}/run` | POST |
| C | `/v1/gitea/pipelines/runs` | GET |
| C | `/v1/gitea/pipelines/runs/{run_id}` | GET |
| D | `/v1/gitea/agent/hotfix` | POST |
| D | `/v1/gitea/agent/update-docs` | POST |
| D | `/v1/gitea/agent/cleanup` | POST |
| D | `/v1/gitea/wiki/sync-to-gitea` | POST |
| D | `/v1/gitea/wiki/sync-from-gitea` | POST |
| D | `/v1/gitea/wiki/auto-docs` | POST |
| E | `/v1/gitea/orgs` | GET |
| E | `/v1/gitea/repos/{owner}/{repo}/stats` | GET |
| E | `/v1/gitea/repos/{owner}/{repo}/contributors` | GET |
| E | `/v1/gitea/repos/{owner}/{repo}/codeowners` | POST |
| E | `/v1/gitea/repos/{owner}/{repo}/secret-scan` | GET |
| E | `/v1/gitea/repos/{owner}/{repo}/license` | GET |

---

## 6. 신규 생성 파일 (Phase A~F)

| 파일 | 기능 | Phase |
|------|------|-------|
| `coworker/connectors/gitea/__init__.py` | GiteaClient export | A |
| `coworker/connectors/gitea/client.py` | Gitea API 클라이언트 (9 서브API) | A |
| `coworker/connectors/gitea/reviewer.py` | AI 코드 리뷰어 + PR 자동화 | B |
| `coworker/connectors/gitea/pipeline.py` | CI/CD 파이프라인 엔진 | C |
| `coworker/connectors/gitea/agent_ops.py` | 에이전트 주도 Git 작업 | D |
| `coworker/connectors/gitea/sync.py` | Wiki ↔ Gitea 동기화 | D |
| `coworker/connectors/gitea/teams.py` | 멀티 리포/팀 + 보안 스캐너 | E+F |

---

## 7. 성공 지표 달성

| 지표 | 목표 | 달성 |
|------|------|------|
| Gitea API 연동 도구 | 25+개 | ✅ 37개 |
| PR 자동 리뷰 | 100% | ✅ Webhook 트리거 |
| 배포 자동화 | main 머지 → 자동 | ✅ deploy 파이프라인 |
| 릴리즈 자동화 | 태그 → 자동 | ✅ release 파이프라인 |
| 코드 품질 게이트 | 리뷰 필수 | ✅ merge-check API |
| MCP Gitea 도구 | 12+개 | ✅ 24개 (Gitea 전용) |
| 에이전트 Git 작업 | 핫픽스/문서 자동 | ✅ agent_ops |

---

## 8. 리스크 및 대응

| 리스크 | 영향 | 대응 | 상태 |
|--------|------|------|------|
| Gitea Actions 러너 리소스 | 중간 | 내장 PipelineManager로 대체 | ✅ 해소 |
| AI 코드 리뷰 정확도 | 중간 | 정적 분석 기본, LLM은 보강용 | ✅ 구현 |
| 자동 머지 사고 | 높음 | merge-check 체크리스트 필수 | ✅ 구현 |
| Gitea DB 증가 | 낮음 | BackupManager에 통합 | ✅ 구현 |
| API 토큰 보안 | 중간 | SecretStore 암호화 저장 | ✅ 구현 |
| 시크릿 유출 | 높음 | secret_scan 7패턴 감지 | ✅ 구현 |
