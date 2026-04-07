"""LLM client with multi-provider support.

Provider priority: Meridian (Max subscription, $0) > OpenRouter > Claude API (paid fallback).
Meridian proxies Claude via local HTTP endpoint, billing against Max subscription.
OpenRouter provides access to multiple models (Gemini, GPT, Claude) with per-token cost.

Tool-calling is handled by the Claude Agent SDK (sdk_agent_runner.py).
This client is used only for single-call completions (outward mode, router).
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
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_MERIDIAN_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4-6"

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
    """Multi-provider LLM client: Meridian > OpenRouter > Claude API.

    Used for single-call completions only. Tool-calling is handled by
    the SDK agent runner.

    Usage:
        client = LLMClient(meridian_url="http://127.0.0.1:3456")
        response = await client.generate(messages, temperature=0.3)
    """

    def __init__(
        self,
        meridian_url: str = "",
        anthropic_api_key: str = "",
        openrouter_api_key: str = "",
        openrouter_model: str = "",
        *,
        # Legacy: accept api_key= for backward compat with agent_relay
        api_key: str = "",
    ) -> None:
        self._anthropic_key = anthropic_api_key or api_key
        self._meridian_url = meridian_url.rstrip("/") if meridian_url else ""
        self._openrouter_key = openrouter_api_key
        self._openrouter_model = openrouter_model or DEFAULT_OPENROUTER_MODEL
        self._provider: str = ""

        # Priority: Meridian ($0) > OpenRouter (per-token) > Claude API (per-token)
        if self._meridian_url:
            self._provider = "meridian"
            logger.info("LLMClient: using Meridian at %s", self._meridian_url)
        elif self._openrouter_key:
            self._provider = "openrouter"
            logger.info("LLMClient: using OpenRouter (%s)", self._openrouter_model)
        elif self._anthropic_key:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self._anthropic_key)
            self._provider = "claude"
            logger.info("LLMClient: using Claude (%s)", DEFAULT_CLAUDE_MODEL)
        else:
            raise ValueError(
                "No LLM provider configured "
                "(need MERIDIAN_URL, OPENROUTER_API_KEY, or ANTHROPIC_API_KEY)"
            )

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
        if self._provider == "meridian":
            return await self._generate_meridian(messages, model, temperature, max_tokens, require_structured)
        if self._provider == "openrouter":
            return await self._generate_openrouter(messages, model, temperature, max_tokens, require_structured)
        return await self._generate_claude(messages, model, temperature, max_tokens, require_structured)

    # ------------------------------------------------------------------
    # Meridian provider (Claude via Max subscription proxy)
    # ------------------------------------------------------------------

    async def _generate_meridian(
        self,
        messages: list[dict],
        model: str | None,
        temperature: float,
        max_tokens: int,
        require_structured: bool,
    ) -> LLMResponse:
        """Generate via Meridian proxy (OpenAI-compatible endpoint).

        Meridian runs locally and routes requests through Claude Agent SDK,
        billing against Max subscription instead of API credits.
        Uses httpx (transitive dep of anthropic SDK) for async HTTP.
        """
        return await self._generate_openai_compat(
            base_url=self._meridian_url,
            api_key="placeholder",
            model=model or DEFAULT_MERIDIAN_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            require_structured=require_structured,
            provider_label="meridian",
        )

    # ------------------------------------------------------------------
    # OpenRouter provider (multi-model, per-token)
    # ------------------------------------------------------------------

    async def _generate_openrouter(
        self,
        messages: list[dict],
        model: str | None,
        temperature: float,
        max_tokens: int,
        require_structured: bool,
    ) -> LLMResponse:
        """Generate via OpenRouter API (OpenAI-compatible endpoint)."""
        return await self._generate_openai_compat(
            base_url="https://openrouter.ai/api",
            api_key=self._openrouter_key,
            model=model or self._openrouter_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            require_structured=require_structured,
            provider_label="openrouter",
        )

    # ------------------------------------------------------------------
    # Shared OpenAI-compatible generation (Meridian + OpenRouter)
    # ------------------------------------------------------------------

    async def _generate_openai_compat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        require_structured: bool,
        provider_label: str,
    ) -> LLMResponse:
        """Generate via any OpenAI-compatible endpoint."""
        import httpx

        system_prompt: Optional[str] = None
        convo_messages: list[dict] = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                convo_messages.append(msg)

        if require_structured:
            system_prompt = (system_prompt or "") + "\n\n" + STRUCTURED_OUTPUT_INSTRUCTION

        if system_prompt:
            convo_messages.insert(0, {"role": "system", "content": system_prompt})

        payload = {
            "model": model,
            "messages": convo_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{base_url}/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()

            latency_ms = int((time.monotonic() - t0) * 1000)
            raw_text = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
            # Some providers may not report usage — estimate from content length
            if not tokens_used:
                prompt_chars = sum(len(m.get("content", "")) for m in convo_messages)
                tokens_used = (prompt_chars + len(raw_text)) // 4  # ~4 chars/token

        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"{provider_label} not reachable at {base_url}."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"{provider_label} error {exc.response.status_code}: {exc.response.text}"
            ) from exc

        return self._parse_response(
            raw_text=raw_text,
            model_used=f"{provider_label}/{model}",
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            structured=require_structured,
        )

    # ------------------------------------------------------------------
    # Claude API provider (paid fallback)
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
            # Last resort: try to extract reply_text with regex
            rt_match = re.search(r'"reply_text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
            if rt_match:
                extracted = rt_match.group(1).replace("\\n", "\n").replace('\\"', '"')
                return LLMResponse(
                    text=extracted,
                    confidence=0.3,
                    evidence=[],
                    model_used=model_used,
                    tokens_used=tokens_used,
                    latency_ms=latency_ms,
                    raw=raw_text,
                )
            return LLMResponse(
                text=raw_text.strip(),
                confidence=0.3,
                evidence=[],
                model_used=model_used,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                raw=raw_text,
            )
