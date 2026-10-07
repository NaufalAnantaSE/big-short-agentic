"""Deterministic crypto-perpetual features, Fibonacci retracements, wave exhaustion, and fail-closed hard gates."""

from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Tuple


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _closed_rows(rows: Iterable[Dict[str, Any]], now_ms: int) -> List[Dict[str, float]]:
    result: List[Dict[str, float]] = []
    for row in rows:
        ts = _finite(row.get("time", row.get("timestamp")))
        values = {key: _finite(row.get(key)) for key in ("open", "high", "low", "close", "volume")}
        if ts is None or ts >= now_ms or any(v is None for v in values.values()):
            continue
        low = float(values["low"])  # type: ignore[arg-type]
        high = float(values["high"])  # type: ignore[arg-type]
        if low <= 0 or high < low:
            continue
        result.append({key: float(value) for key, value in values.items()} | {"time": ts})  # type: ignore[arg-type]
    return sorted(result, key=lambda item: item["time"])


def _timeframe_features(rows: Iterable[Dict[str, Any]], now_ms: int) -> Dict[str, Any]:
    closed = _closed_rows(rows, now_ms)
    if not closed:
        return {"candle_count": 0, "valid": False}
    closes = [row["close"] for row in closed]
    volumes = [row["volume"] for row in closed]
    last = closed[-1]
    ranges = [row["high"] - row["low"] for row in closed]
    upper_wick = last["high"] - max(last["open"], last["close"])
    last_range = max(last["high"] - last["low"], 1e-12)
    avg_range = mean(ranges[-14:]) if ranges else 0.0
    avg_close = mean(closes[-14:]) if closes else last["close"]
    vol_mean = mean(volumes[-20:]) if volumes else 0.0
    vol_std = pstdev(volumes[-20:]) if len(volumes[-20:]) > 1 else 0.0
    vol_z = (last["volume"] - vol_mean) / vol_std if vol_std > 0 else 0.0
    change_pct = ((last["close"] / closes[0]) - 1.0) * 100 if closes[0] > 0 else 0.0
    ema_distance = ((last["close"] / avg_close) - 1.0) * 100 if avg_close > 0 else 0.0
    return {
        "candle_count": len(closed), "valid": True, "last_close": last["close"],
        "change_pct": change_pct, "atr": avg_range, "atr_pct": (avg_range / last["close"] * 100) if last["close"] > 0 else 0.0,
        "distance_from_mean_pct": ema_distance, "upper_wick_ratio": upper_wick / last_range,
        "volume_zscore": vol_z, "last_direction": "UP" if last["close"] >= last["open"] else "DOWN",
        "last_time": int(last["time"]),
    }


