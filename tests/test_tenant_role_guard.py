"""Tests for tenant role guard and AI settings integration."""
import pytest
import db
from config import load_config

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'test_guard.db'))
    db.init_db()
    return db

def test_tenant_manager_rejects_admin_role_for_trading(isolated_db):
    from tenant_manager import TenantSessionManager
    base_cfg = load_config()
    mgr = TenantSessionManager(base_cfg)
    admin = db.get_user_by_username('admin')
    
    with pytest.raises(ValueError) as exc:
        mgr.get_client(admin['id'])
    assert "admin" in str(exc.value).lower()

def test_tenant_manager_uses_configured_ai_model(isolated_db):
    from tenant_manager import TenantSessionManager
    from ai_settings import update_ai_settings
    update_ai_settings("ag/gemini-3.7-flash-low")
    
    u_id = db.create_user("trader_ai", "pass123", "Trader AI", "user")
    db.update_user_credentials(u_id, "k", "s", True)
    
    base_cfg = load_config()
    mgr = TenantSessionManager(base_cfg)
    cfg = mgr._build_tenant_config(u_id)
    assert cfg.ai_model_name == "ag/gemini-3.7-flash-low"
