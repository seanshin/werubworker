"""Cloud provider management -- configuration and basic status checks."""
from __future__ import annotations

from typing import Any

PREFIX = "cloud:provider:"


def list_providers(secrets: Any) -> list[dict]:
    """List configured cloud providers."""
    providers: list[dict] = []
    if secrets is None:
        return providers
    for entry in secrets.status():
        key = entry["profile"]
        if not key.startswith(PREFIX):
            continue
        name = key[len(PREFIX):]
        data = secrets.get(key) or {}
        providers.append({
            "name": name,
            "provider": data.get("provider", name),
            "configured": True,
            "region": data.get("region", ""),
        })
    return providers


def add_provider(
    secrets: Any,
    name: str,
    provider: str,
    api_key: str,
    api_secret: str = "",
    region: str = "",
) -> dict:
    if not name.strip() or not api_key.strip():
        return {"ok": False, "error": "name and api_key are required"}
    key = PREFIX + name.strip()
    secrets.put(key, {
        "provider": provider.strip(),
        "api_key": api_key.strip(),
        "api_secret": api_secret.strip(),
        "region": region.strip(),
    })
    return {"ok": True, "name": name}


def remove_provider(secrets: Any, name: str) -> dict:
    key = PREFIX + name.strip()
    if secrets.delete(key):
        return {"ok": True, "removed": name}
    return {"ok": False, "error": f"provider '{name}' not found"}


async def test_provider(secrets: Any, name: str) -> dict:
    """Basic connectivity test."""
    data = secrets.get(PREFIX + name.strip())
    if not data:
        return {"ok": False, "error": "not configured"}
    provider = data.get("provider", "").lower()
    if provider == "aws":
        # Test with STS GetCallerIdentity
        try:
            import boto3  # type: ignore[import-untyped]

            sts = boto3.client(
                "sts",
                aws_access_key_id=data["api_key"],
                aws_secret_access_key=data.get("api_secret", ""),
                region_name=data.get("region", "us-east-1"),
            )
            identity = sts.get_caller_identity()
            return {
                "ok": True,
                "account": identity.get("Account", ""),
                "arn": identity.get("Arn", ""),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
    # For other providers, just confirm key exists
    return {"ok": True, "status": "key stored (connectivity test not implemented)"}
