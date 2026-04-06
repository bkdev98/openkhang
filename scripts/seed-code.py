#!/usr/bin/env python3
"""Seed project source code into semantic memory.

Indexes Kotlin/TypeScript files from configured projects (config/projects.yaml)
into Mem0 with file path, class/function labels, and project metadata.

Handles rate limits with automatic retry and progress tracking.

Usage:
    services/.venv/bin/python3 scripts/seed-code.py                    # all projects
    services/.venv/bin/python3 scripts/seed-code.py --project momo-app # one project
    services/.venv/bin/python3 scripts/seed-code.py --dry-run          # count only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from services.memory.config import MemoryConfig
from services.memory.client import MemoryClient
from services.ingestion.code import CodeIngestor


async def main():
    parser = argparse.ArgumentParser(description="Seed project code into memory")
    parser.add_argument("--project", help="Index specific project only")
    parser.add_argument("--dry-run", action="store_true", help="Count chunks without embedding")
    args = parser.parse_args()

    config = MemoryConfig.from_env()
    client = MemoryClient(config)
    await client.connect()

    ingestor = CodeIngestor(client)

    if args.dry_run:
        docs = await ingestor.fetch_new()
        total_chunks = 0
        by_project = {}
        for d in docs:
            by_project.setdefault(d.metadata["project"], []).append(d)
        for proj, proj_docs in by_project.items():
            if args.project and proj != args.project:
                continue
            chunks = sum(len(ingestor.chunk(d)) for d in proj_docs)
            lines = sum(d.metadata["lines"] for d in proj_docs)
            total_chunks += chunks
            print(f"  {proj}: {len(proj_docs)} files, {lines} lines → {chunks} chunks")
        print(f"\nTotal: {total_chunks} chunks (dry-run, nothing stored)")
        await client.close()
        return

    print("=" * 50)
    print("Code Knowledge Seeder")
    print("=" * 50)

    t0 = time.monotonic()

    if args.project:
        print(f"\nIndexing project: {args.project}")
        result = await ingestor.ingest_project(args.project)
    else:
        print("\nIndexing all configured projects...")
        result = await ingestor.ingest()

    elapsed = time.monotonic() - t0

    await client.close()

    print(f"\n{'=' * 50}")
    print(f"Source: {result.source}")
    print(f"Total chunks: {result.total}")
    print(f"Indexed: {result.ingested}")
    print(f"Errors: {result.errors}")
    print(f"Time: {elapsed:.0f}s")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
