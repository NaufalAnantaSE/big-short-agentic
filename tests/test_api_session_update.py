import uuid
import pytest
from fastapi.testclient import TestClient
from api import app
import security
import db

client = TestClient(app)

def test_session_start_and_update():
    uname = f"trader_up_{uuid.uuid4().hex[:8]}"
    user_id = db.create_user(uname, "Pass123!", "Trader Test", role="user")
    db.update_user_credentials(user_id, "mock_api_key", "mock_sec_key", is_demo=True)
    token = security.create_access_token({"sub": str(user_id), "role": "user", "username": uname})
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Start session with quota 5 and margin 5.0
    start_res = client.post("/api/session/start", json={
        "margin_per_pos": 5.0,
        "leverage": 20,
        "quota": 5,
        "mode": "PUMP_GAINERS",
        "is_live": False
    }, headers=headers)
    assert start_res.status_code == 200
    assert start_res.json()["session"]["quota"] == 5
    assert start_res.json()["session"]["margin_per_pos"] == 5.0

    # 2. Dynamically update quota & margin to 15 & 10.0
    up_res = client.post("/api/session/update", json={
        "margin_per_pos": 10.0,
        "quota": 15
    }, headers=headers)
    assert up_res.status_code == 200
    updated = up_res.json()["session"]
    assert updated["quota"] == 15
    assert updated["margin_per_pos"] == 10.0

    # 3. Stop session
    stop_res = client.post("/api/session/stop", headers=headers)
    assert stop_res.status_code == 200
