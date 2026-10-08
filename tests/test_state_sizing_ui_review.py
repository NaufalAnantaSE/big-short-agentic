"""Tests for N1 (sizing leverage asymmetry), BUG 7 (session restore universe_mode), and BUG 8 (direction-aware explainer)."""

import time
import pytest
from unittest.mock import MagicMock
from sizing import SizingCalculator
from plain_explainer import humanize_ai_decision
from config import load_config


def test_n1_sizing_leverage_asymmetry_respects_max_long_vs_max_short():
    # Contract with maxLongLeverage=10 and maxShortLeverage=20
    contract_info = {
        "quantityPrecision": 2,
        "tradeMinQuantity": "0.01",
        "tradeMinUSDT": "5.0",
        "maxLongLeverage": 10,
        "maxShortLeverage": 20
    }

    # When target leverage is 20:
    # SHORT should receive 20x
    res_short = SizingCalculator.calculate_lot(
        symbol="ASYM-USDT",
        margin_usdt=10.0,
        target_leverage=20,
        current_price=100.0,
        contract_info=contract_info,
        max_allowed_leverage=20,
        direction="SHORT"
    )
    assert res_short.effective_leverage == 20
    assert res_short.notional_value == 200.0

    # LONG should be capped by maxLongLeverage (10x), NOT 20x
    res_long = SizingCalculator.calculate_lot(
        symbol="ASYM-USDT",
        margin_usdt=10.0,
        target_leverage=20,
        current_price=100.0,
        contract_info=contract_info,
        max_allowed_leverage=20,
        direction="LONG"
    )
    assert res_long.effective_leverage == 10
    assert res_long.notional_value == 100.0


def test_bug8_plain_explainer_direction_aware_fib_and_gate_narrative():
    # 1. Extended dump narrative for SHORT vs LONG
    fib_dump = {
        "valid": True,
        "zone": "EXTENDED_DUMP",
        "retracement_ratio": 0.85
    }

    short_card = humanize_ai_decision(
        symbol="DUMP-USDT",
        decision="SKIP",
        confidence=0,
        evidence="Deterministic hard gate rejected candidate",
        risk_factors="dump_already_extended",
        price=1.0,
        change_24h=-15.0,
        spread_pct=0.1,
        fibonacci=fib_dump,
        direction="SHORT"
    )
    assert any("mencegah jual di dasar" in note for note in short_card["market_notes"])
    assert "menolak membuka posisi jual" in short_card["plain_reason"]

    long_card = humanize_ai_decision(
        symbol="DUMP-USDT",
        decision="SKIP",
        confidence=0,
        evidence="Deterministic hard gate rejected candidate",
        risk_factors="dump_already_extended",
        price=1.0,
        change_24h=-15.0,
        spread_pct=0.1,
        fibonacci=fib_dump,
        direction="LONG"
    )
    assert any("potensi pantulan jenuh jual" in note for note in long_card["market_notes"])
    assert "memverifikasi konfirmasi pantulan support" in long_card["plain_reason"]

    # 2. Peak exhaustion / FOMO danger narrative for LONG
    long_fomo_card = humanize_ai_decision(
        symbol="PUMP-USDT",
        decision="SKIP",
        confidence=0,
        evidence="Deterministic hard gate rejected candidate",
        risk_factors="pump_already_extended",
        price=100.0,
        change_24h=35.0,
        spread_pct=0.1,
        fibonacci={"valid": True, "zone": "PEAK_EXHAUSTION", "retracement_ratio": 0.02},
        direction="LONG"
    )
    assert any("risiko beli di pucuk (FOMO)" in note for note in long_fomo_card["market_notes"])
    assert "mencegah risiko membeli di pucuk (FOMO)" in long_fomo_card["plain_reason"]


def test_bug7_session_restore_preserves_universe_mode(tmp_path, monkeypatch):
    import db
    from tenant_manager import TenantSessionManager
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'test_u_mode.db'))
    db.init_db()

    user_id = db.create_user("trader_mode", "hashpass", "Trader Mode")
    db.update_user_credentials(user_id, "mock_key", "mock_sec", is_demo=True)
    db.save_session(
        session_id="bx_test_restore_umode",
        user_id=user_id,
        status="ACTIVE_SEARCHING",
        margin=5.0,
        leverage=20,
        quota=5,
        filled_count=0,
        mode="MEME_ONLY",
        is_live=False,
        started_at=time.time(),
        direction_mode="BOTH"
    )

    tm = TenantSessionManager(base_config=load_config())
    orch = tm.get_orchestrator(user_id)
    orch.current_session = None

    # Call run_cycle_for_user with dry_run=True, which restores session from DB
    monkeypatch.setattr(orch, "run_cycle", lambda dry_run=False: {"status": "TEST_OK", "evaluations": []})
    tm.run_cycle_for_user(user_id, dry_run=True)

    assert orch.current_session is not None
    assert orch.current_session.universe_mode == "MEME_ONLY"
    assert orch.config.universe_mode == "MEME_ONLY"
