"""
P1-2 extension: structured invalidation-contradiction gate.

Evidence that motivated this (falsification replay of session bx_sess_1791579205_ab6bff):
4 of 13 executed entries named their own invalidation risk in `risk_factors` and were
still executed. Example (JEANPHIL-USDT, LONG): "stop-run risk below EMA50 (0.01049)".
A repo-wide search found ZERO production code reading `risk_factors` as a gate.

Design (per review guidance — NOT keyword matching over free text):
the deep evaluation must answer structured questions explicitly, and the gate acts on
those answers. An ENTER is authorized only when there is no invalidation risk, or when a
present invalidation risk has been explicitly rebutted.

Fail-closed: an absent or unparseable answer is treated as UNKNOWN, which blocks ENTER.
"""
import pytest

from ai_evaluator import (
    AIEvaluationResult,
    apply_invalidation_gate,
    build_structured_deep_prompt,
    normalize_ai_payload,
)


def _enter(decision="ENTER_SHORT", present=None, rebuttal="", **over):
    kw = dict(
        symbol="X-USDT",
        decision=decision,
        confidence=75,
        risk_factors="",
        is_valid=True,
    )
    kw.update(over)
    res = AIEvaluationResult(**kw)
    res.invalidation_risk_present = present
    res.invalidation_rebuttal = rebuttal
    return res


# ---------------------------------------------------------------------------
# Gate behaviour
# ---------------------------------------------------------------------------

def test_enter_downgraded_when_invalidation_unrebutted():
    """The exact JEANPHIL pattern: risk named, no rebuttal -> must not execute."""
    res = _enter(present=True, rebuttal="", risk_factors="stop-run risk below EMA50")
    final, reason = apply_invalidation_gate(res)
    assert final == "WAIT"
    assert reason


def test_enter_downgraded_when_invalidation_answer_missing():
    """Fail-closed: an unparseable/absent answer cannot authorize an entry."""
    res = _enter(present=None, rebuttal="")
    final, reason = apply_invalidation_gate(res)
    assert final == "WAIT"
    assert reason


def test_enter_allowed_when_no_invalidation_risk():
    res = _enter(present=False, rebuttal="")
    final, reason = apply_invalidation_gate(res)
    assert final == "ENTER_SHORT"
    assert reason is None


def test_enter_allowed_when_invalidation_explicitly_rebutted():
    res = _enter(
        present=True,
        rebuttal="EMA50 reclaimed on the 15m close and the stop sits below the reclaimed level",
    )
    final, reason = apply_invalidation_gate(res)
    assert final == "ENTER_SHORT"
    assert reason is None


@pytest.mark.parametrize("placeholder", ["", " ", "-", "n/a", "N/A", "none", "None", "no", "null", "unknown", "tbd", "??"])
def test_placeholder_rebuttal_is_not_a_rebuttal(placeholder):
    res = _enter(present=True, rebuttal=placeholder)
    final, _ = apply_invalidation_gate(res)
    assert final == "WAIT"


def test_short_placeholder_rebuttal_is_not_substantive():
    res = _enter(present=True, rebuttal="no risk")
    final, _ = apply_invalidation_gate(res)
    assert final == "WAIT"


def test_long_entry_also_gated():
    res = _enter(decision="ENTER_LONG", present=True, rebuttal="")
    final, _ = apply_invalidation_gate(res)
    assert final == "WAIT"


def test_non_enter_decisions_are_untouched():
    for dec in ("WAIT", "SKIP"):
        res = _enter(decision=dec, present=True, rebuttal="")
        final, reason = apply_invalidation_gate(res)
        assert final == dec
        assert reason is None


def test_invalid_result_is_not_upgraded_or_changed():
    res = _enter(present=False, rebuttal="", is_valid=False, decision="SKIP")
    final, _ = apply_invalidation_gate(res)
    assert final == "SKIP"


# ---------------------------------------------------------------------------
# Parsing of the structured answer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (True, True), (False, False),
    ("yes", True), ("YES", True), ("true", True), ("y", True), ("1", True),
    ("no", False), ("false", False), ("n", False), ("0", False),
    (1, True), (0, False),
])
def test_invalidation_flag_parses_explicit_answers(raw, expected):
    norm = normalize_ai_payload({"decision": "ENTER_SHORT", "confidence": 75,
                                "invalidation_risk_present": raw})
    assert norm["invalidation_risk_present"] is expected


@pytest.mark.parametrize("raw", [None, "", "maybe", "unclear", "unknown", "perhaps"])
def test_invalidation_flag_unknown_stays_unknown(raw):
    payload = {"decision": "ENTER_SHORT", "confidence": 75}
    if raw is not None:
        payload["invalidation_risk_present"] = raw
    norm = normalize_ai_payload(payload)
    assert norm["invalidation_risk_present"] is None


def test_normalize_keeps_rebuttal_text():
    norm = normalize_ai_payload({
        "decision": "ENTER_SHORT", "confidence": 75,
        "invalidation_risk_present": "yes",
        "invalidation_risk_detail": "stop-run risk below EMA50",
        "invalidation_rebuttal": "EMA50 reclaimed on the 15m close",
    })
    assert norm["invalidation_risk_detail"] == "stop-run risk below EMA50"
    assert norm["invalidation_rebuttal"] == "EMA50 reclaimed on the 15m close"


