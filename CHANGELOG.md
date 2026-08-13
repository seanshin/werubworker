# Changelog

## [2.0.0] - 2026-08-13

### Added — 모니터링 서브시스템
- 시계열 저장소 (SQLite, 4단계 다운샘플링)
- 멀티 서버 메트릭 수집기 (SSH 병렬, asyncio)
- 8종 헬스체크 매니저 (HTTP/TCP/DNS/Ping/SSL/Docker/K8s/Process)
- 규칙 기반 알림 엔진 (cooldown, 에스컬레이션)
- 인시던트 관리 (타임라인, 에스컬레이션, 사후분석)
- 자동 복구 엔진 (7개 기본 액션, Inbox 승인)
- 다중 서버 로그 집계 (패턴 매칭, 심각도 분류)
- 운영 감사 로그 (append-only, CSV 내보내기)

### Added — 도구 확장
- 서버 온보딩 (등록→테스트→Wiki 자동 생성)
- 서비스 설정 (Nginx/systemd/Compose 생성, 의존관계 맵)
- 보안 스캔 (포트, SSL, 인증 로그, 취약점, 파일 무결성)
- 네트워크 진단 (traceroute, MTR, DNS, 대역폭)
- IaC (Terraform plan/state, Ansible playbook)
- 인증서 관리 (SSL 모니터링, Let's Encrypt 갱신)
- 개발 환경 (프로젝트 스캔, Git 연동)
- Docker 확장 (+4: inspect, networks, volumes, prune)
- K8s 확장 (+5: nodes, top, ingress, hpa, contexts)
- Cloud 확장 (+4: RDS, ELB, Route53, IAM audit)

### Added — 멀티 클라우드
- GCP 연동 (Compute Engine, GKE)
- Azure 연동 (VM, AKS)

### Added — 플랫폼 통합
- DashboardMixin (12 REST 엔드포인트)
- WikiAutoSync (도구 실행→Wiki 자동 동기화)
- ServiceResolver (자연어 서비스 참조 해석)
- SRE 에이전트 (21 capability, 100+ 도구)
- 개발팀 페르소나 5개 (tech-lead, backend-dev, ui-dev, qa-engineer, planner)
- SSH 터널링 (TunnelManager)
- Wiki 확장 도구 7개 (create, delete, history, categories, recent, credential, runbook)
- Wiki 카테고리 5개 추가 (development, config, incident, network, backup)
- 서비스 시작 스크립트 (start.sh)

### Changed
- catalog.py: 15 → 23 Capability
- SRE 페르소나: 19 capability
- WikiStore.update_page(): structured_data 파라미터 추가

### Stats
- 신규 파일: 51개
- 신규 코드: +13,240줄
- 테스트: 1,226 passed (신규 65개)

## [1.0.0] - 이전 릴리즈
- 초기 버전 (Ops/Dev 에이전트, 54개 도구, GUI)
