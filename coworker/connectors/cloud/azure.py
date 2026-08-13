"""Azure cloud connector — Virtual Machines and AKS clusters.

Uses azure-mgmt-compute SDK if available, falls back to httpx REST API.
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


def azure_list_vms(
    credentials: dict[str, Any],
    subscription_id: str,
    resource_group: str = "",
) -> dict[str, Any]:
    """Azure VM 목록."""
    try:
        from azure.identity import ClientSecretCredential  # type: ignore[import-untyped]
        from azure.mgmt.compute import ComputeManagementClient  # type: ignore[import-untyped]

        cred = ClientSecretCredential(
            tenant_id=credentials.get("tenant_id"),
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
        )
        client = ComputeManagementClient(cred, subscription_id)
        if resource_group:
            vms = client.virtual_machines.list(resource_group)
        else:
            vms = client.virtual_machines.list_all()
        result: list[dict[str, Any]] = []
        for vm in vms:
            result.append({
                "name": vm.name,
                "location": vm.location,
                "vm_size": (
                    vm.hardware_profile.vm_size if vm.hardware_profile else ""
                ),
                "os": (
                    vm.storage_profile.os_disk.os_type
                    if vm.storage_profile and vm.storage_profile.os_disk
                    else ""
                ),
                "provisioning_state": vm.provisioning_state,
                "resource_group": vm.id.split("/")[4] if vm.id else "",
            })
        return {"ok": True, "count": len(result), "vms": result}
    except ImportError:
        return _azure_rest_vms(credentials, subscription_id, resource_group)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def azure_list_aks(
    credentials: dict[str, Any],
    subscription_id: str,
    resource_group: str = "",
) -> dict[str, Any]:
    """AKS 클러스터 목록."""
    try:
        from azure.identity import ClientSecretCredential  # type: ignore[import-untyped]
        from azure.mgmt.containerservice import (  # type: ignore[import-untyped]
            ContainerServiceClient,
        )

        cred = ClientSecretCredential(
            tenant_id=credentials.get("tenant_id"),
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
        )
        client = ContainerServiceClient(cred, subscription_id)
        if resource_group:
            clusters = client.managed_clusters.list_by_resource_group(resource_group)
        else:
            clusters = client.managed_clusters.list()
        result: list[dict[str, Any]] = []
        for c in clusters:
            result.append({
                "name": c.name,
                "location": c.location,
                "kubernetes_version": c.kubernetes_version,
                "provisioning_state": c.provisioning_state,
                "node_count": sum(
                    p.count for p in (c.agent_pool_profiles or []) if p.count
                ),
                "fqdn": c.fqdn,
            })
        return {"ok": True, "count": len(result), "clusters": result}
    except ImportError:
        return _azure_rest_aks(credentials, subscription_id, resource_group)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Internal helpers — REST API fallback
# ---------------------------------------------------------------------------


def _azure_get_token(credentials: dict[str, Any]) -> str | None:
    """Client credentials flow로 Azure AD access token 획득."""
    try:
        import httpx  # type: ignore[import-untyped]

        tenant_id = credentials.get("tenant_id", "")
        resp = httpx.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": credentials.get("client_id", ""),
                "client_secret": credentials.get("client_secret", ""),
                "scope": "https://management.azure.com/.default",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception:
        return None


def _azure_rest_vms(
    credentials: dict[str, Any],
    subscription_id: str,
    resource_group: str,
) -> dict[str, Any]:
    """SDK 없을 때 Azure REST API fallback."""
    try:
        import httpx  # type: ignore[import-untyped]

        token = _azure_get_token(credentials)
        if not token:
            return {
                "ok": False,
                "error": (
                    "azure-mgmt-compute not installed and no access token available. "
                    "Install: pip install azure-mgmt-compute azure-identity"
                ),
            }
        headers = {"Authorization": f"Bearer {token}"}
        api_ver = "2024-03-01"
        base = "https://management.azure.com"
        if resource_group:
            url = (
                f"{base}/subscriptions/{subscription_id}"
                f"/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Compute/virtualMachines"
                f"?api-version={api_ver}"
            )
        else:
            url = (
                f"{base}/subscriptions/{subscription_id}"
                f"/providers/Microsoft.Compute/virtualMachines"
                f"?api-version={api_ver}"
            )
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result: list[dict[str, Any]] = []
        for item in data.get("value", []):
            props = item.get("properties", {})
            hw = props.get("hardwareProfile", {})
            storage = props.get("storageProfile", {})
            os_disk = storage.get("osDisk", {})
            rid = item.get("id", "")
            result.append({
                "name": item.get("name", ""),
                "location": item.get("location", ""),
                "vm_size": hw.get("vmSize", ""),
                "os": os_disk.get("osType", ""),
                "provisioning_state": props.get("provisioningState", ""),
                "resource_group": rid.split("/")[4] if len(rid.split("/")) > 4 else "",
            })
        return {"ok": True, "count": len(result), "vms": result}
    except ImportError:
        return {
            "ok": False,
            "error": (
                "azure-mgmt-compute not installed. "
                "Install: pip install azure-mgmt-compute azure-identity"
            ),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _azure_rest_aks(
    credentials: dict[str, Any],
    subscription_id: str,
    resource_group: str,
) -> dict[str, Any]:
    """SDK 없을 때 AKS REST API fallback."""
    try:
        import httpx  # type: ignore[import-untyped]

        token = _azure_get_token(credentials)
        if not token:
            return {
                "ok": False,
                "error": (
                    "azure-mgmt-containerservice not installed and "
                    "no access token available. "
                    "Install: pip install azure-mgmt-containerservice azure-identity"
                ),
            }
        headers = {"Authorization": f"Bearer {token}"}
        api_ver = "2024-01-01"
        base = "https://management.azure.com"
        if resource_group:
            url = (
                f"{base}/subscriptions/{subscription_id}"
                f"/resourceGroups/{resource_group}"
                f"/providers/Microsoft.ContainerService/managedClusters"
                f"?api-version={api_ver}"
            )
        else:
            url = (
                f"{base}/subscriptions/{subscription_id}"
                f"/providers/Microsoft.ContainerService/managedClusters"
                f"?api-version={api_ver}"
            )
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result: list[dict[str, Any]] = []
        for item in data.get("value", []):
            props = item.get("properties", {})
            pools = props.get("agentPoolProfiles", [])
            node_count = sum(p.get("count", 0) for p in pools)
            result.append({
                "name": item.get("name", ""),
                "location": item.get("location", ""),
                "kubernetes_version": props.get("kubernetesVersion", ""),
                "provisioning_state": props.get("provisioningState", ""),
                "node_count": node_count,
                "fqdn": props.get("fqdn", ""),
            })
        return {"ok": True, "count": len(result), "clusters": result}
    except ImportError:
        return {
            "ok": False,
            "error": (
                "azure-mgmt-containerservice not installed. "
                "Install: pip install azure-mgmt-containerservice azure-identity"
            ),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tool registration (register pattern)
# ---------------------------------------------------------------------------


def register(
    secrets: SecretStore,
    tools: list[Callable[..., Any]],
    *,
    roots: Any = None,
) -> None:
    """Azure 도구 등록 — cloud_infra_tools 또는 connector 시스템에서 호출."""
    creds = secrets.get("cloud:provider:azure") or secrets.get("azure:default")
    if not creds or not isinstance(creds, dict):
        return  # 자격증명 미설정 → 도구 없음

    subscription_id = creds.get("subscription_id", "")
    if not subscription_id:
        return

    # -- azure_list_vms ----------------------------------------------------
    def azure_vm_list(resource_group: str = "") -> dict[str, Any]:
        """List Azure Virtual Machines. Omit resource_group to list all."""
        return azure_list_vms(creds, subscription_id, resource_group)

    azure_vm_list.__name__ = "azure_list_vms"
    tools.append(
        _attach(
            azure_vm_list,
            _schema(
                "azure_list_vms",
                "List Azure Virtual Machines. "
                "Omit resource_group to list across all resource groups.",
                {
                    "resource_group": {
                        "type": "string",
                        "description": "Azure resource group name. "
                        "Empty string for all resource groups.",
                    },
                },
                [],
            ),
            caps=["azure", "read"],
        )
    )

    # -- azure_list_aks ----------------------------------------------------
    def azure_aks_clusters(resource_group: str = "") -> dict[str, Any]:
        """List AKS clusters. Omit resource_group to list all."""
        return azure_list_aks(creds, subscription_id, resource_group)

    azure_aks_clusters.__name__ = "azure_list_aks"
    tools.append(
        _attach(
            azure_aks_clusters,
            _schema(
                "azure_list_aks",
                "List Azure Kubernetes Service (AKS) clusters. "
                "Omit resource_group to list across all resource groups.",
                {
                    "resource_group": {
                        "type": "string",
                        "description": "Azure resource group name. "
                        "Empty string for all resource groups.",
                    },
                },
                [],
            ),
            caps=["azure", "read"],
        )
    )
