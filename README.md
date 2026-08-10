# WeruBWorker

로컬 우선 AI 에이전트 플랫폼 — 서버 관리, 개발 관리, 인프라 운영을 위한 통합 도구.

> Based on [OpenWorker](https://github.com/andrewyng/openworker) (MIT License)

## 주요 기능

| 기능 | 설명 |
|------|------|
| 🤖 **다중 모델** | Ollama, OpenAI 호환 서버, 자체 AI 서버 연동 |
| 🖥 **서버 관리** | SSH, Docker, Kubernetes, 시스템 모니터링 |
| 🔧 **개발 관리** | CI/CD (GitHub Actions), 코드 리뷰, 테스트 커버리지 |
| 🗄 **DB 관리** | PostgreSQL/MySQL/SQLite 쿼리, 상태, 백업 |
| ☁️ **클라우드** | AWS (EC2/S3/CloudWatch), Cloudflare (DNS/캐시), Wasabi |
| 📚 **서비스 위키** | 자격증명 문서화 + AI 자동 추출 + 암호화 볼트 |
| 🔐 **보안** | 마스터 비밀번호, AES-256 암호화, 감사 로그 |
| 🌐 **한국어** | 전체 UI 한국어/영어 전환 (1,100+ 번역 키) |
| 🔗 **25+ 연동** | Slack, GitHub, Gmail, Jira, HubSpot 등 |

## 에이전트

| 에이전트 | 도구 수 | 용도 |
|----------|---------|------|
| **Cowork** | 기본 | 지식작업, 분석, 보고서 |
| **Code** | 기본 | 코딩, 디버깅, 리팩토링 |
| **Chat** | — | 단순 대화 |
| **Ops** | 30 | 서버 운영, 인프라 관리, Docker, K8s, DB, 클라우드 |
| **Dev** | 8 | CI/CD, 코드 리뷰, 프로젝트 관리 |

## 빠른 시작

```bash
# 클론
git clone https://github.com/seanshin/werubworker.git
cd werubworker

# Python 설정
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,messaging,browser,bedrock]"

# GUI 설정
cd surfaces/gui && npm install && cd ../..

# 서버 실행
.venv/bin/python -m coworker.server.run --host 0.0.0.0 --port 8765

# GUI 실행 (별도 터미널)
TOKEN=$(cat ~/.config/werubworker/sidecar-8765.token | tr -d '\n')
cd surfaces/gui && VITE_COWORKER_API_TOKEN="$TOKEN" npx vite --host 0.0.0.0
```

브라우저에서 `http://localhost:1420` 접속

## 도구 (54개)

| 모듈 | 도구 수 | 내용 |
|------|---------|------|
| 서버 모니터링 | 6 | CPU, 메모리, 디스크, 포트, 프로세스, 로그 |
| SSH | 7 | 원격 실행, 상태, 파일, 로그, 포트 |
| Docker | 7 | ps, logs, restart, compose, stats, images |
| Kubernetes | 6 | pods, logs, describe, restart, scale, events |
| 데이터베이스 | 4 | 쿼리, 상태, 테이블, 백업 |
| 클라우드 | 10 | AWS(4), Cloudflare(4), Wasabi(2) |
| CI/CD | 5 | 상태, 트리거, 로그, 배포, 롤백 |
| 코드 리뷰 | 3 | PR 리뷰, 보안 스캔, 커버리지 |
| 위키 | 6 | 검색, 조회, 자격증명, 수정, 알림, AI 분석 |

## 테스트

```bash
.venv/bin/pytest tests/ -q
# 1,161 passed, 74 skipped
```

## 문서

| 문서 | 설명 |
|------|------|
| [사용자 가이드](docs/user-guide.md) | 설치, 사용법, 도구 레퍼런스 |
| [아키텍처 분석](docs/architecture-analysis.md) | 전체 시스템 구조 |
| [구현 로드맵](docs/implementation-roadmap.md) | 개발 계획 |
| [기업 서비스](docs/enterprise-service-plan.md) | WeruB Service 계획 |

## 라이선스

MIT License. Based on [OpenWorker](https://github.com/andrewyng/openworker).
