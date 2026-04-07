"""Unit tests for confidence scoring and auto-send threshold logic."""

import pytest
from unittest.mock import patch, MagicMock
from ..confidence import (
    ConfidenceScorer,
    MODIFIER_MANY_MEMORIES,
    MODIFIER_DEADLINE_RISK,
    MODIFIER_UNKNOWN_SENDER,
    MODIFIER_LANGUAGE_MISMATCH,
)
from ..llm_client import LLMResponse


def make_response(confidence: float) -> LLMResponse:
    return LLMResponse(
        text="test reply",
        confidence=confidence,
        evidence=[],
        model_used="claude-sonnet-4-20250514",
        tokens_used=100,
        latency_ms=500,
    )


def make_memories(n: int) -> list[dict]:
    return [{"memory": f"fact {i}", "score": 0.9} for i in range(n)]


@pytest.fixture
def scorer():
    # Patch config loading to avoid filesystem dependency
    with patch.object(ConfidenceScorer, "_load_config", return_value={
        "default_threshold": 0.85,
        "graduated_spaces": {"!graduated:localhost": 0.65},
    }):
        yield ConfidenceScorer()


class TestConfidenceScore:
    def test_base_score_preserved(self, scorer):
        resp = make_response(0.7)
        result = scorer.score(resp, [], {})
        assert result == pytest.approx(0.7, abs=0.01)

    def test_many_memories_bonus(self, scorer):
        resp = make_response(0.7)
        result = scorer.score(resp, make_memories(3), {})
        assert result == pytest.approx(0.7 + MODIFIER_MANY_MEMORIES, abs=0.01)

    def test_two_memories_no_bonus(self, scorer):
        resp = make_response(0.7)
        result = scorer.score(resp, make_memories(2), {})
        assert result == pytest.approx(0.7, abs=0.01)

    def test_deadline_risk_penalty(self, scorer):
        resp = make_response(0.9)
        result = scorer.score(resp, [], {}, has_deadline_risk=True)
        assert result == pytest.approx(0.9 + MODIFIER_DEADLINE_RISK, abs=0.01)

    def test_unknown_sender_penalty(self, scorer):
        resp = make_response(0.9)
        result = scorer.score(resp, [], {}, sender_known=False)
        assert result == pytest.approx(0.9 + MODIFIER_UNKNOWN_SENDER, abs=0.01)

    def test_score_clipped_to_zero(self, scorer):
        # Many penalties should not go below 0.0
        resp = make_response(0.1)
        result = scorer.score(
            resp, [], {}, has_deadline_risk=True, sender_known=False
        )
        assert result >= 0.0

    def test_score_clipped_to_one(self, scorer):
        # Bonuses should not exceed 1.0
        resp = make_response(1.0)
        result = scorer.score(resp, make_memories(5), {})
        assert result <= 1.0

    def test_combined_modifiers(self, scorer):
        resp = make_response(0.8)
        result = scorer.score(
            resp,
            make_memories(3),
            {},
            has_deadline_risk=True,
            sender_known=True,
        )
        expected = 0.8 + MODIFIER_MANY_MEMORIES + MODIFIER_DEADLINE_RISK
        assert result == pytest.approx(max(0.0, min(1.0, expected)), abs=0.01)

    def test_language_mismatch_cjk(self, scorer):
        # CJK characters in body trigger language mismatch penalty
        resp = make_response(0.8)
        result = scorer.score(resp, [], {"body": "这是一条中文消息"})
        assert result == pytest.approx(0.8 + MODIFIER_LANGUAGE_MISMATCH, abs=0.01)

    def test_vietnamese_no_mismatch(self, scorer):
        # Vietnamese uses Latin-based script — no mismatch penalty
        resp = make_response(0.8)
        result = scorer.score(resp, [], {"body": "mình check lại rồi nhé"})
        assert result == pytest.approx(0.8, abs=0.01)


