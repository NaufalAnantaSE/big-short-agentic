import pytest
from db import (
    init_db,
    record_trade_entry,
    record_trade_exit,
    get_closed_trade_attribution,
    get_db
)


@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()


def test_trade_ledger_lifecycle_entry_to_exit_attribution():
    """
    P1-4 Acceptance Test:
    For every closed trade, we can answer in a SINGLE query:
    1. Realized R
    2. Total fees (entry fee + exit fee + funding fee)
    3. Exit reason (TP/SL/timeout/manual)
    4. Effective leverage (actual sizing leverage, not session default)
    """
    client_order_id = "bx_short_test_12345"

    # 1. Record Trade Entry
    record_trade_entry(
        user_id=1,
        session_id="bx_sess_test_1",
        symbol="PEPE-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=1000.0,
        price=10.0,
        notional=10000.0,
        effective_leverage=12,  # Adaptive sizing leverage 12x
        client_order_id=client_order_id,
        order_id="ord_99901",
        status="FILLED",
        stop_loss_price=10.5,
        take_profit_price=9.0,
        quote_ts=1700000000000,
        request_price=10.0,
        avg_fill_price=10.0,
        entry_fee=5.0
    )

    # 2. Record Trade Exit (Take Profit reached at 9.0)
    # Stop distance is 0.5 per unit ($500 risk = 1R). Profit is 1.0 per unit ($1000 gain = +2.0R).
    record_trade_exit(
        client_order_id=client_order_id,
        exit_price=9.0,
        exit_reason="TAKE_PROFIT",
        exit_fee=4.5,
        funding_fee=-0.5,
        realized_pnl=1000.0,
        realized_r=2.0
    )

    # 3. Answer all 4 attribution questions in a SINGLE query
    attr = get_closed_trade_attribution(client_order_id)
    assert attr is not None
    assert attr["realized_r"] == 2.0
    assert attr["exit_reason"] == "TAKE_PROFIT"
    assert attr["effective_leverage"] == 12
    assert attr["total_fee"] == 9.0  # entry_fee (5.0) + exit_fee (4.5) + funding (-0.5)
    assert attr["entry_price"] == 10.0
    assert attr["exit_price"] == 9.0


def test_trade_ledger_stop_loss_exit_attribution():
    """Verify attribution when position exits on STOP_LOSS (-1.0R)."""
    client_order_id = "bx_short_test_sl_54321"

    record_trade_entry(
        user_id=1,
        session_id="bx_sess_test_2",
        symbol="DOGE-USDT",
        side="SELL",
        position_side="SHORT",
        quantity=500.0,
        price=0.20,
        notional=100.0,
        effective_leverage=15,
        client_order_id=client_order_id,
        order_id="ord_99902",
        status="FILLED",
        stop_loss_price=0.21,
        take_profit_price=0.18,
        entry_fee=0.06
    )

    record_trade_exit(
        client_order_id=client_order_id,
        exit_price=0.21,
        exit_reason="STOP_LOSS",
        exit_fee=0.06,
        funding_fee=0.01,
        realized_pnl=-5.0,
        realized_r=-1.0
    )

    attr = get_closed_trade_attribution(client_order_id)
    assert attr is not None
    assert attr["realized_r"] == -1.0
    assert attr["exit_reason"] == "STOP_LOSS"
    assert attr["effective_leverage"] == 15
    assert attr["total_fee"] == 0.13


def test_session_equity_snapshot():
    """Verify session equity snapshot recording at start and stop."""
    from db import save_session, update_session_equity, get_db

    sess_id = "test_sess_equity_1"
    save_session(
        session_id=sess_id,
        user_id=1,
        status="ACTIVE",
        margin=5.0,
        leverage=10,
        quota=2,
        filled_count=0,
        mode="VST",
        is_live=False,
        started_at=1700000000.0
    )
    update_session_equity(sess_id, initial_equity=250.0)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT initial_equity, final_equity FROM sessions WHERE session_id = ?", (sess_id,))
        row = dict(cursor.fetchone())

    assert row["initial_equity"] == 250.0
    assert row["final_equity"] is None

    update_session_equity(sess_id, final_equity=258.5)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT initial_equity, final_equity FROM sessions WHERE session_id = ?", (sess_id,))
        row_updated = dict(cursor.fetchone())

    assert row_updated["final_equity"] == 258.5
