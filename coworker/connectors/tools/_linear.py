"""Linear connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from ._helpers import _attach, _clamp, _linear_gql, _profile, _schema


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    def linear_search_issues(query: str, max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "linear", "api_key")
        if err:
            return err
        gql = (
            "query($term: String!, $first: Int!) {"
            " searchIssues(term: $term, first: $first) {"
            " nodes { identifier title url state { name } assignee { name } } } }"
        )
        return _linear_gql(profile["api_key"], gql, {"term": query, "first": _clamp(max_results)})

    linear_search_issues.__name__ = "linear_search_issues"
    tools.append(
        _attach(
            linear_search_issues,
            _schema(
                "linear_search_issues",
                "Search Linear issues by text.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["linear", "read"],
        )
    )

    def linear_get_issue(issue_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "linear", "api_key")
        if err:
            return err
        gql = (
            "query($id: String!) { issue(id: $id) {"
            " identifier title description url state { name } assignee { name }"
            " comments { nodes { body user { name } } } } }"
        )
        return _linear_gql(profile["api_key"], gql, {"id": issue_id})

    linear_get_issue.__name__ = "linear_get_issue"
    tools.append(
        _attach(
            linear_get_issue,
            _schema(
                "linear_get_issue",
                "Read a Linear issue (with comments) by ID or key like ENG-123.",
                {"issue_id": {"type": "string"}},
                ["issue_id"],
            ),
            caps=["linear", "read"],
        )
    )

    def linear_list_teams() -> dict[str, Any]:
        profile, err = _profile(secrets, "linear", "api_key")
        if err:
            return err
        return _linear_gql(profile["api_key"], "{ teams { nodes { id key name } } }", {})

    linear_list_teams.__name__ = "linear_list_teams"
    tools.append(
        _attach(
            linear_list_teams,
            _schema(
                "linear_list_teams",
                "List Linear teams (IDs are needed to create issues).",
                {},
                [],
            ),
            caps=["linear", "read"],
        )
    )

    def linear_create_issue(team_id: str, title: str, description: str = "") -> dict[str, Any]:
        profile, err = _profile(secrets, "linear", "api_key")
        if err:
            return err
        gql = (
            "mutation($input: IssueCreateInput!) { issueCreate(input: $input) {"
            " success issue { identifier url } } }"
        )
        return _linear_gql(
            profile["api_key"],
            gql,
            {"input": {"teamId": team_id, "title": title, "description": description}},
        )

    linear_create_issue.__name__ = "linear_create_issue"
    tools.append(
        _attach(
            linear_create_issue,
            _schema(
                "linear_create_issue",
                "Create a Linear issue. Get team_id from linear_list_teams. Requires user approval.",
                {
                    "team_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["team_id", "title"],
            ),
            approval=True,
            caps=["linear", "write"],
        )
    )
