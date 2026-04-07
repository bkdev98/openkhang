"""Agent loop — execution path for outward mode (single LLM call).

Inward mode tool-calling is handled by SDKAgentRunner (sdk_agent_runner.py).
This module provides ModeConfig presets and the single-call path for outward.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    """Record of a single tool call made during the agent loop."""

    tool_name: str
    tool_input: dict
    result: Any
    success: bool


@dataclass
class ModeConfig:
    """Configuration preset for an agent execution mode."""
    system_prompt_file: str       # "outward_system.md" | "inward_system.md"
    temperature: float
    max_tokens: int
    use_tools: bool               # False = single LLM call, True = SDK agent
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
            tool_blacklist={"send_message"},
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
    """Execution loop for outward mode (single LLM call).

    Inward mode tool-calling is now handled by SDKAgentRunner.
    """

    async def run(
        self,
        config: ModeConfig,
        messages: list[dict],
        llm_client: Any,
        tools: Any = None,
    ) -> AgentLoopResult:
        """Execute agent loop with mode-specific config.

        Args:
            config: ModeConfig preset (outward only)
            messages: System + user messages from prompt builder
            llm_client: LLMClient instance
            tools: Unused — kept for interface compat with OutwardReplySkill
        """
        if config.use_tools:
            raise NotImplementedError(
                "Tool-calling is now handled by SDKAgentRunner. "
                "Use sdk_agent_runner.py for inward mode."
            )
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
