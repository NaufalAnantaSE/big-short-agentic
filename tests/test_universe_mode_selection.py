"""Tests for Universe Mode Selection (PUMP_GAINERS vs MEME_ONLY) across tenant manager and orchestrator."""

import pytest
import db
from config import load_config
from contracts import DirectionMode, ExecutionMode


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'test_universe.db'))
    db.init_db()
    return db


def test_start_session_sets_meme_only_universe_mode(isolated_db, monkeypatch):
    from tenant_manager import TenantSessionManager
    from client import BingXClient

    monkeypatch.setattr(BingXClient, "get_balance", lambda self: {
        "balance": "1000.0", "equity": "1000.0", "availableMargin": "1000.0", "usedMargin": "0.0", "unrealizedProfit": "0.0"
    })
    monkeypatch.setattr(BingXClient, "get_positions", lambda self: [])

    u_id = db.create_user("trader_meme", "pass123", "Trader Meme", "user")
    db.update_user_credentials(u_id, "mock_k", "mock_s", True)

    base_cfg = load_config()
    mgr = TenantSessionManager(base_cfg)

    # Start session with mode="MEME_ONLY"
    sess = mgr.start_session(
        user_id=u_id,
        margin_per_pos=5.0,
        leverage=20,
        quota=5,
        mode="MEME_ONLY",
        auto_scan=False
    )

    orch = mgr.get_orchestrator(u_id)
    assert orch.config.universe_mode == "MEME_ONLY"
    assert orch.current_session is not None
    assert orch.current_session.universe_mode == "MEME_ONLY"
    assert sess["mode"] == "MEME_ONLY"

    # Verify summary exposes mode correctly for frontend watcher
    summary = mgr.get_account_summary(u_id)
    assert summary["session"]["mode"] == "MEME_ONLY"


def test_start_session_fallback_on_invalid_universe_mode(isolated_db, mocker):
    from tenant_manager import TenantSessionManager
    u_id = db.create_user("trader_fallback", "pass123", "Trader Fallback", "user")
    db.update_user_credentials(u_id, "mock_k", "mock_s", True)

    base_cfg = load_config()
    mgr = TenantSessionManager(base_cfg)

    # Start session with mode="INVALID_MODE"
    sess = mgr.start_session(
        user_id=u_id,
        margin_per_pos=5.0,
        leverage=20,
        quota=5,
        mode="INVALID_MODE",
        auto_scan=False
    )

    orch = mgr.get_orchestrator(u_id)
    assert orch.config.universe_mode == "PUMP_GAINERS"
    assert orch.current_session is not None
    assert orch.current_session.universe_mode == "PUMP_GAINERS"
    assert sess["mode"] == "PUMP_GAINERS"


def test_orchestrator_run_cycle_uses_session_universe_mode(isolated_db, mocker):
    from orchestrator import SessionOrchestrator
    from config import AppConfig

    cfg = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(cfg)
    orch.start_session(
        margin_per_pos=5.0,
        leverage=20,
        quota=2,
        universe_mode="MEME_ONLY",
        direction_mode=DirectionMode.SHORT.value,
        execution_mode=ExecutionMode.LOCAL_PAPER.value
    )

    mock_scan = mocker.patch.object(orch.scanner, "scan_universe", return_value=[])

    orch.run_cycle(dry_run=True)

    # Must call scan_universe with mode="MEME_ONLY"
    mock_scan.assert_called_once()
    call_kwargs = mock_scan.call_args.kwargs
    assert call_kwargs["mode"] == "MEME_ONLY"
    assert call_kwargs["direction"] == "SHORT"
