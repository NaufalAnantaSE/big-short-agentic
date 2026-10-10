"""
Review BUG3+6, N2, N3 and direction-aware gates integration tests.
Tests triage suggested_direction, deep evaluation direction preservation,
WAIT watchlist direction preservation, hard_gate per-direction evaluation,
veto of barred directions, and N3 watchlist clearance.
"""

import pytest
from unittest.mock import MagicMock
from config import AppConfig
from ai_evaluator import (
    AIEvaluator,
    BatchTriageResult,
    TriageCandidate,
    normalize_batch_triage_payload,
    build_batch_triage_prompt,
    build_structured_deep_prompt,
    AIEvaluationResult,
)
from orchestrator import SessionOrchestrator
from scanner import CandidatePair


def test_triage_candidate_has_suggested_direction_and_normalizes_properly():
    """TriageCandidate should have suggested_direction ('LONG', 'SHORT', 'UNKNOWN')."""
    cand = TriageCandidate(symbol="COIN1", rank=1, action="DEEP_ANALYZE", conviction_score=85, suggested_direction="LONG")
    assert cand.suggested_direction == "LONG"

    # Default should be UNKNOWN
    cand_default = TriageCandidate(symbol="COIN2", rank=2, action="WATCH", conviction_score=75)
    assert cand_default.suggested_direction == "UNKNOWN"

    raw_payload = {
        "ranked_candidates": [
            {"symbol": "COIN1", "rank": 1, "action": "DEEP_ANALYZE", "suggested_direction": "LONG", "conviction_score": 85},
            {"symbol": "COIN2", "rank": 2, "action": "WATCH", "suggested_direction": "short", "conviction_score": 75},
            {"symbol": "COIN3", "rank": 3, "action": "SKIP", "conviction_score": 30},
        ],
        "selected_finalists": ["COIN1"]
    }
    norm = normalize_batch_triage_payload(raw_payload)
    assert norm["ranked_candidates"][0]["suggested_direction"] == "LONG"
    assert norm["ranked_candidates"][1]["suggested_direction"] == "SHORT"
    assert norm["ranked_candidates"][2]["suggested_direction"] == "UNKNOWN"


def test_deep_prompt_both_neutral_never_enter_both():
    """When direction='BOTH', deep prompt must be neutral and NEVER produce ENTER_BOTH."""
    prompt = build_structured_deep_prompt({"symbol": "BTC-USDT", "price": 50000}, direction="BOTH")
    assert "ENTER_BOTH" not in prompt
    assert "ENTER_LONG" in prompt
    assert "ENTER_SHORT" in prompt


def test_batch_triage_prompt_includes_suggested_direction_schema():
    """Triage prompt schema must request suggested_direction."""
    prompt = build_batch_triage_prompt([{"symbol": "BTC-USDT", "current_price": 50000}], direction="BOTH")
    assert "suggested_direction" in prompt
    assert "LONG" in prompt
    assert "SHORT" in prompt


def test_evaluate_candidate_n2_supports_enter_long_schema_and_execution(mocker):
    """N2: evaluate_candidate schema includes ENTER_LONG and returns ENTER_LONG when confidence >= 70."""
    config = AppConfig(api_key="mock", secret_key="mock")
    ai = AIEvaluator(config)

    # Mock response with ENTER_LONG confidence 80
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": '{"symbol": "SOL-USDT", "decision": "ENTER_LONG", "confidence": 80, "setup_type": "OVERSOLD_BOUNCE", "key_evidence": "Reversal at key support", "risk_factors": "BTC dump", "invalidation_risk_present": false}'
            }
        }],
        "usage": {"total_tokens": 150}
    }
    mock_post = mocker.patch.object(ai.client, "post", return_value=mock_resp)

    res = ai.evaluate_candidate(
        symbol="SOL-USDT",
        price_change_24h=-8.5,
        current_price=130.0,
        klines_summary=[135, 133, 131, 130],
        spread_pct=0.1,
        direction="LONG"
    )

    # 1. Output decision must be ENTER_LONG, not downgraded or failed
    assert res.decision == "ENTER_LONG"
    assert res.confidence == 80
    assert res.is_valid is True

    # 2. Sent prompt must include ENTER_LONG in schema requirement
    sent_payload = mock_post.call_args[1]["json"]
    sent_prompt = sent_payload["messages"][1]["content"]
    assert '"decision": "ENTER_SHORT" | "ENTER_LONG" | "WAIT" | "SKIP"' in sent_prompt
    assert "ENTER_LONG" in sent_prompt


