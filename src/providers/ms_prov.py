"""Microsoft Outlook provider stub — not yet implemented."""
from typing import List

from src.providers.base import EmailMessage, ICommunicationProvider


class OutlookProvider(ICommunicationProvider):
    """Placeholder for a future Microsoft Graph API integration."""

    def fetch_unread_emails(self, max_results: int = 10) -> List[EmailMessage]:
        raise NotImplementedError(
            "Outlook provider is not implemented. Use GmailProvider."
        )

    def send_reply(self, original_email_id: str, reply_body: str) -> bool:
        raise NotImplementedError(
            "Outlook provider is not implemented. Use GmailProvider."
        )
