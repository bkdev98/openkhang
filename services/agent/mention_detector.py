"""Mention detection for Google Chat messages bridged via Matrix.

Builds regex patterns from persona.yaml to detect @-mentions of the owner.
Supports diacritic-stripped matching (KHÁNH → KHANH) for Vietnamese names.
"""

from __future__ import annotations

import re
import unicodedata

# @all is always a mention; owner-specific patterns derived from persona.yaml
_STATIC_MENTION_PATTERNS = [r"@all\b"]
_owner_mention_patterns: list[str] | None = None
_owner_puppet_id: str | None = None


def strip_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics for fuzzy matching.

    'KHÁNH' → 'KHANH', 'BÙI' → 'BUI', 'NGUYỄN' → 'NGUYEN'
    """
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def get_mention_patterns() -> list[str]:
    """Build mention regex patterns from persona.yaml name. Cached after first call.

    Only matches explicit @-mentions in Google Chat handle format
    (e.g., @BÙI QUỐC KHÁNH - ITC - App Dev - Senior - Mobile Engineer).
    Uses diacritic-stripped matching. Does NOT match bare name words in text.
    """
    global _owner_mention_patterns, _owner_puppet_id
    if _owner_mention_patterns is not None:
        return _owner_mention_patterns

    import yaml
    from pathlib import Path
    persona_path = Path(__file__).parent.parent.parent / "config" / "persona.yaml"
    state_path = Path(__file__).parent.parent.parent / ".claude" / "gchat-autopilot.local.md"
    patterns = list(_STATIC_MENTION_PATTERNS)

    # Load owner's Google Chat puppet ID for matrix.to link matching
    try:
        for line in state_path.read_text().splitlines():
            if line.startswith("sender_id:"):
                uid = line.split(":", 1)[1].strip().strip('"').replace("users/", "")
                _owner_puppet_id = uid
                patterns.append(rf"googlechat_{uid}")
                break
    except FileNotFoundError:
        pass

    try:
        persona = yaml.safe_load(persona_path.read_text(encoding="utf-8")) or {}
        name = persona.get("name", "")
        if name:
            name_stripped = strip_diacritics(name).lower()
            parts = name_stripped.split()
            if len(parts) > 1:
                patterns.append(rf"@{' '.join(parts)}")
            for part in parts:
                if len(part) >= 4:  # skip short parts like "bui"
                    patterns.append(rf"@{part}\b")
    except Exception:
        pass  # fail-open: no persona = no owner-specific mention patterns
    _owner_mention_patterns = patterns
    return _owner_mention_patterns


def detect_mention(body: str, formatted_body: str = "") -> bool:
    """Check if a message @mentions the owner via explicit @-prefix or matrix.to link.

    Uses diacritic-stripped matching so @KHÁNH matches pattern 'khanh'.
    Only matches explicit @-mentions, NOT bare name words in text.
    """
    text = strip_diacritics(body + " " + formatted_body).lower()
    return any(re.search(p, text) for p in get_mention_patterns())
