"""ReAct loop for Claude tool_use: call LLM → execute tools → re-feed results → repeat.

Implements the tool-calling iteration pattern for inward mode.
Outward mode MUST NOT use this — it stays deterministic for safety.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10
LOOP_TIMEOUT_SECONDS = 120


@dataclass
class ToolCallRecord:
    """Record of a single tool call made during the loop."""

    tool_name: str
    tool_input: dict
    result: Any
    success: bool


@dataclass
class ToolCallingResult:
    """Final output of the tool-calling loop."""

    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    iterations: int = 0
    tokens_used: int = 0
    model_used: str = ""


async def run_tool_calling_loop(
    llm_client: Any,
    messages: list[dict],
    tools: list[dict],
    tool_executor: Callable,
    max_iterations: int = MAX_ITERATIONS,
    model: str | None = None,
    temperature: float = 0.5,
    max_tokens: int = 4096,
) -> ToolCallingResult:
    """Run ReAct loop: LLM with tools → execute tool_use blocks → re-feed results → repeat.

    Args:
        llm_client: LLMClient instance — must implement generate_with_tools().
        messages: Conversation messages in {role, content} format (mutated in-place).
        tools: Claude-format tool definitions from registry.list_descriptions().
        tool_executor: Async callable matching registry.execute(name, **kwargs) → ToolResult.
        max_iterations: Hard cap on iterations (default 3).
        model: Override model ID; None uses provider default.
        temperature: Sampling temperature (0.5 for inward).
        max_tokens: Max tokens per LLM call.

    Returns:
        ToolCallingResult with final text and all tool call records.
    """
    all_tool_calls: list[ToolCallRecord] = []
    total_tokens = 0
    model_used = ""
    text = ""
    t0 = time.monotonic()

    for iteration in range(max_iterations):
        # Guard against runaway loops
        if time.monotonic() - t0 > LOOP_TIMEOUT_SECONDS:
            logger.warning("Tool-calling loop timed out after %ds", LOOP_TIMEOUT_SECONDS)
            break

        # Call LLM with tool definitions
        response = await llm_client.generate_with_tools(
            messages=messages,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if not isinstance(response, dict):
            raise TypeError(
                f"generate_with_tools must return a dict, got {type(response).__name__}"
            )

        total_tokens += response.get("tokens_used", 0)
        model_used = response.get("model_used", "")
        tool_uses = response.get("tool_uses", [])
        text = response.get("text", "")

        if not tool_uses:
            # LLM returned text with no tool calls — done
            return ToolCallingResult(
                text=text,
                tool_calls=all_tool_calls,
                iterations=iteration + 1,
                tokens_used=total_tokens,
                model_used=model_used,
            )

        # Append assistant message containing the tool_use blocks
        messages.append({"role": "assistant", "content": response["raw_content"]})

        # Execute each tool and collect results
        tool_results = []
        for tu in tool_uses:
            tool_name = tu["name"]
            tool_input = tu["input"]

            result = await tool_executor(tool_name, **tool_input)
            record = ToolCallRecord(
                tool_name=tool_name,
                tool_input=tool_input,
                result=result.data if result.success else result.error,
                success=result.success,
            )
            all_tool_calls.append(record)
            logger.debug(
                "Tool '%s' called (success=%s): %s",
                tool_name, result.success, record.result,
            )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": str(result.data) if result.success else f"Error: {result.error}",
            })

        # Re-feed tool results as a user message for next iteration
        messages.append({"role": "user", "content": tool_results})

    # Exhausted iterations without a final text-only response
    logger.warning("Tool-calling loop exhausted %d iterations", max_iterations)
    return ToolCallingResult(
        text=text or "I wasn't able to complete the request within the allowed steps.",
        tool_calls=all_tool_calls,
        iterations=max_iterations,
        tokens_used=total_tokens,
        model_used=model_used,
    )
