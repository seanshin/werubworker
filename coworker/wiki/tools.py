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

    return tools
