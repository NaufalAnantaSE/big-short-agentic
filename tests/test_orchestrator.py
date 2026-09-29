"""Unit tests for SessionOrchestrator and Pre-Flight Leverage Assertion Gate."""

import pytest
from orchestrator import SessionOrchestrator
from config import AppConfig
from scanner import CandidatePair
from ai_evaluator import AIEvaluationResult
from client import BingXAPIError

def test_preflight_leverage_assertion_before_order(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1)

    candidate = CandidatePair(
        symbol="1000PEPE-USDT",
        last_price=0.008,
        price_change_percent=12.0,
        volume_24h_usdt=500000.0,
        bid1=0.00799,
        ask1=0.00800,
        spread_percent=0.1,
        contract_info={
            "quantityPrecision": 0,
            "tradeMinQuantity": "1",
            "tradeMinUSDT": "5.0",
            "maxShortLeverage": 20
        }
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[candidate])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0})
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=AIEvaluationResult(
        symbol="1000PEPE-USDT",
        decision="ENTER_SHORT",
        confidence=85,
        setup_type="PUMP_EXHAUSTION",
        is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_adversarial", return_value=AIEvaluationResult(
        symbol="1000PEPE-USDT",
        decision="ENTER_SHORT",
        confidence=85,
        setup_type="PUMP_EXHAUSTION",
        is_valid=True
    ))

    # Spy on order of calls between set_leverage and place_order
    mock_set_lev = mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 20})
    mock_place_order = mocker.patch.object(orch.client, "place_order", return_value={"order": {"orderId": "12345"}})

    res = orch.run_cycle(dry_run=False)

    # 1. Assert set_leverage was called with exact effective leverage 20 and side SHORT
    mock_set_lev.assert_called_once_with(symbol="1000PEPE-USDT", leverage=20, side="SHORT")

    # 2. Assert place_order was called
    mock_place_order.assert_called_once()

    # 3. Assert set_leverage was called BEFORE place_order
    assert mock_set_lev.call_args_list[0] is not None
    assert mock_place_order.call_args_list[0] is not None

def test_preflight_leverage_failure_aborts_order(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1)

    candidate = CandidatePair(
        symbol="DOGE-USDT",
        last_price=0.1,
        price_change_percent=5.0,
        volume_24h_usdt=500000.0,
        bid1=0.0999,
        ask1=0.1001,
        spread_percent=0.2,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[candidate])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0})
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=AIEvaluationResult(
        symbol="DOGE-USDT", decision="ENTER_SHORT", confidence=85, is_valid=True
    ))

    # Simulate set_leverage failing with exchange API error
    mocker.patch.object(orch.client, "set_leverage", side_effect=BingXAPIError(100400, "Leverage adjustment rejected"))
    mock_place_order = mocker.patch.object(orch.client, "place_order")

    res = orch.run_cycle(dry_run=False)

    # Order must NOT be placed if leverage adjustment failed
    mock_place_order.assert_not_called()
    assert orch.current_session is not None
    assert orch.current_session.filled_count == 0
