"""Unit tests for agent loop execution.

Tests mode-specific configuration presets, single-call mode (outward),
and the NotImplementedError guard for tool-calling (now handled by SDK).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from ..agent_loop import (
    AgentLoop,
    AgentLoopResult,
    ModeConfig,
    ToolCallRecord,
)
from ..llm_client import LLMResponse


def make_llm_response(text: str = "Test response") -> LLMResponse:
    """Create a mock LLMResponse."""
    return LLMResponse(
        text=text,
        confidence=0.9,
        evidence=[],
        model_used="claude-sonnet-4-20250514",
        tokens_used=100,
        latency_ms=200,
    )


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_tools():
    """Create mock tools registry."""
    tools = MagicMock()
    tools.list_descriptions = MagicMock(return_value=[
        {"name": "search", "description": "Search function"},
        {"name": "get_info", "description": "Get info function"},
    ])
    tools.execute = AsyncMock()
    return tools


@pytest.fixture
def agent_loop():
    """Create an agent loop instance."""
    return AgentLoop()


class TestModeConfigPresets:
    """Test ModeConfig factory methods for mode presets."""

    def test_outward_config_no_tools(self):
        """Outward mode should not use tools."""
        config = ModeConfig.outward()
        assert config.use_tools is False
        assert config.max_iterations == 1

    def test_outward_config_single_call(self):
        """Outward mode should use single LLM call."""
        config = ModeConfig.outward()
        assert config.use_tools is False
        assert config.require_structured is True

    def test_outward_config_deterministic(self):
        """Outward mode should be deterministic (low temperature)."""
        config = ModeConfig.outward()
        assert config.temperature == 0.3
        assert config.require_structured is True

    def test_inward_config_with_tools(self):
        """Inward mode should use tools."""
        config = ModeConfig.inward()
        assert config.use_tools is True
        assert config.require_structured is False

    def test_inward_config_iterations(self):
        """Inward mode should support multiple iterations."""
        config = ModeConfig.inward()
        assert config.max_iterations == 10
        assert config.use_tools is True

    def test_inward_config_blacklist(self):
        """Inward mode should blacklist send_message only; create_draft is allowed."""
        config = ModeConfig.inward()
        assert "send_message" in config.tool_blacklist
        assert "create_draft" not in config.tool_blacklist

    def test_inward_config_temperature(self):
        """Inward mode should be more creative (higher temperature)."""
        config = ModeConfig.inward()
        assert config.temperature == 0.5
        assert config.temperature > ModeConfig.outward().temperature

    def test_inward_config_timeout(self):
        """Inward mode should have longer timeout."""
        inward = ModeConfig.inward()
        outward = ModeConfig.outward()
        assert inward.timeout_seconds == 120
        assert outward.timeout_seconds == 60


class TestSingleLLMCallMode:
    """Test single LLM call execution (outward mode)."""

    @pytest.mark.asyncio
    async def test_single_call_returns_result(self, agent_loop, mock_llm_client):
        """Single call mode should return LLM response."""
        mock_llm_client.generate.return_value = make_llm_response("Hello there")

        config = ModeConfig.outward()
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
        ]
        result = await agent_loop.run(config, messages, mock_llm_client)

        assert result.text == "Hello there"
        assert result.iterations == 1
        mock_llm_client.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_call_passes_config_to_llm(self, agent_loop, mock_llm_client):
        """Config parameters should be passed to LLM."""
        mock_llm_client.generate.return_value = make_llm_response()

        config = ModeConfig.outward()
        messages = [{"role": "user", "content": "Test"}]
        await agent_loop.run(config, messages, mock_llm_client)

        # Check that config values were passed
        call_kwargs = mock_llm_client.generate.call_args.kwargs
        assert call_kwargs["temperature"] == config.temperature
        assert call_kwargs["max_tokens"] == config.max_tokens
        assert call_kwargs["require_structured"] is True

    @pytest.mark.asyncio
    async def test_single_call_ignores_tools(self, agent_loop, mock_llm_client, mock_tools):
        """Single call mode should ignore tools parameter."""
        mock_llm_client.generate.return_value = make_llm_response()

        config = ModeConfig.outward()
        messages = [{"role": "user", "content": "Test"}]
        result = await agent_loop.run(config, messages, mock_llm_client, tools=mock_tools)

        # Should not call tools.list_descriptions or tools.execute
        mock_tools.list_descriptions.assert_not_called()
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_single_call_preserves_response_fields(self, agent_loop, mock_llm_client):
        """All LLMResponse fields should be preserved in result."""
        response = LLMResponse(
            text="Result text",
            confidence=0.87,
            evidence=["fact1", "fact2"],
            model_used="claude-sonnet-4-20250514",
            tokens_used=256,
            latency_ms=350,
        )
        mock_llm_client.generate.return_value = response

        config = ModeConfig.outward()
        messages = [{"role": "user", "content": "Test"}]
        result = await agent_loop.run(config, messages, mock_llm_client)

        assert result.text == response.text
        assert result.confidence == response.confidence
        assert result.tokens_used == response.tokens_used
        assert result.model_used == response.model_used
        assert result.latency_ms == response.latency_ms


class TestToolCallingGuard:
    """Test that tool-calling mode raises NotImplementedError (now handled by SDK)."""

    @pytest.mark.asyncio
    async def test_tool_mode_raises_not_implemented(self, agent_loop, mock_llm_client, mock_tools):
        """Tool mode should raise NotImplementedError directing to SDKAgentRunner."""
        config = ModeConfig.inward()
        messages = [{"role": "user", "content": "Test"}]

        with pytest.raises(NotImplementedError, match="SDKAgentRunner"):
            await agent_loop.run(config, messages, mock_llm_client, tools=mock_tools)

    @pytest.mark.asyncio
    async def test_tool_mode_without_tools_falls_through(self, agent_loop, mock_llm_client):
        """Tool mode without tools param should fall through to single call."""
        mock_llm_client.generate.return_value = make_llm_response()

        config = ModeConfig.inward()
        messages = [{"role": "user", "content": "Test"}]

        # tools=None means use_tools is True but no tools provided → single call
        result = await agent_loop.run(config, messages, mock_llm_client, tools=None)
        assert result is not None
        assert isinstance(result, AgentLoopResult)


class TestToolCallRecord:
    """Test ToolCallRecord dataclass."""

    def test_tool_call_record_fields(self):
        """ToolCallRecord should have all required fields."""
        record = ToolCallRecord(
            tool_name="search",
            tool_input={"query": "test"},
            result="found it",
            success=True,
        )
        assert record.tool_name == "search"
        assert record.tool_input == {"query": "test"}
        assert record.result == "found it"
        assert record.success is True


class TestAgentLoopResultStructure:
    """Test AgentLoopResult field structure."""

    @pytest.mark.asyncio
    async def test_result_has_all_fields(self, agent_loop, mock_llm_client):
        """Result should have all required fields."""
        mock_llm_client.generate.return_value = make_llm_response()

        config = ModeConfig.outward()
        messages = [{"role": "user", "content": "Test"}]
        result = await agent_loop.run(config, messages, mock_llm_client)

        # Check all fields exist
        assert hasattr(result, "text")
        assert hasattr(result, "confidence")
        assert hasattr(result, "evidence")
        assert hasattr(result, "tokens_used")
        assert hasattr(result, "model_used")
        assert hasattr(result, "latency_ms")
        assert hasattr(result, "tool_calls")
        assert hasattr(result, "iterations")
        assert hasattr(result, "raw")

    @pytest.mark.asyncio
    async def test_result_defaults(self, agent_loop, mock_llm_client):
        """Result fields should have sensible defaults."""
        mock_llm_client.generate.return_value = make_llm_response()

        config = ModeConfig.outward()
        messages = [{"role": "user", "content": "Test"}]
        result = await agent_loop.run(config, messages, mock_llm_client)

        assert result.confidence >= 0.0
        assert result.confidence <= 1.0
        assert isinstance(result.tool_calls, list)
        assert result.iterations > 0
