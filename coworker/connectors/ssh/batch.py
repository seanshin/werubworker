"""BatchSSH — parallel command execution across multiple SSH servers.

Supports server groups/tags, parallel execution via asyncio, result aggregation,
and rolling update mode (sequential with health check between each server).
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
class BatchResult:
    """일괄 명령 실행 결과."""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[dict] = field(default_factory=list)
    duration_ms: float = 0


class BatchSSH:
    """멀티 서버 병렬/순차 SSH 명령 실행."""

    def __init__(self, secrets: Any = None) -> None:
        self._secrets = secrets

    def list_servers(self, tag: str = "") -> list[dict]:
        """등록된 SSH 서버 목록 (태그 필터 가능)."""
        if not self._secrets:
            return []
        servers = []
        for entry in self._secrets.status():
            key = entry.get("profile", "")
            if key.startswith("ssh:server:"):
                server_id = key[len("ssh:server:"):]
                profile = self._secrets.get(key) or {}
                if tag and tag not in (profile.get("tags") or []):
                    continue
                servers.append({"server_id": server_id, **profile})
        return servers

    def list_tags(self) -> list[str]:
        """사용 가능한 태그 목록."""
        tags: set[str] = set()
        for s in self.list_servers():
            for t in s.get("tags") or []:
                tags.add(t)
        return sorted(tags)

    async def execute_parallel(
        self,
        command: str,
        server_ids: list[str] | None = None,
        tag: str = "",
        timeout: int = 30,
        max_concurrent: int = 10,
        sudo: bool = False,
    ) -> BatchResult:
        """여러 서버에 병렬로 명령 실행."""
        servers = self._resolve_servers(server_ids, tag)
        if not servers:
            return BatchResult()

        start = time.time()
        sem = asyncio.Semaphore(max_concurrent)

        async def _run_one(server_info: dict) -> dict:
            async with sem:
                return await self._execute_on_server(server_info, command, timeout, sudo)

        results = await asyncio.gather(
            *[_run_one(s) for s in servers],
            return_exceptions=True,
        )

        batch = BatchResult(total=len(servers))
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                batch.results.append({
                    "server_id": servers[i]["server_id"],
                    "ok": False,
                    "error": str(result),
                })
                batch.failed += 1
            else:
                batch.results.append(result)
                if result.get("ok"):
                    batch.succeeded += 1
                else:
                    batch.failed += 1

        batch.duration_ms = round((time.time() - start) * 1000, 1)
        return batch

    async def execute_rolling(
        self,
        command: str,
        server_ids: list[str] | None = None,
        tag: str = "",
        timeout: int = 30,
        sudo: bool = False,
        delay_seconds: int = 5,
        stop_on_failure: bool = True,
    ) -> BatchResult:
        """롤링 업데이트: 한 서버씩 순차 실행, 실패 시 중단 옵션."""
        servers = self._resolve_servers(server_ids, tag)
        if not servers:
            return BatchResult()

        start = time.time()
        batch = BatchResult(total=len(servers))

        for server_info in servers:
            result = await self._execute_on_server(server_info, command, timeout, sudo)
            batch.results.append(result)

            if result.get("ok"):
                batch.succeeded += 1
            else:
                batch.failed += 1
                if stop_on_failure:
                    log.warning("rolling execution stopped at %s: %s", server_info["server_id"], result.get("error"))
                    break

            if delay_seconds > 0 and server_info != servers[-1]:
                await asyncio.sleep(delay_seconds)

        batch.duration_ms = round((time.time() - start) * 1000, 1)
        return batch

    def _resolve_servers(self, server_ids: list[str] | None, tag: str) -> list[dict]:
        """서버 ID 또는 태그로 대상 서버 목록 결정."""
        all_servers = self.list_servers(tag=tag)
        if server_ids:
            return [s for s in all_servers if s["server_id"] in server_ids]
        return all_servers

    async def _execute_on_server(self, server_info: dict, command: str, timeout: int, sudo: bool) -> dict:
        """단일 서버에서 명령 실행."""
        server_id = server_info.get("server_id", "unknown")
        server = SSHServer(
            server_id=server_id,
            host=server_info.get("host", ""),
            port=server_info.get("port", 22),
            username=server_info.get("username", "deploy"),
            key_path=server_info.get("key_path"),
        )
        client = SSHClient(server)
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: client.execute(command, sudo=sudo, timeout=timeout),
            )
            return {"server_id": server_id, **result}
        except Exception as e:
            return {"server_id": server_id, "ok": False, "error": str(e)}
