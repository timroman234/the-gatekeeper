"""Abstract base types for all communication providers."""
from abc import ABC, abstractmethod
from typing import List

from pydantic import BaseModel


class EmailMessage(BaseModel):
    """Represents a single email message, provider-agnostic."""
    id: str
    sender: str
    subject: str
    body: str
    received_at: str
    thread_id: str = ""  # Gmail thread ID; empty for providers that don't support threads


class ICommunicationProvider(ABC):
    """Abstract interface every email provider must implement."""

    @abstractmethod
    def fetch_unread_emails(self, max_results: int = 10) -> List[EmailMessage]:
        """Return up to max_results unread emails, newest first."""

    @abstractmethod
    def send_reply(self, original_email_id: str, reply_body: str) -> bool:
        """Send reply_body as a reply to original_email_id. Return True on success."""
