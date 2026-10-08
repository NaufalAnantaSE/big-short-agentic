"""
Unit tests for Tier 1 Batch Triage Engine in AI Evaluator and Orchestrator.
Validates comparative ranking, candidate categorization (DEEP_ANALYZE, WATCH, SKIP),
auto-addition of high-conviction WATCH candidates directly to Active Watchlist,
adaptive finalists (cap 2), and quota exhaustion skipping.
"""

import pytest
from unittest.mock import MagicMock
from config import AppConfig
from ai_evaluator import (
    AIEvaluator,
    BatchTriageResult,
    TriageCandidate,
    normalize_batch_triage_payload,
    AIEvaluationResult
)
from orchestrator import SessionOrchestrator
from scanner import CandidatePair


def test_triage_normalization_aliases_and_cap():
    raw_payload = {
        "ranked_candidates": [
            {"symbol": "COIN1", "rank": 1, "action": "ENTER", "conviction_score": "85%", "triage_reason": "High pump"},
            {"symbol": "COIN2", "rank": 2, "action": "WAIT", "conviction_score": 75, "triage_reason": "Good resistance"},
            {"symbol": "COIN3", "rank": 3, "action": "DEEP_ANALYZE", "conviction_score": 70, "triage_reason": "Exhaustion"},
            {"symbol": "COIN4", "rank": 4, "action": "PASS", "conviction_score": 30, "triage_reason": "No edge"}
        ],
        "selected_finalists": ["COIN1", "COIN3", "COIN2"]  # 3 finalists returned by LLM
    }

    norm = normalize_batch_triage_payload(raw_payload)

    # 1. Action aliases mapped correctly
    assert norm["ranked_candidates"][0]["action"] == "DEEP_ANALYZE"
    assert norm["ranked_candidates"][0]["conviction_score"] == 85
    assert norm["ranked_candidates"][1]["action"] == "WATCH"
    assert norm["ranked_candidates"][3]["action"] == "SKIP"

    # 2. Selected finalists strictly capped at 2
    assert len(norm["selected_finalists"]) == 2
    assert norm["selected_finalists"] == ["COIN1", "COIN3"]


def test_triage_auto_add_watch_to_watchlist(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=3)

    c1 = CandidatePair(
        symbol="WATCH-ME",
        last_price=10.0,
        price_change_percent=15.0,
        volume_24h_usdt=500000.0,
        bid1=9.99,
        ask1=10.01,
        spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[c1])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2})

    # Triage returns WATCH with conviction 80 (>= 70)
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="WATCH-ME", rank=1, action="WATCH", conviction_score=80, triage_reason="Ascending into resistance")],
        selected_finalists=[],
        is_valid=True
    ))

    # Spy on deep evaluation (should NOT be called!)
    mock_deep = mocker.patch.object(orch.ai, "evaluate_adversarial")
    mock_single = mocker.patch.object(orch.ai, "evaluate_candidate")

    res = orch.run_cycle(dry_run=True)

    # Candidate should be directly placed into active watchlist
    entry = orch.watchlist.get_entry("WATCH-ME")
    assert entry is not None
    assert entry.conviction_score == 80
    assert entry.initial_price == 10.0

    # No Tier 2 calls made
    mock_deep.assert_not_called()
    mock_single.assert_not_called()


def test_triage_watch_low_conviction_rejected(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=3)

    c1 = CandidatePair(
        symbol="WEAK-WATCH",
        last_price=10.0,
        price_change_percent=15.0,
        volume_24h_usdt=500000.0,
        bid1=9.99,
        ask1=10.01,
        spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[c1])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2})

    # Triage returns WATCH with conviction 60 (< 70 threshold)
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="WEAK-WATCH", rank=1, action="WATCH", conviction_score=60, triage_reason="Mediocre")],
        selected_finalists=[],
        is_valid=True
    ))

    res = orch.run_cycle(dry_run=True)

    # Should NOT be added to watchlist
    assert orch.watchlist.get_entry("WEAK-WATCH") is None


def test_skip_second_finalist_when_quota_exhausted(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    # Quota is 1, so only 1 position can be filled
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1)

    c1 = CandidatePair(
        symbol="FINALIST-1",
        last_price=10.0,
        price_change_percent=15.0,
        volume_24h_usdt=500000.0,
        bid1=9.99,
        ask1=10.01,
        spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )
    c2 = CandidatePair(
        symbol="FINALIST-2",
        last_price=20.0,
        price_change_percent=12.0,
        volume_24h_usdt=500000.0,
        bid1=19.98,
        ask1=20.02,
        spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[c1, c2])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2})

    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[
            TriageCandidate(symbol="FINALIST-1", rank=1, action="DEEP_ANALYZE", conviction_score=90),
            TriageCandidate(symbol="FINALIST-2", rank=2, action="DEEP_ANALYZE", conviction_score=85)
        ],
        selected_finalists=["FINALIST-1", "FINALIST-2"],
        is_valid=True
    ))

    # Mock deep evaluation: FINALIST-1 returns ENTER_SHORT (uses the 1 available slot)
    mock_deep = mocker.patch.object(orch.ai, "evaluate_adversarial", side_effect=[
        AIEvaluationResult(symbol="FINALIST-1", decision="ENTER_SHORT", confidence=90, is_valid=True),
        AIEvaluationResult(symbol="FINALIST-2", decision="ENTER_SHORT", confidence=85, is_valid=True)
    ])

    res = orch.run_cycle(dry_run=True)

    # FINALIST-1 was evaluated and took the slot
    assert orch.current_session is not None
    assert orch.current_session.filled_count == 1
    assert "FINALIST-1" in orch.current_session.executed_symbols

    # FINALIST-2 should NOT have been evaluated (skipped because quota reached)
    assert mock_deep.call_count == 1
    assert "FINALIST-2" not in orch.current_session.executed_symbols
