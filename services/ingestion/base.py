"""Abstract base classes for the knowledge ingestion pipeline.

All ingestors implement BaseIngestor which provides a standard interface
for fetch → chunk → store operations across different data sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.memory.client import MemoryClient


@dataclass
class Document:
    """A raw document fetched from a source system."""

    source: str
    doc_id: str
    title: str
    content: str
    metadata: dict[str, Any]


@dataclass
class Chunk:
    """A chunk of text ready to be embedded and stored."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    """Summary of a single ingestion run."""

    source: str
    total: int
    ingested: int
    skipped: int
    errors: int

    def __str__(self) -> str:
        return (
            f"[{self.source}] total={self.total} "
            f"ingested={self.ingested} skipped={self.skipped} errors={self.errors}"
        )


class BaseIngestor(ABC):
    """Abstract ingestor: fetch → chunk → store.

    Subclasses implement fetch_new() and chunk(). The ingest() method
    orchestrates the pipeline and handles errors uniformly.
    """

    def __init__(self, memory_client: "MemoryClient") -> None:
        self.memory = memory_client

    @abstractmethod
    async def fetch_new(self, since: datetime | None = None) -> list[Document]:
        """Fetch documents newer than `since` from the source system.

        Args:
            since: Only return documents updated after this timestamp.
                   When None, implementations should apply a reasonable default
                   (e.g., active sprint + last 7 days for Jira).

        Returns:
            List of Document objects ready for chunking.
        """
        ...

    @abstractmethod
    def chunk(self, doc: Document) -> list[Chunk]:
        """Split a document into embeddable chunks.

        Args:
            doc: The Document to split.

        Returns:
            One or more Chunk objects. Should never return an empty list
            for non-empty documents.
        """
        ...

    async def ingest(self, since: datetime | None = None) -> IngestResult:
        """Run the full ingest pipeline for this source.

        Fetches documents, chunks them, and stores each chunk via the
        MemoryClient. Errors on individual documents are logged but do
        not abort the run.

        Args:
            since: Passed through to fetch_new().

        Returns:
            IngestResult with counts for this run.
        """
        result = IngestResult(
            source=self.__class__.__name__,
            total=0,
            ingested=0,
            skipped=0,
            errors=0,
        )

        try:
            docs = await self.fetch_new(since=since)
        except Exception as exc:
            print(f"[{result.source}] fetch_new failed: {exc}")
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
                    meta = {
                        "source": doc.source,
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        **chunk.metadata,
                    }
                    await self.memory.add_memory(
                        content=chunk.text,
                        metadata=meta,
                        agent_id="outward",
                    )

                result.ingested += 1

            except Exception as exc:
                print(f"[{result.source}] error on doc {doc.doc_id}: {exc}")
                result.errors += 1

        return result
