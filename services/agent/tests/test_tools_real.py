"""Integration tests for all 17 agent tools with real database and services.

Tests each tool individually with real data:
- Real Postgres database (postgresql://openkhang:openkhang@localhost:5433/openkhang)
- Real CLI tools (jira, glab) where applicable
- Live external services (web_fetch, web_search)

Run with: pytest test_tools_real.py -v -s --tb=long -k integration
"""

import time
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

from ..tools import (
    SearchKnowledgeTool,
    SearchCodeTool,
    GetSenderContextTool,
    GetRoomHistoryTool,
    GetThreadMessagesTool,
    SendMessageTool,
    LookupPersonTool,
    CreateDraftTool,
    ListDraftsTool,
    ManageDraftTool,
    SearchEventsTool,
    SearchJiraTool,
    SearchGitLabTool,
    WebFetchTool,
    WebSearchTool,
    MemoryNoteTool,
    ShellExecTool,
)
from ...memory.config import MemoryConfig
from ...memory.client import MemoryClient
from ..draft_queue import DraftQueue


# ============================================================================
# FIXTURES — all async, function-scoped (avoids event loop conflicts)
# ============================================================================

@pytest_asyncio.fixture
async def memory_client():
    """Real memory client connected to live Postgres + pgvector."""
    try:
        config = MemoryConfig.from_env()
        client = MemoryClient(config)
        await client.connect()
        yield client
        await client.close()
    except Exception:
        yield None


@pytest_asyncio.fixture
async def draft_queue():
    """Real draft queue connected to live Postgres."""
    try:
        config = MemoryConfig.from_env()
        queue = DraftQueue(database_url=config.database_url)
        await queue.connect()
        yield queue
        await queue.close()
    except Exception:
        yield None


@pytest_asyncio.fixture
async def real_sender_id(draft_queue):
    """Fetch a real sender_id from the database."""
    if draft_queue is None or draft_queue._pool is None:
        return None
    try:
        return await draft_queue._pool.fetchval(
            "SELECT DISTINCT actor FROM events WHERE source='chat' LIMIT 1"
        )
    except Exception:
        return None


@pytest_asyncio.fixture
async def real_room_id(draft_queue):
    """Fetch a real room_id from the database."""
    if draft_queue is None or draft_queue._pool is None:
        return None
    try:
        return await draft_queue._pool.fetchval(
            "SELECT DISTINCT payload->>'room_id' FROM events "
            "WHERE source='chat' AND payload->>'room_id' IS NOT NULL LIMIT 1"
        )
    except Exception:
        return None


# ============================================================================
# MEMORY TOOLS
# ============================================================================

@pytest.mark.integration
class TestSearchKnowledgeTool:
    @pytest.mark.asyncio
    async def test_search_real_data(self, memory_client):
        if memory_client is None:
            pytest.skip("Memory client not available")
        tool = SearchKnowledgeTool(memory_client)
        start = time.monotonic()
        result = await tool.execute(query="payment transaction", limit=5)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, list)
        print(f"\n  search_knowledge: {len(result)} results in {elapsed:.0f}ms")
        if result:
            print(f"  top: {str(result[0])[:150]}")


@pytest.mark.integration
class TestSearchCodeTool:
    @pytest.mark.asyncio
    async def test_search_code_real(self, memory_client):
        if memory_client is None:
            pytest.skip("Memory client not available")
        tool = SearchCodeTool(memory_client)
        start = time.monotonic()
        result = await tool.execute(query="payment", limit=5)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, list)
        print(f"\n  search_code: {len(result)} results in {elapsed:.0f}ms")


@pytest.mark.integration
class TestGetSenderContextTool:
    @pytest.mark.asyncio
    async def test_real_sender(self, memory_client, real_sender_id):
        if memory_client is None:
            pytest.skip("Memory client not available")
        tool = GetSenderContextTool(memory_client)
        sender_id = real_sender_id or "test_user"
        start = time.monotonic()
        result = await tool.execute(sender_id=sender_id)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, list)
        print(f"\n  get_sender_context({sender_id[:30]}): {len(result)} results in {elapsed:.0f}ms")


@pytest.mark.integration
class TestGetRoomHistoryTool:
    @pytest.mark.asyncio
    async def test_real_room(self, memory_client, real_room_id):
        if memory_client is None:
            pytest.skip("Memory client not available")
        tool = GetRoomHistoryTool(memory_client)
        room_id = real_room_id or "!test:localhost"
        start = time.monotonic()
        result = await tool.execute(room_id=room_id, limit=10)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, list)
        print(f"\n  get_room_history({room_id[:30]}): {len(result)} msgs in {elapsed:.0f}ms")


