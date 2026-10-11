"""Follow-up review at d909385; run only in the isolated /tmp source copy.

Imports the original review fixtures, which block exchange I/O and production paths.
Assertions express expected safety behavior, not the defective implementation.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
import time

import pytest
from test_codex_review_regressions import orch, isolate, candidate, decision, depth, evaluate
import orchestrator as om
from ai_evaluator import apply_invalidation_gate, BatchTriageResult
from config import AppConfig
from tenant_manager import TenantSessionManager
from watchlist_manager import ReversalTriggerResult
from strategy_playbook import PlaybookMatch
import db


def prepare_watchlist_trigger(orch, monkeypatch):
    monkeypatch.setattr(orch.watchlist, "check_deterministic_reversal", lambda **kw: (
        False, None, ReversalTriggerResult(triggered=True, pattern="REVIEW_REVERSAL",
                                         trigger_price=100, evidence="Only price pattern changed")))
    orch.client.get_klines = Mock(return_value=[])
    orch.client.get_contracts = Mock(return_value=[{"symbol": "TEST-USDT", **candidate()["cand"].contract_info}])


def test_control_valid_quote_and_signal_still_submit(orch):
    report, _, placed = evaluate(orch)
    assert placed and orch.client.place_order.call_count == 1
    assert report["status"] == "SUBMITTED" and report["avg_fill_price"] is None


def test_control_owned_today_income_excludes_yesterday(orch):
    now = datetime.now(timezone.utc)
    yesterday = now-timedelta(days=1)
    orch.current_session.started_at = yesterday.timestamp()-100
    orch.current_session.executed_symbols = ["TEST-USDT"]
    orch.client.get_income.return_value = [
        {"incomeId": "past", "symbol": "TEST-USDT", "income": "-4", "time": int(yesterday.timestamp()*1000)},
        {"incomeId": "today", "symbol": "TEST-USDT", "income": "-1", "time": int(now.timestamp()*1000)},
    ]
    assert orch.reconcile_outcomes() is True
    assert orch.current_session.daily_realized_pnl == -1


def test_real_database_restart_preserves_ownership_and_ingests_exit(orch):
    uid = db.get_user_by_username("naufal")["id"]
    session = orch.current_session
    db.save_session(session_id=session.session_id, user_id=uid, status=session.status,
        margin=5, leverage=20, quota=2, filled_count=1, mode="PUMP_GAINERS",
        is_live=False, started_at=session.started_at, risk_budget_per_trade=2)
    db.record_order(user_id=uid, session_id=session.session_id, symbol="TEST-USDT",
        quantity=1, price=100, notional=100, leverage=20, client_order_id="restart-review-entry",
        order_id="restart-owned", status="FILLED", avg_fill_price=100)
    saved = db.get_latest_user_session(uid)
    fresh = om.SessionOrchestrator(orch.config)
    manager = TenantSessionManager(orch.config)
    manager._hydrate_session_state(fresh, saved)
    assert fresh.current_session.risk_budget_per_trade == 2
    fresh.client.get_income = Mock(return_value=[{"incomeId": "close-after-restart",
        "symbol": "TEST-USDT", "income": "-4", "time": int(time.time()*1000)}])
    assert fresh.reconcile_outcomes() is True
    assert fresh.current_session.daily_realized_pnl == -4, (
        f"Owned exit ignored: symbols={fresh.current_session.executed_symbols}, "
        f"pnl={fresh.current_session.daily_realized_pnl}")


def test_unknown_invalidation_answer_remains_blocked_in_watchlist(orch, monkeypatch):
    result = decision()
    result.invalidation_risk_present = None
    result.decision, result.gate_downgrade_reason = apply_invalidation_gate(result)
    assert result.decision == "WAIT"
    orch.ai.evaluate_deep_candidate.return_value = result
    evaluate(orch)
    prepare_watchlist_trigger(orch, monkeypatch)
    orch.run_cycle(dry_run=False)
    assert orch.client.place_order.call_count == 0, "UNKNOWN became bool(None)=False and watchlist submitted"


def test_existing_watchlist_entry_receives_new_invalidation(orch, monkeypatch):
    orch.watchlist.add_candidate(symbol="TEST-USDT", current_price=100, conviction_score=75,
                                direction="SHORT", atr=1.5)
    result = decision()
    result.invalidation_risk_present = True
    result.invalidation_risk_detail = "New invalidation remains unresolved"
    result.invalidation_rebuttal = ""
    result.decision, result.gate_downgrade_reason = apply_invalidation_gate(result)
    orch.ai.evaluate_deep_candidate.return_value = result
    evaluate(orch)
    prepare_watchlist_trigger(orch, monkeypatch)
    orch.run_cycle(dry_run=False)
    assert orch.client.place_order.call_count == 0, "Existing entry discarded new invalidation fields"


@pytest.mark.parametrize("timestamp", [1700000000000, 1])
def test_no_fixture_timestamp_exemption_in_exchange_execution(orch, timestamp):
    orch.client.get_depth.return_value = depth(timestamp)
    evaluate(orch)
    assert orch.client.place_order.call_count == 0, f"Production accepted exempt fixture timestamp {timestamp}"


def test_watchlist_rejects_one_hour_old_quote(orch, monkeypatch):
    orch.watchlist.add_candidate(symbol="TEST-USDT", current_price=100, conviction_score=85,
                                direction="SHORT", atr=1.5)
    prepare_watchlist_trigger(orch, monkeypatch)
    orch.client.get_depth.return_value = depth(int((time.time()-3600)*1000))
    orch.run_cycle(dry_run=False)
    assert orch.client.place_order.call_count == 0, "Watchlist submitted using one-hour-old depth"


def test_quote_expiring_during_leverage_request_blocks_submit(orch, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(om.time, "time", lambda: clock[0])
    orch.client.get_depth.return_value = depth(int((clock[0]-55)*1000))
    def delay_leverage(*args, **kwargs):
        clock[0] += 10
    orch.client.set_leverage.side_effect = delay_leverage
    evaluate(orch)
    assert orch.client.place_order.call_count == 0, "Quote age was checked before, but not after, delayed preflight"


def test_replacing_session_during_triage_cancels_entire_old_cycle(orch, monkeypatch):
    original_id = orch.current_session.session_id
    orch.scanner.scan_universe.return_value = [candidate()["cand"]]
    orch.client.get_klines = Mock(return_value=[])
    monkeypatch.setattr(om, "build_candidate_features", lambda *a, **kw: {
        **candidate()["market_features"], "atr": 1.5})
    monkeypatch.setattr(om, "evaluate_playbooks", lambda **kw: PlaybookMatch(
        playbook="PUMP_EXHAUSTION", direction="SHORT", score=80, recommended_rr=2.5))
    def replacement_during_triage(*args, **kwargs):
        orch.stop_session()
        orch.start_session(direction_mode="SHORT", quota=2)
        return BatchTriageResult(is_valid=False, error_message="Old triage completed after restart")
    orch.ai.evaluate_batch_triage = Mock(side_effect=replacement_during_triage)
    orch.run_cycle(dry_run=False)
    assert orch.current_session.session_id != original_id
    assert orch.client.place_order.call_count == 0, "New per-candidate snapshot adopted previous cycle's candidate"
