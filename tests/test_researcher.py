"""Unit tests for the researcher LangGraph node."""
import pytest
from unittest.mock import patch, MagicMock
from src.agents.state import GatekeeperState
from src.providers.base import EmailMessage


def _make_state(email: EmailMessage) -> GatekeeperState:
    return GatekeeperState(
        current_email=email,
        extracted_metadata={"category": "action_required", "reasoning": "needs reply"},
        project_context=None,
        generated_draft=None,
        is_approved=False,
        user_modifications=None,
        rejection_reason=None,
    )


@pytest.fixture
def thread_email():
    return EmailMessage(
        id="msg-001",
        sender="alice@example.com",
        subject="Q3 Report",
        body="Please send the Q3 report.",
        received_at="2024-01-15T09:00:00Z",
        thread_id="thread-q3",
    )


class TestResearcherNode:
    def test_returns_dict_with_project_context(self, thread_email, mocker):
        """researcher_node must return {'project_context': str}."""
        from src.agents.researcher import researcher_node

        mock_store = mocker.MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.get_thread_history.return_value = []

        with patch("src.agents.researcher.LocalStore", return_value=mock_store):
            result = researcher_node(_make_state(thread_email))

        assert "project_context" in result
        assert isinstance(result["project_context"], str)

    def test_no_prior_history_message(self, thread_email, mocker):
        """With no thread history, context must say no prior context found."""
        from src.agents.researcher import researcher_node

        mock_store = mocker.MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.get_thread_history.return_value = []

        with patch("src.agents.researcher.LocalStore", return_value=mock_store):
            result = researcher_node(_make_state(thread_email))

        assert "no prior" in result["project_context"].lower()

    def test_formats_thread_history(self, thread_email, mocker):
        """With history, context must include sender and body text."""
        from src.agents.researcher import researcher_node

        history = [
            {
                "sender": "alice@example.com",
                "subject": "Q3 Report",
                "body": "Please send the Q3 report.",
                "received_at": "2024-01-15T09:00:00Z",
            }
        ]
        mock_store = mocker.MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.get_thread_history.return_value = history

        with patch("src.agents.researcher.LocalStore", return_value=mock_store):
            result = researcher_node(_make_state(thread_email))

        assert "alice@example.com" in result["project_context"]
        assert "Q3 report" in result["project_context"]

    def test_queries_correct_thread_id(self, thread_email, mocker):
        """researcher_node must query by the email's thread_id."""
        from src.agents.researcher import researcher_node

        mock_store = mocker.MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.get_thread_history.return_value = []

        with patch("src.agents.researcher.LocalStore", return_value=mock_store):
            researcher_node(_make_state(thread_email))

        mock_store.get_thread_history.assert_called_once_with("thread-q3")

    def test_handles_email_with_empty_thread_id(self, mocker):
        """When thread_id is empty, context must indicate no prior context."""
        from src.agents.researcher import researcher_node

        email = EmailMessage(
            id="msg-no-thread",
            sender="x@example.com",
            subject="Hello",
            body="Hi",
            received_at="2024-01-15T09:00:00Z",
            thread_id="",
        )
        mock_store = mocker.MagicMock()
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.get_thread_history.return_value = []

        with patch("src.agents.researcher.LocalStore", return_value=mock_store):
            result = researcher_node(_make_state(email))

        assert "no prior" in result["project_context"].lower()
