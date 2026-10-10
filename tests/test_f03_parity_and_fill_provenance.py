"""
F-03 acceptance tests: Quote/fill provenance and watchlist parity.

Audit findings (F-03):
1. In direct execution, when avg fill was unavailable from the exchange response,
   the code fell back to actual_avg_price = executable_price, fabricating a fill
   and reporting 0.0% slippage as if an actual exchange fill occurred.
   Status also fell back to "FILLED" instead of "SUBMITTED" or pending reconciliation.
2. Watchlist did not use the executable price (bid for short, ask for long) for sizing,
   but used mid-price ((bid + ask) / 2).
3. Watchlist did not have full parity with direct execution on quote revalidation,
   provenance tracking, anti-reentry, and audit logging.

These tests assert:
- Missing fill in exchange response produces avg_fill_price=None, slippage=None,
  and fill_provenance="PENDING_RECONCILIATION" (not fabricated values).
- Exchange-reported fill produces fill_provenance="EXCHANGE_REPORTED".
- Watchlist sizes using executable price (crossing the spread), not mid-price.
- Watchlist honors anti-reentry and logs full fill provenance identical to direct execution.
"""
import pytest
from config import AppConfig
from orchestrator import SessionOrchestrator
from scanner import CandidatePair
from contracts import DirectionMode
from watchlist_manager import ReversalTriggerResult


class DummyAIResponse:
    def __init__(self, decision="ENTER_SHORT"):
        self.symbol = "PEPE-USDT"
        self.decision = decision
        self.confidence = 85
        self.setup_type = "PUMP_EXHAUSTION"
        self.key_evidence = "Strong exhaustion"
        self.risk_factors = "none"
        self.invalidation_risk_present = False
        self.invalidation_risk_detail = ""
        self.invalidation_rebuttal = ""
        self.is_valid = True
        self.usage = {"total_tokens": 150}
        self.latency_ms = 100.0


def _build_test_sc(symbol="PEPE-USDT", last_price=10.0, bid1=9.99, ask1=10.01):
    cand = CandidatePair(
        symbol=symbol,
        last_price=last_price,
        bid1=bid1,
        ask1=ask1,
        volume_24h_usdt=1000000.0,
        price_change_percent=15.0,
        spread_percent=0.10,
        contract_info={"minQty": 1.0, "stepSize": 1.0, "tickSize": 0.01, "maxShortLeverage": 20, "maxLongLeverage": 20}
    )
    return {
        "cand": cand,
        "closes": [last_price * 0.95, last_price * 0.98, last_price],
        "market_features": {
            "atr_14": 0.5,
            "rsi_14": 75.0,
            "spread_pct": 0.10,
            "fresh": True,
            "atr": 0.5,
            "funding_rate": 0.0001,
            "atr_to_friction": 5.0,
        },
        "playbook_match": None,
        "atr_val": 0.5,
        "allowed_directions": ["SHORT"],
        "suggested_direction": "SHORT"
    }


def test_direct_missing_avg_fill_does_not_fabricate_price_or_slippage(mocker):
    """
    When exchange response does NOT provide avgPrice, actual_avg_price must be None,
    slippage must be None, status must not be assumed FILLED, and fill_provenance
    must be PENDING_RECONCILIATION.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_sc("PEPE-USDT", 10.0, bid1=9.99, ask1=10.01)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))
    mocker.patch.object(orch.client, "set_leverage")
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": 1700000000000
    })

    # Exchange responds with orderId and status SUBMITTED, but NO avgPrice or price
    mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "bx_ord_999",
        "status": "SUBMITTED"
    })

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False
    )

    assert placed is True
    assert rep["executed"] is True
    assert rep["order_id"] == "bx_ord_999"
    # Provenance assertions: missing fill must NOT fabricate price or 0.0 slippage
    assert rep.get("avg_fill_price") is None
    assert rep.get("slippage") is None
    assert rep.get("slippage_pct") is None
    assert rep.get("fill_provenance") == "PENDING_RECONCILIATION"
    assert rep.get("status") == "SUBMITTED"


def test_direct_exchange_reported_fill_records_exact_provenance(mocker):
    """
    When exchange response provides avgPrice, actual_avg_price is recorded,
    slippage is calculated accurately, and fill_provenance is EXCHANGE_REPORTED.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    sc = _build_test_sc("PEPE-USDT", 10.0, bid1=9.99, ask1=10.01)
    mocker.patch("orchestrator._evaluate_hard_gate", return_value=(True, []))
    mocker.patch.object(orch.ai, "evaluate_candidate", return_value=DummyAIResponse("ENTER_SHORT"))
    mocker.patch.object(orch.client, "set_leverage")
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": 1700000000000
    })

    # Exchange reports actual fill at 9.98 (short filled 0.01 below bid1)
    mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "bx_ord_1000",
        "status": "FILLED",
        "avgPrice": "9.98"
    })

    rep, tokens, placed = orch._evaluate_and_execute_candidate(
        sc=sc,
        deep_mode=False,
        effective_dry_run=False,
        is_local_paper=False
    )

    assert placed is True
    assert rep["executed"] is True
    assert rep["order_id"] == "bx_ord_1000"
    assert rep["avg_fill_price"] == 9.98
    assert rep["fill_provenance"] == "EXCHANGE_REPORTED"
    assert rep["status"] == "FILLED"
    assert pytest.approx(rep["slippage"], 0.0001) == 9.98 - 9.99  # actual - requested


