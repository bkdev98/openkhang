"""Unified agent loop — single execution path for both outward and inward modes.

Mode differences (prompt, temperature, tool access, iterations, timeout) are
config-driven via ModeConfig presets, not separate code paths.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ModeConfig:
    """Configuration preset for an agent execution mode."""
    system_prompt_file: str       # "outward_system.md" | "inward_system.md"
    temperature: float
    max_tokens: int
    use_tools: bool               # False = single LLM call, True = ReAct loop
    tool_blacklist: set[str] = field(default_factory=set)
    require_structured: bool = False
    max_iterations: int = 1
    timeout_seconds: int = 60

    @classmethod
    def outward(cls) -> ModeConfig:
        return cls(
            system_prompt_file="outward_system.md",
            temperature=0.3,
            max_tokens=4096,
            use_tools=False,
            require_structured=True,
            max_iterations=1,
            timeout_seconds=60,
        )

    @classmethod
    def inward(cls) -> ModeConfig:
        return cls(
            system_prompt_file="inward_system.md",
            temperature=0.5,
            max_tokens=4096,
            use_tools=True,
            tool_blacklist={"create_draft", "send_message"},
            require_structured=False,
            max_iterations=10,
            timeout_seconds=120,
        )


@dataclass
class AgentLoopResult:
    """Result from a single agent loop execution."""
    text: str
    confidence: float = 0.0
    evidence: str = ""
    tokens_used: int = 0
    model_used: str = ""
    latency_ms: int = 0
    tool_calls: list = field(default_factory=list)
    iterations: int = 0
    # For structured output (outward mode)
    raw: str = ""


class AgentLoop:
    """Unified execution loop for both outward and inward modes."""

    async def run(
        self,
        config: ModeConfig,
        messages: list[dict],
        llm_client: Any,
        tools: Any = None,
    ) -> AgentLoopResult:
        """Execute agent loop with mode-specific config.

        Args:
            config: ModeConfig preset (outward or inward)
            messages: System + user messages from prompt builder
            llm_client: LLMClient instance
            tools: ToolRegistry instance (only used when config.use_tools=True)
        """
        if config.use_tools and tools:
            return await self._run_tool_loop(config, messages, llm_client, tools)
        else:
            return await self._run_single(config, messages, llm_client)

    async def _run_single(self, config: ModeConfig, messages: list[dict], llm: Any) -> AgentLoopResult:
        """Single LLM call — used for outward mode (deterministic, structured output)."""
        response = await llm.generate(
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            require_structured=config.require_structured,
        )
        return AgentLoopResult(
            text=response.text,
            confidence=response.confidence,
            evidence=response.evidence,
            tokens_used=response.tokens_used,
            model_used=response.model_used,
            latency_ms=response.latency_ms,
            raw=response.raw,
            iterations=1,
        )

    async def _run_tool_loop(self, config: ModeConfig, messages: list[dict], llm: Any, tools: Any) -> AgentLoopResult:
        """ReAct tool-calling loop — used for inward mode (autonomous reasoning)."""
        from .tool_calling_loop import run_tool_calling_loop

        # Filter tools based on blacklist
        tool_defs = [
            t for t in tools.list_descriptions()
            if t["name"] not in config.tool_blacklist
        ]

        try:
            # Inner timeout slightly lower so it fires before outer, producing clean exit
            inner_timeout = max(config.timeout_seconds - 10, 30)
            result = await asyncio.wait_for(
                run_tool_calling_loop(
                    llm_client=llm,
                    messages=messages,
                    tools=tool_defs,
                    tool_executor=tools.execute,
                    max_iterations=config.max_iterations,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                ),
                timeout=inner_timeout,
            )
            return AgentLoopResult(
                text=result.text,
                tokens_used=result.tokens_used,
                model_used=result.model_used,
                tool_calls=result.tool_calls,
                iterations=result.iterations,
            )
        except asyncio.TimeoutError:
            logger.warning("Agent loop timed out after %ds", config.timeout_seconds)
            return AgentLoopResult(
                text="I ran out of time processing this request. Please try a simpler question or rephrase.",
                iterations=config.max_iterations,
            )