def _fibonacci_analysis(closed_rows: List[Dict[str, float]], current_price: float) -> Dict[str, Any]:
    """
    Computes mathematical Fibonacci Retracement and Extension levels over the recent swing window.
    Standard Retracement levels from Swing High (0.0) to Swing Low (1.0):
      0.0   - Swing High (peak resistance)
      0.236 - Shallow initial pullback
      0.382 - Healthy pullback zone
      0.500 - Midpoint equilibrium
      0.618 - Golden pocket
      0.786 - Deep retracement / breakdown
      1.000 - Swing Low (base support)
    Extension levels:
      1.272 & 1.618 - Overextended Blow-Off Top exhaustion targets
    """
    if not closed_rows or len(closed_rows) < 3 or current_price <= 0:
        return {
            "valid": False,
            "zone": "UNKNOWN",
            "retracement_ratio": 0.0,
            "swing_high": current_price,
            "swing_low": current_price,
            "fib_0_high": current_price,
            "fib_236": current_price,
            "fib_382": current_price,
            "fib_500": current_price,
            "fib_618": current_price,
            "fib_786": current_price,
            "fib_100_low": current_price,
            "fib_ext_1272": current_price,
            "fib_ext_1618": current_price,
            "is_peak_exhaustion": False,
            "is_dump_extended": False,
        }

    # Use up to the last 24 closed candles to determine local swing
    window = closed_rows[-24:]
    highs = [r["high"] for r in window]
    lows = [r["low"] for r in window]
    swing_high = max(highs)
    swing_low = min(lows)
    swing_range = max(swing_high - swing_low, 1e-12)

    fib_236 = swing_high - 0.236 * swing_range
    fib_382 = swing_high - 0.382 * swing_range
    fib_500 = swing_high - 0.500 * swing_range
    fib_618 = swing_high - 0.618 * swing_range
    fib_786 = swing_high - 0.786 * swing_range
    fib_ext_1272 = swing_low + 1.272 * swing_range
    fib_ext_1618 = swing_low + 1.618 * swing_range

    retracement_ratio = (swing_high - current_price) / swing_range

    if retracement_ratio <= 0.0:
        zone = "BLOW_OFF_EXTENSION"
    elif retracement_ratio <= 0.15:
        zone = "PEAK_EXHAUSTION"
    elif retracement_ratio <= 0.382:
        zone = "SHALLOW_PULLBACK"
    elif retracement_ratio <= 0.618:
        zone = "MID_RETRACEMENT"
    else:
        zone = "EXTENDED_DUMP"

    is_peak_exhaustion = zone in ("BLOW_OFF_EXTENSION", "PEAK_EXHAUSTION", "SHALLOW_PULLBACK")
    is_dump_extended = zone == "EXTENDED_DUMP"
    is_golden_pullback = (0.35 <= retracement_ratio <= 0.68)
    is_long_fomo_danger = zone in ("BLOW_OFF_EXTENSION", "PEAK_EXHAUSTION") or retracement_ratio <= 0.05
    is_long_breakdown_danger = retracement_ratio >= 0.786

    return {
        "valid": True,
        "zone": zone,
        "retracement_ratio": round(retracement_ratio, 4),
        "swing_high": round(swing_high, 6),
        "swing_low": round(swing_low, 6),
        "fib_0_high": round(swing_high, 6),
        "fib_236": round(fib_236, 6),
        "fib_382": round(fib_382, 6),
        "fib_500": round(fib_500, 6),
        "fib_618": round(fib_618, 6),
        "fib_786": round(fib_786, 6),
        "fib_100_low": round(swing_low, 6),
        "fib_ext_1272": round(fib_ext_1272, 6),
        "fib_ext_1618": round(fib_ext_1618, 6),
        "distance_to_high_pct": round(((swing_high - current_price) / current_price) * 100, 2),
        "is_peak_exhaustion": is_peak_exhaustion,
        "is_dump_extended": is_dump_extended,
        "is_golden_pullback": is_golden_pullback,
        "is_long_fomo_danger": is_long_fomo_danger,
        "is_long_breakdown_danger": is_long_breakdown_danger,
    }


def _impulse_wave_analysis(closed_15m: List[Dict[str, float]], closed_1h: List[Dict[str, float]], current_price: float) -> Dict[str, Any]:
    """
    Analyzes candlestick waves and impulse structure:
      - Consecutive impulse green candles in recent run
      - Volume fade on higher prices (Bearish Volume Divergence)
      - Upper wick rejection confluence across 15m & 1h
    """
    if not closed_15m:
        return {
            "valid": False,
            "consecutive_bull_bars": 0,
            "volume_fade": False,
            "confluent_rejection": False,
            "wick_15m": 0.0,
            "wick_1h": 0.0,
            "exhaustion_score": 0
        }

    bull_count = 0
    for r in reversed(closed_15m[-8:]):
        if r["close"] >= r["open"]:
            bull_count += 1
        else:
            break

    volumes = [r["volume"] for r in closed_15m[-6:]]
    vol_mean = mean(volumes[:-1]) if len(volumes) > 1 else (volumes[0] if volumes else 0.0)
    last_vol = volumes[-1] if volumes else 0.0
    volume_fade = (last_vol < vol_mean * 0.75) and (bull_count >= 2)

    last_15m = closed_15m[-1]
    range_15m = max(last_15m["high"] - last_15m["low"], 1e-12)
    wick_15m = (last_15m["high"] - max(last_15m["open"], last_15m["close"])) / range_15m
    lower_wick_15m = (min(last_15m["open"], last_15m["close"]) - last_15m["low"]) / range_15m

    wick_1h = 0.0
    lower_wick_1h = 0.0
    if closed_1h:
        last_1h = closed_1h[-1]
        range_1h = max(last_1h["high"] - last_1h["low"], 1e-12)
        wick_1h = (last_1h["high"] - max(last_1h["open"], last_1h["close"])) / range_1h
        lower_wick_1h = (min(last_1h["open"], last_1h["close"]) - last_1h["low"]) / range_1h

    confluent_rejection = (wick_15m >= 0.40) or (wick_15m >= 0.25 and wick_1h >= 0.25)

    score = 0
    if bull_count >= 3:
        score += 30
    elif bull_count >= 2:
        score += 15
    if volume_fade:
        score += 25
    if confluent_rejection:
        score += 35
    if wick_15m >= 0.50:
        score += 10

    return {
        "valid": True,
        "consecutive_bull_bars": bull_count,
        "volume_fade": volume_fade,
        "confluent_rejection": (wick_15m >= 0.25 and wick_1h >= 0.20),
        "wick_15m": round(wick_15m, 3),
        "wick_1h": round(wick_1h, 3),
        "lower_wick_15m": round(lower_wick_15m, 3),
        "lower_wick_1h": round(lower_wick_1h, 3),
        "exhaustion_score": min(score, 100)
    }