def test_watchlist_sizes_at_executable_price_not_mid_price(mocker):
    """
    Watchlist parity: Short entry must size at bid1 (crossing the spread),
    NOT mid-price ((bid1+ask1)/2).
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    orch.watchlist.add_candidate(
        symbol="WL-COIN",
        current_price=10.0,
        conviction_score=85,
        playbook="PUMP_EXHAUSTION",
        direction="SHORT",
        client=orch.client,
        session_id=session.session_id,
        atr=0.1,
        target_rr=2.0
    )

    # Wide bid/ask: bid1=9.80, ask1=10.20 -> mid is 10.00, executable price for SHORT is 9.80
    mocker.patch.object(orch.client, "get_contracts", return_value=[{
        "symbol": "WL-COIN", "quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20
    }])
    mocker.patch.object(orch.watchlist, "check_deterministic_reversal", return_value=(
        False, None, ReversalTriggerResult(triggered=True, pattern="BEARISH_ENGULFING", evidence="Engulfing bar closed")
    ))
    fake_klines = [
        {"openTime": 1700000000000 + i * 900000, "open": "10.0", "high": "10.5", "low": "9.5", "close": "10.0", "volume": "100"}
        for i in range(60)
    ]
    mocker.patch.object(orch.client, "get_klines", return_value=fake_klines)
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": 1700000000000
    })
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.client, "set_leverage")
    mock_place_order = mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "wl_ord_1", "status": "FILLED", "avgPrice": "9.99"
    })
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[])

    res = orch.run_cycle(dry_run=False)

    assert res["status"] == "WATCHLIST_EXECUTED"
    cycle_res = res["cycle_results"][0]
    # Sizing entry price must be bid1 (9.99), NOT mid-price (10.00)
    assert cycle_res["sizing"]["entry_price"] == 9.99
    assert cycle_res["request_price"] == 9.99
    assert cycle_res["fill_provenance"] == "EXCHANGE_REPORTED"
    assert cycle_res["avg_fill_price"] == 9.99


def test_watchlist_missing_avg_fill_records_pending_provenance(mocker):
    """
    Watchlist parity: when exchange does NOT report avgPrice, watchlist report
    must set avg_fill_price=None, slippage=None, and fill_provenance=PENDING_RECONCILIATION.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    orch.watchlist.add_candidate(
        symbol="WL-COIN",
        current_price=10.0,
        conviction_score=85,
        playbook="PUMP_EXHAUSTION",
        direction="SHORT",
        client=orch.client,
        session_id=session.session_id,
        atr=0.1,
        target_rr=2.0
    )

    mocker.patch.object(orch.client, "get_contracts", return_value=[{
        "symbol": "WL-COIN", "quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20
    }])
    mocker.patch.object(orch.watchlist, "check_deterministic_reversal", return_value=(
        False, None, ReversalTriggerResult(triggered=True, pattern="BEARISH_ENGULFING", evidence="Engulfing bar closed")
    ))
    fake_klines = [
        {"openTime": 1700000000000 + i * 900000, "open": "10.0", "high": "10.5", "low": "9.5", "close": "10.0", "volume": "100"}
        for i in range(60)
    ]
    mocker.patch.object(orch.client, "get_klines", return_value=fake_klines)
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": 1700000000000
    })
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.client, "set_leverage")
    # Response without avgPrice
    mocker.patch.object(orch.client, "place_order", return_value={
        "orderId": "wl_ord_2", "status": "SUBMITTED"
    })
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[])

    res = orch.run_cycle(dry_run=False)

    assert res["status"] == "WATCHLIST_EXECUTED"
    cycle_res = res["cycle_results"][0]
    assert cycle_res["avg_fill_price"] is None
    assert cycle_res["slippage"] is None
    assert cycle_res["slippage_pct"] is None
    assert cycle_res["fill_provenance"] == "PENDING_RECONCILIATION"
    assert cycle_res["status"] == "SUBMITTED"


