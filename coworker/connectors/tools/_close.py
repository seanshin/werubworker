"""Close CRM connector tools."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _clamp, _profile, _schema


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    _CLOSE = "https://api.close.com/api/v1"

    def _close_auth(profile: dict[str, Any]) -> tuple[str, str]:
        # HTTP basic: API key as username, blank password.
        return (str(profile.get("api_key", "")), "")

    def close_search_leads(query: str, max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "close", "api_key")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_CLOSE}/lead/",
            auth=_close_auth(profile),
            params={"query": query, "_limit": _clamp(max_results)},
        )

    close_search_leads.__name__ = "close_search_leads"
    tools.append(
        _attach(
            close_search_leads,
            _schema(
                "close_search_leads",
                'Search Close leads (supports Close\'s search syntax, e.g. "status:potential acme").',
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["close", "read"],
        )
    )

    def close_get_lead(lead_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "close", "api_key")
        if err:
            return err
        return _helpers._request(
            "GET", f"{_CLOSE}/lead/{quote(lead_id)}/", auth=_close_auth(profile)
        )

    close_get_lead.__name__ = "close_get_lead"
    tools.append(
        _attach(
            close_get_lead,
            _schema(
                "close_get_lead",
                "Read a Close lead (contacts, opportunities, addresses) by id.",
                {"lead_id": {"type": "string"}},
                ["lead_id"],
            ),
            caps=["close", "read"],
        )
    )

    def close_list_opportunities(lead_id: str = "", max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "close", "api_key")
        if err:
            return err
        params: dict[str, Any] = {"_limit": _clamp(max_results)}
        if lead_id:
            params["lead_id"] = lead_id
        return _helpers._request(
            "GET", f"{_CLOSE}/opportunity/", auth=_close_auth(profile), params=params
        )

    close_list_opportunities.__name__ = "close_list_opportunities"
    tools.append(
        _attach(
            close_list_opportunities,
            _schema(
                "close_list_opportunities",
                "List Close opportunities, optionally for one lead.",
                {"lead_id": {"type": "string"}, "max_results": {"type": "integer"}},
                [],
            ),
            caps=["close", "read"],
        )
    )

    def close_create_lead(
        name: str, contact_name: str = "", contact_email: str = ""
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "close", "api_key")
        if err:
            return err
        body: dict[str, Any] = {"name": name}
        if contact_name or contact_email:
            contact: dict[str, Any] = {"name": contact_name}
            if contact_email:
                contact["emails"] = [{"email": contact_email}]
            body["contacts"] = [contact]
        return _helpers._request("POST", f"{_CLOSE}/lead/", auth=_close_auth(profile), json=body)

    close_create_lead.__name__ = "close_create_lead"
    tools.append(
        _attach(
            close_create_lead,
            _schema(
                "close_create_lead",
                "Create a Close lead (company), optionally with one contact. Requires user approval.",
                {
                    "name": {"type": "string"},
                    "contact_name": {"type": "string"},
                    "contact_email": {"type": "string"},
                },
                ["name"],
            ),
            approval=True,
            caps=["close", "write"],
        )
    )

    def close_update_opportunity(
        opportunity_id: str, status_id: str = "", note: str = ""
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "close", "api_key")
        if err:
            return err
        body: dict[str, Any] = {}
        if status_id:
            body["status_id"] = status_id
        if note:
            body["note"] = note
        if not body:
            return {"error": "nothing to update: pass status_id or note"}
        return _helpers._request(
            "PUT",
            f"{_CLOSE}/opportunity/{quote(opportunity_id)}/",
            auth=_close_auth(profile),
            json=body,
        )

    close_update_opportunity.__name__ = "close_update_opportunity"
    tools.append(
        _attach(
            close_update_opportunity,
            _schema(
                "close_update_opportunity",
                "Update a Close opportunity's status or note. Requires user approval.",
                {
                    "opportunity_id": {"type": "string"},
                    "status_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                ["opportunity_id"],
            ),
            approval=True,
            caps=["close", "write"],
        )
    )

    def close_log_note(lead_id: str, note: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "close", "api_key")
        if err:
            return err
        return _helpers._request(
            "POST",
            f"{_CLOSE}/activity/note/",
            auth=_close_auth(profile),
            json={"lead_id": lead_id, "note": note},
        )

    close_log_note.__name__ = "close_log_note"
    tools.append(
        _attach(
            close_log_note,
            _schema(
                "close_log_note",
                "Log a note on a Close lead's timeline. Requires user approval.",
                {"lead_id": {"type": "string"}, "note": {"type": "string"}},
                ["lead_id", "note"],
            ),
            approval=True,
            caps=["close", "write"],
        )
    )
