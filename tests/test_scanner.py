"""Unit tests for coexistence filter and market scanner logic."""

import pytest
from scanner import MarketScanner
from client import BingXClient
from config import AppConfig

def test_coexistence_exclusion(mocker):
    config = AppConfig(api_key="mock", secret_key="mock")
    client = BingXClient(config)
    scanner = MarketScanner(client, config)

    # Mock user having an active position on DOGE-USDT and a pending order on SHIB-USDT
    mocker.patch.object(client, "get_positions", return_value=[
        {"symbol": "DOGE-USDT", "positionAmt": "500", "side": "BUY"}
    ])
    mocker.patch.object(client, "get_open_orders", return_value=[
        {"symbol": "1000SHIB-USDT", "orderId": "123"}
    ])

    occupied = scanner.get_occupied_symbols()
    assert "DOGE-USDT" in occupied
    assert "1000SHIB-USDT" in occupied
    assert "1000PEPE-USDT" not in occupied

    # Mock contracts list including DOGE, 1000SHIB, and 1000PEPE
    mocker.patch.object(client, "get_contracts", return_value=[
        {"symbol": "DOGE-USDT", "apiStateOpen": "true"},
        {"symbol": "1000SHIB-USDT", "apiStateOpen": "true"},
        {"symbol": "1000PEPE-USDT", "apiStateOpen": "true"},
        {"symbol": "BTC-USDT", "apiStateOpen": "true"}  # Not a meme coin
    ])
    mocker.patch.object(client, "get_tickers", return_value=[
        {"symbol": "1000PEPE-USDT", "lastPrice": "0.008", "priceChangePercent": "12.5", "volume": "10000000", "bidPrice": "0.00799", "askPrice": "0.00800"}
    ])

    candidates = scanner.scan_memecoins()
    candidate_symbols = [c.symbol for c in candidates]

    # DOGE-USDT and 1000SHIB-USDT MUST be excluded due to active positions/orders
    assert "DOGE-USDT" not in candidate_symbols
    assert "1000SHIB-USDT" not in candidate_symbols
    # BTC-USDT must be excluded because it's not a memecoin
    assert "BTC-USDT" not in candidate_symbols
    # 1000PEPE-USDT should be included
    assert "1000PEPE-USDT" in candidate_symbols

def test_spread_filter(mocker):
    config = AppConfig(api_key="mock", secret_key="mock", max_spread_pct=0.25)
    client = BingXClient(config)
    scanner = MarketScanner(client, config)

    mocker.patch.object(scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(client, "get_contracts", return_value=[
        {"symbol": "WIF-USDT", "apiStateOpen": "true"}
    ])
    # Spread: (2.05 - 2.00) / 2.00 = 2.5% > 0.25%
    mocker.patch.object(client, "get_tickers", return_value=[
        {"symbol": "WIF-USDT", "lastPrice": "2.0", "priceChangePercent": "5.0", "volume": "500000", "bidPrice": "2.00", "askPrice": "2.05"}
    ])

    candidates = scanner.scan_memecoins()
    assert len(candidates) == 0

def test_pump_gainers_universe_mode(mocker):
    config = AppConfig(
        api_key="mock",
        secret_key="mock",
        universe_mode="PUMP_GAINERS",
        min_pump_percent=5.0,
        min_volume_24h_usdt=50000.0,
        max_spread_pct=0.25
    )
    client = BingXClient(config)
    scanner = MarketScanner(client, config)

    mocker.patch.object(scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(client, "get_contracts", return_value=[
        {"symbol": "BTC-USDT", "apiStateOpen": "true"},            # Major -> must exclude
        {"symbol": "NCFXEUR2USD-USDT", "apiStateOpen": "true"},    # Forex NC -> must exclude
        {"symbol": "ONDO-USDT", "apiStateOpen": "true"},           # Altcoin Pumper (+15%) -> include
        {"symbol": "LINK-USDT", "apiStateOpen": "true"},           # Altcoin Minor (+2%) -> below 5% -> exclude
        {"symbol": "PENDLE-USDT", "apiStateOpen": "true"},         # Altcoin Pumper (+25%) -> include
    ])
    mocker.patch.object(client, "get_tickers", return_value=[
        {"symbol": "BTC-USDT", "lastPrice": "65000", "priceChangePercent": "20.0", "volume": "1000", "bidPrice": "65000", "askPrice": "65010"},
        {"symbol": "NCFXEUR2USD-USDT", "lastPrice": "1.08", "priceChangePercent": "30.0", "volume": "1000000", "bidPrice": "1.08", "askPrice": "1.0801"},
        {"symbol": "ONDO-USDT", "lastPrice": "0.50", "priceChangePercent": "15.0", "volume": "500000", "bidPrice": "0.4999", "askPrice": "0.5001"},
        {"symbol": "LINK-USDT", "lastPrice": "12.0", "priceChangePercent": "2.0", "volume": "500000", "bidPrice": "11.99", "askPrice": "12.01"},
        {"symbol": "PENDLE-USDT", "lastPrice": "3.00", "priceChangePercent": "25.0", "volume": "500000", "bidPrice": "2.999", "askPrice": "3.001"},
    ])

    candidates = scanner.scan_universe(mode="PUMP_GAINERS")
    candidate_symbols = [c.symbol for c in candidates]

    # BTC and Forex NC excluded
    assert "BTC-USDT" not in candidate_symbols
    assert "NCFXEUR2USD-USDT" not in candidate_symbols
    # LINK excluded because +2% < min 5%
    assert "LINK-USDT" not in candidate_symbols
    # ONDO and PENDLE included
    assert "ONDO-USDT" in candidate_symbols
    assert "PENDLE-USDT" in candidate_symbols
    # Sorted by pump gain desc: PENDLE (+25%) should be first, ONDO (+15%) second
    assert candidate_symbols[0] == "PENDLE-USDT"
    assert candidate_symbols[1] == "ONDO-USDT"
