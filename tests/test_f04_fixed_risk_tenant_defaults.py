"""
F-04 Acceptance Tests: Fixed-risk default behavior across config, tenant, persistence, and sizing.

Audit findings (F-04):
1. `risk_budget_per_trade` was optional with default `None`.
2. Tenant start session did not forward it.
3. Database did not persist or rehydrate it.
4. Claims that all trades use fixed $2 risk were false because without wiring,
   trades sized via standard margin% without risk budget constraint.
"""
import time
import pytest
from config import AppConfig
from orchestrator import SessionOrchestrator
from tenant_manager import TenantSessionManager
from scanner import CandidatePair
import db


def test_app_config_and_tenant_manager_default_to_2_dollar_fixed_risk():
    """
    AppConfig and TenantSessionManager must default to 2.0 USDT risk budget per trade.
    """
    db.init_db()
    user = db.get_user_by_username("naufal")
    assert user is not None
    user_id = user["id"]

    config = AppConfig(api_key="mock", secret_key="mock")
    assert config.default_risk_budget_usdt == 2.0

    tm = TenantSessionManager(config)
    res = tm.start_session(user_id=user_id, margin_per_pos=5.0, leverage=20, quota=2)
    orch = tm.get_orchestrator(user_id)
    assert orch.current_session.risk_budget_per_trade == 2.0
    assert res["risk_budget_per_trade"] == 2.0


def test_tenant_start_session_persists_and_forwards_risk_budget():
    """
    TenantSessionManager.start_session forwards risk_budget_per_trade to orchestrator
    and persists it into SQLite.
    """
    db.init_db()
    user = db.get_user_by_username("naufal")
    assert user is not None
    user_id = user["id"]

    config = AppConfig(api_key="mock", secret_key="mock")
    tm = TenantSessionManager(config)

    res = tm.start_session(
        user_id=user_id,
        margin_per_pos=5.0,
        leverage=20,
        quota=2,
        risk_budget_per_trade=2.5
    )

    orch = tm.get_orchestrator(user_id)
    assert orch.current_session.risk_budget_per_trade == 2.5

    # Check database persistence
    saved_sess = db.get_latest_user_session(user_id)
    assert saved_sess is not None
    assert saved_sess.get("risk_budget_per_trade") == 2.5


def test_tenant_rehydration_restores_risk_budget(mocker):
    """
    When tenant restarts and get_account_summary is called, risk_budget_per_trade
    is rehydrated from the SQLite database.
    """
    db.init_db()
    existing = db.get_user_by_username("f04_rehydrate_user")
    if not existing:
        user_id = db.create_user("f04_rehydrate_user", "pass123", "F04 User", "user")
    else:
        user_id = existing["id"]

    config = AppConfig(api_key="mock", secret_key="mock")
    tm = TenantSessionManager(config)

    session_id = f"bx_sess_rehydrate_{int(time.time())}"
    db.save_session(
        session_id=session_id,
        user_id=user_id,
        status="ACTIVE_SEARCHING",
        margin=5.0,
        leverage=20,
        quota=2,
        filled_count=0,
        mode="PUMP_GAINERS",
        is_live=False,
        started_at=time.time(),
        risk_budget_per_trade=3.0
    )

    # Fresh orchestrator without memory of prior session
    fresh_orch = SessionOrchestrator(config)
    fresh_session = fresh_orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    fresh_session.session_id = session_id
    tm._orchestrator_pool[user_id] = fresh_orch

    mocker.patch.object(tm, "get_client", return_value=fresh_orch.client)
    mocker.patch.object(fresh_orch.client, "get_balance", return_value={"balance": 100.0, "asset": "USDT"})
    mocker.patch.object(fresh_orch.client, "get_positions", return_value=[])

    tm.get_account_summary(user_id)

    assert fresh_orch.current_session.risk_budget_per_trade == 3.0


def test_orchestrator_candidate_sizing_uses_default_risk_budget():
    """
    Candidate sizing via calculate_lot uses the session's 2.0 USDT risk budget,
    sizing the trade so that loss at SL is bounded to ~$2.00 instead of unbounded.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2, risk_budget_per_trade=2.0)
    assert session.risk_budget_per_trade == 2.0

    contract_info = {
        "symbol": "DOGE-USDT",
        "quantityPrecision": 0,
        "maxLeverage": 100,
        "minQty": 1.0
    }
    cand = CandidatePair(
        symbol="DOGE-USDT",
        last_price=0.20,
        price_change_percent=5.0,
        volume_24h_usdt=1000000.0,
        bid1=0.1999,
        ask1=0.2001,
        spread_percent=0.04,
        contract_info=contract_info
    )

    from sizing import SizingCalculator
    sizing = SizingCalculator.calculate_lot(
        symbol=cand.symbol,
        margin_usdt=session.margin_per_pos,
        target_leverage=session.leverage,
        current_price=cand.last_price,
        contract_info=cand.contract_info,
        max_allowed_leverage=20,
        direction="SHORT",
        atr=0.004,
        target_rr=2.0,
        risk_budget_usdt=session.risk_budget_per_trade
    )

    assert sizing.is_valid is True
    # At SL, loss should be within 10% of $2.00
    sl_distance = abs(sizing.entry_price - sizing.stop_loss_price)
    loss_at_sl = sizing.quantity * sl_distance
    assert loss_at_sl <= 2.20
    assert loss_at_sl >= 1.80

