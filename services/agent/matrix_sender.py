"""Matrix API sender for outward agent replies.

Sends text messages to Matrix rooms via the client/v3 REST API.
Supports plain messages and thread replies (m.thread rel_type).
All sent messages are logged to the episodic store.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# Rate limit: max outward auto-replies per minute per room
MAX_AUTO_REPLIES_PER_MINUTE = 5


class MatrixSender:
    """Send messages to Matrix rooms on behalf of the configured user.

    Usage:
        sender = MatrixSender(homeserver="http://localhost:8008", token="syt_...")
        event_id = await sender.send(room_id="!abc:localhost", text="Hello!")
    """

    def __init__(self, homeserver: str, access_token: str) -> None:
        self._hs = homeserver.rstrip("/")
        self._token = access_token
        # Per-room rate limiting: room_id → list of epoch seconds for recent sends
        self._send_times: dict[str, list[float]] = {}

    async def send(
        self,
        room_id: str,
        text: str,
        thread_event_id: Optional[str] = None,
    ) -> str:
        """Send a text message to a Matrix room.

        Runs the HTTP call in a thread-pool executor to stay non-blocking.

        Args:
            room_id: Matrix room ID (e.g. "!abc123:localhost").
            text: Plain-text message body.
            thread_event_id: If set, reply into this thread (m.thread relation).

        Returns:
            The Matrix event_id of the sent message.

        Raises:
            RuntimeError: On HTTP error or rate limit exceeded.
        """
        import asyncio

        self._check_rate_limit(room_id)

        loop = asyncio.get_running_loop()
        event_id = await loop.run_in_executor(
            None,
            lambda: self._send_sync(room_id, text, thread_event_id),
        )

        self._record_send(room_id)
        logger.info("Sent Matrix message event_id=%s room=%s", event_id, room_id)
        return event_id

    def _send_sync(
        self,
        room_id: str,
        text: str,
        thread_event_id: Optional[str],
    ) -> str:
        """Blocking HTTP PUT to Matrix client API. Called in executor."""
        txn_id = str(uuid.uuid4()).replace("-", "")
        enc_room = urllib.parse.quote(room_id, safe="")
        path = f"/_matrix/client/v3/rooms/{enc_room}/send/m.room.message/{txn_id}"
        url = self._hs + path

        content: dict = {
            "msgtype": "m.text",
            "body": text,
        }

        if thread_event_id:
            content["m.relates_to"] = {
                "rel_type": "m.thread",
                "event_id": thread_event_id,
            }

        data = json.dumps(content).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="PUT")
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                return result.get("event_id", "")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Matrix send failed HTTP {exc.code}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Matrix connection error: {exc.reason}") from exc

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self, room_id: str) -> None:
        """Raise if this room has hit MAX_AUTO_REPLIES_PER_MINUTE in last 60s."""
        now = time.monotonic()
        times = self._send_times.get(room_id, [])
        # Keep only sends within last 60 seconds
        recent = [t for t in times if now - t < 60.0]
        if len(recent) >= MAX_AUTO_REPLIES_PER_MINUTE:
            raise RuntimeError(
                f"Rate limit: already sent {MAX_AUTO_REPLIES_PER_MINUTE} messages "
                f"to {room_id} in the last minute. Reply queued as draft."
            )
        self._send_times[room_id] = recent

    def _record_send(self, room_id: str) -> None:
        """Record a successful send for rate-limit tracking."""
        times = self._send_times.get(room_id, [])
        times.append(time.monotonic())
        self._send_times[room_id] = times
