import pytest
from client import BingXClient


@pytest.fixture(autouse=True)
def mock_bingx_network_for_unit_tests(monkeypatch, request):
    """
    Prevents unit tests with dummy/mock credentials from making unmocked network calls
    to external BingX endpoints.
    Live integration tests (e.g. test_live_vst) using load_config() with real keys are exempt.
    """
    if "test_live_vst" in request.node.nodeid:
        return

    orig_request = BingXClient._request

    def safe_mock_request(self, method, url, params=None, signed=False):
        api_key = getattr(self.config, "api_key", "")
        if api_key and (api_key == "mock" or api_key.startswith("mock") or api_key.startswith("test_")):
            if "/openApi/swap/v2/user/positions" in url:
                return []
            if "/openApi/swap/v2/trade/openOrders" in url:
                return []
            if "/openApi/swap/v2/quote/depth" in url:
                return {}
            if "/openApi/swap/v2/quote/contracts" in url:
                return []
            if "/openApi/swap/v3/quote/klines" in url:
                return []
        return orig_request(self, method, url, params=params, signed=signed)

    monkeypatch.setattr(BingXClient, "_request", safe_mock_request)
