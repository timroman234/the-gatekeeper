"""Integration tests for the LangGraph DAG — built up across Tasks 6-9."""
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
