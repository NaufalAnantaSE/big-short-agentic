"""
TDD tests for Orchestrator Tier 1 Batch Triage candidate cap (max 4),
balanced direction selection in BOTH mode, and enhanced telemetry logging.
"""

import pytest
from unittest.mock import MagicMock
from config import AppConfig
from ai_evaluator import BatchTriageResult, TriageCandidate
from orchestrator import SessionOrchestrator
from scanner import CandidatePair


def make_cand(symbol: str, price_chg: float = 10.0, spread: float = 0.1) -> CandidatePair:
    return CandidatePair(
        symbol=symbol,
        last_price=10.0,
        price_change_percent=price_chg,
        volume_24h_usdt=500000.0,
        bid1=9.99,
        ask1=10.01,
        spread_percent=spread,
        contract_info={
            "quantityPrecision": 0,
            "tradeMinQuantity": "1",
            "tradeMinUSDT": "5.0",
            "maxShortLeverage": 20,
            "maxLongLeverage": 20,
            "pricePrecision": 4
        }
    )


def test_orchestrator_caps_batch_triage_to_max_4_candidates(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=5, direction_mode="SHORT")

    cands = [make_cand(f"COIN{i}", price_chg=float(10 + i)) for i in range(1, 8)]  # 7 candidates

    mocker.patch.object(orch.scanner, "scan_universe", return_value=cands)
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch(
        "orchestrator.build_candidate_features",
        return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2}
    )

    triage_mock = mocker.patch.object(
        orch.ai,
        "evaluate_batch_triage",
        return_value=BatchTriageResult(
            ranked_candidates=[],
            selected_finalists=[],
            is_valid=True,
            error_type=None,
            attempts=1,
            latency_ms=1200.0
        )
    )

    orch.run_cycle()

    assert triage_mock.called
    call_args = triage_mock.call_args[0]
    batch_summaries = call_args[0]

    # Must be capped strictly at 4 candidates
    assert len(batch_summaries) == 4


def test_orchestrator_batch_triage_balances_both_mode_directions(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=5, direction_mode="BOTH")

    # 3 long candidates and 3 short candidates
    cands = [
        make_cand("LONG1", price_chg=2.0),
        make_cand("LONG2", price_chg=3.0),
        make_cand("LONG3", price_chg=4.0),
        make_cand("SHORT1", price_chg=25.0),
        make_cand("SHORT2", price_chg=30.0),
        make_cand("SHORT3", price_chg=35.0),
    ]

    mocker.patch.object(orch.scanner, "scan_universe", return_value=cands)
    mocker.patch.object(orch.client, "get_klines", return_value=[])

    # Assign allowed directions: LONG1-3 get LONG, SHORT1-3 get SHORT
    def mock_evaluate_playbook(*args, **kwargs):
        sym = kwargs.get("symbol") or (args[0] if args else "")
        mock_p = MagicMock()
        mock_p.score = 80
        mock_p.direction = "LONG" if "LONG" in sym else "SHORT"
        mock_p.playbook = "OVERSOLD_REVERSAL" if "LONG" in sym else "PUMP_EXHAUSTION"
        mock_p.recommended_rr = 2.0
        mock_p.model_dump.return_value = {"score": 80, "playbook": mock_p.playbook}
        return mock_p

    mocker.patch("orchestrator.evaluate_playbooks", side_effect=mock_evaluate_playbook)
    mocker.patch(
        "orchestrator.build_candidate_features",
        return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2}
    )

    triage_mock = mocker.patch.object(
        orch.ai,
        "evaluate_batch_triage",
        return_value=BatchTriageResult(
            ranked_candidates=[],
            selected_finalists=[],
            is_valid=True
        )
    )

    orch.run_cycle()

    assert triage_mock.called
    batch_summaries = triage_mock.call_args[0][0]
    assert len(batch_summaries) == 4

    symbols = [s["symbol"] for s in batch_summaries]
    long_count = sum(1 for s in symbols if "LONG" in s)
    short_count = sum(1 for s in symbols if "SHORT" in s)

    # Balanced 2 LONG and 2 SHORT
    assert long_count == 2
    assert short_count == 2


def test_orchestrator_logs_enhanced_triage_telemetry(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=5, direction_mode="SHORT")

    cands = [make_cand("COIN1")]

    mocker.patch.object(orch.scanner, "scan_universe", return_value=cands)
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch(
        "orchestrator.build_candidate_features",
        return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2}
    )

    mocker.patch.object(
        orch.ai,
        "evaluate_batch_triage",
        return_value=BatchTriageResult(
            ranked_candidates=[],
            selected_finalists=[],
            is_valid=False,
            error_message="batch_triage_error: timed out",
            error_type="READ_TIMEOUT",
            attempts=1,
            latency_ms=60002.5
        )
    )

    audit_mock = mocker.patch("orchestrator.AuditLogger.log_event")

    orch.run_cycle()

    # Verify AI_BATCH_TRIAGE logged enhanced telemetry
    triage_log = next((call for call in audit_mock.call_args_list if call[0][0] == "AI_BATCH_TRIAGE"), None)
    assert triage_log is not None
    data = triage_log[0][1]
    assert data["error_type"] == "READ_TIMEOUT"
    assert data["attempts"] == 1
    assert data["latency_ms"] == 60002.5

    # Verify AI_BATCH_TRIAGE_FALLBACK also logged enhanced telemetry
    fallback_log = next((call for call in audit_mock.call_args_list if call[0][0] == "AI_BATCH_TRIAGE_FALLBACK"), None)
    assert fallback_log is not None
    fdata = fallback_log[0][1]
    assert fdata["error_type"] == "READ_TIMEOUT"
    assert fdata["attempts"] == 1
    assert fdata["latency_ms"] == 60002.5

