"""Agent tools for the wiki & credentials system.

Follows the same ``ai.tool`` + ``__coworker_schema__`` + ``__aisuite_tool_metadata__``
pattern used by cloud_infra, db_mgmt, and other tool modules.
"""

from __future__ import annotations

from typing import Any, Callable

import aisuite as ai

# ---------------------------------------------------------------------------
# Schema helpers (same pattern as cloud_infra.py)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="wiki",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["wiki"],
        requires_approval=approval,
    )


def _schema(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _attach(
    fn: Callable[..., Any],
    schema: dict[str, Any],
    *,
    approval: bool = False,
    caps: list[str] | None = None,
) -> Callable[..., Any]:
    name = schema["function"]["name"]
    fn.__coworker_schema__ = schema
    fn.__aisuite_tool_metadata__ = _meta(name, approval=approval, capabilities=caps)
    fn.__doc__ = schema["function"]["description"]
    fn.__name__ = name
    return fn


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def wiki_tools(context: Any = None) -> list:
    """Return wiki & credential management tools."""
    # Lazy import to avoid circular dependency
    from .store import WikiStore
    from .vault import Vault

    # Resolve stores from context (SessionManager sets these on AgentContext)
    wiki_store: WikiStore | None = getattr(context, "wiki_store", None)
    vault: Vault | None = getattr(context, "vault", None)

    if wiki_store is None or vault is None:
        return []

    tools: list[Callable[..., Any]] = []

    # -- wiki_search -------------------------------------------------------
    def wiki_search(query: str = "", category: str = "") -> dict:
        pages = wiki_store.list_pages(category=category, query=query)
        return {"ok": True, "count": len(pages), "pages": pages}

    _attach(
        wiki_search,
        _schema(
            "wiki_search",
            "Search wiki for service information and documentation pages.",
            {
                "query": {"type": "string", "description": "Search query text"},
                "category": {
                    "type": "string",
                    "description": "Filter by category (e.g. 'infrastructure', 'api')",
                },
            },
            [],
        ),
    )
    tools.append(wiki_search)

    # -- wiki_get ----------------------------------------------------------
    def wiki_get(page_id: str) -> dict:
        page = wiki_store.get_page(page_id)
        if page is None:
            return {"ok": False, "error": f"page '{page_id}' not found"}
        return {"ok": True, "page": page}

    _attach(
        wiki_get,
        _schema(
            "wiki_get",
            "Get a wiki page by ID. Credential values are masked.",
            {
                "page_id": {"type": "string", "description": "Wiki page identifier"},
            },
            ["page_id"],
        ),
    )
    tools.append(wiki_get)

    # -- wiki_get_credential -----------------------------------------------
    def wiki_get_credential(page_id: str, key: str) -> dict:
        vault_key = f"{page_id}:{key}"
        try:
            value = vault.retrieve(vault_key)
            return {"ok": True, "key": key, "value": value}
        except KeyError:
            return {"ok": False, "error": f"credential '{key}' not found on page '{page_id}'"}
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    _attach(
        wiki_get_credential,
        _schema(
            "wiki_get_credential",
            "Get a specific credential value for service connection. "
            "Use only when actively connecting to a service.",
            {
                "page_id": {"type": "string", "description": "Wiki page identifier"},
                "key": {"type": "string", "description": "Credential key name"},
            },
            ["page_id", "key"],
        ),
        approval=True,
    )
    tools.append(wiki_get_credential)

    # -- wiki_update -------------------------------------------------------
    def wiki_update(page_id: str, content: str, change_note: str = "") -> dict:
        return wiki_store.update_page(
            page_id, content=content, change_note=change_note, updated_by="agent"
        )

    _attach(
        wiki_update,
        _schema(
            "wiki_update",
            "Update a wiki page's content. Requires approval.",
            {
                "page_id": {"type": "string", "description": "Wiki page identifier"},
                "content": {"type": "string", "description": "New page content (markdown)"},
                "change_note": {
                    "type": "string",
                    "description": "Brief note describing the change",
                },
            },
            ["page_id", "content"],
        ),
        approval=True,
    )
    tools.append(wiki_update)

    # -- wiki_check_alerts -------------------------------------------------
    def wiki_check_alerts() -> dict:
        alerts = wiki_store.list_alerts()
        expiring = vault.check_expiring(days=30)
        return {
            "ok": True,
            "alerts": alerts,
            "expiring_credentials": expiring,
        }

    _attach(
        wiki_check_alerts,
        _schema(
            "wiki_check_alerts",
            "Check for expiring credentials and rotation alerts.",
            {},
            [],
        ),
    )
    tools.append(wiki_check_alerts)

    # -- wiki_resolve_service -----------------------------------------------
    secrets = getattr(context, "secrets", None)

    def wiki_resolve_service(service_ref: str) -> dict:
        """Resolve a service reference to its configuration and wiki documentation."""
        from ..registry import ServiceRegistry
        reg = ServiceRegistry(wiki_store, secrets, vault)
        return reg.resolve(service_ref)

    _attach(
        wiki_resolve_service,
        _schema(
            "wiki_resolve_service",
            "Resolve a service reference (e.g. 'database:production', 'ssh:server:web-01') "
            "to its configuration and related wiki documentation.",
            {
                "service_ref": {
                    "type": "string",
                    "description": "Service reference string (e.g. 'database:production', 'ssh:server:web-01', 'cloud:aws')",
                },
            },
            ["service_ref"],
        ),
    )
    tools.append(wiki_resolve_service)

    def wiki_analyze(page_id: str = "", content: str = "") -> dict:
        """Analyze a wiki page or free-form text to extract service credentials.
        Provide either page_id (to analyze existing page) or content (to analyze new text).
        Returns extracted hosts, passwords, tokens, API keys with suggested service mapping."""
        from .analyzer import analyze_document

        if page_id:
            page = wiki_store.get_page(page_id)
            if page is None:
                return {"error": f"page '{page_id}' not found"}
            return analyze_document(page.get("content", ""), page.get("name", ""))
        if content:
            return analyze_document(content)
        return {"error": "provide page_id or content"}

    _attach(
        wiki_analyze,
        _schema(
            "wiki_analyze",
            "Analyze wiki page or text to extract service credentials (hosts, passwords, tokens, API keys). "
            "Returns extracted items with context for user confirmation.",
            {
                "page_id": {"type": "string", "description": "Wiki page ID to analyze (optional)"},
                "content": {
                    "type": "string",
                    "description": "Free-form text to analyze (optional)",
                },
            },
            [],
        ),
    )
    tools.append(wiki_analyze)

    # -- wiki_optimize_prompt (Step 33: A6) --------------------------------
    def wiki_optimize_prompt(page_id: str) -> dict:
        """Analyze prompt run history and suggest improvements."""
        page = wiki_store.get_page(page_id)
        if not page:
            return {"ok": False, "error": "page not found"}
        runs = wiki_store.get_prompt_runs(page_id, limit=50)
        if not runs:
            return {"ok": False, "error": "no run history to analyze"}
        total = len(runs)
        successes = sum(1 for r in runs if r.get("success"))
        avg_latency = sum(r.get("latency_ms", 0) for r in runs) / total if total else 0
        avg_tokens = (
            sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in runs) / total
            if total
            else 0
        )
        return {
            "ok": True,
            "page_id": page_id,
            "analysis": {
                "total_runs": total,
                "success_rate": round(successes / total * 100, 1) if total else 0,
                "avg_latency_ms": round(avg_latency),
                "avg_total_tokens": round(avg_tokens),
                "content": page.get("content", "")[:2000],
            },
            "suggestion": "Review the prompt content above and suggest improvements based on the run statistics.",
        }

    _attach(
        wiki_optimize_prompt,
        _schema(
            "wiki_optimize_prompt",
            "Analyze prompt run history and suggest improvements based on success rate, latency, and token usage.",
            {
                "page_id": {"type": "string", "description": "Wiki page ID of the prompt to optimize"},
            },
            ["page_id"],
        ),
        caps=["wiki", "prompt_library"],
    )
    tools.append(wiki_optimize_prompt)

    # -- wiki_get_model_comparison (Step 34: A7) ---------------------------
    def wiki_get_model_comparison(model_ids: str) -> dict:
        """Compare model cards by their page IDs (comma-separated)."""
        ids = [m.strip() for m in model_ids.split(",") if m.strip()]
        models = []
        for mid in ids[:4]:  # Max 4 models
            page = wiki_store.get_page(mid)
            if page:
                models.append({
                    "page_id": mid,
                    "name": page.get("name", ""),
                    "structured_data": page.get("structured_data", {}),
                })
        return {"ok": True, "models": models, "count": len(models)}

    _attach(
        wiki_get_model_comparison,
        _schema(
            "wiki_get_model_comparison",
            "Compare model cards by their page IDs (comma-separated). Returns structured data for up to 4 models.",
            {
                "model_ids": {
                    "type": "string",
                    "description": "Comma-separated page IDs of model cards to compare",
                },
            },
            ["model_ids"],
        ),
        caps=["wiki", "model_registry"],
    )
    tools.append(wiki_get_model_comparison)

    # -- wiki_test_prompt_with_model (Step 34: A7) -------------------------
    def wiki_test_prompt_with_model(page_id: str, model_id: str, variables: str = "{}") -> dict:
        """Test a prompt template with specific model and variables."""
        import json as _json
        import uuid as _uuid

        page = wiki_store.get_page(page_id)
        if not page:
            return {"ok": False, "error": "prompt page not found"}
        try:
            vars_dict = _json.loads(variables)
        except Exception:
            vars_dict = {}
        run_id = str(_uuid.uuid4())[:8]
        wiki_store.record_prompt_run(
            page_id=page_id, run_id=run_id, model_id=model_id,
            input_tokens=0, output_tokens=0, latency_ms=0,
            success=True, variables=vars_dict, output_preview="(agent test)",
            prompt_version=page.get("version", 1),
        )
        return {"ok": True, "run_id": run_id, "content": page.get("content", "")[:2000]}

    _attach(
        wiki_test_prompt_with_model,
        _schema(
            "wiki_test_prompt_with_model",
            "Test a prompt template with a specific model and variables. Records a run entry.",
            {
                "page_id": {"type": "string", "description": "Wiki page ID of the prompt template"},
                "model_id": {"type": "string", "description": "Model ID to test with"},
                "variables": {
                    "type": "string",
                    "description": "JSON string of variable key-value pairs (default '{}')",
                },
            },
            ["page_id", "model_id"],
        ),
        caps=["wiki", "prompt_library"],
    )
    tools.append(wiki_test_prompt_with_model)

    # -- wiki_create -------------------------------------------------------
    def wiki_create(
        name: str,
        category: str,
        content: str = "",
        linked_service: str = "",
        tags: str = "",
    ) -> dict:
        """Create a wiki page with optional template."""
        import uuid as _uuid  # noqa: F811

        page_id = f"{category}-{name.lower().replace(' ', '-')[:40]}"
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        # 템플릿 적용
        if not content:
            from .store import WIKI_TEMPLATES

            tmpl = WIKI_TEMPLATES.get(category)
            if tmpl:
                content = tmpl["content"]
                # 변수 치환
                for key in (
                    "name",
                    "service_name",
                    "server_name",
                    "db_name",
                    "project_name",
                ):
                    content = content.replace("{{" + key + "}}", name)

        return wiki_store.create_page(
            page_id=page_id,
            name=name,
            category=category,
            content=content,
            linked_service=linked_service,
            tags=tag_list,
            updated_by="agent",
        )

    _attach(
        wiki_create,
        _schema(
            "wiki_create",
            "Create a wiki page with optional category-based template.",
            {
                "name": {"type": "string", "description": "Page name / title"},
                "category": {
                    "type": "string",
                    "description": "Category (e.g. 'infrastructure', 'runbook', 'api')",
                },
                "content": {
                    "type": "string",
                    "description": "Page content (markdown). If empty, a template is applied.",
                },
                "linked_service": {
                    "type": "string",
                    "description": "Service reference to link (optional)",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags (optional)",
                },
            },
            ["name", "category"],
        ),
        approval=True,
    )
    tools.append(wiki_create)

    # -- wiki_delete -------------------------------------------------------
    def wiki_delete(page_id: str) -> dict:
        """Soft-delete a wiki page."""
        return wiki_store.delete_page(page_id)

    _attach(
        wiki_delete,
        _schema(
            "wiki_delete",
            "Soft-delete a wiki page.",
            {
                "page_id": {"type": "string", "description": "Wiki page identifier"},
            },
            ["page_id"],
        ),
        approval=True,
    )
    tools.append(wiki_delete)

    # -- wiki_history ------------------------------------------------------
    def wiki_history(page_id: str) -> dict:
        """Get version history for a wiki page."""
        history = wiki_store.get_history(page_id)
        return {"ok": True, "page_id": page_id, "count": len(history), "history": history}

    _attach(
        wiki_history,
        _schema(
            "wiki_history",
            "Get version history for a wiki page.",
            {
                "page_id": {"type": "string", "description": "Wiki page identifier"},
            },
            ["page_id"],
        ),
    )
    tools.append(wiki_history)

    # -- wiki_categories ---------------------------------------------------
    def wiki_categories() -> dict:
        """List wiki categories with page counts."""
        return {"ok": True, "categories": wiki_store.categories()}

    _attach(
        wiki_categories,
        _schema(
            "wiki_categories",
            "List wiki categories with page counts.",
            {},
            [],
        ),
    )
    tools.append(wiki_categories)

    # -- wiki_recent -------------------------------------------------------
    def wiki_recent(limit: int = 20) -> dict:
        """List recently modified wiki pages."""
        return {"ok": True, "pages": wiki_store.recent(limit)}

    _attach(
        wiki_recent,
        _schema(
            "wiki_recent",
            "List recently modified wiki pages.",
            {
                "limit": {
                    "type": "integer",
                    "description": "Max number of pages to return (default 20)",
                },
            },
            [],
        ),
    )
    tools.append(wiki_recent)

    # -- wiki_set_credential -----------------------------------------------
    def wiki_set_credential(
        page_id: str,
        key: str,
        value: str,
        credential_type: str = "password",
        expires_at: str = "",
    ) -> dict:
        """Store a credential in Vault and update Wiki metadata."""
        import time as _time

        vault.store(f"{page_id}:{key}", value)

        page = wiki_store.get_page(page_id)
        if page:
            creds = page.get("credentials", [])
            found = False
            for c in creds:
                if c.get("key") == key:
                    c["type"] = credential_type
                    c["updated_at"] = _time.time()
                    if expires_at:
                        c["expires_at"] = expires_at
                    found = True
                    break
            if not found:
                entry: dict[str, Any] = {
                    "key": key,
                    "type": credential_type,
                    "updated_at": _time.time(),
                }
                if expires_at:
                    entry["expires_at"] = expires_at
                creds.append(entry)
            wiki_store.update_page(
                page_id,
                credentials=creds,
                change_note=f"Credential '{key}' updated",
            )

        if expires_at:
            wiki_store.add_alert(page_id, key, "expiring", expires_at)

        return {"ok": True, "page_id": page_id, "key": key}

    _attach(
        wiki_set_credential,
        _schema(
            "wiki_set_credential",
            "Store a credential in Vault and update Wiki metadata.",
            {
                "page_id": {"type": "string", "description": "Wiki page identifier"},
                "key": {"type": "string", "description": "Credential key name"},
                "value": {"type": "string", "description": "Credential value to store"},
                "credential_type": {
                    "type": "string",
                    "description": "Type of credential (default 'password')",
                },
                "expires_at": {
                    "type": "string",
                    "description": "Expiration date/time string (optional)",
                },
            },
            ["page_id", "key", "value"],
        ),
        approval=True,
    )
    tools.append(wiki_set_credential)

    # -- wiki_run_runbook --------------------------------------------------
    def wiki_run_runbook(page_id: str) -> dict:
        """Start executing a runbook's steps."""
        import uuid as _uuid  # noqa: F811

        page = wiki_store.get_page(page_id)
        if not page or page.get("category") != "runbook":
            return {"ok": False, "error": "not a runbook page"}
        steps = (page.get("structured_data") or {}).get("steps", [])
        execution_id = str(_uuid.uuid4())[:8]
        wiki_store.record_runbook_execution(
            execution_id=execution_id,
            page_id=page_id,
            steps_total=len(steps),
        )
        return {
            "ok": True,
            "execution_id": execution_id,
            "steps": steps,
            "instruction": (
                "Execute each step in order and use wiki_update to track progress."
            ),
        }

    _attach(
        wiki_run_runbook,
        _schema(
            "wiki_run_runbook",
            "Start executing a runbook's steps.",
            {
                "page_id": {"type": "string", "description": "Wiki page identifier of the runbook"},
            },
            ["page_id"],
        ),
    )
    tools.append(wiki_run_runbook)

    return tools
