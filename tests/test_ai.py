"""Unit tests for 9Router AI Evaluator module and fail-closed policies."""

import pytest
import httpx
from ai_evaluator import AIEvaluator
from config import AppConfig

def test_ai_valid_short_response(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": '{"symbol": "1000PEPE-USDT", "decision": "ENTER_SHORT", "confidence": 85, "setup_type": "PUMP_EXHAUSTION", "key_evidence": "Buyer drop after 15% spike", "risk_factors": "none"}'
            }
        }]
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_candidate(
        symbol="1000PEPE-USDT",
        price_change_24h=15.0,
        current_price=0.008,
        klines_summary=[0.007, 0.0075, 0.008],
        spread_pct=0.05
    )

    assert res.is_valid is True
    assert res.decision == "ENTER_SHORT"
    assert res.confidence == 85
    assert res.setup_type == "PUMP_EXHAUSTION"

def test_ai_confidence_gate_downgrade(mocker):
    # Confidence < 75 should be downgraded to WAIT
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": '{"symbol": "DOGE-USDT", "decision": "ENTER_SHORT", "confidence": 60, "setup_type": "PUMP_EXHAUSTION", "key_evidence": "Weak bounce", "risk_factors": "High volume"}'
            }
        }]
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_candidate("DOGE-USDT", 4.0, 0.15, [], 0.02)
    assert res.decision == "WAIT"

def test_ai_fail_closed_on_timeout(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mocker.patch.object(evaluator.client, "post", side_effect=httpx.TimeoutException("Timeout after 8s"))

    res = evaluator.evaluate_candidate("1000PEPE-USDT", 10.0, 0.008, [], 0.05)
    assert res.decision == "SKIP"
    assert res.is_valid is False
    assert "timed out" in res.error_message

def test_ai_fail_closed_on_invalid_json(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {"content": "I am not sure if you should short this coin right now."}
        }]
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_candidate("BONK-USDT", 2.0, 0.00002, [], 0.05)
    assert res.decision == "SKIP"
    assert res.is_valid is False

def test_ai_normalizes_provider_aliases_and_records_usage(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"symbol":"DOGE-USDT","decision":"NO_TRADE","confidence_score":0.82,"setup_type":"NONE","key_evidence":"No setup","risk_factors":"No exhaustion"}'}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_candidate("DOGE-USDT", 2.0, 0.1, [], 0.1)

    assert res.is_valid is True
    assert res.decision == "SKIP"
    assert res.confidence == 82
    assert res.usage["total_tokens"] == 140
    assert res.latency_ms >= 0

def test_ai_rejects_unsupported_decision(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"symbol":"DOGE-USDT","decision":"FOMO_MOON","confidence":99}'}}]
    }
    mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    res = evaluator.evaluate_candidate("DOGE-USDT", 2.0, 0.1, [], 0.1)

    assert res.decision == "SKIP"
    assert res.is_valid is False
    assert "decision" in res.error_message
