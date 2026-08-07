"""Kubernetes management tools — pods, logs, describe, restart, scale, events.

Uses ``kubectl`` CLI via ``subprocess``. Read-only tools (pods, logs, describe, events)
don't require approval; write tools (restart, scale) do.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import aisuite as ai


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kubectl_available() -> bool:
    """Check if kubectl is on PATH."""
    return shutil.which("kubectl") is not None


def _run_kubectl(args: list[str], timeout: int = 30) -> tuple[str, str, int]:
    """Run a kubectl command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "kubectl not found on PATH", 1
    except subprocess.TimeoutExpired:
        return "", "kubectl command timed out", 1
    except Exception as e:
        return "", str(e), 1


def _parse_json_or_text(stdout: str) -> Any:
    """Try to parse JSON output; fall back to raw text."""
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return stdout


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _k8s_pods(namespace: str = "default", label: str = "") -> dict[str, Any]:
    """List pods with status, restarts, age. Optional label selector filter."""
    if not _kubectl_available():
        return {"error": "kubectl is not installed or not on PATH"}

    cmd = ["get", "pods", "-n", namespace, "-o", "json"]
    if label:
        cmd += ["-l", label]

    stdout, stderr, rc = _run_kubectl(cmd)
    if rc != 0:
        return {"error": stderr or "kubectl command failed"}

    data = _parse_json_or_text(stdout)
    if isinstance(data, str):
        return {"namespace": namespace, "output": data}

    pods = []
    for item in data.get("items", []):
        meta = item.get("metadata", {})
        status = item.get("status", {})
        container_statuses = status.get("containerStatuses", [])
        restarts = sum(cs.get("restartCount", 0) for cs in container_statuses)
        pods.append({
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "phase": status.get("phase"),
            "restarts": restarts,
            "creation": meta.get("creationTimestamp"),
            "containers": [cs.get("name") for cs in container_statuses],
            "ready": all(cs.get("ready", False) for cs in container_statuses) if container_statuses else False,
        })
    return {"namespace": namespace, "count": len(pods), "pods": pods}


def _k8s_logs(pod: str, namespace: str = "default", container: str = "", lines: int = 50) -> dict[str, Any]:
    """View pod logs. Optionally specify container for multi-container pods."""
    if not _kubectl_available():
        return {"error": "kubectl is not installed or not on PATH"}
    if not pod:
        return {"error": "pod name is required"}

    n = min(max(1, lines), 1000)
    cmd = ["logs", pod, "-n", namespace, "--tail", str(n)]
    if container:
        cmd += ["-c", container]

    stdout, stderr, rc = _run_kubectl(cmd, timeout=15)
    if rc != 0:
        return {"error": stderr or "kubectl command failed"}

    return {
        "pod": pod,
        "namespace": namespace,
        "container": container or "(default)",
        "lines": n,
        "output": stdout[:20000],
    }


def _k8s_describe(resource_type: str, name: str, namespace: str = "default") -> dict[str, Any]:
    """Describe a Kubernetes resource (pod, deployment, service, etc.)."""
    if not _kubectl_available():
        return {"error": "kubectl is not installed or not on PATH"}
    if not resource_type or not name:
        return {"error": "resource_type and name are required"}

    cmd = ["describe", resource_type, name, "-n", namespace]
    stdout, stderr, rc = _run_kubectl(cmd, timeout=15)
    if rc != 0:
        return {"error": stderr or "kubectl command failed"}

    return {
        "resource_type": resource_type,
        "name": name,
        "namespace": namespace,
        "output": stdout[:20000],
    }


def _k8s_restart(deployment: str, namespace: str = "default") -> dict[str, Any]:
    """Rolling restart a deployment."""
    if not _kubectl_available():
        return {"error": "kubectl is not installed or not on PATH"}
    if not deployment:
        return {"error": "deployment name is required"}

    cmd = ["rollout", "restart", f"deployment/{deployment}", "-n", namespace]
    stdout, stderr, rc = _run_kubectl(cmd)
    if rc != 0:
        return {"error": stderr or "kubectl command failed"}

    return {
        "deployment": deployment,
        "namespace": namespace,
        "status": "restart initiated",
        "output": stdout,
    }


def _k8s_scale(deployment: str, replicas: int, namespace: str = "default") -> dict[str, Any]:
    """Scale a deployment to a given number of replicas."""
    if not _kubectl_available():
        return {"error": "kubectl is not installed or not on PATH"}
    if not deployment:
        return {"error": "deployment name is required"}
    if replicas < 0:
        return {"error": "replicas must be non-negative"}

    cmd = ["scale", f"deployment/{deployment}", f"--replicas={replicas}", "-n", namespace]
    stdout, stderr, rc = _run_kubectl(cmd)
    if rc != 0:
        return {"error": stderr or "kubectl command failed"}

    return {
        "deployment": deployment,
        "namespace": namespace,
        "replicas": replicas,
        "status": "scaled",
        "output": stdout,
    }


def _k8s_events(namespace: str = "default", type: str = "Warning") -> dict[str, Any]:
    """List recent cluster events, filtered by type."""
    if not _kubectl_available():
        return {"error": "kubectl is not installed or not on PATH"}

    cmd = ["get", "events", "-n", namespace, "-o", "json", "--sort-by=.lastTimestamp"]
    if type:
        cmd += ["--field-selector", f"type={type}"]

    stdout, stderr, rc = _run_kubectl(cmd)
    if rc != 0:
        return {"error": stderr or "kubectl command failed"}

    data = _parse_json_or_text(stdout)
    if isinstance(data, str):
        return {"namespace": namespace, "output": data}

    events = []
    for item in data.get("items", []):
        events.append({
            "type": item.get("type"),
            "reason": item.get("reason"),
            "message": item.get("message"),
            "object": f"{item.get('involvedObject', {}).get('kind', '')}/{item.get('involvedObject', {}).get('name', '')}",
            "count": item.get("count"),
            "last_seen": item.get("lastTimestamp"),
        })
    return {"namespace": namespace, "type": type, "count": len(events), "events": events[-100:]}


