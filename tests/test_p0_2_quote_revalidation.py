import pytest
from orchestrator import SessionOrchestrator
from config import AppConfig
from scanner import CandidatePair
from ai_evaluator import AIEvaluationResult, BatchTriageResult, TriageCandidate
from audit_logger import AuditLogger


def make_candidate(symbol: str = "TEST-USDT", price: float = 10.0, spread: float = 0.1):
    return CandidatePair(
        symbol=symbol,
        last_price=price,
        price_change_percent=10.0,
        volume_24h_usdt=500000.0,
        bid1=price * (1 - spread / 200.0),
        ask1=price * (1 + spread / 200.0),
        spread_percent=spread,
        contract_info={
            "quantityPrecision": 2,
            "tradeMinQuantity": "0.1",
            "tradeMinUSDT": "5.0",
            "maxShortLeverage": 20,
            "maxLongLeverage": 20,
            "pricePrecision": 4
        }
    )


def test_order_rejected_when_price_drift_exceeds_threshold(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1)

    # Scanner price is 10.0
    cand = make_candidate(price=10.0, spread=0.1)

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0})
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="TEST-USDT", rank=1, action="DEEP_ANALYZE", conviction_score=85, triage_reason="Test")],
        selected_finalists=["TEST-USDT"],
        is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="TEST-USDT",
        decision="ENTER_SHORT",
        confidence=85,
        setup_type="PUMP_EXHAUSTION",
        is_valid=True
    ))

    # Fresh depth returns drifted price: 10.10 (drift = 1.0% > 0.50% threshold)
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["10.10", "100"]],
        "asks": [["10.11", "100"]],
        "T": 1700000000000
    })

    mock_place_order = mocker.patch.object(orch.client, "place_order")
    mock_log_veto = mocker.patch.object(AuditLogger, "log_event")

    res = orch.run_cycle(dry_run=False)

    # Order must be vetoed / rejected due to price drift
    mock_place_order.assert_not_called()
    assert len(res["evaluations"]) == 1
    eval_rep = res["evaluations"][0]
    assert eval_rep["executed"] is False
    assert "price_drift_exceeded" in eval_rep.get("veto_reason", "")


def test_order_accepted_and_resized_when_drift_within_threshold(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1)

    # Scanner price is 10.0
    cand = make_candidate(price=10.0, spread=0.1)

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0})
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="TEST-USDT", rank=1, action="DEEP_ANALYZE", conviction_score=85, triage_reason="Test")],
        selected_finalists=["TEST-USDT"],
        is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="TEST-USDT",
        decision="ENTER_SHORT",
        confidence=85,
        setup_type="PUMP_EXHAUSTION",
        is_valid=True
    ))

    # Fresh depth returns slight drift within tolerance: bid 10.02 (drift = 0.20% <= 0.50%)
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["10.02", "100"]],
        "asks": [["10.03", "100"]],
        "T": 1700000000000
    })
    mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 20})
    mock_place_order = mocker.patch.object(orch.client, "place_order", return_value={
        "order": {"orderId": "order_123", "avgPrice": "10.02", "status": "FILLED"}
    })

    res = orch.run_cycle(dry_run=False)

    mock_place_order.assert_called_once()
    eval_rep = res["evaluations"][0]
    assert eval_rep["executed"] is True
    # Verify sizing used fresh executable price 10.02, NOT stale 10.00
    assert eval_rep["sizing"]["entry_price"] == 10.02


def test_order_rejected_when_spread_blows_out_at_execution(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1)

    cand = make_candidate(price=10.0, spread=0.1)

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0})
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="TEST-USDT", rank=1, action="DEEP_ANALYZE", conviction_score=85, triage_reason="Test")],
        selected_finalists=["TEST-USDT"],
        is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="TEST-USDT",
        decision="ENTER_SHORT",
        confidence=85,
        setup_type="PUMP_EXHAUSTION",
        is_valid=True
    ))

    # Fresh depth shows spread blowout: bid=10.00, ask=10.06 -> spread 0.60% > max 0.35%
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["10.00", "100"]],
        "asks": [["10.06", "100"]],
        "T": 1700000000000
    })

    mock_place_order = mocker.patch.object(orch.client, "place_order")

    res = orch.run_cycle(dry_run=False)

    mock_place_order.assert_not_called()
    eval_rep = res["evaluations"][0]
    assert eval_rep["executed"] is False
    assert "spread_too_wide_at_execution" in eval_rep.get("veto_reason", "")


def test_telemetry_records_actual_avg_fill_and_slippage(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1)

    cand = make_candidate(price=10.0, spread=0.1)

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0})
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="TEST-USDT", rank=1, action="DEEP_ANALYZE", conviction_score=85, triage_reason="Test")],
        selected_finalists=["TEST-USDT"],
        is_valid=True
    ))
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="TEST-USDT",
        decision="ENTER_SHORT",
        confidence=85,
        setup_type="PUMP_EXHAUSTION",
        is_valid=True
    ))

    # Quote executable price is 10.00
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["10.00", "100"]],
        "asks": [["10.01", "100"]],
        "T": 1700000000000
    })
    mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 20})

    # Exchange fills at 9.98 (actual avgPrice from exchange response)
    mocker.patch.object(orch.client, "place_order", return_value={
        "order": {"orderId": "order_777", "avgPrice": "9.98", "status": "FILLED"}
    })

    spy_log = mocker.spy(AuditLogger, "log_order_submission")

    res = orch.run_cycle(dry_run=False)

    eval_rep = res["evaluations"][0]
    assert eval_rep["executed"] is True
    assert eval_rep["avg_fill_price"] == 9.98
    assert eval_rep["request_price"] == 10.00
    assert eval_rep["slippage"] == pytest.approx(-0.02)

    # Verify AuditLogger recorded exact fill telemetry
    spy_log.assert_called_once()
    kwargs = spy_log.call_args.kwargs
    assert kwargs["avg_fill_price"] == 9.98
    assert kwargs["request_price"] == 10.00
    assert kwargs["slippage"] == pytest.approx(-0.02)
    assert kwargs["quote_ts"] == 1700000000000
