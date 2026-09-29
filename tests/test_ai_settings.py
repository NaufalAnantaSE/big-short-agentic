"""Tests for AI settings persistence and retrieval."""
import pytest
import db
from config import load_config

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'test_ai.db'))
    db.init_db()
    return db

def test_ai_settings_default_and_update(isolated_db):
    from ai_settings import get_ai_settings, update_ai_settings
    
    # 1. Default settings fallback to base config
    settings = get_ai_settings()
    assert "model" in settings
    assert settings["gateway_url"].startswith("http")
    assert settings["applies_to"] == "new_sessions"
    
    # 2. Update model
    updated = update_ai_settings("ag/gemini-3.7-flash")
    assert updated["model"] == "ag/gemini-3.7-flash"
    
    # 3. Subsequent get reflects updated model
    assert get_ai_settings()["model"] == "ag/gemini-3.7-flash"

def test_ai_settings_rejects_empty_model(isolated_db):
    from ai_settings import update_ai_settings
    with pytest.raises(ValueError):
        update_ai_settings("   ")
