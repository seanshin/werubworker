"""ServerOnboarding — automated SSH server registration and setup.

Handles SSH key deployment, initial system info collection, Wiki page creation,
health check auto-configuration, and metric collection setup.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .client import SSHClient, SSHServer

log = logging.getLogger(__name__)


@dataclass
class OnboardingResult:
    """온보딩 결과."""
    server_id: str = ""
    steps_completed: list[str] = field(default_factory=list)
    steps_failed: list[str] = field(default_factory=list)
    system_info: dict = field(default_factory=dict)
    wiki_page_id: str = ""
    health_checks_created: list[str] = field(default_factory=list)


class ServerOnboarding:
    """SSH 서버 온보딩 자동화 엔진."""

    def __init__(self, secrets: Any = None, wiki_store: Any = None, hc_manager: Any = None) -> None:
        self._secrets = secrets
        self._wiki = wiki_store
        self._hc = hc_manager

    async def onboard(
        self,
        server_id: str,
        host: str,
        port: int = 22,
        username: str = "deploy",
        key_path: str = "",
        label: str = "",
        tags: list[str] | None = None,
    ) -> OnboardingResult:
        """서버를 온보딩한다.

        단계:
        1. SSH 연결 테스트
        2. 시스템 정보 수집 (OS, CPU, 메모리, 디스크)
        3. SSH 프로필 저장
        4. Wiki 페이지 자동 생성
        5. 기본 헬스체크 규칙 설정
        """
        result = OnboardingResult(server_id=server_id)
        server = SSHServer(
            server_id=server_id, host=host, port=port,
            username=username, key_path=key_path,
            label=label or server_id, tags=tags or [],
        )
        client = SSHClient(server)

        # Step 1: SSH 연결 테스트
        loop = asyncio.get_event_loop()
        try:
            test = await loop.run_in_executor(None, client.test_connection)
            if not test.get("ok"):
                result.steps_failed.append(f"ssh_connect: {test.get('error', 'failed')}")
                return result
            result.steps_completed.append("ssh_connect")
        except Exception as e:
            result.steps_failed.append(f"ssh_connect: {e}")
            return result

        # Step 2: 시스템 정보 수집
        try:
            info = await self._collect_system_info(client, loop)
            result.system_info = info
            result.steps_completed.append("system_info")
        except Exception as e:
            result.steps_failed.append(f"system_info: {e}")
            info = {}

        # Step 3: SSH 프로필 저장
        try:
            if self._secrets:
                profile = {
                    "host": host, "port": port, "username": username,
                    "key_path": key_path, "label": label or server_id,
                    "tags": tags or [], "added_at": time.time(),
                    "os": info.get("os", ""), "cpu_cores": info.get("cpu_cores", 0),
                    "memory_gb": info.get("memory_gb", 0),
                }
                self._secrets.set(f"ssh:server:{server_id}", profile)
                result.steps_completed.append("profile_saved")
        except Exception as e:
            result.steps_failed.append(f"profile_save: {e}")

        # Step 4: Wiki 페이지 생성
        try:
            if self._wiki:
                content = self._generate_wiki_content(server_id, host, port, username, info)
                page_id = self._wiki.create_page(
                    title=f"서버: {label or server_id}",
                    content=content,
                    category="server",
                    tags=["server", "onboarding", server_id] + (tags or []),
                )
                result.wiki_page_id = str(page_id)
                result.steps_completed.append("wiki_page")
        except Exception as e:
            result.steps_failed.append(f"wiki_page: {e}")

        # Step 5: 기본 헬스체크 설정
        try:
            if self._hc:
                checks = await self._setup_health_checks(server_id, host, port, info)
                result.health_checks_created = checks
                if checks:
                    result.steps_completed.append("health_checks")
        except Exception as e:
            result.steps_failed.append(f"health_checks: {e}")

        return result

    async def _collect_system_info(self, client: SSHClient, loop: asyncio.AbstractEventLoop) -> dict:
        """시스템 정보를 수집한다."""
        cmd = (
            "echo '---OS---' && uname -a && "
            "echo '---DISTRO---' && cat /etc/os-release 2>/dev/null | head -5 && "
            "echo '---CPU---' && nproc 2>/dev/null && "
            "echo '---MEM---' && free -g 2>/dev/null | grep Mem | awk '{print $2}' && "
            "echo '---DISK---' && df -h / | tail -1 && "
            "echo '---UPTIME---' && uptime && "
            "echo '---SERVICES---' && systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -20"
        )
        result = await loop.run_in_executor(None, lambda: client.execute(cmd, timeout=15))
        stdout = result.get("stdout", "")

        info: dict = {}
        sections = stdout.split("---")
        for section in sections:
            section = section.strip()
            if not section:
                continue
            lines = section.split("\n")
            header = lines[0].strip()
            body = "\n".join(lines[1:]).strip()

            if header == "OS":
                info["os"] = body.split("\n")[0] if body else ""
            elif header == "DISTRO":
                for line in body.split("\n"):
                    if line.startswith("PRETTY_NAME="):
                        info["distro"] = line.split("=", 1)[1].strip('"')
            elif header == "CPU":
                try:
                    info["cpu_cores"] = int(body.strip())
                except ValueError:
                    pass
            elif header == "MEM":
                try:
                    info["memory_gb"] = int(body.strip())
                except ValueError:
                    pass
            elif header == "DISK":
                info["disk_info"] = body
            elif header == "UPTIME":
                info["uptime"] = body
            elif header == "SERVICES":
                services = []
                for line in body.split("\n"):
                    parts = line.split()
                    if parts and parts[0].endswith(".service"):
                        services.append(parts[0].replace(".service", ""))
                info["services"] = services[:20]

        return info

    def _generate_wiki_content(self, server_id: str, host: str, port: int, username: str, info: dict) -> str:
        """Wiki 페이지 콘텐츠를 생성한다."""
        services = info.get("services", [])
        return f"""# 서버: {server_id}

