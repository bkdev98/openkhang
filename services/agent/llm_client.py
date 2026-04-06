"""LLM client with multi-provider support (Gemini primary, Claude fallback).

Handles API calls, retries, and structured output extraction for the agent pipeline.
Prefers Gemini 2.5 Flash (free tier / high rate limits) when GEMINI_API_KEY is set.
Falls back to Claude API when only ANTHROPIC_API_KEY is available.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Default models per provider
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"

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
    """Multi-provider LLM client: Gemini primary, Claude fallback.

    Usage:
        # Auto-selects provider based on available keys
        client = LLMClient(gemini_api_key="...", anthropic_api_key="...")
        response = await client.generate(messages, temperature=0.3)
    """

    def __init__(
        self,
        gemini_api_key: str = "",
        anthropic_api_key: str = "",
        *,
        # Legacy: accept api_key= for backward compat with agent_relay
        api_key: str = "",
    ) -> None:
        self._gemini_key = gemini_api_key
        self._anthropic_key = anthropic_api_key or api_key
        self._provider: str = ""

        if self._gemini_key:
            from google import genai
            self._gemini_client = genai.Client(api_key=self._gemini_key)
            self._provider = "gemini"
            logger.info("LLMClient: using Gemini (%s)", DEFAULT_GEMINI_MODEL)
        elif self._anthropic_key:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self._anthropic_key)
            self._provider = "claude"
            logger.info("LLMClient: using Claude (%s)", DEFAULT_CLAUDE_MODEL)
        else:
            raise ValueError("No LLM API key provided (need GEMINI_API_KEY or ANTHROPIC_API_KEY)")

    async def generate(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        require_structured: bool = True,
    ) -> LLMResponse:
        """Call LLM and return a parsed LLMResponse.

        Args:
            messages: List of {role, content} dicts. System prompt entry must
                      have role='system'; it is extracted and sent separately.
            model: Override model ID. If None, uses provider default.
            temperature: 0.3 for outward (consistent style), 0.5 for inward.
            max_tokens: Maximum tokens in response.
            require_structured: If True, appends JSON output instruction to system prompt.
        """
        if self._provider == "gemini":
            return await self._generate_gemini(messages, model, temperature, max_tokens, require_structured)
        return await self._generate_claude(messages, model, temperature, max_tokens, require_structured)

    # ------------------------------------------------------------------
    # Gemini provider
    # ------------------------------------------------------------------

    async def _generate_gemini(
        self,
        messages: list[dict],
        model: str | None,
        temperature: float,
        max_tokens: int,
        require_structured: bool,
    ) -> LLMResponse:
        """Generate via Google Gemini API."""
        from google.genai import types

        model_id = model or DEFAULT_GEMINI_MODEL
        system_prompt: Optional[str] = None
        convo_contents: list[types.Content] = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                role = "model" if msg["role"] == "assistant" else "user"
                convo_contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))

        if require_structured:
            system_prompt = (system_prompt or "") + "\n\n" + STRUCTURED_OUTPUT_INSTRUCTION

        t0 = time.monotonic()
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            resp = await self._gemini_client.aio.models.generate_content(
                model=model_id,
                contents=convo_contents,
                config=config,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            raw_text = resp.text or ""
            # Gemini usage metadata
            tokens_used = 0
            if resp.usage_metadata:
                tokens_used = (resp.usage_metadata.prompt_token_count or 0) + (resp.usage_metadata.candidates_token_count or 0)

        except Exception as exc:
            raise RuntimeError(f"Gemini API error: {exc}") from exc

        return self._parse_response(
            raw_text=raw_text,
            model_used=model_id,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            structured=require_structured,
        )

    # ------------------------------------------------------------------
    # Claude provider (fallback)
    # ------------------------------------------------------------------

    async def _generate_claude(
        self,
        messages: list[dict],
        model: str | None,
        temperature: float,
        max_tokens: int,
        require_structured: bool,
    ) -> LLMResponse:
        """Generate via Anthropic Claude API."""
        import anthropic

        model_id = model or DEFAULT_CLAUDE_MODEL
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
                "model": model_id,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": convo_messages,
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            resp = await self._anthropic_client.messages.create(**kwargs)
            latency_ms = int((time.monotonic() - t0) * 1000)
            raw_text = resp.content[0].text if resp.content else ""
            tokens_used = resp.usage.input_tokens + resp.usage.output_tokens

        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(f"Claude API connection failed: {exc}") from exc

        return self._parse_response(
            raw_text=raw_text,
            model_used=model_id,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            structured=require_structured,
        )

    # ------------------------------------------------------------------
    # Response parsing (shared)
    # ------------------------------------------------------------------

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
            return LLMResponse(
                text=raw_text.strip(),
                confidence=0.3,
                evidence=[],
                model_used=model_used,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                raw=raw_text,
            )
