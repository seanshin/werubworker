# WeruBWorker v2.0 API 레퍼런스

## 인증

모든 API 요청에는 인증 토큰이 필요합니다.

- **헤더**: `X-WeruBWorker-Token`
- **토큰 위치**: `~/.config/werubworker/sidecar-{port}.token`
- 사이드카 서버 시작 시 자동 생성되며, 파일 권한은 `600`으로 설정됩니다.

```
GET /v1/dashboard/overview
X-WeruBWorker-Token: <token>
```

---

## 대시보드 API (신규)

인프라 모니터링 현황을 조회하는 엔드포인트입니다.

| 메서드 | 경로 | 설명 | 파라미터 |
|--------|------|------|----------|
| GET | `/v1/dashboard/overview` | 인프라 전체 현황 (서버 수, 알림, 인시던트 요약) | - |
| GET | `/v1/dashboard/servers/{server_id}/metrics` | 서버 시계열 메트릭 (CPU, 메모리, 디스크, 네트워크) | `range`: 조회 범위 (`15m`, `1h`, `6h`, `1d`, `7d`, `30d`, `90d`) |
| GET | `/v1/dashboard/alerts` | 알림 피드 | `limit`: 반환 개수 (기본 50) |
| GET | `/v1/dashboard/incidents` | 인시던트 목록 | `status`: 필터 (`open`, `resolved`, `all`) |
| GET | `/v1/dashboard/audit` | 운영 감사 로그 | `limit`: 반환 개수 (기본 100) |

---

## 인프라 API (신규)

서버 인벤토리 및 서비스 토폴로지를 조회합니다.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/v1/infrastructure/servers` | 등록된 서버 목록 + 최신 메트릭 스냅샷 |
| GET | `/v1/infrastructure/topology` | 서비스 의존관계 맵 (노드/엣지 그래프) |

---

## Wiki API (기존)

운영 Wiki 페이지를 관리합니다.

| 메서드 | 경로 | 설명 | 파라미터 |
|--------|------|------|----------|
| GET | `/v1/wiki` | 페이지 목록 | - |
| GET | `/v1/wiki/{page_id}` | 페이지 상세 조회 | - |
| PUT | `/v1/wiki/{page_id}` | 페이지 수정 | Body: `{ "content": "...", "structured_data": {...} }` |
| GET | `/v1/wiki/categories` | 카테고리 목록 | - |
| GET | `/v1/wiki/search` | 전문 검색 | `q`: 검색어 (필수) |
| GET | `/v1/wiki/alerts` | 만료 알림 (인증서, 문서 갱신 등) | - |

---

## 기존 API

v1.0에서 제공되던 핵심 API입니다.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/v1/session` | 세션 생성 |
| DELETE | `/v1/session` | 세션 종료 |
| POST | `/v1/auth/login` | 사용자 로그인 |
| GET | `/v1/connectors` | 커넥터 목록 조회 |
| POST | `/v1/connectors/{type}` | 커넥터 등록 |
| GET | `/v1/automations` | 자동화 규칙 목록 |
| POST | `/v1/automations` | 자동화 규칙 생성 |
| GET | `/v1/models` | 사용 가능한 모델 목록 |
| POST | `/v1/chat` | 채팅 메시지 전송 |
| GET | `/v1/tools` | 등록된 도구 목록 |

---

## 응답 형식

모든 API는 JSON 형식으로 응답합니다.

### 성공 응답

```json
{
  "ok": true,
  "data": { ... }
}
```

### 오류 응답

```json
{
  "ok": false,
  "error": "오류 메시지"
}
```

### HTTP 상태 코드

| 코드 | 설명 |
|------|------|
| 200 | 성공 |
| 400 | 잘못된 요청 |
| 401 | 인증 실패 (토큰 누락 또는 만료) |
| 404 | 리소스를 찾을 수 없음 |
| 500 | 서버 내부 오류 |
