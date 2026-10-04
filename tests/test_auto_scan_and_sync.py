"""Tests for persistent autonomous auto-scan, background daemon, and BingX account sync."""

import uuid
import pytest
from fastapi.testclient import TestClient
from api import app, tenant_manager
from client import BingXClient
import security
import db

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_bingx_calls(monkeypatch):
    monkeypatch.setattr(BingXClient, "get_balance", lambda self: {
        "asset": "VST",
        "balance": 100000.0,
        "equity": 100000.0,
        "availableMargin": 100000.0,
        "usedMargin": 0.0,
        "unrealizedProfit": 0.0
    })
    monkeypatch.setattr(BingXClient, "get_positions", lambda self: [])

def test_sync_account_endpoint():
    uname = f"sync_trader_{uuid.uuid4().hex[:8]}"
    uid = db.create_user(uname, "Pass123!", "Sync Trader", role="user")
    db.update_user_credentials(uid, "mock_key", "mock_sec", is_demo=True)
    token = security.create_access_token({"sub": str(uid), "role": "user", "username": uname})
    headers = {"Authorization": f"Bearer {token}"}

    # Calling sync endpoint
    res = client.post("/api/account/sync", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["balance"] == 100000.0
    assert "active_positions" in data
    assert "last_sync_at" in data
    assert data["has_keys"] is True

def test_auto_scan_toggle_and_persistence():
    uname = f"autoscan_trader_{uuid.uuid4().hex[:8]}"
    uid = db.create_user(uname, "Pass123!", "AutoScan Trader", role="user")
    db.update_user_credentials(uid, "mock_key", "mock_sec", is_demo=True)
    token = security.create_access_token({"sub": str(uid), "role": "user", "username": uname})
    headers = {"Authorization": f"Bearer {token}"}

    # Start session with auto_scan = True
    start_res = client.post("/api/session/start", json={
        "margin_per_pos": 5.0,
        "leverage": 20,
        "quota": 8,
        "mode": "PUMP_GAINERS",
        "is_live": False,
        "auto_scan": True,
        "scan_interval": 60
    }, headers=headers)
    assert start_res.status_code == 200
    sess = start_res.json()["session"]
    assert sess["auto_scan"] is True
    assert sess["scan_interval"] == 60

    # Verify persisted in database
    latest = db.get_latest_user_session(uid)
    assert latest is not None
    assert latest["auto_scan"] == 1
    assert latest["scan_interval"] == 60

    # Toggle auto_scan to False
    toggle_res = client.post("/api/session/auto-scan", json={
        "auto_scan": False,
        "scan_interval": 120
    }, headers=headers)
    assert toggle_res.status_code == 200
    assert toggle_res.json()["session"]["auto_scan"] is False

    # Check database again
    latest2 = db.get_latest_user_session(uid)
    assert latest2 is not None
    assert latest2["auto_scan"] == 0
    assert latest2["scan_interval"] == 120

    # Summary response reflects persisted auto_scan state
    sum_res = client.get("/api/account/summary", headers=headers)
    assert sum_res.status_code == 200
    s_info = sum_res.json()["session"]
    assert s_info["auto_scan"] is False
    assert s_info["scan_interval"] == 120

    # Clean up
    client.post("/api/session/stop", headers=headers)
