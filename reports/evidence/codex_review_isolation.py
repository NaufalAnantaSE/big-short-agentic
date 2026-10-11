import httpx
import config

def blocked_network(*args, **kwargs):
    raise RuntimeError("REVIEW: outbound network blocked")
httpx.HTTPTransport.handle_request = blocked_network
httpx.AsyncHTTPTransport.handle_async_request = blocked_network
config.load_config = lambda: config.AppConfig(api_key="mock_review", secret_key="mock_review")
