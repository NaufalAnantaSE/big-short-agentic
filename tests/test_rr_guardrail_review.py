"""Tests for minimum R:R 2.0 guardrail in sizing.py.

Verifies:
1. Rejection of invalid, nonfinite, or below-2.0 target_rr (ValueError in calculate_dynamic_tpsl, is_valid=False in calculate_lot).
2. Positive and correctly oriented quantized SL/TP for LONG and SHORT.
3. Quote-time effective RR >= 2.0 requirement and rejection of quantization losing min RR without TP widening.
4. Acceptance of standard target_rr=2.0 and target_rr=2.5 with precision-safe decimals.
"""

import math
import pytest
from sizing import SizingCalculator


def test_calculate_dynamic_tpsl_rejects_sub2_target_rr():
    contract_info = {"pricePrecision": 4, "quantityPrecision": 2}
    for sub2_rr in [1.5, 1.99, 1.0, 0.0, -0.5, -2.0]:
        with pytest.raises(ValueError, match="target_rr"):
            SizingCalculator.calculate_dynamic_tpsl(
                symbol="BTC-USDT",
                direction="SHORT",
                entry_price=100.0,
                contract_info=contract_info,
                target_rr=sub2_rr
            )

        with pytest.raises(ValueError, match="target_rr"):
            SizingCalculator.calculate_dynamic_tpsl(
                symbol="BTC-USDT",
                direction="LONG",
                entry_price=100.0,
                contract_info=contract_info,
                target_rr=sub2_rr
            )


def test_calculate_dynamic_tpsl_rejects_nonfinite_and_invalid_target_rr():
    contract_info = {"pricePrecision": 4, "quantityPrecision": 2}
    for bad_rr in [float("nan"), float("inf"), float("-inf"), None, "invalid", True, False]:
        with pytest.raises(ValueError, match="target_rr"):
            SizingCalculator.calculate_dynamic_tpsl(
                symbol="BTC-USDT",
                direction="SHORT",
                entry_price=100.0,
                contract_info=contract_info,
                target_rr=bad_rr
            )


def test_calculate_lot_rejects_sub2_and_nonfinite_target_rr():
    contract_info = {
        "pricePrecision": 4,
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20,
        "maxLongLeverage": 20,
    }
    for bad_rr in [1.5, 1.99, float("nan"), float("inf"), float("-inf"), -1.0, None, "bad"]:
        res_short = SizingCalculator.calculate_lot(
            symbol="TEST-USDT",
            margin_usdt=10.0,
            target_leverage=10,
            current_price=100.0,
            contract_info=contract_info,
            direction="SHORT",
            target_rr=bad_rr
        )
        assert res_short.is_valid is False
        assert "target_rr" in res_short.rejection_reason.lower() or "r:r" in res_short.rejection_reason.lower()

        res_long = SizingCalculator.calculate_lot(
            symbol="TEST-USDT",
            margin_usdt=10.0,
            target_leverage=10,
            current_price=100.0,
            contract_info=contract_info,
            direction="LONG",
            target_rr=bad_rr
        )
        assert res_long.is_valid is False
        assert "target_rr" in res_long.rejection_reason.lower() or "r:r" in res_long.rejection_reason.lower()


def test_positive_correctly_oriented_quantized_sl_tp_long():
    contract_info = {
        "pricePrecision": 4,
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxLongLeverage": 20,
    }
    res = SizingCalculator.calculate_lot(
        symbol="LONG-USDT",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=100.0,
        contract_info=contract_info,
        direction="LONG",
        atr=2.0,  # 3.0% SL
        target_rr=2.0
    )
    assert res.is_valid is True
    assert res.stop_loss_price is not None
    assert res.take_profit_price is not None
    assert 0 < res.stop_loss_price < 100.0
    assert res.take_profit_price > 100.0
    assert res.risk_reward_ratio >= 2.0


def test_positive_correctly_oriented_quantized_sl_tp_short():
    contract_info = {
        "pricePrecision": 4,
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20,
    }
    res = SizingCalculator.calculate_lot(
        symbol="SHORT-USDT",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=100.0,
        contract_info=contract_info,
        direction="SHORT",
        atr=2.0,  # 3.0% SL
        target_rr=2.0
    )
    assert res.is_valid is True
    assert res.stop_loss_price is not None
    assert res.take_profit_price is not None
    assert res.stop_loss_price > 100.0
    assert 0 < res.take_profit_price < 100.0
    assert res.risk_reward_ratio >= 2.0


def test_rejects_nonpositive_tp_or_sl_without_silent_stretching():
    contract_info = {
        "pricePrecision": 4,
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20,
    }
    # For SHORT: if target_rr * sl_pct >= 100%, raw TP is <= 0.
    # Sizing calculator must NOT silently clamp to entry * 0.90!
    with pytest.raises(ValueError):
        SizingCalculator.calculate_dynamic_tpsl(
            symbol="CRASH-USDT",
            direction="SHORT",
            entry_price=10.0,
            contract_info=contract_info,
            target_rr=20.0,
            min_sl_pct=6.0,
            max_sl_pct=6.0  # 6% * 20 = 120% target -> TP = 10 * (1 - 1.2) = -2.0 <= 0
        )

    res = SizingCalculator.calculate_lot(
        symbol="CRASH-USDT",
        margin_usdt=10.0,
        target_leverage=5,
        current_price=10.0,
        contract_info=contract_info,
        direction="SHORT",
        target_rr=20.0,
        atr=10.0  # clamp to 6% SL -> 120% TP
    )
    assert res.is_valid is False
    assert bool(res.rejection_reason)
    assert len(res.rejection_reason) > 0


