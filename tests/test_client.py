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
