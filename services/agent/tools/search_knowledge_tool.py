"""Search semantic memory (Mem0 + pgvector) for relevant knowledge."""
from __future__ import annotations

from ..tool_registry import BaseTool


class SearchKnowledgeTool(BaseTool):
    """Semantic search across Mem0 memories scoped by agent_id."""

    def __init__(self, memory_client) -> None:
        self._memory = memory_client

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search semantic memory for relevant knowledge about work topics, "
            "conversations, people, projects. Returns ranked results with relevance scores."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query in natural language",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return",
                    "default": 10,
                },
                "agent_id": {
                    "type": "string",
                    "description": "Memory scope: 'outward' or 'inward'",
                    "default": "outward",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> list[dict]:
        query = kwargs["query"]
        limit = kwargs.get("limit", 10)
        agent_id = kwargs.get("agent_id", "outward")
        return await self._memory.search(query, agent_id=agent_id, limit=limit)