# ---------------------------------------------------------------------------
# Prompt must force the model to be explicit
# ---------------------------------------------------------------------------

def test_deep_prompt_asks_the_structured_questions():
    prompt = build_structured_deep_prompt({"symbol": "X-USDT", "price": 1.0}, direction="SHORT")
    assert "invalidation_risk_present" in prompt
    assert "invalidation_rebuttal" in prompt
    assert "invalidation_risk_detail" in prompt


def test_deep_prompt_requires_rebuttal_for_entry():
    prompt = build_structured_deep_prompt({"symbol": "X-USDT", "price": 1.0}, direction="SHORT")
    lowered = prompt.lower()
    assert "rebuttal" in lowered
    assert "wait" in lowered


# ---------------------------------------------------------------------------
# Orchestrator Integration Tests
# ---------------------------------------------------------------------------

def test_orchestrator_cycle_downgrades_unrebutted_invalidation_to_wait(mocker):
    from config import AppConfig
    from orchestrator import SessionOrchestrator
    from scanner import CandidatePair

    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)

    cand = CandidatePair(
        symbol="JEANPHIL-USDT",
        last_price=0.0108,
        price_change_percent=15.0,
        volume_24h_usdt=500000.0,
        bid1=0.01079,
        ask1=0.01081,
        spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxLongLeverage": 20, "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch.object(orch.client, "get_depth", return_value={"bids": [["0.01079", "1000"]], "asks": [["0.01081", "1000"]], "T": 1000})
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.0001, "atr_to_friction": 8.0, "atr": 0.0005})

    # Mock raw HTTP response from AI gateway with unrebutted invalidation risk (JEANPHIL pattern)
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": (
                    '{"symbol": "JEANPHIL-USDT", "decision": "ENTER_LONG", "confidence": 76, '
                    '"setup_type": "SUPPORT_PULLBACK", "key_evidence": "Support hold", '
                    '"risk_factors": "stop-run risk below EMA50", '
                    '"invalidation_risk_present": true, '
                    '"invalidation_risk_detail": "stop-run risk below EMA50", '
                    '"invalidation_rebuttal": ""}'
                )
            }
        }],
        "usage": {"total_tokens": 200}
    }
    mocker.patch.object(orch.ai.client, "post", return_value=mock_resp)

    res = orch.run_cycle(dry_run=True)

    # 1. Quota must NOT be filled (no trade executed!)
    assert orch.current_session.filled_count == 0

    # 2. Candidate must be downgraded to WAIT and routed to watchlist
    wl_entries = orch.watchlist.get_all_entries()
    assert any(e.symbol == "JEANPHIL-USDT" for e in wl_entries)

    # 3. Cycle result must reflect WAIT with gate reason
    assert len(res["evaluations"]) == 1
    cr = res["evaluations"][0]
    assert cr["ai_decision"] == "WAIT"
    assert "INVALIDATION_GATE" in cr["ai_evidence"]
    assert cr.get("client_order_id") is None


def test_orchestrator_cycle_allows_rebutted_invalidation(mocker):
    from config import AppConfig
    from orchestrator import SessionOrchestrator
    from scanner import CandidatePair

    config = AppConfig(api_key="mock", secret_key="mock")
    orch = SessionOrchestrator(config)
    orch.start_session(margin_per_pos=5.0, leverage=20, quota=2)

    cand = CandidatePair(
        symbol="VALID-COIN",
        last_price=1.0,
        price_change_percent=12.0,
        volume_24h_usdt=500000.0,
        bid1=0.999,
        ask1=1.001,
        spread_percent=0.1,
        contract_info={"quantityPrecision": 0, "tradeMinQuantity": "1", "tradeMinUSDT": "5.0", "maxShortLeverage": 20}
    )

    mocker.patch.object(orch.scanner, "scan_universe", return_value=[cand])
    mocker.patch.object(orch.scanner, "get_occupied_symbols", return_value=set())
    mocker.patch.object(orch.client, "get_klines", return_value=[])
    mocker.patch.object(orch.client, "get_depth", return_value={"bids": [["0.999", "1000"]], "asks": [["1.001", "1000"]], "T": 1000})
    mocker.patch("orchestrator.build_candidate_features", return_value={"fresh": True, "spread_pct": 0.1, "funding_rate": 0.0001, "atr_to_friction": 8.0, "atr": 0.05})

    # Mock raw HTTP response with valid explicit rebuttal
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": (
                    '{"symbol": "VALID-COIN", "decision": "ENTER_SHORT", "confidence": 80, '
                    '"setup_type": "PUMP_EXHAUSTION", "key_evidence": "Upper wick rejection confirmed", '
                    '"risk_factors": "overhead resistance", '
                    '"invalidation_risk_present": true, '
                    '"invalidation_risk_detail": "overhead resistance", '
                    '"invalidation_rebuttal": "rejection wick on 15m confirmed resistance held firmly"}'
                )
            }
        }],
        "usage": {"total_tokens": 200}
    }
    mocker.patch.object(orch.ai.client, "post", return_value=mock_resp)

    res = orch.run_cycle(dry_run=True)

    # Filled count must increase (trade executed in dry_run)
    assert orch.current_session.filled_count == 1
    cr = res["evaluations"][0]
    assert cr["ai_decision"] == "ENTER_SHORT"
    assert cr["dry_run"] is True
    assert cr.get("client_order_id") is not None

