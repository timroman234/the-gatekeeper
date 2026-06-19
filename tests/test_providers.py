"""Tests for provider base types and stub implementations."""
import pytest
from src.providers.base import EmailMessage, ICommunicationProvider
from src.providers.ms_prov import OutlookProvider


class TestEmailMessage:
    def test_full_construction(self):
        email = EmailMessage(
            id="msg-001",
            sender="alice@example.com",
            subject="Hello",
            body="Hi there",
            received_at="2024-01-15T10:00:00Z",
            thread_id="thread-001",
        )
        assert email.id == "msg-001"
        assert email.thread_id == "thread-001"

    def test_thread_id_defaults_to_empty_string(self):
        email = EmailMessage(
            id="msg-002",
            sender="bob@example.com",
            subject="Test",
            body="Body",
            received_at="2024-01-15T10:00:00Z",
        )
        assert email.thread_id == ""

    def test_is_pydantic_model(self):
        from pydantic import BaseModel
        assert issubclass(EmailMessage, BaseModel)

    def test_serialises_to_dict(self):
        email = EmailMessage(
            id="msg-003",
            sender="carol@example.com",
            subject="Re: Project",
            body="Thanks",
            received_at="2024-01-15T11:00:00Z",
        )
        d = email.model_dump()
        assert d["id"] == "msg-003"
        assert "thread_id" in d


class TestICommunicationProvider:
    def test_is_abstract(self):
        """Cannot instantiate ICommunicationProvider directly."""
        with pytest.raises(TypeError):
            ICommunicationProvider()

    def test_concrete_subclass_must_implement_fetch(self):
        class Partial(ICommunicationProvider):
            def send_reply(self, original_email_id, reply_body):
                return True
        with pytest.raises(TypeError):
            Partial()

    def test_concrete_subclass_must_implement_send(self):
        class Partial(ICommunicationProvider):
            def fetch_unread_emails(self, max_results=10):
                return []
        with pytest.raises(TypeError):
            Partial()


class TestOutlookProvider:
    def test_fetch_raises_not_implemented(self):
        provider = OutlookProvider()
        with pytest.raises(NotImplementedError, match="Outlook"):
            provider.fetch_unread_emails()

    def test_send_raises_not_implemented(self):
        provider = OutlookProvider()
        with pytest.raises(NotImplementedError, match="Outlook"):
            provider.send_reply("msg-001", "body")


class TestGmailProvider:
    """GmailProvider tests that mock the Google API client — no network calls."""

    def test_fetch_returns_email_message_objects(self, tmp_path, mocker):
        """fetch_unread_emails must return a list of EmailMessage instances."""
        from src.providers.google_prov import GmailProvider

        mock_service = mocker.MagicMock()
        mocker.patch.object(GmailProvider, "_build_service", return_value=mock_service)

        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg-001", "threadId": "thread-001"}]
        }
        msg_payload = {
            "id": "msg-001",
            "threadId": "thread-001",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 09:00:00 +0000"},
                ],
                "body": {"data": "SGkgdGhlcmU="},  # base64 "Hi there"
            },
        }
        mock_service.users().messages().get().execute.return_value = msg_payload

        creds_path = tmp_path / "credentials.json"
        token_path = tmp_path / "token.json"
        provider = GmailProvider(creds_path, token_path)
        emails = provider.fetch_unread_emails(max_results=1)

        assert len(emails) == 1
        assert isinstance(emails[0], EmailMessage)
        assert emails[0].id == "msg-001"
        assert emails[0].sender == "alice@example.com"
        assert emails[0].subject == "Hello"
        assert emails[0].thread_id == "thread-001"

    def test_fetch_returns_empty_when_no_messages(self, tmp_path, mocker):
        """fetch_unread_emails returns [] when inbox is empty."""
        from src.providers.google_prov import GmailProvider

        mock_service = mocker.MagicMock()
        mocker.patch.object(GmailProvider, "_build_service", return_value=mock_service)
        mock_service.users().messages().list().execute.return_value = {}

        provider = GmailProvider(tmp_path / "c.json", tmp_path / "t.json")
        emails = provider.fetch_unread_emails()
        assert emails == []

    def test_send_reply_returns_true_on_success(self, tmp_path, mocker):
        """send_reply returns True when the Gmail API succeeds."""
        from src.providers.google_prov import GmailProvider

        mock_service = mocker.MagicMock()
        mocker.patch.object(GmailProvider, "_build_service", return_value=mock_service)

        original_msg = {
            "id": "msg-001",
            "threadId": "thread-001",
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Message-ID", "value": "<hello@example.com>"},
                ]
            },
        }
        mock_service.users().messages().get().execute.return_value = original_msg
        mock_service.users().messages().send().execute.return_value = {"id": "sent-001"}

        provider = GmailProvider(tmp_path / "c.json", tmp_path / "t.json")
        result = provider.send_reply("msg-001", "Thank you!")
        assert result is True

    def test_send_reply_returns_false_on_api_error(self, tmp_path, mocker):
        """send_reply returns False when the Gmail API raises an exception."""
        from src.providers.google_prov import GmailProvider

        mock_service = mocker.MagicMock()
        mocker.patch.object(GmailProvider, "_build_service", return_value=mock_service)
        mock_service.users().messages().get().execute.side_effect = Exception(
            "API error"
        )

        provider = GmailProvider(tmp_path / "c.json", tmp_path / "t.json")
        result = provider.send_reply("msg-001", "body")
        assert result is False