class TestAutoSend:
    def test_above_default_threshold(self, scorer):
        assert scorer.should_auto_send(0.90, "!unknown:localhost") is True

    def test_below_default_threshold(self, scorer):
        assert scorer.should_auto_send(0.80, "!unknown:localhost") is False

    def test_at_default_threshold(self, scorer):
        assert scorer.should_auto_send(0.85, "!unknown:localhost") is True

    def test_graduated_room_lower_threshold(self, scorer):
        # Graduated room has threshold 0.65
        assert scorer.should_auto_send(0.70, "!graduated:localhost") is True

    def test_graduated_room_below_threshold(self, scorer):
        assert scorer.should_auto_send(0.60, "!graduated:localhost") is False

    def test_get_threshold_default(self, scorer):
        assert scorer.get_threshold("!new:localhost") == pytest.approx(0.85)

    def test_get_threshold_graduated(self, scorer):
        assert scorer.get_threshold("!graduated:localhost") == pytest.approx(0.65)


class TestPriorityModifiers:
    """Test priority-based confidence adjustments."""

    def test_high_priority_boost(self, scorer):
        """High priority should boost confidence."""
        resp = make_response(0.7)
        result = scorer.score(resp, [], {}, priority="high")
        assert result > 0.7

    def test_low_priority_penalty(self, scorer):
        """Low priority should penalize confidence."""
        resp = make_response(0.7)
        result = scorer.score(resp, [], {}, priority="low")
        assert result < 0.7

    def test_normal_priority_no_change(self, scorer):
        """Normal priority should not change score."""
        resp = make_response(0.7)
        result = scorer.score(resp, [], {}, priority="normal")
        assert result == pytest.approx(0.7, abs=0.01)

    def test_high_priority_with_memories_combined(self, scorer):
        """High priority + memories should compound bonuses."""
        resp = make_response(0.7)
        result = scorer.score(
            resp, make_memories(3), {}, priority="high"
        )
        # Should have both memory bonus and priority boost
        assert result > 0.7 + 0.10  # At least memory bonus


class TestGroupChatBehavior:
    """Test confidence scoring in group chat context."""

    def test_social_in_group_skip(self, scorer):
        """Social intent in group should skip (very low confidence)."""
        resp = make_response(0.8)
        result = scorer.score(resp, [], {}, intent="social", is_group=True)
        # Should apply no_history penalty which is -0.90
        assert result < 0.5

    def test_social_in_dm_boost(self, scorer):
        """Social intent in DM should boost confidence."""
        resp = make_response(0.7)
        result = scorer.score(resp, [], {}, intent="social", is_group=False)
        # Should apply social_dm bonus which is +0.25
        assert result > 0.7

    def test_work_intent_in_group_normal(self, scorer):
        """Work intent (question/request) in group should not penalize."""
        resp = make_response(0.8)
        result = scorer.score(
            resp, [], {}, intent="question", is_group=True
        )
        # Should not have the group social penalty
        assert result == pytest.approx(0.8, abs=0.01)

    def test_fyi_in_group_skip(self, scorer):
        """FYI intent in group should skip (very low confidence)."""
        resp = make_response(0.8)
        result = scorer.score(resp, [], {}, intent="fyi", is_group=True)
        # Should apply no_history penalty
        assert result < 0.5


class TestConfigDrivenModifiers:
    """Test that modifiers are loaded from config."""

    def test_modifiers_loaded_from_config(self, scorer):
        """Modifiers should be loaded from config YAML."""
        # Scorer fixture loads config with specific modifiers
        # Check that a custom modifier is available
        assert scorer._modifiers is not None
        assert isinstance(scorer._modifiers, dict)
        assert len(scorer._modifiers) > 0

    def test_config_overrides_defaults(self):
        """Config modifiers should override hard-coded defaults."""
        with patch.object(
            ConfidenceScorer,
            "_load_config",
            return_value={
                "default_threshold": 0.85,
                "graduated_spaces": {},
                "modifiers": {
                    "many_memories": 0.20,  # Override default 0.10
                    "deadline_risk": -0.30,  # Override default -0.20
                },
            },
        ):
            scorer = ConfidenceScorer()
            resp = make_response(0.7)
            result = scorer.score(resp, make_memories(3), {})
            # Should use config value 0.20 instead of default 0.10
            assert result == pytest.approx(0.7 + 0.20, abs=0.01)

    def test_missing_yaml_uses_defaults(self):
        """Missing YAML should fall back to hard-coded defaults."""
        with patch.object(ConfidenceScorer, "_load_config", return_value={}):
            scorer = ConfidenceScorer()
            resp = make_response(0.7)
            result = scorer.score(resp, make_memories(3), {})
            # Should use default 0.10
            assert result == pytest.approx(0.7 + 0.10, abs=0.01)
