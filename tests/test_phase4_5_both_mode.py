"""Tests for Phase 4 & 5: BOTH direction mode, coexistence safety, and multi-directional execution."""

import pytest
from unittest.mock import MagicMock
from contracts import DirectionMode, ExecutionMode
from orchestrator import SessionOrchestrator
from config import AppConfig
from scanner import CandidatePair
from ai_evaluator import AIEvaluationResult


def test_both_direction_mode_allows_both_short_and_long_entries(mocker):
    cfg = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(cfg)
    orch.start_session(
        margin_per_pos=5.0,
        leverage=20,
        quota=5,
        direction_mode=DirectionMode.BOTH.value,
        execution_mode=ExecutionMode.EXCHANGE_DEMO.value
    )

    cand_short = CandidatePair(
        symbol="MEME1-USDT",
        last_price=10.0,
        price_change_percent=25.0,
        volume_24h_usdt=500000.0,
        bid1=9.99,
        ask1=10.01,
        spread_percent=0.2,
        contract_info={"quantityPrecision": 1, "tradeMinQuantity": "0.1", "tradeMinUSDT": "5.0", "maxLongLeverage": 20}
    )

    cand_long = CandidatePair(
        symbol="MEME2-USDT",
        last_price=5.0,
        price_change_percent=4.0,
        volume_24h_usdt=800000.0,
        bid1=4.99,
        ask1=5.01,
        spread_percent=0.2,
        contract_info={"quantityPrecision": 1, "tradeMinQuantity": "0.1", "tradeMinUSDT": "5.0", "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand_short, cand_long])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.2, "funding_rate": 0.0001, "atr_to_friction": 10.0})

    def mock_eval(*args, **kwargs):
        sym = kwargs.get("symbol")
        if not sym and args:
            sym = args[0]["symbol"] if isinstance(args[0], dict) else args[0]
        sym = str(sym or "UNKNOWN")
        if sym == "MEME1-USDT":
            return AIEvaluationResult(symbol=sym, decision="ENTER_SHORT", confidence=85, is_valid=True)
        return AIEvaluationResult(symbol=sym, decision="ENTER_LONG", confidence=88, is_valid=True)

    mocker.patch.object(orch.ai, "evaluate_candidate", side_effect=mock_eval)
    mocker.patch.object(orch.ai, "evaluate_adversarial", side_effect=mock_eval)

    mock_set_lev = mocker.patch.object(orch.client, "set_leverage")
    mock_place_order = mocker.patch.object(orch.client, "place_order", side_effect=[
        {"orderId": "ord_short_1"},
        {"orderId": "ord_long_2"}
    ])

    res = orch.run_cycle(dry_run=False)

    assert len(res["evaluations"]) == 2
    # Verify both orders executed
    assert mock_place_order.call_count == 2
    call1 = mock_place_order.call_args_list[0].kwargs
    assert call1["symbol"] == "MEME1-USDT"
    assert call1["side"] == "SELL"
    assert call1["position_side"] == "SHORT"

    call2 = mock_place_order.call_args_list[1].kwargs
    assert call2["symbol"] == "MEME2-USDT"
    assert call2["side"] == "BUY"
    assert call2["position_side"] == "LONG"


def test_direction_filter_enforces_short_only_rejection_of_long(mocker):
    cfg = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(cfg)
    orch.start_session(
        margin_per_pos=5.0,
        leverage=20,
        quota=2,
        direction_mode=DirectionMode.SHORT.value,
        execution_mode=ExecutionMode.EXCHANGE_DEMO.value
    )

    cand_long = CandidatePair(
        symbol="PUMP-USDT",
        last_price=10.0,
        price_change_percent=8.0,
        volume_24h_usdt=500000.0,
        bid1=9.99,
        ask1=10.01,
        spread_percent=0.2,
        contract_info={"quantityPrecision": 1, "tradeMinQuantity": "0.1", "tradeMinUSDT": "5.0", "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand_long])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.2, "funding_rate": 0.0001, "atr_to_friction": 10.0})
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=AIEvaluationResult(
        symbol="PUMP-USDT", decision="ENTER_LONG", confidence=90, is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_adversarial", return_value=AIEvaluationResult(
        symbol="PUMP-USDT", decision="ENTER_LONG", confidence=90, is_valid=True
    ))

    mock_place_order = mocker.patch.object(orch.client, "place_order")
    res = orch.run_cycle(dry_run=False)

    # Should NOT place order because session is SHORT-only!
    mock_place_order.assert_not_called()
    assert res["evaluations"][0]["executed"] is False
