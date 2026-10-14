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


def test_f07_reconciliation_order_with_submitted_status(mocker):
    """
    Acceptance Test: An order recorded with status='SUBMITTED' (synchronous order submit before fill update)
    must be recognized as an open order by get_open_orders_for_session and reconciled to status='CLOSED'.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["SOL-USDT"]

    client_order_id = "cl_sol_submitted_01"
    entry_ts_ms = 1700000000000
    exit_ts_ms = 1700000010000

    # Entry recorded with status='SUBMITTED'
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="SOL-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=10.0,
        price=150.0,
        notional=1500.0,
        effective_leverage=10,
        client_order_id=client_order_id,
        order_id="ord_sol_sub",
        status="SUBMITTED",
        stop_loss_price=155.0,
        take_profit_price=140.0,
        quote_ts=entry_ts_ms,
        request_price=150.0,
        avg_fill_price=150.0,
        entry_fee=-0.10
    )

    mock_incomes = [
        {
            "incomeId": "inc_sol_sub",
            "symbol": "SOL-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "100.0",
            "time": exit_ts_ms
        }
    ]
    mock_orders = [
        {
            "orderId": "ord_tp_sol",
            "symbol": "SOL-USDT",
            "side": "BUY",
            "positionSide": "SHORT",
            "type": "TAKE_PROFIT_MARKET",
            "status": "FILLED",
            "avgPrice": "140.0",
            "executedQty": "10.0",
            "time": exit_ts_ms,
            "updateTime": exit_ts_ms
        }
    ]

    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", return_value=mock_orders)

    ok = orch.reconcile_outcomes()
    assert ok is True

    attr = db.get_closed_trade_attribution(client_order_id)
    assert attr is not None
    assert attr["exit_time"] is not None
    assert attr["exit_reason"] == "TAKE_PROFIT"
    assert attr["exit_price"] == pytest.approx(140.0)
    assert "inc_sol_sub" in session.processed_income_ids


def test_f07_reconciliation_rejects_entry_order_as_closing_order(mocker):
    """
    Acceptance Test (Tugas Akhir 1):
    When multiple open candidates exist (len(sym_candidates) > 1) and an entry order (side='SELL')
    occurs within <= 5000ms of exit_time with identical executedQty (e.g. 250.0), the executedQty matching loop
    must reject the entry order (side='SELL') and strictly select the closing side order (side='BUY' for SHORT).
    Candidate with qty=250.0 is closed, while candidate with qty=100.0 remains open.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["NEAR-USDT"]

    t_exit_ms = 1700000003000
    t_entry_ms = t_exit_ms - 2000  # Entry happened 2 seconds before exit (e.g. emergency close)

    # Candidate 1: qty=100.0
    client_order_id_1 = "cl_near_order_100"
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="NEAR-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=100.0,
        price=5.0,
        notional=500.0,
        effective_leverage=10,
        client_order_id=client_order_id_1,
        order_id="ord_near_entry_1",
        status="FILLED",
        stop_loss_price=5.20,
        take_profit_price=4.50,
        quote_ts=t_entry_ms - 1000,
        request_price=5.0,
        avg_fill_price=5.0,
        entry_fee=0.0
    )

    # Candidate 2: qty=250.0 (the one that will close)
    client_order_id_2 = "cl_near_order_250"
    db.record_trade_entry(
        user_id=1,
        session_id=session.session_id,
        symbol="NEAR-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=250.0,
        price=5.0,
        notional=1250.0,
        effective_leverage=10,
        client_order_id=client_order_id_2,
        order_id="ord_near_entry_2",
        status="FILLED",
        stop_loss_price=5.20,
        take_profit_price=4.50,
        quote_ts=t_entry_ms,
        request_price=5.0,
        avg_fill_price=5.0,
        entry_fee=0.0
    )

    mock_incomes = [
        {
            "incomeId": "inc_near_fast",
            "symbol": "NEAR-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "125.0",
            "time": t_exit_ms
        }
    ]

    # Two exchange orders within 5s window of exit, BOTH with executedQty=250.0:
    # 1. Entry order: side='SELL', executedQty=250.0 (must be rejected!)
    # 2. Closing order: side='BUY', executedQty=250.0, avgPrice=4.50, type='TAKE_PROFIT_MARKET' (must be selected!)
    mock_orders = [
        {
            "orderId": "ord_entry_wrong_pick_250",
            "symbol": "NEAR-USDT",
            "side": "SELL",
            "positionSide": "SHORT",
            "type": "MARKET",
            "status": "FILLED",
            "executedQty": "250.0",
            "avgPrice": "5.0",
            "time": t_entry_ms,
            "updateTime": t_entry_ms
        },
        {
            "orderId": "ord_close_correct_pick_250",
            "symbol": "NEAR-USDT",
            "side": "BUY",
            "positionSide": "SHORT",
            "type": "TAKE_PROFIT_MARKET",
            "status": "FILLED",
            "executedQty": "250.0",
            "avgPrice": "4.50",
            "time": t_exit_ms,
            "updateTime": t_exit_ms
        }
    ]

    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", return_value=mock_orders)

    ok = orch.reconcile_outcomes()
    assert ok is True

    attr_1 = db.get_closed_trade_attribution(client_order_id_1)
    attr_2 = db.get_closed_trade_attribution(client_order_id_2)

    assert attr_1 is not None
    assert attr_2 is not None

    # Candidate 1 (qty=100.0) remains OPEN
    assert attr_1["exit_time"] is None

    # Candidate 2 (qty=250.0) is matched and CLOSED via executedQty branch
    assert attr_2["exit_time"] is not None
    # Must have matched ord_close_correct_pick_250 (side=BUY), NOT ord_entry_wrong_pick_250 (side=SELL)
    assert attr_2["exit_reason"] == "TAKE_PROFIT"
    assert attr_2["exit_price"] == pytest.approx(4.50)
    assert attr_2["realized_pnl"] == pytest.approx(125.0)


