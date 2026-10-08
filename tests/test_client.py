"""Unit tests for BingX API signing and client mechanics."""

import pytest
from client import BingXClient
from config import AppConfig

def test_signature_generation():
    params = {
        "symbol": "1000PEPE-USDT",
        "side": "SELL",
        "positionSide": "SHORT",
        "timestamp": 1727500000000,
        "recvWindow": 10000
    }
    secret = "test_secret_key_12345"
    sig = BingXClient.sign_params(params, secret)
    assert isinstance(sig, str)
    assert len(sig) == 64
    # Idempotent signature
    assert sig == BingXClient.sign_params(params, secret)

def test_signature_sort_order():
    params1 = {"b": 2, "a": 1, "c": 3}
    params2 = {"c": 3, "b": 2, "a": 1}
    secret = "secret"
    # Both parameter dicts should produce the exact same signature regardless of initial insertion order
    assert BingXClient.sign_params(params1, secret) == BingXClient.sign_params(params2, secret)

def test_client_order_id_formatting(mocker):
    config = AppConfig(api_key="mock_key", secret_key="mock_secret")
    client = BingXClient(config)
    mock_post = mocker.patch.object(client, "_request", return_value={"orderId": 12345})
    
    long_upper_id = "BX_SHORT_ORDER_IDENTIFIER_THAT_IS_EXTREMELY_LONG_OVER_40_CHARACTERS"
    client.place_order(
        symbol="DOGE-USDT",
        side="SELL",
        position_side="SHORT",
        order_type="MARKET",
        quantity=100.0,
        client_order_id=long_upper_id
    )
    
    # Assert clientOrderId was converted to lowercase and truncated to <= 40 chars
    called_params = mock_post.call_args[1]["params"]
    assert called_params["clientOrderId"] == long_upper_id.lower()[:40]
    assert len(called_params["clientOrderId"]) <= 40
    assert called_params["clientOrderId"].islower()

def test_signed_request_urlencodes_tpsl_json(mocker):
    """Regression test: TP/SL JSON payloads must be URL-encoded in the signed
    query string. Previously the raw JSON (spaces, quotes, braces) was pasted
    into the URL, producing an illegal request URL and a signature that did
    not match the transmitted bytes."""
    import hashlib
    import hmac as hmaclib
    import json as jsonlib
    from urllib.parse import parse_qsl

    config = AppConfig(api_key="mock_key", secret_key="mock_secret")
    client = BingXClient(config)
    captured = {}

    def fake_request(method, url, params=None, headers=None):
        captured["method"] = method
        captured["url"] = url

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"code": 0, "data": {"orderId": 1}}

        return Resp()

    mocker.patch.object(client.client, "request", side_effect=fake_request)

    client.place_order(
        symbol="DOGE-USDT",
        side="SELL",
        position_side="SHORT",
        order_type="MARKET",
        quantity=100.0,
        client_order_id="test123",
        stop_loss_price=0.21,
        take_profit_price=0.18,
    )

    url = captured["url"]
    assert "?" in url
    query = url.split("?", 1)[1]
    # No illegal characters may appear raw in the transmitted query string
    for ch in (" ", "{", "}", '"', "<", ">"):
        assert ch not in query, f"illegal character {ch!r} in signed URL query"
    encoded_query, sig = query.rsplit("&signature=", 1)
    # stopLoss/takeProfit must round-trip as valid JSON after decoding
    params = dict(parse_qsl(encoded_query))
    assert jsonlib.loads(params["stopLoss"])["type"] == "STOP_MARKET"
    assert jsonlib.loads(params["takeProfit"])["type"] == "TAKE_PROFIT_MARKET"
    assert " " not in params["stopLoss"], "stopLoss JSON must be compact without spaces"
    assert " " not in params["takeProfit"], "takeProfit JSON must be compact without spaces"
    # Per BingX spec: signature is generated from unencoded raw parameter string
    expected = BingXClient.sign_params(params, "mock_secret")
    assert sig == expected
