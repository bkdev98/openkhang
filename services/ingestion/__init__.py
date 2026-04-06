"""openkhang knowledge ingestion pipeline.

Provides ingestors for chat, Jira, GitLab, and Confluence that feed
structured knowledge into the memory layer (semantic + episodic).

Quick start:
    from dotenv import load_dotenv
    load_dotenv()

    from services.memory import MemoryClient, MemoryConfig
    from services.ingestion import JiraIngestor, IngestionScheduler
    from services.ingestion.sync_state import SyncStateStore

    config = MemoryConfig.from_env()
    memory = MemoryClient(config)
    await memory.connect()

    sync = SyncStateStore(config.database_url)
    await sync.connect()

    # One-shot ingest
    ingestor = JiraIngestor(memory)
    result = await ingestor.ingest()
    print(result)

    # Continuous background scheduler
    scheduler = IngestionScheduler(memory, sync)
    await scheduler.start()
"""

from .base import BaseIngestor, Chunk, Document, IngestResult
from .chat import ChatIngestor
from .confluence import ConfluenceIngestor
from .gitlab import GitLabIngestor
from .jira import JiraIngestor
from .scheduler import IngestionScheduler
from .sync_state import SyncStateStore

__all__ = [
    "BaseIngestor",
    "Chunk",
    "Document",
    "IngestResult",
    "ChatIngestor",
    "ConfluenceIngestor",
    "GitLabIngestor",
    "JiraIngestor",
    "IngestionScheduler",
    "SyncStateStore",
]
