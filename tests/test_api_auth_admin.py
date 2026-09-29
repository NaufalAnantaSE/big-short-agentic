"""Unit and integration tests for FastAPI multi-tenant authentication,
public registration lockdown, admin user management, and strict admin/trader role separation.
"""

import time
import uuid
import pytest
from fastapi.testclient import TestClient
from api import app
import db

@pytest.fixture
def client():
    return TestClient(app)

def test_public_registration_is_forbidden(client):
    """Verify that public registration is locked down (requires admin)."""
    res = client.post("/api/auth/register", json={
        "username": f"intruder_{uuid.uuid4().hex[:6]}",
        "password": "password123",
        "full_name": "Random User"
    })
    assert res.status_code == 403
    assert "Pendaftaran mandiri dinonaktifkan" in res.json().get("detail", "")

def test_admin_auth_and_user_creation(client):
    """Verify that admin can login, create users, reset passwords, and delete users."""
    suffix = uuid.uuid4().hex[:6]
    nonadmin_username = f"nonadmin_{suffix}"
    vip_username = f"vip_{suffix}"

    # 1. Admin login
    login_res = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "naufal2026admin"
    })
    assert login_res.status_code == 200
    admin_token = login_res.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Non-admin access to admin endpoint is rejected
    db.create_user(nonadmin_username, "password123", "Non Admin", "user")
    user_jwt = client.post("/api/auth/login", json={
        "username": nonadmin_username,
        "password": "password123"
    }).json()["token"]
    forbidden_res = client.get("/api/admin/users", headers={"Authorization": f"Bearer {user_jwt}"})
    assert forbidden_res.status_code == 403

    # 3. Admin creates client account
    create_res = client.post("/api/admin/users", json={
        "username": vip_username,
        "password": "vip_password_2026",
        "full_name": "Klien VIP",
        "is_demo": True
    }, headers=admin_headers)
    assert create_res.status_code == 200
    new_user = create_res.json()["user"]
    new_user_id = new_user["id"]
    assert new_user["username"] == vip_username

    # 4. Newly created client can login
    client_login = client.post("/api/auth/login", json={
        "username": vip_username,
        "password": "vip_password_2026"
    })
    assert client_login.status_code == 200
    assert client_login.json()["user"]["role"] == "user"

    # 5. Admin resets password
    reset_res = client.post(f"/api/admin/users/{new_user_id}/reset-password", json={
        "new_password": "new_vip_password_99"
    }, headers=admin_headers)
    assert reset_res.status_code == 200

    # Verify old password fails and new password succeeds
    fail_login = client.post("/api/auth/login", json={
        "username": vip_username,
        "password": "vip_password_2026"
    })
    assert fail_login.status_code == 401

    ok_login = client.post("/api/auth/login", json={
        "username": vip_username,
        "password": "new_vip_password_99"
    })
    assert ok_login.status_code == 200

    # 6. Admin cannot delete admin self
    admin_self = client.get("/api/auth/me", headers=admin_headers).json()
    self_delete = client.delete(f"/api/admin/users/{admin_self['id']}", headers=admin_headers)
    assert self_delete.status_code == 400

    # 7. Admin deletes client account
    delete_res = client.delete(f"/api/admin/users/{new_user_id}", headers=admin_headers)
    assert delete_res.status_code == 200

def test_role_separation_admin_blocked_from_trading(client):
    """Verify that admin cannot run bot trading or query account balances, but trader accounts can."""
    # 1. Admin login
    admin_res = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "naufal2026admin"
    })
    assert admin_res.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_res.json()['token']}"}

    # Admin is blocked from trading endpoints with 403 Forbidden
    summary_res = client.get("/api/account/summary", headers=admin_headers)
    assert summary_res.status_code == 403
    assert "Akun admin dikhususkan untuk manajemen sistem" in summary_res.json().get("detail", "")

    start_res = client.post("/api/session/start", json={"margin_per_pos": 5.0}, headers=admin_headers)
    assert start_res.status_code == 403

    creds_res = client.post("/api/credentials", json={"api_key": "k", "secret_key": "s"}, headers=admin_headers)
    assert creds_res.status_code == 403

    orders_res = client.get("/api/orders", headers=admin_headers)
    assert orders_res.status_code == 403

    # 2. Trader account (naufal personal) can access trader endpoints
    trader_res = client.post("/api/auth/login", json={
        "username": "naufal",
        "password": "naufal2026trader"
    })
    assert trader_res.status_code == 200
    trader_headers = {"Authorization": f"Bearer {trader_res.json()['token']}"}

    trader_summary = client.get("/api/account/summary", headers=trader_headers)
    # Status code 200 means trader role passed the require_trader gate!
    assert trader_summary.status_code == 200

def test_admin_ai_settings_and_sessions(client):
    """Verify that admin can read/update AI model settings and monitor client sessions."""
    admin_res = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "naufal2026admin"
    })
    admin_headers = {"Authorization": f"Bearer {admin_res.json()['token']}"}

    # 1. Get AI settings
    get_res = client.get("/api/admin/ai-settings", headers=admin_headers)
    assert get_res.status_code == 200
    assert "model" in get_res.json()
    assert "gateway_url" in get_res.json()

    # 2. Update AI settings
    put_res = client.put("/api/admin/ai-settings", json={"model": "ag/gemini-3.7-flash"}, headers=admin_headers)
    assert put_res.status_code == 200
    assert put_res.json()["model"] == "ag/gemini-3.7-flash"

    # Reset back to default
    client.put("/api/admin/ai-settings", json={"model": "ag/gemini-3.8-flash"}, headers=admin_headers)

    # 3. Monitor client sessions
    sess_res = client.get("/api/admin/sessions", headers=admin_headers)
    assert sess_res.status_code == 200
    assert "sessions" in sess_res.json()
