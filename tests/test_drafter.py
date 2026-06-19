"""Unit tests for the drafter LangGraph node."""
import pytest
from unittest.mock import patch
from langchain_core.runnables import RunnableLambda
from src.agents.state import GatekeeperState
from src.providers.base import EmailMessage


def _make_state(
    email: EmailMessage,
    category: str = "action_required",
    context: str = "No prior context found.",
) -> GatekeeperState:
    return GatekeeperState(
        current_email=email,
        extracted_metadata={"category": category, "reasoning": "test reason"},
        project_context=context,
        generated_draft=None,
        is_approved=False,
        user_modifications=None,
        rejection_reason=None,
    )


@pytest.fixture
def action_email():
    return EmailMessage(
        id="msg-draft-001",
        sender="client@example.com",
        subject="Quote Request",
        body="Can you send me a quote for the project?",
        received_at="2024-01-15T09:00:00Z",
        thread_id="thread-draft",
    )


class TestDrafterNode:
    def test_returns_generated_draft(self, action_email, mocker):
        """drafter_node must return {'generated_draft': str}."""
        from src.agents.drafter import drafter_node

        mock_response = mocker.MagicMock()
        mock_response.content = "Dear Client, thank you for reaching out..."
        # llm is the second step in DRAFT_PROMPT | llm; use RunnableLambda so
        # LangChain treats it as a proper Runnable and calls .invoke() on it
        mock_llm = RunnableLambda(lambda _: mock_response)

        with patch("src.agents.drafter.llm", mock_llm):
            result = drafter_node(_make_state(action_email))

        assert "generated_draft" in result
        assert isinstance(result["generated_draft"], str)
        assert len(result["generated_draft"]) > 0

    def test_draft_content_comes_from_llm(self, action_email, mocker):
        """The draft text must be exactly what the LLM returned."""
        from src.agents.drafter import drafter_node

        expected_text = "Dear Client, I will send the quote shortly."
        mock_response = mocker.MagicMock()
        mock_response.content = expected_text
        mock_llm = RunnableLambda(lambda _: mock_response)

        with patch("src.agents.drafter.llm", mock_llm):
            result = drafter_node(_make_state(action_email))

        assert result["generated_draft"] == expected_text

    def test_spam_email_returns_empty_draft(self, mocker):
        """Spam-classified emails must return an empty draft — no reply needed."""
        from src.agents.drafter import drafter_node

        spam_email = EmailMessage(
            id="msg-spam-001",
            sender="spammer@bad.com",
            subject="Win a prize!",
            body="Click here to claim your prize.",
            received_at="2024-01-15T09:00:00Z",
        )
        invoked = []
        mock_llm = RunnableLambda(lambda x: invoked.append(x) or None)

        with patch("src.agents.drafter.llm", mock_llm):
            result = drafter_node(_make_state(spam_email, category="spam"))

        assert result["generated_draft"] == ""
        assert invoked == [], "LLM must not be called for spam"

    def test_newsletter_email_returns_empty_draft(self, mocker):
        """Newsletter-classified emails must return an empty draft."""
        from src.agents.drafter import drafter_node

        newsletter_email = EmailMessage(
            id="msg-nl-001",
            sender="news@digest.com",
            subject="Weekly Digest",
            body="Here is your weekly digest.",
            received_at="2024-01-15T09:00:00Z",
        )
        invoked = []
        mock_llm = RunnableLambda(lambda x: invoked.append(x) or None)

        with patch("src.agents.drafter.llm", mock_llm):
            result = drafter_node(_make_state(newsletter_email, category="newsletter"))

        assert result["generated_draft"] == ""
        assert invoked == [], "LLM must not be called for newsletters"

    def test_prompt_uses_template_variables(self, mocker):
        """Verify that DRAFT_PROMPT is a ChatPromptTemplate with named variables."""
        from src.agents import drafter as drafter_module
        from langchain_core.prompts import ChatPromptTemplate

        assert isinstance(drafter_module.DRAFT_PROMPT, ChatPromptTemplate)
        vars_set = set(drafter_module.DRAFT_PROMPT.input_variables)
        assert "sender" in vars_set
        assert "subject" in vars_set
        assert "body" in vars_set
        assert "category" in vars_set
        assert "context" in vars_set
