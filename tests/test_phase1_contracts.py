"""TDD Tests for Phase 1: Execution Mode and Direction Contract.

Validates:
1. Explicit Enums for Environment, ExecutionMode, DirectionMode, and TradeAction.
2. Database schema evolution with backward-compatible defaults for existing sessions.
3. Dynamic order_records supporting both LONG and SHORT (not hardcoded to SELL/SHORT).
4. Client-side assertion of side and position_side pairing.
5. Orchestrator SessionState and start_session with explicit contracts.
6. API SessionStartRequest accepting explicit contracts while maintaining backward compatibility.
"""

import pytest
import uuid
import time
from fastapi.testclient import TestClient

import db
from config import AppConfig
from client import BingXClient, BingXAPIError
from orchestrator import SessionOrchestrator, SessionState
from contracts import Environment, ExecutionMode, DirectionMode, TradeAction, ExitPolicy


def test_contracts_enum_definitions():
    assert Environment.BINGX_VST == "BINGX_VST"
    assert Environment.BINGX_LIVE == "BINGX_LIVE"

    assert ExecutionMode.LOCAL_PAPER == "LOCAL_PAPER"
    assert ExecutionMode.EXCHANGE_DEMO == "EXCHANGE_DEMO"
    assert ExecutionMode.EXCHANGE_LIVE == "EXCHANGE_LIVE"

    assert DirectionMode.SHORT == "SHORT"
    assert DirectionMode.LONG == "LONG"
    assert DirectionMode.BOTH == "BOTH"

    assert ExitPolicy.MANUAL_ONLY == "MANUAL_ONLY"

    assert TradeAction.OPEN_SHORT == "OPEN_SHORT"
    assert TradeAction.OPEN_LONG == "OPEN_LONG"
    assert TradeAction.CLOSE_SHORT == "CLOSE_SHORT"
    assert TradeAction.CLOSE_LONG == "CLOSE_LONG"
    assert TradeAction.NO_NEW_RISK == "NO_NEW_RISK"
    assert TradeAction.NO_CHANGE == "NO_CHANGE"


def test_db_session_stores_and_loads_phase1_contracts():
    uid = db.create_user(f"u_p1_{uuid.uuid4().hex[:6]}", "Pass123!", role="user")
    sess_id = f"bx_test_{uuid.uuid4().hex[:8]}"

    # Save session with explicit contracts
    db.save_session(
        session_id=sess_id,
        user_id=uid,
        status="ACTIVE_SEARCHING",
        margin=5.0,
        leverage=20,
        quota=5,
        filled_count=0,
        mode="PUMP_GAINERS",
        is_live=False,
        started_at=time.time(),
        environment="BINGX_VST",
        execution_mode="EXCHANGE_DEMO",
        direction_mode="SHORT",
        exit_policy="MANUAL_ONLY"
    )

    loaded = db.get_latest_user_session(uid)
    assert loaded is not None
    assert loaded["session_id"] == sess_id
    assert loaded["environment"] == "BINGX_VST"
    assert loaded["execution_mode"] == "EXCHANGE_DEMO"
    assert loaded["direction_mode"] == "SHORT"
    assert loaded["exit_policy"] == "MANUAL_ONLY"


def test_db_record_order_supports_both_short_and_long():
    uid = db.create_user(f"u_ord_{uuid.uuid4().hex[:6]}", "Pass123!", role="user")
    sess_id = f"bx_ord_{uuid.uuid4().hex[:8]}"

    # Record SHORT order
    db.record_order(
        user_id=uid,
        session_id=sess_id,
        symbol="DOGE-USDT",
        quantity=100.0,
        price=0.1,
        notional=10.0,
        leverage=20,
        client_order_id="c_short_1",
        order_id="11111",
        status="FILLED",
        side="SELL",
        position_side="SHORT"
    )

    # Record LONG order
    db.record_order(
        user_id=uid,
        session_id=sess_id,
        symbol="PEPE-USDT",
        quantity=500.0,
        price=0.002,
        notional=10.0,
        leverage=20,
        client_order_id="c_long_1",
        order_id="22222",
        status="FILLED",
        side="BUY",
        position_side="LONG"
    )

    orders = db.get_user_orders(uid)
    assert len(orders) == 2
    # Verify order sides are accurately recorded
    order_map = {o["symbol"]: o for o in orders}
    assert order_map["DOGE-USDT"]["side"] == "SELL"
    assert order_map["DOGE-USDT"]["position_side"] == "SHORT"
    assert order_map["PEPE-USDT"]["side"] == "BUY"
    assert order_map["PEPE-USDT"]["position_side"] == "LONG"


