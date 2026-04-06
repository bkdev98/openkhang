"""Regex-based entity extraction for the ingestion pipeline.

Extracts structured entities (Jira keys, MR refs, people) from text and
metadata, then persists them as memories via MemoryClient so they can be
retrieved when building context for responses.

No NER model required — all extraction is pattern-based.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.memory.client import MemoryClient

# Jira ticket key: PROJECT-123
_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")

# GitLab MR reference: !42
_GITLAB_MR_RE = re.compile(r"!\d+")

# GitLab issue reference: #42 (used in descriptions)
_GITLAB_ISSUE_RE = re.compile(r"#\d+")


def extract_jira_keys(text: str) -> list[str]:
    """Return all unique Jira ticket keys found in text (e.g. VR-123)."""
    return list(dict.fromkeys(_JIRA_KEY_RE.findall(text)))


def extract_mr_refs(text: str) -> list[str]:
    """Return all unique GitLab MR references found in text (e.g. !42)."""
    return list(dict.fromkeys(_GITLAB_MR_RE.findall(text)))


def extract_people_from_metadata(meta: dict[str, Any]) -> list[str]:
    """Extract person names/IDs from common metadata fields.

    Checks the following keys: assignee, author, participants, reporter,
    reviewer, creator.

    Returns:
        Deduplicated list of non-empty name strings.
    """
    people: list[str] = []

    for key in ("assignee", "author", "reporter", "reviewer", "creator"):
        val = meta.get(key)
        if val and isinstance(val, str):
            people.append(val.strip())

    participants = meta.get("participants", [])
    if isinstance(participants, list):
        people.extend(p.strip() for p in participants if p and isinstance(p, str))

    # Deduplicate, preserving order
    seen: set[str] = set()
    result: list[str] = []
    for p in people:
        if p and p not in seen:
            seen.add(p)
            result.append(p)
    return result


async def store_jira_entity(
    memory: "MemoryClient",
    jira_key: str,
    context: str,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    """Store a Jira ticket entity memory linking the key to its context.

    Args:
        memory:     MemoryClient instance.
        jira_key:   Jira ticket key, e.g. "VR-123".
        context:    Short description or title for this ticket.
        extra_meta: Additional metadata to tag the memory with.
    """
    meta: dict[str, Any] = {
        "entity_type": "jira_ticket",
        "jira_key": jira_key,
        "source": "jira",
    }
    if extra_meta:
        meta.update(extra_meta)

    await memory.add_memory(
        content=f"Jira ticket {jira_key}: {context}",
        metadata=meta,
        agent_id="outward",
    )


async def store_mr_entity(
    memory: "MemoryClient",
    mr_ref: str,
    title: str,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    """Store a GitLab MR entity memory.

    Args:
        memory:     MemoryClient instance.
        mr_ref:     MR reference string, e.g. "!42".
        title:      MR title.
        extra_meta: Additional metadata to tag the memory with.
    """
    meta: dict[str, Any] = {
        "entity_type": "gitlab_mr",
        "mr_ref": mr_ref,
        "source": "gitlab",
    }
    if extra_meta:
        meta.update(extra_meta)

    await memory.add_memory(
        content=f"GitLab MR {mr_ref}: {title}",
        metadata=meta,
        agent_id="outward",
    )


async def store_person_entity(
    memory: "MemoryClient",
    person: str,
    role: str,
    context: str,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    """Store a person entity memory.

    Args:
        memory:     MemoryClient instance.
        person:     Person name or identifier.
        role:       Role in context (e.g. "assignee", "author", "participant").
        context:    Document or event the person appeared in.
        extra_meta: Additional metadata.
    """
    meta: dict[str, Any] = {
        "entity_type": "person",
        "person": person,
        "role": role,
    }
    if extra_meta:
        meta.update(extra_meta)

    await memory.add_memory(
        content=f"{person} is {role} in {context}",
        metadata=meta,
        agent_id="outward",
    )


async def extract_and_store_entities(
    memory: "MemoryClient",
    text: str,
    metadata: dict[str, Any],
    context_label: str,
) -> None:
    """Extract all entity types from text + metadata and store them.

    This is the convenience entry point called by ingestors after chunking.

    Args:
        memory:        MemoryClient instance.
        text:          Combined text to scan for Jira keys and MR refs.
        metadata:      Document/chunk metadata for person extraction.
        context_label: Human-readable label for the source document.
    """
    # Jira keys from text
    for key in extract_jira_keys(text):
        try:
            await store_jira_entity(
                memory, key, context=f"referenced in {context_label}",
                extra_meta={"context": context_label},
            )
        except Exception as exc:
            print(f"[entity] failed to store Jira entity {key}: {exc}")

    # GitLab MR refs from text
    for ref in extract_mr_refs(text):
        try:
            await store_mr_entity(
                memory, ref, title=f"referenced in {context_label}",
                extra_meta={"context": context_label},
            )
        except Exception as exc:
            print(f"[entity] failed to store MR entity {ref}: {exc}")

    # People from metadata
    for person in extract_people_from_metadata(metadata):
        role = _infer_role(person, metadata)
        try:
            await store_person_entity(
                memory, person, role=role, context=context_label,
                extra_meta={"context": context_label},
            )
        except Exception as exc:
            print(f"[entity] failed to store person entity {person}: {exc}")


def _infer_role(person: str, metadata: dict[str, Any]) -> str:
    """Determine the role label for a person based on which metadata field they appear in."""
    for role_key in ("assignee", "author", "reporter", "reviewer", "creator"):
        if metadata.get(role_key) == person:
            return role_key
    participants = metadata.get("participants", [])
    if isinstance(participants, list) and person in participants:
        return "participant"
    return "contributor"
