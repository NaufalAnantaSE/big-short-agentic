"""Independent review regressions; run only against a copied source tree in /tmp.

Assertions describe the required safety behavior. Failures demonstrate defects.
All exchange operations are mocked; production database and logs are untouched.
"""
import concurrent.futures
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import orchestrator as om

if not Path(om.__file__).resolve().is_relative_to(Path(tempfile.gettempdir())):
    raise RuntimeError("Run this review only against a source copy in the system temp directory")

from ai_evaluator import AIEvaluationResult, apply_invalidation_gate, normalize_ai_payload
from audit_logger import AuditLogger
from client import BingXClient
from config import AppConfig
from market_features import compute_market_features, hard_gate
from scanner import CandidatePair
from sizing import SizingCalculator
from watchlist_manager import ReversalTriggerResult
from tenant_manager import TenantSessionManager
import tenant_manager as tm_module
import db


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(AuditLogger, "log_event", Mock())
    monkeypatch.setattr(BingXClient, "_request", Mock(side_effect=RuntimeError("No external API in review")))
    monkeypatch.setattr(tm_module, "get_ai_settings", lambda: {"model": "mock"})


@pytest.fixture
def orch():
    o = om.SessionOrchestrator(AppConfig(api_key="mock_review", secret_key="mock_review"))
    o.start_session(margin_per_pos=5, leverage=20, quota=2)
    o.client.get_income = Mock(return_value=[])
    o.scanner.get_occupied_symbols = Mock(return_value=set())
    o.scanner.scan_universe = Mock(return_value=[])
    o.client.get_depth = Mock(return_value=depth())
    o.client.set_leverage = Mock()
    o.client.place_order = Mock(return_value={"orderId": "review-order", "status": "SUBMITTED"})
    o.ai.evaluate_deep_candidate = Mock(return_value=decision())
    o.ai.evaluate_candidate = Mock(return_value=decision())
    return o


def depth(timestamp=None):
    return {"bids": [["99.99", "100"]], "asks": [["100.01", "100"]],
            "T": int(time.time() * 1000) if timestamp is None else timestamp}


def decision():
    return AIEvaluationResult(symbol="TEST-USDT", decision="ENTER_SHORT", confidence=85,
                              invalidation_risk_present=False, is_valid=True)


def candidate():
    return {"cand": CandidatePair(symbol="TEST-USDT", last_price=100,
        price_change_percent=10, volume_24h_usdt=1000000, bid1=99.99, ask1=100.01,
        spread_percent=0.02, contract_info={"pricePrecision": 2, "quantityPrecision": 3,
        "tradeMinQuantity": "0.001", "tradeMinUSDT": "5", "maxShortLeverage": 20}),
        "closes": [], "market_features": {"fresh": True, "spread_pct": .02,
        "funding_rate": .0001, "atr_to_friction": 10}, "playbook_match": None,
        "atr_val": 1.5, "allowed_directions": ["SHORT"], "suggested_direction": "SHORT"}


def evaluate(orch):
    return orch._evaluate_and_execute_candidate(candidate(), True, False, False)


def test_depth_timeout_must_not_submit_using_scanner_quote(orch):
    orch.client.get_depth.side_effect = RuntimeError("depth timed out")
    evaluate(orch)
    assert orch.client.place_order.call_count == 0, "Order submitted using stale scanner bid/ask after depth failure"


def test_old_depth_timestamp_must_be_rejected(orch):
    orch.client.get_depth.return_value = depth(int((time.time()-3600)*1000))
    evaluate(orch)
    assert orch.client.place_order.call_count == 0, "Order submitted with one-hour-old orderbook"


def test_new_session_cannot_adopt_old_ai_signal(orch):
    first_id = orch.current_session.session_id
    def replace_session(*args, **kwargs):
        orch.stop_session()
        orch.start_session(direction_mode="LONG")
        return decision()
    orch.ai.evaluate_deep_candidate.side_effect = replace_session
    evaluate(orch)
    assert orch.current_session.session_id != first_id
    assert orch.client.place_order.call_count == 0, "Old SHORT signal submitted into replacement LONG session"


