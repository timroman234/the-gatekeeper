"""Unit tests for src.database.local_store.LocalStore."""
import pytest
from pathlib import Path
from src.database.local_store import LocalStore


@pytest.fixture
def tmp_store(tmp_path):
    return LocalStore(tmp_path / "test.db")


class TestLocalStoreInit:
    def test_creates_tables_on_init(self, tmp_db_path):
        store = LocalStore(tmp_db_path)
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "emails" in tables
        assert "drafts" in tables
        store.close()

    def test_db_file_is_created(self, tmp_db_path):
        store = LocalStore(tmp_db_path)
        store.close()
        assert tmp_db_path.exists()


class TestSaveEmail:
    def test_saves_email(self, tmp_db_path, sample_email):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        row = store.get_email(sample_email.id)
        assert row is not None
        assert row["sender"] == "alice@example.com"
        store.close()

    def test_save_email_idempotent(self, tmp_db_path, sample_email):
        """Saving the same email twice must not raise (INSERT OR IGNORE)."""
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        store.save_email(sample_email)  # should not raise
        store.close()

    def test_thread_id_persisted(self, tmp_db_path, sample_email):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        row = store.get_email(sample_email.id)
        assert row["thread_id"] == "thread-xyz"
        store.close()


class TestUpdateTriage:
    def test_sets_triage_category(self, tmp_db_path, sample_email):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        store.update_triage(sample_email.id, "urgent")
        row = store.get_email(sample_email.id)
        assert row["triage_category"] == "urgent"
        store.close()


class TestMarkProcessed:
    def test_marks_processed(self, tmp_db_path, sample_email):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        store.mark_processed(sample_email.id)
        row = store.get_email(sample_email.id)
        assert row["is_processed"] == 1
        store.close()


class TestGetThreadHistory:
    def test_returns_messages_in_same_thread(
        self, tmp_db_path, sample_email, sample_email_2
    ):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        store.save_email(sample_email_2)
        history = store.get_thread_history("thread-xyz")
        assert len(history) == 2
        store.close()

    def test_history_oldest_first(self, tmp_db_path, sample_email, sample_email_2):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email_2)  # save newer first
        store.save_email(sample_email)
        history = store.get_thread_history("thread-xyz")
        assert history[0]["received_at"] == "2024-01-15T09:00:00Z"
        assert history[1]["received_at"] == "2024-01-15T10:00:00Z"
        store.close()

    def test_returns_empty_for_unknown_thread(self, tmp_db_path):
        store = LocalStore(tmp_db_path)
        history = store.get_thread_history("nonexistent-thread")
        assert history == []
        store.close()

    def test_history_dict_keys(self, tmp_db_path, sample_email):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        history = store.get_thread_history("thread-xyz")
        assert set(history[0].keys()) == {"subject", "body", "sender", "received_at"}
        store.close()


class TestDrafts:
    def test_save_draft_returns_id(self, tmp_db_path, sample_email):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        draft_id = store.save_draft(sample_email.id, "Dear Alice, ...")
        assert isinstance(draft_id, int)
        assert draft_id > 0
        store.close()

    def test_draft_status_defaults_to_pending(self, tmp_db_path, sample_email):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        draft_id = store.save_draft(sample_email.id, "Draft body")
        cursor = store._conn.execute(
            "SELECT status FROM drafts WHERE id=?", (draft_id,)
        )
        assert cursor.fetchone()[0] == "pending"
        store.close()

    def test_update_draft_status(self, tmp_db_path, sample_email):
        store = LocalStore(tmp_db_path)
        store.save_email(sample_email)
        draft_id = store.save_draft(sample_email.id, "Draft body")
        store.update_draft_status(draft_id, "sent")
        cursor = store._conn.execute(
            "SELECT status FROM drafts WHERE id=?", (draft_id,)
        )
        assert cursor.fetchone()[0] == "sent"
        store.close()


class TestSenderRules:
    def test_add_and_list(self, tmp_store):
        rule_id = tmp_store.add_sender_rule("tim@sf415.com", "action_required", "my alt email")
        assert isinstance(rule_id, int)
        rules = tmp_store.list_sender_rules()
        assert len(rules) == 1
        assert rules[0]["pattern"] == "tim@sf415.com"
        assert rules[0]["override_category"] == "action_required"
        assert rules[0]["note"] == "my alt email"

    def test_get_sender_rule_exact_match(self, tmp_store):
        tmp_store.add_sender_rule("tim@sf415.com", "action_required")
        result = tmp_store.get_sender_rule("Tim Roman <tim@sf415.com>")
        assert result is not None
        assert result["override_category"] == "action_required"

    def test_get_sender_rule_domain_match(self, tmp_store):
        tmp_store.add_sender_rule("@sf415.com", "informational", "whole domain")
        result = tmp_store.get_sender_rule("anyone <other@sf415.com>")
        assert result is not None
        assert result["override_category"] == "informational"

    def test_get_sender_rule_exact_wins_over_domain(self, tmp_store):
        tmp_store.add_sender_rule("@sf415.com", "informational")
        tmp_store.add_sender_rule("tim@sf415.com", "urgent")
        result = tmp_store.get_sender_rule("tim@sf415.com")
        assert result["override_category"] == "urgent"

    def test_get_sender_rule_no_match_returns_none(self, tmp_store):
        assert tmp_store.get_sender_rule("nobody@nowhere.com") is None

    def test_delete_sender_rule(self, tmp_store):
        rule_id = tmp_store.add_sender_rule("x@x.com", "spam")
        tmp_store.delete_sender_rule(rule_id)
        assert tmp_store.list_sender_rules() == []


class TestTriageCorrections:
    def test_save_and_retrieve_corrections(self, tmp_store):
        from src.providers.base import EmailMessage
        email = EmailMessage(id="e1", sender="x@x.com", subject="Hi",
                             body="body", received_at="2026-01-01", thread_id="")
        tmp_store.save_email(email)
        correction_id = tmp_store.save_correction(
            "e1", "x@x.com", "Hi", "spam", "action_required"
        )
        assert isinstance(correction_id, int)
        corrections = tmp_store.get_recent_corrections(limit=5)
        assert len(corrections) == 1
        assert corrections[0]["original_category"] == "spam"
        assert corrections[0]["corrected_category"] == "action_required"

    def test_get_recent_corrections_respects_limit(self, tmp_store):
        from src.providers.base import EmailMessage
        for i in range(5):
            e = EmailMessage(id=f"e{i}", sender="x@x.com", subject="s",
                             body="b", received_at="2026-01-01", thread_id="")
            tmp_store.save_email(e)
            tmp_store.save_correction(f"e{i}", "x@x.com", "s", "spam", "informational")
        assert len(tmp_store.get_recent_corrections(limit=3)) == 3

    def test_get_recent_corrections_newest_first(self, tmp_store):
        from src.providers.base import EmailMessage
        for i in range(3):
            e = EmailMessage(id=f"e{i}", sender="x@x.com", subject=f"s{i}",
                             body="b", received_at="2026-01-01", thread_id="")
            tmp_store.save_email(e)
            tmp_store.save_correction(f"e{i}", "x@x.com", f"s{i}", "spam", "informational")
        corrections = tmp_store.get_recent_corrections(limit=10)
        assert corrections[0]["subject"] == "s2"
