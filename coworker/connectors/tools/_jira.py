"""Jira and Confluence connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import (
    _atlassian_base,
    _attach,
    _basic_auth,
    _profile,
    _schema,
)


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    def jira_search_issues(jql: str, max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "jira", "base_url", "email", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_atlassian_base(profile)}/rest/api/3/search",
            auth=_basic_auth(profile["email"], profile["api_token"]),
            params={"jql": jql, "maxResults": max(1, min(int(max_results or 10), 20))},
        )

    jira_search_issues.__name__ = "jira_search_issues"
    tools.append(
        _attach(
            jira_search_issues,
            _schema(
                "jira_search_issues",
                "Search Jira issues using JQL.",
                {"jql": {"type": "string"}, "max_results": {"type": "integer"}},
                ["jql"],
            ),
            caps=["jira", "read"],
        )
    )

    def jira_get_issue(issue_key: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "jira", "base_url", "email", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_atlassian_base(profile)}/rest/api/3/issue/{issue_key}",
            auth=_basic_auth(profile["email"], profile["api_token"]),
        )

    jira_get_issue.__name__ = "jira_get_issue"
    tools.append(
        _attach(
            jira_get_issue,
            _schema(
                "jira_get_issue",
                "Read a Jira issue.",
                {"issue_key": {"type": "string"}},
                ["issue_key"],
            ),
            caps=["jira", "read"],
        )
    )

    def jira_create_issue(
        project_key: str, issue_type: str, summary: str, description: str = ""
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "jira", "base_url", "email", "api_token")
        if err:
            return err
        payload = {
            "fields": {
                "project": {"key": project_key},
                "issuetype": {"name": issue_type},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description or summary}],
                        }
                    ],
                },
            }
        }
        return _helpers._request(
            "POST",
            f"{_atlassian_base(profile)}/rest/api/3/issue",
            auth=_basic_auth(profile["email"], profile["api_token"]),
            json=payload,
        )

    jira_create_issue.__name__ = "jira_create_issue"
    tools.append(
        _attach(
            jira_create_issue,
            _schema(
                "jira_create_issue",
                "Create a Jira issue. Requires user approval.",
                {
                    "project_key": {"type": "string"},
                    "issue_type": {"type": "string"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["project_key", "issue_type", "summary"],
            ),
            approval=True,
            caps=["jira", "write"],
        )
    )

    def confluence_search(query: str, max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "confluence", "base_url", "email", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_atlassian_base(profile)}/wiki/rest/api/search",
            auth=_basic_auth(profile["email"], profile["api_token"]),
            params={
                "cql": f'text ~ "{query}"',
                "limit": max(1, min(int(max_results or 10), 20)),
            },
        )

    confluence_search.__name__ = "confluence_search"
    tools.append(
        _attach(
            confluence_search,
            _schema(
                "confluence_search",
                "Search Confluence pages.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["confluence", "read"],
        )
    )

    def confluence_get_page(page_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "confluence", "base_url", "email", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_atlassian_base(profile)}/wiki/rest/api/content/{page_id}",
            auth=_basic_auth(profile["email"], profile["api_token"]),
            params={"expand": "body.storage,version,space"},
        )

    confluence_get_page.__name__ = "confluence_get_page"
    tools.append(
        _attach(
            confluence_get_page,
            _schema(
                "confluence_get_page",
                "Read a Confluence page.",
                {"page_id": {"type": "string"}},
                ["page_id"],
            ),
            caps=["confluence", "read"],
        )
    )

    def confluence_create_page(
        space_key: str, title: str, body: str, parent_id: str = ""
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "confluence", "base_url", "email", "api_token")
        if err:
            return err
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        return _helpers._request(
            "POST",
            f"{_atlassian_base(profile)}/wiki/rest/api/content",
            auth=_basic_auth(profile["email"], profile["api_token"]),
            json=payload,
        )

    confluence_create_page.__name__ = "confluence_create_page"
    tools.append(
        _attach(
            confluence_create_page,
            _schema(
                "confluence_create_page",
                "Create a Confluence page. Body should be Confluence storage-format HTML. Requires user approval.",
                {
                    "space_key": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "parent_id": {"type": "string"},
                },
                ["space_key", "title", "body"],
            ),
            approval=True,
            caps=["confluence", "write"],
        )
    )
