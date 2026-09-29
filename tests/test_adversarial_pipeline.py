from ai_evaluator import AIEvaluator
from config import AppConfig


def test_adversarial_panel_evaluates_short_squeeze_and_arbiter(mocker):
    config = AppConfig(ai_gateway_url="http://127.0.0.1:20128/v1")
    evaluator = AIEvaluator(config)

    responses = [
        {"choices": [{"message": {"content": '{"decision":"ENTER_SHORT","confidence":85,"setup_type":"PUMP_EXHAUSTION","key_evidence":"Wick + volume fade","risk_factors":"Low OI"}'}}], "usage": {"total_tokens": 120}},
        {"choices": [{"message": {"content": '{"decision":"WAIT","confidence":70,"setup_type":"NONE","key_evidence":"Breakout holding","risk_factors":"Funding crowded"}'}}], "usage": {"total_tokens": 110}},
        {"choices": [{"message": {"content": '{"decision":"ENTER_SHORT","confidence":88,"setup_type":"PUMP_EXHAUSTION","key_evidence":"Exhaustion outweighs squeeze","risk_factors":"Manageable"}'}}], "usage": {"total_tokens": 150}},
    ]
    mock_post = mocker.MagicMock(side_effect=[mocker.MagicMock(status_code=200, json=lambda r=resp: r) for resp in responses])
    mocker.patch.object(evaluator.client, "post", mock_post)

    result = evaluator.evaluate_adversarial({"symbol": "DOGE-USDT", "features": {"funding_rate": 0.001}})

    assert result.is_valid is True
    assert result.decision == "ENTER_SHORT"
    assert result.confidence == 88
    assert result.usage.get("total_tokens") == 380
    assert mock_post.call_count == 3
