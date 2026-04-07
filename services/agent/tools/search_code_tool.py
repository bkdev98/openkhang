"""Search indexed source code (3 projects) for classes, functions, APIs."""
from __future__ import annotations

from ..tool_registry import BaseTool
from ..skills.skill_helpers import extract_code_search_terms


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
        search_terms = extract_code_search_terms(query)
        return await self._memory.search_code(search_terms, limit=limit)
