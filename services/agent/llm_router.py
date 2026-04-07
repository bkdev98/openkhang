"""LLM-based message router for the digital twin agent pipeline.

Hybrid approach: regex fast-path for clear social signals, LLM call (haiku)
for everything else. Returns None on any failure so callers can fall back to
the regex Classifier without interrupting the pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .classifier import SOCIAL_PATTERNS

if TYPE_CHECKING:
    from .llm_client import LLMClient

logger = logging.getLogger(__name__)

# Haiku model — fast and cheap for routing decisions
_ROUTER_MODEL = "claude-haiku-4-5-20251001"
_ROUTER_TIMEOUT_SECS = 2.0
_BODY_TRUNCATE_CHARS = 200


@dataclass
class RouterResult:
    """Structured classification result from the LLM router."""

    mode: str           # 'outward' | 'inward'
    intent: str         # 'question' | 'request' | 'fyi' | 'social' | 'instruction' | 'query'
    should_respond: bool
    priority: str       # 'high' | 'normal' | 'low'
    reasoning: str      # LLM's brief reasoning (for traces/debugging)


class LLMRouter:
    """Route messages using a fast LLM call (haiku) with regex social fast-path.

    Usage:
        router = LLMRouter(llm_client)
        result = await router.route(event)
        if result is None:
            # LLM failed → fall back to regex Classifier
    """

    def __init__(self, llm_client: "LLMClient") -> None:
        self._llm = llm_client
        self._system_prompt = self._load_prompt()

    async def route(self, event: dict) -> RouterResult | None:
        """Route a message event. Returns None on failure (caller falls back to regex).

        Args:
            event: Plain dict from pipeline (body, source, room_name, sender_id, etc.)

        Returns:
            RouterResult on success, None if LLM call fails or times out.
        """
        body = (event.get("body") or "").strip()
        if not body:
            return None

        # Fail fast if system prompt failed to load
        if not self._system_prompt:
            logger.warning("llm_router: no system prompt loaded, falling back to regex")
            return None

        # Fast-path: clear social signals skip the LLM call entirely
        if SOCIAL_PATTERNS.match(body):
            source = (event.get("source") or "").lower()
            mode = "outward" if source in {"matrix", "chat", "gchat", "google_chat"} else "inward"
            member_count = event.get("member_count", 0)
            is_group = member_count > 2 or event.get("is_group", False)
            is_mentioned = event.get("is_mentioned", False)
            should_respond = not is_group or is_mentioned
            return RouterResult(
                mode=mode,
                intent="social",
                should_respond=should_respond,
                priority="low",
                reasoning="regex fast-path: social pattern matched",
            )

        user_message = self._build_user_message(event, body)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            response = await asyncio.wait_for(
                self._llm.generate(
                    messages=messages,
                    model=_ROUTER_MODEL,
                    temperature=0,
                    max_tokens=256,
                    require_structured=False,
                ),
                timeout=_ROUTER_TIMEOUT_SECS,
            )
            return self._parse_result(response.text)
        except asyncio.TimeoutError:
            logger.warning("llm_router: timed out after %.1fs, falling back to regex", _ROUTER_TIMEOUT_SECS)
            return None
        except Exception as exc:
            logger.warning("llm_router: LLM call failed (%s), falling back to regex", exc)
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_user_message(self, event: dict, body: str) -> str:
        """Compose the classification prompt user message."""
        truncated_body = body[:_BODY_TRUNCATE_CHARS]
        room_name = event.get("room_name") or ""
        member_count = event.get("member_count", 0)
        room_type = "group" if (member_count > 2 or event.get("is_group", False)) else "dm"
        sender_id = event.get("sender_id") or event.get("sender") or "unknown"
        sender_name = event.get("sender_display_name") or sender_id
        source = event.get("source") or "unknown"

        thread_event_id = event.get("thread_event_id") or ""
        user_in_thread = bool(thread_event_id)  # active thread if thread_event_id is set
        thread_status = "active (user participating)" if user_in_thread else "new/not participating"

        return (
            f'Classify this message:\n'
            f'Body: "{truncated_body}"\n'
            f'Room: {room_name} | Type: {room_type} | Members: {member_count}\n'
            f'Sender: {sender_name} ({sender_id})\n'
            f'Thread: {thread_status}\n'
            f'Source: {source}\n\n'
            f'Respond with JSON: {{"mode": "outward|inward", "intent": "question|request|fyi|social|instruction|query", '
            f'"should_respond": true|false, "priority": "high|normal|low", "reasoning": "brief reason"}}'
        )

    def _parse_result(self, raw: str) -> RouterResult | None:
        """Parse LLM JSON response into RouterResult. Returns None if unparseable."""
        text = raw.strip()

        # Strip markdown fences if the model wrapped the response
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence:
            text = fence.group(1).strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("llm_router: failed to parse JSON response: %s | raw=%r", exc, raw[:200])
            return None

        mode = str(data.get("mode", "")).strip()
        intent = str(data.get("intent", "")).strip()
        priority = str(data.get("priority", "normal")).strip()
        reasoning = str(data.get("reasoning", "")).strip()
        should_respond = bool(data.get("should_respond", True))

        # Validate expected values to catch hallucinated outputs
        valid_modes = {"outward", "inward"}
        valid_intents = {"question", "request", "fyi", "social", "instruction", "query"}
        valid_priorities = {"high", "normal", "low"}

        if mode not in valid_modes or intent not in valid_intents or priority not in valid_priorities:
            logger.warning(
                "llm_router: unexpected classification values mode=%r intent=%r priority=%r",
                mode, intent, priority,
            )
            return None

        return RouterResult(
            mode=mode,
            intent=intent,
            should_respond=should_respond,
            priority=priority,
            reasoning=reasoning,
        )

    @staticmethod
    def _load_prompt() -> str:
        """Load the router system prompt from prompts/router_prompt.md."""
        prompt_path = Path(__file__).parent / "prompts" / "router_prompt.md"
        try:
            return prompt_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.error("llm_router: cannot load router_prompt.md: %s", exc)
            return None
