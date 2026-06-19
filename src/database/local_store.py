"""SQLite-backed local store for emails and drafts."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.providers.base import EmailMessage

_CREATE_EMAILS = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    received_at TEXT NOT NULL,
    thread_id TEXT DEFAULT '',
    triage_category TEXT,
    is_processed INTEGER DEFAULT 0
);
"""

_CREATE_DRAFTS = """
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL,
    draft_body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    FOREIGN KEY (email_id) REFERENCES emails(id)
);
"""


class LocalStore:
    """Thin wrapper around a SQLite connection providing typed operations."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._migrate()

    def _migrate(self) -> None:
        self._conn.execute(_CREATE_EMAILS)
        self._conn.execute(_CREATE_DRAFTS)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Email operations
    # ------------------------------------------------------------------

    def save_email(self, email: EmailMessage) -> None:
        """Persist an email. Silently ignores duplicate IDs."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO emails
                (id, sender, subject, body, received_at, thread_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                email.id,
                email.sender,
                email.subject,
                email.body,
                email.received_at,
                email.thread_id,
            ),
        )
        self._conn.commit()

    def get_email(self, email_id: str) -> Optional[dict]:
        """Return a single email row as a dict, or None if not found."""
        cursor = self._conn.execute(
            "SELECT * FROM emails WHERE id = ?", (email_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_triage(self, email_id: str, category: str) -> None:
        """Set the triage_category for an email."""
        self._conn.execute(
            "UPDATE emails SET triage_category = ? WHERE id = ?",
            (category, email_id),
        )
        self._conn.commit()

    def mark_processed(self, email_id: str) -> None:
        """Mark an email as fully processed (sent or rejected)."""
        self._conn.execute(
            "UPDATE emails SET is_processed = 1 WHERE id = ?", (email_id,)
        )
        self._conn.commit()

    def get_thread_history(self, thread_id: str) -> list[dict]:
        """Return all emails in a thread, ordered oldest to newest.

        Returns a list of dicts with keys: subject, body, sender, received_at.
        """
        cursor = self._conn.execute(
            """
            SELECT subject, body, sender, received_at
            FROM emails
            WHERE thread_id = ?
            ORDER BY received_at ASC
            """,
            (thread_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Draft operations
    # ------------------------------------------------------------------

    def save_draft(self, email_id: str, draft_body: str) -> int:
        """Persist a draft reply. Returns the new draft's integer ID."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO drafts (email_id, draft_body, created_at)
            VALUES (?, ?, ?)
            """,
            (email_id, draft_body, now),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def update_draft_status(self, draft_id: int, status: str) -> None:
        """Update draft status: 'pending' | 'sent' | 'rejected'."""
        self._conn.execute(
            "UPDATE drafts SET status = ? WHERE id = ?", (status, draft_id)
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __enter__(self) -> "LocalStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
