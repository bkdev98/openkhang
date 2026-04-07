"""Explicitly save a note or insight to long-term memory."""
from __future__ import annotations

from ..tool_registry import BaseTool

_VALID_CATEGORIES = {"note", "decision", "person", "project", "meeting"}
_DEFAULT_CATEGORY = "note"


class MemoryNoteTool(BaseTool):
    """Save a note, insight, or decision to long-term memory (inward agent scope)."""

    def __init__(self, memory_client) -> None:
        self._memory = memory_client

    @property
    def name(self) -> str:
        return "memory_note"

    @property
    def description(self) -> str:
        return (
            "Save a note, insight, or decision to long-term memory. "
            "Use when you learn something important that should be remembered for future "
            "conversations. Examples: 'Alice is the new lead for payments team', "
            "'Sprint 43 goal is to finish disbursement 2.2'."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The note to save",
                },
                "category": {
                    "type": "string",
                    "description": "Category tag: note, decision, person, project, meeting",
                    "default": _DEFAULT_CATEGORY,
                    "enum": list(_VALID_CATEGORIES),
                },
            },
            "required": ["content"],
        }

    async def execute(self, **kwargs) -> str:
        content: str = kwargs["content"]
        category: str = kwargs.get("category", _DEFAULT_CATEGORY)

        if category not in _VALID_CATEGORIES:
            category = _DEFAULT_CATEGORY

        try:
            await self._memory.add_memory(
                content,
                metadata={"source": "agent_note", "category": category},
                agent_id="inward",
            )
        except Exception as exc:
            return f"Failed to save note: {exc}"

        preview = content[:100]
        suffix = "..." if len(content) > 100 else ""
        return f"Saved note: {preview}{suffix}"