def test_stop_session_clears_watchlist_entries(mocker):
    """N3: stop_session must clear stale watchlist entries so they don't bleed into next session."""
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=3)

    # Add an entry to the watchlist
    orch.watchlist.add_candidate(
        symbol="STALE-COIN",
        current_price=10.0,
        conviction_score=80,
        direction="LONG",
        margin_per_pos=5.0,
        leverage=20,
    )
    assert len(orch.watchlist.get_all_entries()) == 1

    # Stop session
    orch.stop_session()

    # Watchlist entries must be completely cleared
    assert len(orch.watchlist.get_all_entries()) == 0
    assert orch.watchlist.get_entry("STALE-COIN") is None


def test_screening_evaluates_hard_gate_per_direction_and_rejects_if_neither(mocker):
    """
    Initial screening must evaluate hard_gate separately for each session-allowed direction.
    Keep allowed_directions per candidate, reject if neither direction passes.
    Put allowed_directions in summary sent to triage.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=3, direction_mode="BOTH")

    c_long = CandidatePair(
        symbol="LONG-COIN", last_price=10.0, price_change_percent=-15.0,
        volume_24h_usdt=500000.0, bid1=9.99, ask1=10.01, spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20, "maxLongLeverage": 20}
    )
    c_rej = CandidatePair(
        symbol="REJ-COIN", last_price=20.0, price_change_percent=5.0,
        volume_24h_usdt=500000.0, bid1=19.98, ask1=20.02, spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20, "maxLongLeverage": 20}
    )
    c_short = CandidatePair(
        symbol="SHORT-COIN", last_price=30.0, price_change_percent=25.0,
        volume_24h_usdt=500000.0, bid1=29.98, ask1=30.02, spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20, "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[c_long, c_rej, c_short])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.5})

    def fake_hard_gate(features, max_spread, direction="SHORT"):
        sym = features.get("symbol")
        # In actual run build_candidate_features returns features without symbol, but we can inspect or track by cand
        return (True, [])

    # Let's mock hard_gate based on direction and symbol via side_effect
    def side_effect_hard_gate(features, max_spread, direction="SHORT"):
        # We can distinguish which candidate by features or call count / inspect
        # To be clean, let's spy on arguments
        return (True, [])

    # Alternatively, let's pass a custom hard_gate mock
    mock_gate = MagicMock()
    def gate_logic(features, max_spread, direction="SHORT"):
        # Look at the price or features
        sym = features.get("_test_sym")
        if sym == "LONG-COIN":
            if direction == "LONG":
                return True, []
            return False, ["dump_already_extended"]
        elif sym == "REJ-COIN":
            return False, ["dump_already_extended" if direction == "SHORT" else "is_long_fomo_danger"]
        elif sym == "SHORT-COIN":
            if direction == "SHORT":
                return True, []
            return False, ["is_long_fomo_danger"]
        return False, ["unknown"]

    def fake_features(client, symbol, now_ms=None):
        return {"_test_sym": symbol, "fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.5}

    mocker.patch("orchestrator.build_candidate_features", side_effect=fake_features)
    mocker.patch("orchestrator.hard_gate", side_effect=gate_logic)

    mock_triage = mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[],
        selected_finalists=[],
        is_valid=True
    ))

    orch.run_cycle(dry_run=True)

    # Assert triage was called with candidates that passed
    assert mock_triage.called
    summaries = mock_triage.call_args[0][0]
    symbols_in_triage = [s["symbol"] for s in summaries]

    # REJ-COIN must be rejected from screening
    assert "REJ-COIN" not in symbols_in_triage
    assert "LONG-COIN" in symbols_in_triage
    assert "SHORT-COIN" in symbols_in_triage

    # Allowed directions must be present in the summary
    long_summary = next(s for s in summaries if s["symbol"] == "LONG-COIN")
    short_summary = next(s for s in summaries if s["symbol"] == "SHORT-COIN")
    assert long_summary["allowed_directions"] == ["LONG"]
    assert short_summary["allowed_directions"] == ["SHORT"]


def test_wait_preserves_long_direction_into_watchlist(mocker):
    """BUG 3 nuance: WAIT decision must NOT collapse pos_dir to SHORT; it must preserve candidate's direction (LONG)."""
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=3, direction_mode="BOTH")

    cand = CandidatePair(
        symbol="DIP-COIN", last_price=50.0, price_change_percent=-20.0,
        volume_24h_usdt=500000.0, bid1=49.95, ask1=50.05, spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20, "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 1.0})
    # Hard gate allows LONG
    mocker.patch("orchestrator.hard_gate", return_value=(True, []))

    # Triage suggests LONG and selects as finalist
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="DIP-COIN", rank=1, action="DEEP_ANALYZE", suggested_direction="LONG", conviction_score=85)],
        selected_finalists=["DIP-COIN"],
        is_valid=True
    ))

    # Deep evaluation returns WAIT with confidence 75 (>= 65 threshold for watchlist)
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="DIP-COIN",
        decision="WAIT",
        confidence=75,
        setup_type="SUPPORT_PULLBACK",
        key_evidence="Waiting for lower wick confirmation",
        is_valid=True
    ))

    orch.run_cycle(dry_run=True)

    # Watchlist entry must exist with direction LONG, NOT SHORT!
    entry = orch.watchlist.get_entry("DIP-COIN")
    assert entry is not None
    assert entry.direction == "LONG"


