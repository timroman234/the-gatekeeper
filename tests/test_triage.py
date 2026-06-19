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
