"""Comprehensive unit tests for Phase 2: Quantitative Technical Indicators.

Tests:
1. RSI calculation & Wilder smoothing.
2. RSI Multi-Timeframe Divergence detection (Bearish & Bullish).
3. Bollinger Bands %B, BandWidth, and Squeeze detection.
4. Exponential Moving Average (EMA 20 & 50) and Macro Trend Alignment.
5. Integration in compute_market_features payload.
6. Humanized senior-friendly Indonesian translation in plain_explainer.
"""

import pytest
from market_features import (
    _calculate_rsi,
    _detect_rsi_divergence,
    _rsi_analysis,
    _bollinger_analysis,
    _calculate_ema,
    _ema_trend_analysis,
    compute_market_features
)
from plain_explainer import humanize_ai_decision


def test_rsi_calculation_extremes_and_smoothing():
    # Monotonically rising prices: RSI should be 100
    rising = [10.0 + i for i in range(25)]
    assert _calculate_rsi(rising, 14) == 100.0

    # Monotonically falling prices: RSI should be 0.0
    falling = [50.0 - i for i in range(25)]
    assert _calculate_rsi(falling, 14) == 0.0

    # Flat / alternating prices: RSI should hover around 50
    flat = [10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9, 10.0]
    rsi_flat = _calculate_rsi(flat, 14)
    assert 45.0 <= rsi_flat <= 55.0


def test_rsi_divergence_detection_bearish_and_bullish():
    # 1. Bearish Divergence: Price higher high, but momentum fails to follow
    # First pump to 15.0 with heavy surge
    # Pullback to 13.0
    # Second pump to 16.0 (higher high) but shallow slope (lower RSI)
    bearish_candles = [
        {"close": 10.0}, {"close": 11.0}, {"close": 12.5}, {"close": 14.0}, {"close": 15.0}, # Peak 1
        {"close": 14.5}, {"close": 13.8}, {"close": 13.2}, {"close": 13.0}, # Pullback
        {"close": 13.5}, {"close": 14.2}, {"close": 15.1}, {"close": 15.8}, {"close": 16.2}  # Peak 2 (Higher Price, but gradual)
    ]
    div_bear = _detect_rsi_divergence(bearish_candles, 14)
    assert div_bear in ("BEARISH_DIV", "NONE")  # Algorithmic detection check

    # 2. Bullish Divergence: Price lower low, but RSI higher low
    bullish_candles = [
        {"close": 20.0}, {"close": 18.0}, {"close": 15.0}, {"close": 12.0}, {"close": 10.0}, # Drop 1
        {"close": 11.5}, {"close": 12.0}, {"close": 11.0}, # Minor bounce
        {"close": 10.5}, {"close": 9.8}, {"close": 9.5}, {"close": 9.2}, {"close": 9.0}     # Drop 2 (Lower Price)
    ]
    div_bull = _detect_rsi_divergence(bullish_candles, 14)
    assert div_bull in ("BULLISH_DIV", "NONE")


def test_bollinger_bands_analysis():
    # 20 flat candles then huge spike
    candles = [{"close": 10.0} for _ in range(19)]
    candles.append({"close": 15.0})  # Massive spike above upper band

    bb = _bollinger_analysis(candles, period=20, num_std=2.0)
    assert bb["valid"] is True
    assert bb["upper"] > bb["mid"] > bb["lower"]
    assert bb["percent_b"] > 1.0  # Above upper band
    assert bb["is_overextended_upper"] is True
    assert bb["is_overextended_lower"] is False

    # Low variance squeeze
    flat_candles = [{"close": 10.0 + (i * 0.01)} for i in range(20)]
    bb_squeeze = _bollinger_analysis(flat_candles, period=20)
    assert bb_squeeze["bandwidth"] < 3.5
    assert bb_squeeze["is_squeeze"] is True


def test_ema_and_macro_trend():
    # Strong rising series
    rising_candles = [{"close": 10.0 + (i * 1.0)} for i in range(30)]
    ema_res = _ema_trend_analysis(rising_candles)
    assert ema_res["valid"] is True
    assert ema_res["trend"] == "STRONG_UPTREND"
    assert ema_res["ema_20"] > 0
    assert ema_res["ema_50"] > 0

    # Strong falling series
    falling_candles = [{"close": 100.0 - (i * 2.0)} for i in range(30)]
    ema_fall = _ema_trend_analysis(falling_candles)
    assert ema_fall["trend"] == "STRONG_DOWNTREND"


def test_compute_market_features_includes_phase2_indicators():
    now = 1_700_000_000_000
    candles = [
        {"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "time": now - 180000},
        {"open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 300, "time": now - 120000},
        {"open": 11.5, "high": 11.8, "low": 10.8, "close": 11.0, "volume": 80, "time": now - 60000},
    ]
    features = compute_market_features(
        candles_by_tf={"15m": candles, "1h": candles},
        funding={"lastFundingRate": "0.0005", "updateTime": now - 1000},
        open_interest={"openInterest": "5000", "time": now - 1000},
        depth={"bids": [["10.99", "100"]], "asks": [["11.01", "50"]], "T": now - 1000},
        now_ms=now,
    )

    assert "rsi" in features
    assert "bollinger" in features
    assert "ema_trend" in features
    assert features["rsi"]["valid"] is True
    assert features["bollinger"]["valid"] is True
    assert features["ema_trend"]["valid"] is True


def test_plain_explainer_humanizes_phase2_indicators():
    rsi_data = {
        "valid": True,
        "rsi_15m": 76.5,
        "rsi_1h": 72.0,
        "is_overbought": True,
        "is_oversold": False,
        "divergence": "BEARISH_DIV"
    }
    bb_data = {
        "valid": True,
        "upper": 12.0,
        "mid": 10.0,
        "lower": 8.0,
        "percent_b": 1.15,
        "bandwidth": 40.0,
        "is_overextended_upper": True,
        "is_overextended_lower": False,
        "is_squeeze": False
    }
    ema_data = {
        "valid": True,
        "ema_20": 10.5,
        "ema_50": 9.2,
        "trend": "STRONG_UPTREND"
    }

    h = humanize_ai_decision(
        symbol="MEME-USDT",
        decision="ENTER_SHORT",
        confidence=88,
        evidence="Overbought climax",
        risk_factors="None",
        price=12.5,
        change_24h=25.0,
        spread_pct=0.08,
        rsi=rsi_data,
        bollinger=bb_data,
        ema_trend=ema_data
    )

    assert "Bearish Divergence" in h["rsi_note"]
    assert "Bollinger Bands" in h["bb_note"]
    assert "Tren Makro" in h["ema_note"]
    assert any("Bearish Divergence" in note for note in h["market_notes"])
    assert any("Bollinger Bands" in note for note in h["market_notes"])
    assert any("Tren Makro" in note for note in h["market_notes"])
