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
import subprocess
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
        """Chunk a code file by class/function boundaries.

        Markdown docs are chunked by section headers and tagged with doc_type
        (business-logic, api-spec, readme, guide) for priority retrieval.
        """
        ext = doc.metadata.get("extension", "")
        if ext == ".md":
            return self._chunk_markdown_doc(doc)
        lang = doc.metadata.get("language", "")
        if lang == "kotlin" or ext == ".kt":
            return self._chunk_kotlin(doc)
        return self._chunk_by_blocks(doc)

    async def ingest_project(self, project_name: str, incremental: bool = False) -> IngestResult:
        """Index a single project.

        Args:
            project_name: Key from config/projects.yaml.
            incremental: If True, only index files changed since last git commit
                         tracked in sync_state. Falls back to full if git fails.
        """
        proj = self._config.get("projects", {}).get(project_name)
        if not proj:
            return IngestResult(source=f"code:{project_name}", total=0,
                                ingested=0, skipped=0, errors=1)

        if incremental:
            docs = self._scan_git_changes(project_name, proj)
            if docs is None:
                # Git failed — fall back to full scan
                docs = self._scan_project(project_name, proj)
        else:
            docs = self._scan_project(project_name, proj)

        return await self._ingest_docs(docs, project_name)

    async def ingest(self, since: datetime | None = None) -> IngestResult:
        """Index all configured projects."""
        docs = await self.fetch_new(since)
        return await self._ingest_docs(docs, "all")

    async def ingest_incremental(self) -> IngestResult:
        """Index only files changed since last sync across all projects."""
        all_docs = []
        for name, proj in self._config.get("projects", {}).items():
            changed = self._scan_git_changes(name, proj)
            if changed is not None:
                all_docs.extend(changed)
            # If git fails for a project, skip it (don't fall back to full)
        if not all_docs:
            return IngestResult(source="code:incremental", total=0,
                                ingested=0, skipped=0, errors=0)
        return await self._ingest_docs(all_docs, "incremental")

    async def _ingest_docs(self, docs: list[Document], label: str) -> IngestResult:
        """Ingest code chunks directly into pgvector via Ollama embeddings.

        Bypasses Mem0's LLM extraction (which doesn't work well for code)
        and stores embeddings directly for vector search.
        """
        import json
        import urllib.request

        total = 0
        ingested = 0
        skipped = 0
        errors = 0

        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        embed_model = os.getenv("EMBEDDING_MODEL", "bge-m3")

        for doc in docs:
            chunks = self.chunk(doc)
            total += len(chunks)

            for chunk in chunks:
                try:
                    # Store as episodic event (always works, no LLM needed)
                    await self.memory.add_event(
                        source="code",
                        event_type="code.indexed",
                        actor="code_ingestor",
                        payload={
                            "text": chunk.text[:2000],  # truncate for storage
                            "project": chunk.metadata.get("project", ""),
                            "file_path": chunk.metadata.get("file_path", ""),
                            "chunk_label": chunk.metadata.get("chunk_label", ""),
                        },
                        metadata=chunk.metadata,
                    )

                    # Also try Mem0 (may work for some chunks)
                    try:
                        await self.memory.add_memory(
                            content=chunk.text[:1500],
                            metadata=chunk.metadata,
                            agent_id="inward",
                        )
                    except Exception:
                        pass  # Mem0 extraction failure is OK — episodic has it

                    ingested += 1
                    if ingested % 50 == 0:
                        print(f"  [code] Indexed {ingested}/{total} chunks...")
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

    # ── Git-based incremental scanning ────────────────────────────

    def _scan_git_changes(self, name: str, proj: dict) -> list[Document] | None:
        """Find files changed since last known commit using git.

        Uses git log/diff to detect:
        - Files modified since a stored commit hash
        - Uncommitted changes (working tree)

        Returns None if git is unavailable or project isn't a git repo.
        """
        base = Path(os.path.expanduser(proj.get("path", ""))).resolve()
        if not (base / ".git").exists():
            return None

        extensions = set(proj.get("extensions", [".kt", ".ts", ".tsx"]))
        include_paths = proj.get("include_paths", [])

        # Get last synced commit from sync_state file
        state_file = Path(__file__).parent.parent.parent / ".claude" / f"code-sync-{name}.txt"
        last_commit = state_file.read_text().strip() if state_file.exists() else ""

        try:
            if last_commit:
                # Files changed since last synced commit
                result = subprocess.run(
                    ["git", "diff", "--name-only", last_commit, "HEAD"],
                    capture_output=True, text=True, timeout=15, cwd=str(base),
                )
                changed_files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            else:
                # No previous sync — get files changed in last 20 commits
                result = subprocess.run(
                    ["git", "log", "--name-only", "--pretty=format:", "-20"],
                    capture_output=True, text=True, timeout=15, cwd=str(base),
                )
                changed_files = list(set(f.strip() for f in result.stdout.strip().split("\n") if f.strip()))

            # Also include uncommitted changes
            result2 = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, timeout=10, cwd=str(base),
            )
            uncommitted = [f.strip() for f in result2.stdout.strip().split("\n") if f.strip()]
            changed_files = list(set(changed_files + uncommitted))

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        if not changed_files:
            print(f"  [code] {name}: no changes since last sync")
            return []

        # Filter to relevant extensions and include_paths
        docs = []
        for rel_path in changed_files:
            file_path = base / rel_path
            if not file_path.exists() or not file_path.is_file():
                continue
            if file_path.suffix not in extensions:
                continue
            if include_paths:
                if not any(rel_path.startswith(ip) for ip in include_paths):
                    continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            docs.append(Document(
                source=f"code:{name}",
                doc_id=f"{name}:{rel_path}",
                title=rel_path,
                content=content,
                metadata={
                    "project": name,
                    "file_path": rel_path,
                    "full_path": str(file_path),
                    "extension": file_path.suffix,
                    "language": proj.get("language", ""),
                    "lines": content.count("\n") + 1,
                    "incremental": True,
                },
            ))

        # Save current HEAD commit for next incremental
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5, cwd=str(base),
            )
            if head.returncode == 0:
                state_file.parent.mkdir(parents=True, exist_ok=True)
                state_file.write_text(head.stdout.strip())
        except Exception:
            pass

        print(f"  [code] {name}: {len(docs)} changed files (incremental)")
        return docs

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

    def _chunk_markdown_doc(self, doc: Document) -> list[Chunk]:
        """Chunk markdown docs by ## headers. Tags with doc_type for priority."""
        file_path = doc.metadata.get("file_path", "").lower()

        # Detect doc type from filename
        doc_type = "documentation"
        if "business-logic" in file_path:
            doc_type = "business-logic"
        elif "api-spec" in file_path:
            doc_type = "api-spec"
        elif "readme" in file_path:
            doc_type = "readme"
        elif "claude" in file_path or "ai.md" in file_path:
            doc_type = "project-guide"

        content = doc.content
        sections = re.split(r'^(#{1,3}\s+.+)$', content, flags=re.MULTILINE)

        chunks = []
        current_header = f"[{doc_type}] {doc.title}"
        current_text = ""

        for part in sections:
            if re.match(r'^#{1,3}\s+', part):
                # Save previous section
                if current_text.strip():
                    chunks.append(self._make_chunk(
                        doc, current_text.strip(), current_header,
                        extra_meta={"doc_type": doc_type, "priority": "high"},
                    ))
                current_header = part.strip().lstrip("#").strip()
                current_text = part + "\n"
            else:
                current_text += part

        # Last section
        if current_text.strip():
            chunks.append(self._make_chunk(
                doc, current_text.strip(), current_header,
                extra_meta={"doc_type": doc_type, "priority": "high"},
            ))

        # If no sections found, treat whole file as one chunk
        if not chunks:
            chunks.append(self._make_chunk(
                doc, content, f"[{doc_type}] {doc.title}",
                extra_meta={"doc_type": doc_type, "priority": "high"},
            ))

        return chunks

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

    def _make_chunk(self, doc: Document, text: str, label: str,
                    extra_meta: dict | None = None) -> Chunk:
        """Create a chunk with full metadata for code search."""
        meta = {
            **doc.metadata,
            "chunk_label": label,
            "source": doc.source,
        }
        if extra_meta:
            meta.update(extra_meta)
        return Chunk(
            text=f"[{doc.metadata['project']}:{doc.metadata['file_path']}] {label}\n\n{text}",
            metadata=meta,
        )
