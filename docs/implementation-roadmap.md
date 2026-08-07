# WeruBWorker 구현 로드맵 (일괄 작업용)

## 현재 상태

### 완료된 작업
- ✅ 기본 설치 + Ollama 연동
- ✅ 리팩토링 3단계 (integration_tools, SessionManager, App.tsx)
- ✅ 한국어 i18n (500+ 키, 30+ 컴포넌트)
- ✅ WeruBWorker 이름 변경
- ✅ Cloud 연결 제거 + UI 숨김
- ✅ Ops 에이전트 (server_monitor 6도구)
- ✅ SSH 커넥터 (7도구 + 4 API)
- ✅ 로그인/인증 시스템
- ✅ About 페이지

### 기획서 현황 (8종)
1. `architecture-analysis.md` — 아키텍처 분석
2. `i18n-korean-plan.md` — 한국어 지원
3. `ops-agent-expansion-plan.md` — Ops 에이전트
4. `ssh-connector-plan.md` — SSH 커넥터
5. `cloud-replacement-plan.md` — Cloud 대체
6. `enterprise-service-plan.md` — 기업 서비스
7. `devops-management-plan.md` — 개발/서버관리 강화
8. `auth-login-plan.md` — 로그인/인증

---

## 남은 구현 작업 (일괄 처리 순서)

### Batch 1: 도구 구현 (백엔드, 병렬 가능)

각 도구는 독립적이므로 동시 작업 가능합니다.

#### 1-A. Docker 관리 도구
**파일**: `coworker/tools/docker_mgmt.py`
**카탈로그**: `catalog.py`에 `docker` Capability 추가
**도구 7개**:
```
docker_ps(server, filter) → 컨테이너 목록
docker_logs(container, lines, server) → 컨테이너 로그
docker_restart(container, server) → 재시작 [승인]
docker_compose_status(path, server) → compose 상태
docker_compose_up(path, service, server) → compose 시작 [승인]
docker_stats(server) → 리소스 사용량
docker_images(server) → 이미지 목록
```
**구현**: subprocess로 `docker`/`docker compose` 명령 실행 (로컬 + SSH 원격)

#### 1-B. 데이터베이스 관리 도구
**파일**: `coworker/tools/db_mgmt.py`
**카탈로그**: `catalog.py`에 `database` Capability 추가
**도구 4개**:
```
db_query(query, database, readonly) → 쿼리 실행 [쓰기 시 승인]
db_status(database) → DB 상태 (연결 수, 크기)
db_tables(database) → 테이블 목록 + 레코드 수
db_backup(database) → 백업 [승인]
```
**구현**: DB 연결정보는 `secrets.json`의 `database:*`에서 읽음
**의존성**: `psycopg2-binary` (PostgreSQL), `pymysql` (MySQL) — 선택적

#### 1-C. 클라우드 인프라 도구
**파일**: `coworker/tools/cloud_infra.py`
**카탈로그**: `catalog.py`에 `cloud_infra` Capability 추가
**도구 10개**:
```
# AWS (boto3 사용, 이미 설치됨)
aws_ec2_list(region) → EC2 인스턴스
aws_s3_list(bucket) → S3 버킷/객체
aws_cloudwatch_metrics(service, metric, period) → 메트릭
aws_cost_explorer(period) → 비용 분석

# Cloudflare (httpx REST API)
cf_dns_list(zone) → DNS 레코드
cf_dns_update(zone, record, value) → DNS 변경 [승인]
cf_analytics(zone, period) → 트래픽 분석
cf_cache_purge(zone, urls) → 캐시 퍼지 [승인]

# Wasabi (boto3 S3 호환)
wasabi_list(bucket) → 객체 목록
wasabi_upload(local, bucket, key) → 업로드 [승인]
```
**구현**: AWS는 boto3, Cloudflare는 httpx REST, Wasabi는 boto3 S3 호환

#### 1-D. CI/CD 도구
**파일**: `coworker/tools/ci_cd.py`
**카탈로그**: `catalog.py`에 `ci_cd` Capability 추가
**도구 5개**:
```
ci_status(repo, branch) → GitHub Actions 워크플로우 상태
ci_trigger(repo, workflow, branch) → 빌드 트리거 [승인]
ci_logs(repo, run_id) → 빌드 로그
deploy_status(service) → 배포 상태
deploy_rollback(service, version) → 롤백 [승인]
```
**구현**: GitHub REST API (`gh` CLI 또는 httpx)

