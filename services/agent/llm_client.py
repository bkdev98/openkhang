"""LLM client with multi-provider support.

Provider priority: Meridian (Max subscription, $0) > Claude API (paid fallback).
Meridian proxies Claude via local HTTP endpoint, billing against Max subscription.
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
    """Multi-provider LLM client: Meridian (default) > Claude API (fallback).

    Usage:
        client = LLMClient(meridian_url="http://127.0.0.1:3456")
        response = await client.generate(messages, temperature=0.3)
    """

    def __init__(
        self,
        meridian_url: str = "",
        anthropic_api_key: str = "",
        *,
        # Legacy: accept api_key= for backward compat with agent_relay
        api_key: str = "",
    ) -> None:
        self._anthropic_key = anthropic_api_key or api_key
        self._meridian_url = meridian_url.rstrip("/") if meridian_url else ""
        self._provider: str = ""

        # Priority: Meridian (Max subscription, $0 marginal) > Claude API (paid fallback)
        if self._meridian_url:
            self._provider = "meridian"
            logger.info("LLMClient: using Meridian at %s", self._meridian_url)
        elif self._anthropic_key:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=self._anthropic_key)
            self._provider = "claude"
            logger.info("LLMClient: using Claude (%s)", DEFAULT_CLAUDE_MODEL)
        else:
            raise ValueError("No LLM provider configured (need MERIDIAN_URL or ANTHROPIC_API_KEY)")

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
        return await self._generate_claude(messages, model, temperature, max_tokens, require_structured)

    async def generate_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str | None = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
    ) -> dict:
        """Call LLM with tool definitions and return raw tool-calling response.

        Used exclusively by the inward-mode tool-calling loop. Outward mode
        MUST NOT call this — it stays deterministic (no tool_use).

        Args:
            messages: Conversation messages in {role, content} format.
            tools: Claude-format tool defs from registry.list_descriptions():
                   [{"name": ..., "description": ..., "input_schema": {...}}]
            model: Override model ID. None uses provider default.
            temperature: Sampling temperature.
            max_tokens: Max tokens in response.

        Returns:
            dict with keys:
                text (str): Text portion of response (empty if only tool_use).
                tool_uses (list[dict]): [{id, name, input}] — empty if text-only.
                raw_content: Original content block list (for re-feeding to LLM).
                tokens_used (int): Total tokens consumed.
                model_used (str): Model identifier string.
        """
        if self._provider == "meridian":
            return await self._generate_with_tools_meridian(messages, tools, model, temperature, max_tokens)
        return await self._generate_with_tools_claude(messages, tools, model, temperature, max_tokens)

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
        import httpx

        model_id = model or DEFAULT_MERIDIAN_MODEL
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
            "model": model_id,
            "messages": convo_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self._meridian_url}/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": "Bearer placeholder"},
                )
                resp.raise_for_status()
                data = resp.json()

            latency_ms = int((time.monotonic() - t0) * 1000)
            raw_text = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
            # Meridian proxy may not report usage — estimate from content length
            if not tokens_used:
                prompt_chars = sum(len(m.get("content", "")) for m in convo_messages)
                tokens_used = (prompt_chars + len(raw_text)) // 4  # ~4 chars/token estimate

        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Meridian not reachable at {self._meridian_url}. "
                "Start it with: meridian"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Meridian error {exc.response.status_code}: {exc.response.text}") from exc

        return self._parse_response(
            raw_text=raw_text,
            model_used=f"meridian/{model_id}",
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            structured=require_structured,
        )

    # ------------------------------------------------------------------
    # Tool-calling: Meridian (OpenAI-compatible format)
    # ------------------------------------------------------------------

    async def _generate_with_tools_meridian(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """Generate with tools via Meridian proxy (OpenAI function-calling format).

        Converts Claude tool defs (input_schema) → OpenAI format (parameters).
        Parses tool_calls from the response choice message.
        """
        import httpx

        model_id = model or DEFAULT_MERIDIAN_MODEL
        system_prompt: Optional[str] = None
        convo_messages: list[dict] = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                convo_messages.append(msg)

        if system_prompt:
            convo_messages.insert(0, {"role": "system", "content": system_prompt})

        # Convert Claude tool format → OpenAI function format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in tools
        ]

        payload = {
            "model": model_id,
            "messages": convo_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "tools": openai_tools,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self._meridian_url}/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": "Bearer placeholder"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Meridian not reachable at {self._meridian_url}. "
                "Start it with: meridian"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Meridian error {exc.response.status_code}: {exc.response.text}"
            ) from exc

        tokens_used = data.get("usage", {}).get("total_tokens", 0)
        # Meridian proxy may not report usage — estimate from content length
        if not tokens_used:
            prompt_chars = sum(len(str(m.get("content", ""))) for m in convo_messages)
            resp_chars = len(str(data["choices"][0]["message"].get("content", "")))
            tokens_used = (prompt_chars + resp_chars) // 4
        choice_message = data["choices"][0]["message"]
        text = choice_message.get("content") or ""
        raw_tool_calls = choice_message.get("tool_calls") or []

        # Normalise OpenAI tool_calls → internal format [{id, name, input}]
        tool_uses = []
        for tc in raw_tool_calls:
            import json as _json
            fn = tc.get("function", {})
            try:
                tool_input = _json.loads(fn.get("arguments", "{}"))
            except (_json.JSONDecodeError, ValueError):
                tool_input = {}
            tool_uses.append({"id": tc["id"], "name": fn["name"], "input": tool_input})

        # Build raw_content in Claude-compatible format so it can be re-fed
        raw_content: list[dict] = []
        if text:
            raw_content.append({"type": "text", "text": text})
        for tu in tool_uses:
            raw_content.append({
                "type": "tool_use",
                "id": tu["id"],
                "name": tu["name"],
                "input": tu["input"],
            })

        return {
            "text": text,
            "tool_uses": tool_uses,
            "raw_content": raw_content,
            "tokens_used": tokens_used,
            "model_used": f"meridian/{model_id}",
        }

    # ------------------------------------------------------------------
    # Tool-calling: Claude API (Anthropic format)
    # ------------------------------------------------------------------

    async def _generate_with_tools_claude(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """Generate with tools via Anthropic Claude API (native tool_use format).

        Claude tool defs from registry are already in Anthropic format
        (input_schema key), so they are passed through directly.
        """
        import anthropic

        model_id = model or DEFAULT_CLAUDE_MODEL
        system_prompt: Optional[str] = None
        convo_messages: list[dict] = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                convo_messages.append(msg)

        try:
            kwargs: dict = {
                "model": model_id,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": convo_messages,
                "tools": tools,  # Anthropic format — matches registry.list_descriptions()
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            resp = await self._anthropic_client.messages.create(**kwargs)
            tokens_used = resp.usage.input_tokens + resp.usage.output_tokens

        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(f"Claude API connection failed: {exc}") from exc

        text = ""
        tool_uses = []
        raw_content = []

        for block in resp.content:
            if block.type == "text":
                text = block.text
                raw_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_uses.append({"id": block.id, "name": block.name, "input": block.input})
                raw_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return {
            "text": text,
            "tool_uses": tool_uses,
            "raw_content": raw_content,
            "tokens_used": tokens_used,
            "model_used": model_id,
        }

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
