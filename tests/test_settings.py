"""Tests for config.settings — validates that Settings loads correctly from env."""
import os
import pytest
from pathlib import Path


def test_settings_loads_anthropic_key(monkeypatch):
    """Settings must load ANTHROPIC_API_KEY from environment."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("DB_PATH", "data/test.db")
    monkeypatch.setenv("CHECKPOINT_PATH", "data/test_checkpoints.db")
    import importlib
    import config.settings as settings_module
    importlib.reload(settings_module)
    assert settings_module.settings.anthropic_api_key == "sk-ant-test"


def test_settings_db_path_is_path_object(monkeypatch):
    """DB_PATH must deserialise to a Path, not a string."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("DB_PATH", "data/test.db")
    monkeypatch.setenv("CHECKPOINT_PATH", "data/test_checkpoints.db")
    import importlib
    import config.settings as settings_module
    importlib.reload(settings_module)
    assert isinstance(settings_module.settings.db_path, Path)


def test_settings_defaults(monkeypatch):
    """email_max_results defaults to 10 when EMAIL_MAX_RESULTS is not set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("DB_PATH", "data/test.db")
    monkeypatch.setenv("CHECKPOINT_PATH", "data/test_checkpoints.db")
    monkeypatch.delenv("EMAIL_MAX_RESULTS", raising=False)
    import importlib
    import config.settings as settings_module
    importlib.reload(settings_module)
    assert isinstance(settings_module.settings.email_max_results, int)
    assert settings_module.settings.email_max_results == 10