def test_tier1_watch_preserves_suggested_direction_in_both_mode(mocker):
    """Tier 1 WATCH in BOTH mode must use suggested_direction (LONG), not collapse to SHORT."""
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=3, direction_mode="BOTH")

    cand = CandidatePair(
        symbol="WATCH-LONG", last_price=10.0, price_change_percent=-10.0,
        volume_24h_usdt=500000.0, bid1=9.99, ask1=10.01, spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20, "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2})
    mocker.patch("orchestrator.hard_gate", return_value=(True, []))

    # Triage returns WATCH with suggested_direction="LONG", conviction=80
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="WATCH-LONG", rank=1, action="WATCH", suggested_direction="LONG", conviction_score=80)],
        selected_finalists=[],
        is_valid=True
    ))

    orch.run_cycle(dry_run=True)

    entry = orch.watchlist.get_entry("WATCH-LONG")
    assert entry is not None
    assert entry.direction == "LONG"


def test_veto_model_choosing_barred_direction(mocker):
    """Model choosing a barred direction (e.g. ENTER_LONG in a SHORT session or barred candidate) must be vetoed."""
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    # Session is SHORT only
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1, direction_mode="SHORT")

    cand = CandidatePair(
        symbol="ROGUE-COIN", last_price=10.0, price_change_percent=10.0,
        volume_24h_usdt=500000.0, bid1=9.99, ask1=10.01, spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2})
    mocker.patch("orchestrator.hard_gate", return_value=(True, []))

    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="ROGUE-COIN", rank=1, action="DEEP_ANALYZE", conviction_score=85)],
        selected_finalists=["ROGUE-COIN"],
        is_valid=True
    ))

    # Model rogue decision: returns ENTER_LONG in a SHORT session
    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="ROGUE-COIN",
        decision="ENTER_LONG",
        confidence=90,
        setup_type="NONE",
        is_valid=True
    ))

    mock_order = mocker.patch.object(orch.client, "place_order")

    res = orch.run_cycle(dry_run=False)

    # Order must NOT be placed!
    mock_order.assert_not_called()
    eval_rep = res["evaluations"][0]
    assert eval_rep["executed"] is False
    assert "veto" in str(eval_rep.get("veto_reason", "")).lower() or not eval_rep["executed"]


