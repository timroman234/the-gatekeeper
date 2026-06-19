"""Integration tests for the LangGraph DAG — built up across Tasks 6-10."""
import pytest


class TestStateImport:
    def test_gatekeeper_state_is_importable(self):
        from src.agents.state import GatekeeperState
        assert GatekeeperState is not None

    def test_gatekeeper_state_has_expected_keys(self):
        from src.agents.state import GatekeeperState
        annotations = GatekeeperState.__annotations__
        expected = {
            "current_email",
            "extracted_metadata",
            "project_context",
            "generated_draft",
            "is_approved",
            "user_modifications",
            "rejection_reason",
        }
        assert expected == set(annotations.keys())


class TestBuildGraph:
    def test_build_graph_returns_compiled_graph(self, tmp_path, mocker):
        """build_graph must return a compiled LangGraph StateGraph."""
        from src.graph import build_graph

        mocker.patch("src.graph.settings.checkpoint_path", tmp_path / "cp.db")
        graph = build_graph()
        assert graph is not None
        assert hasattr(graph, "invoke")

    def test_graph_has_interrupt_before_send_email(self, tmp_path, mocker):
        """Graph must declare interrupt_before=['send_email']."""
        from src.graph import build_graph

        mocker.patch("src.graph.settings.checkpoint_path", tmp_path / "cp.db")
        graph = build_graph()
        # LangGraph exposes this as interrupt_before_nodes in newer versions
        interrupt_attr = getattr(graph, "interrupt_before", None) or getattr(graph, "interrupt_before_nodes", [])
        assert "send_email" in interrupt_attr


class TestSendEmailNode:
    def test_approved_email_triggers_send(self, mocker):
        """send_email_node must call GmailProvider.send_reply with the draft."""
        from src.agents.state import GatekeeperState
        from src.providers.base import EmailMessage
        from src.graph import send_email_node

        email = EmailMessage(
            id="msg-send-001",
            sender="client@example.com",
            subject="Quote Request",
            body="Please send a quote.",
            received_at="2024-01-15T09:00:00Z",
            thread_id="thread-send",
        )
        state = GatekeeperState(
            current_email=email,
            extracted_metadata={"category": "action_required", "reasoning": "needs reply"},
            project_context="No prior context.",
            generated_draft="Dear Client, here is your quote...",
            is_approved=True,
            user_modifications=None,
            rejection_reason=None,
        )

        mock_provider = mocker.MagicMock()
        mock_provider.send_reply.return_value = True
        mock_store = mocker.MagicMock()
        mock_store.__enter__ = mocker.MagicMock(return_value=mock_store)
        mock_store.__exit__ = mocker.MagicMock(return_value=False)
        mock_store.save_draft.return_value = 1

        mocker.patch("src.graph.GmailProvider", return_value=mock_provider)
        mocker.patch("src.graph.LocalStore", return_value=mock_store)

        send_email_node(state)

        mock_provider.send_reply.assert_called_once_with(
            "msg-send-001", "Dear Client, here is your quote..."
        )

    def test_user_modifications_override_draft(self, mocker):
        """When user_modifications is set, it must be sent instead of generated_draft."""
        from src.agents.state import GatekeeperState
        from src.providers.base import EmailMessage
        from src.graph import send_email_node

        email = EmailMessage(
            id="msg-send-002",
            sender="client@example.com",
            subject="Quote",
            body="Send quote.",
            received_at="2024-01-15T09:00:00Z",
        )
        state = GatekeeperState(
            current_email=email,
            extracted_metadata={"category": "action_required", "reasoning": "needs reply"},
            project_context=None,
            generated_draft="Original draft",
            is_approved=True,
            user_modifications="Edited by human",
            rejection_reason=None,
        )

        mock_provider = mocker.MagicMock()
        mock_provider.send_reply.return_value = True
        mock_store = mocker.MagicMock()
        mock_store.__enter__ = mocker.MagicMock(return_value=mock_store)
        mock_store.__exit__ = mocker.MagicMock(return_value=False)
        mock_store.save_draft.return_value = 1

        mocker.patch("src.graph.GmailProvider", return_value=mock_provider)
        mocker.patch("src.graph.LocalStore", return_value=mock_store)

        send_email_node(state)

        mock_provider.send_reply.assert_called_once_with("msg-send-002", "Edited by human")
