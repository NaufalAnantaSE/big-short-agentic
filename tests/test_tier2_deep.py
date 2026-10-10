"""
Unit tests for Tier 2 Single Structured Deep Evaluator.
Validates dual-thesis dialectical evaluation (Bull thesis vs Bear thesis),
verifies confidence gate downgrade (< 70 -> WAIT), and confirms single-call execution.
"""

import pytest
import json
from config import AppConfig
from ai_evaluator import AIEvaluator, AIEvaluationResult, BatchTriageResult, TriageCandidate
from orchestrator import SessionOrchestrator
from scanner import CandidatePair


def test_evaluate_deep_candidate_single_call_dual_thesis(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "symbol": "TRB-USDT",
                    "decision": "ENTER_SHORT",
                    "confidence": 85,
                    "setup_type": "PUMP_EXHAUSTION",
                    "bull_thesis": "Potential short squeeze if volume sustains above resistance",
                    "bear_thesis": "Buyer dry-up, long upper rejection wick on 15m, funding at -0.0005",
                    "key_evidence": "Rejection wick confirmed with declining buying volume",
                    "risk_factors": "High volatility memecoin",
                    "invalidation_risk_present": False
                })
            }
        }],
        "usage": {"prompt_tokens": 300, "completion_tokens": 100, "total_tokens": 400}
    }
    mock_post = mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_deep_candidate({
        "symbol": "TRB-USDT",
        "price": 100.0,
        "price_change_24h": 25.0
    }, direction="SHORT")

    # 1. Assert exactly 1 single HTTP call made (not 3!)
    assert mock_post.call_count == 1

    # 2. Assert valid dual-thesis output
    assert res.is_valid is True
    assert res.decision == "ENTER_SHORT"
    assert res.confidence == 85
    assert res.setup_type == "PUMP_EXHAUSTION"
    assert "Dual-Thesis" in res.key_evidence
    assert "Potential short squeeze" in res.key_evidence
    assert res.usage.get("total_tokens") == 400


def test_evaluate_deep_candidate_confidence_downgrade(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "symbol": "SOL-USDT",
                    "decision": "ENTER_SHORT",
                    "confidence": 65,  # < 70 threshold!
                    "setup_type": "PUMP_EXHAUSTION",
                    "key_evidence": "Weak rejection",
                    "risk_factors": "Moderate buyer volume"
                })
            }
        }],
        "usage": {"total_tokens": 350}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_deep_candidate({
        "symbol": "SOL-USDT",
        "price": 150.0
    }, direction="SHORT")

    assert res.is_valid is True
    # Confidence 65 must be downgraded to WAIT
    assert res.decision == "WAIT"
    assert res.confidence == 65


def test_orchestrator_executes_tier2_deep_candidate(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)

    cand = CandidatePair(
        symbol="DEEP-COIN",
        last_price=10.0,
        price_change_percent=18.0,
        volume_24h_usdt=500000.0,
        bid1=9.99,
        ask1=10.01,
        spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2})

    # Tier 1 Triage selects DEEP-COIN as finalist
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="DEEP-COIN", rank=1, action="DEEP_ANALYZE", conviction_score=90)],
        selected_finalists=["DEEP-COIN"],
        is_valid=True
    ))

    # Mock Tier 2 evaluate_deep_candidate
    mock_deep = mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="DEEP-COIN",
        decision="ENTER_SHORT",
        confidence=88,
        setup_type="PUMP_EXHAUSTION",
        is_valid=True
    ))

    res = orch.run_cycle(dry_run=True)

    # Assert Tier 2 evaluate_deep_candidate was called exactly once
    assert mock_deep.call_count == 1
    assert orch.current_session is not None
    assert orch.current_session.filled_count == 1
    assert "DEEP-COIN" in orch.current_session.executed_symbols
