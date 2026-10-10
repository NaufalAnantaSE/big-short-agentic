import pytest
from orchestrator import SessionOrchestrator
from config import AppConfig
from scanner import CandidatePair
from audit_logger import AuditLogger


class DummyAIResponse:
    def __init__(self, decision="ENTER_SHORT"):
        self.decision = decision
        self.confidence = 85.0
        self.key_evidence = ["Extreme pump exhaustion"]
        self.risk_factors = ["Volatility"]
        self.usage = {"total_tokens": 150}
        self.latency_ms = 450.0


def test_session_stop_mid_ai_evaluation_blocks_place_order(mocker):
    """
    P0-4 Reproduction test:
    When stop_session() is called mid-evaluation (e.g. user stops bot while AI is thinking),
    the post-evaluation order submission MUST be blocked (place_order must NOT be called).
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE"

    cand = CandidatePair(
        symbol="PEPE-USDT",
        last_price=10.0,
        bid1=9.995,
        ask1=10.005,
        volume_24h_usdt=1000000.0,
        price_change_percent=15.0,
        spread_percent=0.10,
        contract_info={"minQty": 1.0, "stepSize": 1.0, "tickSize": 0.01}
    )

    sc = {
        "cand": cand,
        "closes": [9.0, 9.5, 10.0],
        "market_features": {
            "atr_14": 0.5,
            "rsi_14": 75.0,
            "spread_pct": 0.10,
            "adx_14": 30.0,
            "volume_24h": 1000000.0,
            "klines_1m": [{"time": 1000, "close": 10.0}],
            "klines_15m": [{"time": 1000, "close": 10.0}],
            "klines_1h": [{"time": 1000, "close": 10.0}],
        },
        "playbook_match": None,
        "atr_val": 0.5,
        "allowed_directions": ["SHORT"],
        "suggested_direction": "SHORT"
    }

    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))

    # Simulate session stop while AI is running
    def fake_ai_eval(*args, **kwargs):
        orch.stop_session()  # Sets status = TERMINATED
        return DummyAIResponse(decision="ENTER_SHORT")

    mocker.patch.object(orch.ai, "evaluate_candidate", side_effect=fake_ai_eval)
    mock_place_order = mocker.patch.object(orch.client, "place_order")
    mock_set_leverage = mocker.patch.object(orch.client, "set_leverage")

    # Mock orderbook depth for quote revalidation
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.995", "100"]],
        "asks": [["10.005", "100"]],
        "T": 1700000000000
    })

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False
    )

    # place_order and set_leverage MUST NOT be called!
    mock_place_order.assert_not_called()
    mock_set_leverage.assert_not_called()
    assert placed is False
    assert rep.get("executed") is False
    assert "TERMINATED" in rep.get("veto_reason", "")


def test_generation_token_mismatch_blocks_stale_order(mocker):
    """
    If session A is stopped and session B is started while an evaluation was in flight,
    the evaluation belonging to generation A must NOT execute into session B.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session_a = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session_a.status = "ACTIVE"

    cand = CandidatePair(
        symbol="DOGE-USDT",
        last_price=0.20,
        bid1=0.1998,
        ask1=0.2002,
        volume_24h_usdt=5000000.0,
        price_change_percent=12.0,
        spread_percent=0.10,
        contract_info={"minQty": 1.0, "stepSize": 1.0, "tickSize": 0.001}
    )

    sc = {
        "cand": cand,
        "closes": [0.18, 0.19, 0.20],
        "market_features": {
            "atr_14": 0.01,
            "rsi_14": 78.0,
            "spread_pct": 0.10,
            "adx_14": 30.0,
            "volume_24h": 5000000.0,
            "klines_1m": [{"time": 1000, "close": 0.20}],
            "klines_15m": [{"time": 1000, "close": 0.20}],
            "klines_1h": [{"time": 1000, "close": 0.20}],
        },
        "playbook_match": None,
        "atr_val": 0.01,
        "allowed_directions": ["SHORT"],
        "suggested_direction": "SHORT"
    }

    # Simulate mid-eval session restart
    def fake_ai_eval(*args, **kwargs):
        orch.stop_session()
        orch.start_session(margin_per_pos=10.0, leverage=10, quota=1)  # New session B
        return DummyAIResponse(decision="ENTER_SHORT")

    mocker.patch.object(orch.ai, "evaluate_candidate", side_effect=fake_ai_eval)
    mock_place_order = mocker.patch.object(orch.client, "place_order")

    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["0.1998", "1000"]],
        "asks": [["0.2002", "1000"]],
        "T": 1700000000000
    })

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False
    )

    mock_place_order.assert_not_called()
    assert placed is False
    assert rep.get("executed") is False
