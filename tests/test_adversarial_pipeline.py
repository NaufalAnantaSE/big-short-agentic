"""Verifies the dialectical single deep evaluation panel replacing legacy multi-call adversarial loop."""

from ai_evaluator import AIEvaluator
from config import AppConfig


def test_dialectical_deep_evaluation_replaces_adversarial_loop(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    response_payload = {
        "choices": [{
            "message": {
                "content": (
                    '{"decision":"ENTER_SHORT","confidence":88,"setup_type":"PUMP_EXHAUSTION",'
                    '"bull_thesis":"Momentum still high","bear_thesis":"Extreme wick rejection on 15m",'
                    '"synthesis":"Bear exhaustion outweighs squeeze risk","key_evidence":"Wick + volume fade",'
                    '"risk_factors":"Low OI","invalidation_risk_present":false}'
                )
            }
        }],
        "usage": {"total_tokens": 380}
    }
    mock_resp = mocker.MagicMock(status_code=200, json=lambda: response_payload)
    mock_post = mocker.patch.object(evaluator.client, "post", return_value=mock_resp)

    result = evaluator.evaluate_deep_candidate({"symbol": "DOGE-USDT", "features": {"funding_rate": 0.001}}, direction="SHORT")

    assert result.is_valid is True
    assert result.decision == "ENTER_SHORT"
    assert result.confidence == 88
    assert result.usage.get("total_tokens") == 380
    # Verifies exactly 1 HTTP call instead of 3 legacy blocking calls!
    assert mock_post.call_count == 1