def _funding_sentiment(funding_rate: float | None) -> str:
    if funding_rate is None:
        return "UNKNOWN"
    if funding_rate > 0.0005:
        return "EXTREME_LONG_CROWD"
    if funding_rate > 0.0001:
        return "MODERATE_LONG_CROWD"
    if funding_rate >= 0.0:
        return "NEUTRAL_POSITIVE"
    if funding_rate >= -0.005:
        return "MILD_NEGATIVE"
    return "EXTREME_SHORT_CROWD_SQUEEZE_RISK"


def _calculate_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < 3:
        return 50.0
    actual_period = min(period, len(closes) - 1)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0.0, d) for d in deltas]
    losses = [max(0.0, -d) for d in deltas]

    avg_gain = mean(gains[:actual_period]) if gains else 0.0
    avg_loss = mean(losses[:actual_period]) if losses else 0.0

    for i in range(actual_period, len(deltas)):
        avg_gain = (avg_gain * (actual_period - 1) + gains[i]) / actual_period
        avg_loss = (avg_loss * (actual_period - 1) + losses[i]) / actual_period

    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _detect_rsi_divergence(closed_rows: List[Dict[str, float]], period: int = 14) -> str:
    """
    Detects regular divergence between price and RSI in the recent window.
    Returns 'BEARISH_DIV', 'BULLISH_DIV', or 'NONE'.
    """
    if len(closed_rows) < 8:
        return "NONE"

    window = closed_rows[-20:]
    closes = [r["close"] for r in window]

    rsi_vals = []
    for i in range(4, len(closes) + 1):
        rsi_vals.append(_calculate_rsi(closes[:i], period=min(period, i - 1)))

    if len(rsi_vals) < 5:
        return "NONE"

    curr_price = closes[-1]
    curr_rsi = rsi_vals[-1]

    prev_prices = closes[-10:-2]
    prev_rsis = rsi_vals[-10:-2] if len(rsi_vals) >= 10 else rsi_vals[:-2]

    if not prev_prices or not prev_rsis:
        return "NONE"

    max_prev_price = max(prev_prices)
    max_prev_rsi = max(prev_rsis)
    min_prev_price = min(prev_prices)
    min_prev_rsi = min(prev_rsis)

    # Bearish Divergence: Price higher than previous peak, but RSI lower than previous peak (RSI >= 58)
    if curr_price >= max_prev_price and curr_rsi < max_prev_rsi and curr_rsi >= 58.0:
        return "BEARISH_DIV"

    # Bullish Divergence: Price lower than previous trough, but RSI higher than previous trough (RSI <= 42)
    if curr_price <= min_prev_price and curr_rsi > min_prev_rsi and curr_rsi <= 42.0:
        return "BULLISH_DIV"

    return "NONE"


