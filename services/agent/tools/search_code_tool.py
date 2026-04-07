"""Search indexed source code (3 projects) for classes, functions, APIs."""
from __future__ import annotations

import re

from ..tool_registry import BaseTool


class SearchCodeTool(BaseTool):
    """Full-text + semantic search across indexed code chunks in Postgres."""

    def __init__(self, memory_client) -> None:
        self._memory = memory_client

    @property
    def name(self) -> str:
        return "search_code"

    @property
    def description(self) -> str:
        return (
            "Search indexed source code repositories for classes, functions, API endpoints, "
            "business logic. Supports CamelCase and snake_case queries. Use when asked about "
            "code, implementations, or technical details."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Code search query (natural language or code identifiers)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results",
                    "default": 20,
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> list[dict]:
        query = kwargs["query"]
        limit = kwargs.get("limit", 20)
        search_terms = self._extract_code_search_terms(query)
        return await self._memory.search_code(search_terms, limit=limit)

    @staticmethod
    def _extract_code_search_terms(body: str) -> str:
        """Convert natural language query to code-relevant search terms.

        Extracts English keywords, generates CamelCase/snake_case variants,
        and combines with the original query for broader matching.

        NOTE: Mirrors pipeline.py._extract_code_search_terms() — kept in sync
        until the pipeline copy is removed in Phase 3.
        """
        english_words = re.findall(r"[a-zA-Z_]{3,}", body)
        terms = set(english_words)
        if len(english_words) >= 2:
            camel = "".join(w.capitalize() for w in english_words)
            terms.add(camel)
            terms.add("_".join(w.lower() for w in english_words))
        for w in english_words:
            terms.add(w)
        return " ".join(terms) + " " + body