def test_invalid_direction_fails_closed(mocker):
    """When direction cannot be resolved (UNKNOWN) and is ambiguous, system must fail closed."""
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=1, direction_mode="BOTH")

    cand = CandidatePair(
        symbol="AMBIGUOUS-COIN", last_price=10.0, price_change_percent=0.0,
        volume_24h_usdt=500000.0, bid1=9.99, ask1=10.01, spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20, "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 0.2})
    # Both directions pass hard gate
    mocker.patch("orchestrator.hard_gate", return_value=(True, []))

    # Triage returns WATCH but suggested_direction is UNKNOWN
    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="AMBIGUOUS-COIN", rank=1, action="WATCH", suggested_direction="UNKNOWN", conviction_score=80)],
        selected_finalists=[],
        is_valid=True
    ))

    res = orch.run_cycle(dry_run=True)

    # Must NOT be added to watchlist because direction is unknown and ambiguous
    assert orch.watchlist.get_entry("AMBIGUOUS-COIN") is None


def test_both_mode_dip_to_long_buy_order_tp_sl(mocker):
    """
    End-to-end verification:
    Session in BOTH mode, candidate dips deeply:
    - hard_gate passes for LONG, rejected for SHORT (dump_already_extended)
    - triage suggests LONG
    - deep eval confirms ENTER_LONG (confidence 85)
    - executes BUY order with position_side='LONG', TP > entry price, SL < entry price
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=10.0, leverage=10, quota=1, direction_mode="BOTH")

    cand = CandidatePair(
        symbol="DIP-BUY", last_price=100.0, price_change_percent=-25.0,
        volume_24h_usdt=1000000.0, bid1=99.9, ask1=100.1, spread_percent=0.1,
        contract_info={"quantityPrecision": 2, "pricePrecision": 2, "tradeMinQuantity": "0.1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20, "maxLongLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.001, "atr_to_friction": 8.0, "atr": 2.0})

    def fake_gate(features, max_spread, direction="SHORT"):
        if direction == "LONG":
            return True, []
        return False, ["dump_already_extended"]

    mocker.patch("orchestrator.hard_gate", side_effect=fake_gate)

    mocker.patch.object(orch.ai, "evaluate_batch_triage", return_value=BatchTriageResult(
        ranked_candidates=[TriageCandidate(symbol="DIP-BUY", rank=1, action="DEEP_ANALYZE", suggested_direction="LONG", conviction_score=85)],
        selected_finalists=["DIP-BUY"],
        is_valid=True
    ))

    mocker.patch.object(orch.ai, "evaluate_deep_candidate", return_value=AIEvaluationResult(
        symbol="DIP-BUY",
        decision="ENTER_LONG",
        confidence=85,
        setup_type="SUPPORT_PULLBACK",
        key_evidence="Oversold bounce on heavy volume",
        is_valid=True
    ))

    mock_set_lev = mocker.patch.object(orch.client, "set_leverage", return_value={"leverage": 10})
    mock_place_order = mocker.patch.object(orch.client, "place_order", return_value={"orderId": "order_long_999"})

    res = orch.run_cycle(dry_run=False)

    # 1. Leverage must be set for LONG side
    mock_set_lev.assert_called_once_with(symbol="DIP-BUY", leverage=10, side="LONG")

    # 2. Place order must be BUY, position_side LONG
    mock_place_order.assert_called_once()
    order_kwargs = mock_place_order.call_args[1]
    assert order_kwargs["side"] == "BUY"
    assert order_kwargs["position_side"] == "LONG"

    # 3. TP must be ABOVE entry price (100.0) and SL must be BELOW entry price (100.0)
    tp = order_kwargs["take_profit_price"]
    sl = order_kwargs["stop_loss_price"]
    assert tp is not None and tp > 100.0, f"Expected TP > 100.0, got {tp}"
    assert sl is not None and sl < 100.0, f"Expected SL < 100.0, got {sl}"

    # 4. Session status filled
    assert orch.current_session is not None
    assert orch.current_session.filled_count == 1
    assert "DIP-BUY" in orch.current_session.executed_symbols




