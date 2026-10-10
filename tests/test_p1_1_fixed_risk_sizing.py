import pytest
import random
from sizing import SizingCalculator, SizingResult


def test_fixed_risk_sizing_20_diverse_setups_within_10_percent_of_budget():
    """
    P1-1 Acceptance Test:
    Simulation of 20 diverse setups across varying prices ($0.005 to $200),
    volatilities (ATR giving SL from 1.5% to 5.5%), directions (LONG/SHORT),
    and contract precisions.
    Under fixed-risk sizing with a $2.00 budget:
    Every valid trade MUST have risk_amount_usdt within +-10% of the budget ($1.80 - $2.20).
    """
    risk_budget = 2.0  # $2.00 USDT risk budget per trade
    random.seed(42)

    prices_and_precisions = [
        (0.015, 0, 4),    # Micro meme, qty step 1, price prec 4
        (0.085, 0, 4),    # Low price meme, qty step 1, price prec 4
        (0.25, 1, 3),     # DOGE-like, qty step 0.1, price prec 3
        (1.50, 1, 2),     # Mid-range, qty step 0.1, price prec 2
        (8.50, 2, 2),     # Higher range, qty step 0.01, price prec 2
        (45.0, 3, 2),     # High price, qty step 0.001, price prec 2
        (120.0, 3, 1),    # Large price, qty step 0.001, price prec 1
    ]

    valid_trades_count = 0
    legacy_risks = []
    fixed_risks = []

    for i in range(20):
        base_price, qty_prec, price_prec = random.choice(prices_and_precisions)
        price_jitter = random.uniform(0.9, 1.1)
        entry_price = round(base_price * price_jitter, price_prec)
        direction = random.choice(["SHORT", "LONG"])
        # Volatility: SL between 1.5% and 5.5%
        target_sl_pct = random.uniform(1.5, 5.5)
        # ATR multiplier is 1.5, so atr = entry_price * (target_sl_pct / 100) / 1.5
        atr = entry_price * (target_sl_pct / 100.0) / 1.5

        contract_info = {
            "symbol": f"MOCK{i}-USDT",
            "quantityPrecision": qty_prec,
            "pricePrecision": price_prec,
            "tradeMinQuantity": str(10 ** (-qty_prec) if qty_prec > 0 else 1),
            "tradeMinUSDT": "5.0",
            "maxShortLeverage": 20,
            "maxLongLeverage": 20,
        }

        # 1. Legacy fixed-margin sizing ($5 margin, 20x lev)
        legacy_res = SizingCalculator.calculate_lot(
            symbol=f"MOCK{i}-USDT",
            margin_usdt=5.0,
            target_leverage=20,
            current_price=entry_price,
            contract_info=contract_info,
            max_allowed_leverage=20,
            direction=direction,
            atr=atr,
            target_rr=2.1
        )
        if legacy_res.is_valid:
            legacy_risks.append(legacy_res.risk_amount_usdt)

        # 2. Fixed-risk sizing ($2.00 target risk budget)
        fixed_res = SizingCalculator.calculate_fixed_risk_lot(
            symbol=f"MOCK{i}-USDT",
            risk_budget_usdt=risk_budget,
            target_leverage=20,
            current_price=entry_price,
            contract_info=contract_info,
            max_allowed_leverage=20,
            direction=direction,
            atr=atr,
            target_rr=2.1,
            max_margin_usdt=25.0
        )

        if fixed_res.is_valid:
            valid_trades_count += 1
            fixed_risks.append(fixed_res.risk_amount_usdt)
            # Risk must be strictly within +-10% of $2.00 ($1.80 to $2.20)
            rel_error = abs(fixed_res.risk_amount_usdt - risk_budget) / risk_budget
            assert rel_error <= 0.10, (
                f"Trade {i} risk ${fixed_res.risk_amount_usdt:.2f} deviates from budget ${risk_budget:.2f} "
                f"by {rel_error*100:.1f}% (>10%). Setup: entry={entry_price}, sl={fixed_res.stop_loss_price}, qty={fixed_res.quantity}"
            )

    # At least 15 valid trades out of 20
    assert valid_trades_count >= 15

    # Verification: Legacy risks varied widely (>1.8x spread)
    if len(legacy_risks) >= 10:
        legacy_ratio = max(legacy_risks) / min(legacy_risks)
        assert legacy_ratio >= 1.8, f"Legacy risk ratio was unexpectedly low: {legacy_ratio}"

    # Fixed risks stay tightly grouped
    fixed_ratio = max(fixed_risks) / min(fixed_risks)
    assert fixed_ratio <= 1.25, f"Fixed risk ratio spread {fixed_ratio:.2f} exceeded target 1.25"


def test_fixed_risk_sizing_rejects_when_stop_cannot_fit_budget():
    """When stop distance is so wide that min quantity risk exceeds budget by >10%, setup is rejected."""
    contract_info = {
        "symbol": "BTC-USDT",
        "quantityPrecision": 3,
        "pricePrecision": 1,
        "tradeMinQuantity": "0.01",  # Min qty 0.01
        "tradeMinUSDT": "10.0",
        "maxShortLeverage": 20,
    }
    # Price 60,000, min qty 0.01 -> min notional = 600 USDT.
    # If SL is 2.0% ($1200 distance), min qty 0.01 risk = 0.01 * 1200 = 12.0 USDT.
    # Risk budget is only $2.00 USDT. Min risk is 6x the budget!
    res = SizingCalculator.calculate_fixed_risk_lot(
        symbol="BTC-USDT",
        risk_budget_usdt=2.0,
        target_leverage=20,
        current_price=60000.0,
        contract_info=contract_info,
        direction="SHORT",
        atr=800.0,
        target_rr=2.0
    )
    assert res.is_valid is False
    assert "budget" in res.rejection_reason.lower() or "exceeds" in res.rejection_reason.lower()
