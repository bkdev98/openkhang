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
        chat_history: Optional[list[dict]] = None,
        room_messages: Optional[list[dict]] = None,
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
            chat_history: Optional prior conversation turns for inward mode.
                Each entry: {"role": "user"|"assistant", "content": str}.
            room_messages: Optional recent room messages for outward mode context.
                Each entry: {"sender": str, "body": str, "created_at": str}.

        Returns:
            List of {role, content} dicts ready for LLMClient.generate().
        """
        if mode == "outward":
            system = self._build_outward_system(memories, sender_context, style_examples, room_messages)
        else:
            system = self._build_inward_system(memories, sender_context)

        user_content = self._build_user_message(event, intent, mode)

        messages = [{"role": "system", "content": system}]

        # Inject prior conversation turns (inward mode session history)
        # Only allow user/assistant roles to prevent system prompt injection
        if chat_history:
            for turn in chat_history:
                if turn.get("role") in ("user", "assistant"):
                    messages.append(turn)

        messages.append({"role": "user", "content": user_content})
        return messages

    # ------------------------------------------------------------------
    # System prompt builders
    # ------------------------------------------------------------------

    def _build_outward_system(
        self,
        memories: list[dict],
        sender_context: list[dict],
        style_examples: Optional[list[dict]],
        room_messages: Optional[list[dict]] = None,
    ) -> str:
        template = self._render_template(self._load_outward_template())

        context_block = self._format_memories(memories, label="Relevant context")
        sender_block = self._format_memories(sender_context, label="About this person")
        style_block = self._format_style_examples(style_examples)
        room_block = self._format_room_messages(room_messages)
        addressing_block = self._format_addressing_patterns()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        parts = [template, f"\n## Current time\n{now}"]
        if addressing_block:
            parts.append(addressing_block)
        if style_block:
            parts.append(style_block)
        if room_block:
            parts.append(room_block)
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
        template = self._render_template(self._load_inward_template())

        context_block = self._format_memories(memories, label="Work context")
        sender_block = self._format_memories(sender_context, label="About the person asking")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        parts = [template, f"\n## Current time\n{now}"]
        if sender_block:
            parts.append(sender_block)
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

        # Prefer sender_display_name (resolved from Matrix member events) over raw IDs
        sender_display = event.get("sender_display_name", "")
        if not sender_display:
            sender_display = sender_id
            if sender_display.startswith("@googlechat_"):
                sender_display = sender_display.split(":")[0].replace("@googlechat_", "")
            # If still a raw number, use room_name as fallback (for DMs, room_name = person's name)
            if sender_display.isdigit() and room_name:
                sender_display = room_name
            elif sender_display.isdigit():
                sender_display = "colleague"

        if mode == "outward":
            header = f"[Message from {sender_display}"
            if room_name and room_name != sender_display:
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

    def _format_room_messages(self, messages: Optional[list[dict]]) -> str:
        """Format recent room messages as conversation history block."""
        if not messages:
            return ""

        lines = ["## Recent conversation in this room (oldest → newest)\n<conversation>"]
        for msg in messages:
            sender = msg.get("sender", "unknown")
            # Clean up bridge sender IDs for readability
            if sender.startswith("@googlechat_"):
                sender = sender.split(":")[0].replace("@googlechat_", "")
            if sender.isdigit():
                sender = "colleague"
            body = (msg.get("body", ""))[:200]  # truncate long messages
            lines.append(f"- {sender}: {body}")
        lines.append("</conversation>")
        return "\n".join(lines)

    def _render_template(self, template: str) -> str:
        """Replace {placeholders} in a prompt template with persona.yaml values.

        Handles scalar fields ({name}, {role}) and block fields
        ({never_do_block}, {uncertainty_block}, {address_rules_block}).
        """
        persona = self._load_persona()
        style = persona.get("style", {})
        address = persona.get("address_rules", {})

        # Scalar replacements
        replacements = {
            "{name}": persona.get("name", "User"),
            "{role}": persona.get("role", "Engineer"),
            "{company}": persona.get("company", ""),
            "{team}": persona.get("team", ""),
            "{languages}": ", ".join(persona.get("languages", ["English"])),
            "{formality}": style.get("formality", "professional"),
            "{emoji_usage}": style.get("emoji_usage", "minimal"),
            "{response_length}": style.get("response_length", "concise"),
        }

        # Block: never_do + identity_facts
        never_lines = []
        for rule in persona.get("never_do", []):
            never_lines.append(f"- NEVER {rule}")
        for fact in persona.get("identity_facts", []):
            never_lines.append(f"- Context: {fact}")
        replacements["{never_do_block}"] = "\n".join(never_lines) if never_lines else "- Follow standard professional guidelines"

        # Block: uncertainty phrases
        uncertainty_lines = []
        for lang, phrases in persona.get("uncertainty_phrases", {}).items():
            for p in phrases:
                uncertainty_lines.append(f"- ({lang}) \"{p}\"")
        replacements["{uncertainty_block}"] = "\n".join(uncertainty_lines) if uncertainty_lines else '- "Let me check and get back to you"'

        # Block: address rules (Vietnamese xưng hô)
        addr_lines = []
        if address:
            addr_lines.append(f"- Default: call others \"{address.get('default_other', 'anh/chị')}\" when unsure of seniority")
            addr_lines.append(f"- Refer to yourself as \"{address.get('default_self', 'mình')}\"")
            addr_lines.append("- Adjust based on sender context:")
            addr_lines.append("  - Junior → call \"em\", self \"anh\"")
            addr_lines.append("  - Same level → name or \"bạn\", self \"mình\"")
            addr_lines.append("  - Senior/manager → \"anh/chị\", self \"em\"")
            if address.get("never_assume_tu"):
                addr_lines.append("- NEVER use \"tao/mày\" or overly casual forms")
        replacements["{address_rules_block}"] = "\n".join(addr_lines) if addr_lines else "- Use polite, professional address forms"

        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        return result

    def _format_addressing_patterns(self) -> str:
        """Format known addressing patterns from real conversations."""
        addr_patterns = self._load_addressing_patterns()
        if not addr_patterns:
            return ""

        lines = ["## Known addressing (from your real messages)"]
        for person, terms in addr_patterns.items():
            if person == "_default_tone":
                continue
            unique = list(set(terms))
            lines.append(f"- {person}: you call them \"{'/'.join(unique)}\"")
        if "_default_tone" in addr_patterns:
            from collections import Counter
            tone = Counter(addr_patterns["_default_tone"])
            top = tone.most_common(3)
            lines.append(f"- Your default tone: {', '.join(f'{t} ({n}x)' for t, n in top)}")
        return "\n".join(lines)

    def _load_addressing_patterns(self) -> dict:
        """Load addressing_patterns.json (re-reads each time for hot reload)."""
        import json
        addr_path = PERSONA_PATH.parent / "addressing_patterns.json"
        try:
            return json.loads(addr_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

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