def test_watchlist_anti_reentry_vetoes_duplicate_symbol_in_same_session(mocker):
    """
    Watchlist parity: symbol already executed in current session must be vetoed.
    """
    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"
    session.executed_symbols = ["WL-COIN"]  # Already executed

    orch.watchlist.add_candidate(
        symbol="WL-COIN",
        current_price=10.0,
        conviction_score=85,
        playbook="PUMP_EXHAUSTION",
        direction="SHORT",
        client=orch.client,
        session_id=session.session_id,
        atr=0.1,
        target_rr=2.0
    )

    mocker.patch.object(orch.client, "get_contracts", return_value=[{
        "symbol": "WL-COIN", "quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20
    }])
    mocker.patch.object(orch.watchlist, "check_deterministic_reversal", return_value=(
        False, None, ReversalTriggerResult(triggered=True, pattern="BEARISH_ENGULFING", evidence="Engulfing bar closed")
    ))
    fake_klines = [
        {"openTime": 1700000000000 + i * 900000, "open": "10.0", "high": "10.5", "low": "9.5", "close": "10.0", "volume": "100"}
        for i in range(60)
    ]
    mocker.patch.object(orch.client, "get_klines", return_value=fake_klines)
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.99", "100"]],
        "asks": [["10.01", "100"]],
        "T": 1700000000000
    })
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mock_place_order = mocker.patch.object(orch.client, "place_order")
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[])

    res = orch.run_cycle(dry_run=False)

    mock_place_order.assert_not_called()
    assert orch.watchlist.get_entry("WL-COIN") is None or res.get("status") != "WATCHLIST_EXECUTED"


def test_watchlist_spread_blowout_vetoes_order(mocker):
    """
    Watchlist parity: when spread at execution exceeds max_spread_pct (0.35%),
    order must be vetoed.
    """
    config = AppConfig(api_key="mock", secret_key="mock", max_spread_pct=0.35)
    orch = SessionOrchestrator(config)
    session = orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)
    session.status = "ACTIVE_SEARCHING"

    orch.watchlist.add_candidate(
        symbol="WL-COIN",
        current_price=10.0,
        conviction_score=85,
        playbook="PUMP_EXHAUSTION",
        direction="SHORT",
        client=orch.client,
        session_id=session.session_id,
        atr=0.1,
        target_rr=2.0
    )

    mocker.patch.object(orch.client, "get_contracts", return_value=[{
        "symbol": "WL-COIN", "quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20
    }])
    mocker.patch.object(orch.watchlist, "check_deterministic_reversal", return_value=(
        False, None, ReversalTriggerResult(triggered=True, pattern="BEARISH_ENGULFING", evidence="Engulfing bar closed")
    ))
    fake_klines = [
        {"openTime": 1700000000000 + i * 900000, "open": "10.0", "high": "10.5", "low": "9.5", "close": "10.0", "volume": "100"}
        for i in range(60)
    ]
    mocker.patch.object(orch.client, "get_klines", return_value=fake_klines)
    # Spread is (10.05 - 9.95) / 9.95 = 1.005% > 0.35%
    mocker.patch.object(orch.client, "get_depth", return_value={
        "bids": [["9.95", "100"]],
        "asks": [["10.05", "100"]],
        "T": 1700000000000
    })
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mock_place_order = mocker.patch.object(orch.client, "place_order")
    mocker.patch.object(orch.scanner, "scan_universe", return_value=[])

    res = orch.run_cycle(dry_run=False)

    # Order must NOT be placed due to spread blowout
    mock_place_order.assert_not_called()
    assert res.get("status") != "WATCHLIST_EXECUTED"


