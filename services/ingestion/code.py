"""Code ingestor — indexes source files from configured projects into semantic memory.

Chunks code by class/function boundaries (for Kotlin) or by file sections.
Each chunk is stored with file path, project name, and language metadata
so the agent can search and cite specific code locations.

Usage:
    ingestor = CodeIngestor(memory_client)
    result = await ingestor.ingest()  # indexes all configured projects
    result = await ingestor.ingest_project("momo-app")  # index one project
"""

from __future__ import annotations

import fnmatch
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .base import BaseIngestor, Chunk, Document, IngestResult

if TYPE_CHECKING:
    from services.memory.client import MemoryClient

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "projects.yaml"

# Max chars per code chunk (bge-m3 supports 8192 tokens, ~4000 chars is safe)
_CHUNK_SIZE = 3000


class CodeIngestor(BaseIngestor):
    """Index source code from local projects into semantic memory."""

    def __init__(self, memory_client: "MemoryClient") -> None:
        super().__init__(memory_client)
        self._config = self._load_config()

    def _load_config(self) -> dict:
        try:
            return yaml.safe_load(CONFIG_PATH.read_text()) or {}
        except Exception:
            return {}

    async def fetch_new(self, since: datetime | None = None) -> list[Document]:
        """Fetch code files from all configured projects."""
        docs = []
        for name, proj in self._config.get("projects", {}).items():
            docs.extend(self._scan_project(name, proj))
        return docs

    def chunk(self, doc: Document) -> list[Chunk]:
        """Chunk a code file by class/function boundaries."""
        lang = doc.metadata.get("language", "")
        if lang == "kotlin" or doc.metadata.get("extension") == ".kt":
            return self._chunk_kotlin(doc)
        return self._chunk_by_blocks(doc)

    async def ingest_project(self, project_name: str) -> IngestResult:
        """Index a single project."""
        proj = self._config.get("projects", {}).get(project_name)
        if not proj:
            return IngestResult(source=f"code:{project_name}", total=0,
                                ingested=0, skipped=0, errors=1)

        docs = self._scan_project(project_name, proj)
        return await self._ingest_docs(docs, project_name)

    async def ingest(self, since: datetime | None = None) -> IngestResult:
        """Index all configured projects."""
        docs = await self.fetch_new(since)
        return await self._ingest_docs(docs, "all")

    async def _ingest_docs(self, docs: list[Document], label: str) -> IngestResult:
        total = 0
        ingested = 0
        skipped = 0
        errors = 0

        for doc in docs:
            chunks = self.chunk(doc)
            total += len(chunks)

            for chunk in chunks:
                try:
                    await self.memory.add_memory(
                        content=chunk.text,
                        metadata=chunk.metadata,
                        agent_id="inward",
                    )
                    ingested += 1
                    if ingested % 50 == 0:
                        print(f"  [code] Indexed {ingested} chunks...")
                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"  [code] Error: {e}")

        return IngestResult(
            source=f"code:{label}",
            total=total,
            ingested=ingested,
            skipped=skipped,
            errors=errors,
        )

    # ── File scanning ───────────────────────────────────────────────

    def _scan_project(self, name: str, proj: dict) -> list[Document]:
        """Scan project directory for source files."""
        base = Path(os.path.expanduser(proj.get("path", ""))).resolve()
        if not base.exists():
            print(f"  [code] Project path not found: {base}")
            return []

        extensions = set(proj.get("extensions", [".kt", ".ts", ".tsx"]))
        excludes = proj.get("exclude_patterns", ["node_modules", "build", "dist", ".gradle"])
        include_paths = proj.get("include_paths", [])

        docs = []
        if include_paths:
            # Only scan specific subdirectories
            for subpath in include_paths:
                scan_dir = base / subpath
                if scan_dir.exists():
                    docs.extend(self._scan_dir(scan_dir, base, name, proj, extensions, excludes))
        else:
            docs.extend(self._scan_dir(base, base, name, proj, extensions, excludes))

        return docs

    def _scan_dir(self, scan_dir: Path, base: Path, project_name: str,
                  proj: dict, extensions: set, excludes: list) -> list[Document]:
        docs = []
        for file_path in scan_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix not in extensions:
                continue
            # Check excludes
            rel = str(file_path.relative_to(base))
            if any(fnmatch.fnmatch(rel, f"*{ex}*") for ex in excludes):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            docs.append(Document(
                source=f"code:{project_name}",
                doc_id=f"{project_name}:{rel}",
                title=rel,
                content=content,
                metadata={
                    "project": project_name,
                    "file_path": rel,
                    "full_path": str(file_path),
                    "extension": file_path.suffix,
                    "language": proj.get("language", ""),
                    "lines": content.count("\n") + 1,
                },
            ))
        return docs

    # ── Kotlin chunking ─────────────────────────────────────────────

    def _chunk_kotlin(self, doc: Document) -> list[Chunk]:
        """Chunk Kotlin files by class/function/object boundaries."""
        content = doc.content
        chunks = []

        # Split by top-level declarations
        # Pattern: class, object, fun, interface, enum at indent 0
        pattern = re.compile(
            r'^((?:(?:private|internal|public|open|abstract|data|sealed|suspend|override)\s+)*'
            r'(?:class|object|fun|interface|enum)\s+\w+)',
            re.MULTILINE,
        )
        matches = list(pattern.finditer(content))

        if not matches:
            # No class/fun boundaries found — chunk by size
            return self._chunk_by_size(doc)

        # Add imports/package as first chunk
        if matches[0].start() > 50:
            header = content[:matches[0].start()].strip()
            if header:
                chunks.append(self._make_chunk(doc, header, "header"))

        # Each declaration gets its own chunk
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            block = content[start:end].strip()

            if len(block) > _CHUNK_SIZE:
                # Large class — split by methods
                sub_chunks = self._split_large_block(doc, block, match.group(1))
                chunks.extend(sub_chunks)
            elif block:
                chunks.append(self._make_chunk(doc, block, match.group(1)))

        return chunks

    def _split_large_block(self, doc: Document, block: str, label: str) -> list[Chunk]:
        """Split a large class/object into method-level chunks."""
        chunks = []
        # Find fun declarations within the block
        fun_pattern = re.compile(r'^\s+((?:override\s+)?(?:suspend\s+)?fun\s+\w+)', re.MULTILINE)
        fun_matches = list(fun_pattern.finditer(block))

        if not fun_matches:
            # No methods — just chunk by size
            for j in range(0, len(block), _CHUNK_SIZE):
                part = block[j:j + _CHUNK_SIZE]
                chunks.append(self._make_chunk(doc, part, f"{label} (part)"))
            return chunks

        # Class header (before first method)
        if fun_matches[0].start() > 50:
            header = block[:fun_matches[0].start()].strip()
            chunks.append(self._make_chunk(doc, header, f"{label} header"))

        for i, fm in enumerate(fun_matches):
            start = fm.start()
            end = fun_matches[i + 1].start() if i + 1 < len(fun_matches) else len(block)
            method_block = block[start:end].strip()
            if method_block:
                chunks.append(self._make_chunk(doc, method_block, fm.group(1).strip()))

        return chunks

    # ── Generic chunking ────────────────────────────────────────────

    def _chunk_by_blocks(self, doc: Document) -> list[Chunk]:
        """Chunk TypeScript/other files by export/function/class boundaries."""
        content = doc.content
        pattern = re.compile(
            r'^(export\s+(?:default\s+)?(?:function|class|const|interface|type|enum)\s+\w+|'
            r'(?:function|class)\s+\w+)',
            re.MULTILINE,
        )
        matches = list(pattern.finditer(content))

        if not matches:
            return self._chunk_by_size(doc)

        chunks = []
        if matches[0].start() > 50:
            header = content[:matches[0].start()].strip()
            if header:
                chunks.append(self._make_chunk(doc, header, "imports"))

        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            block = content[start:end].strip()
            if block:
                if len(block) > _CHUNK_SIZE:
                    for j in range(0, len(block), _CHUNK_SIZE):
                        chunks.append(self._make_chunk(doc, block[j:j + _CHUNK_SIZE], f"{match.group(1)} (part)"))
                else:
                    chunks.append(self._make_chunk(doc, block, match.group(1)))

        return chunks

    def _chunk_by_size(self, doc: Document) -> list[Chunk]:
        """Fallback: chunk by size with line-boundary splitting."""
        content = doc.content
        chunks = []
        lines = content.split("\n")
        current = []
        current_len = 0

        for line in lines:
            current.append(line)
            current_len += len(line) + 1
            if current_len >= _CHUNK_SIZE:
                text = "\n".join(current)
                chunks.append(self._make_chunk(doc, text, f"lines {len(chunks)*50}-{(len(chunks)+1)*50}"))
                current = []
                current_len = 0

        if current:
            text = "\n".join(current)
            chunks.append(self._make_chunk(doc, text, f"lines {len(chunks)*50}+"))

        return chunks

    def _make_chunk(self, doc: Document, text: str, label: str) -> Chunk:
        """Create a chunk with full metadata for code search."""
        return Chunk(
            text=f"[{doc.metadata['project']}:{doc.metadata['file_path']}] {label}\n\n{text}",
            metadata={
                **doc.metadata,
                "chunk_label": label,
                "source": doc.source,
            },
        )
