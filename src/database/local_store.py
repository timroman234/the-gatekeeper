"""SQLite-backed local store for emails and drafts."""
import email.utils as _email_utils
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

_CREATE_SENDER_RULES = """
CREATE TABLE IF NOT EXISTS sender_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,
    override_category TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""

_CREATE_TRIAGE_CORRECTIONS = """
CREATE TABLE IF NOT EXISTS triage_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    original_category TEXT NOT NULL,
    corrected_category TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (email_id) REFERENCES emails(id)
);
"""


def _extract_email_addr(sender: str) -> str:
    """Parse 'Name <addr>' or bare address → lowercase addr."""
    _, addr = _email_utils.parseaddr(sender)
    return (addr or sender).lower().strip()


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
        self._conn.execute(_CREATE_SENDER_RULES)
        self._conn.execute(_CREATE_TRIAGE_CORRECTIONS)
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
    # Sender rule operations
    # ------------------------------------------------------------------

    def add_sender_rule(self, pattern: str, override_category: str, note: str = "") -> int:
        """Add or replace a sender rule. Returns the rule id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT OR REPLACE INTO sender_rules (pattern, override_category, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (pattern.lower().strip(), override_category, note, now),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_sender_rule(self, sender: str) -> Optional[dict]:
        """Return the first matching rule for sender, or None.

        Tries exact email address match first, then @domain match.
        Handles 'Name <addr>' format automatically.
        """
        addr = _extract_email_addr(sender)
        cursor = self._conn.execute(
            "SELECT * FROM sender_rules WHERE pattern = ?", (addr,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        if "@" in addr:
            domain = "@" + addr.split("@", 1)[1]
            cursor = self._conn.execute(
                "SELECT * FROM sender_rules WHERE pattern = ?", (domain,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def list_sender_rules(self) -> list[dict]:
        """Return all sender rules ordered by creation date descending."""
        cursor = self._conn.execute(
            "SELECT * FROM sender_rules ORDER BY created_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_sender_rule(self, rule_id: int) -> None:
        """Delete a sender rule by id."""
        self._conn.execute("DELETE FROM sender_rules WHERE id = ?", (rule_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Triage correction operations
    # ------------------------------------------------------------------

    def save_correction(
        self,
        email_id: str,
        sender: str,
        subject: str,
        original_category: str,
        corrected_category: str,
    ) -> int:
        """Persist a user triage correction. Returns new correction id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO triage_corrections
                (email_id, sender, subject, original_category, corrected_category, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (email_id, sender, subject, original_category, corrected_category, now),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_recent_corrections(self, limit: int = 10) -> list[dict]:
        """Return the most recent triage corrections, newest first."""
        cursor = self._conn.execute(
            """
            SELECT * FROM triage_corrections
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
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