def test_f07_hydrate_session_state_preserves_new_executed_symbols_and_reconciles_subsequent_trades(mocker):
    """
    Acceptance Test (Titik 4A & Langkah 5.1):
    1. Simulates Trade #1 (CNPY-USDT) saved in sessions.executed_symbols = '["CNPY-USDT"]'.
    2. Simulates Trade #2 (CITREA-USDT) and Trade #3 (STANDARD-USDT) in order_records and in-memory orch.
    3. _hydrate_session_state must merge symbols and preserve all 3 symbols instead of overwriting with only CNPY.
    4. reconcile_outcomes() successfully reconciles all 3 trades to CLOSED with TRUE-NET entry_fee, exit_fee, funding_fee.
    """
    import json
    from tenant_manager import TenantSessionManager

    config = AppConfig(api_key="mock", secret_key="mock")
    tm = TenantSessionManager(config)
    user_id = db.create_user(f"trader_{uuid.uuid4().hex[:6]}", "pass123", "Trader", role="user")
    db.update_user_credentials(user_id, "mock_key", "mock_secret", is_demo=True)
    orch = tm.get_orchestrator(user_id=user_id)

    sess_id = f"bx_sess_test_{uuid.uuid4().hex[:6]}"
    now = time.time()
    db.save_session(
        session_id=sess_id,
        user_id=user_id,
        status="ACTIVE_SEARCHING",
        margin=5.0,
        leverage=20,
        quota=2,
        filled_count=1,
        mode="PUMP_GAINERS",
        is_live=False,
        started_at=now - 3600,
        auto_scan=True,
        scan_interval=60,
        last_scan_at=now,
        latest_evaluations="[]",
        environment="BINGX_VST",
        execution_mode="EXCHANGE_DEMO",
        direction_mode="SHORT",
        exit_policy="MANUAL_ONLY",
        risk_budget_per_trade=2.0
    )

    # Initial DB session state only has CNPY-USDT
    db.update_session_pnl_state(
        session_id=sess_id,
        daily_realized_pnl=0.0,
        consecutive_losses=0,
        cooldown_until=0.0,
        last_pnl_date="2026-10-15",
        processed_income_ids="[]",
        executed_symbols=json.dumps(["CNPY-USDT"])
    )

    t_base_ms = int(now * 1000)

    # Record 3 trades in order_records: CNPY, CITREA, STANDARD
    db.record_trade_entry(
        user_id=1, session_id=sess_id, symbol="CNPY-USDT", side="SELL", position_side="SHORT",
        quantity=150.0, price=0.30, notional=45.0, effective_leverage=18,
        client_order_id="cl_cnpy_test", order_id="ord_cnpy_01", status="FILLED",
        stop_loss_price=0.32, take_profit_price=0.26, quote_ts=t_base_ms - 30000,
        request_price=0.30, avg_fill_price=0.30, entry_fee=0.0
    )
    db.record_trade_entry(
        user_id=1, session_id=sess_id, symbol="CITREA-USDT", side="SELL", position_side="SHORT",
        quantity=5000.0, price=0.014, notional=70.0, effective_leverage=20,
        client_order_id="cl_citrea_test", order_id="ord_citrea_02", status="FILLED",
        stop_loss_price=0.015, take_profit_price=0.013, quote_ts=t_base_ms - 20000,
        request_price=0.014, avg_fill_price=0.014, entry_fee=0.0
    )
    db.record_trade_entry(
        user_id=1, session_id=sess_id, symbol="STANDARD-USDT", side="SELL", position_side="SHORT",
        quantity=200.0, price=0.33, notional=66.0, effective_leverage=20,
        client_order_id="cl_standard_test", order_id="ord_standard_03", status="FILLED",
        stop_loss_price=0.34, take_profit_price=0.30, quote_ts=t_base_ms - 10000,
        request_price=0.33, avg_fill_price=0.33, entry_fee=0.0
    )

    # Initialize orch.current_session and simulate runtime addition of CITREA and STANDARD
    saved_sess = db.get_session(sess_id)
    tm._hydrate_session_state(orch, saved_sess, active_count=2)
    orch.current_session.executed_symbols = ["CNPY-USDT", "CITREA-USDT", "STANDARD-USDT"]

    # Re-hydrate using DB row that only had ["CNPY-USDT"]
    # Thanks to db.get_session_executed_symbols merge, all 3 symbols must be preserved!
    tm._hydrate_session_state(orch, saved_sess, active_count=2)
    assert set(orch.current_session.executed_symbols) == {"CNPY-USDT", "CITREA-USDT", "STANDARD-USDT"}

    # Mock incomes for all 3 closed trades
    mock_incomes = [
        # CNPY SL
        {"incomeId": "inc_cnpy_pnl", "symbol": "CNPY-USDT", "incomeType": "REALIZED_PNL", "income": "-2.00", "time": t_base_ms - 25000},
        {"incomeId": "inc_cnpy_entry_fee", "symbol": "CNPY-USDT", "incomeType": "TRADING_FEE", "income": "-0.02", "time": t_base_ms - 30000},
        {"incomeId": "inc_cnpy_exit_fee", "symbol": "CNPY-USDT", "incomeType": "TRADING_FEE", "income": "-0.02", "time": t_base_ms - 25000},

        # CITREA TP + Funding
        {"incomeId": "inc_citrea_pnl", "symbol": "CITREA-USDT", "incomeType": "REALIZED_PNL", "income": "5.00", "time": t_base_ms - 15000},
        {"incomeId": "inc_citrea_entry_fee", "symbol": "CITREA-USDT", "incomeType": "TRADING_FEE", "income": "-0.03", "time": t_base_ms - 20000},
        {"incomeId": "inc_citrea_exit_fee", "symbol": "CITREA-USDT", "incomeType": "TRADING_FEE", "income": "-0.03", "time": t_base_ms - 15000},
        {"incomeId": "inc_citrea_fund", "symbol": "CITREA-USDT", "incomeType": "FUNDING_FEE", "income": "0.01", "time": t_base_ms - 18000},

        # STANDARD SL
        {"incomeId": "inc_standard_pnl", "symbol": "STANDARD-USDT", "incomeType": "REALIZED_PNL", "income": "-2.20", "time": t_base_ms - 5000},
        {"incomeId": "inc_standard_entry_fee", "symbol": "STANDARD-USDT", "incomeType": "TRADING_FEE", "income": "-0.03", "time": t_base_ms - 10000},
        {"incomeId": "inc_standard_exit_fee", "symbol": "STANDARD-USDT", "incomeType": "TRADING_FEE", "income": "-0.03", "time": t_base_ms - 5000},
    ]

    mock_orders = {
        "CNPY-USDT": [
            {"orderId": "close_cnpy", "symbol": "CNPY-USDT", "side": "BUY", "positionSide": "SHORT", "type": "STOP_MARKET", "status": "FILLED", "avgPrice": "0.32", "time": t_base_ms - 25000}
        ],
        "CITREA-USDT": [
            {"orderId": "close_citrea", "symbol": "CITREA-USDT", "side": "BUY", "positionSide": "SHORT", "type": "TAKE_PROFIT_MARKET", "status": "FILLED", "avgPrice": "0.013", "time": t_base_ms - 15000}
        ],
        "STANDARD-USDT": [
            {"orderId": "close_standard", "symbol": "STANDARD-USDT", "side": "BUY", "positionSide": "SHORT", "type": "STOP_MARKET", "status": "FILLED", "avgPrice": "0.34", "time": t_base_ms - 5000}
        ]
    }

    mocker.patch.object(orch.client, "get_income", return_value=mock_incomes)
    mocker.patch.object(orch.client, "get_all_orders", side_effect=lambda sym, **kwargs: mock_orders.get(sym, []))

    ok = orch.reconcile_outcomes()
    assert ok is True

    attr_cnpy = db.get_closed_trade_attribution("cl_cnpy_test")
    attr_citrea = db.get_closed_trade_attribution("cl_citrea_test")
    attr_standard = db.get_closed_trade_attribution("cl_standard_test")

    # All 3 trades must be successfully reconciled to status='CLOSED'
    assert attr_cnpy["exit_time"] is not None
    assert attr_cnpy["exit_reason"] == "STOP_LOSS"
    assert attr_cnpy["entry_fee"] == pytest.approx(-0.02)
    assert attr_cnpy["exit_fee"] == pytest.approx(-0.02)
    assert attr_cnpy["realized_pnl"] == pytest.approx(-2.04)

    assert attr_citrea["exit_time"] is not None
    assert attr_citrea["exit_reason"] == "TAKE_PROFIT"
    assert attr_citrea["entry_fee"] == pytest.approx(-0.03)
    assert attr_citrea["exit_fee"] == pytest.approx(-0.03)
    assert attr_citrea["funding_fee"] == pytest.approx(0.01)
    assert attr_citrea["realized_pnl"] == pytest.approx(4.95)

    assert attr_standard["exit_time"] is not None
    assert attr_standard["exit_reason"] == "STOP_LOSS"
    assert attr_standard["entry_fee"] == pytest.approx(-0.03)
    assert attr_standard["exit_fee"] == pytest.approx(-0.03)
    assert attr_standard["realized_pnl"] == pytest.approx(-2.26)


