"""Unit tests for deterministic Decimal lot sizing and precision."""

import pytest
from sizing import SizingCalculator

def test_standard_sizing_calculation():
    # Target margin $5, leverage 20x -> Notional $100
    # Price $0.008, contract precision 0 (integer lot)
    contract_info = {
        "quantityPrecision": 0,
        "tradeMinQuantity": "1",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 50
    }
    res = SizingCalculator.calculate_lot(
        symbol="1000PEPE-USDT",
        margin_usdt=5.0,
        target_leverage=20,
        current_price=0.008,
        contract_info=contract_info,
        max_allowed_leverage=20
    )
    assert res.is_valid is True
    assert res.effective_leverage == 20
    assert res.quantity == 12500.0  # 100 / 0.008 = 12500
    assert res.notional_value == 100.0

def test_leverage_capping():
    # Pair only supports 10x leverage, but user requested 20x -> Effective leverage should clamp to 10x
    contract_info = {
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.1",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 10
    }
    res = SizingCalculator.calculate_lot(
        symbol="LOWLEV-USDT",
        margin_usdt=5.0,
        target_leverage=20,
        current_price=2.0,
        contract_info=contract_info,
        max_allowed_leverage=20
    )
    assert res.effective_leverage == 10
    # Notional = 5 * 10 = 50. Qty = 50 / 2 = 25.0
    assert res.quantity == 25.0
    assert res.is_valid is True

def test_truncation_not_rounding_up():
    # 5.0 * 20 = 100. Price = 3.0. 100 / 3 = 33.3333...
    # quantityPrecision = 1.
    # Must be 33.3 (truncated down), NEVER 33.4
    contract_info = {
        "quantityPrecision": 1,
        "tradeMinQuantity": "0.1",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 50
    }
    res = SizingCalculator.calculate_lot(
        symbol="TEST-USDT",
        margin_usdt=5.0,
        target_leverage=20,
        current_price=3.0,
        contract_info=contract_info
    )
    assert res.quantity == 33.3
    assert res.is_valid is True

def test_rejection_below_min_quantity():
    # If calculated lot is below tradeMinQuantity, fail-closed without modifying margin
    contract_info = {
        "quantityPrecision": 4,
        "tradeMinQuantity": "100.0",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20
    }
    res = SizingCalculator.calculate_lot(
        symbol="HIGHMIN-USDT",
        margin_usdt=1.0,
        target_leverage=5,
        current_price=10.0,
        contract_info=contract_info
    )
    assert res.is_valid is False
    assert "below exchange tradeMinQuantity" in res.rejection_reason

def test_rejection_invalid_inputs():
    contract_info = {"quantityPrecision": 2, "tradeMinQuantity": "1", "tradeMinUSDT": "5"}
    assert SizingCalculator.calculate_lot("DOGE-USDT", -5.0, 10, 0.1, contract_info).is_valid is False
    assert SizingCalculator.calculate_lot("DOGE-USDT", 5.0, 10, 0.0, contract_info).is_valid is False
