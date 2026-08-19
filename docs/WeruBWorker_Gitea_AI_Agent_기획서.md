# WeruBWorker × Gitea AI Agent 기능 확장 기획서

> **작성일**: 2026-08-19  
> **기반 버전**: v2.3.1 (Gitea Phase A~F 완료, MCP 37개 도구)  
> **목표**: Gitea를 AI 에이전트의 자율 개발·운영 허브로 확장

---

## 1. 비전

```
┌─────────────────────────────────────────────────────────────────────────┐
│              AI Agent-Native Git Platform                                │
│                                                                          │
│   사람이 요청하면 → AI 에이전트가 코드를 작성하고 → 스스로 리뷰하고 →      │
│   테스트하고 → 배포하고 → 모니터링하고 → 장애를 감지하면 → 자동 수정한다    │
│                                                                          │
│   ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐      │
│   │ 요청 수신 │────→│ 코드 생성 │────→│ 자동 리뷰 │────→│ 빌드/테스트│      │
│   │ (Slack/   │     │ (LLM)    │     │ (보안/품질)│     │ (Actions) │      │
│   │  GUI/MCP) │     │          │     │           │     │           │      │
│   └──────────┘     └──────────┘     └──────────┘     └──────────┘      │
│         ↑                                                    │           │
│         │           ┌──────────┐     ┌──────────┐           ↓           │
│         └───────────│ 장애 감지 │←────│ 모니터링  │←────── 배포 ──→      │
│                     │ (자동수정)│     │ (메트릭)  │     (자동/승인)       │
│                     └──────────┘     └──────────┘                       │
└─────────────────────────────────────────────────────────────────────────┘
```

현재 WeruBWorker는 **사람이 지시하면 에이전트가 실행**하는 모델이다. 이를 **에이전트가 자율적으로 판단하고 실행**하되, 중요 결정에서만 사람의 승인을 받는 모델로 확장한다.

---

## 2. 확장 영역

### Area 1: 자율 코딩 에이전트

#### 1.1 이슈 기반 자동 구현
- [ ] Gitea 이슈 라벨 `ai-implement` 감지 → 에이전트가 자동으로 구현
- [ ] 이슈 내용 분석 → 변경할 파일 식별 → 코드 생성
- [ ] 자동 브랜치 생성 (`ai/{issue-number}`)
- [ ] 구현 완료 → PR 자동 생성 (이슈 연결 `Closes #N`)
- [ ] PR에 구현 설명 + 변경 근거 자동 작성
- [ ] 구현 불가 시 이슈에 코멘트로 사유 설명

#### 1.2 코드 생성 엔진
- [ ] 프로젝트 구조 분석 → 코딩 컨벤션 학습
- [ ] 기존 코드 패턴 참조 (유사 기능 검색)
- [ ] 멀티 파일 변경 지원 (프론트+백엔드 동시)
- [ ] 테스트 코드 자동 생성 (기존 테스트 패턴 학습)
- [ ] import/의존성 자동 관리

#### 1.3 대화형 코드 수정
- [ ] PR 리뷰 코멘트에 `@werub-agent fix this` → 자동 수정
- [ ] 이슈 코멘트에 `@werub-agent 이 기능 추가해줘` → 자동 구현
- [ ] GUI 채팅에서 "이 파일 수정해줘" → Gitea에 커밋

---

### Area 2: 지능형 CI/CD

#### 2.1 적응형 테스트
- [ ] 변경된 파일 기반 관련 테스트만 선택 실행 (테스트 영향 분석)
- [ ] 테스트 실패 → AI가 원인 분석 + 자동 수정 시도
- [ ] 불안정 테스트(flaky) 자동 감지 및 격리
- [ ] 테스트 커버리지 저하 시 누락 테스트 자동 생성

#### 2.2 스마트 배포
- [ ] 카나리 배포: 트래픽 일부만 새 버전에 라우팅
- [ ] 블루/그린 배포: 무중단 전환
- [ ] 배포 후 헬스체크 자동 검증 (5분간 모니터링)
- [ ] 이상 감지 시 자동 롤백 + 인시던트 생성
- [ ] 배포 윈도우: 근무 시간 외 자동 배포 스케줄

#### 2.3 의존성 자동 관리
- [ ] 의존성 업데이트 자동 감지 (npm outdated, pip-audit)
- [ ] 보안 패치 PR 자동 생성 (severity high/critical)
- [ ] 호환성 테스트 후 자동 머지 (테스트 통과 시)
- [ ] CHANGELOG에 의존성 업데이트 기록

