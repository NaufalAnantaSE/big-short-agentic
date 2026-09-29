"""Deterministic lot sizing calculator using Python Decimal arithmetic."""

from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any, Tuple
from pydantic import BaseModel

class SizingResult(BaseModel):
    symbol: str
    target_margin: float
    effective_leverage: int
    entry_price: float
    notional_value: float
    quantity: float
    is_valid: bool
    rejection_reason: str = ""

class SizingError(Exception):
    pass

class SizingCalculator:
    @staticmethod
    def calculate_lot(
        symbol: str,
        margin_usdt: float,
        target_leverage: int,
        current_price: float,
        contract_info: Dict[str, Any],
        max_allowed_leverage: int = 20
    ) -> SizingResult:
        """
        Calculates exact order quantity according to exchange contract precision.
        Formula:
          effective_leverage = min(target_leverage, contract_max_leverage, max_allowed_leverage)
          notional = margin_usdt * effective_leverage
          raw_qty = notional / current_price
          qty = floor(raw_qty, quantityPrecision)
        """
        if margin_usdt <= 0:
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason="Margin input must be strictly positive (> 0)."
            )

        if current_price <= 0:
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason="Price must be strictly positive (> 0)."
            )

        # Exchange contract rules
        qty_precision = int(contract_info.get("quantityPrecision", 0))
        trade_min_qty = Decimal(str(contract_info.get("tradeMinQuantity", "0.0001")))
        trade_min_usdt = Decimal(str(contract_info.get("tradeMinUSDT", "5.0")))
        pair_max_leverage = int(contract_info.get("maxShortLeverage", max_allowed_leverage))

        effective_leverage = min(target_leverage, pair_max_leverage, max_allowed_leverage)
        if effective_leverage < 1:
            effective_leverage = 1

        d_margin = Decimal(str(margin_usdt))
        d_lev = Decimal(str(effective_leverage))
        d_price = Decimal(str(current_price))

        d_notional = d_margin * d_lev
        d_raw_qty = d_notional / d_price

        # Quantize to contract quantityPrecision using ROUND_DOWN (truncation)
        precision_step = Decimal("10") ** (-qty_precision) if qty_precision > 0 else Decimal("1")
        d_qty = d_raw_qty.quantize(precision_step, rounding=ROUND_DOWN)

        # Validate minimum exchange limits
        if d_qty < trade_min_qty:
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(d_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=f"Calculated quantity {d_qty} is below exchange tradeMinQuantity ({trade_min_qty})."
            )

        actual_notional = d_qty * d_price
        if actual_notional < trade_min_usdt:
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=f"Effective notional {actual_notional:.2f} USDT is below tradeMinUSDT ({trade_min_usdt} USDT)."
            )

        return SizingResult(
            symbol=symbol,
            target_margin=margin_usdt,
            effective_leverage=effective_leverage,
            entry_price=current_price,
            notional_value=float(actual_notional),
            quantity=float(d_qty),
            is_valid=True,
            rejection_reason=""
        )