def test_f07_restored_session_in_db_is_not_overwritten_to_terminated_by_in_memory_state():
    """
    Acceptance Test (Titik 4C & Langkah 5.2):
    When DB session status is restored to 'ACTIVE_SEARCHING' but in-memory orch.current_session
    has status='TERMINATED' with token 'TERMINATED_...', _hydrate_session_state must restore
    orch.current_session.status to 'ACTIVE_SEARCHING' with a fresh generation_token.
    """
    from tenant_manager import TenantSessionManager

    config = AppConfig(api_key="mock", secret_key="mock")
    tm = TenantSessionManager(config)
    user_id = db.create_user(f"trader_{uuid.uuid4().hex[:6]}", "pass123", "Trader", role="user")
    db.update_user_credentials(user_id, "mock_key", "mock_secret", is_demo=True)
    orch = tm.get_orchestrator(user_id=user_id)

    sess_id = f"bx_sess_restored_{uuid.uuid4().hex[:6]}"
    now = time.time()
    db.save_session(
        session_id=sess_id,
        user_id=user_id,
        status="ACTIVE_SEARCHING",
        margin=5.0,
        leverage=20,
        quota=2,
        filled_count=1,
        mode="PUMP_GAINERS",
        is_live=False,
        started_at=now,
        auto_scan=False,
        scan_interval=60,
        last_scan_at=now,
        latest_evaluations="[]",
        environment="BINGX_VST",
        execution_mode="EXCHANGE_DEMO",
        direction_mode="SHORT",
        exit_policy="MANUAL_ONLY",
        risk_budget_per_trade=2.0
    )

    # Initialize orch with TERMINATED status and token
    saved_sess = db.get_session(sess_id)
    tm._hydrate_session_state(orch, saved_sess, active_count=1)
    orch.current_session.status = "TERMINATED"
    orch.current_session.generation_token = "TERMINATED_old_token_xyz"

    # Re-hydrate with DB row where status is ACTIVE_SEARCHING
    tm._hydrate_session_state(orch, saved_sess, active_count=1)

    assert orch.current_session.status == "ACTIVE_SEARCHING"
    assert not orch.current_session.generation_token.startswith("TERMINATED_")
    assert len(orch.current_session.generation_token) > 0


