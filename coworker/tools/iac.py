"""Infrastructure as Code tools — Terraform and Ansible management.

Wraps the ``terraform`` and ``ansible`` CLI tools via subprocess.
All commands run with captured output and configurable timeouts.

Tools that mutate state (``terraform_plan``, ``ansible_playbook`` with
``check=False``) require approval; the rest are read-only.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable

import aisuite as ai


# ---------------------------------------------------------------------------
# Terraform helpers
# ---------------------------------------------------------------------------


def _terraform_plan(path: str, workspace: str = "default") -> dict[str, Any]:
    """Run ``terraform plan`` and return the planned changes."""
    if not path:
        return {"ok": False, "error": "path is required"}
    try:
        # Select workspace first
        if workspace != "default":
            ws_cmd = ["terraform", f"-chdir={path}", "workspace", "select", workspace]
            ws_result = subprocess.run(
                ws_cmd, capture_output=True, text=True, timeout=30
            )
            if ws_result.returncode != 0:
                return {
                    "ok": False,
                    "error": f"workspace select failed: {ws_result.stderr.strip()}",
                }

        cmd = ["terraform", f"-chdir={path}", "plan", "-no-color"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr.strip() if result.stderr else "",
            "workspace": workspace,
            "path": path,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "terraform plan timed out after 120s"}
    except FileNotFoundError:
        return {"ok": False, "error": "terraform command not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _terraform_state(path: str) -> dict[str, Any]:
    """Show current Terraform state."""
    if not path:
        return {"ok": False, "error": "path is required"}
    try:
        cmd = ["terraform", f"-chdir={path}", "state", "list"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}
        resources = [r for r in result.stdout.strip().split("\n") if r]
        return {"ok": True, "path": path, "resources": resources, "count": len(resources)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "terraform state timed out after 30s"}
    except FileNotFoundError:
        return {"ok": False, "error": "terraform command not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _terraform_output(path: str) -> dict[str, Any]:
    """Get Terraform output variables."""
    if not path:
        return {"ok": False, "error": "path is required"}
    try:
        cmd = ["terraform", f"-chdir={path}", "output", "-json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}
        outputs = json.loads(result.stdout) if result.stdout.strip() else {}
        return {"ok": True, "path": path, "outputs": outputs}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "terraform output timed out after 30s"}
    except FileNotFoundError:
        return {"ok": False, "error": "terraform command not found"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "failed to parse terraform output JSON"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Ansible helpers
# ---------------------------------------------------------------------------


def _ansible_inventory(path: str) -> dict[str, Any]:
    """Show Ansible inventory."""
    if not path:
        return {"ok": False, "error": "path is required"}
    try:
        cmd = ["ansible-inventory", "-i", path, "--list"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}
        inventory = json.loads(result.stdout) if result.stdout.strip() else {}
        return {"ok": True, "path": path, "inventory": inventory}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ansible-inventory timed out after 30s"}
    except FileNotFoundError:
        return {"ok": False, "error": "ansible-inventory command not found"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "failed to parse inventory JSON"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _ansible_playbook(
    path: str,
    playbook: str,
    check: bool = True,
    extra_vars: str = "",
) -> dict[str, Any]:
    """Run an Ansible playbook. Default: check mode (dry-run)."""
    if not path:
        return {"ok": False, "error": "path (inventory) is required"}
    if not playbook:
        return {"ok": False, "error": "playbook is required"}
    try:
        cmd = ["ansible-playbook", "-i", path, playbook]
        if check:
            cmd.append("--check")
        if extra_vars:
            cmd.extend(["-e", extra_vars])
        cmd.append("--no-color")

        timeout = 300 if not check else 120
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr.strip() if result.stderr else "",
            "check_mode": check,
            "playbook": playbook,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ansible-playbook timed out after {timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "ansible-playbook command not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_TERRAFORM_PLAN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "terraform_plan",
        "description": (
            "Run terraform plan (dry-run) and return the planned changes. "
            "Optionally select a workspace before planning."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to Terraform configuration directory.",
                },
                "workspace": {
                    "type": "string",
                    "description": "Terraform workspace to select (default: 'default').",
                },
            },
            "required": ["path"],
        },
    },
}

_TERRAFORM_STATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "terraform_state",
        "description": "Show the current Terraform state — list all managed resources.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to Terraform configuration directory.",
                },
            },
            "required": ["path"],
        },
    },
}

_TERRAFORM_OUTPUT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "terraform_output",
        "description": "Get Terraform output variables as JSON.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to Terraform configuration directory.",
                },
            },
            "required": ["path"],
        },
    },
}

_ANSIBLE_INVENTORY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ansible_inventory",
        "description": "Show Ansible inventory — list all hosts and groups.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to Ansible inventory file or directory.",
                },
            },
            "required": ["path"],
        },
    },
}

_ANSIBLE_PLAYBOOK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ansible_playbook",
        "description": (
            "Run an Ansible playbook. Runs in check mode (dry-run) by default. "
            "Set check=false to execute for real (requires approval)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to Ansible inventory file or directory.",
                },
                "playbook": {
                    "type": "string",
                    "description": "Path to the Ansible playbook YAML file.",
                },
                "check": {
                    "type": "boolean",
                    "description": "Run in check mode / dry-run (default: true).",
                },
                "extra_vars": {
                    "type": "string",
                    "description": "Extra variables as key=value or JSON string.",
                },
            },
            "required": ["path", "playbook"],
        },
    },
}


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def iac_tools(context: Any = None) -> list:
    """Return Infrastructure as Code tools for Terraform and Ansible."""
    tools: list[Callable[..., Any]] = []

    def terraform_plan(path: str, workspace: str = "default") -> dict:
        """Run terraform plan and return the planned changes."""
        return _terraform_plan(path, workspace)

    def terraform_state(path: str) -> dict:
        """Show current Terraform state."""
        return _terraform_state(path)

    def terraform_output(path: str) -> dict:
        """Get Terraform output variables."""
        return _terraform_output(path)

    def ansible_inventory(path: str) -> dict:
        """Show Ansible inventory."""
        return _ansible_inventory(path)

    def ansible_playbook(
        path: str, playbook: str, check: bool = True, extra_vars: str = ""
    ) -> dict:
        """Run an Ansible playbook. Default: check mode (dry-run)."""
        return _ansible_playbook(path, playbook, check, extra_vars)

    # Metadata
    _read_meta = ai.ToolMetadata(
        category="iac",
        risk_level="low",
        capabilities=["iac"],
        requires_approval=False,
    )
    _write_meta = ai.ToolMetadata(
        category="iac",
        risk_level="medium",
        capabilities=["iac"],
        requires_approval=True,
    )

    for fn, schema, meta in [
        (terraform_plan, _TERRAFORM_PLAN_SCHEMA, _write_meta),
        (terraform_state, _TERRAFORM_STATE_SCHEMA, _read_meta),
        (terraform_output, _TERRAFORM_OUTPUT_SCHEMA, _read_meta),
        (ansible_inventory, _ANSIBLE_INVENTORY_SCHEMA, _read_meta),
        (ansible_playbook, _ANSIBLE_PLAYBOOK_SCHEMA, _write_meta),
    ]:
        wrapped = ai.tool(fn, metadata=meta)
        wrapped.__coworker_schema__ = schema
        wrapped.__aisuite_tool_metadata__ = meta
        tools.append(wrapped)

    return tools
