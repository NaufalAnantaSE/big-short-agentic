"""Deterministic crypto-perpetual features and fail-closed hard gates."""

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
        "change_pct": change_pct, "atr_pct": (avg_range / last["close"] * 100) if last["close"] > 0 else 0.0,
        "distance_from_mean_pct": ema_distance, "upper_wick_ratio": upper_wick / last_range,
        "volume_zscore": vol_z, "last_direction": "UP" if last["close"] >= last["open"] else "DOWN",
        "last_time": int(last["time"]),
    }


def compute_market_features(candles_by_tf: Dict[str, Iterable[Dict[str, Any]]], funding: Dict[str, Any], open_interest: Dict[str, Any], depth: Dict[str, Any], now_ms: int, max_age_ms: int = 120_000, max_funding_age_ms: int = 43_200_000) -> Dict[str, Any]:
    timeframes = {tf: _timeframe_features(rows, now_ms) for tf, rows in candles_by_tf.items()}
    funding_rate = _finite(funding.get("lastFundingRate"))
    oi = _finite(open_interest.get("openInterest"))
    funding_ts = _finite(funding.get("updateTime"))
    oi_ts = _finite(open_interest.get("time"))
    depth_ts = _finite(depth.get("T"))

    def is_fresh(ts: float | None, max_age: int) -> bool:
        # Exchange clocks can lead local clock by a few seconds; larger future drift is invalid.
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
    return {"fresh": fresh, "timeframes": timeframes, "funding_rate": funding_rate, "open_interest": oi, "depth_imbalance": imbalance, "spread_pct": spread, "atr_to_friction": atr_pct / friction_pct if friction_pct > 0 else 0.0}


def hard_gate(features: Dict[str, Any], max_spread_pct: float = 0.35) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if features.get("fresh") is not True:
        reasons.append("stale_data")
    for key in ("spread_pct", "funding_rate", "atr_to_friction"):
        if _finite(features.get(key)) is None:
            reasons.append("non_finite")
    spread, funding, ratio = _finite(features.get("spread_pct")), _finite(features.get("funding_rate")), _finite(features.get("atr_to_friction"))
    if spread is not None and spread > max_spread_pct: reasons.append("spread_too_wide")
    if funding is not None and funding <= -0.005: reasons.append("crowded_short_squeeze_risk")
    if ratio is not None and ratio < 3.0: reasons.append("atr_below_friction_threshold")
    return not reasons, reasons


def build_candidate_features(client: Any, symbol: str, now_ms: int | None = None) -> Dict[str, Any]:
    import time
    now = now_ms or int(time.time() * 1000)
    candles = {tf: client.get_klines(symbol, interval=tf, limit=30) for tf in ("1m", "15m", "1h")}
    funding = client._request("GET", "/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol}, signed=False)
    oi = client._request("GET", "/openApi/swap/v2/quote/openInterest", {"symbol": symbol}, signed=False)
    return compute_market_features(candles, funding, oi, client.get_depth(symbol, limit=5), now)
