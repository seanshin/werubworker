"""Stripe connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _bearer_headers, _clamp, _profile, _schema


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    def stripe_search_customers(query: str, max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "stripe", "api_key")
        if err:
            return err
        return _helpers._request(
            "GET",
            "https://api.stripe.com/v1/customers/search",
            headers=_bearer_headers(profile["api_key"]),
            params={"query": query, "limit": _clamp(max_results)},
        )

    stripe_search_customers.__name__ = "stripe_search_customers"
    tools.append(
        _attach(
            stripe_search_customers,
            _schema(
                "stripe_search_customers",
                "Search Stripe customers. Query uses Stripe search syntax, e.g. email:'jane@example.com' or name~'Jane'.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["stripe", "read"],
        )
    )

    def stripe_list_charges(
        customer_id: str = "", max_results: int = 10
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "stripe", "api_key")
        if err:
            return err
        params: dict[str, Any] = {"limit": _clamp(max_results)}
        if customer_id:
            params["customer"] = customer_id
        return _helpers._request(
            "GET",
            "https://api.stripe.com/v1/charges",
            headers=_bearer_headers(profile["api_key"]),
            params=params,
        )

    stripe_list_charges.__name__ = "stripe_list_charges"
    tools.append(
        _attach(
            stripe_list_charges,
            _schema(
                "stripe_list_charges",
                "List Stripe charges, optionally for one customer.",
                {"customer_id": {"type": "string"}, "max_results": {"type": "integer"}},
                [],
            ),
            caps=["stripe", "read"],
        )
    )

    def stripe_list_invoices(
        customer_id: str = "", max_results: int = 10
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "stripe", "api_key")
        if err:
            return err
        params: dict[str, Any] = {"limit": _clamp(max_results)}
        if customer_id:
            params["customer"] = customer_id
        return _helpers._request(
            "GET",
            "https://api.stripe.com/v1/invoices",
            headers=_bearer_headers(profile["api_key"]),
            params=params,
        )

    stripe_list_invoices.__name__ = "stripe_list_invoices"
    tools.append(
        _attach(
            stripe_list_invoices,
            _schema(
                "stripe_list_invoices",
                "List Stripe invoices, optionally for one customer.",
                {"customer_id": {"type": "string"}, "max_results": {"type": "integer"}},
                [],
            ),
            caps=["stripe", "read"],
        )
    )