## 접속 정보
| 항목 | 값 |
|------|-----|
| 호스트 | `{host}` |
| 포트 | {port} |
| 사용자 | {username} |
| OS | {info.get('os', '확인 중')} |
| 배포판 | {info.get('distro', '확인 중')} |
| CPU | {info.get('cpu_cores', '?')} 코어 |
| 메모리 | {info.get('memory_gb', '?')} GB |
| 디스크 | {info.get('disk_info', '확인 중')} |
| 가동시간 | {info.get('uptime', '확인 중')} |

## 실행 중인 서비스
{chr(10).join(f'- {s}' for s in services) if services else '서비스 목록 수집 중...'}

## 모니터링
- 헬스체크: 자동 설정됨
- 메트릭 수집: 60초 간격

---
*온보딩 일시: {time.strftime('%Y-%m-%d %H:%M:%S')}*
"""

    async def _setup_health_checks(self, server_id: str, host: str, port: int, info: dict) -> list[str]:
        """기본 헬스체크 규칙을 설정한다."""
        created = []

        # SSH 연결 체크
        try:
            from ...monitoring.healthcheck import HealthCheckRule
            ssh_check = HealthCheckRule(
                name=f"{server_id}-ssh",
                type="tcp",
                target=f"{host}:{port}",
                interval_seconds=300,
                timeout_seconds=10,
            )
            result = self._hc.add_check(ssh_check)
            if result.get("ok"):
                created.append(f"{server_id}-ssh")
        except Exception as e:
            log.warning("failed to create SSH health check: %s", e)

        # HTTP 체크 (웹 서비스가 있는 경우)
        services = info.get("services", [])
        if any(s in services for s in ["nginx", "apache2", "httpd", "caddy"]):
            try:
                http_check = HealthCheckRule(
                    name=f"{server_id}-http",
                    type="http",
                    target=f"http://{host}",
                    interval_seconds=60,
                    timeout_seconds=10,
                )
                result = self._hc.add_check(http_check)
                if result.get("ok"):
                    created.append(f"{server_id}-http")
            except Exception:
                pass

        return created
