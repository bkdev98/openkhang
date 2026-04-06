"""GitLab MR ingestor — fetches merge requests via glab CLI.

Uses `glab mr list --output json` and `glab api` for details.
Extracts Jira ticket cross-references from branch names and descriptions.
Stores MR title + description + diff stat summary (NOT full diff).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import BaseIngestor, Chunk, Document, IngestResult
from .chunker import chunk_by_size
from .entity import extract_and_store_entities, extract_jira_keys, store_mr_entity

if TYPE_CHECKING:
    from services.memory.client import MemoryClient

_CHUNK_SIZE = 2000
# Jira key pattern for cross-referencing from branch/description
_JIRA_RE = re.compile(r"[A-Z][A-Z0-9_]+-\d+")


class GitLabIngestor(BaseIngestor):
    """Ingest GitLab merge requests into semantic memory.

    Fetches open + recently merged MRs. Each MR becomes one Document
    containing title, description, and diff stat summary.

    Requires:
        - `glab` CLI installed and authenticated
        - GITLAB_HOST env var (optional; glab reads its own config)
    """

    def __init__(
        self,
        memory_client: "MemoryClient",
        project: str | None = None,
    ) -> None:
        super().__init__(memory_client)
        # Allow overriding project path; glab uses current repo by default
        self._project = project or os.getenv("GITLAB_PROJECT", "")

    def _run_glab(self, args: list[str]) -> Any:
        """Run glab CLI and return parsed JSON output.

        Args:
            args: Arguments after `glab`.

        Returns:
            Parsed JSON (list or dict), or None on error.
        """
        cmd = ["glab"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            print("[gitlab] `glab` CLI not found — skipping GitLab ingestion")
            return None
        except subprocess.TimeoutExpired:
            print("[gitlab] CLI timed out")
            return None

        if result.returncode != 0:
            print(f"[gitlab] CLI error (rc={result.returncode}): {result.stderr[:300]}")
            return None

        output = result.stdout.strip()
        if not output:
            return []

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            # glab sometimes returns non-JSON for empty results
            return []

    def _project_args(self) -> list[str]:
        """Return --repo flag if GITLAB_PROJECT is set."""
        if self._project:
            return ["--repo", self._project]
        return []

    async def fetch_new(self, since: datetime | None = None) -> list[Document]:
        """Fetch open MRs and recently merged MRs.

        Args:
            since: Unused for GitLab (glab has limited filtering);
                   open MRs + last 20 merged are always fetched.

        Returns:
            One Document per MR.
        """
        docs: list[Document] = []

        # Fetch open MRs
        open_mrs = self._run_glab(
            ["mr", "list", "--output", "json"] + self._project_args()
        )
        if open_mrs and isinstance(open_mrs, list):
            for mr in open_mrs:
                doc = self._mr_to_document(mr)
                if doc:
                    docs.append(doc)

        # Fetch recently merged MRs (last 20)
        merged_mrs = self._run_glab(
            ["mr", "list", "--state", "merged", "--per-page", "20",
             "--output", "json"] + self._project_args()
        )
        if merged_mrs and isinstance(merged_mrs, list):
            seen_ids = {d.doc_id for d in docs}
            for mr in merged_mrs:
                iid = str(mr.get("iid", mr.get("number", "")))
                if iid not in seen_ids:
                    doc = self._mr_to_document(mr)
                    if doc:
                        docs.append(doc)

        print(f"[gitlab] fetched {len(docs)} MRs")
        return docs

    def _mr_to_document(self, mr: dict[str, Any]) -> Document | None:
        """Convert raw glab MR dict to a Document."""
        iid = str(mr.get("iid", mr.get("number", "")))
        if not iid:
            return None

        title = mr.get("title", "")
        description = mr.get("description", "") or ""
        state = mr.get("state", "")
        branch = mr.get("source_branch", mr.get("head_branch", ""))
        target = mr.get("target_branch", mr.get("base_branch", "main"))
        author_raw = mr.get("author", {})
        author = (
            author_raw.get("username", author_raw.get("login", ""))
            if isinstance(author_raw, dict)
            else str(author_raw)
        )
        pipeline_raw = mr.get("head_pipeline", mr.get("pipeline")) or {}
        pipeline_status = (
            pipeline_raw.get("status", "")
            if isinstance(pipeline_raw, dict)
            else str(pipeline_raw)
        )

        # Diff stat summary (counts only, not actual diff)
        additions = mr.get("additions", mr.get("changes_count", "?"))
        deletions = mr.get("deletions", "?")
        diff_summary = f"+{additions}/-{deletions} lines changed" if additions != "?" else ""

        # Extract Jira cross-refs from branch name and description
        jira_refs = list(dict.fromkeys(
            _JIRA_RE.findall(branch) + _JIRA_RE.findall(description)
        ))

        # Build content
        parts = [f"MR !{iid}: {title}", f"Branch: {branch} → {target}"]
        if description.strip():
            parts.append(f"Description:\n{description.strip()}")
        if diff_summary:
            parts.append(f"Diff summary: {diff_summary}")
        if jira_refs:
            parts.append(f"Related tickets: {', '.join(jira_refs)}")

        content = "\n\n".join(parts)

        metadata: dict[str, Any] = {
            "mr_iid": iid,
            "mr_ref": f"!{iid}",
            "branch": branch,
            "target_branch": target,
            "author": author,
            "state": state,
            "pipeline_status": pipeline_status,
            "jira_refs": jira_refs,
        }

        return Document(
            source="gitlab",
            doc_id=iid,
            title=f"MR !{iid}: {title}",
            content=content,
            metadata=metadata,
        )

    def chunk(self, doc: Document) -> list[Chunk]:
        """Chunk MR content; attach MR metadata to each chunk."""
        chunks = chunk_by_size(doc.content, max_chars=_CHUNK_SIZE)
        for c in chunks:
            c.metadata.update({
                "mr_iid": doc.metadata.get("mr_iid", ""),
                "mr_ref": doc.metadata.get("mr_ref", ""),
                "branch": doc.metadata.get("branch", ""),
                "author": doc.metadata.get("author", ""),
                "pipeline_status": doc.metadata.get("pipeline_status", ""),
            })
        return chunks

    async def ingest(self, since: datetime | None = None) -> IngestResult:
        """Ingest GitLab MRs: semantic memory + MR entities + cross-refs."""
        result = IngestResult(source="gitlab", total=0, ingested=0, skipped=0, errors=0)

        try:
            docs = await self.fetch_new(since=since)
        except Exception as exc:
            print(f"[gitlab] fetch_new failed: {exc}")
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
                        "source": "gitlab",
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        **chunk.metadata,
                    }
                    await self.memory.add_memory(
                        content=chunk.text,
                        metadata=meta,
                        agent_id="outward",
                    )

                # Store MR as named entity
                await store_mr_entity(
                    self.memory,
                    mr_ref=doc.metadata["mr_ref"],
                    title=doc.title,
                    extra_meta={
                        "author": doc.metadata.get("author", ""),
                        "state": doc.metadata.get("state", ""),
                        "pipeline_status": doc.metadata.get("pipeline_status", ""),
                    },
                )

                # Entity extraction: Jira cross-refs + author
                await extract_and_store_entities(
                    self.memory,
                    text=doc.content,
                    metadata=doc.metadata,
                    context_label=doc.title,
                )

                result.ingested += 1
            except Exception as exc:
                print(f"[gitlab] error on MR {doc.doc_id}: {exc}")
                result.errors += 1

        return result