@pytest.mark.integration
class TestGetThreadMessagesTool:
    @pytest.mark.asyncio
    async def test_nonexistent_thread(self, memory_client):
        if memory_client is None:
            pytest.skip("Memory client not available")
        tool = GetThreadMessagesTool(memory_client)
        start = time.monotonic()
        result = await tool.execute(thread_event_id="$nonexistent_thread", limit=10)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, list)
        print(f"\n  get_thread_messages: {len(result)} results in {elapsed:.0f}ms (expected empty)")


@pytest.mark.integration
class TestLookupPersonTool:
    @pytest.mark.asyncio
    async def test_lookup_person(self):
        """LookupPersonTool takes no __init__ args — uses room_lookup module."""
        tool = LookupPersonTool()
        start = time.monotonic()
        result = await tool.execute(name="Khanh")
        elapsed = (time.monotonic() - start) * 1000
        # Returns dict or None
        assert result is None or isinstance(result, dict)
        print(f"\n  lookup_person('Khanh'): {result} in {elapsed:.0f}ms")


# ============================================================================
# DRAFT TOOLS
# ============================================================================

@pytest.mark.integration
class TestListDraftsTool:
    @pytest.mark.asyncio
    async def test_list_pending(self, draft_queue):
        if draft_queue is None:
            pytest.skip("Draft queue not available")
        tool = ListDraftsTool(draft_queue)
        start = time.monotonic()
        result = await tool.execute(status="pending", limit=10)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, list)
        print(f"\n  list_drafts(pending): {len(result)} drafts in {elapsed:.0f}ms")
        if result:
            print(f"  first: {str(result[0])[:200]}")


@pytest.mark.integration
class TestSearchEventsTool:
    @pytest.mark.asyncio
    async def test_recent_events(self, draft_queue):
        if draft_queue is None:
            pytest.skip("Draft queue not available")
        tool = SearchEventsTool(draft_queue)
        start = time.monotonic()
        result = await tool.execute(since_hours=168, limit=20)  # last week
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, list)
        print(f"\n  search_events(168h): {len(result)} events in {elapsed:.0f}ms")
        if result:
            print(f"  first: {str(result[0])[:200]}")


# ============================================================================
# SCHEMA-ONLY TOOLS (skip actual execution)
# ============================================================================

class TestSchemaChecks:
    def test_send_message_schema(self):
        tool = SendMessageTool(AsyncMock())
        assert tool.name == "send_message"
        assert "room_id" in tool.parameters["properties"]
        print(f"\n  send_message: schema valid")

    def test_create_draft_schema(self):
        tool = CreateDraftTool(AsyncMock())
        assert tool.name == "create_draft"
        assert "draft_text" in tool.parameters["properties"]
        print(f"\n  create_draft: schema valid")

    def test_manage_draft_schema(self):
        tool = ManageDraftTool(AsyncMock(), AsyncMock())
        assert tool.name == "manage_draft"
        assert "action" in tool.parameters["properties"]
        print(f"\n  manage_draft: schema valid")


# ============================================================================
# CLI TOOLS
# ============================================================================

@pytest.mark.integration
class TestSearchJiraTool:
    @pytest.mark.asyncio
    async def test_jira_cli(self):
        tool = SearchJiraTool()
        start = time.monotonic()
        result = await tool.execute(query="type = Bug", limit=5)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, (list, dict))
        print(f"\n  search_jira: returned in {elapsed:.0f}ms")
        print(f"  result: {str(result)[:300]}")


@pytest.mark.integration
class TestSearchGitLabTool:
    @pytest.mark.asyncio
    async def test_gitlab_cli(self):
        tool = SearchGitLabTool()
        start = time.monotonic()
        result = await tool.execute(query="opened", limit=5)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, (list, dict))
        print(f"\n  search_gitlab: returned in {elapsed:.0f}ms")
        print(f"  result: {str(result)[:300]}")


# ============================================================================
# WEB TOOLS
# ============================================================================

@pytest.mark.integration
class TestWebFetchTool:
    @pytest.mark.asyncio
    async def test_fetch_example_com(self):
        tool = WebFetchTool()
        start = time.monotonic()
        result = await tool.execute(url="https://example.com", max_chars=1000)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, str)
        assert len(result) > 0
        print(f"\n  web_fetch(example.com): {len(result)} chars in {elapsed:.0f}ms")

    @pytest.mark.asyncio
    async def test_fetch_invalid_url(self):
        tool = WebFetchTool()
        result = await tool.execute(url="https://invalid-domain-12345.invalid/")
        assert isinstance(result, str)
        # Should contain error, not crash
        assert "error" in result.lower() or "Error" in result
        print(f"\n  web_fetch(invalid): graceful error")