def _rsi_analysis(closed_15m: List[Dict[str, float]], closed_1h: List[Dict[str, float]]) -> Dict[str, Any]:
    if not closed_15m:
        return {
            "valid": False,
            "rsi_15m": 50.0,
            "rsi_1h": 50.0,
            "is_overbought": False,
            "is_oversold": False,
            "divergence": "NONE"
        }

    closes_15m = [r["close"] for r in closed_15m]
    closes_1h = [r["close"] for r in closed_1h] if closed_1h else closes_15m

    rsi_15m = _calculate_rsi(closes_15m, period=14)
    rsi_1h = _calculate_rsi(closes_1h, period=14)
    divergence = _detect_rsi_divergence(closed_15m, period=14)

    is_ob = rsi_15m >= 70.0 or rsi_1h >= 70.0
    is_os = rsi_15m <= 30.0 or rsi_1h <= 30.0

    return {
        "valid": True,
        "rsi_15m": rsi_15m,
        "rsi_1h": rsi_1h,
        "is_overbought": is_ob,
        "is_oversold": is_os,
        "divergence": divergence
    }


def _bollinger_analysis(closed_rows: List[Dict[str, float]], period: int = 20, num_std: float = 2.0) -> Dict[str, Any]:
    if not closed_rows or len(closed_rows) < 3:
        return {
            "valid": False,
            "upper": 0.0,
            "mid": 0.0,
            "lower": 0.0,
            "percent_b": 0.5,
            "bandwidth": 0.0,
            "is_overextended_upper": False,
            "is_overextended_lower": False,
            "is_squeeze": False
        }

    window = closed_rows[-period:]
    closes = [r["close"] for r in window]
    mid = mean(closes)
    std = pstdev(closes) if len(closes) > 1 else 0.0
    upper = mid + (num_std * std)
    lower = mid - (num_std * std)
    curr = closes[-1]

    band_range = max(upper - lower, 1e-12)
    percent_b = (curr - lower) / band_range
    bandwidth = (band_range / mid * 100.0) if mid > 0 else 0.0

    return {
        "valid": True,
        "upper": round(upper, 6),
        "mid": round(mid, 6),
        "lower": round(lower, 6),
        "percent_b": round(percent_b, 4),
        "bandwidth": round(bandwidth, 2),
        "is_overextended_upper": percent_b >= 1.0,
        "is_overextended_lower": percent_b <= 0.0,
        "is_squeeze": bandwidth < 3.5
    }


def _calculate_ema(closes: List[float], period: int) -> float:
    if not closes:
        return 0.0
    if len(closes) < period:
        return mean(closes)
    multiplier = 2.0 / (period + 1.0)
    ema = mean(closes[:period])
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def _ema_trend_analysis(closed_rows: List[Dict[str, float]]) -> Dict[str, Any]:
    if not closed_rows or len(closed_rows) < 3:
        return {
            "valid": False,
            "ema_20": 0.0,
            "ema_50": 0.0,
            "trend": "NEUTRAL"
        }

    closes = [r["close"] for r in closed_rows]
    curr = closes[-1]
    ema_20 = _calculate_ema(closes, 20)
    ema_50 = _calculate_ema(closes, 50)

    if curr > ema_20 > ema_50:
        trend = "STRONG_UPTREND"
    elif curr < ema_20 < ema_50:
        trend = "STRONG_DOWNTREND"
    elif curr > ema_20:
        trend = "MILD_UPTREND"
    elif curr < ema_20:
        trend = "MILD_DOWNTREND"
    else:
        trend = "NEUTRAL"

    return {
        "valid": True,
        "ema_20": round(ema_20, 6),
        "ema_50": round(ema_50, 6),
        "trend": trend
    }


