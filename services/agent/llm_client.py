"""LLM client with Claude API primary and structured response parsing.

Handles API calls, retries, and structured output extraction for the agent pipeline.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

# Default model — Claude Sonnet (fast + capable for chat replies)
DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Appended to system prompt to request structured JSON output
STRUCTURED_OUTPUT_INSTRUCTION = """
Respond in JSON with this exact structure:
{
  "reply_text": "<your reply here>",
  "confidence": <float 0.0-1.0>,
  "evidence": [<list of facts from context you relied on>]
}
confidence: 1.0 = very sure, 0.0 = guessing. Be honest.
If you have no relevant context to ground your reply, set confidence <= 0.4.
"""


@dataclass
class LLMResponse:
    """Parsed response from an LLM call."""

    text: str
    confidence: float
    evidence: list[str]
    model_used: str
    tokens_used: int
    latency_ms: int
    raw: str = ""


class LLMClient:
    """Claude API client with structured output parsing.

    Usage:
        client = LLMClient(api_key="sk-ant-...")
        response = await client.generate(messages, temperature=0.3)
    """

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        messages: list[dict],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        require_structured: bool = True,
    ) -> LLMResponse:
        """Call Claude API and return a parsed LLMResponse.

        Args:
            messages: List of {role, content} dicts. System prompt entry must
                      have role='system'; it is extracted and sent separately.
            model: Claude model ID.
            temperature: 0.3 for outward (consistent style), 0.5 for inward.
            max_tokens: Maximum tokens in response.
            require_structured: If True, appends JSON output instruction to system prompt.

        Returns:
            LLMResponse with text, confidence, evidence, model, tokens, latency.

        Raises:
            RuntimeError: If API call fails.
        """
        system_prompt: Optional[str] = None
        convo_messages: list[dict] = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                convo_messages.append(msg)

        if require_structured:
            system_prompt = (system_prompt or "") + "\n\n" + STRUCTURED_OUTPUT_INSTRUCTION

        t0 = time.monotonic()
        try:
            kwargs: dict = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": convo_messages,
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            resp = await self._client.messages.create(**kwargs)

            latency_ms = int((time.monotonic() - t0) * 1000)
            raw_text = resp.content[0].text if resp.content else ""
            tokens_used = resp.usage.input_tokens + resp.usage.output_tokens

        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(f"Claude API connection failed: {exc}") from exc

        return self._parse_response(
            raw_text=raw_text,
            model_used=model,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            structured=require_structured,
        )

    def _parse_response(
        self,
        raw_text: str,
        model_used: str,
        tokens_used: int,
        latency_ms: int,
        structured: bool,
    ) -> LLMResponse:
        """Parse raw LLM text into LLMResponse.

        Attempts JSON parse for structured mode; falls back to plain text with
        neutral confidence so the pipeline can still route the response.
        """
        if not structured:
            return LLMResponse(
                text=raw_text.strip(),
                confidence=0.5,
                evidence=[],
                model_used=model_used,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                raw=raw_text,
            )

        # Extract JSON block — model may wrap it in markdown code fences
        json_str = raw_text.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", json_str)
        if fence_match:
            json_str = fence_match.group(1).strip()

        try:
            data = json.loads(json_str)
            return LLMResponse(
                text=str(data.get("reply_text", "")).strip(),
                confidence=float(data.get("confidence", 0.5)),
                evidence=list(data.get("evidence", [])),
                model_used=model_used,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                raw=raw_text,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse structured LLM response: %s", exc)
            # Fallback: treat entire output as reply text, assign low confidence
            # so it always lands in draft queue rather than auto-sending.
            return LLMResponse(
                text=raw_text.strip(),
                confidence=0.3,
                evidence=[],
                model_used=model_used,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                raw=raw_text,
            )
