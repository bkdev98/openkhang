"""Search the web via DuckDuckGo HTML (no API key required)."""
from __future__ import annotations

import re

import httpx

from ..tool_registry import BaseTool

_USER_AGENT = "openkhang-agent/1.0"
_DDG_URL = "https://html.duckduckgo.com/html/"
_TIMEOUT = 10.0
_DEFAULT_LIMIT = 5


class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo and return titles, URLs, and snippets."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for information not available in memory. "
            "Returns titles, URLs, and snippets. Use when memory search returns no relevant "
            "results or for general knowledge questions."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return",
                    "default": _DEFAULT_LIMIT,
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> list[dict]:
        query: str = kwargs["query"]
        limit: int = kwargs.get("limit", _DEFAULT_LIMIT)

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                response = await client.get(_DDG_URL, params={"q": query})
                response.raise_for_status()
                html = response.text
        except httpx.TimeoutException:
            return [{"error": f"Search timed out after {_TIMEOUT:.0f}s"}]
        except Exception as exc:
            return [{"error": f"Search failed: {exc}"}]

        return _parse_ddg_results(html, limit)


def _parse_ddg_results(html: str, limit: int) -> list[dict]:
    """Extract result title, URL, and snippet from DuckDuckGo HTML response."""
    # Extract anchor tags with class result__a (titles + URLs)
    title_pattern = re.compile(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    # Extract snippet spans/anchors with class result__snippet
    snippet_pattern = re.compile(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|span)>',
        re.DOTALL,
    )

    titles_urls = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    results = []
    for i, (url, raw_title) in enumerate(titles_urls[:limit]):
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()

        # Skip non-http URLs (DDG internal links)
        if not url.startswith("http"):
            continue

        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break

    if not results:
        return [{"error": "No results found or failed to parse response"}]

    return results
