"""
F-07 Acceptance Tests: End-to-end production exit reconciliation.

Verifies:
1. Production path (reconcile_outcomes / run_cycle) records closed trade fills directly into order_records.
2. Exchange timestamp (time in ms -> ISO8601 UTC) is used for exit_time, NOT local call time.
3. exit_price, exit_reason, exit_fee, funding_fee, realized_pnl, and realized_r match exchange ledger.
4. Idempotency: Re-polling with same events produces no duplicates and does not alter closed records.
5. Restart: Restarting the orchestrator with rehydrated state produces zero duplicate records.
6. Unknown data remains unknown: If exchange order history lacks closing order, exit_price is None and exit_reason is 'UNKNOWN' (no fabrication).
"""
import time
import uuid
from datetime import datetime, timezone
import pytest

from config import AppConfig
from orchestrator import SessionOrchestrator
import db


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / f"test_{uuid.uuid4().hex}.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()


def test_e2e_production_exit_reconciliation_take_profit(mocker):
    """
    Production path trigger: reconcile_outcomes() attributes closed Take Profit fill
    to order_records using exchange timestamp and fees, with verified idempotency.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["PEPE-USDT"]

    client_order_id = "bx_short_test_f07_tp_01"
    entry_ts_ms = 1700000000000  # 2023-11-14T22:13:20Z

    # 1. Entry record in database
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="PEPE-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=1000.0,
        price=10.0,
        notional=10000.0,
        effective_leverage=10,
        client_order_id=client_order_id,
        order_id="ord_entry_101",
        status="FILLED",
        stop_loss_price=10.5,
        take_profit_price=9.0,
        quote_ts=entry_ts_ms,
        request_price=10.0,
        avg_fill_price=10.0,
        entry_fee=-0.05
    )

    exit_ts_ms = 1700000005000  # 2023-11-14T22:13:25Z
    expected_exit_time_iso = datetime.fromtimestamp(exit_ts_ms / 1000.0, tz=timezone.utc).isoformat()

    mock_incomes = [
        {
            "incomeId": "inc_pnl_101",
            "symbol": "PEPE-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "1000.0",
            "time": exit_ts_ms
        },
        {
            "incomeId": "inc_fee_101",
            "symbol": "PEPE-USDT",
            "incomeType": "TRADING_FEE",
            "income": "-0.05",
            "time": exit_ts_ms
        },
        {
            "incomeId": "inc_funding_101",
            "symbol": "PEPE-USDT",
            "incomeType": "FUNDING_FEE",
            "income": "0.10",
            "time": entry_ts_ms + 2000
        }
    ]

    mock_orders = [
        {
            "orderId": "ord_tp_exit_201",
            "symbol": "PEPE-USDT",
            "side": "BUY",
            "positionSide": "SHORT",
            "type": "TAKE_PROFIT_MARKET",
            "status": "FILLED",
            "avgPrice": "9.0",
            "price": "0.0",
            "time": exit_ts_ms,
            "updateTime": exit_ts_ms
        }
    ]

    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", return_value=mock_orders)

    # Trigger exit reconciliation through production path
    ok = orch.reconcile_outcomes()
    assert ok is True

    # Verify order_records row in DB
    attr = db.get_closed_trade_attribution(client_order_id)
    assert attr is not None
    assert attr["exit_time"] == expected_exit_time_iso
    assert attr["exit_reason"] == "TAKE_PROFIT"
    assert attr["exit_price"] == pytest.approx(9.0)
    assert attr["exit_fee"] == pytest.approx(-0.05)
    assert attr["funding_fee"] == pytest.approx(0.10)
    # Net PnL = 1000.0 gross + -0.05 entry + -0.05 exit + 0.10 funding = 1000.0
    assert attr["realized_pnl"] == pytest.approx(1000.0)
    # Risk 1R = |10.0 - 10.5| * 1000 = 500.0 USDT. Realized R = 1000.0 / 500.0 = +2.0 R
    assert attr["realized_r"] == pytest.approx(2.0, 0.001)

    # Verify idempotency on re-polling
    prev_daily_pnl = session.daily_realized_pnl
    orch.reconcile_outcomes()
    assert session.daily_realized_pnl == prev_daily_pnl
    attr_recheck = db.get_closed_trade_attribution(client_order_id)
    assert attr_recheck is not None
    assert attr_recheck["realized_r"] == pytest.approx(2.0, 0.001)

    # Verify idempotency on simulated restart
    new_orch = SessionOrchestrator(config)
    new_orch.current_session = orch.current_session
    mocker.patch.object(new_orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(new_orch.client, "get_all_orders", return_value=mock_orders)
    new_orch.reconcile_outcomes()
    assert new_orch.current_session is not None
    assert new_orch.current_session.daily_realized_pnl == prev_daily_pnl


def test_e2e_production_exit_reconciliation_stop_loss(mocker):
    """Verify production exit reconciliation when closing order is STOP_MARKET (-1.0 R)."""
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["DOGE-USDT"]

    client_order_id = "bx_short_test_f07_sl_02"
    entry_ts_ms = 1700000010000

    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="DOGE-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=500.0,
        price=0.20,
        notional=100.0,
        effective_leverage=10,
        client_order_id=client_order_id,
        order_id="ord_entry_102",
        status="FILLED",
        stop_loss_price=0.21,
        take_profit_price=0.18,
        quote_ts=entry_ts_ms,
        request_price=0.20,
        avg_fill_price=0.20,
        entry_fee=-0.05
    )

    exit_ts_ms = 1700000020000
    mock_incomes = [
        {
            "incomeId": "inc_pnl_102",
            "symbol": "DOGE-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "-5.0",
            "time": exit_ts_ms
        },
        {
            "incomeId": "inc_fee_102",
            "symbol": "DOGE-USDT",
            "incomeType": "TRADING_FEE",
            "income": "-0.05",
            "time": exit_ts_ms
        }
    ]

    mock_orders = [
        {
            "orderId": "ord_sl_exit_202",
            "symbol": "DOGE-USDT",
            "side": "BUY",
            "positionSide": "SHORT",
            "type": "STOP_MARKET",
            "status": "FILLED",
            "avgPrice": "0.21",
            "time": exit_ts_ms,
            "updateTime": exit_ts_ms
        }
    ]

    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", return_value=mock_orders)

    orch.reconcile_outcomes()

    attr = db.get_closed_trade_attribution(client_order_id)
    assert attr is not None
    assert attr["exit_reason"] == "STOP_LOSS"
    assert attr["exit_price"] == pytest.approx(0.21)
    # Risk 1R = |0.20 - 0.21| * 500 = 5.0 USDT. Net PnL = -5.0 + -0.05 + -0.05 = -5.10
    # Realized R = -5.10 / 5.0 = -1.02 R
    assert attr["realized_r"] == pytest.approx(-1.02, 0.001)


def test_e2e_production_exit_unknown_no_fabrication(mocker):
    """
    If exchange order history does not return the closing order,
    exit_price must be None and exit_reason must be 'UNKNOWN' (no fabrication).
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["SHIB-USDT"]

    client_order_id = "bx_short_test_f07_unknown_03"
    entry_ts_ms = 1700000030000

    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="SHIB-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=10000.0,
        price=0.000010,
        notional=100.0,
        effective_leverage=10,
        client_order_id=client_order_id,
        order_id="ord_entry_103",
        status="FILLED",
        stop_loss_price=0.000011,
        take_profit_price=0.000008,
        quote_ts=entry_ts_ms,
        request_price=0.000010,
        avg_fill_price=0.000010,
        entry_fee=0.0
    )

    exit_ts_ms = 1700000040000
    mock_incomes = [
        {
            "incomeId": "inc_pnl_103",
            "symbol": "SHIB-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "20.0",
            "time": exit_ts_ms
        }
    ]

    # Empty order history from exchange
    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", return_value=[])

    orch.reconcile_outcomes()

    attr = db.get_closed_trade_attribution(client_order_id)
    assert attr is not None
    assert attr["exit_price"] is None  # Strictly None, NOT fallback to entry price
    assert attr["exit_reason"] == "UNKNOWN"
    assert attr["realized_pnl"] == pytest.approx(20.0)


