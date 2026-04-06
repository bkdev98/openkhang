"""System prompt assembly for the dual-mode agent.

Loads base system prompts from prompts/ directory, injects RAG memories,
style examples (outward), and conversation context.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
PERSONA_PATH = Path(__file__).parent.parent.parent / "config" / "persona.yaml"


class PromptBuilder:
    """Build the messages list for an LLM call.

    Loads outward_system.md / inward_system.md once and caches them.
    Thread-safe for reads after initial load.
    """

    def __init__(self) -> None:
        self._outward_template: Optional[str] = None
        self._inward_template: Optional[str] = None
        self._persona: Optional[dict] = None

    def build(
        self,
        mode: str,
        intent: str,
        memories: list[dict],
        sender_context: list[dict],
        event: dict,
        style_examples: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Build messages list for LLM call.

        Args:
            mode: 'outward' or 'inward'.
            intent: Classified intent label.
            memories: RAG results from memory client (list of {memory, score, ...}).
            sender_context: Related memories about the sender.
            event: The original event dict (must have 'body', optionally 'sender_id',
                   'room_name', 'thread_event_id').
            style_examples: Optional few-shot examples for outward mode.

        Returns:
            List of {role, content} dicts ready for LLMClient.generate().
        """
        if mode == "outward":
            system = self._build_outward_system(memories, sender_context, style_examples)
        else:
            system = self._build_inward_system(memories, sender_context)

        user_content = self._build_user_message(event, intent, mode)

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    # ------------------------------------------------------------------
    # System prompt builders
    # ------------------------------------------------------------------

    def _build_outward_system(
        self,
        memories: list[dict],
        sender_context: list[dict],
        style_examples: Optional[list[dict]],
    ) -> str:
        template = self._load_outward_template()
        persona_block = self._format_persona()

        context_block = self._format_memories(memories, label="Relevant context")
        sender_block = self._format_memories(sender_context, label="About this person")
        style_block = self._format_style_examples(style_examples)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        parts = [template]
        if persona_block:
            parts.append(persona_block)
        parts.append(f"\n## Current time\n{now}")
        if style_block:
            parts.append(style_block)
        if context_block:
            parts.append(context_block)
        if sender_block:
            parts.append(sender_block)

        return "\n\n".join(parts)

    def _build_inward_system(
        self,
        memories: list[dict],
        sender_context: list[dict],
    ) -> str:
        template = self._load_inward_template()

        context_block = self._format_memories(memories, label="Work context")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        parts = [template, f"\n## Current time\n{now}"]
        if context_block:
            parts.append(context_block)

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # User message builder
    # ------------------------------------------------------------------

    def _build_user_message(self, event: dict, intent: str, mode: str) -> str:
        body = event.get("body", "").strip()
        sender_id = event.get("sender_id", "unknown")
        room_name = event.get("room_name", "")

        # Use readable name: prefer room_name sender context over raw numeric ID
        sender_display = sender_id
        # Strip googlechat_ prefix and numeric IDs for readability
        if sender_display.startswith("@googlechat_"):
            sender_display = sender_display.split(":")[0].replace("@googlechat_", "")
        # If still a raw number, label as "a colleague"
        if sender_display.isdigit():
            sender_display = "a colleague"

        if mode == "outward":
            header = f"[Message from {sender_display}"
            if room_name:
                header += f" in {room_name}"
            header += f" | intent: {intent}]"
            return f"{header}\n\n{body}"
        else:
            return f"[intent: {intent}]\n\n{body}"

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_memories(self, memories: list[dict], label: str) -> str:
        """Format RAG results as a <context> block."""
        if not memories:
            return ""

        lines = [f"## {label}\n<context>"]
        for item in memories:
            # Mem0 result shape: {memory: str, score: float, metadata: dict}
            mem_text = item.get("memory") or item.get("text") or str(item)
            score = item.get("score", 0.0)
            lines.append(f"- [{score:.2f}] {mem_text}")
        lines.append("</context>")
        return "\n".join(lines)

    def _format_persona(self) -> str:
        """Load persona.yaml and format as identity override block."""
        persona = self._load_persona()
        if not persona:
            return ""

        lines = ["## Identity (from persona.yaml — overrides defaults above)"]
        lines.append(f"- Name: {persona.get('name', 'Unknown')}")
        lines.append(f"- Role: {persona.get('role', 'Engineer')}")
        lines.append(f"- Company: {persona.get('company', '')}")
        lines.append(f"- Team: {persona.get('team', '')}")

        facts = persona.get("identity_facts", [])
        if facts:
            lines.append("\n### Key facts about you")
            for fact in facts:
                lines.append(f"- {fact}")

        never = persona.get("never_do", [])
        if never:
            lines.append("\n### NEVER do these (hard rules)")
            for rule in never:
                lines.append(f"- {rule}")

        address = persona.get("address_rules", {})
        if address:
            lines.append("\n### Vietnamese form of address (xưng hô) — CRITICAL")
            lines.append(f"- Default: call others \"{address.get('default_other', 'anh/chị')}\" when you have no history about their seniority")
            lines.append(f"- Refer to yourself as \"{address.get('default_self', 'mình')}\"")
            lines.append("- If 'About this person' context below reveals seniority, adjust accordingly:")
            lines.append("  - Junior colleague → call them \"em\", refer to self as \"anh\"")
            lines.append("  - Same level → call them by name or \"bạn\", refer to self as \"mình\"")
            lines.append("  - Senior/manager → call them \"anh/chị\", refer to self as \"em\"")
            if address.get("never_assume_tu"):
                lines.append("- NEVER use \"tao/mày\" or overly casual forms")

        phrases = persona.get("uncertainty_phrases", {})
        if phrases:
            lines.append("\n### When uncertain, use one of these:")
            for lang, plist in phrases.items():
                for p in plist:
                    lines.append(f"- ({lang}) \"{p}\"")

        return "\n".join(lines)

    def _load_persona(self) -> dict:
        """Load persona.yaml. Re-reads from disk each time (no cache) so edits take effect on next request."""
        try:
            text = PERSONA_PATH.read_text(encoding="utf-8")
            return yaml.safe_load(text) or {}
        except FileNotFoundError:
            logger.warning("persona.yaml not found at %s", PERSONA_PATH)
            return {}
        except yaml.YAMLError as exc:
            logger.error("Failed to parse persona.yaml: %s", exc)
            return {}

    def _format_style_examples(self, examples: Optional[list[dict]]) -> str:
        """Format few-shot style examples for outward mode."""
        if not examples:
            return ""

        lines = ["## Your message style (examples of how you write)\n<style_examples>"]
        for ex in examples[:10]:  # cap at 10 to stay within token budget
            msg = ex.get("body") or ex.get("text") or ""
            if msg:
                lines.append(f"- {msg}")
        lines.append("</style_examples>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Template loaders (cached after first read)
    # ------------------------------------------------------------------

    def _load_outward_template(self) -> str:
        if self._outward_template is None:
            self._outward_template = self._read_prompt("outward_system.md")
        return self._outward_template

    def _load_inward_template(self) -> str:
        if self._inward_template is None:
            self._inward_template = self._read_prompt("inward_system.md")
        return self._inward_template

    def _read_prompt(self, filename: str) -> str:
        path = PROMPTS_DIR / filename
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            logger.error("Prompt file not found: %s", path)
            return f"# Missing prompt: {filename}"