@pytest.mark.integration
class TestWebSearchTool:
    @pytest.mark.asyncio
    async def test_search_real(self):
        tool = WebSearchTool()
        start = time.monotonic()
        result = await tool.execute(query="python asyncio tutorial", limit=5)
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, list)
        print(f"\n  web_search: {len(result)} results in {elapsed:.0f}ms")
        if result:
            print(f"  first: {result[0]}")


# ============================================================================
# MEMORY NOTE TOOL
# ============================================================================

@pytest.mark.integration
class TestMemoryNoteTool:
    @pytest.mark.asyncio
    async def test_save_note(self, memory_client):
        if memory_client is None:
            pytest.skip("Memory client not available")
        tool = MemoryNoteTool(memory_client)
        test_note = f"Integration test note at {datetime.now(timezone.utc).isoformat()}"
        start = time.monotonic()
        result = await tool.execute(content=test_note, category="test")
        elapsed = (time.monotonic() - start) * 1000
        assert isinstance(result, str)
        assert "saved" in result.lower()
        print(f"\n  memory_note: saved in {elapsed:.0f}ms")


# ============================================================================
# SHELL EXEC TOOL
# ============================================================================

@pytest.mark.integration
class TestShellExecTool:
    @pytest.mark.asyncio
    async def test_safe_echo(self):
        tool = ShellExecTool()
        result = await tool.execute(command="echo hello world")
        assert result["stdout"].strip() == "hello world"
        assert result["return_code"] == 0
        print(f"\n  shell_exec(echo): OK")

    @pytest.mark.asyncio
    async def test_safe_date(self):
        tool = ShellExecTool()
        result = await tool.execute(command="date")
        assert result["return_code"] == 0
        assert len(result["stdout"]) > 0
        print(f"\n  shell_exec(date): {result['stdout'].strip()}")

    @pytest.mark.asyncio
    async def test_safe_ls(self):
        tool = ShellExecTool()
        result = await tool.execute(
            command="ls services/agent/tools/ | wc -l",
            working_dir="/Users/khanh.bui2/Projects/openkhang",
        )
        assert result["return_code"] == 0
        count = int(result["stdout"].strip())
        assert count >= 17  # at least 17 tool files
        print(f"\n  shell_exec(ls tools): {count} files")

    @pytest.mark.asyncio
    async def test_blocked_rm_rf(self):
        tool = ShellExecTool()
        result = await tool.execute(command="rm -rf /tmp/test")
        assert result["return_code"] == -1
        assert "Blocked" in result["stderr"]
        print(f"\n  shell_exec(rm -rf): BLOCKED")

    @pytest.mark.asyncio
    async def test_blocked_sudo(self):
        tool = ShellExecTool()
        result = await tool.execute(command="sudo ls /root")
        assert result["return_code"] == -1
        assert "Blocked" in result["stderr"]
        print(f"\n  shell_exec(sudo): BLOCKED")

    @pytest.mark.asyncio
    async def test_blocked_git_push(self):
        tool = ShellExecTool()
        result = await tool.execute(command="git push origin main")
        assert result["return_code"] == -1
        assert "Blocked" in result["stderr"]
        print(f"\n  shell_exec(git push): BLOCKED")

    @pytest.mark.asyncio
    async def test_timeout(self):
        tool = ShellExecTool()
        start = time.monotonic()
        result = await tool.execute(command="sleep 30", timeout=2)
        elapsed = (time.monotonic() - start) * 1000
        assert result["return_code"] == -1
        assert "timed out" in result["stderr"].lower()
        assert elapsed < 5000  # should timeout around 2s, not 30s
        print(f"\n  shell_exec(timeout): caught in {elapsed:.0f}ms")


# ============================================================================
# TOOL COUNT SUMMARY
# ============================================================================

class TestToolSummary:
    def test_total_tool_count(self):
        """Verify all 17 tools are importable."""
        tools = [
            SearchKnowledgeTool, SearchCodeTool, GetSenderContextTool,
            GetRoomHistoryTool, GetThreadMessagesTool, SendMessageTool,
            LookupPersonTool, CreateDraftTool, ListDraftsTool,
            ManageDraftTool, SearchEventsTool, SearchJiraTool,
            SearchGitLabTool, WebFetchTool, WebSearchTool,
            MemoryNoteTool, ShellExecTool,
        ]
        assert len(tools) == 17
        print(f"\n  All 17 tools importable")
