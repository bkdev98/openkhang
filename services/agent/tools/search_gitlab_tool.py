"""Search GitLab merge requests and issues via the glab CLI."""
from __future__ import annotations

import json
import logging
import subprocess

from ..tool_registry import BaseTool

logger = logging.getLogger(__name__)


class SearchGitLabTool(BaseTool):
    """Thin wrapper around `glab mr list` / `glab issue list` for real-time search."""

    @property
    def name(self) -> str:
        return "search_gitlab"

    @property
    def description(self) -> str:
        return (
            "Search GitLab merge requests and issues. "
            "Returns MR/issue number, title, state, author, and URL. "
            "Use for 'any open MRs', 'my pending reviews', 'recent merged MRs'."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords",
                },
                "type": {
                    "type": "string",
                    "description": "Resource type: mr | issue (default: mr)",
                    "enum": ["mr", "issue"],
                    "default": "mr",
                },
                "state": {
                    "type": "string",
                    "description": "Filter by state: opened | merged | closed | all",
                    "enum": ["opened", "merged", "closed", "all"],
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
        resource_type: str = kwargs.get("type", "mr")
        state: str | None = kwargs.get("state")
        limit = int(kwargs.get("limit", 10))

        args = _build_args(query, resource_type, state, limit)

        try:
            proc = subprocess.run(
                ["glab"] + args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            return {"error": "`glab` CLI not found. Install via: brew install glab"}
        except subprocess.TimeoutExpired:
            return {"error": "glab CLI timed out after 10 seconds"}

        if proc.returncode != 0:
            err = proc.stderr.strip()[:300]
            logger.warning("glab CLI rc=%d: %s", proc.returncode, err)
            return {"error": f"glab CLI error: {err}"}

        stdout = proc.stdout.strip()
        if not stdout:
            return []

        try:
            data = json.loads(stdout)
            items = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            logger.warning("glab returned non-JSON output: %s", stdout[:200])
            return {"error": "Unexpected output format from glab CLI"}

        return [_format_item(i, resource_type) for i in items[:limit]]


def _build_args(query: str, resource_type: str, state: str | None, limit: int) -> list[str]:
    """Build glab CLI argument list."""
    sub = "mr" if resource_type == "mr" else "issue"
    args = [sub, "list", "--search", query, "-F", "json", "--per-page", str(limit)]
    if state and state != "all":
        args += ["--state", state]
    return args


def _format_item(item: dict, resource_type: str) -> dict:
    """Normalise raw glab JSON item to a consistent flat dict."""
    author_raw = item.get("author") or {}
    author = (
        author_raw.get("name") or author_raw.get("username") or ""
        if isinstance(author_raw, dict) else str(author_raw)
    )

    result = {
        "id": item.get("iid") or item.get("id", ""),
        "title": item.get("title", ""),
        "state": item.get("state", ""),
        "author": author,
        "url": item.get("web_url") or item.get("url") or "",
    }

    if resource_type == "mr":
        result["source_branch"] = item.get("source_branch", "")
        result["target_branch"] = item.get("target_branch", "")

    return result
