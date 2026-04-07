"""Unit tests for LLM-based message router.

Tests regex social fast-path, LLM call success/failure, JSON parsing,
mode classification from source, and RouterResult validation.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict

from ..llm_router import LLMRouter, RouterResult
from ..llm_client import LLMResponse


def make_llm_response(text: str) -> LLMResponse:
    """Create a mock LLMResponse."""
    return LLMResponse(
        text=text,
        confidence=0.9,
        evidence=[],
        model_used="claude-haiku-4-5-20251001",
        tokens_used=50,
        latency_ms=100,
    )


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    return AsyncMock()


@pytest.fixture
def router(mock_llm_client):
    """Create a router with mocked LLM client."""
    router = LLMRouter(mock_llm_client)
    # Mock the prompt loader to avoid file I/O
    router._system_prompt = "Test prompt"
    return router


class TestSocialFastPath:
    """Test regex social fast-path (no LLM call)."""

    @pytest.mark.asyncio
    async def test_social_hi_skips_llm(self, router, mock_llm_client):
        """'hi' should match social pattern and skip LLM."""
        event = {
            "body": "hi",
            "source": "matrix",
            "member_count": 0,
            "is_group": False,
        }
        result = await router.route(event)
        assert result is not None
        assert result.intent == "social"
        assert result.priority == "low"
        mock_llm_client.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_social_thanks_skips_llm(self, router, mock_llm_client):
        """'thanks' should match social pattern and skip LLM."""
        event = {
            "body": "thanks!",
            "source": "cli",
            "member_count": 0,
        }
        result = await router.route(event)
        assert result is not None
        assert result.intent == "social"
        mock_llm_client.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_social_oke_skips_llm(self, router, mock_llm_client):
        """'oke' should match social pattern and skip LLM."""
        event = {
            "body": "oke",
            "source": "dashboard",
            "member_count": 0,
        }
        result = await router.route(event)
        assert result is not None
        assert result.intent == "social"
        mock_llm_client.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_social_vietnamese_chao(self, router, mock_llm_client):
        """Vietnamese 'chào' should match social pattern and skip LLM."""
        event = {
            "body": "chào",
            "source": "matrix",
            "member_count": 0,
        }
        result = await router.route(event)
        assert result is not None
        assert result.intent == "social"
        mock_llm_client.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_social_in_dm_should_respond(self, router, mock_llm_client):
        """Social in DM should always respond."""
        event = {
            "body": "hi",  # Minimal social message to match pattern
            "source": "matrix",
            "member_count": 2,  # DM
            "is_group": False,
            "is_mentioned": False,
        }
        result = await router.route(event)
        # Social pattern should match and skip LLM
        assert result is not None
        assert result.intent == "social"
        assert result.should_respond is True

    @pytest.mark.asyncio
    async def test_social_in_group_not_mentioned_skip(self, router, mock_llm_client):
        """Social in group WITHOUT mention should skip."""
        event = {
            "body": "thanks!",
            "source": "matrix",
            "member_count": 5,
            "is_group": True,
            "is_mentioned": False,
        }
        result = await router.route(event)
        assert result.should_respond is False

    @pytest.mark.asyncio
    async def test_social_in_group_with_mention_respond(self, router, mock_llm_client):
        """Social in group WITH mention should respond."""
        event = {
            "body": "hi",  # Minimal social message to match pattern
            "source": "matrix",
            "member_count": 5,
            "is_group": True,
            "is_mentioned": True,
        }
        result = await router.route(event)
        # Social pattern should match and skip LLM
        assert result is not None
        assert result.intent == "social"
        assert result.should_respond is True


class TestModeClassificationFromSource:
    """Test mode classification from event source."""

    @pytest.mark.asyncio
    async def test_matrix_source_is_outward(self, router, mock_llm_client):
        """Matrix source should set mode='outward'."""
        mock_llm_client.generate.return_value = make_llm_response(
            '{"mode": "outward", "intent": "question", "should_respond": true, '
            '"priority": "normal", "reasoning": "test"}'
        )
        event = {
            "body": "what is this?",
            "source": "matrix",
        }
        result = await router.route(event)
        assert result.mode == "outward"

    @pytest.mark.asyncio
    async def test_cli_source_is_inward(self, router, mock_llm_client):
        """CLI source should set mode='inward'."""
        mock_llm_client.generate.return_value = make_llm_response(
            '{"mode": "inward", "intent": "question", "should_respond": true, '
            '"priority": "normal", "reasoning": "test"}'
        )
        event = {
            "body": "explain this code",
            "source": "cli",
        }
        result = await router.route(event)
        assert result.mode == "inward"


class TestLLMCall:
    """Test LLM call success and response parsing."""

    @pytest.mark.asyncio
    async def test_valid_json_response_parsed(self, router, mock_llm_client):
        """Valid JSON response should be parsed correctly."""
        expected_response = {
            "mode": "outward",
            "intent": "question",
            "should_respond": True,
            "priority": "high",
            "reasoning": "This is a work question",
        }
        mock_llm_client.generate.return_value = make_llm_response(
            json.dumps(expected_response)
        )
        event = {
            "body": "When will the project be done?",
            "source": "matrix",
        }
        result = await router.route(event)
        assert result is not None
        assert result.mode == expected_response["mode"]
        assert result.intent == expected_response["intent"]
        assert result.should_respond == expected_response["should_respond"]
        assert result.priority == expected_response["priority"]

    @pytest.mark.asyncio
    async def test_json_with_markdown_fences(self, router, mock_llm_client):
        """JSON wrapped in markdown code fences should be parsed."""
        json_str = '{"mode": "inward", "intent": "request", "should_respond": true, "priority": "normal", "reasoning": "test"}'
        mock_llm_client.generate.return_value = make_llm_response(
            f"```json\n{json_str}\n```"
        )
        event = {
            "body": "help me debug",
            "source": "cli",
        }
        result = await router.route(event)
        assert result is not None
        assert result.mode == "inward"
        assert result.intent == "request"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self, router, mock_llm_client):
        """Invalid JSON should return None (fallback to regex)."""
        mock_llm_client.generate.return_value = make_llm_response(
            "This is not valid JSON {bad json"
        )
        event = {
            "body": "what is this?",
            "source": "matrix",
        }
        result = await router.route(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_timeout_returns_none(self, router, mock_llm_client):
        """LLM timeout should return None (fallback to regex)."""
        async def timeout_async(*args, **kwargs):
            await asyncio.sleep(10)

        mock_llm_client.generate.side_effect = timeout_async
        event = {
            "body": "what is this?",
            "source": "matrix",
        }
        result = await router.route(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self, router, mock_llm_client):
        """LLM exception should return None (fallback to regex)."""
        mock_llm_client.generate.side_effect = Exception("Network error")
        event = {
            "body": "what is this?",
            "source": "matrix",
        }
        result = await router.route(event)
        assert result is None


class TestInvalidResponses:
    """Test handling of invalid/hallucinated LLM outputs."""

    @pytest.mark.asyncio
    async def test_invalid_mode_returns_none(self, router, mock_llm_client):
        """Invalid mode value should return None."""
        mock_llm_client.generate.return_value = make_llm_response(
            '{"mode": "sideways", "intent": "question", "should_respond": true, '
            '"priority": "normal", "reasoning": "test"}'
        )
        event = {"body": "what is this?", "source": "matrix"}
        result = await router.route(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_intent_returns_none(self, router, mock_llm_client):
        """Invalid intent value should return None."""
        mock_llm_client.generate.return_value = make_llm_response(
            '{"mode": "outward", "intent": "gibberish", "should_respond": true, '
            '"priority": "normal", "reasoning": "test"}'
        )
        event = {"body": "what is this?", "source": "matrix"}
        result = await router.route(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_priority_returns_none(self, router, mock_llm_client):
        """Invalid priority value should return None."""
        mock_llm_client.generate.return_value = make_llm_response(
            '{"mode": "outward", "intent": "question", "should_respond": true, '
            '"priority": "urgent", "reasoning": "test"}'
        )
        event = {"body": "what is this?", "source": "matrix"}
        result = await router.route(event)
        assert result is None


class TestEmptyOrMissingBody:
    """Test handling of empty/missing message body."""

    @pytest.mark.asyncio
    async def test_empty_body_returns_none(self, router, mock_llm_client):
        """Empty body should return None."""
        event = {"body": "", "source": "matrix"}
        result = await router.route(event)
        assert result is None
        mock_llm_client.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_only_body_returns_none(self, router, mock_llm_client):
        """Whitespace-only body should return None."""
        event = {"body": "   \t\n  ", "source": "matrix"}
        result = await router.route(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_body_key_returns_none(self, router, mock_llm_client):
        """Missing body key should return None."""
        event = {"source": "matrix"}
        result = await router.route(event)
        assert result is None


class TestRouterResultFields:
    """Test RouterResult field validation and defaults."""

    @pytest.mark.asyncio
    async def test_router_result_structure(self, router, mock_llm_client):
        """RouterResult should have all required fields."""
        mock_llm_client.generate.return_value = make_llm_response(
            '{"mode": "outward", "intent": "question", "should_respond": false, '
            '"priority": "low", "reasoning": "Just a greeting"}'
        )
        event = {"body": "hello there", "source": "matrix"}
        result = await router.route(event)

        assert result is not None
        assert hasattr(result, "mode")
        assert hasattr(result, "intent")
        assert hasattr(result, "should_respond")
        assert hasattr(result, "priority")
        assert hasattr(result, "reasoning")
        assert isinstance(result.should_respond, bool)
        assert isinstance(result.priority, str)

    @pytest.mark.asyncio
    async def test_should_respond_defaults_to_true(self, router, mock_llm_client):
        """Missing should_respond should default to True."""
        mock_llm_client.generate.return_value = make_llm_response(
            '{"mode": "outward", "intent": "question", '
            '"priority": "normal", "reasoning": "test"}'
        )
        event = {"body": "what is this?", "source": "matrix"}
        result = await router.route(event)
        assert result.should_respond is True

    @pytest.mark.asyncio
    async def test_priority_defaults_to_normal(self, router, mock_llm_client):
        """Missing priority should default to 'normal'."""
        mock_llm_client.generate.return_value = make_llm_response(
            '{"mode": "outward", "intent": "question", "should_respond": true, '
            '"reasoning": "test"}'
        )
        event = {"body": "what is this?", "source": "matrix"}
        result = await router.route(event)
        assert result.priority == "normal"


class TestBuildUserMessage:
    """Test the user message construction for LLM prompt."""

    def test_truncates_long_body(self, router):
        """Long body should be truncated to 200 chars."""
        long_body = "a" * 300
        event = {
            "body": long_body,
            "room_name": "test-room",
            "member_count": 3,
            "sender_id": "user@example",
            "source": "matrix",
        }
        message = router._build_user_message(event, long_body)
        assert len(long_body[:200]) == 200
        assert long_body[:200] in message

    def test_includes_room_info(self, router):
        """User message should include room information."""
        event = {
            "body": "hello",
            "room_name": "Engineering Team",
            "member_count": 5,
            "sender_id": "alice@example",
            "source": "matrix",
        }
        message = router._build_user_message(event, "hello")
        assert "Engineering Team" in message
        assert "5" in message

    def test_handles_missing_room_name(self, router):
        """User message should handle missing room name gracefully."""
        event = {
            "body": "hello",
            "room_name": None,
            "member_count": 2,
            "sender_id": "bob@example",
            "source": "matrix",
        }
        message = router._build_user_message(event, "hello")
        # Should not crash, should include other info
        assert "bob@example" in message

    def test_identifies_group_vs_dm(self, router):
        """User message should correctly identify group vs DM."""
        dm_event = {
            "body": "hello",
            "member_count": 2,
            "is_group": False,
            "source": "matrix",
        }
        dm_msg = router._build_user_message(dm_event, "hello")
        assert "dm" in dm_msg.lower()

        group_event = {
            "body": "hello",
            "member_count": 5,
            "is_group": True,
            "source": "matrix",
        }
        group_msg = router._build_user_message(group_event, "hello")
        assert "group" in group_msg.lower()