def test_unknown_fill_survives_tenant_and_database(orch, monkeypatch):
    rep, _, placed = evaluate(orch)
    assert placed and rep["avg_fill_price"] is None and rep["status"] == "SUBMITTED"
    manager = TenantSessionManager(orch.config)
    monkeypatch.setattr(manager, "get_orchestrator", lambda user_id: orch)
    monkeypatch.setattr(orch, "run_cycle", lambda **kw: {"evaluations": [rep]})
    monkeypatch.setattr(tm_module, "humanize_ai_decision", lambda **kw: {})
    user_id = db.get_user_by_username("naufal")["id"]
    manager.run_cycle_for_user(user_id)
    with db.get_db() as conn:
        row = dict(conn.execute("SELECT status,avg_fill_price FROM order_records WHERE order_id=? ORDER BY id DESC", ("review-order",)).fetchone())
    assert row == {"status": "SUBMITTED", "avg_fill_price": None}, row


def test_worker_rehydrates_risk_and_loss_state_before_first_cycle(orch, monkeypatch):
    manager = TenantSessionManager(orch.config)
    orch.current_session = None
    saved = {"session_id": "saved-review-session", "status": "ACTIVE_SEARCHING",
        "margin_per_pos": 5, "leverage": 20, "quota": 2, "mode": "PUMP_GAINERS",
        "started_at": time.time()-100, "risk_budget_per_trade": 2.5,
        "daily_realized_pnl": -4, "consecutive_losses": 3,
        "cooldown_until": time.time()+1000, "processed_income_ids": '["already-seen"]'}
    monkeypatch.setattr(manager, "get_client", lambda user_id: Mock(get_positions=lambda: []))
    monkeypatch.setattr(manager, "get_orchestrator", lambda user_id: orch)
    monkeypatch.setattr(manager, "run_cycle_for_user", Mock())
    manager._execute_scheduled_cycle(1, saved)
    actual = (orch.current_session.risk_budget_per_trade, orch.current_session.daily_realized_pnl,
              orch.current_session.consecutive_losses, orch.current_session.processed_income_ids)
    assert actual == (2.5, -4, 3, ["already-seen"]), actual


def test_yesterdays_late_income_not_counted_as_todays_loss(orch):
    now = datetime.now(timezone.utc)
    yesterday = now.replace(hour=23, minute=59, second=0)-timedelta(days=1)
    orch.current_session.started_at = yesterday.timestamp()-1000
    orch.current_session.last_pnl_date = yesterday.strftime("%Y-%m-%d")
    orch.current_session.executed_symbols = ["TEST-USDT"]
    orch.client.get_income.return_value = [{"incomeId": "yesterday-late", "symbol": "TEST-USDT",
        "income": "-4", "incomeType": "REALIZED_PNL", "time": int(yesterday.timestamp()*1000)}]
    orch.reconcile_outcomes()
    assert orch.current_session.daily_realized_pnl == 0, orch.current_session.daily_realized_pnl


def test_empty_session_history_does_not_claim_manual_income(orch):
    assert orch.current_session.executed_symbols == []
    orch.client.get_income.return_value = [{"incomeId": "manual-close", "symbol": "OTHER-USDT",
        "income": "10", "incomeType": "REALIZED_PNL", "time": int(time.time()*1000)}]
    orch.reconcile_outcomes()
    assert orch.current_session.daily_realized_pnl == 0, "Unowned profit credited to strategy daily loss budget"


def test_day_reset_is_persisted_even_when_no_new_income(orch, monkeypatch):
    orch.current_session.last_pnl_date = "2000-01-01"
    orch.current_session.daily_realized_pnl = -4
    persist = Mock()
    monkeypatch.setattr(db, "update_session_pnl_state", persist)
    orch.reconcile_outcomes()
    assert orch.current_session.daily_realized_pnl == 0
    assert persist.call_count == 1, "Day reset lost on next DB hydration because empty income returns before persistence"


