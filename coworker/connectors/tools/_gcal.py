"""Google Calendar connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _gcal_profile, _google_headers, _schema


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    _CAL_ACCOUNT_PROP = {
        "type": "string",
        "description": "Google account email to use; omit for the default account.",
    }

    def _gcal_result(email: str, result: dict[str, Any]) -> dict[str, Any]:
        # Name the account on every success so approvals/transcripts say whose
        # calendar was touched (same contract as the gmail tools).
        if result.get("ok"):
            result["account"] = email
        return result

    def gcal_list_events(
        calendar_id: str = "primary",
        time_min: str = "",
        time_max: str = "",
        max_results: int = 10,
        account: str = "",
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        params: dict[str, Any] = {
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": max(1, min(int(max_results or 10), 20)),
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        return _gcal_result(
            email,
            _helpers._request(
                "GET",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers=_google_headers(profile["access_token"]),
                params=params,
            ),
        )

    gcal_list_events.__name__ = "gcal_list_events"
    tools.append(
        _attach(
            gcal_list_events,
            _schema(
                "gcal_list_events",
                "List Google Calendar events. time_min/time_max should be RFC3339 timestamps when provided.",
                {
                    "calendar_id": {"type": "string"},
                    "time_min": {"type": "string"},
                    "time_max": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": _CAL_ACCOUNT_PROP,
                },
                [],
            ),
            caps=["calendar", "read"],
        )
    )

    def gcal_free_busy(
        time_min: str,
        time_max: str,
        calendars: str = "primary",
        timezone: str = "UTC",
        account: str = "",
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        items = [
            {"id": c.strip()}
            for c in str(calendars or "primary").split(",")
            if c.strip()
        ]
        return _gcal_result(
            email,
            _helpers._request(
                "POST",
                "https://www.googleapis.com/calendar/v3/freeBusy",
                headers=_google_headers(profile["access_token"]),
                json={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "timeZone": timezone,
                    "items": items,
                },
            ),
        )

    gcal_free_busy.__name__ = "gcal_free_busy"
    tools.append(
        _attach(
            gcal_free_busy,
            _schema(
                "gcal_free_busy",
                "Look up busy intervals (availability) for one or more calendars. "
                "time_min/time_max are RFC3339 timestamps; calendars is a comma-separated list of calendar ids.",
                {
                    "time_min": {"type": "string"},
                    "time_max": {"type": "string"},
                    "calendars": {"type": "string"},
                    "timezone": {"type": "string"},
                    "account": _CAL_ACCOUNT_PROP,
                },
                ["time_min", "time_max"],
            ),
            caps=["calendar", "read"],
        )
    )

    def gcal_create_event(
        summary: str,
        start: str,
        end: str,
        calendar_id: str = "primary",
        timezone: str = "UTC",
        description: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        payload = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start, "timeZone": timezone},
            "end": {"dateTime": end, "timeZone": timezone},
        }
        return _gcal_result(
            email,
            _helpers._request(
                "POST",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers=_google_headers(profile["access_token"]),
                json=payload,
            ),
        )

    gcal_create_event.__name__ = "gcal_create_event"
    tools.append(
        _attach(
            gcal_create_event,
            _schema(
                "gcal_create_event",
                "Create a Google Calendar event. Requires user approval.",
                {
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "calendar_id": {"type": "string"},
                    "timezone": {"type": "string"},
                    "description": {"type": "string"},
                    "account": _CAL_ACCOUNT_PROP,
                },
                ["summary", "start", "end"],
            ),
            approval=True,
            caps=["calendar", "write"],
        )
    )

    def gcal_update_event(
        event_id: str,
        calendar_id: str = "primary",
        summary: str = "",
        start: str = "",
        end: str = "",
        timezone: str = "UTC",
        description: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        # PATCH semantics: only the provided fields change.
        payload: dict[str, Any] = {}
        if summary:
            payload["summary"] = summary
        if description:
            payload["description"] = description
        if start:
            payload["start"] = {"dateTime": start, "timeZone": timezone}
        if end:
            payload["end"] = {"dateTime": end, "timeZone": timezone}
        if not payload:
            return {
                "error": "nothing to update — pass summary, description, start, or end"
            }
        return _gcal_result(
            email,
            _helpers._request(
                "PATCH",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                headers=_google_headers(profile["access_token"]),
                json=payload,
            ),
        )

    gcal_update_event.__name__ = "gcal_update_event"
    tools.append(
        _attach(
            gcal_update_event,
            _schema(
                "gcal_update_event",
                "Update fields of a Google Calendar event (only the provided fields change). Requires user approval.",
                {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "timezone": {"type": "string"},
                    "description": {"type": "string"},
                    "account": _CAL_ACCOUNT_PROP,
                },
                ["event_id"],
            ),
            approval=True,
            caps=["calendar", "write"],
        )
    )

    def gcal_delete_event(
        event_id: str, calendar_id: str = "primary", account: str = ""
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        return _gcal_result(
            email,
            _helpers._request(
                "DELETE",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                headers=_google_headers(profile["access_token"]),
            ),
        )

    gcal_delete_event.__name__ = "gcal_delete_event"
    tools.append(
        _attach(
            gcal_delete_event,
            _schema(
                "gcal_delete_event",
                "Delete a Google Calendar event. Requires user approval.",
                {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                    "account": _CAL_ACCOUNT_PROP,
                },
                ["event_id"],
            ),
            approval=True,
            caps=["calendar", "write"],
        )
    )
