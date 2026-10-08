"""TDD Tests for Phase 2: Long Strategy Features, Evaluator, and Orchestration.

Tests:
1. AI evaluator normalizes LONG, BUY, ENTER_LONG and enforces 70% confidence gate.
2. Market features compute lower wick rejection and Fibonacci golden pullback zone.
3. Plain explainer generates humanized Indonesian explanations for ENTER_LONG.
4. Orchestrator executes LONG in LOCAL_PAPER without exchange calls.
5. Orchestrator executes LONG in EXCHANGE_DEMO with set_leverage(side='LONG') and place_order(side='BUY', position_side='LONG').
"""

import json
import pytest
from unittest.mock import MagicMock
from ai_evaluator import normalize_ai_payload, AIEvaluationResult, AIEvaluator, BatchTriageResult, TriageCandidate
from plain_explainer import humanize_ai_decision
from orchestrator import SessionOrchestrator
from config import AppConfig
from scanner import CandidatePair


def test_ai_evaluator_supports_long_decisions():
    # Test normalization of LONG decisions
    p1 = normalize_ai_payload({"decision": "LONG", "confidence": 85, "reasoning": "Golden pocket bounce"})
    assert p1["decision"] == "ENTER_LONG"
    assert p1["confidence"] == 85

    p2 = normalize_ai_payload({"decision": "BUY", "confidence": 75, "reasoning": "Support reclaim"})
    assert p2["decision"] == "ENTER_LONG"

    p3 = normalize_ai_payload({"decision": "ENTER_LONG", "confidence": 90})
    assert p3["decision"] == "ENTER_LONG"

    # Quality gate: confidence < 70 should fallback to WAIT
    cfg = AppConfig(api_key="mock", secret_key="mock")
    evaluator = AIEvaluator(cfg)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({"decision": "ENTER_LONG", "confidence": 65, "setup_type": "BULLISH_PULLBACK"})
            }
        }],
        "usage": {"total_tokens": 100}
    }
    evaluator.client.post = MagicMock(return_value=mock_resp)

    res = evaluator.evaluate_candidate(
        symbol="DOGE-USDT",
        price_change_24h=5.0,
        current_price=0.1,
        klines_summary=[0.09, 0.095, 0.1],
        spread_pct=0.05,
        market_features={"fibonacci": {"zone": "MID_RETRACEMENT"}}
    )
    assert res.decision == "WAIT"


def test_plain_explainer_humanizes_long_decision():
    exp = humanize_ai_decision(
        symbol="SOL-USDT",
        decision="ENTER_LONG",
        confidence=88,
        evidence="Harga memantul di zona support Fibonacci 50% dengan lower rejection wick",
        risk_factors="Potensi fakeout jika Bitcoin drop",
        price=150.0,
        change_24h=4.5,
        spread_pct=0.07,
        executed=True,
        order_id="ord_long_99",
        dry_run=False,
        fibonacci={"zone": "MID_RETRACEMENT", "retracement_ratio": 0.50}
    )
    assert "Beli" in exp["summary_title"] or "LONG" in exp["summary_title"] or "Long" in exp["summary_title"]
    assert exp["badge_color"] in ("sky", "emerald", "blue")
    assert "SOL" in exp["summary_title"]


def test_orchestrator_paper_mode_handles_long_without_exchange_calls(mocker):
    cfg = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(cfg)
    orch.start_session(
        margin_per_pos=5.0,
        leverage=20,
        quota=2,
        direction_mode="LONG",
        execution_mode="LOCAL_PAPER"
    )

    cand = CandidatePair(
        symbol="SOL-USDT",
        last_price=150.0,
        price_change_percent=4.5,
        volume_24h_usdt=1000000.0,
        bid1=149.95,
        ask1=150.05,
        spread_percent=0.07,
        contract_info={"quantityPrecision": 2, "tradeMinQuantity": "0.01", "tradeMinUSDT": "5.0", "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.07, "funding_rate": 0.0001, "atr_to_friction": 10.0})
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="SOL-USDT", rank=1, action="DEEP_ANALYZE", conviction_score=85)],
        selected_finalists=["SOL-USDT"],
        is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="SOL-USDT", decision="ENTER_LONG", confidence=85, is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=AIEvaluationResult(
        symbol="SOL-USDT", decision="ENTER_LONG", confidence=85, is_valid=True
    ))

    mock_set_lev = mocker.patch.object(orch.client, "set_leverage")
    mock_place_order = mocker.patch.object(orch.client, "place_order")

    res = orch.run_cycle(dry_run=False)

    mock_set_lev.assert_not_called()
    mock_place_order.assert_not_called()
    assert len(res["evaluations"]) == 1
    ev = res["evaluations"][0]
    assert ev["executed"] is False
    assert ev["dry_run"] is True
    assert "LOCAL-PAPER" in ev.get("message", "")
    assert "LONG" in ev.get("message", "")


def test_orchestrator_exchange_demo_executes_long_order(mocker):
    cfg = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(cfg)
    orch.start_session(
        margin_per_pos=5.0,
        leverage=20,
        quota=2,
        direction_mode="LONG",
        execution_mode="EXCHANGE_DEMO"
    )

    cand = CandidatePair(
        symbol="SOL-USDT",
        last_price=150.0,
        price_change_percent=4.5,
        volume_24h_usdt=1000000.0,
        bid1=149.95,
        ask1=150.05,
        spread_percent=0.07,
        contract_info={"quantityPrecision": 2, "tradeMinQuantity": "0.01", "tradeMinUSDT": "5.0", "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.07, "funding_rate": 0.0001, "atr_to_friction": 10.0})
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="SOL-USDT", rank=1, action="DEEP_ANALYZE", conviction_score=85)],
        selected_finalists=["SOL-USDT"],
        is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="SOL-USDT", decision="ENTER_LONG", confidence=85, is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=AIEvaluationResult(
        symbol="SOL-USDT", decision="ENTER_LONG", confidence=85, is_valid=True
    ))

    mock_set_lev = mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 20})
    mock_place_order = mocker.patch.object(orch.client, "place_order", return_value={"orderId": "99999"})

    res = orch.run_cycle(dry_run=False)

    # Must set leverage with side="LONG"
    mock_set_lev.assert_called_once_with(symbol="SOL-USDT", leverage=20, side="LONG")
    # Must place order with side="BUY" and position_side="LONG"
    mock_place_order.assert_called_once()
    call_kwargs = mock_place_order.call_args.kwargs
    assert call_kwargs["side"] == "BUY"
    assert call_kwargs["position_side"] == "LONG"
    assert call_kwargs["symbol"] == "SOL-USDT"
    assert res["evaluations"][0]["executed"] is True
    assert res["evaluations"][0]["order_id"] == "99999"