def test_client_enforces_side_and_position_side_coupling():
    cfg = AppConfig(api_key="mock", secret_key="mock")
    client = BingXClient(cfg)

    # Invalid pairings must raise ValueError before touching exchange
    with pytest.raises(ValueError, match="Invalid order pairing"):
        client.place_order(
            symbol="BTC-USDT",
            side="BUY",
            position_side="SHORT",  # Invalid! To open SHORT must be SELL
            order_type="MARKET",
            quantity=1.0,
            client_order_id="test_inv_1"
        )

    with pytest.raises(ValueError, match="Invalid order pairing"):
        client.place_order(
            symbol="BTC-USDT",
            side="SELL",
            position_side="LONG",  # Invalid! To open LONG must be BUY
            order_type="MARKET",
            quantity=1.0,
            client_order_id="test_inv_2"
        )


def test_orchestrator_initializes_with_explicit_contracts():
    cfg = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(cfg)
    sess = orch.start_session(
        margin_per_pos=5.0,
        leverage=20,
        quota=3,
        environment="BINGX_VST",
        execution_mode="EXCHANGE_DEMO",
        direction_mode="SHORT",
        exit_policy="MANUAL_ONLY"
    )
    assert sess.environment == "BINGX_VST"
    assert sess.execution_mode == "EXCHANGE_DEMO"
    assert sess.direction_mode == "SHORT"
    assert sess.exit_policy == "MANUAL_ONLY"


def test_local_paper_execution_mode_never_calls_exchange(mocker):
    cfg = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(cfg)
    orch.start_session(
        margin_per_pos=5.0,
        leverage=20,
        quota=1,
        execution_mode="LOCAL_PAPER"
    )

    from scanner import CandidatePair
    from ai_evaluator import AIEvaluationResult

    cand = CandidatePair(
        symbol="1000PEPE-USDT",
        last_price=0.008,
        price_change_percent=12.0,
        volume_24h_usdt=500000.0,
        bid1=0.00799,
        ask1=0.00800,
        spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0})
    from ai_evaluator import BatchTriageResult, TriageCandidate
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="1000PEPE-USDT", rank=1, action="DEEP_ANALYZE", conviction_score=85)],
        selected_finalists=["1000PEPE-USDT"],
        is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="1000PEPE-USDT", decision="ENTER_SHORT", confidence=85, is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=AIEvaluationResult(
        symbol="1000PEPE-USDT", decision="ENTER_SHORT", confidence=85, is_valid=True
    ))

    mock_set_lev = mocker.patch.object(orch.client, "set_leverage")
    mock_place_order = mocker.patch.object(orch.client, "place_order")

    # Run cycle with dry_run=False but execution_mode is LOCAL_PAPER
    res = orch.run_cycle(dry_run=False)

    # Must NOT call exchange endpoints in LOCAL_PAPER mode
    mock_set_lev.assert_not_called()
    mock_place_order.assert_not_called()
    ev = res["evaluations"][0]
    assert ev["executed"] is False
    assert ev["dry_run"] is True
    assert "LOCAL-PAPER" in ev.get("message", "")


def test_api_session_start_and_summary_contract_roundtrip():
    from api import app
    import security

    test_client = TestClient(app)
    uname = f"u_api_{uuid.uuid4().hex[:6]}"
    uid = db.create_user(uname, "Pass123!", role="user")
    db.update_user_credentials(uid, "test_k", "test_s", is_demo=True)
    tok = security.create_access_token({"sub": str(uid), "role": "user", "username": uname})
    hdrs = {"Authorization": f"Bearer {tok}"}

    # Start session with explicit contracts
    res = test_client.post("/api/session/start", json={
        "margin_per_pos": 5.0,
        "leverage": 20,
        "quota": 3,
        "environment": "BINGX_VST",
        "execution_mode": "EXCHANGE_DEMO",
        "direction_mode": "SHORT",
        "exit_policy": "MANUAL_ONLY"
    }, headers=hdrs)
    assert res.status_code == 200
    sess = res.json()["session"]
    assert sess["environment"] == "BINGX_VST"
    assert sess["execution_mode"] == "EXCHANGE_DEMO"
    assert sess["direction_mode"] == "SHORT"
    assert sess["exit_policy"] == "MANUAL_ONLY"
