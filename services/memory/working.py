"""Working memory: in-memory session context with TTL expiry.

Keyed by session_id. Entries auto-expire after 30 minutes of inactivity.
No persistence — this is intentionally ephemeral.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Optional


_TTL_SECONDS = 30 * 60  # 30 minutes


class WorkingMemory:
    """Thread-safe in-memory context store with TTL-based expiry.

    Each session holds an arbitrary dict of context values. Reads and
    writes reset the TTL for that session. Expired sessions are pruned
    lazily on the next access to that key, and eagerly via purge_expired().
    """

    def __init__(self, ttl_seconds: int = _TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        # { session_id: {"data": dict, "last_access": float} }
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_context(self, session_id: str, key: str, value: Any) -> None:
        """Set a key in the session context, resetting the TTL."""
        with self._lock:
            entry = self._store.setdefault(session_id, {"data": {}, "last_access": 0.0})
            entry["data"][key] = value
            entry["last_access"] = time.monotonic()

    def get_context(self, session_id: str, key: Optional[str] = None) -> Any:
        """Return one key or the full context dict for a session.

        Returns None if the session is expired or the key is absent.
        Accessing a valid session resets its TTL.
        """
        with self._lock:
            entry = self._store.get(session_id)
            if entry is None:
                return None
            if self._is_expired(entry):
                del self._store[session_id]
                return None
            entry["last_access"] = time.monotonic()
            if key is None:
                return dict(entry["data"])  # copy to avoid external mutation
            return entry["data"].get(key)

    def clear_session(self, session_id: str) -> None:
        """Remove all context for a session immediately."""
        with self._lock:
            self._store.pop(session_id, None)

    def purge_expired(self) -> int:
        """Remove all expired sessions. Returns count of sessions pruned."""
        with self._lock:
            expired = [
                sid for sid, entry in self._store.items() if self._is_expired(entry)
            ]
            for sid in expired:
                del self._store[sid]
        return len(expired)

    def active_sessions(self) -> list[str]:
        """Return list of non-expired session IDs."""
        with self._lock:
            return [
                sid
                for sid, entry in self._store.items()
                if not self._is_expired(entry)
            ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        if self._ttl <= 0:
            return False  # TTL disabled — sessions never expire
        return (time.monotonic() - entry["last_access"]) > self._ttl
