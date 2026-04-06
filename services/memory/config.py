"""Memory service configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class MemoryConfig:
    """All runtime settings for the memory layer.

    Values are read from environment variables so that nothing is
    hard-coded outside of .env / docker-compose.
    """

    database_url: str
    redis_url: str
    ollama_base_url: str
    embedding_model: str
    anthropic_api_key: str

    # Mem0 collection stored in pgvector
    mem0_collection: str = "openkhang_memories"

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        """Build config from environment. Raises ValueError for missing required vars."""
        required = {
            "OPENKHANG_DATABASE_URL": os.getenv(
                "OPENKHANG_DATABASE_URL",
                "postgresql://openkhang:openkhang@localhost:5433/openkhang",
            ),
            "OPENKHANG_REDIS_URL": os.getenv("OPENKHANG_REDIS_URL", "redis://localhost:6379"),
            "OLLAMA_BASE_URL": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL", "bge-m3"),
        }

        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not anthropic_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Mem0 needs it for memory extraction (LLM call). "
                "Add it to your .env file."
            )

        return cls(
            database_url=required["OPENKHANG_DATABASE_URL"],
            redis_url=required["OPENKHANG_REDIS_URL"],
            ollama_base_url=required["OLLAMA_BASE_URL"],
            embedding_model=required["EMBEDDING_MODEL"],
            anthropic_api_key=anthropic_key,
        )

    def as_mem0_config(self) -> dict:
        """Return Mem0-compatible config dict.

        See: https://docs.mem0.ai/open-source/quickstart
        """
        # Parse postgres DSN components for Mem0 (it needs individual fields)
        from urllib.parse import urlparse

        parsed = urlparse(self.database_url)

        return {
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "dbname": parsed.path.lstrip("/"),
                    "user": parsed.username,
                    "password": parsed.password,
                    "host": parsed.hostname,
                    "port": parsed.port or 5432,
                    "collection_name": self.mem0_collection,
                    "embedding_model_dims": 1024,  # bge-m3 outputs 1024-dim vectors
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": self.embedding_model,
                    "ollama_base_url": self.ollama_base_url,
                    "embedding_dims": 1024,
                },
            },
            "llm": {
                "provider": "anthropic",
                "config": {
                    "model": "claude-sonnet-4-20250514",
                    "api_key": self.anthropic_api_key,
                },
            },
            "version": "v1.1",
        }
