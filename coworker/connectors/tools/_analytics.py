"""Product analytics connector tools: PostHog, Mixpanel, Amplitude."""

from __future__ import annotations

import json
from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import (
    _GEN_ACCOUNT_PROP,
    _account_profile,
    _acct_result,
    _attach,
    _bearer_headers,
    _clamp,
    _schema,
)


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    def _posthog_base(profile: dict[str, Any]) -> str:
        return str(profile.get("base_url") or "https://us.posthog.com").rstrip("/")

    def posthog_query(hogql: str, account: str = "") -> dict[str, Any]:
        aid, profile, err = _account_profile(
            secrets, "posthog", account, "api_key", "project_id"
        )
        if err:
            return err
        result = _helpers._request(
            "POST",
            f"{_posthog_base(profile)}/api/projects/{profile['project_id']}/query",
            headers=_bearer_headers(profile["api_key"]),
            json={"query": {"kind": "HogQLQuery", "query": hogql}},
        )
        return _acct_result(aid, result)

    posthog_query.__name__ = "posthog_query"
    tools.append(
        _attach(
            posthog_query,
            _schema(
                "posthog_query",
                "Run a HogQL (SQL-like) query against PostHog analytics, e.g. "
                "SELECT event, count() FROM events WHERE timestamp > now() - "
                "INTERVAL 7 DAY GROUP BY event.",
                {"hogql": {"type": "string"}, "account": _GEN_ACCOUNT_PROP},
                ["hogql"],
            ),
            caps=["posthog", "read"],
        )
    )

    def posthog_list_insights(
        query: str = "", max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(
            secrets, "posthog", account, "api_key", "project_id"
        )
        if err:
            return err
        params: dict[str, Any] = {"limit": _clamp(max_results)}
        if query:
            params["search"] = query
        result = _helpers._request(
            "GET",
            f"{_posthog_base(profile)}/api/projects/{profile['project_id']}/insights",
            headers=_bearer_headers(profile["api_key"]),
            params=params,
        )
        return _acct_result(aid, result)

    posthog_list_insights.__name__ = "posthog_list_insights"
    tools.append(
        _attach(
            posthog_list_insights,
            _schema(
                "posthog_list_insights",
                "List saved PostHog insights (dashboards' building blocks).",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                [],
            ),
            caps=["posthog", "read"],
        )
    )

    def mixpanel_segmentation(
        event: str,
        from_date: str,
        to_date: str,
        unit: str = "day",
        where: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(
            secrets, "mixpanel", account, "username", "secret", "project_id"
        )
        if err:
            return err
        params = {
            "project_id": profile["project_id"],
            "event": event,
            "from_date": from_date,
            "to_date": to_date,
            "unit": (
                unit if unit in ("minute", "hour", "day", "week", "month") else "day"
            ),
        }
        if where:
            params["where"] = where
        result = _helpers._request(
            "GET",
            "https://mixpanel.com/api/query/segmentation",
            params=params,
            auth=(profile["username"], profile["secret"]),
        )
        return _acct_result(aid, result)

    mixpanel_segmentation.__name__ = "mixpanel_segmentation"
    tools.append(
        _attach(
            mixpanel_segmentation,
            _schema(
                "mixpanel_segmentation",
                "Mixpanel event counts over a date range (YYYY-MM-DD), optionally "
                'filtered by a `where` expression like properties["plan"]=="pro".',
                {
                    "event": {"type": "string"},
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                    "unit": {"type": "string"},
                    "where": {"type": "string"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["event", "from_date", "to_date"],
            ),
            caps=["mixpanel", "read"],
        )
    )

    def mixpanel_top_events(max_results: int = 10, account: str = "") -> dict[str, Any]:
        aid, profile, err = _account_profile(
            secrets, "mixpanel", account, "username", "secret", "project_id"
        )
        if err:
            return err
        result = _helpers._request(
            "GET",
            "https://mixpanel.com/api/query/events/top",
            params={
                "project_id": profile["project_id"],
                "type": "general",
                "limit": _clamp(max_results, ceiling=100),
            },
            auth=(profile["username"], profile["secret"]),
        )
        return _acct_result(aid, result)

    mixpanel_top_events.__name__ = "mixpanel_top_events"
    tools.append(
        _attach(
            mixpanel_top_events,
            _schema(
                "mixpanel_top_events",
                "Today's top Mixpanel events by volume.",
                {"max_results": {"type": "integer"}, "account": _GEN_ACCOUNT_PROP},
                [],
            ),
            caps=["mixpanel", "read"],
        )
    )

    def amplitude_active_users(
        start: str, end: str, metric: str = "active", account: str = ""
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(
            secrets, "amplitude", account, "api_key", "secret_key"
        )
        if err:
            return err
        result = _helpers._request(
            "GET",
            "https://amplitude.com/api/2/users",
            params={
                "m": metric if metric in ("active", "new") else "active",
                "start": start.replace("-", ""),
                "end": end.replace("-", ""),
                "i": 1,
            },
            auth=(profile["api_key"], profile["secret_key"]),
        )
        return _acct_result(aid, result)

    amplitude_active_users.__name__ = "amplitude_active_users"
    tools.append(
        _attach(
            amplitude_active_users,
            _schema(
                "amplitude_active_users",
                "Amplitude daily active or new users between two dates (YYYYMMDD "
                "or YYYY-MM-DD).",
                {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "metric": {"type": "string", "description": "active | new"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["start", "end"],
            ),
            caps=["amplitude", "read"],
        )
    )

    def amplitude_event_totals(
        event_type: str, start: str, end: str, account: str = ""
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(
            secrets, "amplitude", account, "api_key", "secret_key"
        )
        if err:
            return err
        result = _helpers._request(
            "GET",
            "https://amplitude.com/api/2/events/segmentation",
            params={
                "e": json.dumps({"event_type": event_type}),
                "start": start.replace("-", ""),
                "end": end.replace("-", ""),
                "m": "totals",
            },
            auth=(profile["api_key"], profile["secret_key"]),
        )
        return _acct_result(aid, result)

    amplitude_event_totals.__name__ = "amplitude_event_totals"
    tools.append(
        _attach(
            amplitude_event_totals,
            _schema(
                "amplitude_event_totals",
                "Daily totals for one Amplitude event between two dates.",
                {
                    "event_type": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["event_type", "start", "end"],
            ),
            caps=["amplitude", "read"],
        )
    )
