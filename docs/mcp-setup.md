# WeruBWorker MCP 서버 설정 가이드

## 개요

WeruBWorker 모니터링 도구를 MCP(Model Context Protocol) 서버로 외부 AI에 노출합니다.
Claude Desktop, Cursor, 기타 MCP 호환 클라이언트에서 서버 모니터링 데이터를 직접 조회할 수 있습니다.

## 제공되는 도구 (10개)

| 도구 | 설명 |
|------|------|
| `metrics_latest` | 전체 서버 최신 메트릭 (CPU, 메모리, 디스크) |
| `metrics_query` | 시계열 메트릭 조회 (15m~30d) |
| `healthcheck_list` | 헬스체크 규칙 목록 |
| `healthcheck_run` | 헬스체크 즉시 실행 |
| `active_alerts` | 활성 알림 목록 |
| `alert_rules` | 알림 규칙 목록 |
| `incidents_list` | 인시던트 목록 |
| `incident_get` | 인시던트 상세 (타임라인 포함) |
| `audit_recent` | 운영 감사 로그 |
| `dashboard_overview` | 인프라 전체 현황 |

## Claude Desktop 설정

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "werubworker-monitoring": {
      "command": "/Users/seanshin/ai/agent/openworker/.venv/bin/python",
      "args": ["-m", "coworker.mcp.monitoring_server"]
    }
  }
}
```

## Cursor 설정

`.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "werubworker-monitoring": {
      "command": "/Users/seanshin/ai/agent/openworker/.venv/bin/python",
      "args": ["-m", "coworker.mcp.monitoring_server"]
    }
  }
}
```

## Claude Code 설정

`.claude/settings.json`:

```json
{
  "mcpServers": {
    "werubworker-monitoring": {
      "command": "/Users/seanshin/ai/agent/openworker/.venv/bin/python",
      "args": ["-m", "coworker.mcp.monitoring_server"]
    }
  }
}
```

## 직접 실행 테스트

```bash
cd /Users/seanshin/ai/agent/openworker
.venv/bin/python -m coworker.mcp.monitoring_server
```

## 사용 예시

Claude Desktop에서:
- "서버 상태 확인해줘" → `dashboard_overview` 호출
- "CPU 메트릭 1시간치 보여줘" → `metrics_query(server_id="__local__", range="1h")`
- "헬스체크 실행해줘" → `healthcheck_run` 호출
- "활성 알림 있어?" → `active_alerts` 호출
- "인시던트 목록 보여줘" → `incidents_list` 호출
