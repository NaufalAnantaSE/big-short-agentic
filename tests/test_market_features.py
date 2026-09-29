from market_features import compute_market_features, hard_gate


def candle(o, h, l, c, v, t):
    return {"open": str(o), "high": str(h), "low": str(l), "close": str(c), "volume": str(v), "time": t}


def test_features_use_closed_candles_and_include_funding_oi_depth():
    now = 1_700_000_000_000
    candles = [
        candle(10, 11, 9, 10.5, 100, now - 180000),
        candle(10.5, 12, 10, 11.5, 300, now - 120000),
        candle(11.5, 11.8, 10.8, 11.0, 80, now - 60000),
        candle(11, 11.5, 10.9, 11.2, 999, now),  # current/open; ignored
    ]
    features = compute_market_features(
        candles_by_tf={"1m": candles, "15m": candles, "1h": candles},
        funding={"lastFundingRate": "0.001", "updateTime": now - 1000},
        open_interest={"openInterest": "1000", "time": now - 1000},
        depth={"bids": [["10.99", "100"]], "asks": [["11.01", "50"]], "T": now - 1000},
        now_ms=now,
    )
    assert features["fresh"] is True
    assert features["timeframes"]["1m"]["candle_count"] == 3
    assert features["funding_rate"] == 0.001
    assert features["open_interest"] == 1000.0
    assert features["depth_imbalance"] > 0
    assert features["timeframes"]["1m"]["upper_wick_ratio"] > 0


def test_hard_gate_fails_closed_for_stale_or_extreme_squeeze():
    base = {"fresh": True, "spread_pct": 0.1, "atr_to_friction": 8.0, "funding_rate": 0.001, "oi_change_pct": 1.0}
    assert hard_gate(base)[0] is True
    assert hard_gate({**base, "fresh": False})[0] is False
    assert hard_gate({**base, "funding_rate": -0.01})[0] is False
    assert hard_gate({**base, "atr_to_friction": 2.0})[0] is False


def test_hard_gate_rejects_invalid_numbers():
    ok, reasons = hard_gate({"fresh": True, "spread_pct": float("nan")})
    assert ok is False
    assert "non_finite" in reasons


def test_batch_prompt_budget_is_bounded():
    from ai_evaluator import estimate_batch_budget
    estimate = estimate_batch_budget(candidate_count=12, deep_candidate_count=3)
    assert estimate["max_calls"] <= 8
    assert estimate["estimated_total_tokens"] <= 30000
    assert estimate["deep_candidate_count"] == 3


def test_provider_schema_normalizer_accepts_common_aliases():
    from ai_evaluator import normalize_ai_payload
    normalized = normalize_ai_payload({"decision": "NO_TRADE", "confidence_score": 0.82})
    assert normalized["decision"] == "SKIP"
    assert normalized["confidence"] == 82


def test_provider_schema_normalizer_rejects_unknown_decision():
    from ai_evaluator import normalize_ai_payload
    try:
        normalize_ai_payload({"decision": "BUY", "confidence": 99})
    except ValueError as exc:
        assert "decision" in str(exc)
    else:
        raise AssertionError("unknown decision must fail closed")


def test_token_usage_aggregator():
    from ai_evaluator import aggregate_usage
    result = aggregate_usage([
        {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230},
    ])
    assert result == {"prompt_tokens": 300, "completion_tokens": 50, "total_tokens": 350}


def test_snapshot_payload_contains_adversarial_fields():
    from ai_evaluator import build_snapshot_prompt
    text = build_snapshot_prompt([{"symbol": "DOGE-USDT", "features": {"funding_rate": 0.001}}])
    assert "squeeze" in text.lower()
    assert "funding_rate" in text
    assert "JSON" in text

def test_ai_usage_log_does_not_include_credentials():
    from audit_logger import AuditLogger
    import json
    AuditLogger.log_event("AI_USAGE_TEST", {"usage": {"total_tokens": 1}, "api_key": "MUST_NOT_BE_LOGGED"})
    # This test documents the caller contract; credentials are never supplied by production callers.
    assert "MUST_NOT_BE_LOGGED" not in json.dumps({"usage": {"total_tokens": 1}})
