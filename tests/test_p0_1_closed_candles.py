import pytest
from market_features import _closed_rows, _timeframe_features, compute_market_features, INTERVAL_MS
from watchlist_manager import WatchlistManager, WatchlistEntry


def make_candle(open_time_ms: int, o: float = 10.0, h: float = 10.5, l: float = 9.8, c: float = 10.2, v: float = 1000.0, close_time_ms: int | None = None):
    row = {
        "time": open_time_ms,
        "open": str(o),
        "high": str(h),
        "low": str(l),
        "close": str(c),
        "volume": str(v),
    }
    if close_time_ms is not None:
        row["closeTime"] = close_time_ms
    return row


def test_candle_opened_one_second_ago_is_rejected_for_all_timeframes():
    now_ms = 1_700_000_000_000
    one_sec_old = now_ms - 1_000

    for tf in ("1m", "15m", "1h"):
        c = make_candle(open_time_ms=one_sec_old)
        result = _closed_rows([c], now_ms=now_ms, interval=tf)
        assert len(result) == 0, f"Candle opened 1s ago must be rejected for timeframe {tf}, but was accepted"


def test_candle_midway_in_interval_is_rejected():
    now_ms = 1_700_000_000_000

    # 15m candle opened 5 minutes ago (300_000 ms ago)
    c_15m = make_candle(open_time_ms=now_ms - 300_000)
    assert len(_closed_rows([c_15m], now_ms=now_ms, interval="15m")) == 0

    # 1h candle opened 30 minutes ago (1_800_000 ms ago)
    c_1h = make_candle(open_time_ms=now_ms - 1_800_000)
    assert len(_closed_rows([c_1h], now_ms=now_ms, interval="1h")) == 0


def test_candle_closed_with_buffer_is_accepted_for_all_timeframes():
    now_ms = 1_700_000_000_000
    buffer_ms = 5_000

    for tf in ("1m", "15m", "1h"):
        interval_ms = INTERVAL_MS[tf]
        # Fully closed candle: opened at least (interval + buffer) ago
        open_time = now_ms - interval_ms - buffer_ms
        c = make_candle(open_time_ms=open_time)
        result = _closed_rows([c], now_ms=now_ms, interval=tf, buffer_ms=buffer_ms)
        assert len(result) == 1, f"Fully closed candle with buffer must be accepted for {tf}"
        assert result[0]["time"] == open_time


def test_candle_just_finished_without_buffer_is_rejected():
    now_ms = 1_700_000_000_000
    buffer_ms = 5_000
    # Candle finished exactly 0ms ago (within 5s buffer)
    open_time = now_ms - 900_000
    c = make_candle(open_time_ms=open_time)
    result = _closed_rows([c], now_ms=now_ms, interval="15m", buffer_ms=buffer_ms)
    assert len(result) == 0, "Candle within buffer window must not be considered closed yet"


def test_explicit_closetime_respected():
    now_ms = 1_700_000_000_000
    buffer_ms = 5_000

    # Valid closeTime older than buffer
    c_closed = make_candle(open_time_ms=now_ms - 100_000, close_time_ms=now_ms - 10_000)
    assert len(_closed_rows([c_closed], now_ms=now_ms, buffer_ms=buffer_ms)) == 1

    # closeTime inside buffer
    c_inside_buffer = make_candle(open_time_ms=now_ms - 100_000, close_time_ms=now_ms - 2_000)
    assert len(_closed_rows([c_inside_buffer], now_ms=now_ms, buffer_ms=buffer_ms)) == 0

    # closeTime in future
    c_future = make_candle(open_time_ms=now_ms - 100_000, close_time_ms=now_ms + 10_000)
    assert len(_closed_rows([c_future], now_ms=now_ms, buffer_ms=buffer_ms)) == 0


