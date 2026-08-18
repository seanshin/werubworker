"""AnomalyDetector — statistical anomaly detection with optional LLM analysis.

Uses Z-score and exponential moving average to detect metric anomalies.
Optionally calls LLM for natural-language root cause analysis.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class AnomalyConfig:
    z_score_threshold: float = 3.0
    derivative_threshold: float = 50.0
    min_data_points: int = 10
    baseline_days: int = 7
    metrics: list[str] = field(default_factory=lambda: ["cpu", "memory", "disk", "load_1m"])


@dataclass
class Anomaly:
    server_id: str
    metric: str
    timestamp: float
    value: float
    expected: float
    z_score: float
    severity: str  # low, medium, high
    description: str


@dataclass
class Baseline:
    metric: str
    mean: float
    std: float
    data_points: int


class AnomalyDetector:
    """통계 기반 이상 탐지 + LLM 보강 분석."""

    def __init__(self, ts_store: Any, config: AnomalyConfig | None = None) -> None:
        self._ts = ts_store
        self._config = config or AnomalyConfig()

    def get_baseline(self, server_id: str, metric: str, days: int | None = None) -> Baseline:
        days = days or self._config.baseline_days
        end = time.time()
        start = end - days * 86400
        points = self._ts.query(server_id, start=start, end=end)
        values = [p.get(metric, 0) for p in points if metric in p]
        if len(values) < self._config.min_data_points:
            return Baseline(metric=metric, mean=0, std=0, data_points=len(values))
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance) if variance > 0 else 0.001
        return Baseline(metric=metric, mean=mean, std=std, data_points=len(values))

    def detect(self, server_id: str, window_minutes: int = 60) -> list[Anomaly]:
        end = time.time()
        start = end - window_minutes * 60
        points = self._ts.query(server_id, start=start, end=end)
        if not points:
            return []

        anomalies: list[Anomaly] = []
        for metric in self._config.metrics:
            baseline = self.get_baseline(server_id, metric)
            if baseline.data_points < self._config.min_data_points:
                continue
            for p in points:
                val = p.get(metric)
                if val is None:
                    continue
                z = abs(val - baseline.mean) / baseline.std if baseline.std > 0 else 0
                if z >= self._config.z_score_threshold:
                    severity = "high" if z >= 5 else ("medium" if z >= 4 else "low")
                    anomalies.append(Anomaly(
                        server_id=server_id,
                        metric=metric,
                        timestamp=p.get("ts", end),
                        value=val,
                        expected=baseline.mean,
                        z_score=round(z, 2),
                        severity=severity,
                        description=f"{metric} = {val:.1f} (기대값 {baseline.mean:.1f}, z={z:.1f})",
                    ))
        return anomalies

    def detect_all_servers(self, server_ids: list[str] | None = None) -> dict[str, list[Anomaly]]:
        if server_ids is None:
            server_ids = self._ts.list_servers() if hasattr(self._ts, "list_servers") else []
        result: dict[str, list[Anomaly]] = {}
        for sid in server_ids:
            anomalies = self.detect(sid)
            if anomalies:
                result[sid] = anomalies
        return result

    async def analyze_with_llm(self, anomalies: list[Anomaly], provider: Any = None) -> str:
        if not anomalies:
            return "이상 징후가 없습니다."
        if not provider:
            return self._format_summary(anomalies)

        prompt = "다음 서버 메트릭 이상 징후를 분석하고 원인과 권고 사항을 한국어로 작성해주세요:\n\n"
        for a in anomalies[:20]:
            prompt += f"- [{a.server_id}] {a.metric}: {a.value:.1f} (기대값: {a.expected:.1f}, z-score: {a.z_score}, 심각도: {a.severity})\n"

        try:
            resp = await provider.complete(
                messages=[{"role": "user", "content": prompt}],
                model=None,
            )
            return resp.get("content", self._format_summary(anomalies))
        except Exception:
            log.warning("LLM anomaly analysis failed", exc_info=True)
            return self._format_summary(anomalies)

    def _format_summary(self, anomalies: list[Anomaly]) -> str:
        lines = [f"## 이상 탐지 요약 ({len(anomalies)}건)\n"]
        for a in anomalies:
            lines.append(f"- **[{a.server_id}] {a.metric}**: {a.value:.1f} (기대값 {a.expected:.1f}, z={a.z_score}, {a.severity})")
        return "\n".join(lines)