# ---------------------------------------------------------------------------
# Schema definitions (aisuite tool format)
# ---------------------------------------------------------------------------

_K8S_PODS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "k8s_pods",
        "description": (
            "List Kubernetes pods with status, restarts, and age. "
            "Optionally filter by namespace and label selector. Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace (default: 'default').",
                },
                "label": {
                    "type": "string",
                    "description": "Label selector to filter pods (e.g. 'app=nginx').",
                },
            },
        },
    },
}

_K8S_LOGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "k8s_logs",
        "description": (
            "View logs for a Kubernetes pod. Optionally specify a container "
            "for multi-container pods. Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pod": {
                    "type": "string",
                    "description": "Pod name.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace (default: 'default').",
                },
                "container": {
                    "type": "string",
                    "description": "Container name (for multi-container pods).",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to return (default 50, max 1000).",
                },
            },
            "required": ["pod"],
        },
    },
}

_K8S_DESCRIBE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "k8s_describe",
        "description": (
            "Describe a Kubernetes resource (pod, deployment, service, etc.). "
            "Returns detailed information including events. Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "resource_type": {
                    "type": "string",
                    "description": "Resource type (e.g. 'pod', 'deployment', 'service', 'node').",
                },
                "name": {
                    "type": "string",
                    "description": "Resource name.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace (default: 'default').",
                },
            },
            "required": ["resource_type", "name"],
        },
    },
}

_K8S_RESTART_SCHEMA = {
    "type": "function",
    "function": {
        "name": "k8s_restart",
        "description": (
            "Rolling restart a Kubernetes deployment. This is a write operation "
            "that triggers a new rollout."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deployment": {
                    "type": "string",
                    "description": "Deployment name to restart.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace (default: 'default').",
                },
            },
            "required": ["deployment"],
        },
    },
}

_K8S_SCALE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "k8s_scale",
        "description": (
            "Scale a Kubernetes deployment to a specified number of replicas. "
            "This is a write operation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deployment": {
                    "type": "string",
                    "description": "Deployment name to scale.",
                },
                "replicas": {
                    "type": "integer",
                    "description": "Desired number of replicas.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace (default: 'default').",
                },
            },
            "required": ["deployment", "replicas"],
        },
    },
}

_K8S_EVENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "k8s_events",
        "description": (
            "List recent Kubernetes cluster events, filtered by type. "
            "Useful for spotting warnings and errors. Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Kubernetes namespace (default: 'default').",
                },
                "type": {
                    "type": "string",
                    "description": "Event type filter: 'Warning', 'Normal', or '' for all (default: 'Warning').",
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Public factory — called by catalog.py
# ---------------------------------------------------------------------------

def k8s_tools(context: Any = None) -> list:
    """Return Kubernetes management tools. Uses kubectl CLI via subprocess.

    Read tools (k8s_pods, k8s_logs, k8s_describe, k8s_events) — no approval.
    Write tools (k8s_restart, k8s_scale) — require approval.
    """

    def k8s_pods(namespace: str = "default", label: str = "") -> dict:
        """List pods with status, restarts, age. Optional label selector filter."""
        return _k8s_pods(namespace, label)

    def k8s_logs(pod: str, namespace: str = "default", container: str = "", lines: int = 50) -> dict:
        """View pod logs. Optionally specify container for multi-container pods."""
        return _k8s_logs(pod, namespace, container, lines)

    def k8s_describe(resource_type: str, name: str, namespace: str = "default") -> dict:
        """Describe a Kubernetes resource (pod, deployment, service, etc.)."""
        return _k8s_describe(resource_type, name, namespace)

    def k8s_restart(deployment: str, namespace: str = "default") -> dict:
        """Rolling restart a deployment (requires approval)."""
        return _k8s_restart(deployment, namespace)

    def k8s_scale(deployment: str, replicas: int, namespace: str = "default") -> dict:
        """Scale a deployment (requires approval)."""
        return _k8s_scale(deployment, replicas, namespace)

    def k8s_events(namespace: str = "default", type: str = "Warning") -> dict:
        """List recent cluster events, filtered by type."""
        return _k8s_events(namespace, type)

    _read_meta = ai.ToolMetadata(
        category="k8s",
        risk_level="low",
        capabilities=["monitor"],
        requires_approval=False,
    )
    _write_meta = ai.ToolMetadata(
        category="k8s",
        risk_level="high",
        capabilities=["manage"],
        requires_approval=True,
    )

    tools = []
    for fn, schema, meta in [
        (k8s_pods, _K8S_PODS_SCHEMA, _read_meta),
        (k8s_logs, _K8S_LOGS_SCHEMA, _read_meta),
        (k8s_describe, _K8S_DESCRIBE_SCHEMA, _read_meta),
        (k8s_restart, _K8S_RESTART_SCHEMA, _write_meta),
        (k8s_scale, _K8S_SCALE_SCHEMA, _write_meta),
        (k8s_events, _K8S_EVENTS_SCHEMA, _read_meta),
    ]:
        wrapped = ai.tool(fn, metadata=meta)
        wrapped.__coworker_schema__ = schema
        tools.append(wrapped)

    return tools
