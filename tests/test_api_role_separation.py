"""Tests for role separation and AI settings endpoints in API."""
import pytest
from fastapi.testclient import TestClient
from api import app
import db
import security

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'test_api_roles.db'))
    db.init_db()
    return TestClient(app)

def test_admin_blocked_from_trading_endpoints(client):
    admin_token = security.create_access_token({'sub': '1', 'role': 'admin', 'username': 'admin'})
    headers = {'Authorization': f'Bearer {admin_token}'}
    
    # 1. Summary
    res = client.get('/api/account/summary', headers=headers)
    assert res.status_code == 403
    assert "admin" in res.json().get("detail", "").lower()
    
    # 2. Save credentials
    res = client.post('/api/credentials', json={'api_key': 'k', 'secret_key': 's'}, headers=headers)
    assert res.status_code == 403
    
    # 3. Session start
    res = client.post('/api/session/start', json={'margin_per_pos': 5.0, 'leverage': 20, 'quota': 10}, headers=headers)
    assert res.status_code == 403
    
    # 4. Session cycle
    res = client.post('/api/session/cycle', json={'dry_run': True}, headers=headers)
    assert res.status_code == 403

def test_admin_can_manage_ai_settings(client):
    admin_token = security.create_access_token({'sub': '1', 'role': 'admin', 'username': 'admin'})
    admin_headers = {'Authorization': f'Bearer {admin_token}'}
    
    user_id = db.create_user('trader1', 'pass123', 'Trader', 'user')
    user_token = security.create_access_token({'sub': str(user_id), 'role': 'user', 'username': 'trader1'})
    user_headers = {'Authorization': f'Bearer {user_token}'}
    
    # User cannot access AI settings
    res = client.get('/api/admin/ai-settings', headers=user_headers)
    assert res.status_code == 403
    
    # Admin can get AI settings
    get_res = client.get('/api/admin/ai-settings', headers=admin_headers)
    assert get_res.status_code == 200
    assert "model" in get_res.json()
    assert get_res.json()["applies_to"] == "new_sessions"
    
    # Admin can update AI settings
    put_res = client.put('/api/admin/ai-settings', json={'model': 'ag/gemini-3.7-flash'}, headers=admin_headers)
    assert put_res.status_code == 200
    assert put_res.json()["model"] == "ag/gemini-3.7-flash"
    
    # Verified persisted
    get_res2 = client.get('/api/admin/ai-settings', headers=admin_headers)
    assert get_res2.json()["model"] == "ag/gemini-3.7-flash"
