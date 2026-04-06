"""Confluence page ingestor — fetches pages via atlassian-cli or REST API.

Splits pages by h2 section headers. Each section becomes one chunk.
Prioritises recently-updated pages from the configured space.

Auth: uses CONFLUENCE_API_TOKEN + CONFLUENCE_USERNAME from environment.
Falls back to direct REST API calls if atlassian-cli is unavailable.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import BaseIngestor, Chunk, Document, IngestResult
from .chunker import chunk_by_section
from .entity import extract_and_store_entities

if TYPE_CHECKING:
    from services.memory.client import MemoryClient

_DEFAULT_LIMIT = 20  # Max pages to fetch per run


class ConfluenceIngestor(BaseIngestor):
    """Ingest Confluence pages split by h2 section headers.

    Tries atlassian-cli first, falls back to Confluence REST API v2.

    Requires (from .env):
        CONFLUENCE_DOMAIN    — e.g. "myteam.atlassian.net"
        CONFLUENCE_USERNAME  — Atlassian account email
        CONFLUENCE_API_TOKEN — API token
        CONFLUENCE_SPACE_KEY — Space to ingest (optional, defaults to all)
    """

    def __init__(
        self,
        memory_client: "MemoryClient",
        space_key: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> None:
        super().__init__(memory_client)
        self._domain = os.getenv("CONFLUENCE_DOMAIN", "")
        self._username = os.getenv("CONFLUENCE_USERNAME", "")
        self._api_token = os.getenv("CONFLUENCE_API_TOKEN", "")
        self._space_key = space_key or os.getenv("CONFLUENCE_SPACE_KEY", "")
        self._api_path = os.getenv("CONFLUENCE_API_PATH", "/wiki/api/v2")
        self._limit = limit

    # ------------------------------------------------------------------
    # Fetch via REST API (primary path — more reliable than CLI)
    # ------------------------------------------------------------------

    def _auth_header(self) -> str:
        """Build Basic auth header value from username + API token."""
        creds = f"{self._username}:{self._api_token}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    def _api_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GET request to the Confluence REST API v2.

        Args:
            path:   API path, e.g. "/wiki/api/v2/pages".
            params: Query parameters dict.

        Returns:
            Parsed JSON response body, or None on error.
        """
        if not self._domain:
            print("[confluence] CONFLUENCE_DOMAIN not set")
            return None

        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params)

        url = f"https://{self._domain}{path}{query}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", self._auth_header())
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            print(f"[confluence] API request failed ({url}): {exc}")
            return None

    def _fetch_pages_via_api(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch recent pages from Confluence REST API (v1 or v2, auto-detected)."""
        is_v1 = "/rest/api" in self._api_path and "v2" not in self._api_path

        if is_v1:
            # Confluence Server/DC uses REST API v1: /rest/api/content
            params: dict[str, Any] = {
                "limit": self._limit,
                "orderby": "lastmodified desc",
                "expand": "body.storage,version",
            }
            if self._space_key:
                params["spaceKey"] = self._space_key
            path = f"{self._api_path}/content"
        else:
            # Confluence Cloud uses REST API v2: /wiki/api/v2/pages
            params = {
                "limit": self._limit,
                "sort": "-last-modified",
                "body-format": "storage",
            }
            if self._space_key:
                params["space-key"] = self._space_key
            path = f"{self._api_path}/pages"

        data = self._api_get(path, params)
        if not data:
            return []

        results = data.get("results", [])

        # Filter by since timestamp if provided
        if since:
            since_iso = since.isoformat()
            filtered = []
            for page in results:
                version = page.get("version", {})
                updated = version.get("createdAt", "")
                if not updated or updated >= since_iso:
                    filtered.append(page)
                # Skip pages not updated since last sync
            return filtered

        return results

    def _get_page_body(self, page_id: str) -> str:
        """Fetch the body of a specific page (plain text via REST)."""
        data = self._api_get(
            f"/wiki/api/v2/pages/{page_id}",
            {"body-format": "atlas_doc_format"},
        )
        if not data:
            return ""

        # Try storage format body
        body = data.get("body", {})
        storage = body.get("storage", body.get("atlas_doc_format", {}))
        value = storage.get("value", "") if isinstance(storage, dict) else ""
        return _strip_html_tags(value)

    # ------------------------------------------------------------------
    # Fetch via atlassian-cli (fallback)
    # ------------------------------------------------------------------

    def _run_atlassian_cli(self, args: list[str]) -> list[dict[str, Any]]:
        """Run atlassian-cli and parse JSON output."""
        try:
            result = subprocess.run(
                ["atlassian-cli"] + args,
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ},
            )
        except FileNotFoundError:
            return []
        except subprocess.TimeoutExpired:
            print("[confluence] atlassian-cli timed out")
            return []

        if result.returncode != 0:
            return []

        try:
            data = json.loads(result.stdout)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            return []

    # ------------------------------------------------------------------
    # BaseIngestor interface
    # ------------------------------------------------------------------

    async def fetch_new(self, since: datetime | None = None) -> list[Document]:
        """Fetch Confluence pages, trying REST API first.

        Args:
            since: Only fetch pages updated after this timestamp.

        Returns:
            One Document per page.
        """
        pages = self._fetch_pages_via_api(since=since)

        if not pages:
            # Fallback to atlassian-cli
            cli_args = ["confluence", "page", "list", "--output", "json"]
            if self._space_key:
                cli_args += ["--space", self._space_key]
            pages = self._run_atlassian_cli(cli_args)

        docs: list[Document] = []
        for page in pages:
            try:
                doc = self._page_to_document(page)
                if doc:
                    docs.append(doc)
            except Exception as exc:
                page_id = page.get("id", "unknown") if isinstance(page, dict) else "unknown"
                print(f"[confluence] error converting page {page_id}: {exc}")

        print(f"[confluence] fetched {len(docs)} pages")
        return docs

    def _page_to_document(self, page: dict[str, Any]) -> Document | None:
        """Convert raw Confluence page dict to a Document."""
        page_id = str(page.get("id", ""))
        if not page_id:
            return None

        title = page.get("title", "")
        space_raw = page.get("spaceId", page.get("space", {}))
        space_key = (
            space_raw.get("key", str(space_raw))
            if isinstance(space_raw, dict)
            else str(space_raw)
        )

        # Extract body from inline page data (already fetched with body-format=storage)
        body_raw = page.get("body", {})
        content = ""
        if isinstance(body_raw, dict):
            storage = body_raw.get("storage", body_raw.get("atlas_doc_format", {}))
            value = storage.get("value", "") if isinstance(storage, dict) else ""
            content = _strip_html_tags(value)

        # Only fetch separately if inline body was empty (avoids double API call)
        if not content.strip():
            content = self._get_page_body(page_id)

        if not content.strip():
            content = title  # Minimal fallback

        version = page.get("version", {})
        updated = version.get("createdAt", "") if isinstance(version, dict) else ""

        metadata: dict[str, Any] = {
            "page_id": page_id,
            "space_key": space_key,
            "title": title,
            "updated_at": updated,
        }

        return Document(
            source="confluence",
            doc_id=page_id,
            title=title,
            content=content,
            metadata=metadata,
        )

    def chunk(self, doc: Document) -> list[Chunk]:
        """Split page by h2 headers (## in converted markdown)."""
        # Confluence storage format uses <h2> tags; after stripping HTML
        # we look for lines that were headers. chunk_by_section uses "##"
        # but converted Confluence HTML often has ALL-CAPS or plain lines.
        # We split on double-newline sections as a practical fallback.
        chunks = chunk_by_section(doc.content, delimiter="##")
        if len(chunks) <= 1 and len(doc.content) > 500:
            # Try splitting on h2-style lines (lines ending with no period, short)
            from .chunker import chunk_by_size
            chunks = chunk_by_size(doc.content, max_chars=2000)

        for c in chunks:
            c.metadata.update({
                "page_id": doc.metadata.get("page_id", ""),
                "space_key": doc.metadata.get("space_key", ""),
                "title": doc.metadata.get("title", ""),
            })
        return chunks

    async def ingest(self, since: datetime | None = None) -> IngestResult:
        """Ingest Confluence pages: semantic memory + entity extraction."""
        result = IngestResult(source="confluence", total=0, ingested=0, skipped=0, errors=0)

        if not self._domain and not self._api_token:
            print("[confluence] CONFLUENCE_DOMAIN or CONFLUENCE_API_TOKEN not configured — skipping")
            return result

        try:
            docs = await self.fetch_new(since=since)
        except Exception as exc:
            print(f"[confluence] fetch_new failed: {exc}")
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
                        "source": "confluence",
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        **chunk.metadata,
                    }
                    await self.memory.add_memory(
                        content=chunk.text,
                        metadata=meta,
                        agent_id="outward",
                    )

                await extract_and_store_entities(
                    self.memory,
                    text=doc.content,
                    metadata=doc.metadata,
                    context_label=doc.title,
                )

                result.ingested += 1
            except Exception as exc:
                print(f"[confluence] error on page {doc.doc_id}: {exc}")
                result.errors += 1

        return result


def _strip_html_tags(html: str) -> str:
    """Remove HTML tags and decode common entities for plain text.

    Preserves content inside <code>/<pre> blocks by converting them to
    markdown fenced code blocks before stripping other tags.
    """
    import re
    # Preserve code blocks as markdown fenced code
    text = re.sub(
        r"<(pre|code)[^>]*>(.*?)</\1>",
        lambda m: f"\n```\n{m.group(2)}\n```\n",
        html,
        flags=re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()
