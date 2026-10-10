import pytest
from scripts.shadow_replay_validator import (
    ShadowReplayValidator,
    ReplayTradeResult,
    calculate_experiment_metrics,
    calibrate_confidence_buckets
)


def test_calculate_experiment_metrics_standard():
    """
    Fase 3 Acceptance Test:
    Validates required metrics calculation:
    - Net expectancy in R
    - Profit factor
    - Max drawdown in R
    - Full cost drag (fee + funding + slippage)
    - MAE / MFE
    """
    sample_trades = [
        ReplayTradeResult(
            symbol="BTC-USDT",
            playbook="PUMP_EXHAUSTION",
            direction="SHORT",
            realized_r=2.0,
            holding_time_s=1800,
            fee=0.20,
            funding_fee=-0.02,
            slippage_pct=0.04,
            mae_pct=0.45,
            mfe_pct=2.10,
            ai_confidence=85.0
        ),
        ReplayTradeResult(
            symbol="ETH-USDT",
            playbook="PUMP_EXHAUSTION",
            direction="SHORT",
            realized_r=-1.0,
            holding_time_s=600,
            fee=0.20,
            funding_fee=0.01,
            slippage_pct=0.05,
            mae_pct=1.20,
            mfe_pct=0.10,
            ai_confidence=75.0
        ),
        ReplayTradeResult(
            symbol="SOL-USDT",
            playbook="SUPPORT_PULLBACK",
            direction="LONG",
            realized_r=2.5,
            holding_time_s=2400,
            fee=0.20,
            funding_fee=0.0,
            slippage_pct=0.03,
            mae_pct=0.30,
            mfe_pct=2.60,
            ai_confidence=90.0
        ),
        ReplayTradeResult(
            symbol="DOGE-USDT",
            playbook="BREAKDOWN_RETEST",
            direction="SHORT",
            realized_r=-1.0,
            holding_time_s=900,
            fee=0.20,
            funding_fee=0.02,
            slippage_pct=0.05,
            mae_pct=1.15,
            mfe_pct=0.25,
            ai_confidence=65.0
        ),
    ]

    metrics = calculate_experiment_metrics(sample_trades)

    # 4 trades: 2 wins (+2.0R, +2.5R = +4.5R), 2 losses (-1.0R, -1.0R = -2.0R)
    # Net R = +2.5R over 4 trades -> Expectancy = 2.5 / 4 = +0.625 R per trade
    assert metrics["total_trades"] == 4
    assert metrics["win_rate"] == 0.50
    assert metrics["net_expectancy_r"] == pytest.approx(0.625, abs=1e-3)
    assert metrics["profit_factor"] == pytest.approx(4.5 / 2.0, abs=1e-3)
    assert metrics["max_drawdown_r"] >= 1.0
    assert metrics["total_fee"] == pytest.approx(0.80, abs=1e-3)
    assert metrics["avg_mae_pct"] == pytest.approx((0.45 + 1.20 + 0.30 + 1.15) / 4, abs=1e-3)
    assert metrics["avg_mfe_pct"] == pytest.approx((2.10 + 0.10 + 2.60 + 0.25) / 4, abs=1e-3)


def test_calibrate_confidence_buckets():
    """
    Fase 3 Acceptance Test:
    Verifies that AI confidence is bucketed and calibrated against actual win rate
    to test whether confidence corresponds to empirical probability.
    """
    trades = [
        ReplayTradeResult("A", "PE", "SHORT", 2.0, 100, 0, 0, 0, 0, 0, ai_confidence=92.0),
        ReplayTradeResult("B", "PE", "SHORT", 2.0, 100, 0, 0, 0, 0, 0, ai_confidence=95.0),
        ReplayTradeResult("C", "PE", "SHORT", -1.0, 100, 0, 0, 0, 0, 0, ai_confidence=72.0),
        ReplayTradeResult("D", "PE", "SHORT", -1.0, 100, 0, 0, 0, 0, 0, ai_confidence=78.0),
    ]

    buckets = calibrate_confidence_buckets(trades)
    # Bucket [90, 100] has 2 trades, both wins (100% win rate)
    assert buckets["90-100"]["count"] == 2
    assert buckets["90-100"]["win_rate"] == 1.0

    # Bucket [70, 80) has 2 trades, both losses (0% win rate)
    assert buckets["70-80"]["count"] == 2
    assert buckets["70-80"]["win_rate"] == 0.0


def test_shadow_replay_validator_comparison_pipeline():
    """
    Fase 3 Acceptance Test:
    ShadowReplayValidator compares deterministic baseline (no LLM) vs LLM pipeline.
    """
    validator = ShadowReplayValidator()
    report = validator.run_synthetic_shadow_test()

    assert "deterministic_baseline" in report
    assert "llm_pipeline" in report
    assert "comparison" in report
    assert "stratification_by_playbook" in report
    assert "stratification_by_direction" in report
