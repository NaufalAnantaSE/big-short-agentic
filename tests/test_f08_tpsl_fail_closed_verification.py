"""
Tugas 4 Acceptance Tests: TP/SL verification and fail-closed protection.

Verifies:
1. Normal path: When entry order has TP/SL confirmed resting in open orders, position remains open.
2. Recovery path: When TP/SL is silently dropped, retry via place_tpsl_order is triggered.
3. Fail-closed path: If Stop Loss remains unconfirmed after retry, close_position is immediately
   called fail-closed, guaranteeing no position is ever left naked on the exchange.
"""
import time
import pytest
import uuid
from unittest.mock import MagicMock

from config import AppConfig
from orchestrator import SessionOrchestrator
from scanner import CandidatePair
from contracts import DirectionMode
import db


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / f"test_{uuid.uuid4().hex}.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()


def _build_test_candidate(symbol="PEPE-USDT", last_price=10.0):
    cand = CandidatePair(
        symbol=symbol,
        last_price=last_price,
        bid1=last_price * 0.999,
        ask1=last_price * 1.001,
        volume_24h_usdt=1000000.0,
        price_change_percent=15.0,
        spread_percent=0.10,
        contract_info={
            "minQty": 1.0,
            "stepSize": 1.0,
            "tickSize": 0.01,
            "pricePrecision": 4,
            "quantityPrecision": 0,
            "maxShortLeverage": 20,
            "maxLongLeverage": 20
        }
    )
    return {
        "cand": cand,
        "closes": [last_price * 0.95, last_price * 0.98, last_price],
        "market_features": {
            "atr_14": 0.5,
            "rsi_14": 75.0,
            "spread_pct": 0.10,
            "fresh": True,
            "atr": 0.5,
            "funding_rate": 0.0001,
            "atr_to_friction": 5.0,
        },
        "playbook_match": None,
        "atr_val": 0.5,
        "allowed_directions": ["SHORT"],
        "suggested_direction": "SHORT"
    }


class DummyAIResponse:
    def __init__(self, decision="ENTER_SHORT"):
        self.symbol = "PEPE-USDT"
        self.decision = decision
        self.confidence = 85
        self.setup_type = "PUMP_EXHAUSTION"
        self.key_evidence = "Strong exhaustion"
        self.risk_factors = "none"
        self.invalidation_risk_present = False
        self.invalidation_risk_detail = ""
        self.invalidation_rebuttal = ""
        self.is_valid = True
        self.usage = {"total_tokens": 150}
        self.latency_ms = 100.0


def test_tpsl_verification_normal_path_confirmed(mocker):
    """Normal path: Both SL and TP are confirmed resting on exchange; position remains open."""
    mocker.patch("orchestrator.time.sleep")
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_candidate("PEPE-USDT", 10.0)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))
    mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 10})
    mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "ord_entry_normal_01",
        "status": "FILLED",
        "avgPrice": 10.0
    })
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": int(time.time() * 1000)
    })

    # Exchange reports resting SL and TP in open orders
    mock_open_orders = [
        {"orderId": "sl_01", "positionSide": "SHORT", "type": "STOP_MARKET", "stopPrice": 10.6},
        {"orderId": "tp_01", "positionSide": "SHORT", "type": "TAKE_PROFIT_MARKET", "stopPrice": 8.8}
    ]
    mocker.patch.object(orch.client, "get_open_orders", return_value=mock_open_orders)
    mock_close = mocker.patch.object(orch.client, "close_position")

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False,
        cycle_session_id=session.session_id,
        cycle_session_gen=getattr(session, "generation_token", "")
    )

    assert placed is True
    assert rep.get("tpsl_verified") is True
    assert rep.get("tpsl_verification_status") == "TPSL_VERIFIED"
    # Position must NOT be emergency closed
    mock_close.assert_not_called()


def test_tpsl_verification_silent_drop_recovered_via_retry(mocker):
    """
    Silent drop recovery: Initial open orders check finds no SL/TP.
    Orchestrator detects drop, retries via place_tpsl_order, and subsequent check confirms SL/TP.
    """
    mocker.patch("orchestrator.time.sleep")
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_candidate("PEPE-USDT", 10.0)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))
    mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 10})
    mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "ord_entry_retry_02",
        "status": "FILLED",
        "avgPrice": 10.0
    })
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": int(time.time() * 1000)
    })

    # Initial check returns empty (silent drop), second check after retry returns confirmed orders
    mock_recovered_orders = [
        {"orderId": "sl_retry_02", "positionSide": "SHORT", "type": "STOP_MARKET", "stopPrice": 10.6},
        {"orderId": "tp_retry_02", "positionSide": "SHORT", "type": "TAKE_PROFIT_MARKET", "stopPrice": 8.8}
    ]
    mocker.patch.object(orch.client, "get_open_orders", side_effect=[[], mock_recovered_orders])
    mock_retry_place = mocker.patch.object(orch.client, "place_tpsl_order", return_value={"orderId": "retry_ok"})
    mock_close = mocker.patch.object(orch.client, "close_position")

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False,
        cycle_session_id=session.session_id,
        cycle_session_gen=getattr(session, "generation_token", "")
    )

    assert placed is True
    # Retry was triggered for missing orders
    assert mock_retry_place.call_count >= 1
    assert rep.get("tpsl_verified") is True
    # Position remains open because retry succeeded
    mock_close.assert_not_called()


