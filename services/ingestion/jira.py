"""Jira ticket ingestor — fetches issues via jira-cli and ingests into memory.

Uses the `jira` CLI (jira-cli) to query issues via JQL. Auth is handled
by jira-cli using JIRA_API_TOKEN from the environment.

JQL default: active sprint OR updated in last 7 days for the configured project.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import BaseIngestor, Chunk, Document, IngestResult
from .chunker import chunk_by_size
from .entity import extract_and_store_entities, extract_jira_keys

if TYPE_CHECKING:
    from services.memory.client import MemoryClient

# Max chars per chunk for ticket content
_CHUNK_SIZE = 2000


class JiraIngestor(BaseIngestor):
    """Ingest Jira tickets (title + description + comments) into semantic memory.

    Each ticket becomes one Document. Content is chunked by size when it
    exceeds _CHUNK_SIZE characters.

    Requires:
        - `jira` CLI installed and authenticated
        - JIRA_PROJECT env var (e.g. "VR")
    """

    def __init__(
        self,
        memory_client: "MemoryClient",
        project: str | None = None,
        jql: str | None = None,
    ) -> None:
        super().__init__(memory_client)
        self._project = project or os.getenv("JIRA_PROJECT", "VR")
        self._custom_jql = jql

    def _build_jql(self, since: datetime | None = None) -> str:
        """Build JQL query string.

        Default: active sprint OR updated last 7d for the configured project.
        """
        if self._custom_jql:
            return self._custom_jql

        base = f"project = {self._project}"
        if since:
            # Format: "2024-01-15 00:00"
            since_str = since.strftime("%Y-%m-%d %H:%M")
            return f'{base} AND updated >= "{since_str}"'

        return (
            f"{base} AND "
            f'(sprint in openSprints() OR updated >= "-7d")'
        )

    def _run_jira_cli(self, args: list[str]) -> list[dict[str, Any]]:
        """Run jira CLI command and parse JSON output.

        Args:
            args: CLI arguments after `jira`.

        Returns:
            Parsed JSON list, or empty list on error.

        Raises:
            FileNotFoundError: if `jira` CLI is not installed.
        """
        try:
            result = subprocess.run(
                ["jira"] + args,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            print("[jira] `jira` CLI not found — skipping Jira ingestion")
            return []
        except subprocess.TimeoutExpired:
            print("[jira] CLI timed out")
            return []

        if result.returncode != 0:
            print(f"[jira] CLI error (rc={result.returncode}): {result.stderr[:300]}")
            return []

        try:
            data = json.loads(result.stdout)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError as exc:
            print(f"[jira] failed to parse CLI output: {exc}")
            return []

    def _fetch_issue_detail(self, key: str) -> dict[str, Any]:
        """Fetch full issue detail including description and comments."""
        items = self._run_jira_cli(["issue", "view", key, "--plain", "--comments", "10"])
        if items:
            return items[0]
        # Fallback: structured JSON view
        items = self._run_jira_cli(["issue", "view", key])
        return items[0] if items else {}

    async def fetch_new(self, since: datetime | None = None) -> list[Document]:
        """Fetch Jira issues matching the JQL query.

        Args:
            since: Filter issues updated after this timestamp.

        Returns:
            One Document per issue.
        """
        jql = self._build_jql(since)
        print(f"[jira] JQL: {jql}")

        issues = self._run_jira_cli([
            "issue", "list",
            "--jql", jql,
            "--plain",
            "--no-headers",
            "--columns", "KEY,SUMMARY,STATUS,ASSIGNEE,PRIORITY",
        ])

        if not issues:
            # Try JSON output format
            issues = self._run_jira_cli([
                "issue", "list",
                "--jql", jql,
                "--output-format", "json",
            ])

        docs: list[Document] = []
        for issue in issues:
            try:
                doc = self._issue_to_document(issue)
                if doc:
                    docs.append(doc)
            except Exception as exc:
                key = issue.get("key", "unknown") if isinstance(issue, dict) else "unknown"
                print(f"[jira] error converting issue {key}: {exc}")

        print(f"[jira] fetched {len(docs)} issues")
        return docs

    def _issue_to_document(self, issue: dict[str, Any]) -> Document | None:
        """Convert a raw jira-cli issue dict to a Document."""
        key = issue.get("key", "")
        if not key:
            return None

        fields = issue.get("fields", issue)  # jira-cli may flatten or nest fields
        summary = fields.get("summary", issue.get("summary", ""))
        description = fields.get("description", issue.get("description", "")) or ""
        status_raw = fields.get("status", issue.get("status", {}))
        status = (
            status_raw.get("name", str(status_raw))
            if isinstance(status_raw, dict)
            else str(status_raw)
        )
        assignee_raw = fields.get("assignee", issue.get("assignee")) or {}
        assignee = (
            assignee_raw.get("displayName", assignee_raw.get("name", ""))
            if isinstance(assignee_raw, dict)
            else str(assignee_raw)
        )
        priority_raw = fields.get("priority", issue.get("priority", {}))
        priority = (
            priority_raw.get("name", str(priority_raw))
            if isinstance(priority_raw, dict)
            else str(priority_raw)
        )

        # Sprint info
        sprint = ""
        sprint_field = fields.get("customfield_10020") or []
        if isinstance(sprint_field, list) and sprint_field:
            s = sprint_field[-1]
            sprint = s.get("name", "") if isinstance(s, dict) else str(s)

        # Epic
        epic = fields.get("customfield_10014", issue.get("epic", "")) or ""

        # Comments
        comments_raw = fields.get("comment", {})
        comment_texts: list[str] = []
        if isinstance(comments_raw, dict):
            for c in comments_raw.get("comments", []):
                author = c.get("author", {}).get("displayName", "unknown")
                body = c.get("body", "")
                if body:
                    comment_texts.append(f"[{author}]: {body}")
        elif isinstance(comments_raw, list):
            for c in comments_raw:
                author = c.get("author", {}).get("displayName", "unknown") if isinstance(c, dict) else "unknown"
                body = c.get("body", "") if isinstance(c, dict) else str(c)
                if body:
                    comment_texts.append(f"[{author}]: {body}")

        # Build content
        parts = [f"{key}: {summary}"]
        if description:
            parts.append(f"Description:\n{description}")
        if comment_texts:
            parts.append("Comments:\n" + "\n".join(comment_texts))
        content = "\n\n".join(parts)

        metadata: dict[str, Any] = {
            "jira_key": key,
            "status": status,
            "assignee": assignee,
            "priority": priority,
            "sprint": sprint,
            "epic": str(epic),
        }

        return Document(
            source="jira",
            doc_id=key,
            title=f"{key}: {summary}",
            content=content,
            metadata=metadata,
        )

    def chunk(self, doc: Document) -> list[Chunk]:
        """Chunk ticket content by size; attach Jira metadata to each chunk."""
        chunks = chunk_by_size(doc.content, max_chars=_CHUNK_SIZE)
        for c in chunks:
            c.metadata.update({
                "jira_key": doc.metadata.get("jira_key", ""),
                "status": doc.metadata.get("status", ""),
                "assignee": doc.metadata.get("assignee", ""),
                "priority": doc.metadata.get("priority", ""),
                "sprint": doc.metadata.get("sprint", ""),
            })
        return chunks

    async def ingest(self, since: datetime | None = None) -> IngestResult:
        """Ingest Jira tickets: semantic memory + entity extraction."""
        result = IngestResult(source="jira", total=0, ingested=0, skipped=0, errors=0)

        try:
            docs = await self.fetch_new(since=since)
        except Exception as exc:
            print(f"[jira] fetch_new failed: {exc}")
            result.errors += 1
            return result

        result.total = len(docs)

        for doc in docs:
            try:
                chunks = self.chunk(doc)
                if not chunks:
                    result.skipped += 1
                    continue

                for chunk in chunks:
                    meta: dict[str, Any] = {
                        "source": "jira",
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        **chunk.metadata,
                    }
                    await self.memory.add_memory(
                        content=chunk.text,
                        metadata=meta,
                        agent_id="outward",
                    )

                # Entity extraction: Jira cross-refs + assignee
                await extract_and_store_entities(
                    self.memory,
                    text=doc.content,
                    metadata=doc.metadata,
                    context_label=doc.title,
                )

                # Also store this ticket itself as an entity
                from .entity import store_jira_entity
                await store_jira_entity(
                    self.memory,
                    jira_key=doc.metadata["jira_key"],
                    context=f"{doc.metadata.get('status', '')} — {doc.metadata.get('assignee', 'unassigned')}",
                    extra_meta=doc.metadata,
                )

                result.ingested += 1
            except Exception as exc:
                print(f"[jira] error on {doc.doc_id}: {exc}")
                result.errors += 1

        return result
