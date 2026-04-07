"""Look up a person's DM room by name (fuzzy Vietnamese name matching)."""
from __future__ import annotations

from ..tool_registry import BaseTool
from ..room_lookup import find_room_by_person


class LookupPersonTool(BaseTool):
    """Find a colleague's DM room using fuzzy Vietnamese name matching."""

    @property
    def name(self) -> str:
        return "lookup_person"

    @property
    def description(self) -> str:
        return (
            "Find a colleague's DM room by name. Supports Vietnamese names with or without "
            "diacritics. Returns room_id, display_name, user_id."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Person's name (partial OK, e.g. 'Dương', 'duong.phan1')",
                },
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs) -> dict | None:
        return await find_room_by_person(kwargs["name"])