#### 1-E. 코드 리뷰 도구
**파일**: `coworker/tools/code_review.py`
**카탈로그**: `catalog.py`에 `code_review` Capability 추가
**도구 3개**:
```
review_pr(repo, pr_number) → PR 분석 + 리뷰 코멘트
review_security(path) → 보안 스캔
review_test_coverage(path) → 테스트 커버리지
```
**구현**: GitHub API + 로컬 분석 (grep 기반 패턴 매칭)

---

### Batch 2: 에이전트 등록 (Batch 1 완료 후)

#### 2-A. Dev 에이전트
**파일**: `coworker/agents/dev.py`
**capabilities**: `["code_files", "git", "search", "shell", "todo", "ci_cd", "code_review"]`
**페르소나**: `coworker/personas/builtin/dev.md`

#### 2-B. Ops 에이전트 강화
기존 Ops에 Docker, DB, 클라우드 도구 추가:
**capabilities**: `["files", "search", "shell", "todo", "server_monitor", "ssh", "docker", "database", "cloud_infra"]`

---

### Batch 3: GUI 페이지 (Batch 2 완료 후)

#### 3-A. ServiceConfigView (서비스 설정 페이지)
통합 토큰/설정 관리 UI:
- SSH 서버, DB, AWS, Cloudflare, Wasabi 설정
- Sidebar에 "서비스 설정" 링크 추가

#### 3-B. OpsView (서버 모니터링 대시보드)
- 서버 상태 패널 (CPU/MEM/DISK)
- Docker 컨테이너 목록
- 최근 알림

#### 3-C. DevView (개발 현황 대시보드)
- CI/CD 파이프라인 상태
- PR 리뷰 대기 목록
- 최근 커밋

#### 3-D. DatabaseView (DB 관리)
- 쿼리 실행기
- 테이블 목록
- 백업 상태

---

### Batch 4: GUI 성능 개선

#### 4-A. Transcript 가상화
- `react-window` 설치
- 1000+ 아이템 대화 성능 개선

#### 4-B. React.memo + useMemo
- Sidebar 세션 목록
- Transcript 아이템

#### 4-C. Error Boundary
- Sidebar, Transcript, RightRail 래핑

---

### Batch 5: 최종 검증

#### 5-A. i18n 검증
- 전체 UI 스크린샷 검증
- 레이아웃 깨짐 수정
- 누락 문자열 점검

#### 5-B. 통합 테스트
- Python pytest
- GUI vitest
- E2E 확인

---

## 병렬 실행 가이드

```
Batch 1 (병렬 실행 가능):
  ├── 1-A Docker 도구
  ├── 1-B DB 도구
  ├── 1-C 클라우드 도구
  ├── 1-D CI/CD 도구
  └── 1-E 코드 리뷰 도구
        ↓ 모두 완료
Batch 2 (순차):
  ├── 2-A Dev 에이전트
  └── 2-B Ops 에이전트 강화
        ↓
Batch 3 (병렬 가능):
  ├── 3-A ServiceConfigView
  ├── 3-B OpsView
  ├── 3-C DevView
  └── 3-D DatabaseView
        ↓
Batch 4 (순차):
  └── 성능 개선
        ↓
Batch 5:
  └── 최종 검증
```

## 각 Batch 검증 방법

```bash
# Python 도구 검증
cd /Users/seanshin/ai/agent/openworker
.venv/bin/python -c "from coworker.tools.docker_mgmt import docker_tools; print('OK')"
.venv/bin/python -c "from coworker.tools.db_mgmt import db_tools; print('OK')"
.venv/bin/python -c "from coworker.tools.cloud_infra import cloud_infra_tools; print('OK')"
.venv/bin/python -c "from coworker.tools.ci_cd import ci_cd_tools; print('OK')"
.venv/bin/python -c "from coworker.server.app import create_app; print('server OK')"

# GUI 검증
cd surfaces/gui && npx tsc --noEmit

# 통합
브라우저에서 localhost:1420 수동 확인
```

---

*작성일: 2026-08-07*
*프로젝트: WeruBWorker 구현 로드맵*
