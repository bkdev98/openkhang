"""Look up Matrix rooms by person name for inward-mode actions.

Queries the Matrix API for joined rooms and member display names.
Fuzzy-matches Vietnamese names (diacritics-insensitive, first/last name).
"""

from __future__ import annotations

import json
import logging
import os
import unicodedata
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

_HOMESERVER = os.getenv("MATRIX_HOMESERVER", "http://localhost:8008")
_OWN_USER = os.getenv("MATRIX_USER", "@claude:localhost")


def _strip_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _matrix_get(path: str, token: str) -> Any:
    """GET request to Matrix client API."""
    url = f"{_HOMESERVER.rstrip('/')}{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.warning("Matrix API error (%s): %s", path[:60], exc)
        return None


async def find_room_by_person(name: str) -> Optional[dict[str, str]]:
    """Find a DM room for a person by fuzzy name match.

    Args:
        name: Person's name (partial OK, e.g. "Dương", "duong.phan1", "PHAN DƯƠNG")

    Returns:
        Dict with room_id, display_name, user_id — or None if not found.
    """
    import asyncio
    token = os.getenv("MATRIX_ACCESS_TOKEN", "")
    if not token:
        return None

    # Normalize search query
    query = _strip_diacritics(name.strip())
    # Also handle email-style names: "duong.phan1" → "duong phan"
    query_parts = query.replace(".", " ").replace("_", " ").split()
    # Remove trailing digits (duong.phan1 → duong phan)
    query_parts = [p.rstrip("0123456789") for p in query_parts if p.rstrip("0123456789")]

    # Get joined rooms
    rooms_data = await asyncio.to_thread(_matrix_get, "/_matrix/client/v3/joined_rooms", token)
    if not rooms_data:
        return None

    rooms = rooms_data.get("joined_rooms", [])

    # Search each room for matching member
    best_match: Optional[dict[str, str]] = None
    best_score = 0

    for room_id in rooms:
        members_data = await asyncio.to_thread(
            _matrix_get, f"/_matrix/client/v3/rooms/{room_id}/members", token
        )
        if not members_data:
            continue

        chunks = members_data.get("chunk", [])
        # Count non-bot members to detect DMs (2 members = DM)
        real_members = [c for c in chunks if c.get("type") == "m.room.member"
                        and "claude" not in c.get("state_key", "")]
        is_dm = len(real_members) <= 2

        for chunk in chunks:
            if chunk.get("type") != "m.room.member":
                continue
            user_id = chunk.get("state_key", "")
            if user_id == _OWN_USER or "claude" in user_id:
                continue

            display_name = chunk.get("content", {}).get("displayname", "")
            if not display_name:
                continue

            dn_normalized = _strip_diacritics(display_name)

            # Count matching query parts
            matched_parts = sum(1 for part in query_parts if part in dn_normalized)
            # Require ALL query parts to match (avoid "nguyen" matching everyone)
            if len(query_parts) > 1 and matched_parts < len(query_parts):
                continue
            if matched_parts == 0:
                continue

            score = matched_parts
            # Bonus for exact substring match
            if query in dn_normalized:
                score += 2
            # Prefer DM rooms over group rooms
            if is_dm:
                score += 3

            if score > best_score:
                best_score = score
                best_match = {
                    "room_id": room_id,
                    "display_name": display_name,
                    "user_id": user_id,
                }

    if best_match and best_score > 0:
        logger.info("room_lookup: '%s' → %s (%s)", name, best_match["display_name"], best_match["room_id"])
    else:
        logger.info("room_lookup: '%s' → no match found", name)

    return best_match if best_score > 0 else None
