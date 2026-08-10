"""WeruBWorker Cloud client — DISABLED.

Cloud endpoints have been removed. All functions are stubs that return
safe defaults so existing callers (tools, connectors, server routes)
continue to work without changes. Manual token paste is the only
connection method.
"""

from __future__ import annotations

from typing import Any, Optional

from .secrets import SecretStore

CLOUD_AUTH_PROFILE = "cloud:auth"

# Telemetry profile key — kept so existing secret-store entries don't orphan.
TELEMETRY_PROFILE = "cloud:telemetry"


# --- status -------------------------------------------------------------------


def status(secrets: SecretStore) -> dict[str, Any]:
    """Always signed out — Cloud is not configured."""
    return {"signed_in": False, "account": "", "user_id": ""}


def logout(secrets: SecretStore) -> dict[str, Any]:
    secrets.delete(CLOUD_AUTH_PROFILE)
    return {"ok": True, "signed_in": False}


# --- telemetry (no-ops) -------------------------------------------------------


def telemetry_enabled(secrets: SecretStore) -> bool:
    return False


def set_telemetry_enabled(secrets: SecretStore, enabled: bool) -> dict[str, Any]:
    return {"ok": True, "telemetry_enabled": False}


def emit_session_created(
    secrets: SecretStore,
    config: Any,
    *,
    session_id: str = "",
    persona_id: str = "",
    persona_family: str = "",
    workspace_kind: str = "",
) -> bool:
    return False


# --- connector token refresh (no-op) ------------------------------------------


def ensure_fresh_connector_token(
    secrets: SecretStore,
    config: Any,
    connector: str,
    *,
    profile_key: Optional[str] = None,
    leeway: int = 120,
) -> None:
    """No-op — managed OAuth refresh through the cloud broker is disabled.
    Manual profiles never needed this; managed profiles can no longer refresh."""
    return


# --- managed connect stubs (all return errors) ---------------------------------


def begin_managed_connect(
    secrets: SecretStore,
    config: Any,
    connector: str,
    *,
    access: str = "",
    flow: str = "",
) -> dict[str, Any]:
    return {"ok": False, "error": "Cloud not configured"}


def consume_managed_state(state: str) -> bool:
    return False


def managed_profile_from_callback(form: dict[str, str]) -> dict[str, Any]:
    """Build a profile dict from callback form data. Kept because the
    /oauth/callback route still references it for any in-flight callbacks."""
    import time

    profile = {
        "type": "oauth",
        "enabled": True,
        "managed": True,
        "access_token": form.get("access_token", ""),
        "refresh_token": form.get("refresh_token", ""),
        "scope": form.get("scope", ""),
        "connection_id": form.get("connection_id", ""),
        "provider": form.get("provider", ""),
        "account": form.get("account", ""),
    }
    if form.get("account_id"):
        profile["account_id"] = form["account_id"]
    if form.get("expires_in"):
        profile["expires"] = time.time() + int(form["expires_in"]) - 60
    return profile


def refresh_managed_token(
    secrets: SecretStore,
    config: Any,
    connector: str,
    *,
    profile_key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return None


# --- cloud disconnect stubs ---------------------------------------------------


def cloud_disconnect(
    secrets: SecretStore,
    config: Any,
    connector: str,
    *,
    profile_key: Optional[str] = None,
) -> None:
    """No-op — cloud metadata update is disabled."""
    return


# --- sign-in stubs ------------------------------------------------------------


def begin_login(config: Any) -> dict[str, Any]:
    return {"ok": False, "error": "Cloud not configured", "authorize_url": ""}


def complete_login(secrets: SecretStore, config: Any, code: str, state: str) -> dict[str, Any]:
    return {"ok": False, "error": "Cloud not configured"}


def sync_connections(secrets: SecretStore, config: Any) -> dict[str, Any]:
    return {"ok": False, "error": "Cloud not configured"}


def fresh_access_token(secrets: SecretStore, config: Any) -> Optional[str]:
    return None


def fetch_me(secrets: SecretStore, config: Any) -> Optional[dict]:
    return None


# --- GitHub token stubs -------------------------------------------------------


def github_installation_token(
    secrets: SecretStore, config: Any, installation_id: str, *, force: bool = False
) -> str:
    return ""


def clear_github_token(installation_id: str) -> None:
    pass


def github_disconnect_installation(secrets: SecretStore, config: Any, installation_id: str) -> None:
    pass


# --- Slack disconnect stub ----------------------------------------------------


def slack_disconnect_workspace(secrets: SecretStore, config: Any, team_id: str) -> None:
    pass


# --- gallery stubs ------------------------------------------------------------


def gallery_list(secrets: SecretStore, config: Any) -> Optional[dict]:
    return None


def gallery_manifest(secrets: SecretStore, config: Any, slug: str) -> Optional[dict]:
    return None


def gallery_detail(secrets: SecretStore, config: Any, slug: str) -> Optional[dict]:
    return None


def gallery_install_event(secrets: SecretStore, config: Any, slug: str) -> None:
    pass
