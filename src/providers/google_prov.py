"""Gmail provider using Google OAuth2 and the Gmail REST API."""
import base64
import json
import logging
import os
from email.mime.text import MIMEText
from pathlib import Path
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.providers.base import EmailMessage, ICommunicationProvider

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailProvider(ICommunicationProvider):
    """Fetches and sends Gmail messages using OAuth2 credentials."""

    def __init__(self, credentials_path: Path, token_path: Path) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = self._build_service()

    def _build_service(self):
        """Authenticate and return the Gmail API service object.

        In production (Railway): reads token from GMAIL_TOKEN_JSON env var.
        In local dev: reads token.json from disk, opens browser on first run.
        """
        creds: Credentials | None = None
        token_env = os.environ.get("GMAIL_TOKEN_JSON")

        if token_env:
            creds = Credentials.from_authorized_user_info(json.loads(token_env), SCOPES)
        elif self._token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                if not token_env:
                    self._token_path.write_text(creds.to_json())
            else:
                if token_env:
                    raise RuntimeError(
                        "GMAIL_TOKEN_JSON is set but the token is invalid and cannot be refreshed. "
                        "Re-generate token.json locally and update the env var."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
                self._token_path.write_text(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # ICommunicationProvider
    # ------------------------------------------------------------------

    def fetch_unread_emails(self, max_results: int = 10) -> List[EmailMessage]:
        """Return up to max_results unread emails from the Gmail inbox."""
        try:
            response = (
                self._service.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=max_results)
                .execute()
            )
        except Exception:
            logger.exception("Failed to list Gmail messages")
            return []

        raw_messages = response.get("messages", [])
        if not raw_messages:
            return []

        emails: List[EmailMessage] = []
        for meta in raw_messages:
            try:
                msg = (
                    self._service.users()
                    .messages()
                    .get(userId="me", id=meta["id"], format="full")
                    .execute()
                )
                emails.append(self._parse_message(msg))
            except Exception:
                logger.exception("Failed to fetch message %s", meta["id"])

        return emails

    def send_reply(self, original_email_id: str, reply_body: str) -> bool:
        """Send reply_body as a threaded reply to original_email_id.

        Returns True on success, False on any error.
        """
        try:
            original = (
                self._service.users()
                .messages()
                .get(userId="me", id=original_email_id, format="full")
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in original.get("payload", {}).get("headers", [])
            }
            thread_id = original.get("threadId", "")

            to_address = headers.get("From", "")
            subject = headers.get("Subject", "")
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            message_id_header = headers.get("Message-ID", "")

            mime_msg = MIMEText(reply_body, "plain")
            mime_msg["To"] = to_address
            mime_msg["Subject"] = subject
            if message_id_header:
                mime_msg["In-Reply-To"] = message_id_header
                mime_msg["References"] = message_id_header

            raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
            body = {"raw": raw, "threadId": thread_id}

            self._service.users().messages().send(userId="me", body=body).execute()
            return True

        except Exception:
            logger.exception("Failed to send reply to %s", original_email_id)
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_message(msg: dict) -> EmailMessage:
        """Convert a raw Gmail API message dict to an EmailMessage."""
        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        body = GmailProvider._extract_body(msg.get("payload", {}))
        return EmailMessage(
            id=msg["id"],
            sender=headers.get("From", ""),
            subject=headers.get("Subject", ""),
            body=body,
            received_at=headers.get("Date", ""),
            thread_id=msg.get("threadId", ""),
        )

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """Recursively extract plain-text body from a Gmail payload."""
        mime_type = payload.get("mimeType", "")
        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode(
                    "utf-8", errors="replace"
                )
        for part in payload.get("parts", []):
            result = GmailProvider._extract_body(part)
            if result:
                return result
        return ""
