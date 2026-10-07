"""Native BingX REST Client with HMAC-SHA256 authentication and error handling."""

import hmac
import hashlib
import time
import json
import httpx
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from config import AppConfig

class BingXAPIError(Exception):
    def __init__(self, code: int, msg: str, response: Optional[httpx.Response] = None):
        super().__init__(f"BingX API Error [{code}]: {msg}")
        self.code = code
        self.msg = msg
        self.response = response

class BingXClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.base_url = config.bingx_host.rstrip("/")
        self.client = httpx.Client(timeout=10.0)

    @staticmethod
    def _build_query_string(params: Dict[str, Any]) -> str:
        """Builds a URL-encoded query string with keys sorted alphabetically.

        The exact string returned here is both signed (HMAC-SHA256) and sent
        over the wire, so the signature always matches the transmitted bytes.
        Manual f-string interpolation must NOT be used: values such as the
        JSON-encoded stopLoss/takeProfit payloads contain spaces, quotes and
        braces that are illegal in a URL and would break the signature.
        """
        sorted_items = sorted(params.items(), key=lambda kv: kv[0])
        return urlencode([(k, v) for k, v in sorted_items])

    @staticmethod
    def sign_params(params: Dict[str, Any], secret_key: str) -> str:
        """Sorts parameters alphabetically, URL-encodes the query string, and generates HMAC-SHA256 hex digest."""
        query_str = BingXClient._build_query_string(params)
        return hmac.new(
            secret_key.encode("utf-8"),
            query_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        req_params = dict(params or {})
        headers = {}

        if self.config.api_key:
            headers["X-BX-APIKEY"] = self.config.api_key

        if signed:
            if not self.config.secret_key:
                raise ValueError("Secret key is required for signed requests.")
            req_params["timestamp"] = int(time.time() * 1000)
            req_params["recvWindow"] = 10000
            
            # Build the URL-encoded query string once; the signature is computed
            # over this exact string and the same string is transmitted, so the
            # signature always matches the bytes the server receives.
            query_str = self._build_query_string(req_params)
            signature = hmac.new(
                self.config.secret_key.encode("utf-8"),
                query_str.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

            final_url = f"{url}?{query_str}&signature={signature}"
            send_params = None
        else:
            final_url = url
            send_params = req_params if req_params else None

        try:
            resp = self.client.request(method, final_url, params=send_params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise BingXAPIError(-1, f"HTTP transport error: {str(e)}") from e

        code = data.get("code", 0)
        if code != 0:
            msg = data.get("msg", "Unknown error")
            raise BingXAPIError(code, msg, response=resp)

        return data.get("data", {})

    # ==================== Account & Position Queries ====================

    def get_balance(self) -> Any:
        """Queries asset balance and equity via V3 endpoint."""
        return self._request("GET", "/openApi/swap/v3/user/balance", signed=True)

    def get_position_mode(self) -> Dict[str, Any]:
        """Queries whether account is in Dual-Side (Hedge) Mode or One-Way Mode."""
        return self._request("GET", "/openApi/swap/v1/positionSide/dual", signed=True)

    def get_positions(self, symbol: Optional[str] = None) -> list:
        """Queries open positions. Returns list of position dictionaries."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        res = self._request("GET", "/openApi/swap/v2/user/positions", params=params, signed=True)
        return res if isinstance(res, list) else []

    def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """Queries pending orders. Returns list of order dictionaries."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        res = self._request("GET", "/openApi/swap/v2/trade/openOrders", params=params, signed=True)
        orders = res.get("orders", []) if isinstance(res, dict) else res
        return orders if isinstance(orders, list) else []

    def get_leverage(self, symbol: str) -> Dict[str, Any]:
        """Queries current leverage and max available leverage for symbol."""
        return self._request("GET", "/openApi/swap/v2/trade/leverage", params={"symbol": symbol}, signed=True)

    def set_leverage(self, symbol: str, leverage: int, side: str = "SHORT") -> Dict[str, Any]:
        """Sets leverage for a specific symbol and position side."""
        params = {"symbol": symbol, "side": side, "leverage": leverage}
        return self._request("POST", "/openApi/swap/v2/trade/leverage", params=params, signed=True)

    # ==================== Market Data Queries ====================

    def get_contracts(self) -> list:
        """Queries all perpetual swap contracts and their trading rules."""
        res = self._request("GET", "/openApi/swap/v2/quote/contracts", signed=False)
        return res if isinstance(res, list) else []

    def get_tickers(self) -> list:
        """Queries 24h ticker data for all contracts."""
        res = self._request("GET", "/openApi/swap/v2/quote/ticker", signed=False)
        return res if isinstance(res, list) else []

    def get_depth(self, symbol: str, limit: int = 5) -> Dict[str, Any]:
        """Queries orderbook depth."""
        return self._request("GET", "/openApi/swap/v2/quote/depth", params={"symbol": symbol, "limit": limit}, signed=False)

    def get_klines(self, symbol: str, interval: str = "15m", limit: int = 30) -> list:
        """Queries historical OHLCV klines."""
        res = self._request("GET", "/openApi/swap/v3/quote/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, signed=False)
        return res if isinstance(res, list) else []

    # ==================== Execution Endpoint ====================

    def place_order(
        self,
        symbol: str,
        side: str,
        position_side: str,
        order_type: str,
        quantity: float,
        client_order_id: str,
        price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Submits an order to BingX Swap V2 with optional attached Stop Loss / Take Profit.
        Enforces proper side and position_side pairing for Hedge mode.
        """
        norm_side = side.upper()
        norm_pos_side = position_side.upper()
        if norm_pos_side == "SHORT" and norm_side != "SELL":
            raise ValueError(f"Invalid order pairing: To open SHORT, side must be SELL (got side='{side}', position_side='{position_side}')")
        if norm_pos_side == "LONG" and norm_side != "BUY":
            raise ValueError(f"Invalid order pairing: To open LONG, side must be BUY (got side='{side}', position_side='{position_side}')")
        if norm_pos_side not in ("SHORT", "LONG", "BOTH"):
            raise ValueError(f"Invalid position_side: '{position_side}'")

        params = {
            "symbol": symbol,
            "side": norm_side,
            "positionSide": norm_pos_side,
            "type": order_type,
            "quantity": quantity,
            "clientOrderId": client_order_id.lower()[:40],
        }
        if price is not None:
            params["price"] = price

        if stop_loss_price is not None:
            params["stopLoss"] = json.dumps({
                "type": "STOP_MARKET",
                "stopPrice": float(stop_loss_price),
                "workingType": "MARK_PRICE"
            })
        if take_profit_price is not None:
            params["takeProfit"] = json.dumps({
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": float(take_profit_price),
                "workingType": "MARK_PRICE"
            })

        return self._request("POST", "/openApi/swap/v2/trade/order", params=params, signed=True)

    def place_tpsl_order(
        self,
        symbol: str,
        position_side: str,
        trigger_type: str,
        stop_price: float,
        client_order_id: str,
        working_type: str = "MARK_PRICE",
        quantity: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Submits an independent position-level Stop Loss or Take Profit trigger order in Hedge mode.
        For SHORT position: side='BUY'
        For LONG position: side='SELL'
        """
        norm_pos_side = position_side.upper()
        if norm_pos_side not in ("SHORT", "LONG"):
            raise ValueError(f"Invalid position_side for TP/SL trigger: '{position_side}'")

        order_side = "BUY" if norm_pos_side == "SHORT" else "SELL"
        trigger_norm = trigger_type.upper()
        if trigger_norm not in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            raise ValueError(f"Invalid trigger_type: '{trigger_type}'. Must be STOP_MARKET or TAKE_PROFIT_MARKET.")

        params = {
            "symbol": symbol,
            "side": order_side,
            "positionSide": norm_pos_side,
            "type": trigger_norm,
            "stopPrice": float(stop_price),
            "workingType": working_type,
            "clientOrderId": client_order_id.lower()[:40],
            "closePosition": "true",
        }
        if quantity is not None and quantity > 0:
            params["quantity"] = quantity
            params["reduceOnly"] = "true"

        return self._request("POST", "/openApi/swap/v2/trade/order", params=params, signed=True)

    def close_position(
        self,
        symbol: str,
        position_side: str,
        quantity: float,
        client_order_id: str
    ) -> Dict[str, Any]:
        """
        Closes an open position in Hedge Mode.
        For SHORT position: side='BUY', positionSide='SHORT', type='MARKET'
        For LONG position: side='SELL', positionSide='LONG', type='MARKET'
        """
        close_side = "BUY" if position_side.upper() == "SHORT" else "SELL"
        params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": position_side.upper(),
            "type": "MARKET",
            "quantity": abs(quantity),
            "clientOrderId": client_order_id.lower()[:40],
        }
        return self._request("POST", "/openApi/swap/v2/trade/order", params=params, signed=True)
