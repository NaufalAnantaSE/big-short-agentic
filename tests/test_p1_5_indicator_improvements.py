import pytest
from market_features import _calculate_true_range, _timeframe_features, _ema_trend_analysis


def test_true_range_formula_includes_prior_close():
    """
    P1-5 Acceptance Test:
    True Range must calculate max(H - L, |H - Cp|, |L - Cp|),
    properly accounting for gaps between bars rather than only H - L.
    """
    # Bar 0: C = 100.0
    # Bar 1: Gaps up to H = 110.0, L = 105.0, C = 108.0
    # Simple Range (H - L) = 5.0
    # True Range = max(110 - 105, |110 - 100|, |105 - 100|) = max(5.0, 10.0, 5.0) = 10.0
    tr = _calculate_true_range(
        high=110.0,
        low=105.0,
        prev_close=100.0
    )
    assert tr == 10.0

    # Bar with downward gap:
    # Bar 0: C = 100.0
    # Bar 1: Gaps down to H = 92.0, L = 88.0, C = 90.0
    # Simple Range = 4.0
    # True Range = max(92 - 88, |92 - 100|, |88 - 100|) = max(4.0, 8.0, 12.0) = 12.0
    tr_down = _calculate_true_range(
        high=92.0,
        low=88.0,
        prev_close=100.0
    )
    assert tr_down == 12.0


def test_atr_in_timeframe_features_uses_true_range():
    """
    Verifies that _timeframe_features computes ATR using True Range,
    reflecting price gaps across bars.
    """
    now_ms = 1_000_000
    rows = [
        {"time": 100_000, "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "volume": 100},
        # Gap up: High 15.0, Low 13.0, Close 14.0 -> simple range 2.0, but TR is |15.0 - 10.0| = 5.0
        {"time": 200_000, "open": 13.5, "high": 15.0, "low": 13.0, "close": 14.0, "volume": 150},
    ]

    feat = _timeframe_features(rows, now_ms=now_ms, min_history=2)
    assert feat["valid"] is True
    # The last candle's TR is 5.0. Average TR of the 2 bars: (1.0 + 5.0) / 2 = 3.0
    # (If it used simple range, it would be (1.0 + 2.0) / 2 = 1.5)
    assert feat["atr"] == pytest.approx(3.0, abs=1e-4)


def test_ema_trend_analysis_requires_sufficient_warmup():
    """
    P1-5 Acceptance Test:
    EMA50 requires sufficient candle history (>= 50 bars) for proper warmup.
    If fewer than 50 bars are provided, it must fail-closed (valid=False),
    rather than fabricating an EMA50 from 10 or 20 bars.
    """
    short_rows = [{"close": 10.0 + i * 0.1} for i in range(30)]
    res = _ema_trend_analysis(short_rows, min_bars=50)
    assert res["valid"] is False
    assert res["trend"] == "NEUTRAL"

    sufficient_rows = [{"close": 10.0 + i * 0.1} for i in range(60)]
    res_ok = _ema_trend_analysis(sufficient_rows, min_bars=50)
    assert res_ok["valid"] is True
    assert res_ok["trend"] == "STRONG_UPTREND"
