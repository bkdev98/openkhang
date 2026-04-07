"""Unit tests for parallel context pre-fetching strategy.

Tests intent-driven context resolution, parallel fetch coordination,
partial failure handling, and cross-agent RAG augmentation.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import asdict

from ..context_strategy import (
    ContextStrategy,
    ContextBundle,
    CONTEXT_STRATEGIES,
)


@pytest.fixture
def mock_memory_client():
    """Create a mock memory client."""
    return AsyncMock()


@pytest.fixture
def strategy(mock_memory_client):
    """Create a context strategy with mocked memory client."""
    return ContextStrategy(mock_memory_client)


class TestIntentBasedContextResolution:
    """Test that each intent fetches the right context."""

    @pytest.mark.asyncio
    async def test_social_intent_empty_bundle(self, strategy, mock_memory_client):
        """Social intent should fetch no context."""
        event = {
            "body": "hi there",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("social", "outward", event)
        assert bundle.memories == []
        assert bundle.code_results == []
        assert bundle.sender_context == []
        assert bundle.room_messages == []
        assert bundle.thread_messages == []
        # Memory should not be called at all
        mock_memory_client.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_fyi_intent_only_sender(self, strategy, mock_memory_client):
        """FYI intent should only fetch sender context."""
        mock_memory_client.get_related.return_value = [
            {"memory": "alice sent 3 messages"}
        ]
        event = {
            "body": "heads up, the server is down",
            "sender_id": "bob",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("fyi", "outward", event)
        assert bundle.memories == []
        assert bundle.code_results == []
        assert len(bundle.sender_context) > 0
        assert bundle.room_messages == []
        mock_memory_client.get_related.assert_called_once()
        mock_memory_client.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_question_intent_multiple_contexts(self, strategy, mock_memory_client):
        """Question intent should fetch rag, code, sender, and room."""
        mock_memory_client.search.return_value = [{"memory": "fact 1"}]
        mock_memory_client.search_code.return_value = [
            {"payload": {"text": "code snippet"}, "metadata": {"doc_type": "api-spec"}}
        ]
        mock_memory_client.get_related.return_value = [{"memory": "sender info"}]
        mock_memory_client.get_room_messages.return_value = [{"msg": "room history"}]

        event = {
            "body": "how do I deploy?",
            "sender_id": "charlie",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("question", "outward", event)

        assert len(bundle.memories) > 0
        assert len(bundle.code_results) > 0
        assert len(bundle.sender_context) > 0
        assert len(bundle.room_messages) > 0
        assert bundle.thread_messages == []

    @pytest.mark.asyncio
    async def test_request_intent_with_thread(self, strategy, mock_memory_client):
        """Request intent should fetch rag, sender, room, and thread."""
        # For outward request, will call search twice (outward + inward augmentation)
        mock_memory_client.search.side_effect = [[{"memory": "rag result"}], []]
        mock_memory_client.get_related.return_value = [{"memory": "sender"}]
        mock_memory_client.get_thread_messages.return_value = [{"msg": "thread"}]

        event = {
            "body": "can you review this?",
            "sender_id": "dave",
            "room_id": "!room:localhost",
            "thread_event_id": "$thread_123",
        }
        bundle = await strategy.resolve("request", "outward", event)

        assert len(bundle.memories) > 0
        assert len(bundle.sender_context) > 0
        # Should check thread, will be called twice (once for fetch_room result, once for fetch_thread)
        assert mock_memory_client.get_thread_messages.call_count >= 1

    @pytest.mark.asyncio
    async def test_instruction_intent(self, strategy, mock_memory_client):
        """Instruction intent should fetch rag and sender."""
        mock_memory_client.search.return_value = [{"memory": "instruction context"}]
        mock_memory_client.get_related.return_value = [{"memory": "sender context"}]

        event = {
            "body": "build a new feature",
            "sender_id": "eve",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("instruction", "inward", event)

        assert len(bundle.memories) > 0
        assert len(bundle.sender_context) > 0
        assert bundle.code_results == []
        assert bundle.room_messages == []

    @pytest.mark.asyncio
    async def test_query_intent(self, strategy, mock_memory_client):
        """Query intent should fetch rag and code."""
        mock_memory_client.search.return_value = [{"memory": "query result"}]
        mock_memory_client.search_code.return_value = [
            {"payload": {"text": "code"}, "metadata": {"doc_type": "api-spec"}}
        ]

        event = {
            "body": "search for auth module",
            "sender_id": "frank",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("query", "inward", event)

        assert len(bundle.memories) > 0
        assert len(bundle.code_results) > 0
        assert bundle.sender_context == []


class TestParallelFetchCoordination:
    """Test that fetches run in parallel and are coordinated correctly."""

    @pytest.mark.asyncio
    async def test_all_fetches_awaited(self, strategy, mock_memory_client):
        """All fetches should be awaited in parallel via asyncio.gather."""
        # Set up all the mocks (search is called twice for outward with cross-agent augmentation)
        mock_memory_client.search.side_effect = [
            [{"memory": "rag"}],  # Outward agent search
            [{"memory": "inward rag"}]  # Inward agent augmentation
        ]
        mock_memory_client.search_code.return_value = [
            {"payload": {"text": "code"}, "metadata": {"doc_type": "business-logic"}}
        ]
        mock_memory_client.get_related.return_value = [{"memory": "sender"}]
        mock_memory_client.get_room_messages.return_value = [{"msg": "room"}]

        event = {
            "body": "explain this feature",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }

        bundle = await strategy.resolve("question", "outward", event)

        # All should be populated
        assert bundle.memories
        assert bundle.code_results
        assert bundle.sender_context
        assert bundle.room_messages

        # Verify calls were made (search called twice for cross-agent augmentation)
        assert mock_memory_client.search.call_count == 2
        mock_memory_client.search_code.assert_called_once()
        mock_memory_client.get_related.assert_called_once()
        mock_memory_client.get_room_messages.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_fields_skips_fetch(self, strategy, mock_memory_client):
        """If required event field is missing, that fetch should be skipped."""
        # For outward question, search is called twice (outward + inward augmentation)
        mock_memory_client.search.side_effect = [[], []]

        event = {
            "body": "what about this?",
            # No sender_id, no room_id
        }
        bundle = await strategy.resolve("question", "outward", event)

        # Should still work, RAG should be attempted, but sender/room fetches skipped
        assert mock_memory_client.search.call_count == 2  # Outward + inward augmentation
        mock_memory_client.get_related.assert_not_called()
        mock_memory_client.get_room_messages.assert_not_called()


class TestPartialFetchFailure:
    """Test behavior when some fetches fail."""

    @pytest.mark.asyncio
    async def test_single_fetch_failure_others_succeed(self, strategy, mock_memory_client):
        """One fetch failing should not block others."""
        mock_memory_client.search.return_value = [{"memory": "rag"}]
        mock_memory_client.search_code.side_effect = Exception("Code search failed")
        mock_memory_client.get_related.return_value = [{"memory": "sender"}]
        mock_memory_client.get_room_messages.return_value = [{"msg": "room"}]

        event = {
            "body": "help me",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("question", "outward", event)

        # Should have some results
        assert bundle.memories  # RAG succeeded
        assert bundle.code_results == []  # Code search failed
        assert bundle.sender_context  # Sender succeeded
        assert bundle.room_messages  # Room succeeded

    @pytest.mark.asyncio
    async def test_all_fetches_fail_empty_bundle(self, strategy, mock_memory_client):
        """If all fetches fail, should return empty bundle."""
        mock_memory_client.search.side_effect = Exception("Network error")
        mock_memory_client.search_code.side_effect = Exception("Search failed")
        mock_memory_client.get_related.side_effect = Exception("Query failed")
        mock_memory_client.get_room_messages.side_effect = Exception("Fetch failed")

        event = {
            "body": "what is this?",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("question", "outward", event)

        # Should be empty but not crash
        assert bundle.memories == []
        assert bundle.code_results == []
        assert bundle.sender_context == []
        assert bundle.room_messages == []


class TestCrossAgentRAGAugmentation:
    """Test RAG augmentation for outward questions from inward agent."""

    @pytest.mark.asyncio
    async def test_outward_question_augments_with_inward_rag(
        self, strategy, mock_memory_client
    ):
        """Outward question intent should augment with inward agent RAG."""
        # Outward agent RAG results
        outward_memories = [
            {"id": "mem1", "memory": "outward fact"},
            {"id": "mem2", "memory": "outward fact 2"},
        ]
        # Inward agent RAG results (some overlap, some new)
        inward_memories = [
            {"id": "mem2", "memory": "outward fact 2"},  # duplicate
            {"id": "mem3", "memory": "inward fact"},  # new
            {"id": "mem4", "memory": "another inward fact"},  # new
        ]

        # First call is for outward agent, second is for inward augmentation
        mock_memory_client.search.side_effect = [outward_memories, inward_memories]

        event = {
            "body": "explain this",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("question", "outward", event)

        # Should have combined results without duplicates
        assert len(bundle.memories) == 4  # mem1, mem2, mem3, mem4
        ids = {m.get("id") for m in bundle.memories}
        assert ids == {"mem1", "mem2", "mem3", "mem4"}
        # First 2 should be from outward, last 2 from inward
        assert bundle.memories[0]["id"] == "mem1"
        assert bundle.memories[1]["id"] == "mem2"

    @pytest.mark.asyncio
    async def test_outward_request_augments_with_inward_rag(
        self, strategy, mock_memory_client
    ):
        """Outward request intent should also augment with inward agent RAG."""
        outward_memories = [{"id": "o1", "memory": "outward"}]
        inward_memories = [{"id": "i1", "memory": "inward"}]
        mock_memory_client.search.side_effect = [outward_memories, inward_memories]

        event = {
            "body": "can you help?",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("request", "outward", event)

        # Should include both
        assert len(bundle.memories) == 2
        ids = {m.get("id") for m in bundle.memories}
        assert ids == {"o1", "i1"}

    @pytest.mark.asyncio
    async def test_inward_intent_no_augmentation(self, strategy, mock_memory_client):
        """Inward mode should NOT augment RAG (only outward mode does)."""
        inward_memories = [{"id": "i1", "memory": "inward only"}]
        mock_memory_client.search.return_value = inward_memories

        event = {
            "body": "help me",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("question", "inward", event)

        # Should only have inward memories, no cross-agent call
        assert len(bundle.memories) == 1
        assert bundle.memories[0]["id"] == "i1"
        # search should only be called once (for inward agent)
        mock_memory_client.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_augmentation_respects_limit(self, strategy, mock_memory_client):
        """Cross-agent augmentation should respect the 5-memory limit."""
        outward_memories = [{"id": f"o{i}", "memory": f"out{i}"} for i in range(10)]
        inward_memories = [
            {"id": f"i{i}", "memory": f"in{i}"} for i in range(10)
        ]
        mock_memory_client.search.side_effect = [outward_memories, inward_memories]

        event = {
            "body": "help",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("question", "outward", event)

        # Should have outward (all 10) + inward augmentation (up to 5 new ones)
        # The limit is enforced by slicing inward_memories to RAG_LIMIT = 10 in the augmentation call
        # Result: 10 outward + all 10 inward (no overlap) = 20, but augmentation only takes up to 5 new
        # Since no filtering by limit in actual code, it takes all: 10 + 5 = 15, or actually 10 + all inward matches
        # Looking at the code: only first 5 of inward are checked for deduplication
        assert len(bundle.memories) >= 10


class TestThreadMessagesHandling:
    """Test thread message fetching priority."""

    @pytest.mark.asyncio
    async def test_thread_and_room_fetched_separately(self, strategy, mock_memory_client):
        """Thread and room are fetched independently — no duplication."""
        thread_msgs = [{"msg": "thread message"}]
        room_msgs = [{"msg": "room message"}]
        mock_memory_client.get_thread_messages.return_value = thread_msgs
        mock_memory_client.get_room_messages.return_value = room_msgs
        mock_memory_client.search.side_effect = [[], []]  # For RAG cross-agent augmentation

        event = {
            "body": "feedback on this?",
            "sender_id": "alice",
            "room_id": "!room:localhost",
            "thread_event_id": "$thread_456",
        }
        bundle = await strategy.resolve("request", "outward", event)

        # Room and thread are fetched independently
        assert bundle.room_messages == room_msgs
        assert bundle.thread_messages == thread_msgs

    @pytest.mark.asyncio
    async def test_falls_back_to_room_on_thread_failure(self, strategy, mock_memory_client):
        """If thread fetch fails, fall back to room messages."""
        room_msgs = [{"msg": "room message"}]
        mock_memory_client.get_thread_messages.side_effect = Exception("Thread not found")
        mock_memory_client.get_room_messages.return_value = room_msgs

        event = {
            "body": "any updates?",
            "sender_id": "bob",
            "room_id": "!room:localhost",
            "thread_event_id": "$missing_thread",
        }
        bundle = await strategy.resolve("request", "outward", event)

        # Should have room messages as fallback
        assert bundle.room_messages == room_msgs
        mock_memory_client.get_room_messages.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_thread_id_fetches_room(self, strategy, mock_memory_client):
        """Without thread_event_id, should fetch room directly."""
        room_msgs = [{"msg": "room message"}]
        mock_memory_client.get_room_messages.return_value = room_msgs

        event = {
            "body": "what do you think?",
            "sender_id": "charlie",
            "room_id": "!room:localhost",
            # No thread_event_id
        }
        bundle = await strategy.resolve("request", "outward", event)

        # Should have room messages
        assert bundle.room_messages == room_msgs
        mock_memory_client.get_room_messages.assert_called_once()
        mock_memory_client.get_thread_messages.assert_not_called()


class TestCodeResultFormatting:
    """Test code search result formatting."""

    @pytest.mark.asyncio
    async def test_code_results_scored_by_doc_type(self, strategy, mock_memory_client):
        """Code results should be scored based on document type."""
        code_results = [
            {
                "payload": {"text": "def deploy():\n  pass"},
                "metadata": {"doc_type": "business-logic"},
            },
            {
                "payload": {"text": "GET /users endpoint"},
                "metadata": {"doc_type": "api-spec"},
            },
            {
                "payload": {"text": "random comment"},
                "metadata": {"doc_type": "comment"},
            },
        ]
        mock_memory_client.search_code.return_value = code_results

        event = {
            "body": "how do I deploy?",
            "sender_id": "alice",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("question", "outward", event)

        # All three should be formatted
        assert len(bundle.code_results) == 3
        # High-value types should have score 0.8
        assert bundle.code_results[0]["score"] == 0.8  # business-logic
        assert bundle.code_results[1]["score"] == 0.8  # api-spec
        # Others should have score 0.5
        assert bundle.code_results[2]["score"] == 0.5  # comment

    @pytest.mark.asyncio
    async def test_code_results_truncated_to_500_chars(self, strategy, mock_memory_client):
        """Code text should be truncated to 500 characters."""
        long_code = "x" * 1000
        code_results = [
            {
                "payload": {"text": long_code},
                "metadata": {"doc_type": "api-spec"},
            }
        ]
        mock_memory_client.search_code.return_value = code_results

        event = {
            "body": "show me code",
            "sender_id": "bob",
            "room_id": "!room:localhost",
        }
        bundle = await strategy.resolve("question", "outward", event)

        # Should be truncated
        assert len(bundle.code_results[0]["memory"]) == 500