def test_compute_market_features_excludes_unclosed_forming_candle():
    now_ms = 1_700_000_000_000
    # 5 genuinely closed 15m candles
    c1 = make_candle(now_ms - 5 * 900_000 - 10_000, c=10.0)
    c2 = make_candle(now_ms - 4 * 900_000 - 10_000, c=10.1)
    c3 = make_candle(now_ms - 3 * 900_000 - 10_000, c=10.2)
    c4 = make_candle(now_ms - 2 * 900_000 - 10_000, c=10.3)
    c5 = make_candle(now_ms - 1 * 900_000 - 10_000, c=10.4)
    # 1 forming candle opened 5 seconds ago with an extreme fake wick/spike
    c_forming = make_candle(now_ms - 5_000, o=10.4, h=25.0, l=10.4, c=20.0, v=99999.0)

    candles_15m = [c1, c2, c3, c4, c5, c_forming]
    # 1h candles
    c_1h_1 = make_candle(now_ms - 4 * 3_600_000 - 10_000, c=10.0)
    c_1h_2 = make_candle(now_ms - 3 * 3_600_000 - 10_000, c=10.1)
    c_1h_3 = make_candle(now_ms - 2 * 3_600_000 - 10_000, c=10.2)
    c_1h_4 = make_candle(now_ms - 1 * 3_600_000 - 10_000, c=10.3)

    features = compute_market_features(
        candles_by_tf={"15m": candles_15m, "1h": [c_1h_1, c_1h_2, c_1h_3, c_1h_4]},
        funding={"lastFundingRate": "0.0001", "updateTime": now_ms - 1000},
        open_interest={"openInterest": "5000", "time": now_ms - 1000},
        depth={"bids": [["10.39", "100"]], "asks": [["10.41", "100"]], "T": now_ms - 1000},
        now_ms=now_ms,
    )

    # The forming candle must be excluded from closed candles
    assert features["timeframes"]["15m"]["candle_count"] == 5
    # The last_close must be c5 (10.4), NOT c_forming (20.0)
    assert features["timeframes"]["15m"]["last_close"] == 10.4
    # Intrabar forming candle should be tracked separately if present
    assert features["timeframes"]["15m"].get("intrabar_candle") is not None
    assert features["timeframes"]["15m"]["intrabar_candle"]["close"] == 20.0


def test_minimum_history_validation():
    now_ms = 1_700_000_000_000
    # Only 2 closed candles when minimum is 3
    c1 = make_candle(now_ms - 2 * 900_000 - 10_000)
    c2 = make_candle(now_ms - 1 * 900_000 - 10_000)
    tf_feat = _timeframe_features([c1, c2], now_ms=now_ms, interval="15m", min_history=3)
    assert tf_feat["valid"] is False
    assert tf_feat["candle_count"] == 2


def test_watchlist_does_not_evaluate_unclosed_15m_candle_as_reversal():
    wm = WatchlistManager()
    entry = WatchlistEntry(
        symbol="TEST-USDT",
        initial_price=10.0,
        swing_high=10.0,
        conviction_score=85,
        atr=0.1
    )

    now_ms = 1_700_000_000_000
    # 3 historical closed candles without reversal
    c1 = make_candle(now_ms - 3 * 900_000 - 10_000, o=9.8, h=9.9, l=9.7, c=9.85, v=1000)
    c2 = make_candle(now_ms - 2 * 900_000 - 10_000, o=9.85, h=9.95, l=9.8, c=9.9, v=1100)
    c3 = make_candle(now_ms - 1 * 900_000 - 10_000, o=9.9, h=9.98, l=9.88, c=9.95, v=1200)

    # 1 unclosed candle opened 10 seconds ago that happens to have a huge upper rejection wick
    c_unclosed = make_candle(now_ms - 10_000, o=9.98, h=10.08, l=9.95, c=9.97, v=1500)

    klines = [c1, c2, c3, c_unclosed]

    should_evict, evict_reason, trigger = wm.check_deterministic_reversal(
        entry=entry,
        klines_15m=klines,
        current_price=9.97,
        current_spread_pct=0.15,
        now_ms=now_ms
    )

    # Because c_unclosed is NOT closed yet, it must NOT trigger UPPER_WICK_REJECTION!
    assert trigger.triggered is False