def test_unknown_income_state_blocks_new_scan(orch):
    orch.client.get_income.side_effect = RuntimeError("income API timeout")
    orch.run_cycle(dry_run=False)
    assert orch.scanner.scan_universe.call_count == 0, "Risk ingestion failure still permits entry scanning"


def test_simultaneous_evaluations_cannot_duplicate_same_symbol(orch):
    barrier = threading.Barrier(2)
    def synchronized_depth(*args, **kwargs):
        barrier.wait(timeout=5)
        return depth()
    orch.client.get_depth.side_effect = synchronized_depth
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(evaluate, orch), pool.submit(evaluate, orch)
        a.result(timeout=10); b.result(timeout=10)
    assert orch.client.place_order.call_count <= 1, f"Submitted {orch.client.place_order.call_count} orders for same symbol"


def test_ema_warmup_invalid_must_block_entry_gate():
    now = int(time.time()*1000)
    rows = {}
    for tf, interval in [("1m",60000),("15m",900000),("1h",3600000)]:
        rows[tf] = [{"time": now-(4-i)*interval, "open": 100, "high": 102,
                     "low": 98, "close": 100, "volume": 100} for i in range(3)]
    features = compute_market_features(rows, {"lastFundingRate": .0001, "updateTime": now},
        {"openInterest": 100, "time": now}, depth(now), now)
    assert features["ema_trend"]["valid"] is False
    assert hard_gate(features, direction="LONG")[0] is False, "EMA50 warmup invalid but trading gate passes"


def test_string_null_invalidation_answer_is_unknown():
    parsed = normalize_ai_payload({"decision": "ENTER_SHORT", "confidence": 85,
                                  "invalidation_risk_present": "null"})
    result = AIEvaluationResult(symbol="TEST-USDT", **parsed)
    assert apply_invalidation_gate(result)[0] == "WAIT", "String null is treated as explicit no-risk"


def test_unrebutted_invalidation_cannot_reenter_via_watchlist(orch, monkeypatch):
    ai_result = decision()
    ai_result.invalidation_risk_present = True
    ai_result.invalidation_risk_detail = "Short squeeze risk persists; funding extremely negative"
    ai_result.invalidation_rebuttal = ""
    ai_result.decision, ai_result.gate_downgrade_reason = apply_invalidation_gate(ai_result)
    assert ai_result.decision == "WAIT"
    orch.ai.evaluate_deep_candidate.return_value = ai_result
    evaluate(orch)
    assert len(orch.watchlist.get_all_entries()) == 1
    monkeypatch.setattr(orch.watchlist, "check_deterministic_reversal", lambda **kw: (
        False, None, ReversalTriggerResult(triggered=True, pattern="MOCK_REVERSAL", trigger_price=100, evidence="Price pattern only")))
    orch.client.get_klines = Mock(return_value=[])
    orch.client.get_contracts = Mock(return_value=[{"symbol": "TEST-USDT", **candidate()["cand"].contract_info}])
    orch.run_cycle(dry_run=False)
    assert orch.client.place_order.call_count == 0, "WAIT invalidation reason was discarded; watchlist submitted without reassessment"


def test_fixed_risk_must_respect_requested_leverage_ceiling():
    result = SizingCalculator.calculate_lot(symbol="TEST-USDT", margin_usdt=5,
        target_leverage=5, current_price=100, contract_info=candidate()["cand"].contract_info,
        atr=1.5, risk_budget_usdt=2)
    assert not result.is_valid or result.effective_leverage <= 5, (
        f"Requested 5x, accepted {result.effective_leverage}x")


def test_api_risk_budget_update_is_not_silently_discarded(monkeypatch):
    import api
    update = Mock(return_value={"risk_budget_per_trade": 2})
    monkeypatch.setattr(api.tenant_manager, "update_session_params", update)
    result = api.update_session(api.SessionUpdateRequest(risk_budget_per_trade=0.5), user={"id": 1})
    assert result["success"] is True
    assert update.call_args.kwargs.get("risk_budget_per_trade") == 0.5, update.call_args.kwargs
