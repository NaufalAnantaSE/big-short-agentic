import pytest
from watchlist_manager import WatchlistManager, WatchlistEntry
from orchestrator import SessionOrchestrator
from config import AppConfig
from contracts import DirectionMode


def test_watchlist_reversal_rejected_when_spread_is_between_036_and_040():
    """
    P0-5 Test:
    Previously spread threshold in watchlist was 0.40%, so 0.38% passed.
    Now parity with scanner/gate enforces max 0.35%, so 0.38% MUST be rejected with SPREAD_BLOWOUT.
    """
    wm = WatchlistManager()
    entry = WatchlistEntry(
        symbol="PEPE-USDT",
        initial_price=10.0,
        swing_high=11.0,
        conviction_score=80.0,
        direction="SHORT"
    )
    klines_15m = [
        {"time": 1000, "open": 10.0, "high": 11.0, "low": 9.9, "close": 10.5},
        {"time": 2000, "open": 10.5, "high": 11.2, "low": 9.8, "close": 10.1}
    ]

    # Spread is 0.38% (between 0.35% and 0.40%)
    should_evict, evict_reason, trigger_res = wm.check_deterministic_reversal(
        entry=entry,
        klines_15m=klines_15m,
        current_price=10.1,
        current_spread_pct=0.38
    )

    assert should_evict is True
    assert evict_reason == "SPREAD_BLOWOUT"
    assert trigger_res.triggered is False


def test_watchlist_empty_depth_does_not_produce_zero_spread_and_skips_trigger(mocker):
    """
    P0-5 Test:
    When depth is empty, orchestrator MUST NOT fall back to initial_price resulting in 0.0% spread.
    It must fail closed and NOT execute any order.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    # Add an entry to watchlist
    orch.watchlist.add_candidate(
        symbol="DOGE-USDT",
        current_price=0.20,
        conviction_score=80.0,
        direction="SHORT",
        playbook="PUMP_EXHAUSTION"
    )

    # Mock client returns
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.client, "get_klines", return_value=[
        {"time": 1000, "open": 0.20, "high": 0.22, "low": 0.19, "close": 0.21},
        {"time": 2000, "open": 0.21, "high": 0.22, "low": 0.19, "close": 0.20}
    ])

    # Empty orderbook depth
    mocker.patch.object(orch.client, "get_depth", return_value={"bids": [], "asks": []})

    mock_place_order = mocker.patch.object(orch.client, "place_order")
    spy_reversal = mocker.spy(orch.watchlist, "check_deterministic_reversal")

    res = orch.run_cycle(dry_run=True)

    # Empty depth must not proceed with 0.0% spread
    mock_place_order.assert_not_called()
    # check_deterministic_reversal should not be called with 0.0% fabricated spread
    if spy_reversal.called:
        for call in spy_reversal.call_args_list:
            assert call.kwargs.get("current_spread_pct", 0.0) != 0.0 or not call.kwargs.get("current_price")


def test_watchlist_execution_preserves_playbook_and_target_rr(mocker):
    """
    P0-5 Test:
    Watchlist execution report and sizing must preserve entry playbook and target RR,
    not hardcoded None and 2.0.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE_SEARCHING"

    orch.watchlist.add_candidate(
        symbol="DOGE-USDT",
        current_price=0.20,
        conviction_score=85.0,
        direction="SHORT",
        playbook="PUMP_EXHAUSTION",
        target_rr=2.5,
        atr=0.002,
        leverage=10
    )

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.client, "get_klines", return_value=[
        {"time": 1000, "open": 0.20, "high": 0.22, "low": 0.19, "close": 0.21},
        {"time": 2000, "open": 0.21, "high": 0.22, "low": 0.19, "close": 0.20}
    ])
    # Spread: (0.2002 - 0.1998)/0.1998 = 0.20% <= 0.35%
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["0.1998", "1000000"]],
        "asks": [["0.2002", "1000000"]]
    })
    mocker.patch.object(orch.client, "get_contracts", return_value=[{
        "symbol": "DOGE-USDT",
        "tradeMinQuantity": "1",
        "tradeMinUSDT": "5.0",
        "quantityPrecision": 0,
        "pricePrecision": 4,
        "maxShortLeverage": 20
    }])

    from watchlist_manager import ReversalTriggerResult
    mocker.patch.object(
        orch.watchlist,
        "check_deterministic_reversal",
        return_value=(False, None, ReversalTriggerResult(
            triggered=True,
            pattern="UPPER_WICK_REJECTION",
            trigger_price=0.20,
            evidence="Rejection confirmed"
        ))
    )

    res = orch.run_cycle(dry_run=True)
    assert res.get("status") == "WATCHLIST_EXECUTED"
    assert "cycle_results" in res
    w_res = next((r for r in res["cycle_results"] if r.get("symbol") == "DOGE-USDT"), None)
    assert w_res is not None
    # Playbook and target_rr must be preserved from entry
    assert w_res["playbook"] == "PUMP_EXHAUSTION"
    assert w_res["sizing"]["risk_reward_ratio"] == 2.5
