"""Shared helpers for skills — avoids duplication across skill modules."""
from __future__ import annotations

import re


def extract_code_search_terms(body: str) -> str:
    """Convert body text to code-relevant search terms (CamelCase + snake_case variants)."""
    english_words = re.findall(r"[a-zA-Z_]{3,}", body)
    terms = set(english_words)
    if len(english_words) >= 2:
        terms.add("".join(w.capitalize() for w in english_words))
        terms.add("_".join(w.lower() for w in english_words))
    return " ".join(terms) + " " + body
