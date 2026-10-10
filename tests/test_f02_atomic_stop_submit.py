"""
F-02 acceptance tests: Atomic stop/submit and critical section synchronization.

Defects identified in audit (F-02):
1. Lock was only acquired in stop_session, but token check and order submission ran
   outside any shared critical section.
2. There is a set_leverage call between the check and place_order. If stop_session is
   invoked after the initial check or during set_leverage, place_order would still execute.
3. Both direct candidate evaluation and watchlist reversal triggers suffered from this race.

These tests prove that:
- If stop_session occurs during set_leverage, place_order is NOT called.
- If stop_session occurs concurrently via thread race after initial pre-checks,
  atomic serialization guarantees place_order is NOT called on a terminated session.
- Watchlist execution path also enforces atomic stop protection.
"""
import threading
import time
import pytest

from config import AppConfig
from orchestrator import SessionOrchestrator
from scanner import CandidatePair
from contracts import DirectionMode


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


def _build_test_sc(symbol="PEPE-USDT", last_price=10.0):
    cand = CandidatePair(
        symbol=symbol,
        last_price=last_price,
        bid1=last_price * 0.999,
        ask1=last_price * 1.001,
        volume_24h_usdt=1000000.0,
        price_change_percent=15.0,
        spread_percent=0.10,
        contract_info={"minQty": 1.0, "stepSize": 1.0, "tickSize": 0.01, "maxShortLeverage": 20, "maxLongLeverage": 20}
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


def test_direct_stop_session_during_set_leverage_blocks_place_order(mocker):
    """
    If stop_session() occurs during the set_leverage call, place_order MUST NOT be called.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_sc("PEPE-USDT", 10.0)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))

    mock_place_order = mocker.patch.object(orch.client, "place_order", return_value={"orderId": "123", "status": "FILLED", "avgPrice": 10.0})

    # Simulate user stopping session during set_leverage HTTP call
    def fake_set_leverage(*args, **kwargs):
        orch.stop_session()

    mocker.patch.object(orch.client, "set_leverage", side_effect=fake_set_leverage)
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": 1700000000000
    })

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False
    )

    # CRITICAL: place_order MUST NOT be called because session was stopped during leverage call
    mock_place_order.assert_not_called()
    assert placed is False
    assert rep.get("executed") is False


def test_thread_race_stop_session_concurrent_barrier(mocker):
    """
    Simulates real multi-threaded race:
    Thread A is in _evaluate_and_execute_candidate right before submission.
    Thread B calls stop_session().
    A synchronization barrier ensures Thread B stops the session while Thread A is suspended.
    When Thread A resumes, atomic synchronization must prevent place_order.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_sc("RACE-USDT", 5.0)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))

    mock_place_order = mocker.patch.object(orch.client, "place_order", return_value={"orderId": "123", "status": "FILLED", "avgPrice": 10.0})
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["4.995", "100"]],
        "asks": [["5.005", "100"]],
        "T": 1700000000000
    })

    barrier = threading.Barrier(2)

    def hooked_set_leverage(*args, **kwargs):
        # Wait for the stop thread to synchronize at this exact point
        barrier.wait(timeout=2.0)
        # Sleep slightly so stop thread acquires lock and terminates session first
        time.sleep(0.05)

    mocker.patch.object(orch.client, "set_leverage", side_effect=hooked_set_leverage)

    worker_res = {}

    def run_worker():
        rep, tokens, placed = orch._evaluate_and_execute_candidate(
            sc=sc,
            deep_mode=False,
            effective_dry_run=False,
            is_local_paper=False
        )
        worker_res["placed"] = placed
        worker_res["rep"] = rep

    t_worker = threading.Thread(target=run_worker)
    t_worker.start()

    # Wait at barrier until worker reaches set_leverage
    barrier.wait(timeout=2.0)
    # Stop session while worker is at leverage call
    orch.stop_session()

    t_worker.join(timeout=3.0)

    # Order must NOT have been placed
    mock_place_order.assert_not_called()
    assert worker_res.get("placed") is False


def test_watchlist_stop_session_during_set_leverage_blocks_place_order(mocker):
    """
    Watchlist trigger execution path:
    If stop_session() occurs during set_leverage, place_order must NOT be called.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    # Add candidate to watchlist with valid sizing params
    orch.watchlist.add_candidate(
        symbol="WL-COIN",
        current_price=10.0,
        conviction_score=85,
        playbook="PUMP_EXHAUSTION",
        direction="SHORT",
        client=orch.client,
        session_id=session.session_id,
        atr=0.1,
        target_rr=2.0
    )
    mocker.patch.object(orch.client, "get_contracts", return_value=[{
        "symbol": "WL-COIN", "quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20
    }])

    # Mock watchlist reversal trigger
    from watchlist_manager import ReversalTriggerResult
    mocker.patch.object(orch.watchlist, "check_deterministic_reversal", return_value=(
        False, None, ReversalTriggerResult(triggered=True, pattern="BEARISH_ENGULFING", evidence="Engulfing bar closed")
    ))
    fake_klines = [
        {"openTime": 1700000000000 + i * 900000, "open": "10.0", "high": "10.5", "low": "9.5", "close": "10.0", "volume": "100"}
        for i in range(60)
    ]
    mocker.patch.object(orch.client, "get_klines", return_value=fake_klines)
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": 1700000000000
    })
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())

    mock_place_order = mocker.patch.object(orch.client, "place_order", return_value={"orderId": "123", "status": "FILLED", "avgPrice": 10.0})

    def fake_wl_set_leverage(*args, **kwargs):
        orch.stop_session()

    mocker.patch.object(orch.client, "set_leverage", side_effect=fake_wl_set_leverage)

    # Empty general scan
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[])

    cycle_res = orch.run_cycle(dry_run=False)
    print("CYCLE RES:", cycle_res)
    # place_order MUST NOT be called!
    mock_place_order.assert_not_called()

