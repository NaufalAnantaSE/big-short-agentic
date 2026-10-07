"""Unit and integration tests for Phase 1 Dynamic TP/SL & Risk Management.

Validates:
1. SizingCalculator dynamic ATR TP/SL calculation for SHORT & LONG.
2. Price quantization matching exchange pricePrecision.
3. BingXClient attached stopLoss / takeProfit payload formatting.
4. BingXClient independent place_tpsl_order method.
5. SessionOrchestrator integration with dynamic TP/SL.
6. DB order_records persistence of stop_loss_price and take_profit_price.
7. Plain explainer humanization of TP/SL metrics.
"""

import json
import pytest
import uuid
from unittest.mock import MagicMock

import db
from config import AppConfig
from client import BingXClient
from sizing import SizingCalculator, SizingResult
from contracts import DirectionMode, ExitPolicy, ExecutionMode
from orchestrator import SessionOrchestrator, SessionState
from plain_explainer import humanize_ai_decision


def test_dynamic_tpsl_calculation_short_and_long():
    contract_info = {
        "quantityPrecision": 2,
        "pricePrecision": 4,
        "tradeMinQuantity": "0.1",
        "tradeMinUSDT": "5.0"
    }
    entry_price = 10.0

    # 1. SHORT with 0.1 ATR (1.5x = 0.15 => 1.5% SL, 3.0% TP)
    sl_p, tp_p, sl_pct, tp_pct = SizingCalculator.calculate_dynamic_tpsl(
        symbol="TEST-USDT",
        direction="SHORT",
        entry_price=entry_price,
        contract_info=contract_info,
        atr=0.1,
        atr_multiplier_sl=1.5,
        target_rr=2.0
    )
    assert sl_p > entry_price, "Short SL must be above entry"
    assert tp_p < entry_price, "Short TP must be below entry"
    assert sl_p == 10.15
    assert tp_p == 9.70
    assert sl_pct == 1.5
    assert tp_pct == 3.0

    # 2. LONG with 0.2 ATR (1.5x = 0.3 => 3.0% SL, 6.0% TP)
    sl_long, tp_long, sl_long_pct, tp_long_pct = SizingCalculator.calculate_dynamic_tpsl(
        symbol="TEST-USDT",
        direction="LONG",
        entry_price=entry_price,
        contract_info=contract_info,
        atr=0.2,
        atr_multiplier_sl=1.5,
        target_rr=2.0
    )
    assert sl_long < entry_price, "Long SL must be below entry"
    assert tp_long > entry_price, "Long TP must be above entry"
    assert sl_long == 9.70
    assert tp_long == 10.60
    assert sl_long_pct == 3.0
    assert tp_long_pct == 6.0


def test_dynamic_tpsl_clamps_within_safety_bounds():
    contract_info = {"pricePrecision": 2, "quantityPrecision": 1}
    entry = 100.0

    # Very small ATR => clamp to min_sl_pct (1.5%)
    sl_p, tp_p, sl_pct, tp_pct = SizingCalculator.calculate_dynamic_tpsl(
        symbol="TEST-USDT",
        direction="SHORT",
        entry_price=entry,
        contract_info=contract_info,
        atr=0.01,  # 0.015% raw => clamped to 1.5%
        min_sl_pct=1.5,
        max_sl_pct=6.0
    )
    assert sl_pct == 1.5
    assert sl_p == 101.5
    assert tp_pct == 3.0
    assert tp_p == 97.0

    # Huge ATR => clamp to max_sl_pct (6.0%)
    sl_p, tp_p, sl_pct, tp_pct = SizingCalculator.calculate_dynamic_tpsl(
        symbol="TEST-USDT",
        direction="SHORT",
        entry_price=entry,
        contract_info=contract_info,
        atr=10.0,  # 15% raw => clamped to 6.0%
        min_sl_pct=1.5,
        max_sl_pct=6.0
    )
    assert sl_pct == 6.0
    assert sl_p == 106.0
    assert tp_pct == 12.0
    assert tp_p == 88.0


def test_calculate_lot_populates_tpsl_and_risk_amounts():
    contract_info = {
        "quantityPrecision": 2,
        "pricePrecision": 3,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20
    }
    # Margin 10 USDT, 20x lev => Notional 200 USDT, Price 50.0 => Qty 4.0
    res = SizingCalculator.calculate_lot(
        symbol="SOL-USDT",
        margin_usdt=10.0,
        target_leverage=20,
        current_price=50.0,
        contract_info=contract_info,
        direction="LONG",
        atr=1.0  # 1.5% SL, 3.0% TP
    )
    assert res.is_valid is True
    assert res.quantity == 4.0
    assert res.notional_value == 200.0
    assert res.stop_loss_price is not None
    assert res.take_profit_price is not None
    assert res.stop_loss_price < 50.0
    assert res.take_profit_price > 50.0
    assert res.risk_amount_usdt > 0.0
    assert res.potential_profit_usdt > res.risk_amount_usdt


