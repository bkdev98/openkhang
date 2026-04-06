"""Mode and intent classifier for the dual-mode agent pipeline.

Mode classification: determines if this event is outward (reply AS Khanh to colleagues)
or inward (reply AS assistant TO Khanh).

Intent classification: coarse-grained intent label used to select prompt strategy.
"""

from __future__ import annotations

import re

# Sources that trigger outward mode (acting as Khanh to colleagues)
OUTWARD_SOURCES = {"matrix", "chat", "gchat", "google_chat"}

# Sources that trigger inward mode (acting as assistant to Khanh)
INWARD_SOURCES = {"dashboard", "cli", "terminal", "api", "cron"}

# Intent: deadline/commitment keywords — high-risk, lower confidence modifier applied
DEADLINE_KEYWORDS = re.compile(
    r"\b(deadline|due date|when will|eta|by when|finish by|deliver|release date|sprint end)\b",
    re.IGNORECASE,
)

# Intent: question patterns
QUESTION_PATTERNS = re.compile(
    r"(\?$|\b(how|what|when|why|where|who|which|can you tell|do you know)\b)",
    re.IGNORECASE,
)

# Intent: request patterns
REQUEST_PATTERNS = re.compile(
    r"\b(please|can you|could you|would you|need you to|help me|send|update|fix|check|review)\b",
    re.IGNORECASE,
)

# Intent: FYI patterns
FYI_PATTERNS = re.compile(
    r"\b(fyi|heads up|just so you know|note that|for your info|letting you know|btw|by the way)\b",
    re.IGNORECASE,
)

# Intent: social patterns (greetings, thanks, emoji-only, casual chitchat)
SOCIAL_PATTERNS = re.compile(
    r"^(hi|hello|hey|good morning|good afternoon|chào|xin chào|thanks|thank you|cảm ơn|👋|😊|ok|okay|oke|noted|got it|sure|np|no problem|ack|received)[\s!.]*$",
    re.IGNORECASE,
)


class Classifier:
    """Classify events into modes and intents for the agent pipeline."""

    def classify_mode(self, event: dict) -> str:
        """Determine agent mode from event source.

        Args:
            event: Event dict with at least a 'source' key. Matrix events also
                   carry 'room_id'; CLI/dashboard events carry source='cli'.

        Returns:
            'outward' if acting as Khanh to a colleague,
            'inward'  if acting as assistant to Khanh.
        """
        source = (event.get("source") or "").lower()

        if source in OUTWARD_SOURCES:
            return "outward"
        if source in INWARD_SOURCES:
            return "inward"

        # Heuristic: Matrix room IDs start with '!'
        room_id = event.get("room_id", "")
        if room_id.startswith("!"):
            return "outward"

        # Default safe: treat unknown sources as inward (no auto-send risk)
        return "inward"

    def classify_intent(self, body: str, mode: str) -> str:
        """Classify message intent from body text.

        Args:
            body: Raw message text.
            mode: 'outward' or 'inward' — inward has extra intent labels.

        Returns:
            One of: 'question', 'request', 'fyi', 'social',
                    'instruction' (inward only), 'query' (inward only).
        """
        text = (body or "").strip()

        # Social check first — short greetings/thanks before other patterns
        if SOCIAL_PATTERNS.match(text):
            return "social"

        # Inward-specific intents: instructions and status queries
        if mode == "inward":
            if self._is_instruction(text):
                return "instruction"
            if self._is_status_query(text):
                return "query"

        # Order matters: FYI > question > request (to avoid misclassification)
        if FYI_PATTERNS.search(text):
            return "fyi"
        if QUESTION_PATTERNS.search(text):
            return "question"
        if REQUEST_PATTERNS.search(text):
            return "request"

        # Default: treat as FYI for outward, query for inward
        return "fyi" if mode == "outward" else "query"

    def has_deadline_risk(self, body: str) -> bool:
        """Return True if message asks about timelines/deadlines (confidence penalty)."""
        return bool(DEADLINE_KEYWORDS.search(body or ""))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_instruction(self, text: str) -> bool:
        """Inward: user is telling the agent to DO something."""
        instruction_re = re.compile(
            r"\b(set|add|remove|delete|create|schedule|remind|ignore|enable|disable|configure|adjust|update my|change)\b",
            re.IGNORECASE,
        )
        return bool(instruction_re.search(text))

    def _is_status_query(self, text: str) -> bool:
        """Inward: user is asking about their current work state."""
        status_re = re.compile(
            r"\b(status|summary|report|what('s| is) (my|the)|show me|list|how many|pending|overdue|sprint|backlog|open (tickets|prs|issues))\b",
            re.IGNORECASE,
        )
        return bool(status_re.search(text))
