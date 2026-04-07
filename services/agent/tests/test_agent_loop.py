"""Unit tests for unified agent loop execution.

Tests mode-specific configuration presets, single-call vs tool-calling modes,
timeouts, and config-driven parameter application.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ..agent_loop import (
    AgentLoop,
    AgentLoopResult,
    ModeConfig,
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

    def test_inward_config_tool_calling_loop(self):
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


class TestToolCallingMode:
    """Test tool-calling loop execution (inward mode)."""

    @pytest.mark.asyncio
    async def test_tool_mode_calls_tool_loop(self, agent_loop, mock_llm_client, mock_tools):
        """Tool mode should invoke tool-calling loop."""
        config = ModeConfig.inward()
        messages = [{"role": "user", "content": "Test"}]

        # Mock the tool calling loop
        with patch("services.agent.tool_calling_loop.run_tool_calling_loop") as mock_tool_loop:
            mock_result = MagicMock()
            mock_result.text = "Tool result"
            mock_result.tokens_used = 200
            mock_result.model_used = "test-model"
            mock_result.tool_calls = [{"name": "search"}]
            mock_result.iterations = 3
            mock_tool_loop.return_value = mock_result

            result = await agent_loop.run(config, messages, mock_llm_client, tools=mock_tools)

        assert result.text == "Tool result"
        assert result.iterations == 3
        assert len(result.tool_calls) > 0

    @pytest.mark.asyncio
    async def test_tool_mode_filters_blacklist(self, agent_loop, mock_llm_client, mock_tools):
        """Tool mode should filter tools using blacklist."""
        config = ModeConfig.inward()
        # Add draft tool to mock
        mock_tools.list_descriptions.return_value = [
            {"name": "search", "description": "Search"},
            {"name": "create_draft", "description": "Draft"},
            {"name": "send_message", "description": "Send"},
        ]
        messages = [{"role": "user", "content": "Test"}]

        with patch("services.agent.tool_calling_loop.run_tool_calling_loop") as mock_tool_loop:
            mock_result = MagicMock()
            mock_result.text = "Result"
            mock_result.tokens_used = 100
            mock_result.model_used = "test"
            mock_result.tool_calls = []
            mock_result.iterations = 1
            mock_tool_loop.return_value = mock_result

            await agent_loop.run(config, messages, mock_llm_client, tools=mock_tools)

        # Check the tool list passed to tool loop
        call_kwargs = mock_tool_loop.call_args.kwargs
        tool_defs = call_kwargs["tools"]
        tool_names = [t["name"] for t in tool_defs]

        # send_message is blacklisted; create_draft is now allowed in inward mode
        assert "search" in tool_names
        assert "create_draft" in tool_names
        assert "send_message" not in tool_names

    @pytest.mark.asyncio
    async def test_tool_mode_passes_config(self, agent_loop, mock_llm_client, mock_tools):
        """Config parameters should be passed to tool loop."""
        config = ModeConfig.inward()
        messages = [{"role": "user", "content": "Test"}]

        with patch("services.agent.tool_calling_loop.run_tool_calling_loop") as mock_tool_loop:
            mock_result = MagicMock()
            mock_result.text = "Result"
            mock_result.tokens_used = 100
            mock_result.model_used = "test"
            mock_result.tool_calls = []
            mock_result.iterations = 1
            mock_tool_loop.return_value = mock_result

            await agent_loop.run(config, messages, mock_llm_client, tools=mock_tools)

        call_kwargs = mock_tool_loop.call_args.kwargs
        assert call_kwargs["max_iterations"] == config.max_iterations
        assert call_kwargs["temperature"] == config.temperature
        assert call_kwargs["max_tokens"] == config.max_tokens


class TestTimeoutHandling:
    """Test timeout behavior in agent loop."""

    @pytest.mark.asyncio
    async def test_tool_mode_timeout_returns_graceful_message(
        self, agent_loop, mock_llm_client, mock_tools
    ):
        """Tool mode timeout should return graceful timeout message."""
        config = ModeConfig.inward()
        config.timeout_seconds = 120
        messages = [{"role": "user", "content": "Test"}]

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await agent_loop.run(config, messages, mock_llm_client, tools=mock_tools)

        # Should have timeout message
        assert "out of time" in result.text.lower()
        assert result.iterations == config.max_iterations

    @pytest.mark.asyncio
    async def test_timeout_uses_config_timeout_value(
        self, agent_loop, mock_llm_client, mock_tools
    ):
        """Timeout should use config.timeout_seconds."""
        config = ModeConfig.inward()
        config.timeout_seconds = 50
        messages = [{"role": "user", "content": "Test"}]

        with patch(
            "services.agent.tool_calling_loop.run_tool_calling_loop"
        ) as mock_tool_loop, patch("asyncio.wait_for") as mock_wait_for:
            mock_result = MagicMock()
            mock_result.text = "Result"
            mock_result.tokens_used = 100
            mock_result.model_used = "test"
            mock_result.tool_calls = []
            mock_result.iterations = 1
            mock_wait_for.return_value = mock_result

            await agent_loop.run(config, messages, mock_llm_client, tools=mock_tools)

        # Inner timeout = max(config.timeout_seconds - 10, 30) = 40
        call_kwargs = mock_wait_for.call_args.kwargs
        assert call_kwargs["timeout"] == 40


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


class TestNoToolsParameter:
    """Test behavior when tools parameter is not provided."""

    @pytest.mark.asyncio
    async def test_single_call_without_tools(self, agent_loop, mock_llm_client):
        """Single call mode without tools should work fine."""
        mock_llm_client.generate.return_value = make_llm_response()

        config = ModeConfig.outward()
        messages = [{"role": "user", "content": "Test"}]
        result = await agent_loop.run(config, messages, mock_llm_client, tools=None)

        assert result.text is not None
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_tool_mode_without_tools_parameter(self, agent_loop, mock_llm_client):
        """Tool mode without tools parameter should fall back gracefully."""
        config = ModeConfig.inward()
        messages = [{"role": "user", "content": "Test"}]

        # Should not crash, should be handled
        result = await agent_loop.run(config, messages, mock_llm_client, tools=None)

        # Should still return a result
        assert result is not None
        assert isinstance(result, AgentLoopResult)
