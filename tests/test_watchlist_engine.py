"""
Comprehensive unit tests for Active Watchlist Engine, Deterministic Reversal Confirmations,
Pessimistic Quota Reservation, and Resting Order Lifecycle.
"""

import time
import pytest
from watchlist_manager import WatchlistManager, WatchlistEntry, ReversalTriggerResult
from client import BingXClient
from config import AppConfig
from orchestrator import SessionOrchestrator
from scanner import CandidatePair
from ai_evaluator import AIEvaluationResult


def test_watchlist_capacity_and_lowest_score_eviction(mocker):
    wm = WatchlistManager(max_size=4)

    # Add 4 initial candidates
    assert wm.add_candidate("COIN1", 1.0, conviction_score=80)[0] is True
    assert wm.add_candidate("COIN2", 1.0, conviction_score=70)[0] is True
    assert wm.add_candidate("COIN3", 1.0, conviction_score=90)[0] is True
    assert wm.add_candidate("COIN4", 1.0, conviction_score=75)[0] is True

    assert len(wm.entries) == 4

    # Adding a 5th candidate with conviction_score 65 (lower than COIN2's 70) should be REJECTED
    added, reason = wm.add_candidate("COIN5", 1.0, conviction_score=65)
    assert added is False
    assert reason is not None and "WATCHLIST_FULL_LOWER_CONVICTION" in reason
    assert len(wm.entries) == 4
    assert "COIN2" in wm.entries

    # Adding a 6th candidate with conviction_score 85 should EVICT COIN2 (lowest score = 70)
    added, reason = wm.add_candidate("COIN6", 1.0, conviction_score=85)
    assert added is True
    assert len(wm.entries) == 4
    assert "COIN2" not in wm.entries
    assert "COIN6" in wm.entries


def test_pola_1_upper_wick_rejection_valid():
    wm = WatchlistManager()
    entry = WatchlistEntry(
        symbol="TEST-USDT",
        initial_price=10.0,
        swing_high=10.08,
        conviction_score=85,
        atr=0.1
    )

    # 15m candle: open=9.98, high=10.08, low=9.95, close=9.97 (bearish pullback)
    # upper_wick = 10.08 - 9.98 = 0.10
    # body = 0.01
    # upper_wick / body = 10.0 >= 1.8
    # total_range = 10.08 - 9.95 = 0.13
    # wick / range = 0.10 / 0.13 = 76.9% >= 40%
    # abs_wick = 0.10 >= 0.003 * 10.08 (0.03024) AND >= 0.5 * ATR (0.05)
    # retracement from swing low (9.00) to swing high (10.08) = (10.08 - 9.97) / 1.08 = 0.102 <= 0.382
    klines = [
        {"open": 9.00, "high": 9.20, "low": 9.00, "close": 9.15, "volume": 1000},
        {"open": 9.15, "high": 9.90, "low": 9.10, "close": 9.80, "volume": 1200},
        {"open": 9.98, "high": 10.08, "low": 9.95, "close": 9.97, "volume": 1500}
    ]

    should_evict, evict_reason, trigger = wm.check_deterministic_reversal(
        entry=entry,
        klines_15m=klines,
        current_price=9.97,
        current_spread_pct=0.15
    )

    assert should_evict is False
    assert evict_reason is None
    assert trigger.triggered is True
    assert trigger.pattern == "UPPER_WICK_REJECTION"


def test_pola_1_doji_noise_rejection():
    """Koreksi 1: Doji candle with body near 0 but tiny wick < 0.3% price must NOT trigger."""
    wm = WatchlistManager()
    entry = WatchlistEntry(
        symbol="TEST-USDT",
        initial_price=10.0,
        swing_high=10.0,
        conviction_score=85,
        atr=0.1
    )

    # Candle with tiny noise: open=10.000, high=10.005, low=9.998, close=10.000
    # upper_wick = 0.005 (0.05% of price, far below 0.3% and below 0.5*ATR)
    klines = [
        {"open": 9.90, "high": 9.95, "low": 9.88, "close": 9.92, "volume": 1000},
        {"open": 9.92, "high": 9.99, "low": 9.90, "close": 9.98, "volume": 1200},
        {"open": 10.000, "high": 10.005, "low": 9.998, "close": 10.000, "volume": 500}
    ]

    should_evict, evict_reason, trigger = wm.check_deterministic_reversal(
        entry=entry,
        klines_15m=klines,
        current_price=10.0,
        current_spread_pct=0.10
    )

    assert trigger.triggered is False


def test_pola_2_micro_breakdown_valid():
    """Koreksi 2, 3 & 4: 15m Micro breakdown with volume >= 1.3x SMA10 and Fib safe."""
    wm = WatchlistManager()
    entry = WatchlistEntry(
        symbol="TEST-USDT",
        initial_price=10.0,
        swing_high=10.30,
        conviction_score=80,
        atr=0.15
    )

    # 10 candles with swing low at 9.00 and high at 10.30
    klines = [
        {"open": 9.00, "high": 9.20, "low": 9.00, "close": 9.15, "volume": 1000}
    ]
    klines.extend([
        {"open": 10.1, "high": 10.2, "low": 10.05, "close": 10.15, "volume": 1000}
        for _ in range(7)
    ])
    # Candle t-2: low=10.10
    klines.append({"open": 10.15, "high": 10.30, "low": 10.10, "close": 10.25, "volume": 1000})
    # Candle t-1: low=10.12
    klines.append({"open": 10.25, "high": 10.28, "low": 10.12, "close": 10.18, "volume": 1000})
    # Latest candle: close=10.08 < min(10.10, 10.12), volume=1500 (1.5x SMA10 >= 1.3x)
    # win_high = 10.30, win_low = 9.00 -> swing_span = 1.30
    # retracement = (10.30 - 10.08) / 1.30 = 0.22 / 1.30 = 0.169 <= 0.382 (Fib safe!)
    klines.append({"open": 10.18, "high": 10.20, "low": 10.05, "close": 10.08, "volume": 1500})

    should_evict, evict_reason, trigger = wm.check_deterministic_reversal(
        entry=entry,
        klines_15m=klines,
        current_price=10.08,
        current_spread_pct=0.12
    )

    assert should_evict is False
    assert trigger.triggered is True
    assert trigger.pattern == "MICRO_BREAKDOWN"