def test_tpsl_verification_silent_drop_unrecoverable_triggers_fail_closed(mocker):
    """
    Fail-closed protection: Initial check empty, retry fails to register Stop Loss in exchange.
    Orchestrator immediately calls close_position fail-closed, ensuring no naked position.
    """
    mocker.patch("orchestrator.time.sleep")
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_candidate("PEPE-USDT", 10.0)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))
    mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 10})
    mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "ord_entry_failclosed_03",
        "status": "FILLED",
        "avgPrice": 10.0
    })
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": int(time.time() * 1000)
    })

    # Exchange continuously returns empty open orders (persistent silent drop)
    mocker.patch.object(orch.client, "get_open_orders", return_value=[])
    mocker.patch.object(orch.client, "place_tpsl_order", side_effect=Exception("API reject trigger"))
    mock_close = mocker.patch.object(orch.client, "close_position", return_value={"orderId": "emg_close_99"})

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False,
        cycle_session_id=session.session_id,
        cycle_session_gen=getattr(session, "generation_token", "")
    )

    # CRITICAL: Fail-closed emergency closure MUST be triggered
    assert rep.get("tpsl_verified") is False
    assert rep.get("fail_closed_emergency_closed") is True
    mock_close.assert_called_once()
    args, kwargs = mock_close.call_args
    assert kwargs.get("symbol") == "PEPE-USDT"
    assert kwargs.get("position_side") == "SHORT"
    assert kwargs.get("quantity") > 0


def test_tpsl_verification_rejects_stale_order_with_wrong_price(mocker):
    """
    Verification price checking: If exchange has a STOP_MARKET order but with a stale/wrong price
    (e.g., 15.0 instead of 10.6, > 5% tolerance), it is rejected as stale.
    Retry is triggered to place the correct SL, and confirmed upon matching price.
    """
    mocker.patch("orchestrator.time.sleep")
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_candidate("PEPE-USDT", 10.0)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))
    mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 10})
    mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "ord_entry_stale_04",
        "status": "FILLED",
        "avgPrice": 10.0
    })
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": int(time.time() * 1000)
    })

    # First check: Has STOP_MARKET with price 15.0 (stale!), TP 8.8
    stale_orders = [
        {"orderId": "sl_stale", "positionSide": "SHORT", "type": "STOP_MARKET", "stopPrice": 15.0},
        {"orderId": "tp_ok", "positionSide": "SHORT", "type": "TAKE_PROFIT_MARKET", "stopPrice": 8.8}
    ]
    # Second check after retry: Has correct STOP_MARKET with price 10.6
    fresh_orders = [
        {"orderId": "sl_fresh", "positionSide": "SHORT", "type": "STOP_MARKET", "stopPrice": 10.6},
        {"orderId": "tp_ok", "positionSide": "SHORT", "type": "TAKE_PROFIT_MARKET", "stopPrice": 8.8}
    ]
    mocker.patch.object(orch.client, "get_open_orders", side_effect=[stale_orders, fresh_orders])
    mock_retry_place = mocker.patch.object(orch.client, "place_tpsl_order", return_value={"orderId": "retry_ok"})
    mock_close = mocker.patch.object(orch.client, "close_position")

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False,
        cycle_session_id=session.session_id,
        cycle_session_gen=getattr(session, "generation_token", "")
    )

    assert placed is True
    # Retry was triggered specifically for STOP_MARKET because 15.0 was rejected!
    assert mock_retry_place.call_count >= 1
    args, kwargs = mock_retry_place.call_args
    assert kwargs.get("trigger_type") == "STOP_MARKET"
    assert kwargs.get("stop_price") == pytest.approx(10.6, 0.01)
    assert rep.get("tpsl_verified") is True
    mock_close.assert_not_called()


def test_tpsl_fail_closed_emergency_close_retry_on_initial_failure(mocker):
    """
    Emergency close resilience: If initial close_position call throws an error,
    the fail-closed loop retries up to attempt 2 to ensure position closure.
    """
    mocker.patch("orchestrator.time.sleep")
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_candidate("PEPE-USDT", 10.0)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))
    mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 10})
    mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "ord_entry_failclose_retry_05",
        "status": "FILLED",
        "avgPrice": 10.0
    })
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": int(time.time() * 1000)
    })

    mocker.patch.object(orch.client, "get_open_orders", return_value=[])
    mocker.patch.object(orch.client, "place_tpsl_order", side_effect=Exception("API reject trigger"))
    
    # close_position fails on attempt 1, succeeds on attempt 2
    mock_close = mocker.patch.object(orch.client, "close_position", side_effect=[
        Exception("temporary network blip"),
        {"orderId": "emg_close_success"}
    ])

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False,
        cycle_session_id=session.session_id,
        cycle_session_gen=getattr(session, "generation_token", "")
    )

    assert rep.get("tpsl_verified") is False
    assert rep.get("fail_closed_emergency_closed") is True
    # Emergency close retried and succeeded on attempt 2
    assert mock_close.call_count == 2

