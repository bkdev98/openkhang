"""Fetch a URL and return its content as plain text."""
from __future__ import annotations

import re

import httpx

from ..tool_registry import BaseTool

_USER_AGENT = "openkhang-agent/1.0"
_DEFAULT_MAX_CHARS = 5000
_TIMEOUT = 15.0


class WebFetchTool(BaseTool):
    """Fetch a URL and return its text content (HTML tags stripped)."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a URL and return its content as text. Useful for reading documentation, "
            "API references, web pages, or any URL shared in conversation. "
            "Returns plain text (HTML tags stripped)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max characters to return (truncate longer content)",
                    "default": _DEFAULT_MAX_CHARS,
                },
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs) -> str:
        url: str = kwargs["url"]
        max_chars: int = kwargs.get("max_chars", _DEFAULT_MAX_CHARS)

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
        except httpx.TimeoutException:
            return f"Error: request to {url} timed out after {_TIMEOUT:.0f}s"
        except httpx.HTTPStatusError as exc:
            return f"Error: HTTP {exc.response.status_code} fetching {url}"
        except Exception as exc:
            return f"Error fetching {url}: {exc}"

        # Strip HTML tags
        text = re.sub(r"<[^>]+>", "", html)
        # Collapse excessive whitespace / blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = text.strip()

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[Truncated — {len(text) - max_chars} chars omitted]"

        return text
