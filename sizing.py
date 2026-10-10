"""Deterministic lot sizing calculator using Python Decimal arithmetic."""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, InvalidOperation
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
    # Real risk expressed as % of margin: sl_pct * leverage.
    # Conservative single-position heuristic / risk filter; note this is not
    # guaranteed cross-margin liquidation protection since exchange liquidation
    # depends on total account equity, maintenance margin tiers, and mark slippage.
    risk_pct_of_margin: float = 0.0

# Maximum allowed risk as % of margin. The 80% ceiling (not 100%) provides a
# conservative buffer for maintenance margin and mark-price deviation.
# Note: this is a local sizing heuristic, not guaranteed exchange liquidation protection.
MAX_RISK_PCT_OF_MARGIN = 80.0

# Minimum allowed Risk:Reward ratio guardrail
MIN_TARGET_RR = Decimal("2.0")

class SizingError(Exception):
    pass

def _validate_target_rr(target_rr: Any) -> Decimal:
    """Validates that target_rr is a finite numeric value >= 2.0."""
    if target_rr is None or isinstance(target_rr, bool):
        raise ValueError(f"Invalid target_rr: {target_rr}. Must be a finite number >= 2.0.")
    try:
        d_rr = Decimal(str(target_rr))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Invalid target_rr: {target_rr}. Must be a finite number >= 2.0.")

    if not d_rr.is_finite() or d_rr < MIN_TARGET_RR:
        raise ValueError(f"Invalid target_rr: {target_rr}. Must be a finite number >= 2.0.")
    return d_rr

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
        Raises:
            ValueError: If target_rr is invalid/nonfinite/<2.0, direction is invalid,
                        or calculated prices are non-positive / incorrectly oriented.
        """
        if entry_price <= 0:
            return 0.0, 0.0, 0.0, 0.0

        dir_norm = direction.upper()
        if dir_norm not in ("LONG", "SHORT"):
            raise ValueError(f"Invalid direction: {direction}. Must be 'LONG' or 'SHORT'.")

        d_rr = _validate_target_rr(target_rr)
        d_entry = Decimal(str(entry_price))

        d_min_sl = Decimal(str(min_sl_pct))
        d_max_sl = Decimal(str(max_sl_pct))
        if atr is not None and atr > 0:
            d_atr = Decimal(str(atr))
            d_mult = Decimal(str(atr_multiplier_sl))
            atr_pct = (d_atr * d_mult / d_entry) * Decimal("100")
            clamped_sl_pct = max(d_min_sl, min(d_max_sl, atr_pct))
        else:
            clamped_sl_pct = max(d_min_sl, min(d_max_sl, Decimal("3.0")))

        tp_pct_target = clamped_sl_pct * d_rr

        if dir_norm == "LONG":
            raw_sl = d_entry * (Decimal("1") - (clamped_sl_pct / Decimal("100")))
            raw_tp = d_entry * (Decimal("1") + (tp_pct_target / Decimal("100")))
        else:  # SHORT
            raw_sl = d_entry * (Decimal("1") + (clamped_sl_pct / Decimal("100")))
            raw_tp = d_entry * (Decimal("1") - (tp_pct_target / Decimal("100")))

        # Fail closed on non-positive raw SL/TP rather than silently stretching target
        if raw_sl <= Decimal("0") or raw_tp <= Decimal("0"):
            raise ValueError(
                f"Calculated raw SL ({raw_sl}) or TP ({raw_tp}) is non-positive for entry {entry_price}. "
                f"Sizing rejected."
            )

        price_precision = int(contract_info.get("pricePrecision", 4))
        p_step = Decimal("10") ** (-price_precision) if price_precision > 0 else Decimal("1")

        d_sl = raw_sl.quantize(p_step, rounding=ROUND_HALF_UP)
        d_tp = raw_tp.quantize(p_step, rounding=ROUND_HALF_UP)

        sl_price = float(d_sl)
        tp_price = float(d_tp)

        # Validate positivity and orientation after quantization
        if d_sl <= Decimal("0") or d_tp <= Decimal("0"):
            raise ValueError(f"Quantized SL ({d_sl}) or TP ({d_tp}) is non-positive.")

        if dir_norm == "LONG":
            if not (d_sl < d_entry < d_tp):
                raise ValueError(
                    f"Quantized SL/TP prices ({d_sl}, {d_tp}) incorrectly oriented for LONG at entry {d_entry}."
                )
            act_sl_pct = abs((d_entry - d_sl) / d_entry) * Decimal("100")
            act_tp_pct = abs((d_tp - d_entry) / d_entry) * Decimal("100")
        else:  # SHORT
            if not (d_tp < d_entry < d_sl):
                raise ValueError(
                    f"Quantized SL/TP prices ({d_sl}, {d_tp}) incorrectly oriented for SHORT at entry {d_entry}."
                )
            act_sl_pct = abs((d_sl - d_entry) / d_entry) * Decimal("100")
            act_tp_pct = abs((d_entry - d_tp) / d_entry) * Decimal("100")

        return sl_price, tp_price, round(float(act_sl_pct), 2), round(float(act_tp_pct), 2)

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
        risk_budget_usdt: Optional[float] = None,
    ) -> SizingResult:
        """
        Calculates exact order quantity according to exchange contract precision.
        If risk_budget_usdt is provided and > 0, delegates to fixed-risk sizing (P1-1).
        Formula:
          effective_leverage = min(target_leverage, contract_max_leverage, max_allowed_leverage)
          notional = margin_usdt * effective_leverage
          raw_qty = notional / current_price
          qty = floor(raw_qty, quantityPrecision)
        """
        if risk_budget_usdt is not None and risk_budget_usdt > 0:
            return SizingCalculator.calculate_fixed_risk_lot(
                symbol=symbol,
                risk_budget_usdt=risk_budget_usdt,
                target_leverage=target_leverage,
                current_price=current_price,
                contract_info=contract_info,
                max_allowed_leverage=max_allowed_leverage,
                direction=direction,
                atr=atr,
                target_rr=target_rr,
                atr_multiplier_sl=atr_multiplier_sl,
                max_margin_usdt=margin_usdt if margin_usdt > 0 else None,
            )

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

        # Validate target_rr upfront
        try:
            d_target_rr = _validate_target_rr(target_rr)
        except ValueError as e:
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason=f"Invalid target_rr: {target_rr}. Must be a finite number >= 2.0."
            )

        # Exchange contract rules
        dir_norm = direction.upper()
        if dir_norm not in ("LONG", "SHORT"):
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason=f"Invalid direction: {direction}. Must be 'LONG' or 'SHORT'."
            )

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

        try:
            sl_price, tp_price, sl_pct, tp_pct = SizingCalculator.calculate_dynamic_tpsl(
                symbol=symbol,
                direction=direction,
                entry_price=current_price,
                contract_info=contract_info,
                atr=atr,
                atr_multiplier_sl=atr_multiplier_sl,
                target_rr=float(d_target_rr)
            )
        except ValueError as e:
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=f"TP/SL calculation failed: {str(e)}",
                risk_reward_ratio=float(d_target_rr),
            )

        d_sl = Decimal(str(sl_price))
        d_tp = Decimal(str(tp_price))

        if d_sl <= Decimal("0") or d_tp <= Decimal("0"):
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason="Quantized SL/TP prices must be strictly positive (> 0).",
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                risk_reward_ratio=float(d_target_rr),
                sl_percent=sl_pct,
                tp_percent=tp_pct,
            )

        if dir_norm == "LONG":
            d_sl_dist = d_price - d_sl
            d_tp_dist = d_tp - d_price
            oriented = (d_sl < d_price < d_tp)
        else:  # SHORT
            d_sl_dist = d_sl - d_price
            d_tp_dist = d_price - d_tp
            oriented = (d_tp < d_price < d_sl)

        if not oriented or d_sl_dist <= Decimal("0") or d_tp_dist <= Decimal("0"):
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=f"Incorrectly oriented quantized SL/TP (SL: {sl_price}, TP: {tp_price}, entry: {current_price}) for {dir_norm}.",
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                risk_reward_ratio=float(d_target_rr),
                sl_percent=sl_pct,
                tp_percent=tp_pct,
            )

        effective_rr = d_tp_dist / d_sl_dist
        risk_usdt = float(actual_notional) * (sl_pct / 100.0)
        profit_usdt = float(actual_notional) * (tp_pct / 100.0)

        # Quantization guard: ensure quote-time effective RR >= 2.0.
        # Reject setup if quantization eroded RR below 2.0; do not widen TP just for profit.
        if effective_rr < MIN_TARGET_RR:
            return SizingResult(
                symbol=symbol,
                target_margin=margin_usdt,
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=(
                    f"Effective R:R {effective_rr:.4f} is below minimum 2.0 guardrail due to price quantization "
                    f"(SL: {sl_price}, TP: {tp_price}, entry: {current_price}). Widening TP is disallowed."
                ),
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                risk_reward_ratio=round(float(effective_rr), 4),
                risk_amount_usdt=round(risk_usdt, 2),
                potential_profit_usdt=round(profit_usdt, 2),
                sl_percent=sl_pct,
                tp_percent=tp_pct,
            )

        # Liquidation guard: conservative single-position heuristic (margin x leverage x sl_pct).
        # This acts as a pre-trade screening filter to reject setups where the stop-loss
        # is too wide for the chosen leverage. It is not guaranteed exchange liquidation
        # protection under cross-margin or extreme volatility.
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
                risk_reward_ratio=round(float(effective_rr), 4),
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
            risk_reward_ratio=round(float(effective_rr), 4),
            risk_amount_usdt=round(risk_usdt, 2),
            potential_profit_usdt=round(profit_usdt, 2),
            sl_percent=sl_pct,
            tp_percent=tp_pct,
            risk_pct_of_margin=risk_pct_of_margin,
        )

    @staticmethod
    def calculate_fixed_risk_lot(
        symbol: str,
        risk_budget_usdt: float,
        target_leverage: int,
        current_price: float,
        contract_info: Dict[str, Any],
        max_allowed_leverage: int = 20,
        direction: str = "SHORT",
        atr: Optional[float] = None,
        target_rr: float = 2.0,
        atr_multiplier_sl: float = 1.5,
        max_margin_usdt: Optional[float] = None,
        fee_buffer_pct: float = 0.10,
    ) -> SizingResult:
        """
        P1-1: Fixed-Risk Sizing Calculator.
        Determines quantity based on structural volatility risk:
          quantity = risk_budget / |entry - stop|
        Guarantees that risk_amount_usdt across diverse setups stays within +-10% of risk_budget.
        If exchange constraints (tradeMinQuantity, tradeMinUSDT, max_margin) cannot fit within
        the risk budget +-10%, the trade is rejected (fail-closed).
        """
        if risk_budget_usdt <= 0:
            return SizingResult(
                symbol=symbol,
                target_margin=0.0,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason="Risk budget must be strictly positive (> 0)."
            )

        if current_price <= 0:
            return SizingResult(
                symbol=symbol,
                target_margin=0.0,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason="Price must be strictly positive (> 0)."
            )

        try:
            d_target_rr = _validate_target_rr(target_rr)
        except ValueError as e:
            return SizingResult(
                symbol=symbol,
                target_margin=0.0,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason=f"Invalid target_rr: {target_rr}. Must be a finite number >= 2.0."
            )

        dir_norm = direction.upper()
        if dir_norm not in ("LONG", "SHORT"):
            return SizingResult(
                symbol=symbol,
                target_margin=0.0,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason=f"Invalid direction: {direction}. Must be 'LONG' or 'SHORT'."
            )

        # 1. Determine Stop-Loss and Take-Profit FIRST from volatility/structure
        try:
            sl_price, tp_price, sl_pct, tp_pct = SizingCalculator.calculate_dynamic_tpsl(
                symbol=symbol,
                direction=direction,
                entry_price=current_price,
                contract_info=contract_info,
                atr=atr,
                atr_multiplier_sl=atr_multiplier_sl,
                target_rr=float(d_target_rr)
            )
        except ValueError as e:
            return SizingResult(
                symbol=symbol,
                target_margin=0.0,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason=f"TP/SL calculation failed: {str(e)}",
                risk_reward_ratio=float(d_target_rr),
            )

        d_entry = Decimal(str(current_price))
        d_sl = Decimal(str(sl_price))
        d_tp = Decimal(str(tp_price))
        d_stop_dist = abs(d_entry - d_sl)

        if d_stop_dist <= Decimal("0"):
            return SizingResult(
                symbol=symbol,
                target_margin=0.0,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=0.0,
                quantity=0.0,
                is_valid=False,
                rejection_reason="Stop-loss distance must be strictly positive."
            )

        d_unit_risk = d_stop_dist
        d_risk_budget = Decimal(str(risk_budget_usdt))

        # 2. Derive raw quantity from fixed risk budget
        raw_qty = d_risk_budget / d_unit_risk

        qty_precision = int(contract_info.get("quantityPrecision", 0))
        trade_min_qty = Decimal(str(contract_info.get("tradeMinQuantity", "0.0001")))
        trade_min_usdt = Decimal(str(contract_info.get("tradeMinUSDT", "5.0")))
        lev_key = "maxLongLeverage" if dir_norm == "LONG" else "maxShortLeverage"
        pair_max_leverage = int(contract_info.get(lev_key, max_allowed_leverage))

        precision_step = Decimal("10") ** (-qty_precision) if qty_precision > 0 else Decimal("1")
        qty_round = raw_qty.quantize(precision_step, rounding=ROUND_HALF_UP)
        qty_down = raw_qty.quantize(precision_step, rounding=ROUND_DOWN)

        candidates = [q for q in (qty_round, qty_down) if q >= trade_min_qty]
        if not candidates:
            min_risk = trade_min_qty * d_unit_risk
            if abs(min_risk - d_risk_budget) / d_risk_budget <= Decimal("0.10"):
                d_qty = trade_min_qty
            else:
                return SizingResult(
                    symbol=symbol,
                    target_margin=0.0,
                    effective_leverage=0,
                    entry_price=current_price,
                    notional_value=0.0,
                    quantity=0.0,
                    is_valid=False,
                    rejection_reason=(
                        f"Exchange tradeMinQuantity {trade_min_qty} risk ({min_risk:.2f} USDT) "
                        f"exceeds risk budget ({d_risk_budget:.2f} USDT) by >10%."
                    )
                )
        else:
            d_qty = min(candidates, key=lambda q: abs(q * d_unit_risk - d_risk_budget))

        actual_risk = d_qty * d_unit_risk
        risk_deviation = abs(actual_risk - d_risk_budget) / d_risk_budget
        if risk_deviation > Decimal("0.10"):
            return SizingResult(
                symbol=symbol,
                target_margin=0.0,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=float(d_qty * d_entry),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=(
                    f"Quantized risk {actual_risk:.2f} USDT deviates from budget {d_risk_budget:.2f} USDT by "
                    f"{risk_deviation*100:.1f}% (>10%)."
                )
            )

        actual_notional = d_qty * d_entry
        if actual_notional < trade_min_usdt:
            return SizingResult(
                symbol=symbol,
                target_margin=0.0,
                effective_leverage=0,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=f"Effective notional {actual_notional:.2f} USDT is below tradeMinUSDT ({trade_min_usdt} USDT)."
            )

        # 3. Dynamic leverage adjustment for liquidation safety
        max_safe_lev = int(Decimal(str(MAX_RISK_PCT_OF_MARGIN)) / Decimal(str(sl_pct))) if sl_pct > 0 else max_allowed_leverage
        effective_leverage = min(target_leverage, pair_max_leverage, max_allowed_leverage, max_safe_lev)
        if effective_leverage < 1:
            effective_leverage = 1

        required_margin = actual_notional / Decimal(str(effective_leverage))
        if max_margin_usdt is not None and required_margin > Decimal(str(max_margin_usdt)):
            highest_safe_lev = min(pair_max_leverage, max_allowed_leverage, max_safe_lev)
            lowest_possible_margin = actual_notional / Decimal(str(highest_safe_lev))
            if lowest_possible_margin <= Decimal(str(max_margin_usdt)):
                effective_leverage = highest_safe_lev
                required_margin = lowest_possible_margin
            else:
                return SizingResult(
                    symbol=symbol,
                    target_margin=float(required_margin),
                    effective_leverage=effective_leverage,
                    entry_price=current_price,
                    notional_value=float(actual_notional),
                    quantity=float(d_qty),
                    is_valid=False,
                    rejection_reason=(
                        f"Required margin {required_margin:.2f} USDT exceeds max_margin_usdt ({max_margin_usdt:.2f} USDT)."
                    )
                )

        if dir_norm == "LONG":
            d_sl_dist = d_entry - d_sl
            d_tp_dist = d_tp - d_entry
            oriented = (d_sl < d_entry < d_tp)
        else:
            d_sl_dist = d_sl - d_entry
            d_tp_dist = d_entry - d_tp
            oriented = (d_tp < d_entry < d_sl)

        if not oriented or d_sl_dist <= Decimal("0") or d_tp_dist <= Decimal("0"):
            return SizingResult(
                symbol=symbol,
                target_margin=float(required_margin),
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=f"Incorrectly oriented quantized SL/TP (SL: {sl_price}, TP: {tp_price}, entry: {current_price}) for {dir_norm}."
            )

        effective_rr = d_tp_dist / d_sl_dist
        if effective_rr < MIN_TARGET_RR:
            return SizingResult(
                symbol=symbol,
                target_margin=float(required_margin),
                effective_leverage=effective_leverage,
                entry_price=current_price,
                notional_value=float(actual_notional),
                quantity=float(d_qty),
                is_valid=False,
                rejection_reason=f"Effective R:R {effective_rr:.4f} is below minimum 2.0 guardrail."
            )

        risk_pct_of_margin = round(sl_pct * effective_leverage, 2)
        profit_usdt = float(d_qty * d_tp_dist)

        return SizingResult(
            symbol=symbol,
            target_margin=round(float(required_margin), 4),
            effective_leverage=effective_leverage,
            entry_price=current_price,
            notional_value=float(actual_notional),
            quantity=float(d_qty),
            is_valid=True,
            rejection_reason="",
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            risk_reward_ratio=round(float(effective_rr), 4),
            risk_amount_usdt=round(float(actual_risk), 2),
            potential_profit_usdt=round(profit_usdt, 2),
            sl_percent=sl_pct,
            tp_percent=tp_pct,
            risk_pct_of_margin=risk_pct_of_margin,
        )
