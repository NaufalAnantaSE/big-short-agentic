"""Deterministic lot sizing calculator using Python Decimal arithmetic."""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Dict, Any, Tuple, Optional
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
    # Phase 1: Automated TP/SL & Risk Management
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    risk_reward_ratio: float = 2.0
    risk_amount_usdt: float = 0.0
    potential_profit_usdt: float = 0.0
    sl_percent: float = 0.0
    tp_percent: float = 0.0
    # Real risk expressed as % of margin: sl_pct * leverage. If this exceeds
    # the margin (minus a maintenance buffer), the position is liquidated
    # BEFORE the stop-loss can trigger.
    risk_pct_of_margin: float = 0.0

# Maximum allowed risk as % of margin. The 80% ceiling (not 100%) leaves a
# buffer for maintenance margin / mark-price deviation so the stop-loss has
# room to trigger before liquidation.
MAX_RISK_PCT_OF_MARGIN = 80.0

class SizingError(Exception):
    pass

class SizingCalculator:
    @staticmethod
    def calculate_dynamic_tpsl(
        symbol: str,
        direction: str,
        entry_price: float,
        contract_info: Dict[str, Any],
        atr: Optional[float] = None,
        atr_multiplier_sl: float = 1.5,
        target_rr: float = 2.0,
        min_sl_pct: float = 1.5,
        max_sl_pct: float = 6.0,
    ) -> Tuple[float, float, float, float]:
        """
        Calculates dynamic Stop-Loss and Take-Profit prices quantized to contract pricePrecision.
        Returns:
            (sl_price, tp_price, actual_sl_pct, actual_tp_pct)
        """
        if entry_price <= 0:
            return 0.0, 0.0, 0.0, 0.0

        dir_norm = direction.upper()
        if atr is not None and atr > 0:
            atr_pct = (atr * atr_multiplier_sl / entry_price) * 100.0
            clamped_sl_pct = max(min_sl_pct, min(max_sl_pct, atr_pct))
        else:
            clamped_sl_pct = 3.0

        tp_pct_target = clamped_sl_pct * max(1.0, target_rr)

        if dir_norm == "LONG":
            raw_sl = entry_price * (1.0 - (clamped_sl_pct / 100.0))
            raw_tp = entry_price * (1.0 + (tp_pct_target / 100.0))
            if raw_sl <= 0:
                raw_sl = entry_price * 0.95
        else:  # SHORT
            raw_sl = entry_price * (1.0 + (clamped_sl_pct / 100.0))
            raw_tp = entry_price * (1.0 - (tp_pct_target / 100.0))
            if raw_tp <= 0:
                raw_tp = entry_price * 0.90

        price_precision = int(contract_info.get("pricePrecision", 4))
        p_step = Decimal("10") ** (-price_precision) if price_precision > 0 else Decimal("1")

        d_sl = Decimal(str(raw_sl)).quantize(p_step, rounding=ROUND_HALF_UP)
        d_tp = Decimal(str(raw_tp)).quantize(p_step, rounding=ROUND_HALF_UP)

        sl_price = float(d_sl)
        tp_price = float(d_tp)

        if dir_norm == "LONG":
            act_sl_pct = abs((entry_price - sl_price) / entry_price) * 100.0
            act_tp_pct = abs((tp_price - entry_price) / entry_price) * 100.0
        else:
            act_sl_pct = abs((sl_price - entry_price) / entry_price) * 100.0
            act_tp_pct = abs((entry_price - tp_price) / entry_price) * 100.0

        return sl_price, tp_price, round(act_sl_pct, 2), round(act_tp_pct, 2)

    @staticmethod
    def calculate_lot(
        symbol: str,
        margin_usdt: float,
        target_leverage: int,
        current_price: float,
        contract_info: Dict[str, Any],
        max_allowed_leverage: int = 20,
        direction: str = "SHORT",
        atr: Optional[float] = None,
        target_rr: float = 2.0,
        atr_multiplier_sl: float = 1.5,
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
        dir_norm = direction.upper()
        qty_precision = int(contract_info.get("quantityPrecision", 0))
        trade_min_qty = Decimal(str(contract_info.get("tradeMinQuantity", "0.0001")))
        trade_min_usdt = Decimal(str(contract_info.get("tradeMinUSDT", "5.0")))
        lev_key = "maxLongLeverage" if dir_norm == "LONG" else "maxShortLeverage"
        pair_max_leverage = int(contract_info.get(lev_key, max_allowed_leverage))

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

        sl_price, tp_price, sl_pct, tp_pct = SizingCalculator.calculate_dynamic_tpsl(
            symbol=symbol,
            direction=direction,
            entry_price=current_price,
            contract_info=contract_info,
            atr=atr,
            atr_multiplier_sl=atr_multiplier_sl,
            target_rr=target_rr
        )

        risk_usdt = float(actual_notional) * (sl_pct / 100.0)
        profit_usdt = float(actual_notional) * (tp_pct / 100.0)

        # Liquidation guard: real risk = margin x leverage x sl_pct. If this
        # exceeds the margin (minus buffer), the position is liquidated BEFORE
        # the stop-loss triggers, making the TP/SL risk model meaningless.
        # Fail closed: reject the setup with an actionable reason.
        risk_pct_of_margin = round(sl_pct * effective_leverage, 2)
        if risk_pct_of_margin > MAX_RISK_PCT_OF_MARGIN:
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=(
                    f"Liquidation risk: SL {sl_pct:.2f}% x {effective_leverage}x leverage = "
                    f"{risk_pct_of_margin:.1f}% of margin (limit {MAX_RISK_PCT_OF_MARGIN:.0f}%). "
                    f"Position would be liquidated before the stop-loss is hit. "
                    f"Reduce leverage or tighten the stop-loss."
                ),
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                risk_reward_ratio=target_rr,
                risk_amount_usdt=round(risk_usdt, 2),
                potential_profit_usdt=round(profit_usdt, 2),
                sl_percent=sl_pct,
                tp_percent=tp_pct,
                risk_pct_of_margin=risk_pct_of_margin,
            )

        return SizingResult(
            symbol=symbol,
            target_margin=margin_usdt,
            effective_leverage=effective_leverage,
            entry_price=current_price,
            notional_value=float(actual_notional),
            quantity=float(d_qty),
            is_valid=True,
            rejection_reason="",
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            risk_reward_ratio=target_rr,
            risk_amount_usdt=round(risk_usdt, 2),
            potential_profit_usdt=round(profit_usdt, 2),
            sl_percent=sl_pct,
            tp_percent=tp_pct,
            risk_pct_of_margin=risk_pct_of_margin,
        )
