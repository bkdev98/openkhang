"""Unit tests for mode and intent classifier."""

import pytest
from ..classifier import Classifier


@pytest.fixture
def clf():
    return Classifier()


# ---------------------------------------------------------------------------
# Mode classification
# ---------------------------------------------------------------------------

class TestClassifyMode:
    def test_matrix_source_is_outward(self, clf):
        assert clf.classify_mode({"source": "matrix"}) == "outward"

    def test_chat_source_is_outward(self, clf):
        assert clf.classify_mode({"source": "chat"}) == "outward"

    def test_gchat_source_is_outward(self, clf):
        assert clf.classify_mode({"source": "gchat"}) == "outward"

    def test_cli_source_is_inward(self, clf):
        assert clf.classify_mode({"source": "cli"}) == "inward"

    def test_dashboard_source_is_inward(self, clf):
        assert clf.classify_mode({"source": "dashboard"}) == "inward"

    def test_matrix_room_id_heuristic(self, clf):
        # No source field but room_id starts with '!'
        assert clf.classify_mode({"room_id": "!abc123:localhost"}) == "outward"

    def test_unknown_source_defaults_to_inward(self, clf):
        # Unknown source → inward (safe default, no auto-send risk)
        assert clf.classify_mode({"source": "unknown_thing"}) == "inward"

    def test_empty_event_defaults_to_inward(self, clf):
        assert clf.classify_mode({}) == "inward"

    def test_case_insensitive_source(self, clf):
        assert clf.classify_mode({"source": "MATRIX"}) == "outward"
        assert clf.classify_mode({"source": "CLI"}) == "inward"


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

class TestClassifyIntent:
    def test_question_mark(self, clf):
        assert clf.classify_intent("Can you check this?", "outward") == "question"

    def test_question_word_how(self, clf):
        assert clf.classify_intent("How does the payment flow work", "outward") == "question"

    def test_question_word_what(self, clf):
        assert clf.classify_intent("What is the status of PROJ-42", "inward") == "query"

    def test_request_please(self, clf):
        assert clf.classify_intent("Please review my PR", "outward") == "request"

    def test_request_can_you(self, clf):
        assert clf.classify_intent("Can you help me with the migration", "outward") == "request"

    def test_fyi(self, clf):
        assert clf.classify_intent("FYI the deploy is done", "outward") == "fyi"

    def test_fyi_heads_up(self, clf):
        assert clf.classify_intent("Heads up, server will restart at 3pm", "outward") == "fyi"

    def test_social_greeting(self, clf):
        assert clf.classify_intent("Hi", "outward") == "social"

    def test_social_thanks(self, clf):
        assert clf.classify_intent("thanks", "outward") == "social"

    def test_social_oke(self, clf):
        assert clf.classify_intent("oke", "outward") == "social"

    def test_social_noted(self, clf):
        assert clf.classify_intent("noted", "outward") == "social"

    def test_inward_instruction(self, clf):
        assert clf.classify_intent("Set threshold for room !abc to 0.7", "inward") == "instruction"

    def test_inward_status_query(self, clf):
        assert clf.classify_intent("What's my sprint status?", "inward") == "query"

    def test_inward_show_me(self, clf):
        assert clf.classify_intent("Show me open tickets", "inward") == "query"

    def test_default_outward_is_fyi(self, clf):
        # No pattern matches → default for outward is 'fyi'
        assert clf.classify_intent("The meeting notes are in Confluence", "outward") == "fyi"

    def test_default_inward_is_query(self, clf):
        # No pattern matches → default for inward is 'query'
        assert clf.classify_intent("The deploy pipeline", "inward") == "query"


# ---------------------------------------------------------------------------
# Deadline risk detection
# ---------------------------------------------------------------------------

class TestDeadlineRisk:
    def test_deadline_keyword(self, clf):
        assert clf.has_deadline_risk("What's the deadline for this feature?") is True

    def test_eta_keyword(self, clf):
        assert clf.has_deadline_risk("What's the ETA on the fix?") is True

    def test_deliver_keyword(self, clf):
        assert clf.has_deadline_risk("When will you deliver this?") is True

    def test_no_risk_normal_message(self, clf):
        assert clf.has_deadline_risk("Thanks for the update") is False

    def test_no_risk_empty(self, clf):
        assert clf.has_deadline_risk("") is False

    def test_case_insensitive(self, clf):
        assert clf.has_deadline_risk("DEADLINE is tomorrow") is True