---

### Area 3: 인텔리전트 모니터링 연동

#### 3.1 장애 자동 대응 (Closed Loop)
- [ ] 알림 발생 → 관련 코드 자동 분석 (최근 변경 사항 추적)
- [ ] 근본 원인이 코드 변경이면 → 자동 리버트 PR 생성
- [ ] 설정 문제면 → 설정 파일 수정 + PR
- [ ] 인프라 문제면 → 자동 복구 실행 (기존 RemediationEngine)
- [ ] 대응 결과 → 인시던트 타임라인에 자동 기록

#### 3.2 성능 최적화 제안
- [ ] 메트릭 추이 분석 → 성능 병목 감지
- [ ] 관련 코드 분석 → 최적화 제안 이슈 자동 생성
- [ ] N+1 쿼리, 메모리 누수 패턴 감지
- [ ] 자원 사용량 예측 → 스케일링 권고

#### 3.3 SLA 추적 + 보고서
- [ ] 서비스별 SLA 목표 설정 (가용성, 응답시간)
- [ ] SLA 위반 시 자동 알림 + 이슈 생성
- [ ] 주간/월간 SLA 보고서 자동 생성 (Wiki 저장)
- [ ] 인시던트 영향 시간 자동 계산

---

### Area 4: 지식 관리 에이전트

#### 4.1 코드베이스 문서 자동화
- [ ] 코드 변경 시 관련 문서 자동 갱신
- [ ] API 변경 → API 문서 자동 업데이트
- [ ] 새 함수/클래스 → JSDoc/docstring 자동 생성
- [ ] 아키텍처 다이어그램 자동 갱신 (코드 구조 분석)

#### 4.2 온보딩 가이드 자동 생성
- [ ] 새 기여자 → 프로젝트 구조 설명 자동 생성
- [ ] 관련 파일/함수 의존성 그래프
- [ ] "이 파일을 수정하려면 이것도 확인하세요" 안내

#### 4.3 의사결정 기록
- [ ] PR/이슈의 설계 결정 → ADR (Architecture Decision Record) 자동 생성
- [ ] 기술 부채 자동 추적 (TODO/FIXME 통계 + 트렌드)
- [ ] 리팩토링 우선순위 자동 산정

---

### Area 5: 보안 에이전트

#### 5.1 지속적 보안 감사
- [ ] 매 push마다 시크릿 스캔 (commit + diff 기반)
- [ ] 발견 시 자동 알림 + 이슈 생성 + 커밋 리버트 권고
- [ ] 시크릿 로테이션 자동화 (만료된 토큰 갱신)

#### 5.2 취약점 자동 패치
- [ ] CVE 데이터베이스 연동 (OSV, NVD)
- [ ] 영향 받는 의존성 감지 → 업데이트 PR 자동 생성
- [ ] 패치 적용 후 테스트 실행 → 통과 시 자동 머지

#### 5.3 접근 제어 분석
- [ ] 코드 내 권한 체크 패턴 분석
- [ ] 미인가 접근 가능 경로 감지
- [ ] RBAC 규칙 일관성 검증

---

### Area 6: 멀티 에이전트 협업

#### 6.1 에이전트 역할 분리
- [ ] **Coder Agent**: 코드 생성 + 수정
- [ ] **Reviewer Agent**: 코드 리뷰 + 품질 검증
- [ ] **Ops Agent**: 배포 + 모니터링 + 장애 대응
- [ ] **Security Agent**: 보안 스캔 + 취약점 패치
- [ ] **Docs Agent**: 문서 갱신 + 지식 관리

#### 6.2 에이전트 간 통신
- [ ] Coder가 PR 생성 → Reviewer가 자동 리뷰
- [ ] Reviewer 승인 → Ops가 자동 배포
- [ ] Ops 장애 감지 → Coder에 핫픽스 요청
- [ ] Security 취약점 발견 → Coder에 패치 요청

#### 6.3 사람의 역할
- [ ] **승인자**: Critical 배포, 보안 패치 머지 승인
- [ ] **감독자**: 에이전트 활동 대시보드 모니터링
- [ ] **방향 설정**: 이슈 생성, 우선순위 결정
- [ ] **최종 판단**: 에이전트가 판단 불가 시 개입

---

## 3. 구현 우선순위

