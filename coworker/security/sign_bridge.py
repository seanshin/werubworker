"""Sign REST API bridge for audit log anchoring.

Submits hash chain head values to the WeruB Sign service
for cryptographic timestamping (RFC 3161) and tamper-evidence.
Sign service failure never blocks local audit log recording.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_BASE = "http://127.0.0.1:4100/v1"
_TIMEOUT = 10.0


@dataclass
class AnchorResult:
    ok: bool
    anchor_id: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class SignBridge:
    """Async Sign REST API client for audit anchoring."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self._base = (
            base_url or os.getenv("SIGN_API_URL") or _DEFAULT_BASE
        ).rstrip("/")
        self._api_key = api_key or os.getenv("SIGN_API_KEY") or ""

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["x-api-key"] = self._api_key
        return h

    async def submit_anchor(
        self,
        chain_head_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> AnchorResult:
        """Submit chain head hash to Sign for TSA anchoring.

        POST /v1/audit-events
        """
        import httpx

        payload: dict[str, Any] = {"hash": chain_head_hash}
        if metadata:
            payload["metadata"] = metadata
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._base}/audit-events",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return AnchorResult(
                    ok=True,
                    anchor_id=str(data.get("id", data.get("anchor_id", ""))),
                    raw=data,
                )
        except httpx.HTTPStatusError as exc:
            log.warning("Sign anchor HTTP %s: %s", exc.response.status_code, exc)
            return AnchorResult(ok=False, error=f"HTTP {exc.response.status_code}")
        except Exception as exc:
            log.warning("Sign anchor failed: %s", exc)
            return AnchorResult(ok=False, error=str(exc))

    async def verify_anchor(self, anchor_id: str) -> dict[str, Any]:
        """Verify an anchor by ID.

        GET /v1/audit-events/<anchor_id>
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{self._base}/audit-events/{anchor_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return {"ok": True, **data}
        except httpx.HTTPStatusError as exc:
            return {"ok": False, "error": f"HTTP {exc.response.status_code}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def list_anchors(self, limit: int = 20) -> dict[str, Any]:
        """List recent anchors.

        GET /v1/audit-events?limit=N
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{self._base}/audit-events",
                    params={"limit": limit},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return {"ok": True, "anchors": resp.json()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
