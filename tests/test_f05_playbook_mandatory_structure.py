"""
F-05 acceptance tests: mandatory structural conditions for each core playbook.

Defects being closed:
- PUMP_EXHAUSTION could satisfy its core gate from a Fibonacci peak zone alone. A zone is
  a location, not proof that buyers were physically rejected.
- SUPPORT_PULLBACK required a support zone, but macro uptrend and rebound confirmation
  were only bonus points.
- BREAKDOWN_RETEST accepted a retracement/flag as a breakdown, and the failed retest was
  only a bonus.

Each test asserts that a setup missing the structural core is rejected, and that a setup
carrying the full structure is still accepted.
"""
from strategy_playbook import evaluate_playbooks


def _features(**over):
    base = {
        "fibonacci": {},
        "impulse_wave": {},
        "rsi": {},
        "bollinger": {},
        "ema_trend": {},
        "timeframes": {},
        "funding_rate": 0.0,
        "funding_sentiment": "NEUTRAL",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# PUMP_EXHAUSTION
# ---------------------------------------------------------------------------

def test_pump_exhaustion_rejected_on_fibonacci_zone_alone():
    """A peak zone with no rejection price action must not open a short."""
    mf = _features(
        fibonacci={"zone": "PEAK_EXHAUSTION", "is_peak_exhaustion": True},
        rsi={"rsi_15m": 60.0},
    )
    res = evaluate_playbooks("X-USDT", 10.0, 3.0, 0.05, mf)
    assert res.playbook != "PUMP_EXHAUSTION"


def test_pump_exhaustion_rejected_without_exhaustion_context():
    """Rejection alone, with no exhaustion context, is not a pump-exhaustion short."""
    mf = _features(
        impulse_wave={"wick_15m": 0.30},
        rsi={"rsi_15m": 55.0},
        fibonacci={},
    )
    res = evaluate_playbooks("X-USDT", 10.0, 3.0, 0.05, mf)
    assert res.playbook != "PUMP_EXHAUSTION"


def test_pump_exhaustion_accepted_with_rejection_and_context():
    """Physical rejection plus exhaustion context must still produce the short."""
    mf = _features(
        fibonacci={"zone": "PEAK_EXHAUSTION", "is_peak_exhaustion": True},
        impulse_wave={"wick_15m": 0.30},
        rsi={"rsi_15m": 74.0, "is_overbought": True},
        bollinger={"is_overextended_upper": True, "percent_b": 0.99},
    )
    res = evaluate_playbooks("X-USDT", 10.0, 12.0, 0.05, mf)
    assert res.playbook == "PUMP_EXHAUSTION"
    assert res.direction == "SHORT"


# ---------------------------------------------------------------------------
# SUPPORT_PULLBACK
# ---------------------------------------------------------------------------

def test_support_pullback_rejected_without_macro_uptrend():
    mf = _features(
        fibonacci={"is_golden_pullback": True, "zone": "GOLDEN_POCKET"},
        ema_trend={"trend": "NEUTRAL"},
        rsi={"rsi_15m": 40.0},
    )
    res = evaluate_playbooks("X-USDT", 10.0, 5.0, 0.05, mf)
    assert res.playbook != "SUPPORT_PULLBACK"


def test_support_pullback_rejected_without_rebound_confirmation():
    mf = _features(
        fibonacci={"is_golden_pullback": True, "zone": "GOLDEN_POCKET"},
        ema_trend={"trend": "STRONG_UPTREND"},
        rsi={"rsi_15m": 40.0},
        timeframes={"15m": {"last_direction": "DOWN"}},
    )
    res = evaluate_playbooks("X-USDT", 10.0, 5.0, 0.05, mf)
    assert res.playbook != "SUPPORT_PULLBACK"


def test_support_pullback_accepted_with_full_structure():
    mf = _features(
        fibonacci={"is_golden_pullback": True, "zone": "GOLDEN_POCKET"},
        ema_trend={"trend": "STRONG_UPTREND"},
        rsi={"rsi_15m": 40.0},
        timeframes={"15m": {"last_direction": "UP"}},
    )
    res = evaluate_playbooks("X-USDT", 10.0, 5.0, 0.05, mf)
    assert res.playbook == "SUPPORT_PULLBACK"
    assert res.direction == "LONG"


# ---------------------------------------------------------------------------
# BREAKDOWN_RETEST
# ---------------------------------------------------------------------------

def test_breakdown_retest_rejected_without_retest_rejection():
    """A deep retracement is not a breakdown-retest without a rejected retest."""
    mf = _features(
        fibonacci={"retracement_ratio": 0.80},
        ema_trend={"trend": "STRONG_DOWNTREND"},
        rsi={"rsi_15m": 40.0},
    )
    res = evaluate_playbooks("X-USDT", 10.0, -5.0, 0.05, mf)
    assert res.playbook != "BREAKDOWN_RETEST"


def test_breakdown_retest_accepted_with_rejection():
    mf = _features(
        fibonacci={"retracement_ratio": 0.80},
        ema_trend={"trend": "STRONG_DOWNTREND"},
        impulse_wave={"wick_15m": 0.25},
        rsi={"rsi_15m": 40.0},
    )
    res = evaluate_playbooks("X-USDT", 10.0, -5.0, 0.05, mf)
    assert res.playbook == "BREAKDOWN_RETEST"
    assert res.direction == "SHORT"
