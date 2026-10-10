"""
Fase 3 acceptance tests.

These tests exercise the METRIC MATH and the fail-closed dataset handling only.
They intentionally do NOT contain "baseline vs LLM" trade outcomes: fabricated
outcomes must never be usable as experiment results. Sample inputs below are
minimal math fixtures, not replay findings.
"""
import json
import pytest

from scripts.shadow_replay_validator import (
    ReplayTradeResult,
    ReplayDatasetError,
    calculate_experiment_metrics,
    calibrate_confidence_buckets,
    parse_replay_records,
    load_replay_dataset,
    run_replay_report,
)


def _sample_trades():
    return [
        ReplayTradeResult("A-USDT", "PUMP_EXHAUSTION", "SHORT", 2.0, 1800, 0.20, -0.02, 0.04, 0.45, 2.10, 85.0),
        ReplayTradeResult("B-USDT", "PUMP_EXHAUSTION", "SHORT", -1.0, 600, 0.20, 0.01, 0.05, 1.20, 0.10, 75.0),
        ReplayTradeResult("C-USDT", "SUPPORT_PULLBACK", "LONG", 2.5, 2400, 0.20, 0.0, 0.03, 0.30, 2.60, 90.0),
        ReplayTradeResult("D-USDT", "BREAKDOWN_RETEST", "SHORT", -1.0, 900, 0.20, 0.02, 0.05, 1.15, 0.25, 65.0),
    ]


def test_calculate_experiment_metrics_standard():
    """
    Validates required metric math: net expectancy in R, profit factor, max
    drawdown in R, cost sums, and MAE/MFE averages.
    """
    metrics = calculate_experiment_metrics(_sample_trades())

    # 2 wins (+2.0R, +2.5R = +4.5R), 2 losses (-1.0R, -1.0R = -2.0R) -> +2.5R over 4
    assert metrics["total_trades"] == 4
    assert metrics["win_rate"] == 0.50
    assert metrics["net_expectancy_r"] == pytest.approx(0.625, abs=1e-3)
    assert metrics["profit_factor"] == pytest.approx(4.5 / 2.0, abs=1e-3)
    assert metrics["max_drawdown_r"] >= 1.0
    assert metrics["total_fee"] == pytest.approx(0.80, abs=1e-3)
    assert metrics["avg_mae_pct"] == pytest.approx((0.45 + 1.20 + 0.30 + 1.15) / 4, abs=1e-3)
    assert metrics["avg_mfe_pct"] == pytest.approx((2.10 + 0.10 + 2.60 + 0.25) / 4, abs=1e-3)


def test_empty_metrics_are_zeroed():
    metrics = calculate_experiment_metrics([])
    assert metrics["total_trades"] == 0
    assert metrics["net_expectancy_r"] == 0.0
    assert metrics["profit_factor"] == 0.0


def test_calibrate_confidence_buckets():
    """Confidence buckets must be calibrated against realized outcomes, not assumed."""
    trades = [
        ReplayTradeResult("A", "PE", "SHORT", 2.0, 100, ai_confidence=92.0),
        ReplayTradeResult("B", "PE", "SHORT", 2.0, 100, ai_confidence=95.0),
        ReplayTradeResult("C", "PE", "SHORT", -1.0, 100, ai_confidence=72.0),
        ReplayTradeResult("D", "PE", "SHORT", -1.0, 100, ai_confidence=78.0),
    ]
    buckets = calibrate_confidence_buckets(trades)
    assert buckets["90-100"]["count"] == 2
    assert buckets["90-100"]["win_rate"] == 1.0
    assert buckets["70-80"]["count"] == 2
    assert buckets["70-80"]["win_rate"] == 0.0


def test_parse_replay_records_rejects_missing_required_fields():
    """Fail-closed: records without the required provenance fields are rejected."""
    with pytest.raises(ReplayDatasetError):
        parse_replay_records([{"symbol": "X-USDT", "playbook": "PE", "direction": "SHORT"}])


def test_parse_replay_records_rejects_unknown_direction():
    with pytest.raises(ReplayDatasetError):
        parse_replay_records([{
            "symbol": "X-USDT", "playbook": "PE", "direction": "SIDEWAYS", "realized_r": 1.0,
        }])


def test_parse_replay_records_rejects_non_numeric_values():
    with pytest.raises(ReplayDatasetError):
        parse_replay_records([{
            "symbol": "X-USDT", "playbook": "PE", "direction": "SHORT", "realized_r": "profit",
        }])


def test_load_replay_dataset_fails_closed_when_missing(tmp_path):
    """No dataset means no results: never fabricate a report from thin air."""
    with pytest.raises(ReplayDatasetError):
        load_replay_dataset(str(tmp_path / "does-not-exist.json"))


def test_load_replay_dataset_round_trip(tmp_path):
    path = tmp_path / "replay.json"
    path.write_text(json.dumps({"trades": [{
        "symbol": "X-USDT", "playbook": "PUMP_EXHAUSTION", "direction": "SHORT",
        "realized_r": 2.0, "holding_time_s": 1200, "fee": 0.1, "funding_fee": 0.0,
        "slippage_pct": 0.03, "mae_pct": 0.4, "mfe_pct": 2.2, "ai_confidence": 88.0,
        "is_fallback": False, "execution_path": "DIRECT",
        "quote_ts": 1, "entry_ts": 2, "exit_ts": 3, "exit_reason": "TP",
    }]}), encoding="utf-8")

    trades = load_replay_dataset(str(path))
    assert len(trades) == 1
    assert trades[0].execution_path == "DIRECT"
    assert trades[0].exit_reason == "TP"


def test_run_replay_report_stratifies_execution_path_and_fallback():
    trades = parse_replay_records([
        {"symbol": "X-USDT", "playbook": "PE", "direction": "SHORT", "realized_r": 2.0, "execution_path": "DIRECT"},
        {"symbol": "Y-USDT", "playbook": "PE", "direction": "LONG", "realized_r": -1.0,
         "execution_path": "WATCHLIST", "is_fallback": True},
    ])
    report = run_replay_report(trades)
    assert report["overall"]["total_trades"] == 2
    assert set(report["stratification_by_execution_path"]) == {"DIRECT", "WATCHLIST"}
    assert report["stratification_by_fallback"]["FALLBACK"]["total_trades"] == 1


def test_run_replay_report_refuses_empty_dataset():
    with pytest.raises(ReplayDatasetError):
        run_replay_report([])


def test_no_synthetic_result_path_remains():
    """
    Guard: the removed synthetic comparison must not be reintroduced. If a
    synthetic entry point exists again, fabricated numbers can leak into reports.
    """
    import scripts.shadow_replay_validator as module
    assert not hasattr(module, "ShadowReplayValidator")
    assert not hasattr(module, "run_synthetic_shadow_test")
