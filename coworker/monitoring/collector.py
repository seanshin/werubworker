"""MetricCollector — multi-server metric collection via SSH.

Collects CPU, memory, disk, network, and load metrics from registered SSH servers
in parallel using asyncio. Local server metrics are collected via psutil or shell.
Results are stored in TimeSeriesStore.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class CollectorConfig:
    """수집기 설정."""

    interval_seconds: int = 60
    parallel_workers: int = 10
    collect_local: bool = True
    ssh_timeout: int = 15


class MetricCollector:
    """SSH 기반 다중 서버 메트릭 수집기.

    등록된 모든 SSH 서버에서 CPU, 메모리, 디스크, 네트워크, 로드 메트릭을
    병렬로 수집하고 TimeSeriesStore에 저장한다.

    사용 예시::

        from coworker.monitoring.timeseries import TimeSeriesStore
        from coworker.secrets import SecretStore

        ts = TimeSeriesStore(Path("metrics.db"))
        secrets = SecretStore()
        collector = MetricCollector(ts, secrets)

        result = await collector.collect_all()
        # {"ok": True, "collected": 3, "errors": [], "total": 4}
    """

    def __init__(
        self,
        ts_store: Any,
        secrets: Any | None = None,
        config: CollectorConfig | None = None,
        on_collect: Any | None = None,
    ) -> None:
        """MetricCollector를 초기화한다.

        Parameters
        ----------
        ts_store:
            TimeSeriesStore 인스턴스 — record / record_batch 메서드 필요.
        secrets:
            SecretStore 인스턴스 — SSH 서버 프로필 조회용. None이면 원격 수집 비활성.
        config:
            수집 설정. None이면 기본값 사용.
        on_collect:
            수집 완료 후 호출되는 콜백. ``async def on_collect(points)`` 형태.
        """
        self._ts = ts_store
        self._secrets = secrets
        self._config = config or CollectorConfig()
        self._on_collect = on_collect
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def collect_all(self) -> dict[str, Any]:
        """등록된 모든 서버에서 메트릭을 병렬 수집하고 TimeSeriesStore에 저장.

        Returns
        -------
        dict
            ``{"ok": True, "collected": int, "errors": list, "total": int}``
        """
        servers: list[dict[str, Any]] = self._list_servers()
        if self._config.collect_local:
            servers.append({"server_id": "__local__", "local": True})

        sem = asyncio.Semaphore(self._config.parallel_workers)

        async def _collect_one(server_info: dict[str, Any]) -> dict[str, Any]:
            async with sem:
                return await self._collect_server(server_info)

        results = await asyncio.gather(
            *[_collect_one(s) for s in servers],
            return_exceptions=True,
        )

        points: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append(
                    {"server_id": servers[i].get("server_id", "?"), "error": str(result)}
                )
                log.warning(
                    "collection failed for %s: %s", servers[i].get("server_id"), result
                )
            elif result and result.get("ok"):
                points.append(result["point"])
            elif result:
                errors.append(
                    {
                        "server_id": result.get("server_id", "?"),
                        "error": result.get("error", "unknown"),
                    }
                )

        if points:
            self._ts.record_batch(points)

        if points and self._on_collect:
            try:
                await self._on_collect(points)
            except Exception:
                log.warning("on_collect callback error", exc_info=True)

        return {"ok": True, "collected": len(points), "errors": errors, "total": len(servers)}

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """백그라운드 수집 루프를 시작한다.

        이미 실행 중이면 무시된다.
        """
        if self._running:
            return
        self._running = True
        _loop = loop or asyncio.get_event_loop()
        self._task = _loop.create_task(self._loop())

    async def stop(self) -> None:
        """수집 루프를 중지한다."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Internal — server discovery
    # ------------------------------------------------------------------

    def _list_servers(self) -> list[dict[str, Any]]:
        """SecretStore에서 ``ssh:server:*`` 프로필 목록을 조회한다.

        Returns
        -------
        list[dict]
            ``[{"server_id": "web-01", "host": "...", ...}, ...]``
        """
        if not self._secrets:
            return []
        servers: list[dict[str, Any]] = []
        for entry in self._secrets.status():
            key: str = entry.get("profile", "")
            if key.startswith("ssh:server:"):
                server_id = key[len("ssh:server:") :]
                profile = self._secrets.get(key)
                if profile:
                    servers.append({"server_id": server_id, **profile})
        return servers

    # ------------------------------------------------------------------
    # Internal — per-server collection
    # ------------------------------------------------------------------

    async def _collect_server(self, server_info: dict[str, Any]) -> dict[str, Any]:
        """단일 서버 메트릭을 수집한다.

        Parameters
        ----------
        server_info:
            서버 프로필 dict. ``local=True``이면 로컬 수집.
        """
        server_id: str = server_info.get("server_id", "unknown")

        if server_info.get("local"):
            return await self._collect_local(server_id)

        return await self._collect_remote(server_id, server_info)

    async def _collect_local(self, server_id: str) -> dict[str, Any]:
        """로컬 서버 메트릭을 수집한다 (psutil 우선, 셸 폴백)."""
        loop = asyncio.get_event_loop()
        point: dict[str, Any] = await loop.run_in_executor(None, self._local_metrics)
        point["server_id"] = server_id
        return {"ok": True, "server_id": server_id, "point": point}

    def _local_metrics(self) -> dict[str, Any]:
        """psutil 또는 셸 명령으로 로컬 메트릭을 수집한다.

        Returns
        -------
        dict
            ``{"cpu": float, "memory": float, "disk": float,
              "net_rx": int, "net_tx": int, "load_1m": float}``
        """
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            net = psutil.net_io_counters()
            load = psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else 0.0
            return {
                "cpu": cpu,
                "memory": mem.percent,
                "disk": disk.percent,
                "net_rx": net.bytes_recv,
                "net_tx": net.bytes_sent,
                "load_1m": load,
            }
        except ImportError:
            pass

        # 셸 폴백 — psutil 없을 때 최소한의 메트릭
        import os

        cpu = 0.0
        mem = 0.0
        disk = 0.0
        try:
            load = os.getloadavg()[0]
        except (OSError, AttributeError):
            load = 0.0
        return {
            "cpu": cpu,
            "memory": mem,
            "disk": disk,
            "net_rx": 0,
            "net_tx": 0,
            "load_1m": load,
        }

    async def _collect_remote(
        self, server_id: str, profile: dict[str, Any]
    ) -> dict[str, Any]:
        """SSH로 원격 서버 메트릭을 수집한다.

        Parameters
        ----------
        server_id:
            서버 식별자 (예: ``"web-01"``).
        profile:
            SSH 접속 정보 — ``host``, ``port``, ``username``, ``key_path`` 등.
        """
        from ..connectors.ssh.client import SSHClient, SSHServer

        server = SSHServer(
            server_id=server_id,
            host=profile["host"],
            port=profile.get("port", 22),
            username=profile.get("username", "deploy"),
            key_path=profile.get("key_path"),
        )
        client = SSHClient(server)

        # 하나의 SSH 명령으로 모든 메트릭을 한 번에 수집
        cmd = (
            "echo '---CPU---' && "
            "grep 'cpu ' /proc/stat 2>/dev/null || sysctl -n vm.loadavg 2>/dev/null && "
            "echo '---MEM---' && "
            "free -b 2>/dev/null || vm_stat 2>/dev/null && "
            "echo '---DISK---' && "
            "df / --output=pcent 2>/dev/null || df -h / | tail -1 && "
            "echo '---NET---' && "
            "cat /proc/net/dev 2>/dev/null | grep -E 'eth0|ens|enp' | head -1 && "
            "echo '---LOAD---' && "
            "cat /proc/loadavg 2>/dev/null || sysctl -n vm.loadavg 2>/dev/null"
        )

        loop = asyncio.get_event_loop()
        result: dict[str, Any] = await loop.run_in_executor(
            None, lambda: client.execute(cmd, timeout=self._config.ssh_timeout)
        )

        if not result.get("ok"):
            return {
                "ok": False,
                "server_id": server_id,
                "error": result.get("error", result.get("stderr", "ssh failed")),
            }

        point = self._parse_remote_output(result.get("stdout", ""))
        point["server_id"] = server_id
        return {"ok": True, "server_id": server_id, "point": point}

    # ------------------------------------------------------------------
    # Internal — parsing
    # ------------------------------------------------------------------

    def _parse_remote_output(self, output: str) -> dict[str, Any]:
        """원격 수집 결과를 파싱하여 메트릭 dict로 변환한다.

        ``---CPU---``, ``---MEM---`` 등의 구분자로 분리된 섹션을 각각 파싱한다.

        Returns
        -------
        dict
            ``{"cpu": float, "memory": float, "disk": float,
              "net_rx": int, "net_tx": int, "load_1m": float}``
        """
        cpu = 0.0
        memory = 0.0
        disk = 0.0
        net_rx = 0
        net_tx = 0
        load_1m = 0.0

        sections = output.split("---")
        for section in sections:
            section = section.strip()
            if not section:
                continue
            lines = section.strip().split("\n")
            header = lines[0].strip() if lines else ""
            body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

            if header == "CPU":
                cpu = self._parse_cpu(body)
            elif header == "MEM":
                memory = self._parse_mem(body)
            elif header == "DISK":
                disk = self._parse_disk(body)
            elif header == "NET":
                net_rx, net_tx = self._parse_net(body)
            elif header == "LOAD":
                load_1m = self._parse_load(body)

        return {
            "cpu": cpu,
            "memory": memory,
            "disk": disk,
            "net_rx": net_rx,
            "net_tx": net_tx,
            "load_1m": load_1m,
        }

    @staticmethod
    def _parse_cpu(body: str) -> float:
        """/proc/stat ``cpu`` 행에서 CPU 사용률(%)을 계산한다."""
        parts = body.split()
        if len(parts) >= 5:
            try:
                user, nice, system, idle = (int(x) for x in parts[1:5])
                total = user + nice + system + idle
                if total > 0:
                    return round((1 - idle / total) * 100, 1)
            except (ValueError, IndexError):
                pass
        return 0.0

    @staticmethod
    def _parse_mem(body: str) -> float:
        """``free -b`` 출력에서 메모리 사용률(%)을 계산한다."""
        for line in body.split("\n"):
            if line.strip().startswith("Mem:"):
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        total = int(parts[1])
                        used = int(parts[2])
                        if total > 0:
                            return round(used / total * 100, 1)
                    except (ValueError, IndexError):
                        pass
        return 0.0

    @staticmethod
    def _parse_disk(body: str) -> float:
        """``df --output=pcent`` 출력에서 디스크 사용률(%)을 추출한다."""
        for line in body.split("\n"):
            line = line.strip().rstrip("%")
            try:
                return float(line)
            except ValueError:
                continue
        return 0.0

    @staticmethod
    def _parse_net(body: str) -> tuple[int, int]:
        """/proc/net/dev 출력에서 RX/TX 바이트를 추출한다."""
        parts = body.split()
        if len(parts) >= 10:
            try:
                return int(parts[1]), int(parts[9])
            except (ValueError, IndexError):
                pass
        return 0, 0

    @staticmethod
    def _parse_load(body: str) -> float:
        """/proc/loadavg 출력에서 1분 평균 로드를 추출한다."""
        parts = body.split()
        if parts:
            try:
                return float(parts[0])
            except ValueError:
                pass
        return 0.0

    # ------------------------------------------------------------------
    # Internal — background loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """``interval_seconds`` 간격으로 ``collect_all``을 반복 실행한다."""
        while self._running:
            try:
                result = await self.collect_all()
                log.info(
                    "collected metrics: %d servers, %d errors",
                    result.get("collected", 0),
                    len(result.get("errors", [])),
                )
            except Exception:
                log.exception("collection loop error")
            await asyncio.sleep(self._config.interval_seconds)