def compute_market_features(
    candles_by_tf: Dict[str, Iterable[Dict[str, Any]]],
    funding: Dict[str, Any],
    open_interest: Dict[str, Any],
    depth: Dict[str, Any],
    now_ms: int,
    max_age_ms: int = 120_000,
    max_funding_age_ms: int = 43_200_000
) -> Dict[str, Any]:
    timeframes = {tf: _timeframe_features(rows, now_ms) for tf, rows in candles_by_tf.items()}
    funding_rate = _finite(funding.get("lastFundingRate"))
    oi = _finite(open_interest.get("openInterest"))
    funding_ts = _finite(funding.get("updateTime"))
    oi_ts = _finite(open_interest.get("time"))
    depth_ts = _finite(depth.get("T"))

    def is_fresh(ts: float | None, max_age: int) -> bool:
        return ts is not None and ts <= now_ms + 5_000 and now_ms - ts <= max_age

    fresh = is_fresh(funding_ts, max_funding_age_ms) and is_fresh(oi_ts, max_age_ms) and is_fresh(depth_ts, max_age_ms)
    bids, asks = depth.get("bids") or [], depth.get("asks") or []
    bid_qty = sum((_finite(row[1]) or 0.0) for row in bids if len(row) >= 2)
    ask_qty = sum((_finite(row[1]) or 0.0) for row in asks if len(row) >= 2)
    total_depth = bid_qty + ask_qty
    imbalance = (bid_qty - ask_qty) / total_depth if total_depth > 0 else float("nan")
    best_bid = _finite(bids[0][0]) if bids and len(bids[0]) >= 2 else None
    best_ask = _finite(asks[0][0]) if asks and len(asks[0]) >= 2 else None
    spread = ((best_ask - best_bid) / best_bid * 100) if best_bid and best_ask and best_ask >= best_bid else float("nan")
    atr_pct = max(float(timeframes.get("1h", {}).get("atr_pct", 0.0) or 0.0), float(timeframes.get("15m", {}).get("atr_pct", 0.0) or 0.0))
    friction_pct = 0.10 + (spread if math.isfinite(spread) else 1.0)

    # Multi-timeframe closed candle series for Fibonacci and Wave analysis
    closed_1h = _closed_rows(candles_by_tf.get("1h", []), now_ms)
    closed_15m = _closed_rows(candles_by_tf.get("15m", []), now_ms)
    last_close = closed_15m[-1]["close"] if closed_15m else (closed_1h[-1]["close"] if closed_1h else 0.0)

    fibonacci = _fibonacci_analysis(closed_1h or closed_15m, last_close)
    impulse_wave = _impulse_wave_analysis(closed_15m, closed_1h, last_close)
    funding_sent = _funding_sentiment(funding_rate)

    atr_val = max(float(timeframes.get("1h", {}).get("atr", 0.0) or 0.0), float(timeframes.get("15m", {}).get("atr", 0.0) or 0.0))

    # Phase 2 Indicators: RSI Divergence, Bollinger Bands, EMA Trend
    rsi = _rsi_analysis(closed_15m, closed_1h)
    bollinger = _bollinger_analysis(closed_15m or closed_1h)
    ema_trend = _ema_trend_analysis(closed_15m or closed_1h)

    return {
        "fresh": fresh,
        "timeframes": timeframes,
        "funding_rate": funding_rate,
        "funding_sentiment": funding_sent,
        "open_interest": oi,
        "depth_imbalance": imbalance,
        "spread_pct": spread,
        "atr": atr_val,
        "atr_to_friction": atr_pct / friction_pct if friction_pct > 0 else 0.0,
        "fibonacci": fibonacci,
        "impulse_wave": impulse_wave,
        "rsi": rsi,
        "bollinger": bollinger,
        "ema_trend": ema_trend
    }


def hard_gate(features: Dict[str, Any], max_spread_pct: float = 0.35) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if features.get("fresh") is not True:
        reasons.append("stale_data")
    for key in ("spread_pct", "funding_rate", "atr_to_friction"):
        if _finite(features.get(key)) is None:
            reasons.append("non_finite")
    spread, funding, ratio = _finite(features.get("spread_pct")), _finite(features.get("funding_rate")), _finite(features.get("atr_to_friction"))
    if spread is not None and spread > max_spread_pct:
        reasons.append("spread_too_wide")
    if funding is not None and funding <= -0.005:
        reasons.append("crowded_short_squeeze_risk")
    if ratio is not None and ratio < 3.0:
        reasons.append("atr_below_friction_threshold")

    # Reject if price has already dumped past 68% of the swing (avoid shorting the bottom)
    fib = features.get("fibonacci")
    if isinstance(fib, dict) and fib.get("valid") and fib.get("is_dump_extended"):
        reasons.append("dump_already_extended")

    return not reasons, reasons


def build_candidate_features(client: Any, symbol: str, now_ms: int | None = None) -> Dict[str, Any]:
    import time
    now = now_ms or int(time.time() * 1000)
    candles = {tf: client.get_klines(symbol, interval=tf, limit=30) for tf in ("1m", "15m", "1h")}
    funding = client._request("GET", "/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol}, signed=False)
    oi = client._request("GET", "/openApi/swap/v2/quote/openInterest", {"symbol": symbol}, signed=False)
    return compute_market_features(candles, funding, oi, client.get_depth(symbol, limit=5), now)
