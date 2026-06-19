"""Shared pytest fixtures for The Gatekeeper test suite."""
import pytest
from pathlib import Path
from src.providers.base import EmailMessage


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a path to a temporary SQLite database file."""
    return tmp_path / "test_gatekeeper.db"


@pytest.fixture
def sample_email() -> EmailMessage:
    """Return a canonical test EmailMessage."""
    return EmailMessage(
        id="msg-abc123",
        sender="alice@example.com",
        subject="Project Update",
        body="Hi, here is the weekly project update.",
        received_at="2024-01-15T09:00:00Z",
        thread_id="thread-xyz",
    )


@pytest.fixture
def sample_email_2() -> EmailMessage:
    """Return a second EmailMessage in the same thread."""
    return EmailMessage(
        id="msg-abc456",
        sender="bob@example.com",
        subject="Re: Project Update",
        body="Thanks for the update!",
        received_at="2024-01-15T10:00:00Z",
        thread_id="thread-xyz",
    )
