import pytest
from strategy_playbook import evaluate_playbooks, PlaybookType


def test_pump_exhaustion_without_core_rejection_is_rejected_score_zero():
    """
    P1-2 Codex Reproduction:
    A setup has high 24h change (+15%), overbought RSI (72), and upper Bollinger Band breach,
    but NO core rejection pattern (no upper wick, no peak exhaustion, no bearish divergence).
    Additive scoring previously gave 55 points and triggered PUMP_EXHAUSTION.
    With mandatory conditions, this MUST be rejected (score 0 / PlaybookType.NONE).
    """
    market_features = {
        "fibonacci": {"is_peak_exhaustion": False, "zone": "MID_EXPANSION"},
        "impulse_wave": {"confluent_rejection": False, "wick_15m": 0.05, "volume_fade": True},
        "rsi": {"rsi_15m": 72.0, "is_overbought": True, "divergence": "NONE"},
        "bollinger": {"is_overextended_upper": True, "percent_b": 0.98},
        "ema_trend": {"trend": "MILD_UPTREND"}
    }

    match = evaluate_playbooks(
        symbol="MEME-USDT",
        price=10.0,
        change_24h=15.0,
        spread_pct=0.10,
        market_features=market_features
    )

    assert match.playbook == PlaybookType.NONE.value
    assert match.score == 0


def test_support_pullback_without_core_support_is_rejected_score_zero():
    """
    P1-2 Codex Reproduction:
    A setup is in a strong uptrend and RSI is in discount range (40),
    but there is NO actual support/pullback zone (no golden pocket, no support retest).
    Previously: additive score reached 50 points and triggered SUPPORT_PULLBACK.
    With mandatory conditions, this MUST be rejected (score 0 / PlaybookType.NONE).
    """
    market_features = {
        "fibonacci": {
            "is_golden_pullback": False,
            "zone": "FREE_FALL",
            "is_dump_extended": False,
            "is_long_breakdown_danger": False
        },
        "impulse_wave": {"confluent_bounce": False, "lower_wick_15m": 0.05},
        "rsi": {"rsi_15m": 40.0, "divergence": "NONE"},
        "bollinger": {"is_overextended_lower": True},
        "ema_trend": {"trend": "STRONG_UPTREND"}
    }

    match = evaluate_playbooks(
        symbol="MEME-USDT",
        price=5.0,
        change_24h=10.0,
        spread_pct=0.10,
        market_features=market_features
    )

    assert match.playbook == PlaybookType.NONE.value
    assert match.score == 0


def test_breakdown_retest_without_core_breakdown_is_rejected_score_zero():
    """
    P1-2 Codex Reproduction:
    A setup has a downtrend EMA and an upper wick on pullback,
    but NO actual breakdown of major support (retracement ratio 0.35, no breakdown).
    Previously: additive score reached 65 points and triggered BREAKDOWN_RETEST.
    With mandatory conditions, this MUST be rejected (score 0 / PlaybookType.NONE).
    """
    market_features = {
        "fibonacci": {
            "retracement_ratio": 0.35,
            "is_dump_extended": False,
            "zone": "MID_RANGE"
        },
        "impulse_wave": {"wick_15m": 0.25, "confluent_rejection": True},
        "rsi": {"rsi_15m": 42.0},
        "ema_trend": {"trend": "STRONG_DOWNTREND"}
    }

    match = evaluate_playbooks(
        symbol="MEME-USDT",
        price=1.0,
        change_24h=-5.0,
        spread_pct=0.10,
        market_features=market_features
    )

    assert match.playbook == PlaybookType.NONE.value
    assert match.score == 0


def test_missing_data_does_not_award_points():
    """Missing or empty feature dictionaries must fail mandatory conditions and receive 0 points."""
    match = evaluate_playbooks(
        symbol="EMPTY-USDT",
        price=1.0,
        change_24h=0.0,
        spread_pct=0.10,
        market_features={}
    )
    assert match.playbook == PlaybookType.NONE.value
    assert match.score == 0


def test_valid_setups_with_mandatory_conditions_match_correctly():
    """When core mandatory patterns are present, playbooks match with high confidence."""
    # Valid PUMP_EXHAUSTION with upper wick rejection + peak exhaustion
    pe_features = {
        "fibonacci": {"is_peak_exhaustion": True, "zone": "PEAK_EXHAUSTION"},
        "impulse_wave": {"confluent_rejection": True, "wick_15m": 0.30, "volume_fade": True},
        "rsi": {"rsi_15m": 75.0, "is_overbought": True, "divergence": "BEARISH_DIV"},
        "bollinger": {"is_overextended_upper": True, "percent_b": 0.98},
        "ema_trend": {"trend": "MILD_UPTREND"}
    }
    pe_match = evaluate_playbooks("PEPE-USDT", 10.0, 18.0, 0.10, pe_features)
    assert pe_match.playbook == PlaybookType.PUMP_EXHAUSTION.value
    assert pe_match.score >= 70

    # Valid SUPPORT_PULLBACK with golden pocket + rebound
    sp_features = {
        "fibonacci": {"is_golden_pullback": True, "zone": "GOLDEN_POCKET", "is_dump_extended": False, "is_long_breakdown_danger": False},
        "impulse_wave": {"confluent_bounce": True, "lower_wick_15m": 0.30},
        "rsi": {"rsi_15m": 38.0, "divergence": "BULLISH_DIV"},
        "bollinger": {"is_overextended_lower": True},
        "ema_trend": {"trend": "STRONG_UPTREND"}
    }
    sp_match = evaluate_playbooks("DOGE-USDT", 0.20, 5.0, 0.10, sp_features)
    assert sp_match.playbook == PlaybookType.SUPPORT_PULLBACK.value
    assert sp_match.score >= 70