```
즉시 (1주)    ─── 이슈→자동 구현, 테스트 자동 수정, 장애→리버트
    │
단기 (2주)    ─── 적응형 테스트, 의존성 자동관리, 문서 자동화
    │
중기 (3주)    ─── 스마트 배포, SLA 추적, 보안 자동 패치
    │
장기 (4주)    ─── 멀티 에이전트 협업, 자율 코딩, 지식 관리
```

---

## 4. 기술 구현 포인트

### 이슈→자동 구현 흐름

```python
# Webhook: issues.labeled → ai-implement
async def on_ai_implement_label(issue):
    # 1. 이슈 분석
    context = await analyze_issue(issue)  # 제목, 본문, 라벨
    
    # 2. 관련 코드 탐색
    relevant_files = await find_relevant_code(context)  # Gitea file tree + grep
    
    # 3. 코드 생성
    changes = await generate_code(context, relevant_files)  # LLM
    
    # 4. 브랜치 + 커밋 + PR
    branch = f"ai/{issue.number}"
    await gitea.branches.create(owner, repo, branch)
    for file_change in changes:
        await gitea.contents.create_or_update(owner, repo, file_change)
    pr = await gitea.pulls.create(owner, repo, 
        title=f"[AI] {issue.title}",
        head=branch, body=f"Closes #{issue.number}\n\n{changes.explanation}")
    
    # 5. 자동 리뷰 트리거
    await reviewer.review_and_post(owner, repo, pr.number)
```

### 장애 자동 대응 흐름

```python
# Alert → 코드 변경 추적 → 리버트/수정
async def on_critical_alert(alert):
    # 1. 최근 변경 추적
    recent_commits = await gitea.commits.list(owner, repo, limit=5)
    
    # 2. 변경과 장애 연관성 분석
    analysis = await llm.analyze(alert, recent_commits)
    
    # 3. 판단
    if analysis.cause == "code_change":
        # 리버트 PR 생성
        await agent_ops.create_revert_pr(owner, repo, analysis.commit_sha)
    elif analysis.cause == "config":
        # 설정 수정 PR
        await agent_ops.create_hotfix(owner, repo, analysis.fix)
    else:
        # 인프라 복구
        await remediation.execute_and_verify(action_id, alert_id)
    
    # 4. 인시던트 기록
    await incidents.add_timeline(incident_id, "AI 자동 대응 실행")
```

### MCP 도구 확장 계획

| # | 도구 | 설명 | 우선순위 |
|---|------|------|---------|
| 38 | `ai_implement_issue` | 이슈 자동 구현 | 즉시 |
| 39 | `ai_fix_test` | 테스트 실패 자동 수정 | 즉시 |
| 40 | `ai_revert_commit` | 장애 시 커밋 리버트 PR | 즉시 |
| 41 | `ai_update_deps` | 의존성 업데이트 PR | 단기 |
| 42 | `ai_generate_test` | 누락 테스트 자동 생성 | 단기 |
| 43 | `ai_update_docs` | 코드 변경 시 문서 갱신 | 단기 |
| 44 | `ai_canary_deploy` | 카나리 배포 | 중기 |
| 45 | `ai_sla_report` | SLA 보고서 생성 | 중기 |

---

## 5. 성공 지표

| 지표 | 현재 | 목표 |
|------|------|------|
| 이슈→코드 자동 구현 | 0% | 단순 이슈 70% 자동 |
| 테스트 실패 자동 수정 | 0% | 50% 자동 수정 |
| 장애→자동 대응 | 알림만 | 코드 리버트/설정 수정 자동 |
| 문서 자동 갱신 | 0% | API/아키텍처 100% 동기화 |
| 보안 패치 자동 | 수동 | CVE 감지 → PR 자동 |
| 에이전트 자율 작업 | 0건/일 | 10+ 건/일 |

---

## 6. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| AI 코드 품질 불안정 | 높음 | 자동 리뷰 + 테스트 게이트 필수 |
| 자동 리버트 오판 | 높음 | Critical만 자동, 나머지 승인 필요 |
| LLM 비용 폭증 | 중간 | 로컬 Ollama 우선, 복잡한 것만 클라우드 LLM |
| 무한 루프 (수정→실패→수정) | 높음 | 최대 재시도 3회, 실패 시 사람에게 에스컬레이션 |
| 에이전트 권한 남용 | 중간 | main 직접 push 금지, PR만 허용, 승인 게이트 |
