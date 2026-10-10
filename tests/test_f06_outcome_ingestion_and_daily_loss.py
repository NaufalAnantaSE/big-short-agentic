"""
F-06 Acceptance Tests: Outcome ingestion, daily loss limit, and cooldown streak.

Audit findings (F-06):
1. `record_trade_outcome` had zero production callers; tests manually assigned
   PnL to session state instead of ingesting from actual exchange outcomes.
2. No deduplication of income events.
3. No persistence/restart recovery for realized PnL, consecutive loss count, or cooldown.
4. No day-boundary reset logic.
"""
import time
from datetime import datetime, timezone
import pytest

from config import AppConfig
from orchestrator import SessionOrchestrator
from scanner import CandidatePair
import db


def test_reconcile_outcomes_ingests_realized_pnl_and_deduplicates(mocker):
    """
    reconcile_outcomes() queries client.get_income(), attributes realized PnL
    to the active session, updates daily_realized_pnl, and deduplicates event IDs.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["PEPE-USDT"]

    # Exchange reports closed trade realized loss of -1.50 USDT
    mock_income = [
        {
            "incomeId": "inc_001",
            "symbol": "PEPE-USDT",
            "incomeType": "REALIZED_PNL",
            "income": "-1.50",
            "time": int(time.time() * 1000)
        }
    ]
    mocker.patch.object(orch.client, "get_income", return_value=mock_income)

    orch.reconcile_outcomes()

    assert session.daily_realized_pnl == pytest.approx(-1.50, 0.001)
    assert session.consecutive_losses == 1
    assert "inc_001" in session.processed_income_ids

    # Second call with the same event MUST NOT double count
    orch.reconcile_outcomes()
    assert session.daily_realized_pnl == pytest.approx(-1.50, 0.001)
    assert session.consecutive_losses == 1


def test_consecutive_losses_triggers_cooldown_and_halts_cycle(mocker):
    """
    3 consecutive losses trigger cooldown, which halts run_cycle with COOLDOWN_ACTIVE.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["PEPE-USDT", "DOGE-USDT", "SHIB-USDT"]
    session.max_consecutive_losses = 3

    mock_income = [
        {"incomeId": "inc_1", "symbol": "PEPE-USDT", "incomeType": "REALIZED_PNL", "income": "-0.50", "time": 1000},
        {"incomeId": "inc_2", "symbol": "DOGE-USDT", "incomeType": "REALIZED_PNL", "income": "-0.50", "time": 2000},
        {"incomeId": "inc_3", "symbol": "SHIB-USDT", "incomeType": "REALIZED_PNL", "income": "-0.50", "time": 3000},
    ]
    mocker.patch.object(orch.client, "get_income", return_value=mock_income)

    orch.reconcile_outcomes()

    assert session.consecutive_losses == 3
    assert session.cooldown_until > time.time()

    # run_cycle must now reject new entries due to cooldown
    res = orch.run_cycle(dry_run=True)
    assert res["status"] == "COOLDOWN_ACTIVE"


def test_daily_loss_limit_halts_run_cycle(mocker):
    """
    When daily realized loss reaches max_daily_loss_pct (e.g. 3% of $100 = $3.00),
    run_cycle() returns DAILY_LOSS_LIMIT_REACHED.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.strategy_capital_usdt = 100.0
    session.max_daily_loss_pct = 3.0
    session.executed_symbols = ["PEPE-USDT"]

    mock_income = [
        {"incomeId": "inc_big_loss", "symbol": "PEPE-USDT", "incomeType": "REALIZED_PNL", "income": "-3.50", "time": 1000}
    ]
    mocker.patch.object(orch.client, "get_income", return_value=mock_income)

    res = orch.run_cycle(dry_run=True)
    assert res["status"] == "DAILY_LOSS_LIMIT_REACHED"


def test_day_boundary_resets_daily_pnl(mocker):
    """
    When date advances to a new UTC day, daily_realized_pnl resets to 0.0.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.daily_realized_pnl = -2.50
    session.consecutive_losses = 2
    session.last_pnl_date = "2026-10-09"  # Yesterday

    mocker.patch.object(orch.client, "get_income", return_value=[])

    orch.reconcile_outcomes()

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert session.last_pnl_date == today_str
    assert session.daily_realized_pnl == 0.0
    assert session.consecutive_losses == 0


def test_session_pnl_state_persists_to_db_and_recovers(mocker):
    """
    Ensures that when outcomes are ingested, the PnL state is saved to the SQLite DB
    and can be recovered upon session restart.
    """
    db.init_db()
    user = db.get_user_by_username("naufal")
    assert user is not None
    user_id = user["id"]

    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["PEPE-USDT"]

    # Save session to DB
    db.save_session(
        session_id=session.session_id,
        user_id=user_id,
        status="ACTIVE_SEARCHING",
        margin=5.0,
        leverage=20,
        quota=2,
        filled_count=0,
        mode="PUMP_GAINERS",
        is_live=False,
        started_at=session.started_at
    )

    mock_income = [
        {"incomeId": "inc_db_test", "symbol": "PEPE-USDT", "incomeType": "REALIZED_PNL", "income": "-2.50", "time": 5000}
    ]
    mocker.patch.object(orch.client, "get_income", return_value=mock_income)

    orch.reconcile_outcomes()

    assert session.daily_realized_pnl == -2.50
    assert session.consecutive_losses == 1

    # Check that database was updated
    latest_db = db.get_latest_user_session(user_id)
    assert latest_db is not None
    assert latest_db["daily_realized_pnl"] == -2.50
    assert latest_db["consecutive_losses"] == 1
    assert "inc_db_test" in latest_db["processed_income_ids"]

    # Now simulate restart recovery via TenantSessionManager
    from tenant_manager import TenantSessionManager
    tm = TenantSessionManager(config)
    mocker.patch.object(tm, "get_client", return_value=orch.client)
    mocker.patch.object(orch.client, "get_balance", return_value={"balance": 100.0, "asset": "USDT"})
    mocker.patch.object(orch.client, "get_positions", return_value=[])

    # Put a fresh orchestrator without prior state in memory
    fresh_orch = SessionOrchestrator(config)
    fresh_session = fresh_orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    fresh_session.session_id = session.session_id
    tm._orchestrator_pool[user_id] = fresh_orch

    # Calling get_account_summary triggers recovery from db
    tm.get_account_summary(user_id)

    assert fresh_orch.current_session is not None
    assert fresh_orch.current_session.daily_realized_pnl == -2.50
    assert fresh_orch.current_session.consecutive_losses == 1
    assert "inc_db_test" in fresh_orch.current_session.processed_income_ids

