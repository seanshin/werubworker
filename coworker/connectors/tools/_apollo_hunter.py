"""Apollo and Hunter prospecting/enrichment connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import (
    _GEN_ACCOUNT_PROP,
    _account_profile,
    _acct_result,
    _attach,
    _clamp,
    _schema,
)


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    def _apollo_headers(profile: dict[str, Any]) -> dict[str, str]:
        return {"X-Api-Key": profile["api_key"], "Content-Type": "application/json"}

    def apollo_enrich_person(
        email: str = "", name: str = "", company_domain: str = "", account: str = ""
    ) -> dict[str, Any]:
        if not email and not name:
            return {"error": "provide an email, a name, or both"}
        aid, profile, err = _account_profile(secrets, "apollo", account, "api_key")
        if err:
            return err
        body: dict[str, Any] = {}
        if email:
            body["email"] = email
        if name:
            body["name"] = name
        if company_domain:
            body["domain"] = company_domain
        result = _helpers._request(
            "POST",
            "https://api.apollo.io/api/v1/people/match",
            headers=_apollo_headers(profile),
            json=body,
        )
        return _acct_result(aid, result)

    apollo_enrich_person.__name__ = "apollo_enrich_person"
    tools.append(
        _attach(
            apollo_enrich_person,
            _schema(
                "apollo_enrich_person",
                "Enrich a person from Apollo: title, company, LinkedIn, location "
                "— by email and/or name (+ optional company domain).",
                {
                    "email": {"type": "string"},
                    "name": {"type": "string"},
                    "company_domain": {"type": "string"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                [],
            ),
            caps=["apollo", "read"],
        )
    )

    def apollo_enrich_company(domain: str, account: str = "") -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "apollo", account, "api_key")
        if err:
            return err
        result = _helpers._request(
            "GET",
            "https://api.apollo.io/api/v1/organizations/enrich",
            headers=_apollo_headers(profile),
            params={"domain": domain},
        )
        return _acct_result(aid, result)

    apollo_enrich_company.__name__ = "apollo_enrich_company"
    tools.append(
        _attach(
            apollo_enrich_company,
            _schema(
                "apollo_enrich_company",
                "Enrich a company from Apollo by domain: size, industry, funding, "
                "tech stack.",
                {"domain": {"type": "string"}, "account": _GEN_ACCOUNT_PROP},
                ["domain"],
            ),
            caps=["apollo", "read"],
        )
    )

    def apollo_search_people(
        query: str, max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "apollo", account, "api_key")
        if err:
            return err
        result = _helpers._request(
            "POST",
            "https://api.apollo.io/api/v1/mixed_people/search",
            headers=_apollo_headers(profile),
            json={"q_keywords": query, "page": 1, "per_page": _clamp(max_results)},
        )
        return _acct_result(aid, result)

    apollo_search_people.__name__ = "apollo_search_people"
    tools.append(
        _attach(
            apollo_search_people,
            _schema(
                "apollo_search_people",
                "Keyword-search people in Apollo's B2B database (e.g. 'VP "
                "engineering fintech Berlin').",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["query"],
            ),
            caps=["apollo", "read"],
        )
    )

    def _hunter_get(
        profile: dict[str, Any], path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        return _helpers._request(
            "GET",
            f"https://api.hunter.io/v2/{path}",
            params={**params, "api_key": profile["api_key"]},
        )

    def hunter_domain_search(
        domain: str, max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "hunter", account, "api_key")
        if err:
            return err
        result = _hunter_get(
            profile, "domain-search", {"domain": domain, "limit": _clamp(max_results)}
        )
        return _acct_result(aid, result)

    hunter_domain_search.__name__ = "hunter_domain_search"
    tools.append(
        _attach(
            hunter_domain_search,
            _schema(
                "hunter_domain_search",
                "Find published email addresses for a company domain (Hunter).",
                {
                    "domain": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["domain"],
            ),
            caps=["hunter", "read"],
        )
    )

    def hunter_find_email(
        domain: str, first_name: str, last_name: str, account: str = ""
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "hunter", account, "api_key")
        if err:
            return err
        result = _hunter_get(
            profile,
            "email-finder",
            {"domain": domain, "first_name": first_name, "last_name": last_name},
        )
        return _acct_result(aid, result)

    hunter_find_email.__name__ = "hunter_find_email"
    tools.append(
        _attach(
            hunter_find_email,
            _schema(
                "hunter_find_email",
                "Find a person's most likely email address from their name and "
                "company domain (Hunter).",
                {
                    "domain": {"type": "string"},
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["domain", "first_name", "last_name"],
            ),
            caps=["hunter", "read"],
        )
    )

    def hunter_verify_email(email: str, account: str = "") -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "hunter", account, "api_key")
        if err:
            return err
        return _acct_result(
            aid, _hunter_get(profile, "email-verifier", {"email": email})
        )

    hunter_verify_email.__name__ = "hunter_verify_email"
    tools.append(
        _attach(
            hunter_verify_email,
            _schema(
                "hunter_verify_email",
                "Check whether an email address is deliverable (Hunter).",
                {"email": {"type": "string"}, "account": _GEN_ACCOUNT_PROP},
                ["email"],
            ),
            caps=["hunter", "read"],
        )
    )
