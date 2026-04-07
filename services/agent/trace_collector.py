"""Request trace collector — records the full pipeline flow for observability.

Accumulates trace steps (classification, RAG, prompt, LLM call, tool calls,
confidence scoring) during request processing. Persisted to request_traces table.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Truncate large text fields to avoid bloating the DB
_MAX_PROMPT_CHARS = 12_000
_MAX_RAG_ITEMS = 20
_MAX_TOOL_RESULT_CHARS = 2_000


@dataclass
class TraceStep:
    """A single step in the request trace."""

    name: str
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.monotonic)


@dataclass
class TraceCollector:
    """Accumulates trace data during a single request's lifecycle.

    Created at pipeline entry, passed via SkillContext, saved after completion.
    """

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.monotonic)
    steps: list[TraceStep] = field(default_factory=list)

    # Top-level metadata (set by pipeline/skill)
    mode: str = ""
    channel: str = ""
    intent: str = ""
    skill_name: str = ""
    action: str = ""
    input_body: str = ""
    room_id: str = ""
    sender_id: str = ""
    confidence: float = 0.0
    tokens_used: int = 0
    latency_ms: int = 0
    error: str = ""

    def add_step(self, name: str, **data: Any) -> None:
        """Record a named step with arbitrary data."""
        self.steps.append(TraceStep(name=name, data=data))

    def record_classification(self, mode: str, intent: str) -> None:
        self.mode = mode
        self.intent = intent
        self.add_step("classification", mode=mode, intent=intent)

    def record_rag(self, memories: list[dict], label: str = "rag") -> None:
        truncated = [
            {"memory": str(m.get("memory", m.get("text", "")))[:300], "score": m.get("score", 0)}
            for m in memories[:_MAX_RAG_ITEMS]
        ]
        self.add_step(label, count=len(memories), results=truncated)

    def record_prompt(self, messages: list[dict]) -> None:
        """Record the full messages array sent to LLM (truncated)."""
        serialized = []
        total_chars = 0
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = json.dumps(content, default=str)[:_MAX_PROMPT_CHARS]
            else:
                content = str(content)
            # Truncate individual messages proportionally
            remaining = _MAX_PROMPT_CHARS - total_chars
            if remaining <= 0:
                serialized.append({"role": role, "content": f"[truncated — {len(messages) - len(serialized)} more messages]"})
                break
            truncated_content = content[:remaining]
            serialized.append({"role": role, "content": truncated_content})
            total_chars += len(truncated_content)
        self.add_step("prompt", messages=serialized, message_count=len(messages))

    def record_llm_call(
        self, model: str, tokens: int, latency_ms: int,
        temperature: float = 0.0, raw_response: str = "",
    ) -> None:
        self.tokens_used += tokens
        self.add_step(
            "llm_call",
            model=model, tokens=tokens, latency_ms=latency_ms,
            temperature=temperature,
            response_preview=raw_response[:1000] if raw_response else "",
        )

    def record_tool_call(
        self, tool_name: str, tool_input: dict, result: Any, success: bool,
    ) -> None:
        result_str = str(result)[:_MAX_TOOL_RESULT_CHARS]
        self.add_step(
            "tool_call",
            tool_name=tool_name, tool_input=tool_input,
            result=result_str, success=success,
        )

    def record_confidence(self, score: float, breakdown: dict | None = None) -> None:
        self.confidence = score
        self.add_step("confidence", score=score, breakdown=breakdown or {})

    def record_result(self, action: str, latency_ms: int, error: str = "") -> None:
        self.action = action
        self.latency_ms = latency_ms
        self.error = error
        self.add_step("result", action=action, latency_ms=latency_ms, error=error)

    def to_dict(self) -> dict:
        """Serialize trace for DB storage."""
        return {
            "trace_id": self.trace_id,
            "mode": self.mode,
            "channel": self.channel,
            "intent": self.intent,
            "skill_name": self.skill_name,
            "action": self.action,
            "input_body": self.input_body[:500],
            "room_id": self.room_id,
            "sender_id": self.sender_id,
            "confidence": self.confidence,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "steps": [{"name": s.name, "data": s.data} for s in self.steps],
        }


async def save_trace(pool: Any, trace: TraceCollector) -> None:
    """Persist trace to request_traces table (fire-and-forget)."""
    if pool is None:
        return
    try:
        data = trace.to_dict()
        await pool.execute(
            """
            INSERT INTO request_traces (id, mode, channel, intent, skill_name, action,
                input_body, room_id, sender_id, confidence, tokens_used, latency_ms,
                error, steps)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """,
            uuid.UUID(data["trace_id"]), data["mode"], data["channel"],
            data["intent"], data["skill_name"], data["action"],
            data["input_body"], data["room_id"], data["sender_id"],
            data["confidence"], data["tokens_used"], data["latency_ms"],
            data["error"], json.dumps(data["steps"], default=str),
        )
    except Exception as exc:
        logger.warning("Failed to save request trace: %s", exc)