def test_quantization_losing_min_rr_rejected_without_tp_widening_short():
    # Coarse price precision (1 decimal):
    # entry = 10.0, SL raw = 1.5% -> 10.15 -> quantized 10.2 (SL dist = 0.2, 2.0%)
    # TP raw = 3.0% (target_rr=2.0) -> 9.70 -> quantized 9.7 (TP dist = 0.3, 3.0%)
    # Effective RR = 0.3 / 0.2 = 1.5 < 2.0!
    contract_info = {
        "pricePrecision": 1,
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20,
    }
    res = SizingCalculator.calculate_lot(
        symbol="COARSE-USDT",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=10.0,
        contract_info=contract_info,
        direction="SHORT",
        atr=0.1,  # 0.1 * 1.5 / 10 * 100 = 1.5% SL
        target_rr=2.0
    )
    assert res.is_valid is False
    assert "r:r" in res.rejection_reason.lower() or "quantization" in res.rejection_reason.lower()
    # Ensure TP was NOT widened to 9.6 just to force 2.0 RR:
    assert res.take_profit_price == 9.7
    assert res.stop_loss_price == 10.2


def test_quantization_losing_min_rr_rejected_without_tp_widening_long():
    # Coarse price precision (1 decimal) for LONG:
    # entry = 10.0, atr chosen so sl_pct = 2.6%:
    # raw SL = 10.0 * (1 - 0.026) = 9.74 -> quantized 9.7 (SL dist = 0.3)
    # raw TP = 10.0 * (1 + 0.052) = 10.52 -> quantized 10.5 (TP dist = 0.5)
    # Effective RR = 0.5 / 0.3 = 1.6667 < 2.0!
    contract_info = {
        "pricePrecision": 1,
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxLongLeverage": 20,
    }
    # atr * 1.5 / 10 * 100 = 2.6 => atr = 2.6 * 10 / 150 = 0.17333333333333334
    res = SizingCalculator.calculate_lot(
        symbol="COARSE-LONG",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=10.0,
        contract_info=contract_info,
        direction="LONG",
        atr=0.17333333333333334,
        target_rr=2.0
    )
    assert res.is_valid is False
    assert "r:r" in res.rejection_reason.lower() or "quantization" in res.rejection_reason.lower()
    # Ensure TP was NOT widened to 10.6 just to force 2.0 RR:
    assert res.take_profit_price == 10.5
    assert res.stop_loss_price == 9.7


def test_quantization_boundary_effective_rr_exact_2_and_above():
    contract_info = {
        "pricePrecision": 2,
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20,
        "maxLongLeverage": 20,
    }
    # Exactly 2.0 effective RR:
    # entry = 10.0, atr = 0.1 -> sl_pct = 1.5% -> SL 10.15 (dist 0.15), TP 9.70 (dist 0.30)
    # 0.30 / 0.15 = 2.00
    res = SizingCalculator.calculate_lot(
        symbol="EXACT-USDT",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=10.0,
        contract_info=contract_info,
        direction="SHORT",
        atr=0.1,
        target_rr=2.0
    )
    assert res.is_valid is True
    assert res.stop_loss_price == 10.15
    assert res.take_profit_price == 9.70
    assert res.risk_reward_ratio == 2.0


def test_usual_target_rr_2_and_2_5():
    contract_info = {
        "pricePrecision": 4,
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20,
        "maxLongLeverage": 20,
    }
    # 2.0 target on SHORT
    res_2_short = SizingCalculator.calculate_lot(
        symbol="USUAL-SHORT",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=50.0,
        contract_info=contract_info,
        direction="SHORT",
        target_rr=2.0
    )
    assert res_2_short.is_valid is True
    assert res_2_short.risk_reward_ratio >= 2.0

    # 2.5 target on SHORT (Pump Exhaustion playbook)
    res_25_short = SizingCalculator.calculate_lot(
        symbol="USUAL-SHORT",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=50.0,
        contract_info=contract_info,
        direction="SHORT",
        target_rr=2.5
    )
    assert res_25_short.is_valid is True
    assert res_25_short.risk_reward_ratio >= 2.5

    # 2.0 target on LONG
    res_2_long = SizingCalculator.calculate_lot(
        symbol="USUAL-LONG",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=50.0,
        contract_info=contract_info,
        direction="LONG",
        target_rr=2.0
    )
    assert res_2_long.is_valid is True
    assert res_2_long.risk_reward_ratio >= 2.0

    # 2.5 target on LONG
    res_25_long = SizingCalculator.calculate_lot(
        symbol="USUAL-LONG",
        margin_usdt=10.0,
        target_leverage=10,
        current_price=50.0,
        contract_info=contract_info,
        direction="LONG",
        target_rr=2.5
    )
    assert res_25_long.is_valid is True
    assert res_25_long.risk_reward_ratio >= 2.5
