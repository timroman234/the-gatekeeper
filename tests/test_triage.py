"""Unit tests for the triage LangGraph node."""
import pytest
from unittest.mock import patch
from langchain_core.runnables import RunnableLambda
from src.agents.state import GatekeeperState
from src.providers.base import EmailMessage


def _make_state(email: EmailMessage) -> GatekeeperState:
    return GatekeeperState(
        current_email=email,
        extracted_metadata={},
        project_context=None,
        generated_draft=None,
        is_approved=False,
        user_modifications=None,
        rejection_reason=None,
    )


def _make_mock_llm(mocker, category: str, reasoning: str):
    """Return a mock LLM whose with_structured_output returns a proper Runnable."""
    mock_response = mocker.MagicMock()
    mock_response.category = category
    mock_response.reasoning = reasoning
    mock_llm = mocker.MagicMock()
    mock_llm.with_structured_output.return_value = RunnableLambda(lambda _: mock_response)
    return mock_llm, mock_response


@pytest.fixture
def sample_email():
    return EmailMessage(
        id="msg-triage-001",
        sender="boss@company.com",
        subject="URGENT: Deploy now",
        body="Please deploy the hotfix immediately.",
        received_at="2024-01-15T09:00:00Z",
        thread_id="thread-001",
    )


class TestTriageNode:
    def test_returns_dict_with_extracted_metadata(self, sample_email, mocker):
        """triage_node must return a dict containing 'extracted_metadata'."""
        from src.agents.triage import triage_node

        mock_llm, _ = _make_mock_llm(mocker, "urgent", "Subject says URGENT.")
        with patch("src.agents.triage.llm", mock_llm):
            result = triage_node(_make_state(sample_email))

        assert "extracted_metadata" in result

    def test_extracted_metadata_has_category_and_reasoning(self, sample_email, mocker):
        from src.agents.triage import triage_node

        mock_llm, _ = _make_mock_llm(mocker, "urgent", "Marked urgent.")
        with patch("src.agents.triage.llm", mock_llm):
            result = triage_node(_make_state(sample_email))

        assert result["extracted_metadata"]["category"] == "urgent"
        assert "reasoning" in result["extracted_metadata"]

    def test_valid_categories_accepted(self, mocker):
        """Node must accept all five defined categories without error."""
        from src.agents.triage import triage_node

        for category in ["urgent", "action_required", "informational", "spam", "newsletter"]:
            email = EmailMessage(
                id=f"msg-{category}",
                sender="x@example.com",
                subject="Test",
                body="Body",
                received_at="2024-01-15T09:00:00Z",
            )
            mock_llm, _ = _make_mock_llm(mocker, category, "reason")
            with patch("src.agents.triage.llm", mock_llm):
                result = triage_node(_make_state(email))
            assert result["extracted_metadata"]["category"] == category

    def test_email_fields_passed_as_template_variables(self, sample_email, mocker):
        """Verify TRIAGE_PROMPT is a ChatPromptTemplate with named variables."""
        from src.agents import triage as triage_module
        from langchain_core.prompts import ChatPromptTemplate

        assert isinstance(triage_module.TRIAGE_PROMPT, ChatPromptTemplate)
        input_vars = set(triage_module.TRIAGE_PROMPT.input_variables)
        assert "sender" in input_vars
        assert "subject" in input_vars
        assert "body" in input_vars
        assert "correction_examples" in input_vars


class TestTriageNodeSenderRules:
    def test_sender_rule_bypasses_llm(self, tmp_path, mocker):
        """When a sender rule matches, the LLM must not be called."""
        from src.agents.triage import triage_node
        from src.database.local_store import LocalStore

        db = tmp_path / "test.db"
        with LocalStore(db) as store:
            store.add_sender_rule("tim@sf415.com", "action_required", "my alt account")

        email = EmailMessage(id="e1", sender="Tim <tim@sf415.com>", subject="Hey",
                             body="test", received_at="2026-01-01", thread_id="")

        mock_llm = mocker.MagicMock()
        with patch("src.agents.triage.llm", mock_llm), \
             patch("src.agents.triage.settings") as mock_settings:
            mock_settings.db_path = db
            result = triage_node(_make_state(email))

        mock_llm.with_structured_output.assert_not_called()
        assert result["extracted_metadata"]["category"] == "action_required"
        assert "Sender rule" in result["extracted_metadata"]["reasoning"]

    def test_no_rule_calls_llm_normally(self, tmp_path, mocker):
        """When no rule matches, the LLM is called as before."""
        from src.agents.triage import triage_node

        db = tmp_path / "test.db"
        email = EmailMessage(id="e2", sender="unknown@nowhere.com", subject="Hi",
                             body="body", received_at="2026-01-01", thread_id="")

        mock_llm, _ = _make_mock_llm(mocker, "informational", "FYI email")
        with patch("src.agents.triage.llm", mock_llm), \
             patch("src.agents.triage.settings") as mock_settings:
            mock_settings.db_path = db
            result = triage_node(_make_state(email))

        assert result["extracted_metadata"]["category"] == "informational"


class TestTriageCorrectionInjection:
    def test_correction_examples_injected_into_prompt(self, tmp_path, mocker):
        """Correction history appears in the LLM prompt when corrections exist."""
        from src.agents.triage import triage_node
        from src.database.local_store import LocalStore

        db = tmp_path / "test.db"
        with LocalStore(db) as store:
            e = EmailMessage(id="e0", sender="x@x.com", subject="test",
                             body="b", received_at="2026-01-01", thread_id="")
            store.save_email(e)
            store.save_correction("e0", "x@x.com", "test", "spam", "action_required")

        email = EmailMessage(id="e1", sender="new@new.com", subject="New",
                             body="body", received_at="2026-01-01", thread_id="")
        captured_inputs = {}

        def fake_invoke(inputs):
            captured_inputs.update(inputs)
            r = mocker.MagicMock()
            r.category = "informational"
            r.reasoning = "test"
            return r

        mock_llm = mocker.MagicMock()
        mock_llm.with_structured_output.return_value = RunnableLambda(fake_invoke)

        with patch("src.agents.triage.llm", mock_llm), \
             patch("src.agents.triage.settings") as mock_settings:
            mock_settings.db_path = db
            triage_node(_make_state(email))

        # By the time the mock is called, the prompt template has already rendered
        # correction_examples into the system message content.
        system_content = captured_inputs["messages"][0].content
        assert "x@x.com" in system_content
        assert "spam" in system_content
        assert "action_required" in system_content

    def test_format_corrections_empty(self):
        from src.agents.triage import _format_corrections
        assert _format_corrections([]) == ""

    def test_format_corrections_non_empty(self):
        from src.agents.triage import _format_corrections
        corrections = [{"sender": "x@x.com", "subject": "Hi",
                        "original_category": "spam", "corrected_category": "action_required"}]
        result = _format_corrections(corrections)
        assert "x@x.com" in result
        assert "spam" in result
        assert "action_required" in result
