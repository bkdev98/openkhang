"""Text chunking strategies for the ingestion pipeline.

Three strategies:
- chunk_by_thread:   all messages in a thread → one Chunk (for chat)
- chunk_by_section:  split on section headers (for Confluence docs)
- chunk_by_size:     sliding window fallback for unstructured text
"""

from __future__ import annotations

import re
from typing import Any

from .base import Chunk


def chunk_by_thread(messages: list[dict[str, Any]]) -> list[Chunk]:
    """Combine all messages in a thread into a single Chunk.

    Args:
        messages: List of message dicts with keys: sender_id, body, time.

    Returns:
        Single-element list with the full thread concatenated.
    """
    if not messages:
        return []

    lines: list[str] = []
    participants: set[str] = set()
    timestamps: list[str] = []

    for msg in messages:
        sender = msg.get("sender_id") or msg.get("sender", "unknown")
        body = msg.get("body", "").strip()
        ts = msg.get("time", "")
        if body:
            lines.append(f"{sender}: {body}")
            participants.add(sender)
            if ts:
                timestamps.append(ts)

    if not lines:
        return []

    text = "\n".join(lines)
    meta: dict[str, Any] = {
        "participants": sorted(participants),
        "message_count": len(messages),
    }
    if timestamps:
        meta["timestamp_start"] = min(timestamps)
        meta["timestamp_end"] = max(timestamps)

    return [Chunk(text=text, metadata=meta)]


def chunk_by_section(text: str, delimiter: str = "##") -> list[Chunk]:
    """Split text by section headers matching the delimiter prefix.

    Each section (header + body) becomes one Chunk. Content before the
    first header is treated as an introduction section.

    Args:
        text:      Full document text.
        delimiter: Markdown heading prefix (default "##").

    Returns:
        One Chunk per section. Empty sections are dropped.
    """
    if not text.strip():
        return []

    # Escape delimiter for use in regex, then build split pattern
    escaped = re.escape(delimiter)
    # Split on lines that start with the delimiter (section headers)
    pattern = re.compile(rf"^{escaped}\s+.+$", re.MULTILINE)
    headers = list(pattern.finditer(text))

    if not headers:
        # No sections found — return the whole text as one chunk
        return [Chunk(text=text.strip(), metadata={"section_header": ""})]

    chunks: list[Chunk] = []

    # Text before first header
    intro = text[: headers[0].start()].strip()
    if intro:
        chunks.append(Chunk(text=intro, metadata={"section_header": "intro"}))

    for i, match in enumerate(headers):
        header_text = match.group().strip()
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end].strip()
        section_text = f"{header_text}\n{body}".strip() if body else header_text
        if section_text:
            chunks.append(Chunk(text=section_text, metadata={"section_header": header_text}))

    return chunks


def chunk_by_size(text: str, max_chars: int = 2000) -> list[Chunk]:
    """Split text into fixed-size chunks with no overlap.

    Tries to break at sentence boundaries (". ") rather than mid-word.
    Falls back to hard splitting when no boundary is found.

    Args:
        text:      Input text.
        max_chars: Maximum characters per chunk (default 2000).

    Returns:
        List of Chunks, each at most max_chars long.
    """
    text = text.strip()
    if not text:
        return []

    if len(text) <= max_chars:
        return [Chunk(text=text, metadata={})]

    chunks: list[Chunk] = []
    start = 0
    total = len(text)

    while start < total:
        end = min(start + max_chars, total)
        if end < total:
            # Try to break at sentence boundary
            boundary = text.rfind(". ", start, end)
            if boundary != -1 and boundary > start:
                end = boundary + 2  # include the period and space
        piece = text[start:end].strip()
        if piece:
            chunks.append(Chunk(text=piece, metadata={"chunk_index": len(chunks)}))
        start = end

    return chunks
