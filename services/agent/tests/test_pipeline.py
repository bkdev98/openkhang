"""Integration tests for AgentPipeline with mocked LLM and memory backends.

Verifies full event → classify → RAG → prompt → LLM → route flow
without hitting any real API or database.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from ..pipeline import AgentPipeline, AgentResult
from ..llm_client import LLMClient, LLMResponse
from ..draft_queue import DraftQueue
from ..matrix_sender import MatrixSender
from ..confidence import ConfidenceScorer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_llm_response(text="oke mình check lại nhé", confidence=0.9, evidence=None):
    return LLMResponse(
        text=text,
        confidence=confidence,
        evidence=evidence or ["context fact 1"],
        model_used="claude-sonnet-4-20250514",
        tokens_used=150,
        latency_ms=800,
    )


@pytest.fixture
def mock_memory():
    m = AsyncMock()
    m.search.return_value = [
        {"memory": "Khanh works on payments backend", "score": 0.85},
        {"memory": "Alice is on the infra team", "score": 0.78},
        {"memory": "Sprint 42 ends Friday", "score": 0.70},
    ]
    m.get_related.return_value = [
        {"memory": "Alice asked about the deploy last week", "score": 0.80}
    ]
    m.add_event = AsyncMock(return_value="evt-123")
    return m


@pytest.fixture
def mock_llm():
    m = AsyncMock(spec=LLMClient)
    m.generate.return_value = make_llm_response()
    return m


@pytest.fixture
def mock_drafts():
    m = AsyncMock(spec=DraftQueue)
    m.add_draft.return_value = "draft-uuid-001"
    return m


@pytest.fixture
def mock_sender():
    m = AsyncMock(spec=MatrixSender)
    m.send.return_value = "$matrix-event-id"
    return m


@pytest.fixture
def pipeline(mock_memory, mock_llm, mock_drafts, mock_sender):
    p = AgentPipeline(
        memory_client=mock_memory,
        llm_client=mock_llm,
        draft_queue=mock_drafts,
        matrix_sender=mock_sender,
    )
    # Patch scorer to use low threshold so we can test both paths
    return p


# ---------------------------------------------------------------------------
# Outward mode — draft path (below threshold)
# ---------------------------------------------------------------------------

class TestOutwardDraftPath:
    @pytest.mark.asyncio
    async def test_low_confidence_creates_draft(self, pipeline, mock_llm, mock_drafts):
        mock_llm.generate.return_value = make_llm_response(confidence=0.3)

        result = await pipeline.process_event({
            "source": "matrix",
            "body": "Hey, what's the deadline for the payment migration?",
            "room_id": "!room1:localhost",
            "room_name": "Payments Team",
            "sender_id": "alice",
        })

        assert result.action == "drafted"
        assert result.draft_id == "draft-uuid-001"
        mock_drafts.add_draft.assert_called_once()

    @pytest.mark.asyncio
    async def test_draft_contains_correct_fields(self, pipeline, mock_llm, mock_drafts):
        mock_llm.generate.return_value = make_llm_response(
            text="mình check lại rồi nhé", confidence=0.3
        )

        result = await pipeline.process_event({
            "source": "matrix",
            "body": "Can you deploy today?",
            "room_id": "!room1:localhost",
            "sender_id": "bob",
        })

        call_kwargs = mock_drafts.add_draft.call_args.kwargs
        assert call_kwargs["room_id"] == "!room1:localhost"
        assert call_kwargs["draft_text"] == "mình check lại rồi nhé"
        assert "Can you deploy today?" in call_kwargs["original_message"]

    @pytest.mark.asyncio
    async def test_mode_is_outward(self, pipeline, mock_llm):
        mock_llm.generate.return_value = make_llm_response(confidence=0.3)

        result = await pipeline.process_event({
            "source": "matrix",
            "body": "Hi there",
            "room_id": "!room1:localhost",
            "sender_id": "carol",
        })

        assert result.mode == "outward"


# ---------------------------------------------------------------------------
# Outward mode — auto-send path (above threshold)
# ---------------------------------------------------------------------------

class TestOutwardAutoSendPath:
    @pytest.mark.asyncio
    async def test_high_confidence_triggers_send(self, pipeline, mock_llm, mock_sender):
        mock_llm.generate.return_value = make_llm_response(confidence=0.99)

        # Patch scorer to approve auto-send
        with patch.object(ConfidenceScorer, "should_auto_send", return_value=True):
            result = await pipeline.process_event({
                "source": "matrix",
                "body": "Thanks for the update!",
                "room_id": "!room1:localhost",
                "sender_id": "alice",
            })

        assert result.action == "auto_sent"
        assert result.matrix_event_id == "$matrix-event-id"
        mock_sender.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure_falls_back_to_draft(self, pipeline, mock_llm, mock_sender, mock_drafts):
        mock_llm.generate.return_value = make_llm_response(confidence=0.99)
        mock_sender.send.side_effect = RuntimeError("Rate limit exceeded")

        with patch.object(ConfidenceScorer, "should_auto_send", return_value=True):
            result = await pipeline.process_event({
                "source": "matrix",
                "body": "ok noted",
                "room_id": "!room1:localhost",
                "sender_id": "alice",
            })

        # Falls back to draft when send fails
        assert result.action == "drafted"
        mock_drafts.add_draft.assert_called_once()


# ---------------------------------------------------------------------------
# Inward mode
# ---------------------------------------------------------------------------

class TestInwardMode:
    @pytest.mark.asyncio
    async def test_inward_action_is_inward_response(self, pipeline, mock_llm):
        mock_llm.generate.return_value = make_llm_response(
            text="You have 3 open tickets in PROJ sprint.", confidence=0.85
        )

        result = await pipeline.process_event({
            "source": "cli",
            "body": "What's my sprint status?",
        })

        assert result.action == "inward_response"
        assert result.mode == "inward"

    @pytest.mark.asyncio
    async def test_inward_never_calls_matrix_sender(self, pipeline, mock_llm, mock_sender):
        mock_llm.generate.return_value = make_llm_response(confidence=0.99)

        result = await pipeline.process_event({
            "source": "dashboard",
            "body": "Show me pending drafts",
        })

        mock_sender.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_inward_uses_higher_temperature(self, pipeline, mock_llm):
        mock_llm.generate.return_value = make_llm_response(confidence=0.8)

        await pipeline.process_event({
            "source": "cli",
            "body": "Summarise my week",
        })

        call_kwargs = mock_llm.generate.call_args.kwargs
        assert call_kwargs.get("temperature", 0) == 0.5


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_empty_body_returns_error(self, pipeline):
        result = await pipeline.process_event({"source": "matrix", "body": ""})
        assert result.action == "error"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_error(self, pipeline, mock_llm):
        mock_llm.generate.side_effect = RuntimeError("Claude API down")

        result = await pipeline.process_event({
            "source": "matrix",
            "body": "Hello",
            "room_id": "!room1:localhost",
        })

        assert result.action == "error"
        assert "Claude API down" in result.error

    @pytest.mark.asyncio
    async def test_episodic_log_failure_does_not_crash(self, pipeline, mock_llm, mock_memory):
        mock_llm.generate.return_value = make_llm_response(confidence=0.3)
        mock_memory.add_event.side_effect = Exception("DB down")

        # Should not raise — episodic logging failure is swallowed
        result = await pipeline.process_event({
            "source": "matrix",
            "body": "hi",
            "room_id": "!room1:localhost",
            "sender_id": "alice",
        })

        assert result.action in ("drafted", "auto_sent", "inward_response")


# ---------------------------------------------------------------------------
# RAG and memory interactions
# ---------------------------------------------------------------------------

class TestMemoryUsage:
    @pytest.mark.asyncio
    async def test_memory_search_called_with_body(self, pipeline, mock_llm, mock_memory):
        mock_llm.generate.return_value = make_llm_response(confidence=0.3)

        await pipeline.process_event({
            "source": "matrix",
            "body": "payment migration status?",
            "room_id": "!room1:localhost",
            "sender_id": "alice",
        })

        mock_memory.search.assert_called_once()
        call_args = mock_memory.search.call_args
        assert "payment migration status?" in call_args.args or \
               call_args.kwargs.get("query") == "payment migration status?"

    @pytest.mark.asyncio
    async def test_sender_context_fetched(self, pipeline, mock_llm, mock_memory):
        mock_llm.generate.return_value = make_llm_response(confidence=0.3)

        await pipeline.process_event({
            "source": "matrix",
            "body": "hey",
            "room_id": "!room1:localhost",
            "sender_id": "alice",
        })

        mock_memory.get_related.assert_called_once()
        call_args = mock_memory.get_related.call_args
        assert "alice" in (call_args.args or [call_args.kwargs.get("entity", "")])
