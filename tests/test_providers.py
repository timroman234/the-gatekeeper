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
