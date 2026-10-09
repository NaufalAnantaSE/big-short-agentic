"""Tests for batch triage evaluator timeout, telemetry, compact prompt, and validation."""

import time
import json
import pytest
import httpx
from config import AppConfig
from ai_evaluator import (
    AIEvaluator,
    BatchTriageResult,
    TriageCandidate,
    build_batch_triage_prompt
)


def test_batch_triage_uses_60s_read_10s_connect_timeout(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": '{"ranked_candidates": [{"symbol": "BTC-USDT", "rank": 1, "action": "SKIP", "suggested_direction": "UNKNOWN", "conviction_score": 10, "triage_reason": "none"}], "selected_finalists": []}'
            }
        }],
        "usage": {}
    }
    mock_post = mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    evaluator.evaluate_batch_triage([{"symbol": "BTC-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert mock_post.called
    _, kwargs = mock_post.call_args
    assert "timeout" in kwargs
    timeout = kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read == 60.0
    assert timeout.connect == 10.0


def test_other_eval_preserves_30s_default_timeout(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    assert evaluator.client.timeout.read == 30.0


def test_batch_triage_result_telemetry_defaults():
    res = BatchTriageResult()
    assert res.is_valid is False
    assert res.latency_ms == 0.0
    assert res.error_type is None
    assert res.attempts == 1
    assert res.attempt == 1

    # Supports passing attempt alias
    res2 = BatchTriageResult(attempt=2)
    assert res2.attempts == 2
    assert res2.attempt == 2


def test_batch_triage_connect_timeout_telemetry(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    def slow_connect(*args, **kwargs):
        time.sleep(0.02)
        raise httpx.ConnectTimeout("Connect timeout to gateway")

    mocker.patch.object(evaluator.client, "post", side_effect=slow_connect)

    res = evaluator.evaluate_batch_triage([{"symbol": "BTC-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "CONNECT_TIMEOUT"
    assert "Connect timeout" in res.error_message
    assert res.latency_ms > 0.0  # Measured failed latency, not 0.0
    assert res.attempts == 1
    assert res.attempt == 1


def test_batch_triage_read_timeout_telemetry(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    def slow_read(*args, **kwargs):
        time.sleep(0.02)
        raise httpx.ReadTimeout("Read timeout after 60s")

    mocker.patch.object(evaluator.client, "post", side_effect=slow_read)

    res = evaluator.evaluate_batch_triage([{"symbol": "ETH-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "READ_TIMEOUT"
    assert "Read timeout" in res.error_message
    assert res.latency_ms > 0.0
    assert res.attempts == 1


def test_batch_triage_http_error_telemetry(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 502
    mock_resp.text = "Bad Gateway"
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_batch_triage([{"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "HTTP_ERROR"
    assert "502" in res.error_message
    assert res.latency_ms >= 0.0
    assert res.attempts == 1


def test_compact_batch_prompt_preserves_essentials_and_strips_bloat():
    candidates = [
        {
            "symbol": "DOGE-USDT",
            "allowed_directions": ["SHORT"],
            "current_price": 0.15,
            "price_change_24h": 12.5,
            "rsi_15m": 72.3,
            "volume_sma_ratio": 2.1,
            "funding_rate": 0.0008,
            "atr_pct": 3.2,
            "spread_pct": 0.04,
            "fib_zone": "PEAK_EXHAUSTION",
            "playbook_matched": "PUMP_EXHAUSTION",
            "bloated_debug_key": "x" * 2000,
            "raw_candles": [{"c": 1}, {"c": 2}]
        }
    ]

    prompt = build_batch_triage_prompt(candidates, direction="SHORT")

    # Essential metrics and contract preserved
    assert "DOGE-USDT" in prompt
    assert "SHORT" in prompt
    assert "allowed_directions" in prompt
    assert "price_change_24h" in prompt or "change_24h" in prompt
    assert "rsi_15m" in prompt or "rsi" in prompt
    assert "cap: select at most 2 finalists" in prompt.lower() or "at most 2 finalists" in prompt.lower()
    assert "selected_finalists" in prompt

    # Extraneous keys stripped
    assert "bloated_debug_key" not in prompt
    assert "raw_candles" not in prompt


def test_fail_closed_on_empty_response_to_nonempty_input(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"ranked_candidates": [], "selected_finalists": []}'}}],
        "usage": {}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_batch_triage([{"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "VALIDATION_ERROR"
    assert "empty" in res.error_message.lower()
    assert res.latency_ms >= 0.0
    assert res.attempts == 1


def test_fail_closed_on_unknown_symbol(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "ranked_candidates": [
                        {"symbol": "UNKNOWN-COIN", "rank": 1, "action": "DEEP_ANALYZE", "suggested_direction": "SHORT", "conviction_score": 85, "triage_reason": "fake"}
                    ],
                    "selected_finalists": ["UNKNOWN-COIN"]
                })
            }
        }],
        "usage": {}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_batch_triage([{"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "VALIDATION_ERROR"
    assert "unknown" in res.error_message.lower()


def test_fail_closed_on_duplicate_symbol(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "ranked_candidates": [
                        {"symbol": "SOL-USDT", "rank": 1, "action": "DEEP_ANALYZE", "suggested_direction": "SHORT", "conviction_score": 85, "triage_reason": "first"},
                        {"symbol": "SOL-USDT", "rank": 2, "action": "WATCH", "suggested_direction": "SHORT", "conviction_score": 70, "triage_reason": "duplicate"}
                    ],
                    "selected_finalists": ["SOL-USDT"]
                })
            }
        }],
        "usage": {}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_batch_triage([{"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "VALIDATION_ERROR"
    assert "duplicate" in res.error_message.lower()


def test_fail_closed_on_finalist_not_ranked_deep(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "ranked_candidates": [
                        {"symbol": "SOL-USDT", "rank": 1, "action": "WATCH", "suggested_direction": "SHORT", "conviction_score": 75, "triage_reason": "premature"}
                    ],
                    "selected_finalists": ["SOL-USDT"]  # Finalist is WATCH, not DEEP_ANALYZE
                })
            }
        }],
        "usage": {}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_batch_triage([{"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "VALIDATION_ERROR"
    assert "deep" in res.error_message.lower()


def test_fail_closed_on_disallowed_direction(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    # Candidate allows only SHORT, but LLM suggested LONG
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "ranked_candidates": [
                        {"symbol": "SOL-USDT", "rank": 1, "action": "DEEP_ANALYZE", "suggested_direction": "LONG", "conviction_score": 85, "triage_reason": "bullish"}
                    ],
                    "selected_finalists": ["SOL-USDT"]
                })
            }
        }],
        "usage": {}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_batch_triage([{"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "VALIDATION_ERROR"
    assert "direction" in res.error_message.lower()


def test_fail_closed_on_unknown_direction_for_deep_analyze(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    # Candidate is DEEP_ANALYZE, but suggested_direction is UNKNOWN (only SKIP may remain UNKNOWN)
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "ranked_candidates": [
                        {"symbol": "SOL-USDT", "rank": 1, "action": "DEEP_ANALYZE", "suggested_direction": "UNKNOWN", "conviction_score": 85, "triage_reason": "ambiguous"}
                    ],
                    "selected_finalists": ["SOL-USDT"]
                })
            }
        }],
        "usage": {}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_batch_triage([{"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    assert res.is_valid is False
    assert res.error_type == "VALIDATION_ERROR"
    assert "direction" in res.error_message.lower()


def test_validation_allows_unknown_direction_for_skip(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    # SKIP candidate with UNKNOWN direction is valid
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "ranked_candidates": [
                        {"symbol": "SOL-USDT", "rank": 1, "action": "SKIP", "suggested_direction": "UNKNOWN", "conviction_score": 20, "triage_reason": "no edge"}
                    ],
                    "selected_finalists": []
                })
            }
        }],
        "usage": {}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_batch_triage([{"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]}], direction="SHORT")

    # In current implementation this passes, but when validator is added it must remain valid
    assert res.error_type is None


def test_validation_succeeds_for_valid_triage(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "ranked_candidates": [
                        {"symbol": "SOL-USDT", "rank": 1, "action": "DEEP_ANALYZE", "suggested_direction": "SHORT", "conviction_score": 85, "triage_reason": "clean rejection"},
                        {"symbol": "DOGE-USDT", "rank": 2, "action": "WATCH", "suggested_direction": "SHORT", "conviction_score": 75, "triage_reason": "near resistance"},
                        {"symbol": "PEPE-USDT", "rank": 3, "action": "SKIP", "suggested_direction": "UNKNOWN", "conviction_score": 30, "triage_reason": "too extended"}
                    ],
                    "selected_finalists": ["SOL-USDT"]
                })
            }
        }],
        "usage": {"total_tokens": 120}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    input_candidates = [
        {"symbol": "SOL-USDT", "allowed_directions": ["SHORT"]},
        {"symbol": "DOGE-USDT", "allowed_directions": ["SHORT"]},
        {"symbol": "PEPE-USDT", "allowed_directions": ["SHORT"]}
    ]
    res = evaluator.evaluate_batch_triage(input_candidates, direction="SHORT")

    assert res.is_valid is True
    assert res.error_type is None
    assert len(res.ranked_candidates) == 3
    assert res.selected_finalists == ["SOL-USDT"]
    assert res.latency_ms >= 0.0
    assert res.attempts == 1