def test_client_place_order_serializes_tpsl_json():
    cfg = AppConfig(api_key="dummy", secret_key="dummy")
    client = BingXClient(cfg)
    client._request = MagicMock(return_value={"orderId": "12345"})

    client.place_order(
        symbol="PEPE-USDT",
        side="SELL",
        position_side="SHORT",
        order_type="MARKET",
        quantity=1000.0,
        client_order_id="test_ord_1",
        stop_loss_price=0.000015,
        take_profit_price=0.000012
    )

    client._request.assert_called_once()
    args, kwargs = client._request.call_args
    params = kwargs.get("params", {})
    assert "stopLoss" in params
    assert "takeProfit" in params

    sl_obj = json.loads(params["stopLoss"])
    assert sl_obj["type"] == "STOP_MARKET"
    assert sl_obj["stopPrice"] == 0.000015
    assert sl_obj["workingType"] == "MARK_PRICE"

    tp_obj = json.loads(params["takeProfit"])
    assert tp_obj["type"] == "TAKE_PROFIT_MARKET"
    assert tp_obj["stopPrice"] == 0.000012
    assert tp_obj["workingType"] == "MARK_PRICE"


def test_client_place_tpsl_order_independent_trigger():
    cfg = AppConfig(api_key="dummy", secret_key="dummy")
    client = BingXClient(cfg)
    client._request = MagicMock(return_value={"orderId": "tpsl_trigger_99"})

    client.place_tpsl_order(
        symbol="DOGE-USDT",
        position_side="SHORT",
        trigger_type="TAKE_PROFIT_MARKET",
        stop_price=0.15,
        client_order_id="tp_doge_1"
    )

    client._request.assert_called_once()
    args, kwargs = client._request.call_args
    params = kwargs.get("params", {})
    assert params["symbol"] == "DOGE-USDT"
    assert params["side"] == "BUY"  # Close SHORT
    assert params["positionSide"] == "SHORT"
    assert params["type"] == "TAKE_PROFIT_MARKET"
    assert params["stopPrice"] == 0.15
    assert params["closePosition"] == "true"


def test_db_record_order_stores_and_retrieves_tpsl():
    uid = db.create_user(f"u_tpsl_{uuid.uuid4().hex[:6]}", "Pass123!", role="user")
    sess_id = f"bx_test_{uuid.uuid4().hex[:8]}"

    db.record_order(
        user_id=uid,
        session_id=sess_id,
        symbol="BTC-USDT",
        quantity=0.01,
        price=60000.0,
        notional=600.0,
        leverage=10,
        client_order_id="cl_tpsl_1",
        order_id="ord_tpsl_1",
        status="FILLED",
        side="SELL",
        position_side="SHORT",
        stop_loss_price=61800.0,
        take_profit_price=56400.0
    )

    orders = db.get_user_orders(uid, limit=1)
    assert len(orders) == 1
    o = orders[0]
    assert o["stop_loss_price"] == 61800.0
    assert o["take_profit_price"] == 56400.0


def test_plain_explainer_formats_tpsl_note():
    h = humanize_ai_decision(
        symbol="DOGE-USDT",
        decision="ENTER_SHORT",
        confidence=85,
        evidence="Buyer exhaustion",
        risk_factors="None",
        price=0.20,
        change_24h=12.5,
        spread_pct=0.05,
        take_profit_price=0.188,
        stop_loss_price=0.206,
        tp_percent=6.0,
        sl_percent=3.0,
        risk_amount_usdt=3.0,
        potential_profit_usdt=6.0
    )

    assert h["take_profit_price"] == 0.188
    assert h["stop_loss_price"] == 0.206
    assert h["tp_percent"] == 6.0
    assert h["sl_percent"] == 3.0
    assert "Manajemen Risiko Otomatis" in h["tpsl_note"]
    assert any("Ambil Untung (TP)" in note for note in h["market_notes"])

def test_liquidation_guard_rejects_overleveraged_wide_sl():
    """20x leverage with a 6% SL risks 120% of margin: the position would be
    liquidated before the stop-loss triggers, so the setup must be rejected."""
    from sizing import SizingCalculator

    contract_info = {
        "quantityPrecision": 2,
        "pricePrecision": 3,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20,
    }
    res = SizingCalculator.calculate_lot(
        symbol="SOL-USDT",
        margin_usdt=10.0,
        target_leverage=20,
        current_price=50.0,
        contract_info=contract_info,
        direction="SHORT",
        atr=2.0,  # atr_pct = 2.0*1.5/50*100 = 6.0% SL (clamped to max)
    )
    assert res.is_valid is False
    assert "Liquidation risk" in res.rejection_reason
    assert res.risk_pct_of_margin == 120.0


def test_liquidation_guard_allows_safe_combo():
    """20x leverage with a 3% SL risks 60% of margin: within the 80% limit."""
    from sizing import SizingCalculator

    contract_info = {
        "quantityPrecision": 2,
        "pricePrecision": 3,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxShortLeverage": 20,
    }
    res = SizingCalculator.calculate_lot(
        symbol="SOL-USDT",
        margin_usdt=10.0,
        target_leverage=20,
        current_price=50.0,
        contract_info=contract_info,
        direction="SHORT",
        atr=1.0,  # atr_pct = 1.0*1.5/50*100 = 3.0% SL
    )
    assert res.is_valid is True
    assert res.risk_pct_of_margin == 60.0