def test_pola_2_low_volume_rejected():
    """Koreksi 3: Micro breakdown with volume < 1.3x SMA10 must NOT trigger."""
    wm = WatchlistManager()
    entry = WatchlistEntry(
        symbol="TEST-USDT",
        initial_price=9.50,
        swing_high=10.30,
        conviction_score=80,
        atr=0.15
    )

    klines = [
        {"open": 10.1, "high": 10.2, "low": 10.05, "close": 10.15, "volume": 1000}
        for _ in range(8)
    ]
    klines.append({"open": 10.15, "high": 10.30, "low": 10.10, "close": 10.25, "volume": 1000})
    klines.append({"open": 10.25, "high": 10.28, "low": 10.12, "close": 10.18, "volume": 1000})
    # Volume is only 1100 (1.1x, below 1.3x)
    klines.append({"open": 10.18, "high": 10.20, "low": 10.05, "close": 10.08, "volume": 1100})

    should_evict, evict_reason, trigger = wm.check_deterministic_reversal(
        entry=entry,
        klines_15m=klines,
        current_price=10.08,
        current_spread_pct=0.12
    )

    assert trigger.triggered is False


def test_fast_evictions():
    wm = WatchlistManager()

    # 1. Breakout Invalidation: Close candle 15m > swing_high * 1.02
    entry1 = WatchlistEntry(symbol="SYM1", initial_price=10.0, swing_high=10.0, conviction_score=80)
    klines_breakout = [
        {"open": 10.0, "high": 10.25, "low": 9.95, "close": 10.23, "volume": 1000}
        for _ in range(3)
    ]
    should_evict, reason, _ = wm.check_deterministic_reversal(entry1, klines_breakout, 10.23, 0.1)
    assert should_evict is True
    assert reason == "BREAKOUT_INVALIDATION"

    # 2. Dump Missed: Price > 5% below swing high
    entry2 = WatchlistEntry(symbol="SYM2", initial_price=10.0, swing_high=10.0, conviction_score=80)
    klines_dump = [
        {"open": 9.9, "high": 9.9, "low": 9.4, "close": 9.45, "volume": 1000}
        for _ in range(3)
    ]
    should_evict, reason, _ = wm.check_deterministic_reversal(entry2, klines_dump, 9.45, 0.1)
    assert should_evict is True
    assert reason == "DUMP_MISSED"

    # 3. Spread Blowout: > 0.40%
    entry3 = WatchlistEntry(symbol="SYM3", initial_price=10.0, swing_high=10.0, conviction_score=80)
    should_evict, reason, _ = wm.check_deterministic_reversal(entry3, klines_dump, 10.0, 0.45)
    assert should_evict is True
    assert reason == "SPREAD_BLOWOUT"

    # 4. TTL Expired: > 30 minutes
    entry4 = WatchlistEntry(symbol="SYM4", initial_price=10.0, swing_high=10.0, conviction_score=80, entered_at=time.time() - 1900)
    should_evict, reason, _ = wm.check_deterministic_reversal(entry4, klines_dump, 10.0, 0.1)
    assert should_evict is True
    assert reason == "TTL_EXPIRED"


def test_immediate_cancel_resting_order_on_eviction(mocker):
    wm = WatchlistManager()
    config = AppConfig(api_key="mock", secret_key="mock")
    client = BingXClient(config)
    mock_cancel = mocker.patch.object(client, "cancel_order", return_value={"status": "CANCELED"})

    wm.add_candidate("RESTING-COIN", 1.0, conviction_score=80)
    entry = wm.get_entry("RESTING-COIN")
    assert entry is not None
    entry.resting_order_id = "12345"
    entry.resting_client_order_id = "bx_limit_test"
    entry.resting_order_price = 1.05

    # Evicting entry must cancel the resting order immediately
    wm.evict_entry("RESTING-COIN", reason="BREAKOUT_INVALIDATION", client=client)

    mock_cancel.assert_called_once_with(symbol="RESTING-COIN", order_id="12345", client_order_id="bx_limit_test")
    assert "RESTING-COIN" not in wm.entries


def test_pessimistic_quota_reservation_in_orchestrator(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)

    # 1 occupied position
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value={"OCCUPIED1-USDT"})

    # 1 resting order in watchlist
    orch.watchlist.add_candidate("WATCH1-USDT", 1.0, conviction_score=80)
    entry = orch.watchlist.get_entry("WATCH1-USDT")
    assert entry is not None
    entry.resting_order_id = "999"
    entry.resting_client_order_id = "bx_short_test"

    # Total used slots = 1 (occupied) + 1 (resting) = 2 == quota (2)
    # Available slots = 0 -> Quota exhausted!
    mock_cancel_resting = mocker.patch.object(orch.watchlist, "cancel_entry_resting_order")
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[])

    res = orch.run_cycle(dry_run=True)
    assert res.get("status") in ("QUOTA_EXHAUSTED", "WATCHLIST_ACTIVE")
