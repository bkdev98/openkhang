"""Unit tests for PromptBuilder — verifies message structure and content injection."""

import pytest
from unittest.mock import patch
from ..prompt_builder import PromptBuilder


FAKE_OUTWARD = "You are Khanh Bui. ## Hard Rules\n- NEVER fabricate."
FAKE_INWARD = "You are openkhang, Khanh's assistant."


@pytest.fixture
def builder():
    with patch.object(PromptBuilder, "_read_prompt", side_effect=lambda f: (
        FAKE_OUTWARD if "outward" in f else FAKE_INWARD
    )):
        yield PromptBuilder()


def make_event(body="Hello!", sender_id="alice", room_name="Dev Chat"):
    return {
        "body": body,
        "sender_id": sender_id,
        "room_name": room_name,
        "room_id": "!abc:localhost",
    }


class TestBuildStructure:
    def test_returns_two_messages(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event())
        assert len(msgs) == 2

    def test_first_message_is_system(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event())
        assert msgs[0]["role"] == "system"

    def test_second_message_is_user(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event())
        assert msgs[1]["role"] == "user"

    def test_inward_uses_inward_template(self, builder):
        msgs = builder.build("inward", "query", [], [], make_event())
        assert "openkhang" in msgs[0]["content"]

    def test_outward_uses_outward_template(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event())
        assert "Khanh Bui" in msgs[0]["content"]


class TestMemoryInjection:
    def test_memories_injected_as_context_block(self, builder):
        memories = [{"memory": "Khanh prefers async", "score": 0.9}]
        msgs = builder.build("outward", "question", memories, [], make_event())
        assert "<context>" in msgs[0]["content"]
        assert "Khanh prefers async" in msgs[0]["content"]

    def test_empty_memories_no_context_block(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event())
        assert "<context>" not in msgs[0]["content"]

    def test_sender_context_injected(self, builder):
        sender_ctx = [{"memory": "alice is on the payments team", "score": 0.8}]
        msgs = builder.build("outward", "question", [], sender_ctx, make_event())
        assert "alice is on the payments team" in msgs[0]["content"]


class TestStyleExamples:
    def test_style_examples_injected_outward(self, builder):
        examples = [{"body": "oke mình check lại nhé"}, {"body": "sounds good!"}]
        msgs = builder.build("outward", "social", [], [], make_event(), style_examples=examples)
        assert "oke mình check lại nhé" in msgs[0]["content"]
        assert "<style_examples>" in msgs[0]["content"]

    def test_no_style_examples_no_block(self, builder):
        msgs = builder.build("outward", "social", [], [], make_event(), style_examples=None)
        assert "<style_examples>" not in msgs[0]["content"]

    def test_style_examples_capped_at_ten(self, builder):
        examples = [{"body": f"msg {i}"} for i in range(20)]
        msgs = builder.build("outward", "social", [], [], make_event(), style_examples=examples)
        # Only first 10 should appear
        assert "msg 9" in msgs[0]["content"]
        assert "msg 10" not in msgs[0]["content"]


class TestUserMessage:
    def test_outward_user_msg_contains_sender(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event(sender_id="bob"))
        assert "bob" in msgs[1]["content"]

    def test_outward_user_msg_contains_room_name(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event(room_name="Sprint Room"))
        assert "Sprint Room" in msgs[1]["content"]

    def test_outward_user_msg_contains_body(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event(body="What is the ETA?"))
        assert "What is the ETA?" in msgs[1]["content"]

    def test_inward_user_msg_contains_body(self, builder):
        msgs = builder.build("inward", "query", [], [], make_event(body="Show me open tickets"))
        assert "Show me open tickets" in msgs[1]["content"]

    def test_inward_user_msg_no_sender(self, builder):
        # Inward messages don't expose sender metadata (it's Khanh talking to himself)
        msgs = builder.build("inward", "query", [], [], make_event(sender_id="alice"))
        assert "alice" not in msgs[1]["content"]

    def test_timestamp_injected_in_system(self, builder):
        msgs = builder.build("outward", "question", [], [], make_event())
        assert "UTC" in msgs[0]["content"]