def test_f07_reconciliation_fifo_multiple_orders_same_symbol(mocker):
    """
    Test 1: Multiple orders on same symbol with different timestamps.
    Income at T_close_1 must match Order 1 (quote_ts <= T_close_1).
    Order 2 (quote_ts > T_close_1) MUST NOT be attributed to the earlier exit.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["PEPE-USDT"]

    t1_ms = 1700000010000
    t_exit1_ms = 1700000020000
    t2_ms = 1700000030000
    t_exit2_ms = 1700000040000

    # Order 1 entered at t1
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="PEPE-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=100.0,
        price=10.0,
        notional=1000.0,
        effective_leverage=10,
        client_order_id="cl_pepe_order_1",
        order_id="ord_p1",
        status="FILLED",
        stop_loss_price=10.5,
        take_profit_price=9.0,
        quote_ts=t1_ms,
        request_price=10.0,
        avg_fill_price=10.0,
        entry_fee=0.0
    )

    # Order 2 entered later at t2 (re-entry)
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="PEPE-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=100.0,
        price=10.0,
        notional=1000.0,
        effective_leverage=10,
        client_order_id="cl_pepe_order_2",
        order_id="ord_p2",
        status="FILLED",
        stop_loss_price=10.5,
        take_profit_price=9.0,
        quote_ts=t2_ms,
        request_price=10.0,
        avg_fill_price=10.0,
        entry_fee=0.0
    )

    # First income arrives for exit 1 at t_exit1 (between t1 and t2)
    mock_incomes_1 = [
        {
            "incomeId": "inc_pepe_1",
            "symbol": "PEPE-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "50.0",
            "time": t_exit1_ms
        }
    ]
    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes_1)
    mocker.patch.object(orch.client, "get_all_orders", return_value=[])

    orch.reconcile_outcomes()

    # Order 1 must be closed, Order 2 MUST remain open!
    attr_1 = db.get_closed_trade_attribution("cl_pepe_order_1")
    attr_2 = db.get_closed_trade_attribution("cl_pepe_order_2")

    assert attr_1 is not None
    assert attr_1["exit_time"] is not None
    assert attr_1["realized_pnl"] == pytest.approx(50.0)

    assert attr_2 is not None
    assert attr_2["exit_time"] is None  # Still OPEN!

    # Second income arrives for exit 2 at t_exit2
    mock_incomes_2 = [
        mock_incomes_1[0],
        {
            "incomeId": "inc_pepe_2",
            "symbol": "PEPE-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "80.0",
            "time": t_exit2_ms
        }
    ]
    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes_2)
    orch.reconcile_outcomes()

    attr_2_after = db.get_closed_trade_attribution("cl_pepe_order_2")
    assert attr_2_after is not None
    assert attr_2_after["exit_time"] is not None
    assert attr_2_after["realized_pnl"] == pytest.approx(80.0)


def test_f07_reconciliation_qty_match_multiple_orders(mocker):
    """
    Test 2: Multiple open orders with different quantities.
    Closing fill with executedQty = 250 must match the order with quantity = 250,
    even if another order was opened earlier.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["W-USDT"]

    t0_ms = 1700000000000
    exit_ms = 1700000010000

    # Order A entered first with qty 100.0
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="W-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=100.0,
        price=1.0,
        notional=100.0,
        effective_leverage=10,
        client_order_id="cl_w_qty100",
        order_id="ord_w1",
        status="FILLED",
        stop_loss_price=1.05,
        take_profit_price=0.90,
        quote_ts=t0_ms,
        request_price=1.0,
        avg_fill_price=1.0,
        entry_fee=0.0
    )

    # Order B entered second with qty 250.0
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="W-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=250.0,
        price=1.0,
        notional=250.0,
        effective_leverage=10,
        client_order_id="cl_w_qty250",
        order_id="ord_w2",
        status="FILLED",
        stop_loss_price=1.05,
        take_profit_price=0.90,
        quote_ts=t0_ms + 1000,
        request_price=1.0,
        avg_fill_price=1.0,
        entry_fee=0.0
    )

    mock_incomes = [
        {
            "incomeId": "inc_w_250",
            "symbol": "W-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "25.0",
            "time": exit_ms
        }
    ]

    mock_orders = [
        {
            "orderId": "ord_close_w2",
            "symbol": "W-USDT",
            "side": "BUY",
            "positionSide": "SHORT",
            "type": "TAKE_PROFIT_MARKET",
            "status": "FILLED",
            "executedQty": "250.0",
            "avgPrice": "0.90",
            "time": exit_ms,
            "updateTime": exit_ms
        }
    ]

    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", return_value=mock_orders)

    orch.reconcile_outcomes()

    # Order B (250 qty) must be matched and closed; Order A (100 qty) must remain open!
    attr_a = db.get_closed_trade_attribution("cl_w_qty100")
    attr_b = db.get_closed_trade_attribution("cl_w_qty250")

    assert attr_a is not None
    assert attr_b is not None
    assert attr_a["exit_time"] is None  # Remains open
    assert attr_b["exit_time"] is not None  # Successfully closed
    assert attr_b["realized_pnl"] == pytest.approx(25.0)


