"""Search Jira tickets via the jira CLI."""
from __future__ import annotations

import json
import logging
import os
import subprocess

from ..tool_registry import BaseTool

logger = logging.getLogger(__name__)

# Signals that the query is already JQL (not plain keyword)
_JQL_OPERATORS = ("=", "!=", "~", " AND ", " OR ", " IN ", " ORDER ")


class SearchJiraTool(BaseTool):
    """Thin wrapper around `jira issue list --output json` for real-time ticket search."""

    @property
    def name(self) -> str:
        return "search_jira"

    @property
    def description(self) -> str:
        return (
            "Search Jira tickets by JQL query or keyword. "
            "Returns ticket key, summary, status, assignee, and priority. "
            "Use for 'what tickets are assigned to me', 'open bugs in VR project'."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "JQL expression or plain keyword search",
                },
                "project": {
                    "type": "string",
                    "description": "Jira project key (default from JIRA_PROJECT env var)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> list[dict] | dict:
        query: str = kwargs["query"]
        project: str = kwargs.get("project") or os.getenv("JIRA_PROJECT", "")
        limit = int(kwargs.get("limit", 10))

        jql = _build_jql(query, project)
        args = [
            "issue", "list",
            "--jql", jql,
            "--output", "json",
        ]

        try:
            proc = subprocess.run(
                ["jira"] + args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            return {"error": "`jira` CLI not found. Install via: brew install ankitpokhrel/jira-cli/jira"}
        except subprocess.TimeoutExpired:
            return {"error": "Jira CLI timed out after 10 seconds"}

        if proc.returncode != 0:
            err = proc.stderr.strip()[:300]
            logger.warning("jira CLI rc=%d: %s", proc.returncode, err)
            return {"error": f"Jira CLI error: {err}"}

        stdout = proc.stdout.strip()
        if not stdout:
            return []

        try:
            data = json.loads(stdout)
            issues = data if isinstance(data, list) else data.get("issues", [data])
        except json.JSONDecodeError:
            # Fallback: plain tab-separated output
            issues = _parse_plain(stdout)

        return [_format_issue(i) for i in issues[:limit]]


def _build_jql(query: str, project: str) -> str:
    """Wrap plain keyword as JQL if needed."""
    if any(op in query for op in _JQL_OPERATORS):
        return query
    base = f'text ~ "{query}"'
    if project:
        base += f" AND project = {project}"
    return base + " ORDER BY updated DESC"


def _parse_plain(text: str) -> list[dict]:
    """Parse tab-separated fallback output: KEY\\tSUMMARY\\tSTATUS\\tASSIGNEE\\tPRIORITY."""
    fields = ["key", "summary", "status", "assignee", "priority"]
    items = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) >= 2:
            items.append({fields[i]: parts[i] if i < len(parts) else "" for i in range(len(fields))})
    return items


def _format_issue(issue: dict) -> dict:
    """Normalise raw jira-cli issue dict (nested or flat)."""
    fields = issue.get("fields", issue)

    def _str(val) -> str:
        if isinstance(val, dict):
            return val.get("name") or val.get("displayName") or val.get("key") or ""
        return str(val) if val is not None else ""

    return {
        "key": issue.get("key", ""),
        "summary": _str(fields.get("summary", issue.get("summary", ""))),
        "status": _str(fields.get("status", issue.get("status", ""))),
        "assignee": _str(fields.get("assignee", issue.get("assignee", ""))),
        "priority": _str(fields.get("priority", issue.get("priority", ""))),
    }
