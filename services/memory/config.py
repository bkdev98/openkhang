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
    embedding_api_key: str
    embedding_api_url: str
    embedding_model: str
    meridian_url: str

    # Mem0 collection stored in pgvector
    mem0_collection: str = "openkhang_memories"

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        """Build config from environment. Raises ValueError for missing required vars."""
        db_url = os.getenv(
            "OPENKHANG_DATABASE_URL",
            "postgresql://openkhang:openkhang@localhost:5433/openkhang",
        )
        redis_url = os.getenv("OPENKHANG_REDIS_URL", "redis://localhost:6379")
        embedding_api_key = os.getenv("EMBEDDING_API_KEY", "")
        embedding_api_url = os.getenv(
            "EMBEDDING_API_URL", "https://openrouter.ai/api/v1"
        )
        embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
        meridian_url = os.getenv("MERIDIAN_URL", "http://127.0.0.1:3456")

        if not embedding_api_key:
            raise ValueError(
                "EMBEDDING_API_KEY not set. Required for bge-m3 embeddings via OpenRouter. "
                "Get a key at https://openrouter.ai/keys and add to .env."
            )

        if not meridian_url:
            raise ValueError(
                "MERIDIAN_URL not set. Required for Mem0 memory extraction via Haiku. "
                "Run `meridian` and add MERIDIAN_URL to .env."
            )

        return cls(
            database_url=db_url,
            redis_url=redis_url,
            embedding_api_key=embedding_api_key,
            embedding_api_url=embedding_api_url,
            embedding_model=embedding_model,
            meridian_url=meridian_url,
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
                "provider": "openai",
                "config": {
                    "model": self.embedding_model,
                    "api_key": self.embedding_api_key,
                    "openai_base_url": self.embedding_api_url,
                    "embedding_dims": 1024,  # bge-m3 outputs 1024-dim vectors
                },
            },
            "llm": self._llm_config(),
            "version": "v1.1",
        }

    def _llm_config(self) -> dict:
        """LLM provider for Mem0 memory extraction: Haiku 4.5 via Meridian proxy."""
        return {
            "provider": "openai",
            "config": {
                "model": "claude-haiku-4-5-20251001",
                "openai_base_url": f"{self.meridian_url}/v1",
                "api_key": "not-needed",  # Meridian uses Claude Max subscription
            },
        }