def test_f07_income_not_marked_processed_on_db_error(mocker):
    """
    Test 3: If database write throws an exception, incomeId is NOT marked processed,
    guaranteeing that the exit is not permanently lost and will be retried.
    """
    import sqlite3
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["DOGE-USDT"]

    client_order_id = "cl_doge_retry_db"
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="DOGE-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=50.0,
        price=0.20,
        notional=10.0,
        effective_leverage=10,
        client_order_id=client_order_id,
        order_id="ord_doge_err",
        status="FILLED",
        stop_loss_price=0.21,
        take_profit_price=0.18,
        quote_ts=1700000000000,
        request_price=0.20,
        avg_fill_price=0.20,
        entry_fee=0.0
    )

    mock_incomes = [
        {
            "incomeId": "inc_doge_err_1",
            "symbol": "DOGE-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "5.0",
            "time": 1700000010000
        }
    ]

    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", return_value=[])

    # First attempt: Simulate database failure on record_trade_exit
    mocker.patch("db.record_trade_exit", side_effect=sqlite3.OperationalError("database is locked"))

    orch.reconcile_outcomes()

    # CRITICAL: inc_doge_err_1 MUST NOT be in processed_income_ids
    assert "inc_doge_err_1" not in session.processed_income_ids

    # Second attempt: Database succeeds
    mocker.stopall()
    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", return_value=[])

    orch.reconcile_outcomes()

    # Now it must be marked processed and record in DB must be closed
    assert "inc_doge_err_1" in session.processed_income_ids
    attr = db.get_closed_trade_attribution(client_order_id)
    assert attr is not None
    assert attr["exit_time"] is not None
    assert attr["realized_pnl"] == pytest.approx(5.0)

