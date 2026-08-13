"""GCP cloud connector — Compute Engine instances and GKE clusters.

Uses google-cloud-compute SDK if available, falls back to REST API via httpx
with service account credentials.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ...secrets import SecretStore
from ..tools._helpers import _attach, _schema

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core API functions
# ---------------------------------------------------------------------------


def gcp_list_instances(
    credentials: dict[str, Any],
    project: str,
    zone: str = "",
) -> dict[str, Any]:
    """GCE 인스턴스 목록."""
    try:
        from google.cloud import compute_v1  # type: ignore[import-untyped]

        client = compute_v1.InstancesClient(credentials=_build_gcp_creds(credentials))
        result: list[dict[str, Any]] = []
        if zone:
            for inst in client.list(project=project, zone=zone):
                result.append({
                    "name": inst.name,
                    "zone": zone,
                    "status": inst.status,
                    "machine_type": inst.machine_type.rsplit("/", 1)[-1] if inst.machine_type else "",
                })
        else:
            for zone_name, scope in client.aggregated_list(project=project):
                for inst in scope.instances or []:
                    result.append({
                        "name": inst.name,
                        "zone": zone_name.removeprefix("zones/"),
                        "status": inst.status,
                        "machine_type": (
                            inst.machine_type.rsplit("/", 1)[-1] if inst.machine_type else ""
                        ),
                    })
        return {"ok": True, "count": len(result), "instances": result}
    except ImportError:
        return _gcp_rest_instances(credentials, project, zone)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def gcp_list_gke_clusters(
    credentials: dict[str, Any],
    project: str,
    location: str = "-",
) -> dict[str, Any]:
    """GKE 클러스터 목록."""
    try:
        from google.cloud import container_v1  # type: ignore[import-untyped]

        client = container_v1.ClusterManagerClient(
            credentials=_build_gcp_creds(credentials),
        )
        parent = f"projects/{project}/locations/{location}"
        resp = client.list_clusters(parent=parent)
        clusters: list[dict[str, Any]] = []
        for c in resp.clusters:
            clusters.append({
                "name": c.name,
                "location": c.location,
                "status": c.status.name,
                "node_count": c.current_node_count,
                "version": c.current_master_version,
                "endpoint": c.endpoint,
            })
        return {"ok": True, "count": len(clusters), "clusters": clusters}
    except ImportError:
        return _gcp_rest_gke(credentials, project, location)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_gcp_creds(credentials: dict[str, Any]) -> Any:
    """서비스 계정 JSON에서 credentials 생성."""
    from google.oauth2 import service_account  # type: ignore[import-untyped]

    if "private_key" in credentials:
        return service_account.Credentials.from_service_account_info(credentials)
    return None  # ADC fallback


def _gcp_rest_instances(
    credentials: dict[str, Any],
    project: str,
    zone: str,
) -> dict[str, Any]:
    """SDK 없을 때 REST API fallback."""
    try:
        import httpx  # type: ignore[import-untyped]

        token = _gcp_access_token(credentials)
        if not token:
            return {
                "ok": False,
                "error": (
                    "google-cloud-compute not installed and no access token available. "
                    "Install: pip install google-cloud-compute"
                ),
            }
        headers = {"Authorization": f"Bearer {token}"}
        base = "https://compute.googleapis.com/compute/v1"
        if zone:
            url = f"{base}/projects/{project}/zones/{zone}/instances"
        else:
            url = f"{base}/projects/{project}/aggregated/instances"
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result: list[dict[str, Any]] = []
        if zone:
            for item in data.get("items", []):
                result.append({
                    "name": item.get("name", ""),
                    "zone": zone,
                    "status": item.get("status", ""),
                    "machine_type": item.get("machineType", "").rsplit("/", 1)[-1],
                })
        else:
            for z_scope in data.get("items", {}).values():
                for item in z_scope.get("instances", []):
                    result.append({
                        "name": item.get("name", ""),
                        "zone": item.get("zone", "").rsplit("/", 1)[-1],
                        "status": item.get("status", ""),
                        "machine_type": item.get("machineType", "").rsplit("/", 1)[-1],
                    })
        return {"ok": True, "count": len(result), "instances": result}
    except ImportError:
        return {
            "ok": False,
            "error": (
                "google-cloud-compute not installed. "
                "Install: pip install google-cloud-compute"
            ),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _gcp_rest_gke(
    credentials: dict[str, Any],
    project: str,
    location: str,
) -> dict[str, Any]:
    """SDK 없을 때 GKE REST API fallback."""
    try:
        import httpx  # type: ignore[import-untyped]

        token = _gcp_access_token(credentials)
        if not token:
            return {
                "ok": False,
                "error": (
                    "google-cloud-container not installed and no access token available. "
                    "Install: pip install google-cloud-container"
                ),
            }
        headers = {"Authorization": f"Bearer {token}"}
        url = (
            f"https://container.googleapis.com/v1"
            f"/projects/{project}/locations/{location}/clusters"
        )
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        clusters: list[dict[str, Any]] = []
        for c in data.get("clusters", []):
            clusters.append({
                "name": c.get("name", ""),
                "location": c.get("location", ""),
                "status": c.get("status", ""),
                "node_count": c.get("currentNodeCount", 0),
                "version": c.get("currentMasterVersion", ""),
                "endpoint": c.get("endpoint", ""),
            })
        return {"ok": True, "count": len(clusters), "clusters": clusters}
    except ImportError:
        return {
            "ok": False,
            "error": (
                "google-cloud-container not installed. "
                "Install: pip install google-cloud-container"
            ),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _gcp_access_token(credentials: dict[str, Any]) -> str | None:
    """서비스 계정 JSON으로부터 OAuth2 access token 획득 (httpx fallback용)."""
    try:
        import time

        import jwt  # type: ignore[import-untyped]

        import httpx  # type: ignore[import-untyped]

        now = int(time.time())
        payload = {
            "iss": credentials.get("client_email", ""),
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600,
        }
        private_key = credentials.get("private_key", "")
        if not private_key:
            return None
        encoded = jwt.encode(payload, private_key, algorithm="RS256")
        resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": encoded,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tool registration (register pattern)
# ---------------------------------------------------------------------------


def register(
    secrets: SecretStore,
    tools: list[Callable[..., Any]],
    *,
    roots: Any = None,
) -> None:
    """GCP 도구 등록 — cloud_infra_tools 또는 connector 시스템에서 호출."""
    creds = secrets.get("cloud:provider:gcp") or secrets.get("gcp:default")
    if not creds or not isinstance(creds, dict):
        return  # 자격증명 미설정 → 도구 없음

    project = creds.get("project_id", creds.get("project", ""))
    if not project:
        return

    # -- gcp_list_instances ------------------------------------------------
    def gcp_compute_list(zone: str = "") -> dict[str, Any]:
        """List GCE instances. Omit zone to list all zones."""
        return gcp_list_instances(creds, project, zone)

    gcp_compute_list.__name__ = "gcp_list_instances"
    tools.append(
        _attach(
            gcp_compute_list,
            _schema(
                "gcp_list_instances",
                "List Google Compute Engine instances. "
                "Omit zone to list across all zones.",
                {
                    "zone": {
                        "type": "string",
                        "description": "GCE zone (e.g. us-central1-a). "
                        "Empty string for all zones.",
                    },
                },
                [],
            ),
            caps=["gcp", "read"],
        )
    )

    # -- gcp_list_gke_clusters ---------------------------------------------
    def gcp_gke_clusters(location: str = "-") -> dict[str, Any]:
        """List GKE clusters. Use '-' for all locations."""
        return gcp_list_gke_clusters(creds, project, location)

    gcp_gke_clusters.__name__ = "gcp_list_gke_clusters"
    tools.append(
        _attach(
            gcp_gke_clusters,
            _schema(
                "gcp_list_gke_clusters",
                "List Google Kubernetes Engine clusters. "
                "Use '-' for all locations.",
                {
                    "location": {
                        "type": "string",
                        "description": "GKE location (e.g. us-central1). "
                        "Use '-' for all locations.",
                    },
                },
                [],
            ),
            caps=["gcp", "read"],
        )
    )
