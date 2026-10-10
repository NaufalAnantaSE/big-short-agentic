import pytest
from orchestrator import SessionOrchestrator
from config import AppConfig
from scanner import CandidatePair
from audit_logger import AuditLogger


def test_anti_reentry_blocks_previously_executed_symbol_in_same_session(mocker):
    """
    P1-3 Acceptance Test:
    When a symbol was already executed in the current session (present in executed_symbols),
    even if the position has closed, the symbol CANNOT re-enter in the same session.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE"
    session.executed_symbols = ["PEPE-USDT"]  # Already executed in this session

    cand = CandidatePair(
        symbol="PEPE-USDT",
        last_price=10.0,
        bid1=9.995,
        ask1=10.005,
        volume_24h_usdt=1000000.0,
        price_change_percent=15.0,
        spread_percent=0.10,
        contract_info={"minQty": 1.0, "stepSize": 1.0, "tickSize": 0.01}
    )

    sc = {
        "cand": cand,
        "closes": [9.0, 9.5, 10.0],
        "market_features": {},
        "playbook_match": None,
        "atr_val": 0.2,
        "allowed_directions": ["SHORT"],
        "suggested_direction": "SHORT"
    }

    class DummyAIResponse:
        decision = "ENTER_SHORT"
        confidence = 90.0
        key_evidence = ["Rejection"]
        risk_factors = []
        usage = {}
        latency_ms = 100.0

    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse())
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mock_place_order = mocker.patch.object(orch.client, "place_order")

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False
    )

    # Must be vetoed due to anti-reentry
    assert placed is False
    assert rep.get("executed") is False
    assert "ANTI_REENTRY" in rep.get("veto_reason", "")
    mock_place_order.assert_not_called()


def test_daily_loss_limit_stops_entries_after_max_loss(mocker):
    """
    P1-3 Acceptance Test:
    When accumulated daily loss reaches or exceeds max_daily_loss_pct (e.g. 3% of capital),
    all further candidate evaluations and order submissions are completely halted.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.strategy_capital_usdt = 100.0
    session.max_daily_loss_pct = 3.0  # Max loss $3.00

    # Simulate accumulated daily loss of -$3.50
    session.daily_realized_pnl = -3.50

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mock_scan = mocker.patch.object(orch.scanner, "scan_universe")
    mock_place_order = mocker.patch.object(orch.client, "place_order")

    res = orch.run_cycle(dry_run=False)

    assert res["status"] == "DAILY_LOSS_LIMIT_REACHED"
    mock_scan.assert_not_called()
    mock_place_order.assert_not_called()


def test_consecutive_losses_triggers_cooldown(mocker):
    """
    P1-3 Acceptance Test:
    After N consecutive losses (e.g. 3 losses), a cooldown period is activated,
    preventing immediate revenge trading.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=10, quota=2)
    session.status = "ACTIVE_SEARCHING"

    import time
    session.consecutive_losses = 3
    session.cooldown_until = time.time() + 600.0  # 10 min cooldown

    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mock_scan = mocker.patch.object(orch.scanner, "scan_universe")

    res = orch.run_cycle(dry_run=False)

    assert res["status"] == "COOLDOWN_ACTIVE"
    mock_scan.assert_not_called()
